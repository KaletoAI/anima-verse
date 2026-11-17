"""Smoke: A194 — the ONE live-progress mechanism of CPU jobs (``app/core/cpu_progress.py``).

Usage:
    ./.venv/bin/python scripts/smoke_cpu_progress.py

No server, no world, no Blender: the registry is driven by hand, the Blender side by the stdlib-only
``app/blender/scripts/_common.py``, ``runner.run`` with a stubbed status and subprocess.

Expected, derived by hand from the module:

[1] eta_seconds(i, n, spent) = spent / i * (n - i): (3, 12, 6.0) → 6/3*9 = 18.0; (0, 12, 6) → None (no i);
    (12, 12, 6) → None (done); (3, 12, 1.5) → None (under 2 s of data).
[2] format_line([Garment fit], [Cloth substeps 96/400], elapsed 42.4, eta 30.2)
    = "Garment fit · Cloth substeps 96/400 · 42 s · ~30 s left"; without parts' i/n and eta: "Working · 7 s".
[3] scope("t:a"): snapshot → parts [Working] (nothing reported yet). stage("face_cleanup") → parts
    ["Face cleanup"]. sub("drape_substeps", 96, 400) → parts ["Face cleanup", "Cloth substeps" 96/400]; the line
    starts "Face cleanup · Cloth substeps 96/400 · ". After the block: snapshot None.
[4] Nested scopes both receive a report: scope("t:outer") ⊃ scope("t:inner"), stage("assemble") → both snapshots
    have parts[0] "Assembling the figure". Leaving inner keeps outer open.
[5] attach("blender:lod", f) with f = {stage "levels", i 2, n 3, t0 100, t 106} → parts [Level of detail
    (Blender), Levels 2/3], eta = 6/2*1 = 3.0 → line ends "· ~3 s left". After the block the head is gone and f is
    deleted. An unreadable file → parts [head] only, still a line.
[6] A172's drape record {stage "shapes", index 2, count 4, pose "arms_down", frame 7, frames 12} (with the label
    "Draping the pose shapes" registered for "shapes") → part label "Draping the pose shapes (arms down)", i 2,
    n 4, extra "frame 7/12" → line contains "Draping the pose shapes (arms down) 2/4 · frame 7/12".
[7] A worker's report: run_reporting(f, fn) where fn calls sub("shell_views", 2, 4) → f holds stage "shell_views",
    i 2, n 4; outside the trampoline sub writes no file (child file reset).
[8] relabel: scope("t:r", relabel=cb) + stage("assemble") → cb got "Assembling the figure · 0 s" (the first
    report after the scope opens is not throttled: its last-shown stamp starts at 0). track_relabel(q, id,
    "Build · X") writes "Build · X — <line>" through q.track_update_label.
[9] Never fails a job: sub()/stage() with no scope open do nothing; write_file into a missing folder returns
    None; a relabel callback that raises is swallowed.
[10] Blender side: _common.progress without a file is a no-op; with _PROGRESS["file"] = f, progress("bones", 1, 5)
    writes {stage "bones", i 1, n 5}; a second call in the same stage within 0.25 s (i < n) is throttled
    (file unchanged); a new stage writes at once.
[11] runner.run (status stubbed usable, _spawn stubbed): the args file carries "progress" = <job>/progress.json
    (params without progress_file) or the given params.progress_file; while the subprocess runs, the open scope's
    snapshot head is "Level of detail (Blender)" and reads what the "Blender" wrote into that file (levels 1/2).
[12] refit_pool.run in-process (workers 1) in a scope: inside fn the head is "cpu:<fn name>"; fn's
    sub("shell_views", 1, 2) shows as "Shell views 1/2"; afterwards the head is gone.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import cpu_progress as cp  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def labels(snap):
    return [p["label"] for p in snap["parts"]]


tmp = Path(tempfile.mkdtemp(prefix="smoke-cpu-progress-"))

# [1]
check("[1] eta 3/12 in 6 s = 18", cp.eta_seconds(3, 12, 6.0) == 18.0)
check("[1] eta without i", cp.eta_seconds(0, 12, 6.0) is None)
check("[1] eta when done", cp.eta_seconds(12, 12, 6.0) is None)
check("[1] eta under 2 s", cp.eta_seconds(3, 12, 1.5) is None)

# [2]
line = cp.format_line([{"label": "Garment fit"}, {"label": "Cloth substeps", "i": 96, "n": 400}], 42.4, 30.2)
check("[2] full line", line == "Garment fit · Cloth substeps 96/400 · 42 s · ~30 s left", line)
check("[2] bare line", cp.format_line([{"label": "Working"}], 7.0, None) == "Working · 7 s")

# [3]
with cp.scope("t:a"):
    s = cp.snapshot("t:a")
    check("[3] nothing reported → Working", labels(s) == ["Working"], labels(s))
    cp.stage("face_cleanup")
    check("[3] stage", labels(cp.snapshot("t:a")) == ["Face cleanup"])
    cp.sub("drape_substeps", 96, 400)
    s = cp.snapshot("t:a")
    check("[3] stage + sub", labels(s) == ["Face cleanup", "Cloth substeps"] and s["parts"][1]["i"] == 96
          and s["parts"][1]["n"] == 400, s)
    check("[3] line", s["line"].startswith("Face cleanup · Cloth substeps 96/400 · "), s["line"])
check("[3] closed → None", cp.snapshot("t:a") is None)

# [4]
with cp.scope("t:outer"):
    with cp.scope("t:inner"):
        cp.stage("assemble")
        check("[4] inner", labels(cp.snapshot("t:inner"))[0] == "Assembling the figure")
        check("[4] outer", labels(cp.snapshot("t:outer"))[0] == "Assembling the figure")
    check("[4] inner closed, outer open", cp.snapshot("t:inner") is None and cp.snapshot("t:outer") is not None)

# [5]
f = tmp / "p5.json"
with cp.scope("t:b"):
    with cp.attach("blender:lod", str(f)):
        f.write_text(json.dumps({"stage": "levels", "i": 2, "n": 3, "t0": 100.0, "t": 106.0}))
        s = cp.snapshot("t:b")
        check("[5] head + sub", labels(s) == ["Level of detail (Blender)", "Levels"], labels(s))
        check("[5] eta 3 s", s["eta_s"] == 3.0 and s["line"].endswith("· ~3 s left"), s["line"])
        f.write_text("{not json")
        s = cp.snapshot("t:b")
        check("[5] unreadable file → head only", labels(s) == ["Level of detail (Blender)"] and s["line"], labels(s))
    s = cp.snapshot("t:b")
    check("[5] head gone after", s["head"] is None and labels(s) == ["Working"], s)
    check("[5] file deleted", not f.exists())

# [6]
cp.register_labels({"shapes": "Draping the pose shapes"})
f6 = tmp / "p6.json"
with cp.scope("t:c"):
    with cp.attach("blender:garment_template_build", str(f6)):
        f6.write_text(json.dumps({"stage": "shapes", "index": 2, "count": 4, "pose": "arms_down",
                                  "frame": 7, "frames": 12}))
        s = cp.snapshot("t:c")
        p = s["parts"][-1]
        check("[6] A172 record", p["label"] == "Draping the pose shapes (arms down)" and p["i"] == 2
              and p["n"] == 4 and p["extra"] == "frame 7/12", p)
        check("[6] line", "Draping the pose shapes (arms down) 2/4 · frame 7/12" in s["line"], s["line"])

# [7]
f7 = tmp / "p7.json"


def _worker_fn():
    cp.sub("shell_views", 2, 4)
    return 1


cp.run_reporting(str(f7), _worker_fn)
rec = json.loads(f7.read_text())
check("[7] worker file", rec["stage"] == "shell_views" and rec["i"] == 2 and rec["n"] == 4, rec)
f7.unlink()
cp.sub("shell_views", 3, 4)
check("[7] child file reset", not f7.exists())

# [8]
got = []
with cp.scope("t:r", relabel=got.append):
    cp.stage("assemble")
check("[8] relabel", got and got[0] == "Assembling the figure · 0 s", got)


class _Q:
    def __init__(self):
        self.rows = {}

    def track_update_label(self, tid, label):
        self.rows[tid] = label


q = _Q()
cp.track_relabel(q, "t1", "Build · X")("Shell views 1/2 · 3 s")
check("[8] track row", q.rows == {"t1": "Build · X — Shell views 1/2 · 3 s"}, q.rows)
check("[8] no row → None", cp.track_relabel(None, "", "x") is None)

# [9]
cp.sub("drape_substeps", 1, 2)
cp.stage("assemble")
check("[9] no scope: nothing", cp.snapshot("t:none") is None)
check("[9] write_file to a missing folder", cp.write_file(str(tmp / "no" / "such" / "p.json"), "x") is None)


def _boom(_line):
    raise RuntimeError("row gone")


with cp.scope("t:boom", relabel=_boom):
    cp.stage("assemble")
check("[9] raising relabel swallowed", True)

# [10]
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import _common  # noqa: E402
sys.path.pop(0)
_common._PROGRESS["file"] = None
_common.progress("bones", 1, 5)
f10 = tmp / "p10.json"
_common._PROGRESS.update(file=str(f10), stage=None, t0=None, last=0.0)
_common.progress("bones", 1, 5)
r1 = json.loads(f10.read_text())
check("[10] written", r1["stage"] == "bones" and r1["i"] == 1 and r1["n"] == 5, r1)
_common.progress("bones", 2, 5)
check("[10] throttled", json.loads(f10.read_text())["i"] == 1)
_common.progress("exporting")
check("[10] new stage at once", json.loads(f10.read_text())["stage"] == "exporting")
_common._PROGRESS["file"] = None

# [11]
from app.blender import runner  # noqa: E402
seen = {}


def _fake_spawn(cmd, timeout, env):
    args = json.loads(Path(cmd[-1]).read_text())
    seen.setdefault("progress", []).append(args.get("progress"))
    Path(args["progress"]).write_text(json.dumps({"stage": "levels", "i": 1, "n": 2, "t0": 1.0, "t": 1.5}))
    seen.setdefault("snap", []).append(cp.snapshot("t:run"))
    Path(args["result"]).write_text(json.dumps({"ok": True, "data": {}, "outputs": {}}))

    class _P:
        returncode, stdout, stderr = 0, "", ""
    return _P()


runner.status = lambda: {"enabled": True, "executable": "/bin/true", "error": ""}
runner._spawn = _fake_spawn
runner.slot_dir = lambda: tmp / "slots"
given = str(tmp / "given.json")
with cp.scope("t:run"):
    r = runner.run("lod", params={})
    r2 = runner.run("lod", params={"progress_file": given})
check("[11] runs ok", r["ok"] and r2["ok"], (r, r2))
check("[11] progress in job dir", seen["progress"][0].endswith("/progress.json") and "av-blender-" in seen["progress"][0],
      seen["progress"])
check("[11] given progress_file kept", seen["progress"][1] == given)
s = seen["snap"][0]
check("[11] live during the run", s and labels(s) == ["Level of detail (Blender)", "Levels"]
      and s["parts"][1]["i"] == 1, s)

# [12]
from app.core import refit_pool  # noqa: E402
refit_pool.workers = lambda: 1
inside = {}


def build_shell_stub():
    inside["head"] = cp.snapshot("t:pool")["head"]
    cp.sub("shell_views", 1, 2)
    inside["labels"] = labels(cp.snapshot("t:pool"))
    return 7


with cp.scope("t:pool"):
    out = refit_pool.run(build_shell_stub)
    after = cp.snapshot("t:pool")
check("[12] result", out == 7)
check("[12] head inside", inside["head"] == "cpu:build_shell_stub", inside)
check("[12] sub inside", inside["labels"] == ["Build shell stub", "Shell views"], inside)
check("[12] head gone", after["head"] is None)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all passed")
