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

OpenRouter-schema pricing (what OpenRouter and the AI-Hub gateway send):
``prompt``/``completion`` as strings in USD per TOKEN. A priced, a free ("0")
and an unknown-price ("-1") entry must all stay selectable, and the price must
arrive per 1M tokens: "0.0000008"/"0.0000016" -> 0.8 / 1.6 (x 1e6 by hand);
"-1" -> 0 (no price shown). Reading this schema with the Together keys found
no price anywhere and hid every priced model (live 2026-11-10: OpenRouter via
the gateway 429 -> 24, every local gateway model gone).
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
        {"id": "openrouter/priced", "pricing": {"prompt": "0.0000008", "completion": "0.0000016",
                                                "input_cache_read": "0.0000002"}},
        {"id": "openrouter/free:free", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
        {"id": "image-model", "type": "image"},
        {"id": "video-model", "type": "video"},
        {"id": "audio-model", "type": "audio"},
        {"id": "embedding-model", "type": "embedding"},
    ]}
    response = SimpleNamespace(status_code=200, json=lambda: catalog)
    provider = Provider(name="demo", type="openai",
                        api_base="https://example.invalid/v1", api_key="")
    with patch("app.core.provider.requests.get", return_value=response):
        listed = {m["name"]: m for m in provider.list_models(force_refresh=True)}
    names = set(listed)
    expected = {"venice-language", "together-chat", "openai-language",
                "output-priced-chat", "openrouter/priced", "openrouter/free:free",
                "openrouter/auto"}
    assert names == expected, f"Expected {expected}, got {names}"

    def price(name):
        p = listed[name]["pricing"]
        return round(p["input"], 6), round(p["output"], 6)
    assert price("together-chat") == (0.2, 0.3), price("together-chat")
    assert price("openrouter/priced") == (0.8, 1.6), price("openrouter/priced")
    assert price("openrouter/free:free") == (0.0, 0.0), price("openrouter/free:free")
    assert price("openrouter/auto") == (0.0, 0.0), price("openrouter/auto")
    print("PASS: Venice text, Together chat, untyped and OpenRouter-priced language models "
          "selectable with per-1M prices; media and non-serverless models excluded")


if __name__ == "__main__":
    main()
