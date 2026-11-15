#!/usr/bin/env python3
"""Ruling A100: a base front whose figure runs out of the image never passes the front gate and ranks behind every
attempt in frame.

Usage:
    ./.venv/bin/python scripts/smoke_front_framing_gate.py

Pure numpy, no files. Fixture: a 400 x 200 alpha, a column x 90..109 (20 px wide) on rows 20..379 = the figure.

Expected, by hand (EDGE_CUT_PX 8, EDGE_CUT_PENALTY 1.0):
[1] edge_cut: in frame -> None; the column down to row 399 (20 px on the bottom row) -> "bottom"; from row 0 -> "top";
    only 5 px on the bottom row (x 90..94) -> None (below 8).
[2] hand_pose_gate_mask: the column has no arm end, so the hand part is unmeasurable (ok True, score None);
    cut at the bottom -> ok False, cut "bottom", score 0 + 1.0 = 1.0.
[3] best_attempt([cut with score 1.04, in frame failing with 0.20]) -> (1, False): the one in frame wins (Ylva
    2026-11-15: attempt 1 hand score 0.2014 with feet, attempt 2 0.0417 without -> now 1.0417, attempt 1 kept).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import base_body_gates as g  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def column(top, bottom, x0=90, x1=110):
    a = np.zeros((400, 200), dtype=np.uint8)
    a[top:bottom + 1, x0:x1] = 255
    return a


print("[1] edge_cut")
check("in frame", g.edge_cut(column(20, 379)), None)
check("bottom", g.edge_cut(column(20, 399)), "bottom")
check("top", g.edge_cut(column(0, 379)), "top")
thin = column(20, 379)
thin[399, 90:95] = 255
check("5 px only", g.edge_cut(thin), None)
print("[2] the gate")
r = g.hand_pose_gate_mask(column(20, 379))
check("in frame", (r["ok"], r["score"], r.get("cut")), (True, None, None))
r = g.hand_pose_gate_mask(column(20, 399))
check("cut", (r["ok"], r["score"], r.get("cut")), (False, 1.0, "bottom"))
print("[3] best_attempt")
check("in frame wins", g.best_attempt([{"ok": False, "score": 1.0417, "cut": "bottom"}, {"ok": False, "score": 0.2014}]),
      (1, False))
print("All checks passed." if not FAILS else f"FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
