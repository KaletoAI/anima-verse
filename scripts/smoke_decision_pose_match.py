#!/usr/bin/env python3
"""Smoke: decision points pose_match / expression_match in
pose_catalog.resolve_to_catalog (development_instructions/plan-decision-models.md § 4.2, § 9).

Usage:  ./.venv/bin/python scripts/smoke_decision_pose_match.py

decide() is stubbed (no network); the catalogs are the real shared ones.

EXPECTATIONS, DERIVED BY HAND (shared/templates/pose/pose_catalog.json today:
groups stand 37 / seat 14 / ground 3 / lie 2 entries, every entry grouped;
expression catalog: 8 entries, no groups):
Q1 catalog_questions("pose") -> first question "group" with the 4 group ids,
   and a then(); then({"group": seat}) -> "entry" with the 14 seat keys + "none"
   = 15 options; then({}) -> None (no confident group, stop).
Q2 catalog_questions("expression") -> one question "entry" with 8 keys + "none"
   = 9 options, then is None.
R1 point inactive (is_active False) -> decide never called; an exact alias
   still resolves "exact" as before.
R2 active, decide -> entry "sitting" (a real key) -> ("sitting", "decision"),
   mark_taken once, no outcome recorded.
R3 active, decide -> entry "none" -> (default key, "decision_none") and the
   text lands in the candidate list.
R4 active, decide -> None -> usual path (stubbed embedding returns nothing ->
   "fallback"), record_outcome with {"entry": "none"} (fallback = none), no group.
R5 decide raises -> resolve_to_catalog still returns ("<default>", "fallback").
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_decision_pose_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))
from app.core.db import init_schema  # noqa: E402
init_schema()

from app.core import decision, decision_points as DP, pose_catalog as PC  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


print("=== Q questions ===")
first, then = DP.catalog_questions("pose")
check("Q1 first is group", list(first), ["group"])
check("Q1 group options", sorted(first["group"].options), ["ground", "lie", "seat", "stand"])
nxt = then({"group": decision.Answer("seat", None, 0.9, {})})
check("Q1 entry options", len(nxt["entry"].options), 15)
check("Q1 none option", DP.NONE_KEY in nxt["entry"].options, True)
check("Q1 then({}) stops", then({}), None)
first_e, then_e = DP.catalog_questions("expression")
check("Q2 expression entry only", list(first_e), ["entry"])
check("Q2 expression options", len(first_e["entry"].options), 9)
check("Q2 no then", then_e, None)

CALLS, OUTCOMES, TAKEN = [], [], []
ACTIVE = [False]
RESULT = [None]


def fake_decide(point, state, questions, *, key=None, then=None):
    CALLS.append(point)
    if isinstance(RESULT[0], Exception):
        raise RESULT[0]
    return RESULT[0]


decision.is_active = lambda point: ACTIVE[0]
decision.decide = fake_decide
decision.record_outcome = lambda point, key, actual: OUTCOMES.append(actual)
decision.mark_taken = lambda point, key: TAKEN.append(key)
no_embed = lambda text: None  # noqa: E731
DEFAULT = PC.get_default_key("pose")


def reset(active, result):
    ACTIVE[0] = active
    RESULT[0] = result
    for lst in (CALLS, OUTCOMES, TAKEN):
        lst.clear()


print("=== R resolve ===")
reset(False, None)
check("R1 exact alias", PC.resolve_to_catalog("stehen", "pose", _embed=no_embed), ("standing", "exact"))
check("R1 inactive fallback", PC.resolve_to_catalog("xyzzy lehnt", "pose", _embed=no_embed), (DEFAULT, "fallback"))
check("R1 decide not called", CALLS, [])

reset(True, decision.Decision(answers={"group": decision.Answer("seat", None, 0.9, {}),
                                       "entry": decision.Answer("sitting", None, 0.8, {})}))
check("R2 decision key", PC.resolve_to_catalog("xyzzy hockt", "pose", _embed=no_embed), ("sitting", "decision"))
check("R2 taken", len(TAKEN), 1)
check("R2 no outcome", OUTCOMES, [])

reset(True, decision.Decision(answers={"entry": decision.Answer("none", None, 0.9, {})}))
check("R3 none", PC.resolve_to_catalog("xyzzy jongliert", "pose", _embed=no_embed), (DEFAULT, "decision_none"))
check("R3 candidate", any(c["raw_text"] == "xyzzy jongliert" for c in PC.list_candidates("pose")), True)

reset(True, None)
check("R4 usual path", PC.resolve_to_catalog("xyzzy tanzt", "pose", _embed=no_embed), (DEFAULT, "fallback"))
check("R4 outcome", OUTCOMES, [{"entry": "none"}])

reset(True, RuntimeError("boom"))
check("R5 never raises", PC.resolve_to_catalog("xyzzy schwebt", "pose", _embed=no_embed), (DEFAULT, "fallback"))

print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
sys.exit(1 if FAILS else 0)
