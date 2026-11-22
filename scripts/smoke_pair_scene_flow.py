#!/usr/bin/env python3
"""ONE free pair scene driven end to end through the real core (plan pair
scene, Task 9 — the headless integration check): interaction_engine starts
the pair, pose_scene beats it, a package fills a meter, asks for a tempo,
starts the finale and ends the scene, and the start / end lines stay out of
the player's transcript while the characters still perceive them.

Usage:
    ./.venv/bin/python scripts/smoke_pair_scene_flow.py

Runs on the temporary world of `smoke_prop_action_runs.py` (its fixtures,
`paths.init(<tmp>)` first): no server, no real world DB, no real clips,
nothing generated.

THE FAKE PACKAGE (registered here, neutral)
===========================================
- hook `scene.active`: the meter of the LEAD role's member rises by
  FILL = 5 points per GAME second of the beat (`delta_game_s`), capped at 100.
  The first beat that reaches 100 calls `pose_scene.begin_finale(scene, lead,
  tempo=0.5)` and `pose_scene.end_after_finale(scene, lead, 3)`.
- provider `scene.tempo`: 0.2 + 0.8 * meter / 100 of the lead member.
- provider `scene.meters`: one row `{name: lead, value: meter}`.
- provider `scene.quiet_narration`: True for the scene's pose only.
- hook `scene.finale_done`: the package's own closing line CLOSING, a storyteller
  line told literally and NOT quiet.

THE FIXTURE
===========
Two characters A and B of `authored_pair` in one room. A free pose
`flow-pair` (2 participants, a group whose poses need no marker, no stored
lead role -> lead role "a") with the pair clip `flow-pair` (roles a/b,
duration 2 s, looping, no gender assignment -> the initiator A plays "a")
and the finale clip `fin-flow` (pair halves, duration_s 1.2, loop_count 3).
pose_scene's SYSTEM clock (`utc_now`) and MOTION clock (`motion_time`) are
pinned to the same hand-moved second t; the game clock moves by
`set_game_time`. The process's first `advance` (the boot step) runs before
the start, so the start itself is the first beat's baseline.

EXPECTATIONS, DERIVED BY HAND
=============================
[1] START at t = 0, game g: `start_interaction(A, B, flow-pair)` -> id I,
    A on role a. A payload read at t = 0 makes the clip clock: clip_s 0.0,
    tempo 1.0 (no beat yet asked the package: the tempo is 1).
[2] BEAT 1 at t = 10, game g + 10: the clock steps at the old tempo,
    clip_s = 0 + 10 * 1.0 = 10.0; the package is asked with meter 0 ->
    tempo 0.2 + 0.8 * 0 = 0.2; then `scene.active` (delta_game_s 10, lead_role
    a, roles {a: A, b: B}) -> meter 0 + 5 * 10 = 50.
    Payload at t = 10: clip_s 10.0, tempo 0.2. Meters row of I: [{A, 50.0}].
[3] BEAT 2 at t = 20, game g + 20: clip_s = 10 + 10 * 0.2 = 12.0; tempo
    0.2 + 0.8 * 50 / 100 = 0.6; the hook: meter 50 + 50 = 100 -> finale at
    tempo 0.5 + end 3 s after it.
    Payload at t = 20: clip_s 12.0, tempo 0.6. At t = 25: 12 + 5 * 0.6 =
    15.0, tempo 0.6. Meters row: [{A, 100.0}].
[4] THE FINALE BLOCK of A at t = 20.4: kind fin-flow, role a, alt "",
    elapsed_s 0.4, loop_count 3, tempo 0.5,
    duration_s = 1.2 * 3 / 0.5 = 7.2. B has none. `scene.finale_started` fired
    once (scene I, A, fin-flow, flow-pair).
[5] THE END: due 20 + 7.2 + 3 = 30.2. `advance` at t = 30.1 (game time
    unchanged: no beat) leaves I running; at t = 30.2 it ends I — neither A
    nor B has an interaction — and `scene.finale_done` fired for A. Two beats
    in all reached the hook.
[6] QUIET NARRATION: the start line "A and B start <label>." and the end line
    "A and B stop <label>." (<label> = `pose_label(flow-pair, "en")`) are in
    B's perception stream (the prompt view) and carry meta.quiet True; the
    player transcript `/play/scene` of the avatar A has neither of them. The
    package's closing line (told at the scene end, after the end line) is
    in both: the transcript is not simply empty.
"""
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F, clips, pose_catalog = RUNS.F, RUNS.clips, RUNS.pose_catalog
F.paths.init(F.ROOT / "world")
from app.core import hooks, pose_scene as S                              # noqa: E402
from app.core import interaction_engine as IE                            # noqa: E402
from app.core.game_time import GameDuration                             # noqa: E402
from app.core.timeutils import utc_now                                  # noqa: E402

POSE, FINALE = "flow-pair", "fin-flow"
FILL = 5.0                     # meter points per GAME second of a beat
OWNER = "smoke.pair_scene_flow"
FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'}  {label}: {actual!r}" + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


# --- the fixture ------------------------------------------------------------
A, B, _target, _pid = RUNS.authored_pair()
directory = F.ROOT / "clips"
for role in ("a", "b"):
    (directory / f"{POSE}__{role}.fbx").write_bytes(b"private pair fixture")
    (directory / f"{FINALE}__{role}.fbx").write_bytes(b"private finale fixture")
(directory / f"{POSE}.json").write_text(json.dumps(dict(
    kind=POSE, pair=True, duration_s=2, loop=True,
    geometry=dict(roles=dict(a=dict(anchor_xz_m=[-.3, 0]), b=dict(anchor_xz_m=[.3, 0]))))))
(directory / f"{FINALE}.json").write_text(json.dumps(dict(
    kind=FINALE, pair=True, duration_s=1.2, loop=False, loop_count=3)))
clips._clear_entries_cache()
entries = pose_catalog.world_entries("pose")
entries[POSE] = dict(participants=2, animation=POSE, group=pose_catalog.placeless_groups()[0],
                     finale_animation=FINALE, prompt="Two people together")
pose_catalog.replace_world_entries("pose", entries)
pose_catalog.reload_catalogs()

# --- the fake package -------------------------------------------------------
METER = {}
BEATS = []
EVENTS = []


def lead_of(roles, lead_role):
    return (roles or {}).get(lead_role or "a", "")


def on_active(**beat):
    BEATS.append(beat)
    lead = lead_of(beat["roles"], beat["lead_role"])
    before = METER.get(lead, 0.0)
    METER[lead] = min(100.0, before + FILL * float(beat["delta_game_s"]))
    if before < 100.0 <= METER[lead]:
        EVENTS.append(("begin_finale", S.begin_finale(beat["scene_id"], lead, tempo=0.5)))
        EVENTS.append(("end_after_finale", S.end_after_finale(beat["scene_id"], lead, 3)))


def tempo(*, scene_id, members, roles, pose_key, lead_role):
    return 0.2 + 0.8 * METER.get(lead_of(roles, lead_role), 0.0) / 100.0


def meters(*, scene_id, members, pose_key):
    lead = members[0] if members else ""
    return [dict(name=lead, value=METER.get(lead, 0.0))]


CLOSING = "The scene comes to a close."


def on_finale_done(**kw):
    """The package's own closing line: a storyteller line that is NOT quiet."""
    EVENTS.append(("scene.finale_done", kw))
    IE._narrate(kw["name"], CLOSING, literal=True)


hooks.register("scene.active", on_active, tag=OWNER)
hooks.register("scene.finale_started", lambda **kw: EVENTS.append(("scene.finale_started", kw)), tag=OWNER)
hooks.register("scene.finale_done", on_finale_done, tag=OWNER)
hooks.register_provider("scene.tempo", tempo, owner=OWNER)
hooks.register_provider("scene.meters", meters, owner=OWNER)
hooks.register_provider("scene.quiet_narration", lambda pose_key: pose_key == POSE,
                        owner=OWNER, multiple=True)

# --- the clocks -------------------------------------------------------------
T0 = utc_now()
NOW = [0.0]
patch.object(S, "utc_now", lambda: T0 + timedelta(seconds=NOW[0])).start()
patch.object(S, "motion_time", lambda: float(NOW[0])).start()


def at(seconds):
    NOW[0] = float(seconds)


def game_plus(seconds):
    F.set_game_time(F.game_time() + GameDuration.of(seconds=seconds))


def advance():
    return S.advance(F.game_time())


def payload(name):
    row = IE.payload_for(name, F.C.get_character_profile(name), F.game_time(), 1.0) or {}
    return row.get("clip_s"), row.get("tempo")


def meter_values(scene_id):
    return [(m["name"], m["value"]) for m in S.meters(scene_id, A)]


F.W.set_world_frozen(False)
advance()                                    # the boot step: notes the process start

# [1] the start
at(0)
inter = IE.start_interaction(A, B, POSE)
I = inter["id"]
check("[1] A plays role a", inter["role"], "a")
check("[1] payload at t=0 (clip_s, tempo)", payload(A), (0.0, 1.0))

# [2] beat 1
at(10)
game_plus(10)
advance()
check("[2] one beat reached the package", len(BEATS), 1)
beat = BEATS[0]
check("[2] beat: scene, kind, lead role, roles",
      (beat["scene_id"], beat["kind"], beat["lead_role"], beat["roles"]),
      (I, "interaction", "a", {"a": A, "b": B}))
check("[2] beat: delta_game_s", round(beat["delta_game_s"], 3), 10.0)
check("[2] meter after beat 1", METER.get(A), 50.0)
check("[2] payload at t=10", payload(A), (10.0, 0.2))
check("[2] B reads the same clock", payload(B), (10.0, 0.2))
check("[2] meters row", meter_values(I), [(A, 50.0)])

# [3] beat 2 -> finale
at(20)
game_plus(10)
advance()
check("[3] two beats", len(BEATS), 2)
check("[3] meter after beat 2", METER.get(A), 100.0)
check("[3] the package's calls", [(k, v) for k, v in EVENTS if k in ("begin_finale", "end_after_finale")],
      [("begin_finale", dict(ok=True, reason="")), ("end_after_finale", True)])
check("[3] payload at t=20", payload(A), (12.0, 0.6))
at(20.4)
block = S.finale_for(A) or {}
block.pop("id", None)
check("[4] finale block of A at t=20.4", block,
      dict(kind=FINALE, role="a", alt="", elapsed_s=0.4, duration_s=7.2, loop_count=3, tempo=0.5))
check("[4] B has no finale", S.finale_for(B), None)
started = [kw for k, kw in EVENTS if k == "scene.finale_started"]
check("[4] scene.finale_started once",
      [(s["scene_id"], s["name"], s["kind"], s["pose_key"]) for s in started], [(I, A, FINALE, POSE)])
at(25)
check("[3] payload at t=25", payload(A), (15.0, 0.6))
check("[3] meters row", meter_values(I), [(A, 100.0)])

# [5] the end, exactly 3 s after the finale has played
at(30.1)
advance()
check("[5] t=30.1: still running", (IE.get_interaction(A) or {}).get("id"), I)
at(30.2)
advance()
check("[5] t=30.2: A's interaction ended", IE.get_interaction(A), None)
check("[5] t=30.2: B's interaction ended", IE.get_interaction(B), None)
check("[5] scene.finale_done for A", [kw["name"] for k, kw in EVENTS if k == "scene.finale_done"], [A])
check("[5] beats in all", len(BEATS), 2)

# [6] quiet narration
from app.core.pose_catalog import pose_label                             # noqa: E402
from app.models import perception_store                                  # noqa: E402
from app.models.account import set_active_character                      # noqa: E402
from app.models.character import get_character_current_location, get_character_current_room  # noqa: E402
label = pose_label(POSE, "en")
START, STOP = f"{A} and {B} start {label}.", f"{A} and {B} stop {label}."
loc, room = get_character_current_location(A), get_character_current_room(A)
stream = [r["content"] for r in perception_store.get_character_room_stream(B, loc, room)]
check("[6] B perceives the start line", START in stream, True)
check("[6] B perceives the end line", STOP in stream, True)
quiet = {u["content"]: (u.get("meta") or {}).get("quiet")
         for u in perception_store.get_room_utterances(loc, room)}
check("[6] both lines carry meta.quiet", (quiet.get(START), quiet.get(STOP)), (True, True))
set_active_character(A)
from app.routes import play                                              # noqa: E402
scene = [ln["content"] for ln in play.play_scene(user=None)["scene"]]
check("[6] /play/scene has no start line", START in scene, False)
check("[6] /play/scene has no end line", STOP in scene, False)
check("[6] /play/scene shows the package's closing line", CLOSING in scene, True)
check("[6] B perceives the closing line too", CLOSING in stream, True)

hooks.unregister_owned_providers(OWNER)
print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
