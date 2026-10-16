"""Test doubles for the integration ports."""

import asyncio
import json
from pathlib import Path
from typing import Any

from src.integration.llm import ParserOutput
from src.integration.llm.schema import RawParse

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"


def fixture(name: str) -> dict[str, Any]:
    """A committed n8n receipt: its `raw` model output and the `context` n8n saw."""
    return json.loads(next(FIXTURES.glob(f"{name}-*.json")).read_text())


def output_of(raw: dict[str, Any], **fields: Any) -> ParserOutput:
    defaults = dict(model="gpt-test", input_tokens=1200, output_tokens=300, duration_ms=2500)
    return ParserOutput(raw=RawParse.model_validate(raw), **{**defaults, **fields})


class StubReceiptParser:
    """Returns the output prepared for an image (or the default), or raises.

    `events` records `("start", image)` and `("end", image)` in order, so a test can assert
    that two calls did not overlap. `gates[image]` holds that image's call open until set.
    """

    def __init__(
        self,
        default: ParserOutput | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.default = default
        self.outputs: dict[bytes, ParserOutput] = {}
        self.error = error
        self.delay = delay
        self.gates: dict[bytes, asyncio.Event] = {}
        self.events: list[tuple[str, bytes]] = []
        self.started = asyncio.Event()  # set by the first call

    async def parse(self, image: bytes, media_type: str) -> ParserOutput:
        self.events.append(("start", image))
        self.started.set()
        try:
            if image in self.gates:
                await self.gates[image].wait()
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error is not None:
                raise self.error
            output = self.outputs.get(image, self.default)
            assert output is not None, "the stub has no output prepared"
            return output
        finally:
            self.events.append(("end", image))

    async def close(self) -> None:
        pass
