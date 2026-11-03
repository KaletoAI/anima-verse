#!/usr/bin/env python3
"""Missing transition clips are counted for avatars and their partners, and
suggested until a rule covers them.

Usage: ./.venv/bin/python scripts/smoke_transition_misses.py

Temporary world, instance and clip libraries; no server. The avatar set is
patched to {"Ava"} (the scope is under test, not the account store). Clip
library: idle, walk, wave, bow, wave-bow (a bridge), hug__a/hug__b (a pair)
— dummy bytes, never read. World poses: "p-wave" (wave), "p-bow" (bow),
"p-lost" (animation "lost", no clip), "p-hug" (participants 2, hug), all in
group "stand" (no place needed). World transition rules replace the shared
ones: none at first. Hand-derived from ``transition_misses``:

  [1] Ben (no avatar, no interaction) p-wave -> p-bow: no row.
  [2] Ava (female) strikes p-wave with no pose held: one row
      standing -> p-wave, set "female", count 1, names [Ava], ready.
  [3] p-wave -> p-bow twice (bow, wave, bow): rows p-wave -> p-bow count 2
      and p-bow -> p-wave count 1. The same pose again counts nothing.
  [4] A world rule p-wave -> p-bow with bridge "wave-bow" hides that row
      from the suggestions; the table row stays (count 2).
  [5] clear_pose_intent from p-bow: row p-bow -> standing. The same on a
      journey's arrival (arriving=True) counts nothing; an arrival pose
      (set_pose_intent arriving=True) counts walking -> p-wave.
  [6] departure_bridge with p-wave held: row p-wave -> walking.
  [7] Ben in an interaction with Ava (role b of p-hug): the switch
      p-hug -> standing counts with start_role "b", target_role "" — also
      when the interaction has just ended (last_interaction_result names
      p-hug); a last result of ANOTHER pose does not make him in scope.
  [8] p-lost -> p-wave for Ava: the row is listed, ready False, problem
      names p-lost ("pose animation missing from library").
  [9] dismiss hides the row; dismissing an unknown row answers False; the
      routes answer the same list and 404 for an unknown row.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transition-misses-"))
for sub in ("free", "licensed", "world", "instance"):
    (ROOT / sub).mkdir()
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "free")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(ROOT / "licensed")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "unused.fbx")

from app.core import paths  # noqa: E402
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import db  # noqa: E402
db.init_schema()

from app.core import animation_clips as clips, pose_catalog, transition_misses as M  # noqa: E402
from app.core.travel_engine import departure_bridge  # noqa: E402
from app.models.character import (clear_pose_intent, get_character_profile,  # noqa: E402
                                  save_character_profile, set_pose_intent)


def rows():
    return {(r[0], r[1], r[2], r[3]): (r[4], r[5], json.loads(r[6])) for r in db.get_connection().execute(
        "SELECT start_pose, target_pose, start_role, target_role, cset, count, names FROM transition_misses")}


def listed():
    return {(m["start_pose"], m["target_pose"], m["start_role"], m["target_role"]): m for m in M.suggestions()}


def main():
    for kind in ("idle", "walk", "wave", "bow", "wave-bow"):
        (ROOT / "free" / f"{kind}.fbx").write_bytes(b"dummy")
        (ROOT / "free" / f"{kind}.json").write_text(json.dumps({"duration_s": 1.0}))
    for role in ("a", "b"):
        (ROOT / "free" / f"hug__{role}.fbx").write_bytes(b"dummy")
    (ROOT / "free" / "hug.json").write_text(json.dumps({"pair": True, "duration_s": 1.0}))
    clips.reload_clip_caches()
    entries = pose_catalog.world_entries("pose")
    for key, animation, people in (("p-wave", "wave", 1), ("p-bow", "bow", 1),
                                   ("p-lost", "lost", 1), ("p-hug", "hug", 2)):
        entries[key] = dict(participants=people, animation=animation, group="stand", places=1, prompt=key)
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()
    clips.replace_world_transitions([])
    for name, gender in (("Ava", "female"), ("Ben", "male")):
        save_character_profile(name, {"current_location": "", "language": "en", "gender": gender},
                               create_new=True)

    with patch("app.models.account.get_all_avatars", return_value={"Ava"}):
        M.note_switch("Ben", "p-wave", "p-bow")
        assert rows() == {}, rows()
        print("[1] PASS: a figure without an avatar is not counted")

        set_pose_intent("Ava", "p-wave")
        assert rows() == {("standing", "p-wave", "", ""): ("female", 1, ["Ava"])}, rows()
        assert listed()[("standing", "p-wave", "", "")]["ready"] is True
        print("[2] PASS: the first pose counts from standing, with the set")

        for pose in ("p-bow", "p-wave", "p-bow", "p-bow"):
            set_pose_intent("Ava", pose)
        got = rows()
        assert got[("p-wave", "p-bow", "", "")][1] == 2 and got[("p-bow", "p-wave", "", "")][1] == 1, got
        assert len(got) == 3, got
        print("[3] PASS: each switch once, the same pose never")

        clips.replace_world_transitions([{"from": "p-wave", "to": "p-bow", "kind": "wave-bow", "accel": 0}])
        assert ("p-wave", "p-bow", "", "") not in listed() and rows()[("p-wave", "p-bow", "", "")][1] == 2
        print("[4] PASS: a rule hides its row")

        clear_pose_intent("Ava")
        assert rows()[("p-bow", "standing", "", "")][1] == 1
        set_pose_intent("Ava", "p-bow")
        before = rows()
        clear_pose_intent("Ava", arriving=True)
        after = rows()
        assert after[("standing", "p-bow", "", "")][1] == 1 and ("p-bow", "standing", "", "") in after
        assert after[("p-bow", "standing", "", "")][1] == before[("p-bow", "standing", "", "")][1] == 1
        set_pose_intent("Ava", "p-wave", arriving=True)
        assert rows()[("walking", "p-wave", "", "")][1] == 1
        print("[5] PASS: standing up counts, an arrival's clear does not, an arrival pose comes from walking")

        departure_bridge("Ava")
        assert rows()[("p-wave", "walking", "", "")][1] == 1
        print("[6] PASS: setting off with a pose counts pose -> walking")

        ben = get_character_profile("Ben")
        ben["interaction"] = {"id": "i1", "pose_key": "p-hug", "role": "b", "members": {"a": "Ava", "b": "Ben"}}
        M.note_switch("Ben", "p-hug", "standing", profile=ben)
        assert rows()[("p-hug", "standing", "b", "")] == ("male", 1, ["Ben"]), rows()
        ended = {k: v for k, v in ben.items() if k != "interaction"}
        ended["last_interaction_result"] = {"pose_key": "p-hug", "members": {"a": "Ava", "b": "Ben"}}
        M.note_switch("Ben", "p-hug", "standing", profile=ended)
        assert rows()[("p-hug", "standing", "b", "")][1] == 2
        other = dict(ended, last_interaction_result={"pose_key": "p-wave", "members": {"a": "Ava", "b": "Ben"}})
        M.note_switch("Ben", "p-hug", "standing", profile=other)
        assert rows()[("p-hug", "standing", "b", "")][1] == 2
        print("[7] PASS: a partner counts with its role, also right after the end")

        M.note_switch("Ava", "p-lost", "p-wave")
        lost = listed()[("p-lost", "p-wave", "", "")]
        assert lost["ready"] is False and lost["problem"] == "p-lost: pose animation missing from library", lost
        print("[8] PASS: a pose without its clip is listed but not ready")

        assert M.dismiss("p-lost", "p-wave", cset="female")
        assert ("p-lost", "p-wave", "", "") not in listed()
        assert not M.dismiss("p-none", "p-wave")
        from app.routes import poses
        from fastapi import HTTPException
        from starlette.requests import Request

        async def post(body):
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            return await poses.dismiss_transition_miss(
                Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive), _={})

        answer = asyncio.run(poses.transition_misses(_={}))["misses"]
        assert answer == M.suggestions()
        try:
            asyncio.run(post({"start_pose": "p-none", "target_pose": "p-wave"}))
            raise AssertionError("unknown row dismissed")
        except HTTPException as e:
            assert e.status_code == 404
        assert asyncio.run(post({"start_pose": "p-wave", "target_pose": "walking", "cset": "female"})) == {"ok": True}
        print("[9] PASS: dismiss and the routes")


if __name__ == "__main__":
    main()
