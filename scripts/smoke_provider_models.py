#!/usr/bin/env python3
"""Verify language-model discovery across OpenAI-compatible provider catalogs.

Usage: ./.venv/bin/python scripts/smoke_provider_models.py

No server, world DB or network access is needed. The catalog is hand-built:
Venice declares language models as type=text; Together uses type=chat and
per-token pricing; plain OpenAI catalogs omit type. These three entries must
be selectable. Image/video/audio/embedding entries and Together chat entries
with zero input AND output pricing must remain excluded. A chat model with
only output pricing is still serverless and must remain selectable.

This catches a chat-only filter hiding every Venice model, or an overly broad
fix admitting media models or non-serverless Together entries.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.provider import Provider


def main():
    catalog = {"data": [
        {"id": "venice-language", "type": "text"},
        {"id": "together-chat", "type": "chat",
         "pricing": {"input": 0.2, "output": 0.3}},
        {"id": "openai-language"},
        {"id": "output-priced-chat", "type": "chat",
         "pricing": {"input": 0, "output": 0.3}},
        {"id": "dedicated-chat", "type": "chat",
         "pricing": {"input": 0, "output": 0}},
        {"id": "image-model", "type": "image"},
        {"id": "video-model", "type": "video"},
        {"id": "audio-model", "type": "audio"},
        {"id": "embedding-model", "type": "embedding"},
    ]}
    response = SimpleNamespace(status_code=200, json=lambda: catalog)
    provider = Provider(name="demo", type="openai",
                        api_base="https://example.invalid/v1", api_key="")
    with patch("app.core.provider.requests.get", return_value=response):
        names = {m["name"] for m in provider.list_models(force_refresh=True)}
    expected = {"venice-language", "together-chat", "openai-language",
                "output-priced-chat"}
    assert names == expected, f"Expected {expected}, got {names}"
    print("PASS: Venice text, Together chat and untyped language models selectable; "
          "media and non-serverless models excluded")


if __name__ == "__main__":
    main()
