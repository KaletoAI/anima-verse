#!/usr/bin/env python3
"""World-admin tick: how many character profiles ONE sub-job pass reads for
five idle characters.

Usage:
    ./.venv/bin/python scripts/smoke_periodic_profile_reads.py
    ./.venv/bin/python scripts/smoke_periodic_profile_reads.py --head
        (--head counts the very same passes against the HEAD version of
         ``periodic_jobs`` and ``activity_engine``, loaded side by side from
         ``git show`` into a throwaway directory — that is how the "before"
         numbers below were obtained. It changes no git state and writes into
         no tracked file.)

No server, no real world DB: throwaway storage via ``paths.init``. Every
character read is intercepted at ``app.models.character.get_character_profile``
— the composite read the review measured at 0.41 ms (2 SQLite queries plus one
file read per ``source_file`` field).

Review 2026-09-20, finding SIM-7: ``_sub_status_tick``, ``_sub_force_rules``
and ``_sub_flag_lifecycle`` each pulled several FULL profiles per character per
minute for work that normally changes nothing, and ``cleanup_expired_conditions``
loaded a profile (under the profile lock) even when the character carried no
condition at all. ``_sub_force_rules`` has ``min_interval = 0``, i.e. it runs on
EVERY tick.

EXPECTED VALUES, DERIVED BY HAND
  Five idle characters. A stubbed profile is ``{}``: no ``status_effects``, no
  ``active_conditions``, no location. Contributions per call site:

    is_feature_enabled(name, …)        2  (get_character_config -> profile,
                                           then get_character_profile)
    get_character_config(name)         1
    get_character_current_location     1  (0 when a profile is handed in)
    get_character_current_room         1  (0 when a profile is handed in)
    get_effective_activity             1  (0 when a profile is handed in)
    resolve_force_destination(…,
      "stay")                          2  (current_location + current_room)

  A) _sub_status_tick, FIRST pass of a fresh process (no hourly stamps yet)

     after   per char: hourly tick gates on its RAM stamp before reading
                       anything -> 0; the sub-job reads the profile ONCE -> 1;
                       cleanup_expired_conditions gets it handed in, sees no
                       active_conditions and never takes the lock -> 0.
                       = 1  ->  5 for five characters
     before  per char: is_feature_enabled 2 — and it answers FALSE here,
                       because a stubbed ``{}`` profile resolves to the
                       template ``human-default``, whose
                       ``status_effects_enabled`` is false (checked by hand in
                       shared/templates/character/human-default.json). The old
                       order paid those two reads a minute per character for a
                       gate that says "off"; the new order never gets there.
                       Then cleanup_expired_conditions loads its own profile 1.
                       = 3  ->  15

  B) _sub_status_tick, SECOND pass (stamp set, half a game hour later)

     after   per char: gate returns on the RAM stamp -> 0, sub-job read 1,
                       cleanup 0.  = 1  ->  5
     before  per char: same 3 as in A — the old code asked the feature gate
                       BEFORE the hour gate, so the cost did not depend on the
                       stamp at all.  = 3  ->  15

  C) _sub_force_rules with NO force rule in the world

     after   the pass asks ``load_rules()`` once, finds no force rule and
             returns before touching a single character.  ->  0
     before  per char: check_force_rules -> get_character_current_location 1,
             then the empty rule list ends it.  = 1  ->  5

  D) _sub_force_rules with ONE always-matching force rule (go_to "stay", no
     set_flags, so nothing is written and nothing changes)

     after   per char: check_force_rules 1 (current_location; the condition
                       "always" reads nothing), resolve_force_destination 2,
                       before-snapshot 1 (ONE profile, three readers fed from
                       it), after-snapshot 1.  = 5  ->  25
     before  per char: 1 + 2 + 3 (three separate reads before) + 3 (three
                       after).  = 9  ->  45

  Totals: after 5 + 5 + 0 + 25 = 35, before 15 + 15 + 5 + 45 = 80.
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="periodic-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="periodic-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.game_time import GameDuration, GameTime  # noqa: E402

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


NAMES = ["Ada", "Bo", "Cy", "Dee", "Eli"]
T0 = GameTime.parse("Y0002-D100T12:00:00")

_HEAD_DIR = Path(tempfile.mkdtemp(prefix="periodic-head-"))


def load_head(relpath):
    """The HEAD revision of ``relpath`` as a module object."""
    src = subprocess.check_output(["git", "show", f"HEAD:{relpath}"],
                                  cwd=str(ROOT), text=True)
    twin = Path(relpath).stem + "__head"
    path = _HEAD_DIR / f"{twin}.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(twin, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[twin] = mod
    spec.loader.exec_module(mod)
    return mod


FORCE_RULE = {
    "id": "smoke_force",
    "type": "force",
    "condition": "always",
    "character": "",
    "rule_name": "smoke",
    "force_action": {"go_to": "stay", "message": "stay put"},
}


def main(use_head):
    import app.core.activity_engine as live_act
    import app.models.account as account
    import app.models.character as character
    import app.models.rules as rules

    if use_head:
        act = load_head("app/core/activity_engine.py")
        sys.modules["app.core.activity_engine"] = act
        jobs = load_head("app/core/periodic_jobs.py")
    else:
        act = live_act
        import app.core.periodic_jobs as jobs

    counter = {"n": 0}

    def counting_profile(name):
        counter["n"] += 1
        return {}

    orig = {
        "get_character_profile": character.get_character_profile,
        "list_available_characters": character.list_available_characters,
    }
    orig_player = account.is_player_controlled
    orig_rules = rules.load_rules
    character.get_character_profile = counting_profile
    character.list_available_characters = lambda: list(NAMES)
    account.is_player_controlled = lambda name: False

    # A settable game clock so the hourly gate is exercised deterministically.
    now = [T0]
    act.game_time = lambda: now[0]
    act._LAST_HOURLY_TICK.clear()

    try:
        print("A) _sub_status_tick, first pass of a fresh process")
        counter["n"] = 0
        jobs._sub_status_tick()
        check("A profile reads for 5 idle characters", counter["n"],
              15 if use_head else 5)

        print("B) _sub_status_tick, second pass half a game hour later")
        now[0] = T0 + GameDuration.of(minutes=30)
        counter["n"] = 0
        jobs._sub_status_tick()
        check("B profile reads for 5 idle characters", counter["n"],
              15 if use_head else 5)

        print("C) _sub_force_rules with no force rule in the world")
        rules.load_rules = lambda: []
        counter["n"] = 0
        jobs._sub_force_rules()
        check("C profile reads for 5 idle characters", counter["n"],
              5 if use_head else 0)

        print("D) _sub_force_rules with one always-matching force rule")
        rules.load_rules = lambda: [dict(FORCE_RULE)]
        counter["n"] = 0
        jobs._sub_force_rules()
        check("D profile reads for 5 idle characters", counter["n"],
              45 if use_head else 25)
    finally:
        for k, v in orig.items():
            setattr(character, k, v)
        account.is_player_controlled = orig_player
        rules.load_rules = orig_rules
        sys.modules["app.core.activity_engine"] = live_act

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
                    help="count the same passes against the HEAD modules "
                         "(the 'before' numbers)")
    args = ap.parse_args()
    sys.exit(main(args.head))
