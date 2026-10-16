"""ReceiptService.parse through the Unit of Work, with a stub parser and tmp photo storage."""

import asyncio
from datetime import datetime

import pytest

from src.domain.enums import ReceiptStatus
from src.exception import InvalidReceiptTransition, ReceiptNotFound
from src.integration.llm import LLMError
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
    assert "consum" in catalog.stores
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


async def test_a_receipt_that_is_parsing_or_parsed_refuses_another_parse(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="g1")
    async with make_uow() as uow:  # a parse of another process is in flight
        receipt = await uow.receipts.get(receipt_id)
        receipt.mark_parsing()
        await uow.receipts.save(receipt)
        await uow.commit()

    with pytest.raises(InvalidReceiptTransition):
        await service.parse(1, receipt_id)
    assert parser.events == []

    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
        receipt.status = ReceiptStatus.PENDING
        await uow.receipts.save(receipt)
        await uow.commit()
    await service.parse(1, receipt_id)
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
