from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from src.exception import IntegrationException
from src.integration.llm.schema import RawParse


class LLMError(IntegrationException):
    """The model could not read the image: API, network, timeout or an unusable answer."""


@dataclass(frozen=True)
class ParserOutput:
    """The model's validated answer with how it was obtained."""

    raw: RawParse
    model: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int


class ReceiptParser(Protocol):
    async def parse(
        self, image: bytes, media_type: str, known_stores: Mapping[str, Sequence[str]]
    ) -> ParserOutput:
        """Read a receipt photo. `known_stores` maps the name of each store the user bought from
        lately to the printed texts of its recent products; the model may match the receipt to
        them (`store.known_name`, `items[].known_name_raw`). Raises `LLMError` on any failure of
        the model call."""
        ...

    async def close(self) -> None:
        """Release the HTTP client; called once by `App` on shutdown."""
        ...
