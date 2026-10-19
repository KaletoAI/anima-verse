#!/usr/bin/env python3
"""Smoke plugin task declarations.

Usage: ./.venv/bin/python scripts/smoke_plugin_llm_tasks.py

Hand-derived expectations: demo_note declares a chat_stream parent and no
priority, so it is catalogued with NORMAL priority and that parent. demo_bad
has an unknown parent, so it has no fallback. A chat_stream declaration cannot
replace the core label. Invalid categories and priorities must not register.
Inventory scans contribute no tasks. A missing dependency contributes none;
active discovery contributes one task, and removing its manifest removes it.
"""
import sys
import tempfile
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="plugin-tasks-"))
from app.core import paths
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db
config.load(STORAGE / "config.json")
db.init_schema()
from app.core import llm_tasks, llm_router
from app.core.llm_queue import Priority
from app.plugins.loader import _parse_package

package_dir = STORAGE / "notes"
package_dir.mkdir()
manifest = package_dir / "plugin.yaml"
manifest.write_text("""name: notes
llm_tasks:
  demo_note: {label: Demo note, category: chat, fallback: chat_stream}
  demo_bad: {label: Bad parent, category: helper, fallback: no_such_task}
  chat_stream: {label: Hijack, category: chat}
""")
pkg = _parse_package(package_dir, yaml.safe_load(manifest.read_text()))
assert "demo_note" in llm_tasks.TASK_TYPES
assert pkg is not None
assert llm_tasks.TASK_TYPES["demo_note"]["label"] == "Demo note"
assert llm_router.fallback_parent("demo_note") == "chat_stream"
assert llm_router.fallback_parent("demo_bad") is None
assert llm_tasks.TASK_TYPES["chat_stream"]["label"] != "Hijack"
assert llm_tasks.get_default_priority("demo_note") == Priority.NORMAL
assert not llm_tasks.register_plugin_task("invalid", {"label": "Invalid", "category": "other"}, "notes")
assert not llm_tasks.register_plugin_task("invalid", {"label": "Invalid", "category": "chat", "priority": "urgent"}, "notes")
assert "invalid" not in llm_tasks.TASK_TYPES
from app.plugins.loader import _collect_packages, discover_packages
from unittest.mock import patch

inventory = STORAGE / "inventory"
notes = inventory / "notes"
notes.mkdir(parents=True)
notes_manifest = notes / "plugin.yaml"
notes_manifest.write_text("""name: notes
llm_tasks:
  inventory_note: {label: Inventory note, category: helper}
""")
assert _collect_packages(inventory)
assert "inventory_note" not in llm_tasks.TASK_TYPES
notes_manifest.write_text(notes_manifest.read_text() + "requires: [missing_package]\n")
with patch("app.plugins.loader._activation_enabled_ids", frozenset({"notes"})):
    assert discover_packages(inventory, force=True) == []
    assert "inventory_note" not in llm_tasks.TASK_TYPES
    notes_manifest.write_text(notes_manifest.read_text().replace("requires: [missing_package]\n", ""))
    assert discover_packages(inventory, force=True)
    assert "inventory_note" in llm_tasks.TASK_TYPES
    notes_manifest.unlink()
    discover_packages(inventory, force=True)
    assert "inventory_note" not in llm_tasks.TASK_TYPES
print("PASS: plugin LLM tasks")
