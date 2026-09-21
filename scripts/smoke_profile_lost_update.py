#!/usr/bin/env python3
"""Smoke run for the profile lost update (DATA-3 of the 2026-09-20 review).

Usage:
    ./.venv/bin/python scripts/smoke_profile_lost_update.py

Runs against a THROWAWAY storage directory — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.

THE BUG, in the report's own words: ``places.assign`` writes
``profile["place"]`` while ``POST /inventory/characters/<name>/equip`` runs
in the threadpool holding ``keyed_lock("character_profile", name)``. The
equip route read the profile BEFORE the assign wrote it and writes its stale
copy back afterwards — ``profile["place"]`` is ``None`` again while the
figure physically sits in the chair, so ``places.occupancy`` hands the same
slot to the next character: two figures on one anchor.

The mechanism is not specific to ``place``. ``save_character_profile``
serialises the WHOLE ``profile_json`` blob from the dict it is given, so the
later writer wins over every blob field, not only the one it meant to change.
That is what this check reproduces — with the REAL background writers, and
with the equip side SIMULATED by a function that does the identical
read-modify-write under the same lock (a real equip would need an item
catalogue and would prove nothing more).

THE INTERLEAVING IS FORCED, not raced: the equip thread reads, signals, and
only writes 0.3 s later. So without the lock in the background writer the
loss is certain, and with it the assertions below can only hold because the
background writer WAITED. No sleep-and-hope.

Hand-derived expectations:

  [1] ``set_movement_target`` (app/models/character.py). Pre-state: the
      character has a stored ``journey`` towards "market" and
      ``movement_target`` "market". The equip thread reads that state,
      then ``set_movement_target(name, "")`` runs — which by contract drops
      target AND journey together. Afterwards BOTH must hold:
        * ``default_outfit`` == "coat"   (the equip side's change survived)
        * no ``journey`` in the profile  (the cancel survived)
      Without the lock the equip write resurrects the journey: the ticker
      would walk the character on although its trip was cancelled.

  [2] ``activity_engine.apply_effects`` (status deltas). Same interleaving,
      and the same two-sided assertion: ``status_effects["stamina"]`` is
      80 − 30 = 50 AND the equip side's ``default_outfit`` is still there.
      ``status_effects`` lives in ``character_state.meta``, which
      ``save_character_profile`` re-merges inside its transaction, so the
      stat itself survives either way — the blob field next to it does not.

  [3] Control: with BOTH sides deliberately unlocked the loss still happens.
      This is what makes [1] and [2] a statement about the lock rather than
      about timing — if [3] passed too, the interleaving would not be
      reaching the bug at all.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="lostupd-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="lostupd-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.activity_engine import apply_effects  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  save_character_profile, set_movement_target)

NAME = "Racer"
#: How long the equip thread sits between its read and its write. Long enough
#: that the background writer runs to completion inside the window when it
#: does NOT take the lock — i.e. the control case in [3] is deterministic.
HOLD_S = 0.3

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def seed():
    """Pre-state: a running journey plus an empty default_outfit."""
    save_character_profile(NAME, {
        "character_name": NAME,
        "template": "human-default",
        "default_outfit": "",
        "status_effects": {"stamina": 80},
        "movement_target": "market",
        "journey": {"target": "market",
                    "waypoints": [[0.0, 0.0, 0.0], [10.0, 0.0, 10.0]],
                    "started_at_game": "Y0001-D001T12:00:00",
                    "speed_m_s": 1.0, "entry_edge": None},
    }, create_new=True)


def equip_side(read_done: threading.Event, locked: bool):
    """What POST /inventory/.../equip does to the blob, minus the catalogue.

    Reads the profile, lets the other writer run, writes its own field back —
    the read-modify-write the route performs under
    ``keyed_lock("character_profile", …)``.
    """
    def body():
        profile = get_character_profile(NAME)
        read_done.set()
        time.sleep(HOLD_S)
        profile["default_outfit"] = "coat"
        save_character_profile(NAME, profile)

    if locked:
        with keyed_lock("character_profile", NAME):
            body()
    else:
        body()


def run_case(label, background, *, equip_locked=True):
    """Start the equip thread, wait for its READ, then run ``background``."""
    seed()
    read_done = threading.Event()
    t = threading.Thread(target=equip_side, args=(read_done, equip_locked),
                         name="equip-sim")
    t.start()
    read_done.wait(5.0)
    background()
    t.join(10.0)
    prof = get_character_profile(NAME)
    print(f"\n{label}: default_outfit={prof.get('default_outfit')!r} "
          f"journey={'yes' if isinstance(prof.get('journey'), dict) else 'no'} "
          f"stamina={(prof.get('status_effects') or {}).get('stamina')}")
    return prof


def main():
    print("=" * 72)
    print("profile lost update under concurrent writers (DATA-3)")
    print("=" * 72)

    # ── [1] set_movement_target vs equip ────────────────────────────────
    prof = run_case("[1] set_movement_target vs equip",
                    lambda: set_movement_target(NAME, ""))
    check("[1] the equip side's field survived",
          prof.get("default_outfit") == "coat", repr(prof.get("default_outfit")))
    check("[1] the cancelled journey stayed cancelled",
          not isinstance(prof.get("journey"), dict), repr(prof.get("journey")))
    check("[1] movement_target is empty",
          (prof.get("movement_target") or "") == "",
          repr(prof.get("movement_target")))

    # ── [2] apply_effects vs equip ──────────────────────────────────────
    prof = run_case("[2] activity_engine.apply_effects vs equip",
                    lambda: apply_effects(NAME, {"stamina_change": -30},
                                          source="smoke"))
    check("[2] the equip side's field survived",
          prof.get("default_outfit") == "coat", repr(prof.get("default_outfit")))
    check("[2] the stat delta landed (80 - 30 = 50)",
          (prof.get("status_effects") or {}).get("stamina") == 50,
          repr(prof.get("status_effects")))
    check("[2] the journey in the blob is untouched by an unrelated write",
          isinstance(prof.get("journey"), dict), repr(prof.get("journey")))

    # ── [3] control: no lock on either side -> the loss happens ─────────
    def unlocked_cancel():
        profile = get_character_profile(NAME)
        profile["movement_target"] = ""
        profile.pop("journey", None)
        save_character_profile(NAME, profile)

    prof = run_case("[3] control, BOTH sides unlocked", unlocked_cancel,
                    equip_locked=False)
    check("[3] control: the stale equip write DID resurrect the journey "
          "(so the interleaving really reaches the bug)",
          isinstance(prof.get("journey"), dict), repr(prof.get("journey")))

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAIL — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("PASS — all checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
