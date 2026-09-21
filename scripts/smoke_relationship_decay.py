#!/usr/bin/env python3
"""Relationship decay: the handler must RUN (no ``user_id`` gate) and must
charge one week of idleness per week, not per run.

Usage:
    ./.venv/bin/python scripts/smoke_relationship_decay.py

No server. Part A stubs ``app.models.relationship`` with an in-memory store, so
the decay arithmetic is checked on its own. Part B runs the handler with the
real model against a THROWAWAY storage directory (tempfile + ``paths.init``),
which is what the periodic sub-job now submits: ``{}``.

Why this exists (review 2026-09-20, DATA-4): ``_sub_relationship_decay``
submitted ``{"user_id": ""}`` and the handler answered
``{"error": "user_id missing"}`` — the job has not decayed anything since the
multi-user rework, and the handler body never used ``user_id``.

Expected values, derived by hand (DECAY_STRENGTH_PER_WEEK = 1.0,
DECAY_ROMANTIC_PER_WEEK = 0.02, GRACE_DAYS = 7, MAX_WEEKS_PER_RUN = 2):

  A1 pair idle 2 days                -> untouched (inside the grace period),
                                        and no ``last_decay`` stamp
  A2 pair idle 90 days, first run    -> strength unchanged, ``last_decay``
                                        stamped at now. Charging 90/7 = 12.8
                                        weeks at once would take 12.8 strength
                                        off a pair that never had a decay run.
  A3 same pair, next run 1 day later -> 1/7 week: strength 20 - 0.142857 =
                                        19.857143 -> rounded (2 dp) 19.86;
                                        romantic 0.5 - 0.02/7 = 0.497143
                                        -> rounded 0.497
  A7 seven daily runs                -> about one full week of decay (1.0);
                                        rounding strength to ONE decimal would
                                        only take off 0.7
  A4 stamp 30 days old (downtime)    -> weeks = 30/7 = 4.29, capped at 2:
                                        strength 20 - 2 = 18.0,
                                        romantic 0.5 - 0.04 = 0.46
  A5 interaction AFTER the last decay stamp (stamp 30 d old, interaction 7 d
     ago) -> reference is the interaction: weeks = 1.0,
             strength 20 - 1 = 19.0, romantic 0.5 - 0.02 = 0.48
  A6 strength already 0, romantic 0  -> stays 0 (max(0, ...)), stamp refreshed

  B1 handler called with ``{}``      -> no "error" key, returns success

Fails before the fix: A1-A6 all return ``{"error": "user_id missing"}`` (the
old handler's first two statements), so every check fails; B1 fails on the same
key. Confirmed by running this script against ``git show HEAD:…`` of the module
(see the report).
"""
import importlib
import os
import sys
import tempfile
import types
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="reldecay-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="reldecay-clips-")

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


def iso_days_ago(days):
    return (utc_now() - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Part A — pure decay arithmetic against a stubbed relationship model
# ---------------------------------------------------------------------------
importlib.import_module("app")   # parent package before we inject a submodule

_store = {"rels": []}
_fake = types.ModuleType("app.models.relationship")
_fake.load_relationships = lambda: _store["rels"]
_fake.save_relationships = lambda rels: _store.__setitem__("saved", True)
_fake.are_romantically_compatible = lambda a, b: True


def _classify_type(strength, sa, sb, tension, romantic_compatible=True):
    return "friend" if strength >= 15 else "acquaintance"


_fake.classify_type = _classify_type
sys.modules["app.models.relationship"] = _fake

from app.core import relationship_decay as RD  # noqa: E402


def make_rel(**kw):
    rel = {"character_a": "Ada", "character_b": "Bo", "strength": 20,
           "sentiment_a_to_b": 0.0, "sentiment_b_to_a": 0.0,
           "romantic_tension": 0.5, "type": "friend",
           "last_interaction": iso_days_ago(90)}
    rel.update(kw)
    return rel


def run(rel):
    _store["rels"] = [rel]
    _store.pop("saved", None)
    return RD.handle_relationship_decay({})


print("A) decay arithmetic")
r = make_rel(last_interaction=iso_days_ago(2))
res = run(r)
check("A1 inside the grace period: strength", r["strength"], 20)
check("A1 no stamp inside the grace period", "last_decay" in r, False)
check("A1 no error key", "error" in res, False)

r = make_rel()
run(r)
check("A2 first run does not charge the backlog", r["strength"], 20)
check("A2 first run stamps last_decay", bool(r.get("last_decay")), True)

r = make_rel(last_decay=iso_days_ago(1))
run(r)
check("A3 one day of decay: strength", r["strength"], 19.86)
check("A3 one day of decay: romantic", r["romantic_tension"], 0.497)

r = make_rel(last_decay=iso_days_ago(30))
run(r)
check("A4 long downtime is capped at 2 weeks: strength", r["strength"], 18.0)
check("A4 long downtime is capped at 2 weeks: romantic",
      r["romantic_tension"], 0.46)

r = make_rel(last_decay=iso_days_ago(30), last_interaction=iso_days_ago(7))
run(r)
check("A5 an interaction resets the reference: strength", r["strength"], 19.0)
check("A5 an interaction resets the reference: romantic",
      r["romantic_tension"], 0.48)

r = make_rel(strength=0, romantic_tension=0.0, last_decay=iso_days_ago(30))
run(r)
check("A6 floor at zero: strength", r["strength"], 0)
check("A6 floor at zero: romantic", r["romantic_tension"], 0.0)

# The steady state: one run per day for a week must cost about one week of
# decay, not seven (the pre-fix code charged min(weeks, 2) EVERY run).
r = make_rel(last_decay=iso_days_ago(7))
start = r["strength"]
for _ in range(7):
    r["last_decay"] = iso_days_ago(1)
    run(r)
check("A7 seven daily runs cost about one week",
      round(start - r["strength"], 1), 1.0)

del sys.modules["app.models.relationship"]
del sys.modules["app.core.relationship_decay"]

# ---------------------------------------------------------------------------
# Part B — the real handler with the real model on a throwaway storage dir
# ---------------------------------------------------------------------------
print("B) handler against a throwaway world")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.relationship_decay import (  # noqa: E402
    handle_relationship_decay)
from app.models.relationship import (  # noqa: E402
    load_relationships, save_relationships)

save_relationships([{
    "id": "rel_smoke", "character_a": "Ada", "character_b": "Bo",
    "type": "friend", "strength": 20, "sentiment_a_to_b": 0.0,
    "sentiment_b_to_a": 0.0, "romantic_tension": 0.5,
    "interaction_count": 3, "last_interaction": iso_days_ago(90),
    "last_decay": iso_days_ago(7), "history": [],
    "created_at": iso_days_ago(120)}])

res = handle_relationship_decay({})
check("B1 empty payload is accepted", "error" in res, False)
check("B1 handler reports success", res.get("success"), True)
check("B1 one strength update", res.get("strength_affected"), 1)

stored = [r for r in load_relationships() if r.get("character_a") == "Ada"]
check("B1 relationship still there", len(stored), 1)
if stored:
    # 7 days since the last decay run -> exactly one week -> 20 - 1 = 19.0
    check("B1 strength after one week of idleness", stored[0]["strength"], 19.0)
    check("B1 romantic after one week of idleness",
          stored[0]["romantic_tension"], 0.48)
    check("B1 last_decay persisted", bool(stored[0].get("last_decay")), True)

print()
print(f"(throwaway storage: {STORAGE})")
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
