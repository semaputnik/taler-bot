"""The system prompt ships inside the package and stays identical to the n8n snapshot."""

from importlib.resources import files
from pathlib import Path

from src.integration.llm import SYSTEM_PROMPT

SNAPSHOT = Path(__file__).parents[3] / "docs" / "n8n-reference" / "system_prompt.md"


def test_the_packaged_prompt_is_byte_identical_to_the_docs_snapshot():
    packaged = files("src.integration.llm").joinpath("prompt.md").read_bytes()
    assert packaged == SNAPSHOT.read_bytes()


def test_the_system_prompt_is_loaded_from_the_package():
    assert SYSTEM_PROMPT.strip()
    assert "Write every issue message in English" in SYSTEM_PROMPT
