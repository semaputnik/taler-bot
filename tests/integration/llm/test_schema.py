import json
from datetime import datetime
from pathlib import Path

import pytest

from src.domain.normalize import PARSER_VERSION, normalize
from src.integration.llm.schema import RawParse

FIXTURES = sorted(Path(__file__).parents[2].joinpath("fixtures/receipts").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_raw_output_validates_and_normalizes_the_same_as_plain_data(path):
    data = json.loads(path.read_text())
    ctx = data["context"]
    context = dict(
        received_at=datetime.fromisoformat(ctx["received_at"]),
        timezone=ctx["timezone"],
        known_product_keys=ctx["known_product_keys"],
        known_card_last4=ctx["known_card_last4"],
        parser_version=PARSER_VERSION,
        model="m",
    )
    from_plain = normalize(data["raw"], **context)
    from_model = normalize(RawParse.model_validate(data["raw"]).model_dump(), **context)
    assert from_model == from_plain


def test_every_schema_field_is_required_in_the_json_schema_the_model_sees():
    receipt_info = RawParse.model_json_schema()["$defs"]["RawReceiptInfo"]
    assert set(receipt_info["required"]) == set(receipt_info["properties"])


def test_the_item_categories_the_model_may_use_are_the_product_categories():
    from src.domain.enums import ProductCategory
    from src.integration.llm.schema import ItemCategory

    assert [c.value for c in ItemCategory] == [c.value for c in ProductCategory]
