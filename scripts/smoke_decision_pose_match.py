#!/usr/bin/env python3
"""Smoke: decision points pose_match / expression_match in
pose_catalog.resolve_to_catalog (development_instructions/plan-decision-models.md § 4.2, § 9).

Usage:  ./.venv/bin/python scripts/smoke_decision_pose_match.py

decide() is stubbed (no network). The pose catalog is the real shared one
PINNED at commit 1010e7d1 (read with `git show`, written to a temp file the
catalog reads) — the working tree's file carries local-only entries and
grows with every new pose, which would move every spread below; the
expression catalog is the working tree's.

EXPECTATIONS, DERIVED BY HAND (the pose catalog at 1010e7d1:
groups stand 43 / seat 14 / ground 5 / lie 3 entries, every entry grouped;
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

T option texts (budget rule _option_budget(n) = max(80, min(220, 1400 // n))):
T1 _option_budget: 4 -> 220 (1400//4 = 350, capped), 9 -> 155, 38 -> 80 (1400//38 = 36,
   floored), 0 -> 220 (n treated as 1).
T2 group question instructions = "Which body position does the text describe? Each option
   lists poses of that position."; examples = the default, then k <= 9 (10 in all) keys
   spread evenly over the rest: rest index round_half_up(i * (len(rest)-1) / (k-1)).
   Group "stand" (label "Standing spot", default "standing"; rest = the 42 other keys
   alphabetical, rest[0] celebrating .. rest[41] washing_dishes), k = 9, step 41/8 = 5.125:
   i=0 -> 0 celebrating, 1 -> 5.125 -> 5 comforting, 2 -> 10.25 -> 10 digging,
   3 -> 15.375 -> 15 forehead-wiping, 4 -> 20.5 -> 21 leaning, 5 -> 25.625 -> 26 picking up,
   6 -> 30.75 -> 31 shooting, 7 -> 35.875 -> 36 talking, 8 -> 41 washing_dishes.
   Length: "Standing spot: " 15 + standing 23 + celebrating 36 + comforting 48 + digging 57 +
   forehead-wiping 74 + leaning 83 + picking up 95 + shooting 105 + talking 114 +
   washing_dishes 130 <= 220, so all 10 fit ->
   "Standing spot: standing, celebrating, comforting, digging, forehead-wiping, leaning,
   picking up, shooting, talking, washing_dishes".
   Group "lie" (label "Lying place", rest = [sleeping, sleeping on back], k = 2 -> 0, 1) ->
   exactly "Lying place: lying, sleeping, sleeping on back"; "ground" (rest bathing,
   gardening, meditating, yoga; k = 4 -> 0, 1, 2, 3) -> "Ground: kneeling, bathing,
   gardening, meditating, yoga"; no group option longer than _option_budget(4)=220.
T3 expression entry question has 9 options (8 + none) -> budget 155. neutral: prefix
   "neutral: calm neutral face, relaxed brow, soft mouth, attentive eyes; e.g. " = 75 chars,
   then synonyms while <= 155: focused 82, thoughtful 94, curious 103, determined 115,
   calm 121, relaxed 130, creative 140, in control 152, chatting would be 162 -> stop.
   So the option is the prefix + "focused, thoughtful, curious, determined, calm, relaxed,
   creative, in control" (152 chars). Every expression option starts with "<key>: " and
   contains its prompt; the none option reads "none of these fits the text".
T4 pose group "stand" entry question: 43 + none = 44 options -> budget 80 (1400//44 = 31,
   floored); no option longer than 80, none contains its pose prompt, each starts with
   "<key>: " or is just the key.
T5 pose group "lie" entry question: 3 + none = 4 options (<= 12) -> the pose prompt IS
   offered: the options of lying, sleeping and sleeping on back each contain their prompt.
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
import subprocess  # noqa: E402

PINNED = "1010e7d1"
_PINNED_CATALOG = _TMP / "pose_catalog.json"
_PINNED_CATALOG.write_text(subprocess.run(
    ["git", "-C", str(ROOT), "show", f"{PINNED}:shared/templates/pose/pose_catalog.json"],
    capture_output=True, text=True, check=True, encoding="utf-8").stdout, encoding="utf-8")
PC.catalog_path = lambda axis, _orig=PC.catalog_path: (
    _PINNED_CATALOG if axis == "pose" else _orig(axis))
PC.reload_catalogs()

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
first_e, then_e = DP.catalog_questions("expression", set_id="humanoid")
check("Q2 expression entry only", list(first_e), ["entry"])
check("Q2 expression options", len(first_e["entry"].options), 9)
check("Q2 no then", then_e, None)

print("=== T option texts ===")
check("T1 budget 4", DP._option_budget(4), 220)
check("T1 budget 9", DP._option_budget(9), 155)
check("T1 budget 38", DP._option_budget(38), 80)
check("T1 budget 0", DP._option_budget(0), 220)
gq = first["group"]
check("T2 no group option over budget(4)",
      [g for g, o in gq.options.items() if len(o) > DP._option_budget(4)], [])
eq = first_e["entry"]
from app.core.expression_sets import catalog_snapshot
expr = {key: PC.get_catalog("expression")[key] for key in catalog_snapshot().sets["humanoid"].members}
check("T3 every expression option = key + prompt",
      [k for k, e in expr.items()
       if not (eq.options[k].startswith(f"{k}: ") and e.get("prompt")
               and e.get("prompt") in eq.options[k])], [])
check("T3 expression options within budget",
      [k for k, o in eq.options.items() if len(o) > DP._option_budget(len(eq.options))], [])
stand_q = then({"group": decision.Answer("stand", None, 0.9, {})})["entry"]
check("T4 stand entry options", len(stand_q.options), 44)
pose = PC.get_catalog("pose")
check("T4 stand entries within budget",
      [k for k, o in stand_q.options.items() if len(o) > DP._option_budget(len(stand_q.options))], [])
check("T4 stand entries without prompt",
      [k for k, o in stand_q.options.items()
       if (pose.get(k) or {}).get("prompt") and pose[k].get("prompt") in o], [])
check("T4 stand entries start with key",
      [k for k, o in stand_q.options.items() if k != DP.NONE_KEY and not (o == k or o.startswith(f"{k}: "))], [])
lie_q = then({"group": decision.Answer("lie", None, 0.9, {})})["entry"]
check("T5 lie options", sorted(lie_q.options), ["lying", DP.NONE_KEY, "sleeping", "sleeping on back"])
check("T5 lie entries carry their prompt",
      [k for k, o in lie_q.options.items()
       if k != DP.NONE_KEY and not ((pose.get(k) or {}).get("prompt")
                                    and pose[k].get("prompt") in o)], [])

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
