"""The n8n import end to end on real Postgres: a small export (payments 3, 4 and 6)."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from src.integration.storage import LocalPhotoStorage, StorageError
from src.services.expense import ExpenseService
from src.services.receipt import ReceiptService
from src.services.results import NewPhoto, ReceiptCard
from src.tools.import_n8n import ImportAborted, ImportReport, import_and_print, run_import
from tests.domain.builders import WHEN
from tests.helpers import MakeUow, add_allowed_user
from tests.stubs import StubReceiptParser, fixture, output_of

EXPORT = Path(__file__).parent.parent / "fixtures" / "n8n_export"
USER = 1


@pytest.fixture
async def user(make_uow: MakeUow) -> int:
    await add_allowed_user(make_uow, USER)
    return USER


@pytest.fixture
def export(tmp_path: Path) -> Path:
    """A private copy of the fixture export, so a test may edit it."""
    target = tmp_path / "export"
    shutil.copytree(EXPORT, target)
    return target


def edit_payment(export: Path, payment_id: int, **columns) -> None:
    path = export / "receipt_payments.json"
    rows = json.loads(path.read_text())
    next(row for row in rows if row["id"] == payment_id).update(columns)
    path.write_text(json.dumps(rows))


def receipt_service(make_uow: MakeUow, tmp_storage: LocalPhotoStorage, parser=None):
    return ReceiptService(make_uow, tmp_storage, parser or StubReceiptParser())


async def imported_ids(make_uow: MakeUow) -> dict[int, int]:
    """Receipt ids by n8n payment id."""
    ids = {}
    async with make_uow() as uow:
        for payment_id in (3, 4, 6):
            receipt = await uow.receipts.find_by_source_ref(USER, f"n8n:{payment_id}")
            if receipt is not None:
                assert receipt.id is not None
                ids[payment_id] = receipt.id
    return ids


async def test_one_run_writes_catalog_receipts_and_expenses(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int
):
    report = await run_import(export, user, make_uow, tmp_storage)

    assert (report.payees_added, report.payees_skipped) == (2, 0)
    assert (report.products_added, report.products_skipped) == (10, 0)
    assert (report.receipts_added, report.receipts_skipped) == (3, 0)
    assert (report.expenses_added, report.expenses_skipped) == (2, 0)

    async with make_uow() as uow:
        catalog = await uow.catalog.get(user)
    assert set(catalog.payees) == {"consum", "ametller-origen"}
    assert catalog.payees["consum"].legal_name == "CONSUM, S.COOP.V."
    assert catalog.payees["ametller-origen"].tax_id == "B52591359"
    assert len(catalog.products) == 10
    water = catalog.products["consum::aigua-c-g-pelegrino"]
    assert water.name == "San Pellegrino 1L"  # the hand edit wins over the printed reading
    assert water.source_ref is not None and water.source_ref.startswith("n8n:")

    ids = await imported_ids(make_uow)
    service = receipt_service(make_uow, tmp_storage)
    consum, ametller, repeat = [await service.card(user, ids[n]) for n in (3, 4, 6)]
    assert (consum.status, ametller.status, repeat.status) == ("parsed", "parsed", "duplicate")
    assert repeat.duplicate_of is not None and repeat.duplicate_of.receipt_id == ids[3]
    assert repeat.expense_id is None
    assert consum.expense_category == ametller.expense_category == "groceries"
    assert consum.total == Decimal("7.58") and consum.card_last4 == "0848"
    assert consum.item_count == 2 and ametller.item_count == 8

    page = await ExpenseService(make_uow).history(user, 2026, 10)
    expenses = [row for row in page.rows if row.expense_id is not None]
    assert {(r.payee_name, r.amount, str(r.day)) for r in expenses} == {
        ("Consum", Decimal("7.58"), "2026-10-10"),
        ("Ametller Origen", Decimal("50.46"), "2026-10-10"),
    }
    assert page.expense_count == 2
    assert [r.receipt_id for r in page.rows if r.status == "duplicate"] == [ids[6]]


async def test_report_is_empty_on_the_fixture(
    make_uow: MakeUow, export: Path, user: int, tmp_storage: LocalPhotoStorage
):
    report = await run_import(export, user, make_uow, tmp_storage)
    assert report.differences == []
    assert report.lines()[-1] == "no differences from the n8n columns"


async def test_a_second_run_adds_nothing(
    make_uow: MakeUow, export: Path, user: int, tmp_storage: LocalPhotoStorage
):
    await run_import(export, user, make_uow, tmp_storage)
    before = await imported_ids(make_uow)

    report = await run_import(export, user, make_uow, tmp_storage)

    assert (report.payees_added, report.payees_skipped) == (0, 2)
    assert (report.products_added, report.products_skipped) == (0, 10)
    assert (report.receipts_added, report.receipts_skipped) == (0, 3)
    assert (report.expenses_added, report.expenses_skipped) == (0, 2)
    assert report.differences == []
    assert await imported_ids(make_uow) == before


async def test_a_rerun_adds_only_the_new_payment(
    make_uow: MakeUow, export: Path, user: int, tmp_storage: LocalPhotoStorage
):
    full = (export / "receipt_payments.json").read_text()
    rows = json.loads(full)
    (export / "receipt_payments.json").write_text(json.dumps([r for r in rows if r["id"] != 4]))
    first = await run_import(export, user, make_uow, tmp_storage)
    assert first.receipts_added == 2

    (export / "receipt_payments.json").write_text(full)
    second = await run_import(export, user, make_uow, tmp_storage)

    assert (second.receipts_added, second.receipts_skipped) == (1, 2)
    assert (second.expenses_added, second.expenses_skipped) == (1, 1)
    assert set(await imported_ids(make_uow)) == {3, 4, 6}


async def test_the_card_opens_and_there_is_no_stored_photo(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int
):
    await run_import(export, user, make_uow, tmp_storage)
    receipt_id = (await imported_ids(make_uow))[3]
    service = receipt_service(make_uow, tmp_storage)

    card = await service.card(user, receipt_id)
    assert isinstance(card, ReceiptCard) and card.store_name == "Consum"
    with pytest.raises(StorageError):
        await service.photo_bytes(user, receipt_id)
    async with make_uow() as uow:
        photo = (await uow.receipts.get(receipt_id)).photo  # type: ignore[union-attr]
    assert photo.path is None
    assert (photo.drive_file_id, photo.telegram_message_id) == ("drv3", 101)
    assert photo.drive_url == "https://drive.google.com/file/d/drv3/view"


async def test_a_receipt_with_the_same_key_after_the_import_is_a_duplicate(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int
):
    await run_import(export, user, make_uow, tmp_storage)
    original = (await imported_ids(make_uow))[3]
    parser = StubReceiptParser(output_of(fixture("03")["raw"]))
    service = receipt_service(make_uow, tmp_storage, parser)

    saved = await service.save_photo(
        user, b"new photo", NewPhoto(received_at=WHEN, telegram_file_unique_id="again")
    )
    result = await service.parse(user, saved.receipt_id)

    assert result.outcome == "duplicate"
    assert result.duplicate_of is not None and result.duplicate_of.receipt_id == original


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("receiptKey", "consum|other|2026-10-10|7.58", "payment 3 receipt_key: n8n consum|other"),
        (
            "purchasedAt",
            "2026-10-09T18:06:00.000Z",
            "payment 3 purchased_at: n8n 2026-10-09T18:06:00Z, port 2026-10-10T18:06:00Z",
        ),
        ("storeKey", "mercadona", "payment 3 store_key: n8n mercadona, port consum"),
        ("total", 7.59, "payment 3 total: n8n 7.59, port 7.58"),
        ("status", "failed", "payment 3 status: n8n failed, port parsed"),
    ],
)
async def test_the_report_names_the_field_that_differs(
    make_uow: MakeUow,
    export: Path,
    user: int,
    column: str,
    value,
    expected: str,
    tmp_storage: LocalPhotoStorage,
):
    edit_payment(export, 3, **{column: value})

    report = await run_import(export, user, make_uow, tmp_storage)

    [line] = [d for d in report.differences if d.startswith("payment 3 ")]
    assert line.startswith(expected)
    assert expected.split(":")[0].split()[-1] in report.lines()[-1]


async def test_an_unknown_user_writes_nothing(
    make_uow: MakeUow,
    export: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_storage: LocalPhotoStorage,
):
    assert await import_and_print(export, 99, make_uow, tmp_storage) == 1

    assert "no user 99" in capsys.readouterr().err
    async with make_uow() as uow:
        catalog = await uow.catalog.get(99)
        assert not catalog.payees and not catalog.products
        assert await uow.receipts.find_by_source_ref(99, "n8n:3") is None


async def test_a_failing_payment_stops_the_run_and_a_rerun_continues(
    make_uow: MakeUow,
    export: Path,
    user: int,
    capsys: pytest.CaptureFixture[str],
    tmp_storage: LocalPhotoStorage,
):
    edit_payment(export, 4, rawJson="not json")

    with pytest.raises(ImportAborted, match="payment 4"):
        await run_import(export, user, make_uow, tmp_storage)
    assert set(await imported_ids(make_uow)) == {3}  # the payment before it is committed
    assert await import_and_print(export, user, make_uow, tmp_storage) == 1
    assert "payment 4" in capsys.readouterr().err

    edit_payment(
        export,
        4,
        rawJson=next(
            row["rawJson"]
            for row in json.loads((EXPORT / "receipt_payments.json").read_text())
            if row["id"] == 4
        ),
    )
    report = await run_import(export, user, make_uow, tmp_storage)
    assert (report.receipts_added, report.receipts_skipped) == (2, 1)
    assert set(await imported_ids(make_uow)) == {3, 4, 6}


async def test_a_payment_without_raw_json_becomes_a_failed_receipt(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int
):
    edit_payment(
        export,
        4,
        rawJson=None,
        status="failed",
        errorMessage="LLM timeout",
        receiptKey=None,
        purchasedAt=None,
        storeKey=None,
        total=None,
    )

    report = await run_import(export, user, make_uow, tmp_storage)

    assert report.differences == []  # an n8n column left empty is not compared
    card = await receipt_service(make_uow, tmp_storage).card(
        user, (await imported_ids(make_uow))[4]
    )
    assert (card.status, card.error_message, card.expense_id) == ("failed", "LLM timeout", None)


PAYMENT_3_PATH = "2026/10/receipt_2026-10-12_18-28-34_101.jpg"


def put_photo(export: Path, name: str, data: bytes = b"\xff\xd8fake jpeg") -> bytes:
    folder = export / "photos"
    folder.mkdir(exist_ok=True)
    (folder / name).write_bytes(data)
    return data


def stored_files(storage_root: Path) -> dict[str, int]:
    """Relative path -> mtime of every file under the storage root."""
    return {
        str(p.relative_to(storage_root)): p.stat().st_mtime_ns
        for p in storage_root.rglob("*")
        if p.is_file()
    }


async def test_a_photo_file_is_stored_under_the_live_layout(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int
):
    data = put_photo(export, "receipt_2026-10-12_18-28-34_101.jpg")

    report = await run_import(export, user, make_uow, tmp_storage)

    assert report.photos_stored == 1 and report.unmatched_files == []
    assert report.lines()[4] == "photos: 1 stored"
    ids = await imported_ids(make_uow)
    service = receipt_service(make_uow, tmp_storage)
    assert await service.photo_bytes(user, ids[3]) == data
    async with make_uow() as uow:
        photo = (await uow.receipts.get(ids[3])).photo  # type: ignore[union-attr]
    assert photo.path == PAYMENT_3_PATH
    assert (photo.mime_type, photo.size_bytes) == ("image/jpeg", len(data))
    assert (photo.drive_file_id, photo.drive_url) == (
        "drv3",
        "https://drive.google.com/file/d/drv3/view",
    )
    assert await tmp_storage.read(PAYMENT_3_PATH) == data
    with pytest.raises(StorageError):
        await service.photo_bytes(user, ids[4])
    async with make_uow() as uow:
        assert (await uow.receipts.get(ids[4])).photo.path is None  # type: ignore[union-attr]


async def test_a_png_file_gets_its_mime_type_and_extension(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int
):
    put_photo(export, "receipt_2000-01-01_00-00-00_102.PNG", b"png bytes")

    await run_import(export, user, make_uow, tmp_storage)

    ids = await imported_ids(make_uow)
    async with make_uow() as uow:
        photo = (await uow.receipts.get(ids[4])).photo  # type: ignore[union-attr]
    assert photo.mime_type == "image/png"
    assert photo.path is not None and photo.path.endswith("_102.png")
    assert await tmp_storage.read(photo.path) == b"png bytes"


async def test_without_a_photos_folder_nothing_is_stored(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int, tmp_path: Path
):
    report = await run_import(export, user, make_uow, tmp_storage)

    assert report.photos_stored == 0 and report.unmatched_files == []
    assert stored_files(tmp_path / "receipts") == {}


async def test_unmatched_files_are_reported_and_the_run_succeeds(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int, tmp_path: Path
):
    put_photo(export, "receipt_2026-10-12_18-28-34_101.jpg")
    put_photo(export, "receipt_2026-10-01_10-00-00_999.jpg")
    put_photo(export, "receipt_2026-10-01_10-00-00_998.gif")
    put_photo(export, "notes.jpg")

    report = await run_import(export, user, make_uow, tmp_storage)

    assert report.photos_stored == 1
    assert sorted(report.unmatched_files) == [
        "notes.jpg: no message id in the name",
        "receipt_2026-10-01_10-00-00_998.gif: unknown file type",
        "receipt_2026-10-01_10-00-00_999.jpg: no payment",
    ]
    assert report.receipts_added == 3
    assert set(stored_files(tmp_path / "receipts")) == {PAYMENT_3_PATH}
    assert "3 photo file(s) not imported:" in report.lines()


async def test_a_rerun_stores_no_photo_again(
    make_uow: MakeUow, tmp_storage: LocalPhotoStorage, export: Path, user: int, tmp_path: Path
):
    put_photo(export, "receipt_2026-10-12_18-28-34_101.jpg")
    await run_import(export, user, make_uow, tmp_storage)
    before = stored_files(tmp_path / "receipts")

    report = await run_import(export, user, make_uow, tmp_storage)

    assert report.photos_stored == 0
    assert report.receipts_skipped == 3
    assert stored_files(tmp_path / "receipts") == before
    assert report.unmatched_files == [
        "receipt_2026-10-12_18-28-34_101.jpg: payment already imported"
    ]


def test_report_lines_list_the_counts_first():
    report = ImportReport(receipts_added=3, differences=["payment 1 total: n8n 1.00, port 2.00"])
    assert report.lines()[2] == "receipts: 3 added, 0 skipped"
    assert report.lines()[4] == "photos: 0 stored"
    assert report.lines()[-1] == "  payment 1 total: n8n 1.00, port 2.00"
