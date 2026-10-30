#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_pose_group_exit.py

Getting up uses the pose GROUP's exit rule when the pose has none of its own
(``animation_clips.resolve_pose_transition``), the counterpart of the entry
fallback ``walking -> @<group>``.

Hand-derived expectations, private fixture (isolated clip dir + rule file +
catalog): rules walking -> @seat sit-down, @seat -> * get-up-chair,
@lie -> * get-up-bed, sitting at table -> * get-up-table; poses sitting and
sitting at table (group seat), sleeping (lie), kneeling (ground), walking
(stand); clip lengths get-up-chair 4.767 s, get-up-bed 4.067 s, get-up-table
3.0 s, sit-down 2.033 s.

a. ``sitting`` has no rule of its own: leaving it resolves to
   @seat -> * = get-up-chair, and ``exit_bridge_for_pose`` answers
   (get-up-chair, 4.767). The same rule answers sitting -> standing.
b. ``sitting at table`` keeps its own rule: (get-up-table, 3.0).
c. ``sleeping`` (lie) -> (get-up-bed, 4.067).
d. ``kneeling`` (ground) has no group exit rule: ("", 0.0) — released at once.
e. Entering is unchanged: walking -> sitting = walking -> @seat = sit-down.
f. The SHIPPED table carries @seat -> * get-up-chair and @lie -> *
   get-up-bed, and both shipped clips are solo one-shots with a length.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="pose-group-exit-") as tmp:
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
        from app.core.travel_engine import exit_bridge_for_pose
        init_schema()
        for kind, seconds in (("get-up-chair", 4.767), ("get-up-bed", 4.067),
                              ("get-up-table", 3.0), ("sit-down", 2.033)):
            (free / f"{kind}.fbx").write_bytes(b"isolated solo fixture")
            (free / f"{kind}.json").write_text(json.dumps(
                {"kind": kind, "duration_s": seconds, "loop": False}))
        rules = [{"from": "walking", "to": "@seat", "kind": "sit-down", "accel": 0},
                 {"from": "@seat", "to": "*", "kind": "get-up-chair", "accel": 0},
                 {"from": "@lie", "to": "*", "kind": "get-up-bed", "accel": 0},
                 {"from": "sitting at table", "to": "*", "kind": "get-up-table", "accel": 0}]
        transitions = root / "transitions.json"
        transitions.write_text(json.dumps({"transitions": rules}))
        catalog = {"sitting": {"group": "seat"}, "sitting at table": {"group": "seat"},
                   "sleeping": {"group": "lie"}, "kneeling": {"group": "ground"},
                   "walking": {"group": "stand"}, "standing": {"group": "stand"}}
        with patch.object(ac, "clip_transitions_path", return_value=transitions), \
                patch.object(pc, "get_catalog", return_value=catalog):
            ac._clear_entries_cache()
            assert ac.resolve_pose_transition("sitting", "walking")["kind"] == "get-up-chair"
            assert exit_bridge_for_pose("sitting") == ("get-up-chair", 4.767), exit_bridge_for_pose("sitting")
            assert ac.resolve_pose_transition("sitting", "standing")["kind"] == "get-up-chair"
            print("PASS a: a seat pose without its own rule gets up through @seat")
            assert exit_bridge_for_pose("sitting at table") == ("get-up-table", 3.0)
            print("PASS b: the pose's own exit rule wins")
            assert exit_bridge_for_pose("sleeping") == ("get-up-bed", 4.067)
            print("PASS c: a lie pose gets up through @lie")
            assert exit_bridge_for_pose("kneeling") == ("", 0.0)
            print("PASS d: no ground exit rule, no bridge")
            assert ac.resolve_pose_transition("walking", "sitting")["kind"] == "sit-down"
            print("PASS e: entering still uses walking -> @seat")
    shipped = json.loads((ROOT / "shared/config/clip_transitions.json").read_text())["transitions"]
    exits = {(r["from"], r["to"]): r["kind"] for r in shipped}
    assert exits.get(("@seat", "*")) == "get-up-chair" and exits.get(("@lie", "*")) == "get-up-bed", exits
    for kind in ("get-up-chair", "get-up-bed"):
        meta = json.loads((ROOT / "shared/models/clips" / f"{kind}.json").read_text())
        assert not meta.get("loop") and not meta.get("pair") and float(meta["duration_s"]) > 0, meta
        assert (ROOT / "shared/models/clips" / f"{kind}.fbx").exists()
    print("PASS f: the shipped table and clips carry both group exits")


if __name__ == "__main__":
    main()
