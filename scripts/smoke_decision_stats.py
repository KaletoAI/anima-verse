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

print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
sys.exit(1 if FAILS else 0)
