#!/usr/bin/env python3
"""Smoke: ``_cmu.resample_indices`` never hands out a frame index past the
take (review 04#1). The converters (``cmu_clip``, ``fbx_clip``) and the CMU
previews index ``frames[i]`` with what it returns, so an index ``n_frames``
was an IndexError in the Blender run.
No Blender: ``_cmu`` is standard library only.

Usage: ./.venv/bin/python scripts/smoke_clip_resample_indices.py

The stepping: ``t`` starts at the first source frame and advances by
``step = source_fps · speed / fps`` while ``t < last``; the index is
``round(t)``. A ``t`` in ``(n − 1.5, n)`` rounds to ``n``.

[1] 24 → 30 fps, n = 2, speed 1: step 0.8, t = 0, 0.8, 1.6 → round 0, 1, 2;
    the 2 is past the take (frames 0..1) → clamped to 1 → [0, 1, 1].
[2] 30 → 30 fps, n = 2, speed 0.5: step 0.5, t = 0, 0.5, 1.0, 1.5 → round
    (half to even) 0, 0, 1, 2 → the 2 clamped → [0, 0, 1, 1].
[3] integer ratios at speed 1 are untouched: 120 → 30, n = 10, step 4,
    t = 0, 4, 8 → [0, 4, 8]; 30 → 30, n = 5 → [0, 1, 2, 3, 4].
[4] an ``end_s`` inside the take keeps its last frame: 24 → 30, n = 10,
    end_s 0.25 → last = round(0.25 · 24) = 6, t = 0, 0.8, …, 5.6 → round
    0, 1, 2, 2, 3, 4, 5, 6 — 6 is a frame of the take, nothing changes.
[5] sweep: n = 2..399, source fps 24 / 25 / 29.97 / 50 / 120 → 30, speed
    1 / 0.5 / 0.7 / 0.9: every index in 0..n−1, never decreasing, and the
    count of output frames is the unclamped stepping's (the clamp changes
    only the out-of-range values, to n − 1).
[6] proof against the old body (run inline below): case [1] returns 2 for
    n = 2, and the sweep has out-of-range results (> 0).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/blender/scripts"))
import _cmu  # noqa: E402

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        FAIL.append(label)


def old_resample(n_frames, source_fps, fps, start_s=0.0, end_s=None, speed=1.0):
    """The body before the fix (review 04#1), for the proof in [6]."""
    first = int(round(start_s * source_fps))
    last = n_frames if end_s is None else min(n_frames, int(round(end_s * source_fps)))
    speed = float(speed) if speed and speed > 0 else 1.0
    step = source_fps * speed / fps
    idx = []
    t = float(first)
    while t < last - 1e-6:
        idx.append(int(round(t)))
        t += step
    return idx


check("[1] 24->30 n=2", _cmu.resample_indices(2, 24, 30), [0, 1, 1])
check("[2] 30->30 n=2 speed 0.5", _cmu.resample_indices(2, 30, 30, speed=0.5), [0, 0, 1, 1])
check("[3] 120->30 n=10", _cmu.resample_indices(10, 120, 30), [0, 4, 8])
check("[3] 30->30 n=5", _cmu.resample_indices(5, 30, 30), [0, 1, 2, 3, 4])
check("[4] 24->30 n=10 end 0.25", _cmu.resample_indices(10, 24, 30, end_s=0.25),
      [0, 1, 2, 2, 3, 4, 5, 6])

bad = []
old_bad = 0
for src in (24, 25, 29.97, 50, 120):
    for speed in (1.0, 0.5, 0.7, 0.9):
        for n in range(2, 400):
            idx = _cmu.resample_indices(n, src, 30, speed=speed)
            ref = old_resample(n, src, 30, speed=speed)
            old_bad += max(ref) >= n
            if (not idx or max(idx) >= n or min(idx) < 0
                    or any(b < a for a, b in zip(idx, idx[1:]))
                    or idx != [min(i, n - 1) for i in ref]):
                bad.append((src, speed, n))
check("[5] sweep: in range, monotonic, same count", bad[:5], [])

check("[6] old body returns the index n for case [1]", old_resample(2, 24, 30), [0, 1, 2])
check("[6] old body has out-of-range results in the sweep", old_bad > 0, True)

print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
sys.exit(1 if FAIL else 0)
