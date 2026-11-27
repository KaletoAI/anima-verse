#!/usr/bin/env python3
"""Smoke: a world freeze or a task-queue pause holds the AUTOMATIC deleting of a
NOT forced improvement entry — its validity pass waits and its standing rescan
only adds, so no wrong step and no file of it goes until the hold ends — while
a FORCED (Run now) entry keeps its rescans and validity passes; a read of the
entry list changes nothing.

Usage:  ./.venv/bin/python scripts/smoke_improvement_invalid_frozen.py

Runs without the server, on a temp storage (``paths.init`` before any world-DB
import). The freeze flag (``set_world_frozen``) and the queue pause
(``pause_queue``) are set for real; the roster, the pipeline verdict, the GC's
producibility verdict and the T-pose tokens are fixed by hand; the characters
are real rows (``invalid_reason`` reads them strictly); the artefact graph, the
store and the engine run for real, except ``engine._submit``, which only
records the row it was handed (no task is queued). No old-code proof: the held
pass never reached main.

FIXTURE (signatures 12 hex, the outfit-signature shape)
  Ann — humanoid ON the base-body pipeline. A2 = "a2a2a2a2a2a2":
    tpose_A2.png (200 B), tpose_A2.json ("{}", 2 B), tpose_back_A2.png (300 B),
    pose_A2.png (50 B) — NOT producible.
  Bea — humanoid ON the pipeline. B2 = "d2d2d2d2d2d2": tpose_B2.png (120 B),
    tpose_back_B2.png (30 B) — NOT producible.
  Rex — animal OFF the pipeline. R1 = "b1b1b1b1b1b1": tpose_R1.png (70 B), token t4.
  Cid — animal OFF the pipeline. C1 = "c1c1c1c1c1c1": tpose_C1.png (60 B), token
    t9 — a render no entry has a step for yet: a scan ADDS Cid:C1:t9.
  Every file is stamped one hour old, past the automatic sweep's 10-minute
  grace window (``artefact_graph.GRACE_S``), so only the hold can keep them.
  Standing entry E (not forced), never scanned: Ann:A2:t2 + Rex:R1:t4 pending.
  Standing entry F, forced by request_run_now, never scanned: Bea:B2:t2 +
  Rex:R1:t4 pending. The media switch reads as on.

EXPECTATIONS, derived by hand from the rules
  The rule (``mesh_from_tpose.invalid_reason``) makes Ann:A2 and Bea:B2 wrong,
  Rex:R1 valid. A scan lists only the characters off the pipeline: Rex:R1:t4
  and Cid:C1:t9 (labels "Cid · c1c1c1c1" < "Rex · b1b1b1b1").
[1] Frozen: validate_due_entries → held "frozen"; only F is judged: removed 1
    (Bea:B2), files 2, bytes 120 + 30 = 150. E keeps both steps, A2's four
    files are there; Bea's two are gone.
[2] Frozen: tick → scanned 2. E rescans ADD-ONLY: Cid:C1:t9 added, Ann:A2:t2
    neither deleted nor closed (still pending), Rex:R1:t4 pending;
    last_scan_at stays None. F rescans in full (its validity pass first:
    nothing wrong left), Cid:C1:t9 added, closed 0; last_scan_at is set.
    Step 4: the freeze is a RUN_NOW_OVERRIDES gate, so F's first step in label
    order is judged and handed over: (F, "Cid:C1:t9"). A2's four files are
    there. status()["validity_held"] = "frozen".
[3] Frozen, second tick: scanned 0 — E's add-only scan is paced by the
    interval, F's full scan by last_scan_at.
[4] Thawed, "default" queue paused: validate_due_entries → held "paused",
    removed 0; E unchanged (3 pending steps), A2's files there.
[5] Neither: GET /improvements (``list_improvements``) only reads → E still 3
    steps, A2's files there; status()["validity_held"] = "".
[6] Neither: validate_due_entries → removed 1 (Ann:A2), files 4, bytes
    200 + 2 + 300 + 50 = 552; F is not due (judged in [1]). E left: Cid:C1:t9 +
    Rex:R1:t4 pending.
[7] Neither: tick → scanned 1 — E's full rescan is due at once (last_scan_at
    still None), F's is not. It adds 0 and closes 0 (both listed and pending);
    last_scan_at is set now. Rex's and Cid's renders are still there.
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
from app.core.improvements.types import mesh_from_tpose, subjects  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.world import set_world_frozen  # noqa: E402
from app.routes import improvements as improvements_route  # noqa: E402

get_task_queue()._started = True     # no worker threads: rows are inspected only

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


A2, B2, R1, C1 = "a2a2a2a2a2a2", "d2d2d2d2d2d2", "b1b1b1b1b1b1", "c1c1c1c1c1c1"
CHARS = STORAGE / "characters"
ON_PIPELINE = {"Ann": True, "Bea": True, "Cid": False, "Rex": False}
TEMPLATES = {"Ann": "human-roleplay", "Bea": "human-roleplay", "Cid": "animal-default", "Rex": "animal-default"}
PRODUCIBLE = {R1, C1}
TOKENS = {R1: "t4", C1: "t9"}
HOUR_AGO = time.time() - 3600

for _name, _template in sorted(TEMPLATES.items()):
    assert save_character_profile(_name, {"character_name": _name, "template": _template}, create_new=True)


def write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{}" if path.suffix == ".json" else b"x" * size)
    os.utime(path, (HOUR_AGO, HOUR_AGO))
    return path


ANN = CHARS / "Ann" / "model_refs"
A2_FILES = [write(ANN / f"tpose_{A2}.png", 200), write(ANN / f"tpose_{A2}.json", 2),
            write(ANN / f"tpose_back_{A2}.png", 300), write(ANN / f"pose_{A2}.png", 50)]
BEA = CHARS / "Bea" / "model_refs"
B2_FILES = [write(BEA / f"tpose_{B2}.png", 120), write(BEA / f"tpose_back_{B2}.png", 30)]
ANIMAL_FILES = [write(CHARS / "Rex" / "model_refs" / f"tpose_{R1}.png", 70),
                write(CHARS / "Cid" / "model_refs" / f"tpose_{C1}.png", 60)]

SUBMITTED = []
patches = [
    patch.object(subjects, "characters", lambda: sorted(ON_PIPELINE)),
    patch.object(base_body, "is_base_pipeline", lambda name, profile=None: ON_PIPELINE.get(name, True)),
    patch.object(artefact_graph, "_outfit_valid", lambda name, node, roots: node.key in PRODUCIBLE),
    patch.object(outfit_cache_gc, "_worn_signature", lambda name: ""),
    patch.object(mesh_from_tpose, "tpose_token", lambda name, signature: TOKENS[signature]),
    patch.object(engine, "media_generation_enabled", lambda: True),
    patch.object(engine, "_submit",
                 lambda row: SUBMITTED.append((row["improvement_id"], row["candidate_key"])) or "task-1"),
]
for p in patches:
    p.start()

TYPE = registry.get("mesh_from_tpose")
E = store.create(TYPE.id, "Held", {"backend": "hy"}, "standing")["id"]
store.replace_steps_scan(E, [(f"Ann:{A2}:t2", "Ann · a2", 0, ""), (f"Rex:{R1}:t4", "Rex · b1", 0, "")])
F = store.create(TYPE.id, "Forced", {"backend": "hy"}, "standing")["id"]
store.replace_steps_scan(F, [(f"Bea:{B2}:t2", "Bea · d2", 0, ""), (f"Rex:{R1}:t4", "Rex · b1", 0, "")])
engine.request_run_now(F)


def steps(entry):
    return sorted((s["candidate_key"], s["status"]) for s in store.list_steps(entry))


def exists(files):
    return [p.exists() for p in files]


def validity():
    result = engine.validate_due_entries()
    return (result["removed"], result["files"], result["bytes"], result["held"])


E_START = [(f"Ann:{A2}:t2", "pending"), (f"Rex:{R1}:t4", "pending")]
E_ADDED = [(f"Ann:{A2}:t2", "pending"), (f"Cid:{C1}:t9", "pending"), (f"Rex:{R1}:t4", "pending")]
LISTED = [(f"Cid:{C1}:t9", "pending"), (f"Rex:{R1}:t4", "pending")]

print("[1] frozen: the validity pass")
set_world_frozen(True)
check("only the forced entry is judged: 1 removed, 2 files / 150 B", validity(), (1, 2, 150, "frozen"))
check("…E keeps both steps", steps(E), E_START)
check("…F lost Bea's step", steps(F), [(f"Rex:{R1}:t4", "pending")])
check("…A2's four files there, Bea's two gone", (exists(A2_FILES), exists(B2_FILES)), ([True] * 4, [False] * 2))

print("[2] frozen: the tick")
result = engine.tick()
check("both standing entries rescan", result["scanned"], 2)
check("…E only added: Cid new, Ann's wrong step still pending", steps(E), E_ADDED)
check("…E's last_scan_at stays None", store.get(E)["last_scan_at"], None)
check("…F rescanned in full: Cid added", steps(F), LISTED)
check("…F's last_scan_at is set", bool(store.get(F)["last_scan_at"]), True)
check("…the forced step went past the freeze", SUBMITTED, [(F, f"Cid:{C1}:t9")])
check("…A2's four files there", exists(A2_FILES), [True] * 4)
check("status says why", engine.status()["validity_held"], "frozen")

print("[3] frozen: the next tick")
check("nothing rescans within the interval", engine.tick()["scanned"], 0)
check("…E unchanged", steps(E), E_ADDED)

print("[4] thawed, task queue paused")
set_world_frozen(False)
get_task_queue().pause_queue("default")
check("holds: 0 removed, held 'paused'", validity(), (0, 0, 0, "paused"))
check("…E unchanged, A2's files there", (steps(E), exists(A2_FILES)), (E_ADDED, [True] * 4))
get_task_queue().resume_queue("default")

print("[5] GET /improvements only reads")
listed = improvements_route.list_improvements()
check("lists both entries", sorted(i["id"] for i in listed), sorted([E, F]))
check("…E unchanged, A2's files there", (steps(E), exists(A2_FILES)), (E_ADDED, [True] * 4))
check("status: nothing held", engine.status()["validity_held"], "")

print("[6] neither: the validity pass")
check("1 removed, 4 files / 552 B", validity(), (1, 4, 552, ""))
check("…E left: Cid and Rex pending", steps(E), LISTED)
check("…A2's four files gone", exists(A2_FILES), [False] * 4)

print("[7] neither: the tick")
check("E's full rescan is due at once, F's is not", engine.tick()["scanned"], 1)
check("…it added and closed nothing", steps(E), LISTED)
check("…E's last_scan_at is set now", bool(store.get(E)["last_scan_at"]), True)
check("…the animals' renders are there", exists(ANIMAL_FILES), [True] * 2)

for p in patches:
    p.stop()
print("\nOK" if not FAILS else f"\nFAILED: {', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
