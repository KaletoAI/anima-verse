#!/usr/bin/env python3
"""Ruling A123: a dressed view must show the base view's body in its pose — the framing gate refuses a dressed
figure that does not cover the base figure.

Usage:
    ./.venv/bin/python scripts/smoke_dressed_coverage_gate.py

Pure numpy, no files. Base fixture: a 400 x 200 alpha, the figure = rows 50..349 (300 px), columns 50..149
(100 px, centroid column 99.5).

Expected, by hand (COVERAGE_MIN 0.95):
[1] the same figure with a garment that widens it (columns 40..159 on rows 200..239): every base pixel is
    covered -> coverage 1.0, ok True.
[2] a narrower figure, columns 56..144 (89 px, centroid 100.0) on the same rows: base column c looks up about
    c + 0.5 (centroids 99.5 vs 100.0, ratio 1), covered for c in ~55..144 -> 89..90 of 100 columns -> coverage
    0.88..0.90, ok False, the message names "different body or pose".
[3] the same body on a wider canvas (400 x 260, columns 80..179): only the canvas differs -> coverage 1.0.
[4] the whole picture at half scale (200 x 100 canvas, rows 25..174, columns 25..74): heights 150 vs 300, ratio
    0.5; base pixel (y, c) looks up (25 + (y-50)*0.5, 49.5 + (c-99.5)*0.5) -> inside 25..74 -> coverage 1.0.
[5] Glut 2026-11-16 in numbers (from the stored mattes, recorded in the docstring, not run here): front 0.8185
    refused, back 0.9934 kept.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import base_body_gates as g  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'ok ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        FAILS.append(label)


def alpha(shape, rows, cols, extra=None):
    a = np.zeros(shape, np.uint8)
    a[rows[0]:rows[1], cols[0]:cols[1]] = 255
    if extra:
        a[extra[0]:extra[1], extra[2]:extra[3]] = 255
    return a


base = alpha((400, 200), (50, 350), (50, 150))

r = g.framing_arrays(alpha((400, 200), (50, 350), (50, 150), extra=(200, 240, 40, 160)), base)
check("[1] garment widens the figure", r["coverage"] == 1.0 and r["ok"], r)

r = g.framing_arrays(alpha((400, 200), (50, 350), (56, 145)), base)
message = g.framing_message(r, "front")
check("[2] narrower figure refused", 0.88 <= r["coverage"] <= 0.90 and not r["ok"]
      and message.startswith("front view: the dressed image shows a different body or pose"), (r, message))

r = g.framing_arrays(alpha((400, 260), (50, 350), (80, 180)), base)
check("[3] wider canvas, same body", r["coverage"] == 1.0, r)

r = g.framing_arrays(alpha((200, 100), (25, 175), (25, 75)), base)
check("[4] half-scale picture", r["coverage"] == 1.0, r)

print("FAILED: " + ", ".join(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
