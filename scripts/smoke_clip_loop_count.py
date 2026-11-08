#!/usr/bin/env python3
"""Smoke run for the REPEAT COUNT of a looped animation clip — the sidecar
field ``loop_count`` beside ``loop`` (docs/schnittstellen-3d.md § A8, § A8a,
§ A8c).

Builds a throwaway clip tree and points ANIMATION_CLIPS_DIR at it — the real
``shared/models/clips`` is never read or written. No server, no real world.

THE RULE, from which every expectation below is derived by hand:

  * ``loop_count`` is a whole number 1..99 = the cycles a LOOPED clip plays
    before it holds its last frame; absent = endless. Only a looped clip has
    one: with ``loop`` false the count is None whatever the sidecar says.
  * ``clip_play_s(meta)`` = how long the clip plays before it holds:
    ``duration_s`` for a one-shot, ``duration_s × loop_count`` for a counted
    loop, None for an endless loop.
  * It is saved like the loop flag: into the SHARED ``<kind>.json`` beside the
    clip and into every variant's own sidecar of that kind in that set;
    ``null`` removes the key.

The tree (stub FBX files, nothing parses them):

    <root>/spell_casting.fbx + spell_casting.json {duration_s 5.0, loop true}
    <root>/spell_casting_02.fbx + spell_casting_02.json (own numbers, 4.0 s, loop true)
    <root>/hug__a.fbx hug__b.fbx + hug.json  {pair, duration_s 2.0, loop false}

Derived expectations:

  [1] valid_loop_count: 3 -> 3, 1 -> 1, 99 -> 99, None -> None; 0, 100, "x",
      "3", 2.5, True each raise ClipLibraryError.
  [2] clip_loop_count / clip_play_s:
        {loop true, loop_count 3, duration_s 5.0} -> 3 / 5.0 × 3 = 15.0
        {loop true, duration_s 5.0}               -> None / None (endless)
        {loop false, loop_count 3, duration_s 1.5} -> None / 1.5 (once)
        {loop true, loop_count 0, duration_s 2.0} -> None / None (junk = none)
        {loop true, loop_count 2}  (no duration)  -> 2 / None
  [3] set_clip_loop_count("free", "spell_casting.fbx", 3) writes
      ``"loop_count": 3`` into spell_casting.json AND spell_casting_02.json;
      the listing then says loop_count 3 for both root files (and keeps
      loop true). A refused value (0) raises and leaves both at 3. ``None``
      removes the key from both files -> listing None (endless).
  [4] The PATCH route (``patch_animation_clip``): body {loop_count: 3} -> 200,
      the answer's clips carry loop_count 3; {loop_count: 0}, {100}, {"x"},
      {true} -> 400 and the sidecar keeps 3; {loop_count: null} -> 200, key
      gone. A one-shot pair: {loop_count: 3} on hug__a.fbx is stored in
      hug.json but the listing still says None (no loop -> no count).
  [5] The interaction payload (§ A8a): a stored interaction with loop true +
      loop_count 3 hands out loop_count 3; with loop false and a stray
      loop_count 3 it hands out None; an interaction stored without the key
      (started before the field existed) hands out None = endless.
  [6] The spell (``spell_engine.end_cast_pose_after_clip``): the cast pose's
      clip is spell_casting with loop_count 3 -> the pose ends after
      5.0 × 3 = 15.0 s (one timer of 15.0 s). The timer clears the pose only
      while it is still the cast pose and this cast the latest one: a second
      cast replaces the token, so the first timer does nothing; a pose changed
      meanwhile is left alone. Endless (no loop_count) -> None, no timer.
  [7] The finale (``prop_action_engine._finale_duration_s``) is checked in
      ``scripts/smoke_prop_action_finale.py`` [12]: loop_count 3 on a 1.5 s
      finale -> duration_s 4.5, loop_count 3.

Usage:  ./.venv/bin/python scripts/smoke_clip_loop_count.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLIPS = Path(tempfile.mkdtemp(prefix="clip-loop-count-smoke-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-loop-count-world-"))
# MUST be set before paths is imported — otherwise the smoke would scan (and
# then WRITE INTO) the repo's real clip library.
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from fastapi import HTTPException  # noqa: E402

from app.core import animation_clips as ac  # noqa: E402
from app.core import interaction_engine as ie  # noqa: E402
from app.core import spell_engine as se  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def sidecar(rel: str) -> dict:
    return json.loads((CLIPS / rel).read_text(encoding="utf-8"))


def listing() -> dict:
    return {v["rel"]: (v["loop"], v["loop_count"]) for v in
            (ac.clip_view(e) for e in ac.clip_entries())}


(CLIPS / "spell_casting.fbx").write_bytes(b"spell")
write(CLIPS / "spell_casting.json", {"kind": "spell_casting", "duration_s": 5.0, "loop": True})
(CLIPS / "spell_casting_02.fbx").write_bytes(b"spell-2")
write(CLIPS / "spell_casting_02.json", {"kind": "spell_casting", "duration_s": 4.0, "loop": True})
(CLIPS / "hug__a.fbx").write_bytes(b"hug-a")
(CLIPS / "hug__b.fbx").write_bytes(b"hug-b")
write(CLIPS / "hug.json", {"kind": "hug", "pair": True, "duration_s": 2.0, "loop": False})
ac.reload_clip_caches()

print("\n[1] valid_loop_count")
for raw, want in ((3, 3), (1, 1), (99, 99), (None, None)):
    check(f"{raw!r} -> {want!r}", ac.valid_loop_count(raw) == want)
for raw in (0, 100, "x", "3", 2.5, True):
    try:
        ac.valid_loop_count(raw)
        check(f"{raw!r} refused", False, "accepted")
    except ac.ClipLibraryError:
        check(f"{raw!r} refused", True)

print("\n[2] clip_loop_count / clip_play_s")
for meta, count, play in (
        ({"loop": True, "loop_count": 3, "duration_s": 5.0}, 3, 15.0),
        ({"loop": True, "duration_s": 5.0}, None, None),
        ({"loop": False, "loop_count": 3, "duration_s": 1.5}, None, 1.5),
        ({"loop": True, "loop_count": 0, "duration_s": 2.0}, None, None),
        ({"loop": True, "loop_count": 2}, 2, None)):
    check(f"{meta} -> {count} / {play}",
          (ac.clip_loop_count(meta), ac.clip_play_s(meta)) == (count, play),
          str((ac.clip_loop_count(meta), ac.clip_play_s(meta))))

print("\n[3] set_clip_loop_count writes the kind in its set")
views = ac.set_clip_loop_count("free", "spell_casting.fbx", 3)
check("shared sidecar 3", sidecar("spell_casting.json").get("loop_count") == 3)
check("variant's own sidecar 3", sidecar("spell_casting_02.json").get("loop_count") == 3)
check("returned views carry 3", sorted(v["loop_count"] for v in views) == [3, 3])
now = listing()
check("listing", now["spell_casting.fbx"] == (True, 3) and now["spell_casting_02.fbx"] == (True, 3), str(now))
try:
    ac.set_clip_loop_count("free", "spell_casting.fbx", 0)
    check("0 refused", False)
except ac.ClipLibraryError:
    check("0 refused, nothing written", sidecar("spell_casting.json").get("loop_count") == 3)
ac.set_clip_loop_count("free", "spell_casting.fbx", None)
check("null removes the key", "loop_count" not in sidecar("spell_casting.json")
      and "loop_count" not in sidecar("spell_casting_02.json"))
check("listing endless", listing()["spell_casting.fbx"] == (True, None))

print("\n[4] the PATCH route")
from app.routes.assets import patch_animation_clip  # noqa: E402


class Body:
    def __init__(self, data):
        self.data = data

    async def json(self):
        return self.data


def patch_route(rel, body):
    try:
        return 200, asyncio.run(patch_animation_clip("free", rel, Body(body), {}))
    except HTTPException as e:
        return e.status_code, e.detail


status, answer = patch_route("spell_casting.fbx", {"loop_count": 3})
check("{loop_count: 3} -> 200", status == 200 and {c["loop_count"] for c in answer["clips"]} == {3},
      f"{status} {answer if status != 200 else ''}")
for bad in (0, 100, "x", True):
    status, detail = patch_route("spell_casting.fbx", {"loop_count": bad})
    check(f"{bad!r} -> 400, sidecar keeps 3",
          status == 400 and sidecar("spell_casting.json").get("loop_count") == 3, f"{status} {detail}")
status, _ = patch_route("spell_casting.fbx", {"loop_count": None})
check("{loop_count: null} -> 200, key gone", status == 200 and "loop_count" not in sidecar("spell_casting.json"))
status, answer = patch_route("hug__a.fbx", {"loop_count": 3})
check("one-shot pair: stored, listing None",
      status == 200 and sidecar("hug.json").get("loop_count") == 3
      and {c["loop_count"] for c in answer["clips"]} == {None},
      str([c["loop_count"] for c in answer["clips"]]) if status == 200 else str(answer))

print("\n[5] the interaction payload")
NOW = GameTime.parse("Y0001-D001T12:00:10")


def inter(**extra):
    return {"interaction": dict(id="i1", kind="hug", role="a", members={"a": "Ann", "b": "Bob"},
                                started_at_game="Y0001-D001T12:00:00", clip_duration_s=2.0, **extra)}


check("loop + 3 -> 3", ie.payload_for("Ann", inter(loop=True, loop_count=3), NOW)["loop_count"] == 3)
check("one-shot + stray 3 -> None",
      ie.payload_for("Ann", inter(loop=False, loop_count=3), NOW)["loop_count"] is None)
check("stored without the key -> None (endless)",
      ie.payload_for("Ann", inter(loop=True), NOW)["loop_count"] is None)

print("\n[6] the spell ends its cast pose with its clip")
write(CLIPS / "spell_casting.json", {"kind": "spell_casting", "duration_s": 5.0, "loop": True, "loop_count": 3})
ac.reload_clip_caches()
PROFILE = {"pose_key": "casting a spell"}
timers = []


class FakeTimer:
    def __init__(self, seconds, fn, args=()):
        self.seconds, self.fn, self.args, self.daemon = seconds, fn, args, False
        timers.append(self)

    def start(self):
        pass


cleared = []
with patch("app.models.character.get_character_profile", lambda name: dict(PROFILE)), \
        patch("app.core.movement.played_pose_kind", lambda key: "spell_casting" if key == "casting a spell" else ""), \
        patch("app.core.animation_sets.resolve_sets", lambda name, profile=None: []), \
        patch("app.models.character.clear_pose_intent", lambda name: cleared.append(name)), \
        patch.object(se.threading, "Timer", FakeTimer):
    seconds = se.end_cast_pose_after_clip("Ann")
    check("5.0 × 3 = 15.0 s", seconds == 15.0 and [t.seconds for t in timers] == [15.0],
          f"{seconds} {[t.seconds for t in timers]}")
    first = timers[0]
    se.end_cast_pose_after_clip("Ann")
    first.fn(*first.args)
    check("a second cast: the first timer does nothing", cleared == [])
    second = timers[1]
    PROFILE["pose_key"] = "sitting"
    second.fn(*second.args)
    check("a pose changed meanwhile is left alone", cleared == [])
    PROFILE["pose_key"] = "casting a spell"
    se.end_cast_pose_after_clip("Ann")
    timers[2].fn(*timers[2].args)
    check("the latest cast's timer clears the pose", cleared == ["Ann"])
    write(CLIPS / "spell_casting.json", {"kind": "spell_casting", "duration_s": 5.0, "loop": True})
    ac.reload_clip_caches()
    check("endless -> None, no timer", se.end_cast_pose_after_clip("Ann") is None and len(timers) == 3)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} — {FAILURES}")
    sys.exit(1)
print("ALL OK")
