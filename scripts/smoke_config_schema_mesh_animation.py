#!/usr/bin/env python3
"""Settings must expose the UniMate category and every configurable backend field.

Usage: ./.venv/bin/python scripts/smoke_config_schema_mesh_animation.py
"""
import asyncio
import sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config_schema import get_schema
fields = get_schema()["image_generation"]["sub_arrays"]["backends"]["fields"]
assert "mesh2anim" in fields["category"]["choices"]
assert "openai_mesh_animation" in fields["api_type"]["choices"]
for name in ("api_key", "model", "extra_params", "mesh_endpoint", "poll_interval",
             "max_wait", "max_queue_wait", "timeout", "max_concurrent"):
    assert "openai_mesh_animation" in fields[name].get("applicable_for", ["openai_mesh_animation"]), name
print("PASS: mesh2anim and all nine animation settings fields are visible")

import tempfile
from app.core import paths
paths.init(tempfile.mkdtemp())   # the admin module must never reach a real world
from app.routes import admin_settings as adm


async def check_animation_models(items, expected):
    requests = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, *, headers):
            requests.append((url, headers))
            return adm.httpx.Response(200, json={"data": items})

    with patch.object(adm.httpx, "AsyncClient", Client), patch.object(
        adm.config, "get", return_value={"backends": []}
    ):
        result = await adm.imagegen_backend_models(
            "animation-smoke", api_type="openai_mesh_animation",
            api_url="https://gateway.example/v1", api_key="smoke-key", user=None,
        )
    assert result["models"] == expected, result
    assert requests == [
        ("https://gateway.example/v1/models", {"Authorization": "Bearer smoke-key"})
    ], requests


async def check_models():
    await check_animation_models([
        {"id": "mesh-unimate", "owned_by": "ai-hub (image)"},
        {"id": "Trellis2-Low", "type": "mesh"},
    ], ["mesh-unimate"])
    await check_animation_models([
        {"id": "declared-animation", "type": "animation"},
        {"id": "image-model", "type": "image"},
    ], ["declared-animation"])


asyncio.run(check_models())
print("PASS: animation models include untyped aliases and send the Bearer key")
for name in ("width", "height", "_size_note", "image_family", "supports_negative_prompt"):
    assert "openai_mesh_animation" in fields[name].get("not_applicable_for", []), name
print("PASS: all five image-only fields are hidden for animation backends")
