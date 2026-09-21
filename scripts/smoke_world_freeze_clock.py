#!/usr/bin/env python3
"""World freeze must move the GAME clock exactly once — a repeated freeze or
unfreeze is a no-op.

Usage:
    ./.venv/bin/python scripts/smoke_world_freeze_clock.py

No server, no world DB: ``app.models.world`` is stubbed with an in-memory
world_kv, and ``timeutils.utc_now`` with a hand-driven system clock, so the
whole check is arithmetic on ``app/core/timeutils.py``.

Why this exists (review 2026-09-20, SIM-1): ``on_freeze_change`` re-anchors the
clock on every call. The live ``world_frozen`` flag is persisted BEFORE the hook
runs, so the hook cannot see from it whether anything changed. A second freeze
therefore added the whole frozen real span x factor to the game clock, a second
unfreeze subtracted the span since the unfreeze — and a backwards-running world
clock stalls the hourly tick, NPC actions and the director. Two open Game-Admin
tabs are enough (FreezeToggle reads the state only on mount).

Expected values, derived by hand (factor 2.0, game anchor Y0002-D100T12:00:00,
real anchor = T0):

  real T0    +0 s   running  -> 12:00:00                 (anchor)
  real T0  +600 s   running  -> 12:00:00 + 600*2 s       = 12:20:00
  freeze #1 at +600 s                                    -> 12:20:00 stands
  real T0 +4200 s   frozen   -> 12:20:00                 (clock stands still)
  freeze #2 at +4200 s  (no-op)                          -> 12:20:00
      old code: 12:20:00 + (4200-600)*2 s = 12:20:00 + 2 h = 14:20:00
  unfreeze at +4200 s -> re-anchor real side, game stays  12:20:00
  real T0 +4800 s   running  -> 12:20:00 + 600*2 s       = 12:40:00
  unfreeze #2 at +4800 s (no-op)                         -> 12:40:00
      old code: re-anchors the real side onto the OLD game anchor, so the
      clock jumps BACK by the 600 s x 2 = 20 min it had been running
  real T0 +5400 s   running  -> 12:20:00 + 1200*2 s      = 13:00:00

The "fails before" half: run the same sequence against the pre-fix
``on_freeze_change`` (no state guard) and the two no-op steps print the values
noted above — this script's checks 4 and 7 then fail.
"""

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- stub app.models.world BEFORE timeutils touches it (lazy imports) -------
importlib.import_module("app")   # parent package before we inject a submodule

_store = {}
_frozen = [False]

_fake_world = types.ModuleType("app.models.world")
_fake_world.get_world_setting = lambda k, d="": _store.get(k, d)
_fake_world.set_world_setting = lambda k, v: _store.__setitem__(k, v)
_fake_world.is_world_frozen = lambda: _frozen[0]
sys.modules["app.models.world"] = _fake_world

from app.core import timeutils as T  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402

# --- hand-driven system clock ----------------------------------------------
_BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)
_offset = [0.0]
T.utc_now = lambda: _BASE + timedelta(seconds=_offset[0])

FACTOR = 2.0
ANCHOR = GameTime.from_parts(2, 100, 12, 0, 0)

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


def at(seconds):
    _offset[0] = float(seconds)


def now_game():
    return T.game_time().canonical()


def set_frozen(flag):
    """What ``set_world_frozen`` does: persist the flag, then call the hook."""
    _frozen[0] = flag
    _store["world_frozen"] = "1" if flag else "0"
    T.invalidate_game_clock_cache()
    T.on_freeze_change(flag)


def reset_world():
    _store.clear()
    _frozen[0] = False
    at(0)
    _store["game_time.anchor_real"] = T.utc_now().isoformat()
    _store["game_time.anchor_game"] = ANCHOR.canonical()
    _store["game_time.factor"] = repr(FACTOR)
    _store["game_time.anchors_frozen"] = "0"
    _store["world_frozen"] = "0"
    T.invalidate_game_clock_cache()


print("1) repeated freeze / repeated unfreeze")
reset_world()
check("anchor at T0", now_game(), "Y0002-D100T12:00:00")
at(600)
check("running, +600 s real x2", now_game(), "Y0002-D100T12:20:00")
set_frozen(True)
check("freeze #1 stops the clock", now_game(), "Y0002-D100T12:20:00")
at(4200)
check("1 h of real time while frozen", now_game(), "Y0002-D100T12:20:00")
set_frozen(True)          # second tab / repeated POST
check("freeze #2 is a no-op", now_game(), "Y0002-D100T12:20:00")
set_frozen(False)
check("unfreeze resumes where it stopped", now_game(), "Y0002-D100T12:20:00")
at(4800)
check("running again, +600 s real x2", now_game(), "Y0002-D100T12:40:00")
set_frozen(False)         # second tab / repeated POST
check("unfreeze #2 is a no-op", now_game(), "Y0002-D100T12:40:00")
at(5400)
check("still running forward after the no-op", now_game(),
      "Y0002-D100T13:00:00")

print("2) a normal freeze/unfreeze excludes the frozen span")
reset_world()
at(100)                                     # 100 real s -> 200 game s
set_frozen(True)
at(10_000)                                  # ~2.7 h frozen, must not count
set_frozen(False)
at(10_100)                                  # 100 more real s -> 200 game s
# 12:00:00 + 200 s + 200 s = 12:06:40
check("frozen span is not counted", now_game(), "Y0002-D100T12:06:40")

print("3) the anchors carry their own freeze marker")
reset_world()
set_frozen(True)
check("marker after freeze", _store.get("game_time.anchors_frozen"), "1")
set_frozen(False)
check("marker after unfreeze", _store.get("game_time.anchors_frozen"), "0")
# set_game_factor/set_game_time must keep the marker consistent
set_frozen(True)
T.set_game_factor(4.0)
check("marker survives a factor change while frozen",
      _store.get("game_time.anchors_frozen"), "1")
at(20_000)
check("still frozen after the factor change", now_game(),
      "Y0002-D100T12:00:00")

print("4) anchors without a marker (pre-fix world) still re-anchor once")
reset_world()
del _store["game_time.anchors_frozen"]
T.invalidate_game_clock_cache()
at(600)
set_frozen(True)
check("first freeze on unmarked anchors works", now_game(),
      "Y0002-D100T12:20:00")
at(4200)
set_frozen(True)
check("and the second one is already guarded", now_game(),
      "Y0002-D100T12:20:00")

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
