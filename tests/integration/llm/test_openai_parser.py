"""OpenAIReceiptParser: error mapping offline, and one live call marked `llm`.

The live test is deselected by default (`uv run pytest -m llm` runs it). It needs
`LLM__API_KEY` in the environment (tests never read `.env`) and a photo
`tests/fixtures/images/receipt.*`.
"""

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from src.config.llm import LLMConfig
from src.integration.llm import LLMError, OpenAIReceiptParser
from src.integration.llm.openai_parser import USER_PROMPT
from src.integration.llm.schema import RawParse

IMAGES = Path(__file__).parents[2] / "fixtures" / "images"
SECRET = "sk-test-secret-1234"


def parser_failing_with(error: Exception) -> OpenAIReceiptParser:
    parser = OpenAIReceiptParser(LLMConfig(api_key=SecretStr(SECRET)))

    def fail(messages, info):
        raise error

    parser._agent.model = FunctionModel(fail)  # swap the network model for a failing one
    return parser


def parser_answering_with(raw: dict, seen: list | None = None) -> OpenAIReceiptParser:
    """A parser whose model returns `raw` as the structured output, with no network. The
    messages it was sent go into `seen`."""
    parser = OpenAIReceiptParser(LLMConfig(api_key=SecretStr(SECRET)))

    def answer(messages, info):
        if seen is not None:
            seen.extend(messages)
        tool = next(t for t in info.output_tools)
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=raw)])

    parser._agent.model = FunctionModel(answer)
    return parser


async def test_a_successful_call_yields_the_raw_parse_model_and_usage():
    fixture = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "receipts" / "03-consum-parsed.json").read_text()
    )
    parser = parser_answering_with(fixture["raw"])

    output = await parser.parse(b"img", "image/jpeg", {})

    assert output.raw.is_receipt is True
    assert len(output.raw.items) == 2
    assert output.model == "gpt-6-luna"
    assert output.input_tokens is not None and output.output_tokens is not None
    assert output.duration_ms >= 0


def user_text(messages) -> str:
    request = next(m for m in messages if isinstance(m, ModelRequest))
    part = next(p for p in request.parts if isinstance(p, UserPromptPart))
    return next(c for c in part.content if isinstance(c, str))


async def test_the_known_stores_go_into_the_user_message_as_one_json_object():
    fixture = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "receipts" / "03-consum-parsed.json").read_text()
    )
    seen: list = []
    parser = parser_answering_with(fixture["raw"], seen)

    await parser.parse(
        b"img", "image/jpeg", {"Consum": ["CERV FREE LIMO LLA", "LLET SÈGOL"], "Bon Àrea": []}
    )

    text = user_text(seen)
    assert text.startswith(USER_PROMPT)
    catalog = json.loads(text.splitlines()[-1])
    assert catalog == {"Consum": ["CERV FREE LIMO LLA", "LLET SÈGOL"], "Bon Àrea": []}


async def test_with_no_known_stores_the_user_message_is_the_instruction_alone():
    fixture = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "receipts" / "03-consum-parsed.json").read_text()
    )
    seen: list = []
    parser = parser_answering_with(fixture["raw"], seen)

    await parser.parse(b"img", "image/jpeg", {})

    assert user_text(seen) == USER_PROMPT


@pytest.mark.parametrize(
    "error",
    [
        ModelHTTPError(401, "gpt", {"error": f"bad key {SECRET}"}),
        UnexpectedModelBehavior("Exceeded maximum retries for output validation"),
        RuntimeError(f"an SDK bug with {SECRET}"),
        TimeoutError(f"timed out using {SECRET}"),
    ],
)
async def test_model_failures_become_one_line_llm_errors_without_the_key(error):
    parser = parser_failing_with(error)

    with pytest.raises(LLMError) as raised:
        await parser.parse(b"img", "image/jpeg", {})

    assert SECRET not in str(raised.value)
    assert "\n" not in str(raised.value)


def test_an_unsupported_provider_is_refused():
    with pytest.raises(LLMError):
        OpenAIReceiptParser(LLMConfig(model="anthropic:claude", api_key=SecretStr("k")))


def live_key() -> str | None:
    return os.environ.get("LLM__API_KEY") or None


@pytest.mark.llm
async def test_the_real_model_reads_a_receipt_photo():
    key = live_key()
    photos = sorted(IMAGES.glob("receipt.*"))
    if not key:
        pytest.skip("LLM__API_KEY is not set")
    if not photos:
        pytest.skip("no tests/fixtures/images/receipt.* photo")
    media_type = {".png": "image/png", ".webp": "image/webp"}.get(photos[0].suffix, "image/jpeg")
    model = os.environ.get("LLM__MODEL")
    config = LLMConfig(api_key=SecretStr(key), **({"model": model} if model else {}))

    output = await OpenAIReceiptParser(config).parse(photos[0].read_bytes(), media_type, {})

    assert RawParse.model_validate(output.raw.model_dump())
    assert output.raw.is_receipt is True
    assert len(output.raw.items) > 0
    assert output.duration_ms > 0


async def test_close_closes_the_providers_http_client():
    parser = OpenAIReceiptParser(LLMConfig(api_key=SecretStr(SECRET)))

    await parser.close()

    assert parser._client.is_closed()
