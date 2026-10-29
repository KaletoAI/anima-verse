#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_transition_world_fallback.py

Hand-derived expectations: the shared walking -> @stand bridge is step-in.
An absent world replacement cannot apply, so runtime uses step-in/shared,
while both editor listings retain absent-clip/world. Adding absent-clip to
this installation makes that world replacement win. An absent world-only
reading -> resting rule yields no runtime rule and no client clip pair.
A stand-group cooking pose therefore enters through step-in, whose fixture
is a solo, non-loop clip of duration 2 seconds. Shared missing bridges stay
in the runtime table, and explicitly supplied rules remain unfiltered.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="transition-fallback-") as tmp:
        root = Path(tmp)
        free, licensed = root / "free", root / "licensed"
        free.mkdir()
        licensed.mkdir()
        os.environ["ANIMATION_CLIPS_DIR"] = str(free)
        os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(licensed)
        from app.core import paths
        paths.init(root / "world")
        from app.core.db import init_schema
        from app.core import animation_clips as ac
        from app.core import pose_catalog as pc
        from app.core.prop_action_engine import _entry_capability
        init_schema()
        (free / "step-in.fbx").write_bytes(b"isolated solo fixture")
        (free / "step-in.json").write_text(json.dumps({
            "kind": "step-in", "duration_s": 2, "loop": False}))
        shared = {"from": "walking", "to": "@stand", "kind": "step-in", "accel": 0}
        missing_shared = {"from": "resting", "to": "reading", "kind": "missing-shared", "accel": 0}
        replacement = dict(shared, kind="absent-clip")
        extra = {"from": "reading", "to": "resting", "kind": "absent-only", "accel": 0}
        transitions = root / "transitions.json"
        transitions.write_text(json.dumps({"transitions": [shared, missing_shared]}))
        catalog = {"cooking": {"group": "stand", "animation": "cook"},
                   "reading": {"animation": "read"}, "resting": {"animation": "rest"},
                   "walking": {"animation": "walk"}}
        with patch.object(ac, "clip_transitions_path", return_value=transitions), \
                patch.object(pc, "get_catalog", return_value=catalog), \
                patch("app.core.pose_catalog_edit.read_store", return_value={"entries": catalog}):
            # Imported world rules can reference clips absent on this installation.
            ac._write_world_transitions([replacement, extra])
            ac._clear_entries_cache()
            assert ac.resolve_transition("walking", "@stand") == dict(shared, store="shared")
            assert ac.load_transitions()[0] == dict(replacement, store="world")
            assert ac.annotated_transitions()[0]["kind"] == "absent-clip"
            print("PASS a: runtime shared fallback; full/editor tables retain world rule")
            capability, reason = _entry_capability("cooking")
            assert reason == "" and capability[0] == "step-in"
            print("PASS d: stand-group entry uses step-in")
            assert ac.resolve_transition("reading", "resting") is None
            assert not any(r["from"] == "read" and r["to"] == "rest"
                           for r in ac.client_transition_rules())
            assert ac.resolve_transition("resting", "reading")["kind"] == "missing-shared"
            assert ac.resolve_transition("reading", "resting", [extra]) == extra
            assert any(r["kind"] == "absent-only" for r in ac.client_transition_rules([extra]))
            print("PASS c: missing world-only rule dropped; shared/explicit rules unchanged")
            (licensed / "absent-clip.fbx").write_bytes(b"isolated solo fixture")
            ac._clear_entries_cache()
            assert ac.resolve_transition("walking", "@stand") == dict(replacement, store="world")
            print("PASS b: installed world bridge wins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
