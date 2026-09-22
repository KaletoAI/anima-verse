#!/usr/bin/env python3
"""Relationship decay runs on the GAME clock.

Usage:
    ./.venv/bin/python scripts/smoke_relationship_decay_game_time.py

No server, no real world: a throwaway storage directory (``tempfile`` +
``paths.init`` BEFORE the first world-DB import) plus a throwaway clip dir.
The GAME clock is driven through the project's own API — ``set_game_factor(0.0)``
stops it, ``set_game_time(<GameTime>)`` moves it — so every number below is
exact. Nothing monkeypatches ``datetime``.

Part A stubs ``app.models.relationship`` with an in-memory store and a SPY on
``save_relationships``, so the decay arithmetic and the "did it write at all?"
question are checked on their own. ``classify_type`` is the REAL function
(imported before the stub goes in), so the class boundary in [J] is derived
from the code, not guessed. Part B runs the real handler against the real
model on the throwaway world DB and checks the UI payload.

The constants (``app/core/relationship_decay.py``):
    DECAY_STRENGTH_PER_WEEK = 1.0     DECAY_ROMANTIC_PER_WEEK = 0.02
    DECAY_PERIOD = 7 game days        GRACE = 7 game days
    MIN_STEP = 1 game day             MAX_WEEKS_PER_RUN = 2.0
A "week" is a flat ``GameDuration.of(days=7)``; the world calendar has no real
weeks (its ``week_days`` list only NAMES days and may be absent), so seven game
days is a duration, never a calendar lookup.

The clock starts at T0 = epoch + 100 days + 12 h
  = 100 * 86400 + 12 * 3600 = 8 640 000 + 43 200 = 8 683 200 game seconds.
Every pair below starts at strength 20 and romantic_tension 0.5.

Hand-derived expectations
-------------------------
[A] met 6 game days ago, no decay stamp, now = T0
      idle = 6 d < GRACE (7 d) -> skipped before anything is written.
      strength 20, romantic 0.5, no ``last_decay_game``, save NOT called.

[B] idle 8 game days, first run, now = T0
      idle = 8 d >= 7 d, but ``last_decay_game`` is missing -> the run only
      remembers where decay starts. strength stays 20, romantic stays 0.5,
      ``last_decay_game`` = T0, save called once.

[C] same pair, now = T0 + 7 d
      since the last run: 7 d >= MIN_STEP -> due.
      idle = 15 d >= 7 d. reference = max(last_decay T0, last_interaction
      T0-8d) = T0 -> span = 7 d -> weeks = 7/7 = 1.0
      strength  20 - 1.0 * 1.0 = 19.0
      romantic  0.5 - 0.02 * 1.0 = 0.48
      ``last_decay_game`` = T0 + 7 d.

[D] the same pair meets again 3 days later, next run 10 days after [C]
      last_interaction_game = T0 + 10 d (= 3 d after the [C] run at T0+7d),
      now = T0 + 17 d.
      idle = 17 - 10 = 7 d >= 7 d -> due.
      reference = max(last_decay T0+7d, last_interaction T0+10d) = T0 + 10 d
      -> span = 7 d -> weeks = 1.0 -> strength 19.0 - 1.0 = 18.0,
         romantic 0.48 - 0.02 = 0.46.
      Without the reset the reference would be T0+7d -> span 10 d ->
      10/7 = 1.428571 weeks -> strength 19.0 - 1.428571 = 17.57. The check
      for 18.0 is exactly that discrimination.

[E] a forward clock jump of 90 game days
      fresh pair, last_interaction_game = T0 - 8 d, last_decay_game = T0,
      now = T0 + 90 d.
      span = 90 d -> 90/7 = 12.857142 weeks, capped at MAX_WEEKS_PER_RUN = 2
      strength  20 - 1.0 * 2 = 18.0
      romantic  0.5 - 0.02 * 2 = 0.46
      ``last_decay_game`` = T0 + 90 d (the cap limits the AMOUNT, never the
      stamp — otherwise the same backlog would be charged again next run).

[F] the clock is set BACK 10 game days
      fresh pair, last_interaction_game = T0 - 30 d, last_decay_game = T0,
      now = T0 - 10 d -> span would be -10 d.
      A negative span is never charged: strength stays 20, romantic 0.5, and
      ``last_decay_game`` is re-anchored to T0 - 10 d (leaving it in the
      future would freeze the pair until the clock caught up again).

[G] two runs inside the same game day
      the [C] pair again at T0 + 7 d + 6 h: since the last run 6 h < MIN_STEP
      (1 game day) -> no-op, nothing changes and save is NOT called.

[H] the world clock stands still (frozen world / zero span)
      the same pair at exactly T0 + 7 d: span 0 < MIN_STEP -> no-op,
      save NOT called.

[I] a legacy pair that carries only SYSTEM stamps
      no ``last_interaction_game``, no ``last_decay_game``, now = T0.
      The two clocks are not convertible, so the pair is stamped with the
      CURRENT game time and decayed by nothing: strength 20, romantic 0.5,
      ``last_interaction_game`` = ``last_decay_game`` = T0. The SYSTEM
      ``last_interaction`` is left byte-identical (it still orders the row),
      while the obsolete SYSTEM ``last_decay`` is dropped — nothing reads it.

[J] a type re-classification across a class boundary
      The boundary is READ OFF ``classify_type``: with both sentiments 0 and
      romantic_tension 0 the only threshold in reach is "strength >= 15 ->
      acquaintance, else neutral"; the script asserts that on the real
      function before using it.
      pair strength 15.5, romantic_tension 0.0, type "acquaintance",
      last_interaction_game = T0 - 8 d, last_decay_game = T0, now = T0 + 7 d
      -> 1 week -> strength 15.5 - 1.0 = 14.5 < 15 -> type "neutral".

[K] the decay math reads NO system clock
      An AST scan of ``app/core/relationship_decay.py``: no ``utc_now``,
      ``utc_now_iso``, ``parse_iso``, ``datetime`` or ``time`` name is
      imported, called or referenced anywhere in the module.

[L] the real handler + the real model on the throwaway world DB
      A pair stamped last_interaction_game = T0 - 8 d, last_decay_game = T0,
      run at T0 + 7 d -> the same 19.0 / 0.48 as [C], persisted.
      ``build_memory_relationships`` then carries ``last_interaction_game``
      and a non-empty server-rendered ``last_interaction_label`` and does NOT
      carry the system ``last_interaction`` any more.
      ``record_interaction`` on a brand-new pair writes both stamps.
"""
import ast
import importlib
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

# The storage root and the clip library MUST be redirected BEFORE the first
# app import: without a storage root every world access raises
# StorageNotInitialised — there is no default world any more, so nothing here
# can land in the tracked worlds/demo.
STORAGE = Path(tempfile.mkdtemp(prefix="reldecay-game-storage-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="reldecay-game-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import (game_time, set_game_factor,  # noqa: E402
                                set_game_time, utc_now_iso)

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


# ── the stopped clock ───────────────────────────────────────────────────────
set_game_factor(0.0)
T0 = GameTime(0) + GameDuration.of(days=100, hours=12)
check("the clock starts where the docstring says", T0.total_seconds, 8683200)
set_game_time(T0)
check("game_time() returns exactly T0", game_time(), T0)


def at(days=0, hours=0):
    """Move the world clock to T0 + the given offset and return that instant."""
    when = T0 + GameDuration.of(days=days, hours=hours)
    set_game_time(when)
    return when


def stamp(days=0, hours=0):
    """Canonical stamp of T0 + offset (the clock is NOT moved)."""
    return (T0 + GameDuration.of(days=days, hours=hours)).canonical()


# ---------------------------------------------------------------------------
# Part A — decay arithmetic against a stubbed relationship model
# ---------------------------------------------------------------------------
importlib.import_module("app")     # parent package before we inject a submodule
from app.models.relationship import classify_type as REAL_CLASSIFY  # noqa: E402

_store = {"rels": []}
_fake = types.ModuleType("app.models.relationship")
_fake.load_relationships = lambda: _store["rels"]
_fake.save_relationships = lambda rels: _store.__setitem__("saved", True)
_fake.are_romantically_compatible = lambda a, b: True
_fake.classify_type = REAL_CLASSIFY
sys.modules["app.models.relationship"] = _fake

from app.core import relationship_decay as RD  # noqa: E402


def make_rel(**kw):
    rel = {"character_a": "Ada", "character_b": "Bo", "strength": 20,
           "sentiment_a_to_b": 0.0, "sentiment_b_to_a": 0.0,
           "romantic_tension": 0.5, "type": "friend"}
    rel.update(kw)
    return rel


def run(rel):
    _store["rels"] = [rel]
    _store.pop("saved", None)
    return RD.handle_relationship_decay({})


def saved():
    return bool(_store.get("saved"))


print("\n[A] met 6 game days ago — inside the grace period")
at(0)
r = make_rel(last_interaction_game=stamp(days=-6))
res = run(r)
check("A strength untouched", r["strength"], 20)
check("A romantic untouched", r["romantic_tension"], 0.5)
check("A no decay stamp", "last_decay_game" in r, False)
check("A nothing was saved", saved(), False)
check("A no error key", "error" in res, False)

print("\n[B] idle 8 game days, first run — stamp only")
at(0)
r = make_rel(last_interaction_game=stamp(days=-8))
res = run(r)
check("B strength untouched", r["strength"], 20)
check("B romantic untouched", r["romantic_tension"], 0.5)
check("B decay stamp is now", r.get("last_decay_game"), stamp(0))
check("B the write happened", saved(), True)
check("B no strength update reported", res.get("strength_affected"), 0)

print("\n[C] +7 game days — one full week")
at(days=7)
run(r)
check("C strength 20 - 1.0", r["strength"], 19.0)
check("C romantic 0.5 - 0.02", r["romantic_tension"], 0.48)
check("C decay stamp moved", r.get("last_decay_game"), stamp(days=7))

print("\n[D] an interaction in between resets the reference")
r["last_interaction_game"] = stamp(days=10)
at(days=17)
run(r)
check("D strength 19.0 - 1.0 (not 17.57)", r["strength"], 18.0)
check("D romantic 0.48 - 0.02", r["romantic_tension"], 0.46)
check("D decay stamp moved", r.get("last_decay_game"), stamp(days=17))

print("\n[E] a forward jump of 90 game days is capped at 2 weeks")
at(days=90)
r = make_rel(last_interaction_game=stamp(days=-8), last_decay_game=stamp(0))
run(r)
check("E strength 20 - 2.0", r["strength"], 18.0)
check("E romantic 0.5 - 0.04", r["romantic_tension"], 0.46)
check("E decay stamp is the full jump", r.get("last_decay_game"), stamp(days=90))

print("\n[F] the clock set BACK 10 game days")
at(days=-10)
r = make_rel(last_interaction_game=stamp(days=-30), last_decay_game=stamp(0))
res = run(r)
check("F strength untouched", r["strength"], 20)
check("F romantic untouched", r["romantic_tension"], 0.5)
check("F decay stamp re-anchored", r.get("last_decay_game"), stamp(days=-10))
check("F nothing decayed", res.get("strength_affected"), 0)

print("\n[G]/[H] a second run inside the same game day is a no-op")
at(days=7)
r = make_rel(last_interaction_game=stamp(days=-8), last_decay_game=stamp(0))
run(r)
check("G first run decays", r["strength"], 19.0)
at(days=7, hours=6)
run(r)
check("G second run 6 h later: strength unchanged", r["strength"], 19.0)
check("G second run 6 h later: romantic unchanged", r["romantic_tension"], 0.48)
check("G second run 6 h later: stamp unchanged",
      r.get("last_decay_game"), stamp(days=7))
check("G second run 6 h later: save NOT called", saved(), False)
at(days=7)
run(r)
check("H a standing clock (zero span): strength unchanged", r["strength"], 19.0)
check("H a standing clock (zero span): save NOT called", saved(), False)

print("\n[I] a legacy pair with only SYSTEM stamps")
at(0)
system_stamp = utc_now_iso()
r = make_rel(last_interaction=system_stamp, last_decay=system_stamp)
res = run(r)
check("I strength untouched", r["strength"], 20)
check("I romantic untouched", r["romantic_tension"], 0.5)
check("I interaction stamped with game time",
      r.get("last_interaction_game"), stamp(0))
check("I decay stamped with game time", r.get("last_decay_game"), stamp(0))
check("I the SYSTEM interaction stamp is intact",
      r.get("last_interaction"), system_stamp)
check("I the obsolete SYSTEM decay stamp is gone", "last_decay" in r, False)
check("I nothing decayed", res.get("strength_affected"), 0)

print("\n[J] the type is re-classified across the class boundary")
check("J boundary read off classify_type: 15.0 is an acquaintance",
      REAL_CLASSIFY(15.0, 0.0, 0.0, 0.0), "acquaintance")
check("J boundary read off classify_type: 14.99 is neutral",
      REAL_CLASSIFY(14.99, 0.0, 0.0, 0.0), "neutral")
at(days=7)
r = make_rel(strength=15.5, romantic_tension=0.0, type="acquaintance",
             last_interaction_game=stamp(days=-8), last_decay_game=stamp(0))
run(r)
check("J strength 15.5 - 1.0", r["strength"], 14.5)
check("J type crossed the boundary", r["type"], "neutral")

print("\n[K] the decay math reads no system clock")
FORBIDDEN = {"utc_now", "utc_now_iso", "parse_iso", "datetime", "time",
             "game_time_at"}
tree = ast.parse((REPO / "app/core/relationship_decay.py").read_text("utf-8"))
names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Attribute):
        names.add(node.attr)
    elif isinstance(node, ast.alias):
        names.add((node.asname or node.name).split(".")[0])
check("K no system-clock name in the module", sorted(names & FORBIDDEN), [])

del sys.modules["app.models.relationship"]
del sys.modules["app.core.relationship_decay"]

# ---------------------------------------------------------------------------
# Part L — the real handler and the real model on the throwaway world DB
# ---------------------------------------------------------------------------
print("\n[L] the real handler against a throwaway world")
from app.core.character_ops import build_memory_relationships  # noqa: E402
from app.core.relationship_decay import (  # noqa: E402
    handle_relationship_decay)
from app.models.relationship import (  # noqa: E402
    load_relationships, record_interaction, save_relationships)

at(0)
save_relationships([{
    "id": "rel_smoke", "character_a": "Ada", "character_b": "Bo",
    "type": "friend", "strength": 20, "sentiment_a_to_b": 0.0,
    "sentiment_b_to_a": 0.0, "romantic_tension": 0.5,
    "interaction_count": 3, "last_interaction": utc_now_iso(),
    "last_interaction_game": stamp(days=-8), "last_decay_game": stamp(0),
    "history": [], "created_at": utc_now_iso()}])

at(days=7)
res = handle_relationship_decay({})
check("L empty payload is accepted", "error" in res, False)
check("L handler reports success", res.get("success"), True)
check("L one strength update", res.get("strength_affected"), 1)

stored = [x for x in load_relationships() if x.get("character_a") == "Ada"]
check("L the pair is still there", len(stored), 1)
if stored:
    check("L strength after one game week", stored[0]["strength"], 19.0)
    check("L romantic after one game week", stored[0]["romantic_tension"], 0.48)
    check("L the game decay stamp persisted",
          stored[0].get("last_decay_game"), stamp(days=7))

payload = build_memory_relationships("Ada")
item = next((i for i in payload["items"] if i["partner"] == "Bo"), None)
check("L the UI payload has the pair", item is not None, True)
if item:
    check("L payload carries the game stamp",
          item.get("last_interaction_game"), stamp(days=-8))
    check("L payload carries a rendered label",
          bool(item.get("last_interaction_label")), True)
    check("L payload dropped the system stamp",
          "last_interaction" in item, False)

record_interaction("Cara", "Dev", "talkto", summary="smoke")
fresh = [x for x in load_relationships()
         if {x.get("character_a"), x.get("character_b")} == {"Cara", "Dev"}]
check("L record_interaction created the pair", len(fresh), 1)
if fresh:
    check("L record_interaction wrote the game stamp",
          fresh[0].get("last_interaction_game"), stamp(days=7))
    check("L record_interaction kept the system stamp",
          bool(fresh[0].get("last_interaction")), True)

print()
print(f"(throwaway storage: {STORAGE})")
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
