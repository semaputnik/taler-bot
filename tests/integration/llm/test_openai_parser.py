"""OpenAIReceiptParser: error mapping offline, and one live call marked `llm`.

The live test is deselected by default (`uv run pytest -m llm` runs it). It needs
`LLM__API_KEY` (environment or the repo-root `.env`) and a photo `tests/fixtures/images/receipt.*`.
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import SecretStr
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models.function import FunctionModel

from src.config.llm import LLMConfig
from src.config.settings import ENV_FILE
from src.integration.llm import SYSTEM_PROMPT, LLMError, OpenAIReceiptParser
from src.integration.llm.schema import RawParse

IMAGES = Path(__file__).parents[2] / "fixtures" / "images"
SECRET = "sk-test-secret-1234"


def parser_failing_with(error: Exception) -> OpenAIReceiptParser:
    parser = OpenAIReceiptParser(LLMConfig(api_key=SecretStr(SECRET)))

    def fail(messages, info):
        raise error

    parser._agent.model = FunctionModel(fail)  # swap the network model for a failing one
    return parser


def test_the_system_prompt_is_the_n8n_file_verbatim():
    reference = Path(__file__).parents[3] / "docs" / "n8n-reference" / "system_prompt.md"
    assert SYSTEM_PROMPT == reference.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "error",
    [
        ModelHTTPError(401, "gpt", {"error": f"bad key {SECRET}"}),
        UnexpectedModelBehavior("Exceeded maximum retries for output validation"),
        TimeoutError(f"timed out using {SECRET}"),
    ],
)
async def test_model_failures_become_one_line_llm_errors_without_the_key(error):
    parser = parser_failing_with(error)

    with pytest.raises(LLMError) as raised:
        await parser.parse(b"img", "image/jpeg")

    assert SECRET not in str(raised.value)
    assert "\n" not in str(raised.value)


def test_an_unsupported_provider_is_refused():
    with pytest.raises(LLMError):
        OpenAIReceiptParser(LLMConfig(model="anthropic:claude", api_key=SecretStr("k")))


def live_key() -> str | None:
    return os.environ.get("LLM__API_KEY") or dotenv_values(ENV_FILE).get("LLM__API_KEY") or None


@pytest.mark.llm
async def test_the_real_model_reads_a_receipt_photo():
    key = live_key()
    photos = sorted(IMAGES.glob("receipt.*"))
    if not key:
        pytest.skip("LLM__API_KEY is not set")
    if not photos:
        pytest.skip("no tests/fixtures/images/receipt.* photo")
    media_type = {".png": "image/png", ".webp": "image/webp"}.get(photos[0].suffix, "image/jpeg")
    model = os.environ.get("LLM__MODEL") or dotenv_values(ENV_FILE).get("LLM__MODEL")
    config = LLMConfig(api_key=SecretStr(key), **({"model": model} if model else {}))

    output = await OpenAIReceiptParser(config).parse(photos[0].read_bytes(), media_type)

    assert RawParse.model_validate(output.raw.model_dump())
    assert output.raw.is_receipt is True
    assert len(output.raw.items) > 0
    assert output.duration_ms > 0
