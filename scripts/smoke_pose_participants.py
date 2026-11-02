#!/usr/bin/env python3
"""The pose catalog field ``participants`` (plan-gruppen-animationen.md G2a):
how many people a pose takes, 1..5, replacing the old ``solo`` flag. Against
a temporary world and a private copy of the shared catalog only.

Usage: ./.venv/bin/python scripts/smoke_pose_participants.py

Fixture (world layer, so the shared file is never touched): place types
stand (default "standing") and seat (default "sitting").
  standing  no field                       -> solo
  sitting   group seat, no field           -> solo
  hug       participants 2, places 2       -> a pair, clip "hug" with 2 roles
  circle    participants 3, places 7       -> a group, clip "circle" 3 roles
  junk      participants "x"               -> invalid, read as 1
  crowd     participants 9                 -> above the top, read as 5
Clip roles are patched: role_counts() = {hug: 2, circle: 3, crowd: 5}.

[1] LOADER. participants standing 1, hug 2, circle 3, junk 1, crowd 5;
    places standing 1 (solo), hug 2, circle min(3, 7) = 3; the entry
    carries no "solo" field any more; pose_participants("CIRCLE") 3 and
    pose_participants("nope") 1.
[2] CHECK. validate_catalog has no problem for these; set hug to
    participants 3 -> "pose/hug: 'hug' is a 2-person animation, the pose
    takes 3"; a follow pose {c: standing} on the pair -> "pose/hug: follow
    pose for a role the pose does not have"; {a, b, c} on circle is legal.
[3] MIGRATION. World rows {"solo": false, places 1} -> {participants 2,
    places 1}, {"solo": true} -> no participants and no solo, a row without
    "solo" untouched (same updated_at). Returns 2; a second run returns 0.
[4] ROUTE. _participants: "" -> 1, "3" -> 3; 0, 6, "x", True -> 400.
    _places(2, 3) -> 2; 4 and True -> 400 with participants 3. Creating
    "trio" with participants 3, places 2 stores {participants 3, places 2,
    yaw_offset 0}; creating it without places -> 400. Updating trio to
    participants 1 drops participants/places/yaw_offset; back to 2 without
    places -> 400 (a pose that becomes multi-person must say its slots);
    with places 1 -> stored. A row of GET /poses carries participants and
    follow_auto per role a..c for circle.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def status_of(fn, *args):
    from fastapi import HTTPException
    try:
        fn(*args)
    except HTTPException as e:
        return e.status_code
    return 200


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core.db import init_schema, transaction
        init_schema()
        from app.core import pose_catalog as pc
        original = pc.catalog_path
        private = Path(tmp) / "pose_catalog.json"
        private.write_text(json.dumps({"groups": {
            "stand": {"label": "Stand", "default": "standing", "needs_place": False},
            "seat": {"label": "Seat", "default": "sitting", "needs_place": True}},
            "entries": {"standing": {"prompt": "standing", "animation": "idle",
                                     "group": "stand", "_default": True}}}))
        pc.catalog_path = lambda axis: private if axis == "pose" else original(axis)
        world = {
            "sitting": {"prompt": "sitting", "animation": "sit", "group": "seat"},
            "hug": {"prompt": "hug", "animation": "hug", "group": "stand",
                    "participants": 2, "places": 2},
            "circle": {"prompt": "circle", "animation": "circle", "group": "stand",
                       "participants": 3, "places": 7},
            "junk": {"prompt": "junk", "animation": "idle", "group": "stand", "participants": "x"},
            "crowd": {"prompt": "crowd", "animation": "crowd", "group": "stand", "participants": 9},
        }
        pc.replace_world_entries("pose", world)
        pc.reload_catalogs()
        counts = {"hug": 2, "circle": 3, "crowd": 5}
        with patch("app.core.animation_clips.role_counts", return_value=counts):
            print("[1] loader")
            cat = pc.get_catalog("pose")
            check("participants", {k: cat[k]["participants"] for k in
                                   ("standing", "hug", "circle", "junk", "crowd")},
                  {"standing": 1, "hug": 2, "circle": 3, "junk": 1, "crowd": 5})
            check("places", {k: cat[k]["places"] for k in ("standing", "hug", "circle")},
                  {"standing": 1, "hug": 2, "circle": 3})
            check("no solo field", any("solo" in e for e in cat.values()), False)
            check("pose_participants", (pc.pose_participants("CIRCLE"), pc.pose_participants("nope")), (3, 1))

            print("[2] check")
            check("sound", [p for p in pc.validate_catalog("pose")
                            if p.startswith(("pose/hug", "pose/circle"))], [])
            pc.replace_world_entries("pose", dict(world, hug=dict(world["hug"], participants=3)))
            pc.reload_catalogs()
            check("clip roles vs participants",
                  "pose/hug: 'hug' is a 2-person animation, the pose takes 3" in pc.validate_catalog("pose"),
                  True)
            pc.replace_world_entries("pose", dict(
                world, hug=dict(world["hug"], follow_pose={"c": "standing"}),
                circle=dict(world["circle"], follow_pose={"a": "standing", "b": "sitting", "c": "standing"})))
            pc.reload_catalogs()
            problems = pc.validate_catalog("pose")
            check("role the pose lacks",
                  "pose/hug: follow pose for a role the pose does not have" in problems, True)
            check("three roles legal", [p for p in problems if p.startswith("pose/circle")], [])

            print("[3] migration")
            pc.replace_world_entries("pose", {
                "old-pair": {"prompt": "p", "animation": "hug", "group": "stand", "solo": False, "places": 1},
                "old-solo": {"prompt": "s", "animation": "idle", "group": "stand", "solo": True},
                "new": {"prompt": "n", "animation": "idle", "group": "stand"}})
            with transaction() as conn:
                conn.execute("UPDATE pose_catalog_world SET updated_at='T0' WHERE key='new'")
            check("rewritten", pc.migrate_participants_once(), 2)
            rows = pc.world_entries("pose")
            check("pair", rows["old-pair"], {"prompt": "p", "animation": "hug", "group": "stand",
                                             "participants": 2, "places": 1})
            check("solo", rows["old-solo"], {"prompt": "s", "animation": "idle", "group": "stand"})
            with transaction() as conn:
                stamp = conn.execute("SELECT updated_at FROM pose_catalog_world WHERE key='new'").fetchone()[0]
            check("untouched", stamp, "T0")
            check("second run", pc.migrate_participants_once(), 0)

            print("[4] route")
            from app.routes import poses as R
            check("participants default", R._participants(""), 1)
            check("participants 3", R._participants("3"), 3)
            check("participants refused", [status_of(R._participants, v) for v in (0, 6, "x", True)],
                  [400, 400, 400, 400])
            check("places 2 of 3", R._places(2, 3), 2)
            check("places refused", [status_of(R._places, v, 3) for v in (4, True)], [400, 400])
            pc.replace_world_entries("pose", world)
            pc.reload_catalogs()
            body = {"axis": "pose", "key": "trio", "prompt": "trio", "animation": "circle",
                    "group": "stand", "participants": 3, "store": "world"}
            check("create without places", status_of(R._create_entry_sync, {}, dict(body)), 400)
            R._create_entry_sync({}, dict(body, places=2))
            stored = pc.world_entries("pose")["trio"]
            check("created", {k: stored.get(k) for k in ("participants", "places", "yaw_offset")},
                  {"participants": 3, "places": 2, "yaw_offset": 0.0})
            R._update_entry_sync("trio", "pose", {}, {"participants": 1})
            stored = pc.world_entries("pose")["trio"]
            check("to solo", [k for k in ("participants", "places", "yaw_offset") if k in stored], [])
            check("back without places",
                  status_of(R._update_entry_sync, "trio", "pose", {}, {"participants": 2}), 400)
            R._update_entry_sync("trio", "pose", {}, {"participants": 2, "places": 1})
            stored = pc.world_entries("pose")["trio"]
            check("back with places", (stored.get("participants"), stored.get("places")), (2, 1))
            rows = {r["key"]: r for r in R.list_entries(axis="pose", _={}, set_id="")["entries"]}
            check("row participants", rows["circle"]["participants"], 3)
            check("row follow roles", sorted(rows["circle"]["follow_auto"]), ["a", "b", "c"])
        pc.catalog_path = original
        pc.reload_catalogs()

    print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
