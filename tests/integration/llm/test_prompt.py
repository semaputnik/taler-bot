"""The system prompt ships inside the package.

It started as the n8n snapshot `docs/n8n-reference/system_prompt.md` and is taler-bot's own now.
"""

from src.integration.llm import SYSTEM_PROMPT


def test_the_system_prompt_is_loaded_from_the_package():
    assert SYSTEM_PROMPT.strip()
    assert "Write every issue message in English" in SYSTEM_PROMPT


def test_the_system_prompt_explains_the_catalog_match_fields():
    assert "store.known_name" in SYSTEM_PROMPT
    assert "items[].known_name_raw" in SYSTEM_PROMPT
