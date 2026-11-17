#!/usr/bin/env python3
"""WebM companions: a failed encode is remembered, the sweep spares running encodes (app/core/video_webm.py) —
review 09#4.

Usage:
    ./.venv/bin/python scripts/smoke_video_webm_failures.py

No ffmpeg runs: ``shutil.which`` names a fake binary and ``subprocess.run`` inside the module is a recorder that
either fails (returncode 1) or writes 4 bytes to the temp output (returncode 0). No storage, no world, no server —
only a temp directory with ``a.mp4`` (bytes, never decoded). FAILED_RETRY_S = 3600, ENCODE_TIMEOUT_S = 300,
STRAY_TMP_AGE_S = 360.

Expected, by hand from the module's rules:
[1] Encoder failing: ``ensure_webm(a.mp4)`` -> None after 1 run; again -> None, still 1 run (the failure of
    this mp4 is remembered; the old code ran ffmpeg on every request: 2 runs).
[2] The mp4 rewritten (another size) -> tried again: 2 runs, None.
[3] The clock 3601 s on (``time.monotonic`` of the module) -> tried again: 3 runs, None.
[4] Encoder working, the clock 3601 s further: -> the companion ``.video-webm/a.webm`` (4 bytes), 4 runs; the
    failure record is gone; a further call -> the companion with no run (fresh).
[5] Sweep of the directory: a temp file ``.a.1.2.tmp.webm`` written now stays (an encode in flight; the old
    sweep removed it); one aged 361 s goes; ``orphan.webm`` (no orphan.mp4) goes; ``a.webm`` stays -> 2 removed.
Fails on 3f2ce338e in [1] (2 runs), [4] (one run more each) and [5] (3 removed, the young temp file gone).
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import video_webm  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


runs = []
mode = {"ok": False}


def fake_run(cmd, capture_output=True, timeout=None):
    runs.append(cmd)
    if mode["ok"]:
        Path(cmd[-1]).write_bytes(b"webm")
        return SimpleNamespace(returncode=0, stderr=b"")
    return SimpleNamespace(returncode=1, stderr=b"Invalid data found when processing input")


clock = {"t": 1000.0}
video_webm.shutil = SimpleNamespace(which=lambda name: "/fake/ffmpeg")
video_webm.subprocess = SimpleNamespace(run=fake_run, TimeoutExpired=TimeoutError)
video_webm.time = SimpleNamespace(monotonic=lambda: clock["t"], time=time.time)

with tempfile.TemporaryDirectory(prefix="webm-failures-") as tmp:
    d = Path(tmp)
    clip = d / "a.mp4"
    clip.write_bytes(b"not really a video")

    print("[1] a failed encode is remembered")
    check("first call", video_webm.ensure_webm(clip), None)
    check("runs", len(runs), 1)
    check("second call", video_webm.ensure_webm(clip), None)
    check("runs", len(runs), 1)

    print("[2] a replaced mp4 is tried again")
    clip.write_bytes(b"another upload, longer")
    check("call", video_webm.ensure_webm(clip), None)
    check("runs", len(runs), 2)

    print("[3] after FAILED_RETRY_S")
    clock["t"] += 3601
    check("call", video_webm.ensure_webm(clip), None)
    check("runs", len(runs), 3)

    print("[4] a working encode")
    mode["ok"] = True
    clock["t"] += 3601
    target = (d / ".video-webm" / "a.webm").resolve()
    check("call", video_webm.ensure_webm(clip), target)
    check("runs", len(runs), 4)
    check("companion bytes", target.read_bytes(), b"webm")
    check("failure record gone", str(target) in getattr(video_webm, "_failed", {}), False)
    check("fresh: no run", (video_webm.ensure_webm(clip), len(runs)), (target, 4))

    print("[5] the sweep")
    companions = d / ".video-webm"
    young = companions / ".a.1.2.tmp.webm"
    old = companions / ".a.3.4.tmp.webm"
    orphan = companions / "orphan.webm"
    for p in (young, old, orphan):
        p.write_bytes(b"x")
    when = time.time() - 361
    os.utime(old, (when, when))
    check("removed", video_webm.sweep_orphans([d]), 2)
    check("left", sorted(p.name for p in companions.iterdir()), [".a.1.2.tmp.webm", "a.webm"])

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
