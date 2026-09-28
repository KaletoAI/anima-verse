#!/usr/bin/env python3
"""Smoke: decision_log — the JSONL log, the decision_stats counters and the
register that matches a prediction with the real outcome
(development_instructions/plan-decision-models.md § 3.3 and § 9).

Usage:  ./.venv/bin/python scripts/smoke_decision_stats.py

No server, no network. A throwaway storage dir is initialised BEFORE any
world-DB module is imported; the JSONL file is redirected into it.

EXPECTATIONS, DERIVED BY HAND (each scenario uses its own point name, so the
counters of one scenario never leak into another):

C  calls. Point "p_calls", endpoint "A", min confidence 0.7:
   1) answers {"turn": ("idle", 0.9)}, 120 ms   -> 0.9 >= 0.7, not low
   2) answers {"turn": ("act", 0.5)}, 30 ms     -> 0.5 <  0.7, low
   3) error "timeout", 2000 ms                   -> no answers
   4) error "blocked", 0 ms                      -> no latency sample
   Row question '':  calls = 4, errors = {"timeout": 1, "blocked": 1}
   latency samples 120, 30, 2000 -> buckets "200" (120 <= 200), "50" (30 <= 50),
   "3200" (2000 <= 3200). p50: 3 samples, need ceil(0.5*3) = 2; cumulative
   over edges 25:0, 50:1, 100:1, 200:2 -> "<=200 ms". p95: need ceil(2.85) = 3
   -> reached at 3200 -> "<=3200 ms".
   Row question 'turn': answers = 2, low_conf = 1.
   JSONL: 4 lines, each with "starttime" and kind "call".

P  pending. Point "p_pend", endpoints A and B, min 0.7:
   P1 key k1: A delivers turn=("idle",0.9), B delivers turn=("act",0.8), both
      done; outcome {"turn":"idle"} -> A agree 1, B disagree 1 (row 'turn').
   P2 key k2 (outcome FIRST): open [A]; set_outcome {"turn":"idle"}; then A
      delivers ("idle", 0.95) done -> A agree +1 -> A agree total 2.
   P3 key k3: open [A]; A delivers ("act", 0.5) done; outcome idle -> 0.5 < 0.7,
      not compared -> A agree stays 2, disagree stays 0.
   P4 key k4: open [A]; deliver ("idle", 0.9); set_taken -> row '' taken = 1.
   P5 key k5: open [A]; deliver ("idle", 0.9); TTL forced to 0; sweep ->
      row '' no_outcome = 1.
   P6 unknown key: set_outcome on "nope" -> nothing changes, no JSONL line.
   P7 chained, point "p_chain", key k7, open [A]: deliver group=("seat",0.9)
      done=False; deliver entry=("sitting",0.8) done=True; outcome
      {"group":"seat","entry":"reading"} -> group agree 1, entry disagree 1.
   P8 failed endpoint, point "p_fail", key k8, open [A, B]: A delivers None
      (failed), B delivers ("idle",0.9); outcome idle -> B agree 1, A has no
      row for 'turn' at all.

S  _same: True==True agree; 1.4 vs 1 -> round 1 == 1 agree; 1.6 vs 1 -> 2 != 1
   disagree; "idle" vs "idle" agree.

L  percentile_label: {} -> ""; {"25":3,"100":1}: p50 need 2 -> "<=25 ms";
   p95 need ceil(3.8)=4 -> "<=100 ms"; {"inf":1} p50 -> ">6400 ms".

D  state, options, disagreements.
   D1 a shadow record_call (point "p_state", min 0.7) with
      state={"situation": "x"*3100, "who": "Kira"} and options
      {"turn": ["turn", "act", "idle"]}: 3100 > 3000 -> keep the END, the last
      2999 chars plus the "…" prefix = 3000 chars, first "…", last "x";
      "who" (4 chars) stays "Kira"; min_confidence 0.7; options as given.
      The same call in mode "on" has NO "state" key (options + min stay).
   D2 point "p_dis", endpoint A, min 0.7, question "turn", one key each:
      k1 call idle 0.9, outcome act           -> 0.9 >= 0.7 confident, idle != act
      k2 call idle 0.5, outcome act           -> 0.5 <  0.7 unsure, idle != act
      k3 call act 0.9, outcome act            -> agrees, never listed
      k4 outcome act, taken, call idle 0.9    -> a taken row -> never listed
      default               -> [k1]            (unsure left out)
      include_unsure=True   -> [k2, k1]        (k2 written later = newer)
      include_unsure, limit=1 -> [k2]
      k1 item: predicted "idle", confidence 0.9, confident True, actual "act",
      state {"who": "k1"}, options ["turn", "act", "idle"].
      Point "p_dis2", key k5, call idle 0.9 vs outcome act (no state/options
      passed): the point filter "p_dis" leaves it out, "" lists it FIRST
      (newest) with state {} and options [].
   D3 a malformed line appended to the log is skipped -> "p_dis" still [k1].
      A call row written the OLD way (no "min_confidence"), point "p_old",
      confidence 0.1, idle vs act -> treated as confident -> listed without
      include_unsure. DISAGREE_SCAN_BYTES = 1 -> only a partial line is read,
      it is dropped -> []. A missing log file -> [].
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_decision_stats_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))

from app.core.db import init_schema  # noqa: E402
init_schema()
from app.core import decision_log as DL  # noqa: E402

DL.LOG_FILE = _TMP / "decisions.jsonl"

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


def row(point, endpoint, question):
    for r in DL.query_stats(7):
        if (r["point"], r["endpoint"], r["question"]) == (point, endpoint, question):
            return r
    return None


def call(point, answers, ms, error=""):
    DL.record_call(point=point, mode="shadow", endpoint="A", key="", step=1,
                   duration_ms=ms, error=error, answers=answers, min_confidence=0.7,
                   questions={"turn": "choice"}, server_confidence={}, state_chars=10,
                   trace=None)


print("=== C calls ===")
call("p_calls", {"turn": ("idle", 0.9)}, 120)
call("p_calls", {"turn": ("act", 0.5)}, 30)
call("p_calls", None, 2000, error="timeout")
call("p_calls", None, 0, error="blocked")
r0 = row("p_calls", "A", "")
check("C calls", r0 and r0["calls"], 4)
check("C errors", r0 and r0["errors"], {"timeout": 1, "blocked": 1})
check("C p50", r0 and r0["p50"], "<=200 ms")
check("C p95", r0 and r0["p95"], "<=3200 ms")
rt = row("p_calls", "A", "turn")
check("C answers", rt and rt["answers"], 2)
check("C low_conf", rt and rt["low_conf"], 1)
lines = DL.LOG_FILE.read_text(encoding="utf-8").splitlines()
check("C jsonl lines", len(lines), 4)
check("C jsonl starttime", all('"starttime"' in ln and '"kind": "call"' in ln for ln in lines), True)

print("=== P pending ===")
DL.open_pending("p_pend", "k1", ["A", "B"], 0.7)
DL.deliver("p_pend", "k1", "A", {"turn": ("idle", 0.9)}, done=True)
DL.deliver("p_pend", "k1", "B", {"turn": ("act", 0.8)}, done=True)
DL.set_outcome("p_pend", "k1", {"turn": "idle"})
check("P1 A agree", row("p_pend", "A", "turn")["agree"], 1)
check("P1 B disagree", row("p_pend", "B", "turn")["disagree"], 1)

DL.open_pending("p_pend", "k2", ["A"], 0.7)
DL.set_outcome("p_pend", "k2", {"turn": "idle"})
DL.deliver("p_pend", "k2", "A", {"turn": ("idle", 0.95)}, done=True)
check("P2 outcome first, A agree", row("p_pend", "A", "turn")["agree"], 2)

DL.open_pending("p_pend", "k3", ["A"], 0.7)
DL.deliver("p_pend", "k3", "A", {"turn": ("act", 0.5)}, done=True)
DL.set_outcome("p_pend", "k3", {"turn": "idle"})
check("P3 low conf not compared (agree)", row("p_pend", "A", "turn")["agree"], 2)
check("P3 low conf not compared (disagree)", row("p_pend", "A", "turn")["disagree"], 0)

DL.open_pending("p_pend", "k4", ["A"], 0.7)
DL.deliver("p_pend", "k4", "A", {"turn": ("idle", 0.9)}, done=True)
DL.set_taken("p_pend", "k4")
check("P4 taken", row("p_pend", "A", "")["taken"], 1)

DL.open_pending("p_pend", "k5", ["A"], 0.7)
DL.deliver("p_pend", "k5", "A", {"turn": ("idle", 0.9)}, done=True)
_ttl = DL.PENDING_TTL_S
DL.PENDING_TTL_S = 0.0
DL.sweep()
DL.PENDING_TTL_S = _ttl
check("P5 no_outcome", row("p_pend", "A", "")["no_outcome"], 1)

_before = len(DL.LOG_FILE.read_text(encoding="utf-8").splitlines())
DL.set_outcome("p_pend", "nope", {"turn": "idle"})
check("P6 unknown key writes nothing",
      len(DL.LOG_FILE.read_text(encoding="utf-8").splitlines()), _before)

DL.open_pending("p_chain", "k7", ["A"], 0.7)
DL.deliver("p_chain", "k7", "A", {"group": ("seat", 0.9)}, done=False)
DL.deliver("p_chain", "k7", "A", {"entry": ("sitting", 0.8)}, done=True)
DL.set_outcome("p_chain", "k7", {"group": "seat", "entry": "reading"})
check("P7 group agree", row("p_chain", "A", "group")["agree"], 1)
check("P7 entry disagree", row("p_chain", "A", "entry")["disagree"], 1)

DL.open_pending("p_fail", "k8", ["A", "B"], 0.7)
DL.deliver("p_fail", "k8", "A", None, done=True)
DL.deliver("p_fail", "k8", "B", {"turn": ("idle", 0.9)}, done=True)
DL.set_outcome("p_fail", "k8", {"turn": "idle"})
check("P8 B agree", row("p_fail", "B", "turn")["agree"], 1)
check("P8 A has no turn row", row("p_fail", "A", "turn"), None)

print("=== S _same ===")
check("S bool", DL._same(True, True), True)
check("S 1.4~1", DL._same(1.4, 1), True)
check("S 1.6!~1", DL._same(1.6, 1), False)
check("S str", DL._same("idle", "idle"), True)

print("=== L percentile_label ===")
check("L empty", DL.percentile_label({}, 0.5), "")
check("L p50", DL.percentile_label({"25": 3, "100": 1}, 0.5), "<=25 ms")
check("L p95", DL.percentile_label({"25": 3, "100": 1}, 0.95), "<=100 ms")
check("L inf", DL.percentile_label({"inf": 1}, 0.5), ">6400 ms")

print("=== D state + disagreements ===")
import json  # noqa: E402

STATE = {"situation": "x" * 3100, "who": "Kira"}
OPTS = {"turn": ["turn", "act", "idle"]}


def last_row():
    return json.loads(DL.LOG_FILE.read_text(encoding="utf-8").splitlines()[-1])


for mode in ("shadow", "on"):
    DL.record_call(point="p_state", mode=mode, endpoint="A", key="", step=1, duration_ms=5,
                   error="", answers={"turn": ("idle", 0.9)}, min_confidence=0.7,
                   questions={"turn": "choice"}, server_confidence={}, state_chars=10,
                   trace=None, state=STATE, options=OPTS)
    r = last_row()
    if mode == "shadow":
        sit = (r.get("state") or {}).get("situation", "")
        check("D1 situation length", len(sit), 3000)
        check("D1 situation starts with …", sit[:1], "…")
        check("D1 situation ends with x", sit[-1:], "x")
        check("D1 who", (r.get("state") or {}).get("who"), "Kira")
    else:
        check("D1 on row has no state", "state" in r, False)
    check(f"D1 {mode} min_confidence", r.get("min_confidence"), 0.7)
    check(f"D1 {mode} options", r.get("options"), OPTS)


def dis_call(point, key, pred, conf, with_state=True):
    DL.record_call(point=point, mode="shadow", endpoint="A", key=key, step=1, duration_ms=10,
                   error="", answers={"turn": (pred, conf)}, min_confidence=0.7,
                   questions={"turn": "choice"}, server_confidence={}, state_chars=5,
                   trace=None, state={"who": key} if with_state else None,
                   options=OPTS if with_state else None)
    DL.deliver(point, key, "A", {"turn": (pred, conf)}, done=True)


for key, pred, conf in (("k1", "idle", 0.9), ("k2", "idle", 0.5), ("k3", "act", 0.9)):
    DL.open_pending("p_dis", key, ["A"], 0.7)
    dis_call("p_dis", key, pred, conf)
    DL.set_outcome("p_dis", key, {"turn": "act"})
DL.open_pending("p_dis", "k4", ["A"], 0.7)
DL.set_outcome("p_dis", "k4", {"turn": "act"})
DL.set_taken("p_dis", "k4")
dis_call("p_dis", "k4", "idle", 0.9)

keys = lambda rows: [x["key"] for x in rows]  # noqa: E731
got = DL.recent_disagreements("p_dis")
check("D2 default", keys(got), ["k1"])
check("D2 include_unsure", keys(DL.recent_disagreements("p_dis", include_unsure=True)), ["k2", "k1"])
check("D2 limit 1", keys(DL.recent_disagreements("p_dis", limit=1, include_unsure=True)), ["k2"])
it = got[0] if got else {}
check("D2 k1 fields",
      {k: it.get(k) for k in ("point", "endpoint", "question", "predicted", "confidence",
                              "confident", "actual", "state", "options")},
      {"point": "p_dis", "endpoint": "A", "question": "turn", "predicted": "idle",
       "confidence": 0.9, "confident": True, "actual": "act", "state": {"who": "k1"},
       "options": ["turn", "act", "idle"]})
check("D2 k1 starttime", bool(it.get("starttime")), True)
check("D2 k2 unsure", [x["confident"] for x in DL.recent_disagreements("p_dis", include_unsure=True)],
      [False, True])

DL.open_pending("p_dis2", "k5", ["A"], 0.7)
dis_call("p_dis2", "k5", "idle", 0.9, with_state=False)
DL.set_outcome("p_dis2", "k5", {"turn": "act"})
check("D2 point filter", keys(DL.recent_disagreements("p_dis")), ["k1"])
allr = DL.recent_disagreements("")
check("D2 all points newest first", [(x["point"], x["key"]) for x in allr][:2],
      [("p_dis2", "k5"), ("p_dis", "k1")])
check("D2 no state/options", (allr[0].get("state"), allr[0].get("options")) if allr else None, ({}, []))

with open(DL.LOG_FILE, "a", encoding="utf-8") as f:
    f.write("{not json\n")
check("D3 malformed line skipped", keys(DL.recent_disagreements("p_dis")), ["k1"])
with open(DL.LOG_FILE, "a", encoding="utf-8") as f:
    f.write(json.dumps({"starttime": "2026-01-01T00:00:00+00:00", "kind": "call", "point": "p_old",
                        "endpoint": "A", "key": "k6",
                        "answers": {"turn": {"value": "idle", "confidence": 0.1}}}) + "\n")
    f.write(json.dumps({"starttime": "2026-01-01T00:00:01+00:00", "kind": "outcome", "point": "p_old",
                        "key": "k6", "actual": {"turn": "act"}}) + "\n")
old = DL.recent_disagreements("p_old")
check("D3 old row without min_confidence = confident",
      [(x["key"], x["confident"]) for x in old], [("k6", True)])
_scan = DL.DISAGREE_SCAN_BYTES
DL.DISAGREE_SCAN_BYTES = 1
check("D3 tail of one byte -> partial line dropped", DL.recent_disagreements(""), [])
DL.DISAGREE_SCAN_BYTES = _scan
_log = DL.LOG_FILE
DL.LOG_FILE = _TMP / "missing.jsonl"
check("D3 missing file", DL.recent_disagreements(""), [])
DL.LOG_FILE = _log

print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
sys.exit(1 if FAILS else 0)
