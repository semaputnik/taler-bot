# Receipt images for the live LLM test

Put one real receipt photo here as `receipt.jpg` (or `.png`). It is sent to the real model
by the test marked `llm` (`uv run pytest -m llm`, needs `LLM__API_KEY`), which only checks
that the output validates as `RawParse` with `is_receipt = True` and at least one item.

This directory is committed, so the photo must show nothing beyond what the store prints.
