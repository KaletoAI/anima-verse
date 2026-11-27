#!/usr/bin/env python3
"""Smoke: a world freeze or a task-queue pause holds the AUTOMATIC validity pass
of the improvements engine — no wrong step and no file goes until it ends; a
read of the entry list changes nothing.

Usage:  ./.venv/bin/python scripts/smoke_improvement_invalid_frozen.py

Runs without the server, on a temp storage (``paths.init`` before any world-DB
import). The freeze flag (``set_world_frozen``) and the queue pause
(``pause_queue``) are set for real; the roster and the GC's producibility
verdict are fixed by hand; the artefact graph, the store and the engine run for
real. No old-code proof: the unheld pass never reached main.

FIXTURE (signatures 12 hex, the outfit-signature shape)
  Ann — humanoid ON the base-body pipeline. A2 = "a2a2a2a2a2a2":
    tpose_A2.png (200 B), tpose_A2.json ("{}", 2 B), tpose_back_A2.png (300 B),
    pose_A2.png (50 B) — NOT producible (nothing reaches it). Every file is
    stamped one hour old, past the automatic sweep's 10-minute grace window
    (``artefact_graph.GRACE_S``), so the only thing that can keep them is the hold.
  Rex — animal OFF the pipeline. R1 = "b1b1b1b1b1b1": tpose_R1.png (70 B).
  Standing entry E (mesh_from_tpose, backend "hy", never scanned, so a scan is
  due): Ann:A2:t2 and Rex:R1:t4 pending.

EXPECTATIONS, derived by hand from the rules
  The rule (``mesh_from_tpose.invalid_reason``) makes Ann:A2 wrong (Ann is on
  the pipeline) and Rex:R1 valid. Unheld, the automatic pass drops 1 step and
  A2's four files: 200 + 2 + 300 + 50 = 552 B.
[1] Frozen: validate_due_entries → removed 0, files 0, bytes 0, held "frozen";
    still 2 pending steps, all 5 files there.
[2] Frozen: tick → scanned 0 (the due rescan is held, last_scan_at stays None),
    still 2 steps, all 5 files; status()["validity_held"] = "frozen".
[3] Thawed but the "default" queue paused: validate_due_entries → held
    "paused", 0 removed; tick scans 0; still 2 steps, 5 files.
[4] Neither: GET /improvements (``list_improvements``) only reads → still 2
    steps, 5 files; status()["validity_held"] = "".
[5] Neither: validate_due_entries → removed 1, files 4, bytes 552, held "";
    left: Rex:R1:t4 pending; A2's four files gone, Rex's render there. The held
    passes stamped nothing, so the entry was due right away.
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvement-frozen-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvement-frozen-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import artefact_graph, base_body, outfit_cache_gc  # noqa: E402
from app.core.improvements import engine, registry, store  # noqa: E402
import app.core.improvements.types  # noqa: E402,F401  (registers the types)
from app.core.improvements.types import subjects  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.world import set_world_frozen  # noqa: E402
from app.routes import improvements as improvements_route  # noqa: E402

get_task_queue()._started = True     # no worker threads: rows are inspected only

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


A2, R1 = "a2a2a2a2a2a2", "b1b1b1b1b1b1"
CHARS = STORAGE / "characters"
ON_PIPELINE = {"Ann": True, "Rex": False}
PRODUCIBLE = {R1}
HOUR_AGO = time.time() - 3600


def write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{}" if path.suffix == ".json" else b"x" * size)
    os.utime(path, (HOUR_AGO, HOUR_AGO))
    return path


ANN = CHARS / "Ann" / "model_refs"
A2_FILES = [write(ANN / f"tpose_{A2}.png", 200), write(ANN / f"tpose_{A2}.json", 2),
            write(ANN / f"tpose_back_{A2}.png", 300), write(ANN / f"pose_{A2}.png", 50)]
REX_FILE = write(CHARS / "Rex" / "model_refs" / f"tpose_{R1}.png", 70)
ALL_FILES = A2_FILES + [REX_FILE]

patches = [
    patch.object(subjects, "characters", lambda: sorted(ON_PIPELINE)),
    patch.object(base_body, "is_base_pipeline", lambda name, profile=None: ON_PIPELINE.get(name, True)),
    patch.object(artefact_graph, "_outfit_valid", lambda name, node, roots: node.key in PRODUCIBLE),
    patch.object(outfit_cache_gc, "_worn_signature", lambda name: ""),
]
for p in patches:
    p.start()

TYPE = registry.get("mesh_from_tpose")
E = store.create(TYPE.id, "UniForge", {"backend": "hy"}, "standing")["id"]
store.replace_steps_scan(E, [(f"Ann:{A2}:t2", "Ann · a2", 0, ""), (f"Rex:{R1}:t4", "Rex · b1", 0, "")])


def steps():
    return sorted((s["candidate_key"], s["status"]) for s in store.list_steps(E))


BOTH = [(f"Ann:{A2}:t2", "pending"), (f"Rex:{R1}:t4", "pending")]


def exists():
    return [p.exists() for p in ALL_FILES]


def held_pass():
    result = engine.validate_due_entries()
    return (result["removed"], result["files"], result["bytes"], result["held"])


print("[1] frozen: the validity pass")
set_world_frozen(True)
check("holds: 0 removed, held 'frozen'", held_pass(), (0, 0, 0, "frozen"))
check("…both steps and all 5 files there", (steps(), exists()), (BOTH, [True] * 5))

print("[2] frozen: the tick")
check("the due rescan is held", engine.tick()["scanned"], 0)
check("…never scanned", store.get(E)["last_scan_at"], None)
check("…both steps and all 5 files there", (steps(), exists()), (BOTH, [True] * 5))
check("status says why", engine.status()["validity_held"], "frozen")

print("[3] thawed, task queue paused")
set_world_frozen(False)
get_task_queue().pause_queue("default")
check("holds: 0 removed, held 'paused'", held_pass(), (0, 0, 0, "paused"))
check("the tick scans nothing", engine.tick()["scanned"], 0)
check("…both steps and all 5 files there", (steps(), exists()), (BOTH, [True] * 5))
get_task_queue().resume_queue("default")

print("[4] GET /improvements only reads")
listed = improvements_route.list_improvements()
check("lists the entry", [i["id"] for i in listed], [E])
check("…both steps and all 5 files there", (steps(), exists()), (BOTH, [True] * 5))
check("status: nothing held", engine.status()["validity_held"], "")

print("[5] neither: the pass runs")
check("1 removed, 4 files / 552 B, held ''", held_pass(), (1, 4, 552, ""))
check("left: Rex:R1 pending", steps(), [(f"Rex:{R1}:t4", "pending")])
check("A2's four files gone, Rex's render there", exists(), [False] * 4 + [True])

for p in patches:
    p.stop()
print("\nOK" if not FAILS else f"\nFAILED: {', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
