import json
from datetime import datetime
from pathlib import Path

import pytest

from src.domain.normalize import normalize
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
    )
    from_plain = normalize(data["raw"], **context)
    from_model = normalize(RawParse.model_validate(data["raw"]).model_dump(), **context)
    assert from_model == from_plain
