"""`OpenAIReceiptParser`: the n8n "Parse Receipt" step on pydantic-ai.

The system prompt is `prompt.md` next to this module, read verbatim at import through
`importlib.resources`, so it ships with the package. It started as a port of the n8n snapshot
`docs/n8n-reference/system_prompt.md` and is taler-bot's own now. The user's known stores and
their products are not in it: they go into each request's user message (`user_prompt`), so the
system prompt stays fixed.
"""

import json
import os
import time
from collections.abc import Mapping, Sequence
from importlib.resources import files

# pydantic-ai prints a Logfire advert on the first run unless told not to.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent, BinaryContent  # noqa: E402
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.config.llm import LLMConfig
from src.integration.llm.interface import LLMError, ParserOutput
from src.integration.llm.schema import RawParse

SYSTEM_PROMPT = files("src.integration.llm").joinpath("prompt.md").read_text(encoding="utf-8")
USER_PROMPT = "Transcribe this receipt into the JSON schema."
KNOWN_STORES_HEADING = "Known stores (store name -> printed texts of its products):"
_RETRIES = 2


class OpenAIReceiptParser:
    """Created once by `App`; holds one pydantic-ai `Agent`."""

    def __init__(self, config: LLMConfig) -> None:
        provider_name, separator, name = config.model.partition(":")
        if not separator:
            provider_name, name = "openai", config.model
        if provider_name != "openai":
            raise LLMError(f"unsupported LLM provider {provider_name!r}; use openai:<model>")
        provider = OpenAIProvider(api_key=config.api_key.get_secret_value())
        self._client = provider.client
        model = OpenAIResponsesModel(name, provider=provider)
        self._model_name = name
        self._secret = config.api_key.get_secret_value()
        self._agent = Agent(
            model,
            output_type=RawParse,
            instructions=SYSTEM_PROMPT,
            model_settings={"timeout": config.timeout_s},
            retries=_RETRIES,
        )

    async def close(self) -> None:
        """Close the provider's HTTP client."""
        await self._client.close()

    async def parse(
        self, image: bytes, media_type: str, known_stores: Mapping[str, Sequence[str]]
    ) -> ParserOutput:
        started = time.perf_counter()
        try:
            result = await self._agent.run(
                [user_prompt(known_stores), BinaryContent(data=image, media_type=media_type)]
            )
        except Exception as error:
            # Only the model call is in the try block, so anything escaping it (pydantic-ai,
            # openai, httpx, timeouts or an unforeseen SDK error) is a model/provider failure.
            raise LLMError(self._one_line(error)) from error
        usage = result.usage  # a property on AgentRunResult in pydantic-ai 2.x
        return ParserOutput(
            raw=result.output,
            model=self._model_name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    def _one_line(self, error: Exception) -> str:
        """A short message that never carries the API key."""
        text = " ".join(str(error).split()).replace(self._secret, "***")
        return f"{type(error).__name__}: {text}"[:300]


def user_prompt(known_stores: Mapping[str, Sequence[str]]) -> str:
    """The request text: the instruction, then the known stores as one JSON object, if any."""
    if not known_stores:
        return USER_PROMPT
    catalog = json.dumps(
        {name: list(texts) for name, texts in known_stores.items()}, ensure_ascii=False
    )
    return f"{USER_PROMPT}\n\n{KNOWN_STORES_HEADING}\n{catalog}"
