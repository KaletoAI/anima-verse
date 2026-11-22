#!/usr/bin/env python3
"""Quiet narration: the start / switch / end line of a pose a package marks
quiet stays in what the characters PERCEIVE (the prompt view) and leaves the
player's chat transcript (``GET /play/scene``). Plan pair scene, Task 7.

Usage:
    ./.venv/bin/python scripts/smoke_quiet_narration.py

Throwaway storage and world DB; no server, nothing generated. Two
collaborators are stubbed so the numbers are hand-derivable:
``perception._resolve_presence`` (exactly Aveline and Torvin stand in the
room, nobody else in earshot) and ``perception.addressable_for`` inside the
route (Torvin). The lines themselves go through the REAL
``interaction_engine._narrate`` -> ``perception.record_utterance`` -> SQLite,
and the route function ``play.play_scene`` is called directly.

Hand-derived expectations:

[1] ``pose_scene.quiet(pose_key)`` asks provider ``scene.quiet_narration``
    (multiple=True, any True = quiet):
      no provider                                   -> False
      one contributor answering False for every key -> False for "quiet_pose"
      plus one answering True for "quiet_pose" only -> True for "quiet_pose",
                                                       False for "plain_pose"
      plus one that raises                          -> the same two answers
                                                       (a raising provider is skipped)
      an empty pose key                             -> False (nothing is asked)

[2] Three lines are narrated in the room, in this order (English avatar, the
    pose label of an unknown key is the key itself):
      A  start of "quiet_pose", quiet=quiet("quiet_pose") = True
      B  start of "plain_pose", quiet=quiet("plain_pose") = False
      C  the invitation to "quiet_pose" — an invitation never passes quiet
    Prompt view ``get_character_room_stream("Torvin", ...)`` (default
    include_quiet=True): all three, A B C -> 3 lines.
    ``/play/scene`` for the avatar Aveline: A drops, B and C stay -> 2 lines,
    contents [B, C]. The utterance of A carries meta.quiet = True, B and C
    carry no quiet key.

[3] Wiring (source check over the two engines, AST): every ``_narrate`` call
    whose literal key is a start / switch / stop line of a pose
    ("{actor} and {partner} start {pose}.", "... switch to {pose}.",
    "... stop {pose}.", the conditional switch/start expression) passes a
    ``quiet=`` keyword: interaction_engine has 3 such call sites (start of a
    group, start-or-switch of a pair, the end). The invitation lines
    ("{inviter} suggests {pose} to {invitee}.") pass none.
    prop_action_engine: the settle line (``_SETTLE_LINES``) and the leave /
    wake lines of ``_narrate_finish`` pass ``quiet=`` (3 call sites:
    settle, wake, leave); its invitation line passes none.
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="quiet-narration-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(STORAGE / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="quiet-narration-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import hooks, perception, pose_scene  # noqa: E402
from app.core import interaction_engine as IE  # noqa: E402
from app.models import perception_store  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'}  {label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


CAP = "scene.quiet_narration"

# --- [1] pose_scene.quiet ----------------------------------------------------
check("no provider -> not quiet", pose_scene.quiet("quiet_pose"), False)
hooks.register_provider(CAP, lambda pose_key: False, owner="smoke_never", multiple=True)
check("one contributor saying False -> not quiet", pose_scene.quiet("quiet_pose"), False)
hooks.register_provider(CAP, lambda pose_key: pose_key == "quiet_pose",
                        owner="smoke_marks", multiple=True)
check("any True -> quiet", pose_scene.quiet("quiet_pose"), True)
check("a pose nobody marks -> not quiet", pose_scene.quiet("plain_pose"), False)


def _boom(pose_key):
    raise RuntimeError("provider failure")


hooks.register_provider(CAP, _boom, owner="smoke_boom", multiple=True)
check("a raising contributor is skipped (quiet)", pose_scene.quiet("quiet_pose"), True)
check("a raising contributor is skipped (plain)", pose_scene.quiet("plain_pose"), False)
check("empty pose key -> not quiet", pose_scene.quiet(""), False)

# --- [2] the transcripts ------------------------------------------------------
AVATAR, PARTNER = "Aveline", "Torvin"
for who in (AVATAR, PARTNER):
    save_character_profile(who, {"name": who, "language": "en",
                                 "current_location": "loc", "current_room": "room"},
                           create_new=True)
set_active_character(AVATAR)
perception._resolve_presence = lambda loc, room, **kw: ([AVATAR, PARTNER], [], [])

LINE_A = f"{AVATAR} and {PARTNER} start quiet_pose."
LINE_B = f"{AVATAR} and {PARTNER} start plain_pose."
LINE_C = f"{AVATAR} suggests quiet_pose to {PARTNER}."
IE._narrate(AVATAR, "{actor} and {partner} start {pose}.", actor=AVATAR, partner=PARTNER,
            pose_key="quiet_pose", quiet=pose_scene.quiet("quiet_pose"))
IE._narrate(AVATAR, "{actor} and {partner} start {pose}.", actor=AVATAR, partner=PARTNER,
            pose_key="plain_pose", quiet=pose_scene.quiet("plain_pose"))
IE._narrate(AVATAR, "{inviter} suggests {pose} to {invitee}.", inviter=AVATAR,
            invitee=PARTNER, pose_key="quiet_pose")

prompt = [r["content"] for r in perception_store.get_character_room_stream(PARTNER, "loc", "room")]
check("prompt view keeps every line, quiet included", prompt, [LINE_A, LINE_B, LINE_C])
utter = perception_store.get_room_utterances("loc", "room")
check("meta.quiet of the three utterances",
      [(u["meta"] or {}).get("quiet") for u in utter], [True, None, None])

from app.routes import play  # noqa: E402
perception.addressable_for = lambda name: [PARTNER]
payload = play.play_scene(user=None)
check("/play/scene drops the quiet line, keeps the rest",
      [ln["content"] for ln in payload["scene"]], [LINE_B, LINE_C])

# --- [3] wiring -------------------------------------------------------------
SCENE_KEYS = ("start {pose}.", "switch to {pose}.", "stop {pose}.")


def narrate_calls(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_narrate" and len(node.args) >= 2):
            yield node


def key_text(node):
    return " ".join(c.value for c in ast.walk(node)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str))


def has_quiet(call):
    return any(k.arg == "quiet" for k in call.keywords)


ie_path = ROOT / "app/core/interaction_engine.py"
scene_calls = [c for c in narrate_calls(ie_path)
               if any(k in key_text(c.args[1]) for k in SCENE_KEYS)]
check("interaction_engine: start/switch/stop call sites", len(scene_calls), 3)
check("…each passes quiet=", [has_quiet(c) for c in scene_calls], [True] * 3)
invites = [c for c in narrate_calls(ie_path) if "suggests" in key_text(c.args[1])]
check("interaction_engine: invitation lines pass no quiet",
      [has_quiet(c) for c in invites], [False] * len(invites))
check("interaction_engine: there is an invitation line", len(invites) >= 1, True)

pa_path = ROOT / "app/core/prop_action_engine.py"
pa_calls = list(narrate_calls(pa_path))
pa_quiet = [c for c in pa_calls if has_quiet(c)]
check("prop_action_engine: settle + wake + leave pass quiet=", len(pa_quiet), 3)
check("prop_action_engine: its invitation line passes none",
      [has_quiet(c) for c in pa_calls if "suggests" in key_text(c.args[1])], [False])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
