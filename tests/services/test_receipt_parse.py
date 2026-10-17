"""ReceiptService.parse through the Unit of Work, with a stub parser and tmp photo storage."""

import asyncio
from datetime import datetime
from decimal import Decimal

import pytest

from src.domain.enums import IssueResolution, ReceiptStatus
from src.exception import InvalidReceiptTransition, ReceiptNotFound
from src.integration.llm import LLMError
from src.services import receipt as receipt_module
from src.services.catalog import CatalogService
from src.services.receipt import ReceiptService
from src.services.results import NewPhoto
from tests.helpers import MakeUow, add_allowed_user
from tests.services.test_receipt_service import load
from tests.stubs import StubReceiptParser, fixture, output_of

PAID_WITH_CARD = "03"  # Consum, parsed, no known cards
UNSEEN_CARD = "11"  # card 0048 against a known 0848


@pytest.fixture
def parser() -> StubReceiptParser:
    return StubReceiptParser()


@pytest.fixture
async def service(make_uow: MakeUow, tmp_storage, parser) -> ReceiptService:
    await add_allowed_user(make_uow, 1)
    await add_allowed_user(make_uow, 2, first_name="Bo", username="bo")
    return ReceiptService(make_uow, tmp_storage, parser)


async def intake(
    service: ReceiptService, parser: StubReceiptParser, name: str, *, unique: str, user_id: int = 1
) -> int:
    """Save a photo (its bytes are `unique`) and prepare the stub's answer for it."""
    data = fixture(name)
    received_at = datetime.fromisoformat(data["context"]["received_at"])
    image = unique.encode()
    parser.outputs[image] = output_of(data["raw"])
    card = await service.save_photo(
        user_id,
        image,
        NewPhoto(received_at=received_at, telegram_file_unique_id=unique, mime_type="image/jpeg"),
    )
    return card.receipt_id


async def test_a_parsed_receipt_gets_items_catalog_and_a_parse_row_with_usage(
    service, parser, make_uow
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="p1")

    result = await service.parse(1, receipt_id)

    assert result.outcome == "parsed"
    assert (result.card.status, result.card.store_name) == ("parsed", "Consum")
    assert result.card.item_count == len(fixture(PAID_WITH_CARD)["raw"]["items"]) > 0
    stored = await load(make_uow, receipt_id)
    assert stored.parse.model == "gpt-test"
    assert stored.parse.parser_version
    assert (stored.parse.input_tokens, stored.parse.output_tokens) == (1200, 300)
    assert stored.parse.duration_ms == 2500
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
    assert "consum" in catalog.payees
    assert {i.product_key for i in stored.items} <= set(catalog.products)


async def test_the_summary_issues_are_the_five_most_severe_in_parse_order(service, parser):
    data = fixture(PAID_WITH_CARD)
    severities = ["low", "medium", "high", "low", "high", "medium", "low"]
    data["raw"]["issues"] = [
        {
            "type": "other",
            "severity": severity,
            "field": None,
            "item_name_raw": None,
            "message": f"{severity}-{n}",
        }
        for n, severity in enumerate(severities)
    ]
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="i1")
    parser.outputs[b"i1"] = output_of(data["raw"])

    result = await service.parse(1, receipt_id)

    model_lines = [i.message for i in result.issues if i.message[:3] in ("low", "med", "hig")]
    assert len(result.issues) == 5
    assert model_lines[:4] == ["high-2", "high-4", "medium-1", "medium-5"]


async def test_an_image_that_is_not_a_receipt_has_no_items(service, parser, make_uow):
    data = fixture(PAID_WITH_CARD)
    data["raw"].update(is_receipt=False, items=[], issues=[])
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="n1")
    parser.outputs[b"n1"] = output_of(data["raw"])

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.card.status, result.card.item_count) == (
        "not_receipt",
        "not_receipt",
        0,
    )
    assert (await load(make_uow, receipt_id)).items == []


async def test_a_second_photo_of_the_same_receipt_is_a_duplicate_and_the_first_is_untouched(
    service, parser, make_uow
):
    first = await intake(service, parser, PAID_WITH_CARD, unique="d1")
    second = await intake(service, parser, PAID_WITH_CARD, unique="d2")
    await service.parse(1, first)
    before = await load(make_uow, first)

    result = await service.parse(1, second)

    assert result.outcome == "duplicate"
    assert result.card.status == "duplicate"
    assert result.duplicate_of is not None and result.duplicate_of.receipt_id == first
    assert (await load(make_uow, second)).duplicate_of_id == first
    assert await load(make_uow, first) == before


async def test_a_model_failure_marks_the_receipt_failed_and_keeps_the_photo(
    service, parser, make_uow, tmp_storage
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="f1")
    parser.error = LLMError("model timed out")

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.error, result.card.status) == (
        "failed",
        "model timed out",
        "failed",
    )
    stored = await load(make_uow, receipt_id)
    assert stored.error_message == "model timed out"
    assert await tmp_storage.read(stored.photo.path) == b"f1"


async def test_a_failed_receipt_can_be_parsed_again(service, parser):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="r1")
    parser.error = LLMError("down")
    await service.parse(1, receipt_id)
    parser.error = None

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.error) == ("parsed", None)


async def test_an_unexpected_error_marks_the_receipt_failed_and_is_raised(
    service, parser, make_uow
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="x1")
    parser.error = RuntimeError("bug")

    with pytest.raises(RuntimeError):
        await service.parse(1, receipt_id)

    assert (await load(make_uow, receipt_id)).status == "failed"


async def test_a_receipt_that_is_parsing_or_a_duplicate_refuses_another_parse(
    service, parser, make_uow
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="g1")
    async with make_uow() as uow:  # a parse of another process is in flight
        receipt = await uow.receipts.get(receipt_id)
        receipt.mark_parsing()
        await uow.receipts.save(receipt)
        await uow.commit()

    with pytest.raises(InvalidReceiptTransition):
        await service.parse(1, receipt_id)
    assert parser.events == []

    original = await intake(service, parser, PAID_WITH_CARD, unique="g2")
    await service.parse(1, original)
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
        receipt.status = ReceiptStatus.PENDING
        await uow.receipts.save(receipt)
        await uow.commit()
    parser.outputs[b"g1"] = parser.outputs[b"g2"]
    assert (await service.parse(1, receipt_id)).outcome == "duplicate"
    with pytest.raises(InvalidReceiptTransition):
        await service.parse(1, receipt_id)


async def test_another_users_receipt_is_not_found(service, parser):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="o1")

    with pytest.raises(ReceiptNotFound):
        await service.parse(2, receipt_id)


async def test_two_parses_of_one_user_run_one_after_the_other(service, parser):
    parser.delay = 0.02
    first = await intake(service, parser, PAID_WITH_CARD, unique="s1")
    second = await intake(service, parser, UNSEEN_CARD, unique="s2")

    await asyncio.gather(service.parse(1, first), service.parse(1, second))

    kinds = [kind for kind, _ in parser.events]
    assert kinds == ["start", "end", "start", "end"]


async def test_a_parse_of_user_b_is_not_blocked_by_user_a(service, parser):
    a = await intake(service, parser, PAID_WITH_CARD, unique="a1")
    b = await intake(service, parser, UNSEEN_CARD, unique="b1", user_id=2)
    parser.gates[b"a1"] = gate = asyncio.Event()
    running = asyncio.create_task(service.parse(1, a))
    await asyncio.wait_for(parser.started.wait(), 5)

    result = await asyncio.wait_for(service.parse(2, b), timeout=5)

    assert result.outcome == "parsed"
    assert not running.done()
    gate.set()
    assert (await running).outcome == "parsed"


async def test_normalize_gets_the_cards_of_the_users_earlier_parsed_receipts(service, parser):
    earlier = await intake(service, parser, PAID_WITH_CARD, unique="c1")
    seen = await intake(service, parser, UNSEEN_CARD, unique="c2")
    # The earlier receipt paid with another card ending than the new one.
    raw = fixture(PAID_WITH_CARD)["raw"]
    raw["payment"]["card_last4"] = "0848"
    parser.outputs[b"c1"] = output_of(raw)
    await service.parse(1, earlier)

    result = await service.parse(1, seen)

    unseen = [i for i in result.issues if "0048" in i.message]
    assert unseen, [i.message for i in result.issues]


async def test_a_missing_photo_file_marks_the_receipt_failed_without_calling_the_model(
    service, parser, make_uow, tmp_storage
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="m1")
    path = (await load(make_uow, receipt_id)).photo.path
    (tmp_storage._root / path).unlink()

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.card.status) == ("failed", "failed")
    assert parser.events == []


async def test_a_reading_that_cannot_be_normalized_fails_the_receipt_without_raising(
    service, parser, make_uow
):
    data = fixture(PAID_WITH_CARD)
    data["raw"]["totals"]["total"] = "1E+500"
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="z1")
    parser.outputs[b"z1"] = output_of(data["raw"])

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.card.status) == ("failed", "failed")
    assert (await load(make_uow, receipt_id)).error_message


def test_every_final_status_has_one_outcome():
    from src.domain.enums import ReceiptStatus
    from src.services.receipt import _OUTCOMES

    in_flight = {ReceiptStatus.PENDING, ReceiptStatus.PARSING, ReceiptStatus.FAILED}
    assert set(_OUTCOMES) | in_flight == set(ReceiptStatus)


# --- re-parse ----------------------------------------------------------------------------


async def read_with_version(
    service, parser, monkeypatch, name: str, *, unique: str, version: str = "old"
) -> int:
    """A parsed receipt whose parse was made by an older parser."""
    receipt_id = await intake(service, parser, name, unique=unique)
    with monkeypatch.context() as patch:
        patch.setattr(receipt_module, "PARSER_VERSION", version)
        await service.parse(1, receipt_id)
    return receipt_id


async def test_a_reparse_replaces_the_parse_and_keeps_edits_names_and_resolutions(
    service, parser, make_uow, monkeypatch
):
    receipt_id = await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="e1")
    before = await load(make_uow, receipt_id)
    old_parse_id = before.parse.id
    kept, dropped = before.items[0].product_key, before.items[1].product_key
    layout = next(i for i in before.issues if i.field == "receipt.number")
    await service.resolve_issue(1, receipt_id, layout.id, "confirmed")
    await service.edit_header(1, receipt_id, "total", "9.99")
    await CatalogService(make_uow).rename_product(1, kept, "My water")
    raw = fixture(PAID_WITH_CARD)["raw"]
    raw["items"] = raw["items"][:1]  # the new reading finds one line less
    parser.outputs[b"e1"] = output_of(raw, model="gpt-next")

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.card.status) == ("parsed", "parsed")
    after = await load(make_uow, receipt_id)
    assert after.parse.id == old_parse_id  # one parse row, replaced
    assert (after.parse.parser_version, after.parse.model) == (
        receipt_module.PARSER_VERSION,
        "gpt-next",
    )
    assert after.parser_version != "old"
    assert after.header.total == Decimal("9.99")  # the edit still wins
    assert [i.product_key for i in after.items] == [kept]
    carried = next(i for i in after.issues if i.field == "receipt.number")
    assert carried.resolution is IssueResolution.CONFIRMED and carried.resolved_at is not None
    async with make_uow() as uow:
        products = (await uow.catalog.get(1)).products
    assert products[kept].name == "My water"
    assert dropped not in products  # created by this receipt, no longer used anywhere


async def test_a_reparse_keeps_products_other_receipts_use(service, parser, make_uow, monkeypatch):
    first = await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="k1")
    shared = (await load(make_uow, first)).items[0].product_key
    second = await intake(service, parser, "07", unique="k2")
    raw = fixture("07")["raw"]
    raw["items"][0]["name_raw"] = fixture(PAID_WITH_CARD)["raw"]["items"][0]["name_raw"]
    parser.outputs[b"k2"] = output_of(raw)
    await service.parse(1, second)
    assert shared in {i.product_key for i in (await load(make_uow, second)).items}
    only_first = fixture(PAID_WITH_CARD)["raw"]
    only_first["items"] = []
    parser.outputs[b"k1"] = output_of(only_first)

    await service.parse(1, first)

    async with make_uow() as uow:
        assert shared in (await uow.catalog.get(1)).products


async def test_a_failed_reparse_keeps_the_previous_reading_and_records_the_error(
    service, parser, make_uow, monkeypatch
):
    receipt_id = await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="q1")
    before = await load(make_uow, receipt_id)
    parser.error = LLMError("model timed out")

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.error, result.card.status) == (
        "failed",
        "model timed out",
        "parsed",
    )
    assert result.card.error_message == "model timed out" and result.card.can_reparse
    after = await load(make_uow, receipt_id)
    assert (after.parse, after.header, after.items, after.issues) == (
        before.parse,
        before.header,
        before.items,
        before.issues,
    )
    assert after.error_message == "model timed out"
    assert (await service.card(1, receipt_id)).error_message == "model timed out"


async def test_a_reparse_that_matches_another_receipts_key_becomes_a_duplicate(
    service, parser, make_uow
):
    original = await intake(service, parser, PAID_WITH_CARD, unique="d1")
    await service.parse(1, original)
    other = await intake(service, parser, UNSEEN_CARD, unique="d2")
    await service.parse(1, other)
    parser.outputs[b"d2"] = parser.outputs[b"d1"]

    result = await service.parse(1, other)

    assert (result.outcome, result.card.status) == ("duplicate", "duplicate")
    assert result.duplicate_of.receipt_id == original
    assert not result.card.can_reparse


async def test_a_not_receipt_that_now_reads_as_a_receipt_becomes_parsed(service, parser):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="n1")
    parser.outputs[b"n1"] = output_of({**fixture(PAID_WITH_CARD)["raw"], "is_receipt": False})
    assert (await service.parse(1, receipt_id)).outcome == "not_receipt"
    parser.outputs[b"n1"] = output_of(fixture(PAID_WITH_CARD)["raw"])

    result = await service.parse(1, receipt_id)

    assert (result.outcome, result.card.item_count > 0) == ("parsed", True)


async def test_reparse_candidates_count_failed_and_outdated_receipts(service, parser, monkeypatch):
    await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="c1")
    await read_with_version(service, parser, monkeypatch, UNSEEN_CARD, unique="c2", version="old2")
    current = await intake(service, parser, "07", unique="c3")
    await service.parse(1, current)
    broken = await intake(service, parser, "08", unique="c4")
    parser.error = LLMError("down")
    await service.parse(1, broken)

    summary = await service.reparse_candidates(1)

    assert (summary.failed_count, summary.outdated_count) == (1, 2)
    assert summary.parser_version == receipt_module.PARSER_VERSION
    other = await service.reparse_candidates(2)
    assert (other.failed_count, other.outdated_count) == (0, 0)


async def test_reparse_many_reads_outdated_receipts_in_order_and_counts_the_outcomes(
    service, parser, make_uow, monkeypatch
):
    ids = [
        await read_with_version(service, parser, monkeypatch, name, unique=f"m{n}")
        for n, name in enumerate([PAID_WITH_CARD, UNSEEN_CARD, "07"])
    ]
    parser.events.clear()
    parser.started = asyncio.Event()
    parser.outputs[b"m1"] = output_of(fixture(UNSEEN_CARD)["raw"])
    parser.error = None

    result = await service.reparse_many(1, "outdated")

    assert (result.ok, result.failed) == (3, 0)
    assert [image for kind, image in parser.events if kind == "start"] == [b"m0", b"m1", b"m2"]
    assert (await service.reparse_candidates(1)).outdated_count == 0
    versions = [(await load(make_uow, i)).parser_version for i in ids]
    assert versions == [receipt_module.PARSER_VERSION] * 3


async def test_reparse_many_respects_the_limit_and_the_reason(service, parser, monkeypatch):
    for n, name in enumerate([PAID_WITH_CARD, UNSEEN_CARD, "07"]):
        await read_with_version(service, parser, monkeypatch, name, unique=f"l{n}")

    assert (await service.reparse_many(1, "failed")).model_dump() == {"ok": 0, "failed": 0}
    assert (await service.reparse_many(1, "outdated", limit=2)).model_dump() == {
        "ok": 2,
        "failed": 0,
    }
    assert (await service.reparse_candidates(1)).outdated_count == 1


async def test_reparse_many_counts_failures_and_unexpected_errors_and_goes_on(
    service, parser, caplog, monkeypatch
):
    await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="b0")
    await read_with_version(service, parser, monkeypatch, UNSEEN_CARD, unique="b1")
    await read_with_version(service, parser, monkeypatch, "07", unique="b2")
    original = parser.parse

    async def flaky(image: bytes, media_type: str):
        if image == b"b0":
            raise LLMError("down")
        if image == b"b1":
            raise RuntimeError("bug")
        return await original(image, media_type)

    parser.parse = flaky

    result = await service.reparse_many(1, "outdated")

    assert (result.ok, result.failed) == (1, 2)
    assert "failed unexpectedly" in caplog.text


async def test_reparse_many_lets_a_photo_intake_in_between_two_receipts(
    service, parser, monkeypatch
):
    await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="w0")
    await read_with_version(service, parser, monkeypatch, UNSEEN_CARD, unique="w1")
    fresh = await intake(service, parser, "07", unique="w2")
    parser.events.clear()
    parser.started = asyncio.Event()
    parser.gates[b"w0"] = gate = asyncio.Event()
    run = asyncio.create_task(service.reparse_many(1, "outdated"))
    await asyncio.wait_for(parser.started.wait(), 5)
    intake_parse = asyncio.create_task(service.parse(1, fresh))
    await asyncio.sleep(0.05)
    assert not intake_parse.done()

    gate.set()
    await asyncio.wait_for(asyncio.gather(run, intake_parse), 5)

    assert [image for kind, image in parser.events if kind == "start"] == [b"w0", b"w2", b"w1"]


async def test_a_cancelled_reparse_run_stops_after_the_current_receipt(
    service, parser, make_uow, monkeypatch
):
    await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="x0")
    await read_with_version(service, parser, monkeypatch, UNSEEN_CARD, unique="x1")
    parser.events.clear()
    parser.started = asyncio.Event()
    parser.gates[b"x0"] = asyncio.Event()
    run = asyncio.create_task(service.reparse_many(1, "outdated"))
    await asyncio.wait_for(parser.started.wait(), 5)

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert [image for kind, image in parser.events if kind == "start"] == [b"x0"]


async def test_recover_interrupted_fixes_parsing_receipts_only(
    service, parser, make_uow, monkeypatch, caplog
):
    reread = await read_with_version(service, parser, monkeypatch, PAID_WITH_CARD, unique="i0")
    fresh = await intake(service, parser, UNSEEN_CARD, unique="i1")
    settled = await read_with_version(service, parser, monkeypatch, "07", unique="i2")
    waiting = await intake(service, parser, "08", unique="i3")
    other_user = await intake(service, parser, "10", unique="i4", user_id=2)
    for receipt_id in (reread, fresh, other_user):
        async with make_uow() as uow:
            receipt = await uow.receipts.get(receipt_id)
            receipt.mark_parsing()
            await uow.receipts.save(receipt)
            await uow.commit()

    with caplog.at_level("WARNING"):
        recovered = await service.recover_interrupted()

    assert recovered == 3
    assert "interrupted" in caplog.text
    states = {i: (await load(make_uow, i)) for i in (reread, fresh, settled, waiting, other_user)}
    assert [(s.status, s.error_message) for s in states.values()] == [
        ("parsed", "interrupted"),
        ("failed", "interrupted"),
        ("parsed", None),
        ("pending", None),
        ("failed", "interrupted"),
    ]
    assert states[reread].items  # the restored reading is intact
    assert await service.recover_interrupted() == 0
