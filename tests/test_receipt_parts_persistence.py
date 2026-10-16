"""Constraints of photos, parses, issues, edits and messages, proven through the Unit of Work."""

import pytest

from src.database.dto.edit import NewReceiptEditDTO
from src.database.dto.issue import NewReceiptIssueDTO
from src.database.dto.message import NewReceiptMessageDTO
from src.database.dto.parse import NewReceiptParseDTO
from src.database.dto.photo import NewReceiptPhotoDTO
from src.exception import CheckViolationError, UniqueViolationError
from tests.helpers import NOW, add_parsed_receipt, add_receipt, add_user


def photo(receipt_id: int, user_id: int = 1, **fields) -> NewReceiptPhotoDTO:
    return NewReceiptPhotoDTO(
        receipt_id=receipt_id,
        user_id=user_id,
        received_at=NOW,
        **({"path": "2026/10/a.jpg"} | fields),
    )


async def test_photos_round_trip_as_dtos(make_uow):
    await add_user(make_uow)
    receipt = await add_receipt(make_uow)
    async with make_uow() as uow:
        added = await uow.photos.add(photo(receipt.id, telegram_file_unique_id="AQADabc"))
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.photos.get(added.id) == added
    assert (added.path, added.telegram_file_unique_id, added.position) == (
        "2026/10/a.jpg",
        "AQADabc",
        0,
    )


async def test_same_telegram_file_is_rejected_for_the_same_user(make_uow):
    await add_user(make_uow)
    receipt = await add_receipt(make_uow)
    async with make_uow() as uow:
        await uow.photos.add(photo(receipt.id, telegram_file_unique_id="AQADabc"))
        await uow.commit()

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow.photos.add(photo(receipt.id, telegram_file_unique_id="AQADabc"))


async def test_same_telegram_file_is_allowed_for_another_user(make_uow):
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    first = await add_receipt(make_uow, user_id=1)
    second = await add_receipt(make_uow, user_id=2)
    async with make_uow() as uow:
        await uow.photos.add(photo(first.id, 1, telegram_file_unique_id="AQADabc"))
        await uow.photos.add(photo(second.id, 2, telegram_file_unique_id="AQADabc"))
        await uow.commit()


async def test_photos_without_a_telegram_id_never_collide(make_uow):
    await add_user(make_uow)
    receipt = await add_receipt(make_uow)
    async with make_uow() as uow:
        one = await uow.photos.add(photo(receipt.id, drive_file_id="d1"))
        two = await uow.photos.add(photo(receipt.id, drive_file_id="d2"))
        await uow.commit()
    assert one.telegram_file_unique_id is None
    assert two.telegram_file_unique_id is None


async def test_photo_needs_a_stored_path_or_a_drive_file(make_uow):
    await add_user(make_uow)
    receipt = await add_receipt(make_uow)
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.photos.add(photo(receipt.id, path=None))


async def test_parses_round_trip_as_dtos(make_uow):
    _, parse = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        assert await uow.parses.get(parse.id) == parse
    assert (parse.status, parse.photo_ids, parse.raw_output) == ("ok", [], None)


async def test_deleting_the_current_parse_clears_the_pointer_and_keeps_the_receipt(make_uow):
    receipt, parse = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        await uow.receipts.set_current_parse(receipt.id, parse.id)
        await uow.commit()
    async with make_uow() as uow:
        assert (await uow.receipts.get(receipt.id)).current_parse_id == parse.id

    async with make_uow() as uow:
        await uow.parses.delete(parse.id)
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.parses.get(parse.id) is None
        kept = await uow.receipts.get(receipt.id)
    assert kept is not None
    assert kept.current_parse_id is None


async def test_unknown_parse_status_is_rejected(make_uow):
    await add_user(make_uow)
    receipt = await add_receipt(make_uow)
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.parses.add(
                NewReceiptParseDTO(
                    receipt_id=receipt.id, status="pending", parser_version="test", photo_ids=[]
                )
            )


def issue(parse_id: int, **fields) -> NewReceiptIssueDTO:
    return NewReceiptIssueDTO(
        parse_id=parse_id,
        **(
            {
                "source": "workflow",
                "issue_type": "missing_total",
                "severity": "medium",
                "message": "No total",
            }
            | fields
        ),
    )


async def test_issues_round_trip_as_dtos(make_uow):
    _, parse = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        added = await uow.issues.add(issue(parse.id, field="totals.total"))
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.issues.get(added.id) == added
    assert (added.resolution, added.resolved_at, added.field) == ("open", None, "totals.total")


@pytest.mark.parametrize(
    "fields",
    [{"source": "user"}, {"severity": "critical"}, {"resolution": "ignored"}],
    ids=["source", "severity", "resolution"],
)
async def test_unknown_issue_values_are_rejected(make_uow, fields):
    _, parse = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.issues.add(issue(parse.id, **fields))


async def test_edits_round_trip_as_dtos(make_uow):
    receipt, _ = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        on_receipt = await uow.edits.add(
            NewReceiptEditDTO(receipt_id=receipt.id, target="receipt", field="total", value="9.50")
        )
        on_item = await uow.edits.add(
            NewReceiptEditDTO(
                receipt_id=receipt.id,
                target="item",
                item_ref="lidl::pan#0",
                field="quantity",
                value={"amount": 2},
            )
        )
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.edits.get(on_receipt.id) == on_receipt
        assert await uow.edits.get(on_item.id) == on_item
    assert (on_receipt.value, on_item.value) == ("9.50", {"amount": 2})


async def test_unknown_edit_target_is_rejected(make_uow):
    receipt, _ = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.edits.add(
                NewReceiptEditDTO(receipt_id=receipt.id, target="store", field="name", value="x")
            )


@pytest.mark.parametrize(
    ("target", "item_ref"),
    [("item", None), ("receipt", "lidl::pan#0")],
    ids=["item-without-ref", "receipt-with-ref"],
)
async def test_item_ref_goes_with_item_edits_only(make_uow, target, item_ref):
    receipt, _ = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.edits.add(
                NewReceiptEditDTO(
                    receipt_id=receipt.id,
                    target=target,
                    item_ref=item_ref,
                    field="quantity",
                    value=1,
                )
            )


async def test_messages_round_trip_and_are_unique_per_user_and_message_id(make_uow):
    receipt, _ = await add_parsed_receipt(make_uow)
    async with make_uow() as uow:
        added = await uow.messages.add(
            NewReceiptMessageDTO(user_id=1, message_id=77, receipt_id=receipt.id)
        )
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.messages.get(1, 77) == added
        assert await uow.messages.get(1, 78) is None

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow.messages.add(
                NewReceiptMessageDTO(user_id=1, message_id=77, receipt_id=receipt.id)
            )
