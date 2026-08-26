#!/usr/bin/env python3
"""Smoke run for the temporary-NPC TTL readout (plan-npc-leben-bugs, task 1).

Throwaway storage, throwaway world DB, throwaway task queue — no server, no
real world is touched. The GAME clock is frozen (``set_game_factor(0.0)`` +
``set_game_time``), so every number below is exact and reproducible; there is
no system clock anywhere in this feature.

THE RULE, by hand. ``npc_ops.remaining_span(expires_at)`` answers the pair the
Game-Admin list renders, and ``npc_summary`` carries it as ``remaining_hours``
+ ``remaining_label``:

    left            = GameTime.parse(expires_at) - game_time()   → GameDuration
    remaining_hours = round(left.total_seconds / 3600, 2)        (may be < 0)
    remaining_label = "{h}h {m}m"  for a full hour or more, with the minutes
                                   dropped when they are 0 ("2h", never "2h 0m")
                      "{m}m"       below one hour
                      "expired"    when nothing is left
                      ""           when there is no stamp at all

    No stamp ("" — the NPC lives until an admin deletes it) answers
    ``(None, "")``. A NEGATIVE span is a real state, not an error: the sweep
    runs on a tick, so an NPC can be past its stamp and still standing, and the
    list has to say so instead of quietly showing nothing.

    The boundary "exactly nothing left" follows ``is_expired`` (``game_time()
    >= stamp``), so a span of 0 s reads "expired" too — label and the row's
    ``expired`` flag can never disagree about the same instant.

THE CLOCK, by hand. The world starts at Year 1, Day 1, 00:00 (= 0 game
seconds) and a game day is 24·3600 = 86 400 s. This run freezes it at

    T0 = 10 days + 12 h = 10·86 400 + 43 200 = 907 200 s   (Year 1, Day 11, 12:00)

and moves it only by whole, hand-counted spans.

  [1] TTL 2.5 h, stamped by the real creation path. ``expiry_stamp(2.5)`` is
      T0 + 2.5·3600 = T0 + 9 000 s = 916 200 s (Day 11, 14:30), so with the
      clock still at T0 the span is 9 000 s:
        remaining_hours  9000/3600      = 2.5
        remaining_label  9000 = 2 h + 1 800 s = 2 h 30 min → "2h 30m"
        expired          False
      Both values also ride in ``npc_summary`` — that is the payload
      `GET /npc/list` hands the list.

  [2] The clock, not the stamp, moves. Advancing the game clock by 2 h to
      T0 + 7 200 s leaves 916 200 − 914 400 = 1 800 s on the SAME stamp:
        remaining_hours  1800/3600      = 0.5
        remaining_label  under one hour → minutes only → "30m"

  [3] Whole hours drop the minutes. A stamp at clock + 7 200 s:
        remaining_hours  2.0     remaining_label "2h"   (never "2h 0m")

  [4] Minutes round DOWN to whole minutes, hours to 2 decimals. A stamp at
      clock + 100 s:
        remaining_hours  round(100/3600, 2) = round(0.0277…, 2) = 0.03
        remaining_label  100 s = 1 min 40 s → whole minutes → "1m"

  [5] No stamp = no readout. ``ttl_hours`` 0/None writes ``expires_at = ""``
      (``expiry_stamp``), and the pair is ``(None, "")`` — NOT 0/"expired".
      An NPC without a TTL is not an expired NPC.

  [6] A stamp in the PAST. Clock at T0, stamp at T0 − 3 600 s:
        remaining_hours  −3600/3600     = −1.0
        remaining_label  "expired"
        expired          True
      The row still exists — the sweep has not run yet.

  [7] The boundary. Stamp exactly equal to the clock: span 0 s →
        remaining_hours  0.0     remaining_label "expired"    expired True
      matching ``is_expired``'s ``>=`` at that same instant.

  [8] Junk is not a stamp. A profile carrying ``expires_at = "soon"`` answers
      ``(None, "")`` and ``expired False`` — the same as no stamp, so a
      hand-edited profile cannot crash the list.

Usage:  ./.venv/bin/python scripts/smoke_npc_ttl.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcttl-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcttl-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding, npc_ops  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.npc_ops import (apply_npc, expiry_stamp,  # noqa: E402
                              is_expired, npc_summary, remaining_span)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  save_character_profile)

# Offline: no embedding model is downloaded for the pose catalog.
embedding.embed = lambda text: None

# No worker threads in a smoke — nothing here executes a queued task.
get_task_queue()._started = True

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the frozen clock ────────────────────────────────────────────────────────

set_game_factor(0.0)
T0 = GameTime(0) + GameDuration.of(days=10, hours=12)
check("the frozen clock stands where the docstring says",
      T0.total_seconds, 907200)
set_game_time(T0)


def make_npc(name: str, *, ttl_hours=None) -> str:
    """A living temporary NPC through the real creation path, gate off."""
    cfg = config.get_all()
    cfg.setdefault("npc", {})["require_assets"] = False
    config.save(cfg, STORAGE / "config.json")
    apply_npc({"character_name": name,
               "character_appearance": "a lean figure in a patched coat",
               "face_appearance": "a narrow face, dark eyes",
               "outfit_description": "a patched brown coat",
               "standing_task": "watching the road"},
              "", ttl_hours=ttl_hours, created_by="smoke_npc_ttl")
    return name


def stamp_at(name: str, offset: GameDuration) -> str:
    """Put ``expires_at`` ``offset`` away from the CURRENT game clock."""
    profile = get_character_profile(name) or {}
    profile["expires_at"] = (npc_ops.game_time() + offset).canonical()
    save_character_profile(name, profile)
    return profile["expires_at"]


# ---------------------------------------------------------------------------
print("\n[1] a 2.5 h TTL, read straight off the creation path")

make_npc("Torvin", ttl_hours=2.5)
STAMP = (get_character_profile("Torvin") or {}).get("expires_at")
check("expiry_stamp(2.5) is T0 + 9000 s",
      GameTime.parse(STAMP).total_seconds, 916200)
check("the stamp reads as Day 11, 14:30", STAMP, "Y0001-D011T14:30:00")
check("remaining_span at T0", remaining_span(STAMP), (2.5, "2h 30m"))

row = npc_summary("Torvin")
check("npc_summary carries the hours", row["remaining_hours"], 2.5)
check("npc_summary carries the label", row["remaining_label"], "2h 30m")
check("npc_summary is not expired", row["expired"], False)

# ---------------------------------------------------------------------------
print("\n[2] the CLOCK moves, the stamp does not")

set_game_time(T0 + GameDuration.of(hours=2))
check("the same stamp now has 30 minutes left",
      remaining_span(STAMP), (0.5, "30m"))
check("npc_summary agrees",
      (npc_summary("Torvin")["remaining_hours"],
       npc_summary("Torvin")["remaining_label"]), (0.5, "30m"))

set_game_time(T0)      # back to the frozen instant for everything below

# ---------------------------------------------------------------------------
print("\n[3] whole hours drop the minutes")

check("a stamp two hours out",
      remaining_span((T0 + GameDuration.of(hours=2)).canonical()), (2.0, "2h"))

# ---------------------------------------------------------------------------
print("\n[4] under an hour: whole minutes, hours to two decimals")

check("a stamp 100 seconds out",
      remaining_span((T0 + GameDuration.of(seconds=100)).canonical()),
      (0.03, "1m"))

# ---------------------------------------------------------------------------
print("\n[5] no stamp is not an expired stamp")

make_npc("Brenna", ttl_hours=None)
check("expiry_stamp writes nothing for no TTL", expiry_stamp(None), "")
check("remaining_span of an empty stamp", remaining_span(""), (None, ""))
never = npc_summary("Brenna")
check("npc_summary of a TTL-less NPC",
      (never["expires_at"], never["remaining_hours"],
       never["remaining_label"], never["expired"]), ("", None, "", False))

# ---------------------------------------------------------------------------
print("\n[6] a stamp in the past — the row is still there")

past = stamp_at("Brenna", GameDuration.of(hours=-1))
check("the past stamp", past, "Y0001-D011T11:00:00")
check("remaining_span went negative", remaining_span(past), (-1.0, "expired"))
gone = npc_summary("Brenna")
check("npc_summary of an NPC past its stamp",
      (gone["remaining_hours"], gone["remaining_label"], gone["expired"]),
      (-1.0, "expired", True))

# ---------------------------------------------------------------------------
print("\n[7] the boundary follows is_expired")

now_stamp = stamp_at("Brenna", GameDuration.ZERO)
check("nothing left reads as expired", remaining_span(now_stamp),
      (0.0, "expired"))
check("and is_expired says the same at that instant",
      is_expired(now_stamp), True)

# ---------------------------------------------------------------------------
print("\n[8] junk on the profile is not a stamp")

profile = get_character_profile("Brenna") or {}
profile["expires_at"] = "soon"
save_character_profile("Brenna", profile)
junk = npc_summary("Brenna")
check("a hand-edited profile cannot crash the list",
      (junk["remaining_hours"], junk["remaining_label"], junk["expired"]),
      (None, "", False))

# ---------------------------------------------------------------------------
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
