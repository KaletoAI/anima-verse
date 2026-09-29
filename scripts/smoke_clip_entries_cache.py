#!/usr/bin/env python3
"""Smoke run for the clip-entry cache (plan-befundrunde-2026-09-29 B9a, incl.
the binding review notes).

Usage:  ./.venv/bin/python scripts/smoke_clip_entries_cache.py

Builds a throwaway clip tree and points ANIMATION_CLIPS_DIR at it (the
licensed library is then ``<that>-licensed``); ``paths.init`` gets a temp
world first. The real shared/models/clips is never read or touched.
Directory mtimes are dated back with ``os.utime`` — that is how the check
controls the "younger than one second is not trusted" rule.

THE RULE
---------------------------------------------------------------------------
``clip_entries()`` caches its scan behind a fingerprint: the resolved roots
of BOTH libraries (a missing one = "absent") plus ``st_mtime_ns`` of every
root and set subdirectory, taken BEFORE the scan. A directory mtime younger
than 1 s is not trusted — that result is not cached. Callers get copies.
``reload_clip_caches()`` empties the cache and reloads the pose catalogs
exactly ONCE (it used to reload them twice). The two clip imports call it.
``interaction_engine.partner_poses`` asks ``pair_kinds()`` once, not once
per catalog pose.

Hand-derived expectations
---------------------------------------------------------------------------
[1] tree {walk.fbx, male/sit.fbx}, both dirs dated 10 s back:
    first call scans (1 scan), second call does not (still 1); neither call
    uses ``Path.iterdir``; entries = [("", "walk.fbx", free),
    ("male", "male/sit.fbx", free)].
[2] mutating a returned entry does not change the next result.
[3] a file added to male/ (mtime now = fresh): the next call scans and sees
    male/run.fbx; because the mtime is < 1 s old it is NOT cached — the call
    after that scans again. Dated back: one more scan, then cached (no scan).
[4] the fingerprint is taken BEFORE the scan: a file that appears DURING a
    scan (dir re-dated to another settled time inside the scan) is seen by the
    next call — with an after-scan fingerprint the cache would match and hide it.
[5] a licensed library appearing (walk.fbx there, dated back) → the next
    call scans, walk.fbx now comes from "licensed" (licensed wins).
[6] ``reload_clip_caches()`` → the next call scans although nothing changed;
    the pose catalogs were reloaded exactly once by it.
[7] another ANIMATION_CLIPS_DIR is another key → scan, its own entries.
[8] static: ``fbx_import.import_fbx`` and ``clip_catalog.import_take`` call
    ``reload_clip_caches()``.
[9] ``partner_poses()`` calls ``pair_kinds()`` exactly once.
"""
import ast
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLIPS = Path(tempfile.mkdtemp(prefix="clip-cache-smoke-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-cache-world-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ.pop("ANIMATION_CLIPS_LICENSED_DIR", None)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac  # noqa: E402
from app.core import expression_pose_maps as epm  # noqa: E402
from app.core import interaction_engine as ie  # noqa: E402

LICENSED = Path(str(CLIPS) + "-licensed")
REPO = Path(__file__).resolve().parents[1]
FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def backdate(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


SCANS = [0]
_real_scan = ac._scan_entries
DURING_SCAN = []   # callables run right after the real scan (for [4])


def _counting_scan(libraries):
    SCANS[0] += 1
    out = _real_scan(libraries)
    while DURING_SCAN:
        DURING_SCAN.pop(0)()
    return out


ac._scan_entries = _counting_scan

ITERDIR = [0]
_real_iterdir = Path.iterdir


def _counting_iterdir(self):
    ITERDIR[0] += 1
    return _real_iterdir(self)


Path.iterdir = _counting_iterdir


def summary(entries):
    return [(e["set"], e["rel"], e["source"]) for e in entries]


# [1]
print("\n[1] second call without a change does not scan")
(CLIPS / "walk.fbx").write_bytes(b"w")
(CLIPS / "male").mkdir()
(CLIPS / "male" / "sit.fbx").write_bytes(b"s")
backdate(CLIPS / "male", 10)
backdate(CLIPS, 10)
ac._clear_entries_cache()
first = ac.clip_entries()
check("first call scans once", SCANS[0] == 1, str(SCANS[0]))
second = ac.clip_entries()
check("second call does not scan", SCANS[0] == 1, str(SCANS[0]))
check("no Path.iterdir on either call", ITERDIR[0] == 0, str(ITERDIR[0]))
check("entries as expected",
      summary(second) == [("", "walk.fbx", "free"), ("male", "male/sit.fbx", "free")],
      str(summary(second)))

# [2]
print("\n[2] callers get copies")
second[0]["kind"] = "tampered"
third = ac.clip_entries()
check("the cache is untouched", third[0]["kind"] == "walk", third[0]["kind"])

# [3]
print("\n[3] a new file is seen; a fresh mtime is not cached")
(CLIPS / "male" / "run.fbx").write_bytes(b"r")
n = SCANS[0]
seen = ac.clip_entries()
check("next call scans", SCANS[0] == n + 1, str(SCANS[0] - n))
check("male/run.fbx is there", ("male", "male/run.fbx", "free") in summary(seen),
      str(summary(seen)))
ac.clip_entries()
check("fresh mtime (< 1 s): the call after scans again", SCANS[0] == n + 2,
      str(SCANS[0] - n))
backdate(CLIPS / "male", 5)
ac.clip_entries()
check("dated back: one more scan", SCANS[0] == n + 3, str(SCANS[0] - n))
ac.clip_entries()
check("then cached", SCANS[0] == n + 3, str(SCANS[0] - n))

# [4]
print("\n[4] fingerprint before the scan")
backdate(CLIPS / "male", 20)      # a settled, different mtime → forces a scan
n = SCANS[0]


def _add_during_scan():
    (CLIPS / "male" / "jump.fbx").write_bytes(b"j")
    backdate(CLIPS / "male", 8)   # settled again, but not the pre-scan mtime


DURING_SCAN.append(_add_during_scan)
during = ac.clip_entries()
check("the scan ran (and missed the late file)",
      SCANS[0] == n + 1 and ("male", "male/jump.fbx", "free") not in summary(during),
      str(summary(during)))
after = ac.clip_entries()
check("the next call scans again and sees it",
      SCANS[0] == n + 2 and ("male", "male/jump.fbx", "free") in summary(after),
      f"{SCANS[0] - n} {summary(after)}")

# [5]
print("\n[5] a licensed library appears")
LICENSED.mkdir()
(LICENSED / "walk.fbx").write_bytes(b"lw")
backdate(LICENSED, 10)
n = SCANS[0]
lic = ac.clip_entries()
check("scanned", SCANS[0] == n + 1, str(SCANS[0] - n))
check("walk.fbx now licensed", ("", "walk.fbx", "licensed") in summary(lic),
      str(summary(lic)))

# [6]
print("\n[6] reload_clip_caches")
ac.clip_entries()
n = SCANS[0]
RELOADS = [0]
_real_reload = epm.reload_catalogs


def _counting_reload():
    RELOADS[0] += 1
    return _real_reload()


epm.reload_catalogs = _counting_reload
try:
    ac.reload_clip_caches()
finally:
    epm.reload_catalogs = _real_reload
ac.clip_entries()
check("next call scans although nothing changed", SCANS[0] == n + 1, str(SCANS[0] - n))
check("pose catalogs reloaded exactly once", RELOADS[0] == 1, str(RELOADS[0]))

# [7]
print("\n[7] another library path is another key")
OTHER = Path(tempfile.mkdtemp(prefix="clip-cache-other-"))
(OTHER / "swim.fbx").write_bytes(b"x")
backdate(OTHER, 10)
os.environ["ANIMATION_CLIPS_DIR"] = str(OTHER)
try:
    n = SCANS[0]
    other = ac.clip_entries()
    check("scanned", SCANS[0] == n + 1, str(SCANS[0] - n))
    check("its own entries", summary(other) == [("", "swim.fbx", "free")],
          str(summary(other)))
finally:
    os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)


# [8]
print("\n[8] the imports reload through reload_clip_caches")
def calls_in(path: Path, func: str) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return {n.func.id for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return set()


check("fbx_import.import_fbx calls reload_clip_caches()",
      "reload_clip_caches" in calls_in(REPO / "app/core/fbx_import.py", "import_fbx"))
check("clip_catalog.import_take calls reload_clip_caches()",
      "reload_clip_caches" in calls_in(REPO / "app/core/clip_catalog.py", "import_take"))

# [9]
print("\n[9] partner_poses asks pair_kinds once")
PAIRS = [0]
_real_pairs = ac.pair_kinds


def _counting_pairs():
    PAIRS[0] += 1
    return _real_pairs()


ac.pair_kinds = _counting_pairs
try:
    ie.partner_poses()
finally:
    ac.pair_kinds = _real_pairs
check("pair_kinds() called exactly once", PAIRS[0] == 1, str(PAIRS[0]))

Path.iterdir = _real_iterdir
ac._scan_entries = _real_scan

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
