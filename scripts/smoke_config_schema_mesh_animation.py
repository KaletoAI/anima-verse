#!/usr/bin/env python3
"""Settings must expose the UniMate category and every configurable backend field.

Usage: ./.venv/bin/python scripts/smoke_config_schema_mesh_animation.py
"""
import sys
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
