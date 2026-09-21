#!/usr/bin/env python3
"""Game-clock cooldowns: a clock set BACKWARDS must not stall the world, a
fresh start must not charge an hour of stat drift, and an event window
measured in GAME hours must not be compared against REAL hours.

Usage:
    ./.venv/bin/python scripts/smoke_game_clock_cooldowns.py
    ./.venv/bin/python scripts/smoke_game_clock_cooldowns.py --head
        (--head runs the very same checks against the HEAD version of the four
         modules, loaded side by side under a different module name — that is
         how the "fails before the fix" half was confirmed. It needs git and a
         clean HEAD copy of the files, nothing else; it changes no git state.)

No server, no real world DB: throwaway storage via ``paths.init``. The GAME
clock is a stub — ``game_time`` is rebound on each module under test, so the
checks never depend on the real world anchors.

Review 2026-09-20, findings SIM-3 and SIM-4.

WHAT IS WRONG (SIM-3)
  ``activity_engine._LAST_HOURLY_TICK``, ``npc_actions._last_action`` and
  ``npc_scenes._last_scene`` are RAM-only GameTime stamps compared as
  ``now - last < interval``. ``GameTime.__sub__`` returns a signed
  ``GameDuration``, so a clock set backwards makes the delta NEGATIVE — which
  is smaller than any interval, and the hourly tick, the NPC action turns and
  the director scenes all stand still until the clock has caught up again.
  ``random_events.check_and_generate`` and the scheduler's game anchor already
  re-anchor on a negative delta; these three did not.
  Second half: after a RESTART the stamp dict is EMPTY, so the very first
  hourly tick fell straight through the guard and applied a full hour of
  ``bar_hourly`` at once.

WHAT IS WRONG (SIM-4)
  ``ttl_hours`` are GAME hours (app/models/events.py: ``expires_at`` is a
  canonical game stamp), but ``check_escalation`` measured half of them as
  REAL hours against the system stamp ``created_at``. Same mix-up in the
  per-location event cooldown.

EXPECTED VALUES, DERIVED BY HAND

  Part A — activity_engine.apply_hourly_status_tick, game clock stubbed,
  stamp dict emptied first (= a fresh process). "body runs" is counted at
  ``app.models.character.get_character_config``, which the tick body calls
  exactly once and nothing else on the path does.

    A1  first sight at game T0           -> body does NOT run; stamp := T0.
                                            (Old: stamp is None -> the guard
                                            falls through -> one full hour of
                                            bar_hourly on every restart.)
    A2  T0 + 30 game minutes             -> no run (1800 s < 3600 s); stamp
                                            still T0.
    A3  T0 + 60 game minutes             -> RUNS; stamp := T0 + 1 h.
    A4  clock set BACK 5 game hours, to
        T0 + 1h - 5h = T0 - 4h           -> no run, but stamp re-anchored to
                                            T0 - 4h.  (Old: stamp stays
                                            T0 + 1 h.)
    A5  one game hour after that,
        T0 - 3h                          -> RUNS — on schedule from the NEW
                                            now, 1 h after the set-back, not
                                            5 h + 1 h later.  (Old: delta =
                                            (T0-3h) - (T0+1h) = -4 h < 1 h,
                                            so nothing runs for 5 more game
                                            hours.)

  Part B — npc_actions.candidates(), interval 60 game minutes, one NPC.
    B1  no stamp yet                     -> NPC is a candidate (nothing to
                                            re-anchor; an action turn costs no
                                            accumulated state).
    B2  stamped at T0, clock T0 + 30 min -> not a candidate.
    B3  clock set BACK 5 game hours      -> not a candidate THIS pass, stamp
                                            re-anchored to the new now.
    B4  one game hour later              -> candidate again.  (Old: B4 stays
                                            empty; the NPC is mute for 5 more
                                            game hours.)

  Part C — npc_scenes.candidate_rooms(), same arithmetic, keyed per room.
    C1  stamped at T0, clock T0 + 30 min -> room not scheduled.
    C2  clock set BACK 5 game hours      -> not scheduled, stamp re-anchored.
    C3  one game hour later              -> scheduled again.  (Old: empty.)

  Part D — random_events.check_escalation, FACTOR 6 (one real second = six
  game seconds), a danger event with ttl_hours = 8 (the module's own default
  for the danger category). Half the TTL = 4 GAME hours = 4/6 real hours =
  40 REAL minutes.
    D1  39 real minutes after creation
        (= 3 h 54 min game)              -> no escalation.
    D2  40 real minutes after creation
        (= 4 h 00 min game)              -> escalates.  (Old: the code waited
                                            for 4 REAL hours, by which time
                                            the event — 8 game hours = 80 real
                                            minutes of TTL — was long deleted,
                                            so a danger event could NEVER
                                            escalate in an accelerated world.)

  Part E — random_events._try_generate_for_location, factor 6, cooldown
  2 GAME hours = 20 REAL minutes, one ambient event already at the location.
    E1  latest event 10 real minutes old
        (= 1 game hour)                  -> blocked by the cooldown.
    E2  latest event 20 real minutes old
        (= 2 game hours)                 -> generated.  (Old: 20 real minutes
                                            is far inside a 2 REAL hour
                                            cooldown -> blocked, i.e. at
                                            factor 6 the density collapsed to
                                            one event per 12 game hours.)
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="gameclock-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="gameclock-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402

CHECKED = 0
FAILURES = []


def check(label, got, expected):
    global CHECKED
    CHECKED += 1
    if got != expected:
        FAILURES.append(f"{label}: got {got!r}, expected {expected!r}")
        print(f"  FAIL {label}: {got!r} != {expected!r}")
    else:
        print(f"  ok   {label}: {got}")


# ---------------------------------------------------------------------------
# Module loading — live tree, or the HEAD twin for the "fails before" run
# ---------------------------------------------------------------------------
_HEAD_DIR = Path(tempfile.mkdtemp(prefix="gameclock-head-"))


def load_module(relpath, use_head):
    """Import ``relpath`` from the working tree, or — with ``use_head`` — the
    HEAD revision of the same file under a separate module name. The twin
    imports everything else absolutely, so it talks to the same app package."""
    modname = "app." + relpath[len("app/"):-len(".py")].replace("/", ".")
    if not use_head:
        return importlib.import_module(modname)
    src = subprocess.check_output(["git", "show", f"HEAD:{relpath}"],
                                  cwd=str(ROOT), text=True)
    twin = modname.replace(".", "_") + "__head"
    path = _HEAD_DIR / f"{twin}.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(twin, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[twin] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The stubbed clocks
# ---------------------------------------------------------------------------
T0 = GameTime.parse("Y0002-D100T12:00:00")


class GameClock:
    """A settable GAME clock (no real-time coupling) — Parts A-C."""

    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def shift(self, hours=0, minutes=0):
        self.now = self.now + GameDuration.of(hours=hours, minutes=minutes)


class PairedClock:
    """A real clock and a game clock coupled by ``factor`` — Parts D/E.

    ``advance_real(minutes)`` moves BOTH: the real clock by that many minutes,
    the game clock by ``factor`` times as much. That is exactly the relation
    ``timeutils.game_time`` computes from the world anchors.
    """

    def __init__(self, factor):
        self.factor = factor
        self.real0 = utc_now()
        self.game0 = T0
        self.offset_s = 0.0

    def advance_real(self, minutes):
        self.offset_s += minutes * 60.0

    def real(self):
        return self.real0 + timedelta(seconds=self.offset_s)

    def game(self):
        return self.game0 + GameDuration(int(round(self.offset_s * self.factor)))


def main(use_head):
    act_engine = load_module("app/core/activity_engine.py", use_head)
    npc_actions = load_module("app/core/npc_actions.py", use_head)
    npc_scenes = load_module("app/core/npc_scenes.py", use_head)
    random_events = load_module("app/core/random_events.py", use_head)

    import app.models.character as character
    import app.models.character_template as character_template
    import app.models.events as events_model
    # npc_scenes reaches into the LIVE npc_actions for its helpers even when we
    # test the HEAD twin — only the cooldown arithmetic under test differs.
    import app.core.npc_actions as live_npc_actions

    # -----------------------------------------------------------------------
    print("A) activity_engine.apply_hourly_status_tick")
    # -----------------------------------------------------------------------
    clock = GameClock(T0)
    act_engine.game_time = clock
    act_engine._LAST_HOURLY_TICK.clear()

    runs = {"n": 0}
    orig_profile = character.get_character_profile
    orig_config = character.get_character_config
    orig_feature = character_template.is_feature_enabled

    def counting_config(name):
        runs["n"] += 1
        return {}

    character.get_character_profile = lambda name: {}
    character.get_character_config = counting_config
    character_template.is_feature_enabled = lambda name, feat: True
    try:
        act_engine.apply_hourly_status_tick("Ada")
        check("A1 fresh start applies no stat change", runs["n"], 0)
        check("A1 stamp anchored at now",
              act_engine._LAST_HOURLY_TICK.get("Ada"), T0)

        clock.shift(minutes=30)
        act_engine.apply_hourly_status_tick("Ada")
        check("A2 half an hour later: still no run", runs["n"], 0)
        check("A2 stamp unchanged",
              act_engine._LAST_HOURLY_TICK.get("Ada"), T0)

        clock.shift(minutes=30)              # now T0 + 1 h
        act_engine.apply_hourly_status_tick("Ada")
        check("A3 one game hour later: runs once", runs["n"], 1)
        check("A3 stamp moved to now",
              act_engine._LAST_HOURLY_TICK.get("Ada"),
              T0 + GameDuration.of(hours=1))

        clock.shift(hours=-5)                # now T0 - 4 h
        act_engine.apply_hourly_status_tick("Ada")
        check("A4 clock set back 5 h: no run", runs["n"], 1)
        check("A4 stamp re-anchored to the new now",
              act_engine._LAST_HOURLY_TICK.get("Ada"),
              T0 - GameDuration.of(hours=4))

        clock.shift(hours=1)                 # now T0 - 3 h
        act_engine.apply_hourly_status_tick("Ada")
        check("A5 one hour after the set-back: runs", runs["n"], 2)
    finally:
        character.get_character_profile = orig_profile
        character.get_character_config = orig_config
        character_template.is_feature_enabled = orig_feature

    # -----------------------------------------------------------------------
    print("B) npc_actions.candidates")
    # -----------------------------------------------------------------------
    clock = GameClock(T0)
    npc_actions.game_time = clock
    npc_actions._last_action.clear()
    npc_actions._enabled = lambda: True
    npc_actions._interval = lambda: GameDuration.of(minutes=60)
    npc_actions._batch = lambda: 5
    npc_actions._in_party = lambda name: False
    npc_actions._is_busy = lambda name, profile: False
    npc_actions._in_chat = lambda name: False

    orig = {
        "list_temporary_npcs": character.list_temporary_npcs,
        "get_character_status": character.get_character_status,
        "get_character_current_location": character.get_character_current_location,
        "get_character_profile": character.get_character_profile,
    }
    character.list_temporary_npcs = lambda: ["Nico"]
    character.get_character_status = lambda name: ""
    character.get_character_current_location = lambda name="", profile=None: "tavern"
    character.get_character_profile = lambda name: {}
    try:
        check("B1 no stamp yet: candidate", npc_actions.candidates(), ["Nico"])

        npc_actions._last_action["Nico"] = T0
        clock.shift(minutes=30)
        check("B2 half an interval later: not a candidate",
              npc_actions.candidates(), [])

        clock.shift(hours=-5)                # now T0 - 4.5 h
        check("B3 clock set back 5 h: not a candidate this pass",
              npc_actions.candidates(), [])
        check("B3 stamp re-anchored to the new now",
              npc_actions._last_action.get("Nico"),
              T0 - GameDuration.of(hours=4, minutes=30))

        clock.shift(hours=1)
        check("B4 one interval after the set-back: candidate again",
              npc_actions.candidates(), ["Nico"])
    finally:
        for k, v in orig.items():
            setattr(character, k, v)

    # -----------------------------------------------------------------------
    print("C) npc_scenes.candidate_rooms")
    # -----------------------------------------------------------------------
    clock = GameClock(T0)
    npc_scenes.game_time = clock
    npc_scenes._last_scene.clear()
    npc_scenes._interval = lambda: GameDuration.of(minutes=60)
    npc_scenes._free = lambda name: True

    orig_mode = live_npc_actions.conversation_mode
    orig_avatar = live_npc_actions.avatar_at_place
    live_npc_actions.conversation_mode = lambda: "scene"
    live_npc_actions.avatar_at_place = lambda name: True
    orig = {
        "list_temporary_npcs": character.list_temporary_npcs,
        "get_character_current_location": character.get_character_current_location,
        "get_character_current_room": character.get_character_current_room,
    }
    character.list_temporary_npcs = lambda: ["Nico", "Pia"]
    character.get_character_current_location = lambda name="", profile=None: "tavern"
    character.get_character_current_room = lambda name="", profile=None: "main"
    room_key = npc_scenes._room_key("tavern", "main")
    try:
        npc_scenes._last_scene[room_key] = T0
        clock.shift(minutes=30)
        check("C1 half an interval later: no scene",
              npc_scenes.candidate_rooms(), [])

        clock.shift(hours=-5)                # now T0 - 4.5 h
        check("C2 clock set back 5 h: no scene this pass",
              npc_scenes.candidate_rooms(), [])
        check("C2 stamp re-anchored to the new now",
              npc_scenes._last_scene.get(room_key),
              T0 - GameDuration.of(hours=4, minutes=30))

        clock.shift(hours=1)
        check("C3 one interval after the set-back: scene again",
              npc_scenes.candidate_rooms(),
              [("tavern", "main", ["Nico", "Pia"])])
    finally:
        live_npc_actions.conversation_mode = orig_mode
        live_npc_actions.avatar_at_place = orig_avatar
        for k, v in orig.items():
            setattr(character, k, v)

    # -----------------------------------------------------------------------
    print("D) random_events.check_escalation (factor 6, ttl 8 game hours)")
    # -----------------------------------------------------------------------
    paired = PairedClock(factor=6)
    random_events.game_time = paired.game
    random_events.utc_now = paired.real
    random_events._had_chat_since = lambda loc, since: False

    escalated = []
    orig_escalate = random_events._escalate_event
    random_events._escalate_event = lambda ev: escalated.append(ev.get("id"))

    event = {
        "id": "evt_smoke1",
        "category": "danger",
        "ttl_hours": 8,
        "location_id": "tavern",
        "created_at": paired.real().isoformat(),
        "game_ts": paired.game().canonical(),
    }
    orig_all = events_model.get_all_events
    events_model.get_all_events = lambda: [event]
    try:
        paired.advance_real(39)
        random_events.check_escalation()
        check("D1 39 real minutes (3h54 game): no escalation", escalated, [])

        paired.advance_real(1)               # 40 real minutes = 4 game hours
        random_events.check_escalation()
        check("D2 40 real minutes (4h00 game): escalates",
              escalated, ["evt_smoke1"])
    finally:
        events_model.get_all_events = orig_all
        random_events._escalate_event = orig_escalate

    # -----------------------------------------------------------------------
    print("E) random_events location cooldown (factor 6, 2 game hours)")
    # -----------------------------------------------------------------------
    paired = PairedClock(factor=6)
    random_events.game_time = paired.game
    random_events.utc_now = paired.real
    random_events.random.random = lambda: 0.0     # probability gate always passes
    random_events._get_category_weights = lambda loc, s: {"ambient": 100}
    random_events._pick_category = lambda w: "ambient"

    generated = []
    orig_gen = random_events._generate_event
    random_events._generate_event = (
        lambda loc_id, loc, cat, chars, active, settings: generated.append(loc_id))

    existing = {
        "id": "evt_smoke2",
        "category": "ambient",
        "location_id": "tavern",
        "created_at": paired.real().isoformat(),
        "game_ts": paired.game().canonical(),
    }
    orig_list = events_model.list_events
    events_model.list_events = lambda location_id=None: [existing]
    location = {
        "id": "tavern",
        "event_settings": {
            "event_cooldown_hours": 2,
            "max_concurrent_events": 5,
            "secret_reveal_chance": 0.0,
        },
    }
    try:
        paired.advance_real(10)              # 1 game hour
        random_events._try_generate_for_location("tavern", location, ["Ada"])
        check("E1 1 game hour after the last event: still on cooldown",
              generated, [])

        paired.advance_real(10)              # 20 real minutes = 2 game hours
        random_events._try_generate_for_location("tavern", location, ["Ada"])
        check("E2 2 game hours after the last event: generates",
              generated, ["tavern"])
    finally:
        events_model.list_events = orig_list
        random_events._generate_event = orig_gen

    print()
    print(f"(throwaway storage: {STORAGE})")
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKED}:")
        for f in FAILURES:
            print("  -", f)
        return 1
    print(f"OK — {CHECKED} checks passed")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", action="store_true",
                    help="run the checks against the HEAD version of the "
                         "modules (expected to FAIL — that is the point)")
    args = ap.parse_args()
    sys.exit(main(args.head))
