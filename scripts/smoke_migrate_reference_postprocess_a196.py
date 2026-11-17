#!/usr/bin/env python3
"""Smoke: migrate_reference_postprocess_a196 keeps the world default when a profile save failed.

Usage: ./.venv/bin/python scripts/smoke_migrate_reference_postprocess_a196.py

Temp storage only (paths.init on a temp dir); the profile reader/writer are replaced by an in-memory
dict, so no world.db is touched. World config.json = {"base_body": {"reference_postprocess": "op_a",
"other": 1}}, one operation "op_a" (no ``applies`` -> applies to everyone), characters Ann and Bob with
empty profiles: both only follow the world default.

By hand:
[1] migrate_profiles(apply=True) with Bob's save returning False -> failed == ["Bob"]; Ann's stored
    profile is {"reference_postprocess": {"op_a": True}}.
[2] drop_world_default(..., failed=["Bob"]) -> False and config.json byte-identical: Bob still follows
    the default, so it must stay for a re-run (the old code removed it regardless).
[3] a re-run where every save succeeds -> failed == []; drop_world_default -> True, config.json parses to
    {"base_body": {"other": 1}}, and exactly one ``.config-history/<stamp>/config.json`` holds the OLD
    bytes; no ``config.json.a196tmp`` is left behind.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TMP = Path(tempfile.mkdtemp(prefix="a196-smoke-"))
from app.core import paths  # noqa: E402
paths.init(TMP)

import migrate_reference_postprocess_a196 as mig  # noqa: E402
from app.models import character as ch  # noqa: E402

FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)
        print("FAIL:", msg)


cfg_path = TMP / "config.json"
cfg_path.write_text(json.dumps({"base_body": {"reference_postprocess": "op_a", "other": 1}}, indent=2) + "\n")
before = cfg_path.read_bytes()
store = {"Ann": {}, "Bob": {}}
refuse = {"Bob"}


def fake_get(name, *a, **k):
    return json.loads(json.dumps(store.get(name) or {}))


def fake_save(name, profile, *a, **k):
    if name in refuse:
        return False
    store[name] = profile
    return True


ch.get_character_profile, ch.save_character_profile = fake_get, fake_save
available = {"op_a": {"id": "op_a"}}
world_cfg = json.loads(before)
world = mig._world_default(world_cfg)
check(world == ["op_a"], f"world default parsed {world}")

# [1]
failed = mig.migrate_profiles(["Ann", "Bob"], available, world, apply=True)
check(failed == ["Bob"], f"[1] failed {failed}")
check(store["Ann"] == {"reference_postprocess": {"op_a": True}}, f"[1] Ann stored {store['Ann']}")

# [2]
check(mig.drop_world_default(TMP, world_cfg, failed) is False, "[2] world default dropped despite a failed save")
check(cfg_path.read_bytes() == before, "[2] config.json changed despite a failed save")

# [3]
refuse.clear()
failed = mig.migrate_profiles(["Ann", "Bob"], available, world, apply=True)
check(failed == [], f"[3] failed {failed}")
check(mig.drop_world_default(TMP, world_cfg, failed) is True, "[3] world default not dropped")
check(json.loads(cfg_path.read_text()) == {"base_body": {"other": 1}}, f"[3] config {cfg_path.read_text()}")
snaps = sorted((TMP / ".config-history").glob("*/config.json"))
check(len(snaps) == 1 and snaps[0].read_bytes() == before, f"[3] history snapshots {snaps}")
check(not (TMP / "config.json.a196tmp").exists(), "[3] temp file left behind")

print("FAILED" if FAIL else "OK migrate_reference_postprocess_a196 keeps the default on a failed save")
sys.exit(1 if FAIL else 0)
