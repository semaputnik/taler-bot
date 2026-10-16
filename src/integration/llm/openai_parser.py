"""`OpenAIReceiptParser`: the n8n "Parse Receipt" step on pydantic-ai.

The system prompt is `docs/n8n-reference/system_prompt.md`, read verbatim at import so the
docs file stays the single source. The Docker image must therefore ship `docs/n8n-reference/`
(or the prompt must move into the package) before the bot is containerised.
"""

import time
from pathlib import Path

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import AgentRunError, UserError
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.config.llm import LLMConfig
from src.integration.llm.interface import LLMError, ParserOutput
from src.integration.llm.schema import RawParse

SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[3] / "docs" / "n8n-reference" / "system_prompt.md"
).read_text(encoding="utf-8")
USER_PROMPT = "Transcribe this receipt into the JSON schema."
_RETRIES = 2


class OpenAIReceiptParser:
    """Created once by `App`; holds one pydantic-ai `Agent`."""

    def __init__(self, config: LLMConfig) -> None:
        provider_name, separator, name = config.model.partition(":")
        if not separator:
            provider_name, name = "openai", config.model
        if provider_name != "openai":
            raise LLMError(f"unsupported LLM provider {provider_name!r}; use openai:<model>")
        model = OpenAIResponsesModel(
            name, provider=OpenAIProvider(api_key=config.api_key.get_secret_value())
        )
        self._model_name = name
        self._secret = config.api_key.get_secret_value()
        self._agent = Agent(
            model,
            output_type=RawParse,
            instructions=SYSTEM_PROMPT,
            model_settings={"timeout": config.timeout_s},
            retries=_RETRIES,
        )

    async def parse(self, image: bytes, media_type: str) -> ParserOutput:
        started = time.perf_counter()
        try:
            result = await self._agent.run(
                [USER_PROMPT, BinaryContent(data=image, media_type=media_type)]
            )
        except (AgentRunError, UserError, OSError, TimeoutError) as error:
            raise LLMError(self._one_line(error)) from error
        except Exception as error:  # provider SDK errors (openai, httpx) must not leak out
            if type(error).__module__.split(".")[0] in ("openai", "httpx", "httpcore"):
                raise LLMError(self._one_line(error)) from error
            raise
        usage = result.usage()
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
