#!/usr/bin/env python3
"""Smoke: wrong improvement steps are recognised and dropped by the server itself,
with exactly the files that belong only to them.

Usage:  ./.venv/bin/python scripts/smoke_improvement_invalid_steps.py

Runs without the server, on a temp storage (``paths.init`` before any world-DB
import). The roster and the GC's producibility verdict are fixed by hand; the
artefact graph (scan, judge, delete with its locks and containment), the store
and the engine run for real.

FIXTURE (all signatures 12 hex, the outfit-signature shape)
  Ann — humanoid, ON the base-body pipeline.
    A1 = "a1a1a1a1a1a1": tpose_A1.png (100 B) + tpose_A1.json — PRODUCIBLE (the
         GC keeps it: the Figure Build reads it as a dressed view).
    A2 = "a2a2a2a2a2a2": tpose_A2.png (200 B), tpose_A2.json, tpose_back_A2.png
         (300 B), pose_A2.png (50 B) — NOT producible (nothing reaches it).
  Rex — animal, OFF the pipeline. R1 = "b1b1b1b1b1b1": tpose_R1.png (70 B).
  Out — humanoid on the pipeline whose character folder is a symlink OUT of the
        storage. O1 = "c1c1c1c1c1c1": tpose_O1.png outside the world.
  The .json sidecars are written as "{}" (2 B each).
  Ann, Out (template "human-roleplay") and Rex ("animal-default") are real
  character rows: ``invalid_reason`` reads profile, config and template strictly
  before the (fixed) pipeline verdict.

  Standing entry E (mesh_from_tpose, backend "hy"), steps as the OLD rule
  stored them: Ann:A1:t1, Ann:A2:t2, Out:O1:t3, Rex:R1:t4 pending; Ann:A0:t0
  done (history); Ann:A4:t5 running (its worker owns it).

EXPECTATIONS, derived by hand from the rules
[1] The old rule (pinned to main 9af31aef7, before this fix) lists every
    T-pose render without a mesh — Ann's A1 + A2, Out's O1 and Rex's R1:
    4 candidates. The new rule skips every character on the pipeline: only
    Rex's R1 is a candidate.
[2] invalid_reason: Ann:A1 and Ann:A2 and Out:O1 → "Humanoids get their outfit
    models from the Figure Build"; Rex:R1 → "" (valid); a state fork
    "Rex:b1b1b1b1b1b1-s0f0f0f0f" → "Not an outfit combination".
[3] The dry run ("Remove invalid" preview, explicit) judges pending/skipped/
    failed steps only: 3 wrong steps (A1, A2, O1; A0 is done, A4 running).
    Files that belong ONLY to them: A2's four (200 + 2 + 300 + 50 = 552 B).
    Kept: Ann:A1 ("still reached") and Out:O1 ("outside the world").
    Nothing changed: still 6 steps, all files there.
[4] The real pass: 3 removed, 4 files / 552 B deleted. Left steps: A0 done, A4
    running, R1 pending. A1's two files, Rex's render and Out's outside file
    still exist; A2's four are gone.
[5] A rescan after that adds 0 and closes 0 (R1 is listed and pending).
[6] Before the run: a one_shot F with the single step Ann:A1:t9 — run_now(F)
    drops it instead of starting it: reason "empty", and F, worked off with
    no skip and no failure, is gone. A step marked running whose rule changed
    while it waited (Ann:A1:t8 in E) — handle_step answers
    {"skipped": "invalid: <reason>"} and the row is gone; apply never ran.
[7] An entry whose type cannot judge (invalid_reason raises) is left as it
    is: reported with the error, its step still pending.
[8] invalid_reason cannot judge → it RAISES, never "humanoid": Ann's
    profile_json made unreadable ("[" is no JSON) → raises (a JSONDecodeError,
    a ValueError); Ann's template set to "no-such-template" → raises
    LookupError. remove_invalid over a one_shot H with the step Ann:A1:t6 then
    reports an error and keeps the step pending. A character that is not in the
    roster ("Gone:<A1>:t1") → "" (not this rule's to judge). Ann restored →
    FIGURE_BUILD again.
"""
import os
import sys
import tempfile
import types
import subprocess
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]

STORAGE = Path(tempfile.mkdtemp(prefix="improvement-invalid-"))
OUTSIDE = Path(tempfile.mkdtemp(prefix="improvement-invalid-outside-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvement-invalid-clips-")

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

get_task_queue()._started = True     # no worker threads: rows are inspected only

OLD_MAIN = "9af31aef7"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


A0, A1, A2, A4 = "a0a0a0a0a0a0", "a1a1a1a1a1a1", "a2a2a2a2a2a2", "a4a4a4a4a4a4"
R1, O1 = "b1b1b1b1b1b1", "c1c1c1c1c1c1"
CHARS = STORAGE / "characters"
ON_PIPELINE = {"Ann": True, "Out": True, "Rex": False}
PRODUCIBLE = {A1, R1}


def write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{}" if path.suffix == ".json" else b"x" * size)
    return path


ANN = CHARS / "Ann" / "model_refs"
A1_FILES = [write(ANN / f"tpose_{A1}.png", 100), write(ANN / f"tpose_{A1}.json", 2)]
A2_FILES = [write(ANN / f"tpose_{A2}.png", 200), write(ANN / f"tpose_{A2}.json", 2),
            write(ANN / f"tpose_back_{A2}.png", 300), write(ANN / f"pose_{A2}.png", 50)]
REX_FILE = write(CHARS / "Rex" / "model_refs" / f"tpose_{R1}.png", 70)
OUT_FILE = write(OUTSIDE / "model_refs" / f"tpose_{O1}.png", 40)
(CHARS / "Out").symlink_to(OUTSIDE, target_is_directory=True)

from app.models.character import save_character_profile  # noqa: E402
for _name, _template in (("Ann", "human-roleplay"), ("Out", "human-roleplay"), ("Rex", "animal-default")):
    assert save_character_profile(_name, {"character_name": _name, "template": _template}, create_new=True)


def load_old_type():
    """The mesh_from_tpose module as it stood on main before this fix."""
    source = subprocess.run(["git", "show", f"{OLD_MAIN}:app/core/improvements/types/mesh_from_tpose.py"],
                            cwd=REPO, check=True, capture_output=True, text=True).stdout
    module = types.ModuleType("old_mesh_from_tpose")
    exec(compile(source, "old_mesh_from_tpose.py", "exec"), module.__dict__)
    return module.MeshFromTpose()


def keys(candidates):
    return sorted(c.key.rsplit(":", 1)[0] for c in candidates)


def exists(paths_):
    return [p.exists() for p in paths_]


patches = [
    patch.object(subjects, "characters", lambda: sorted(ON_PIPELINE)),
    patch.object(base_body, "is_base_pipeline", lambda name, profile=None: ON_PIPELINE.get(name, True)),
    patch.object(artefact_graph, "_outfit_valid", lambda name, node, roots: node.key in PRODUCIBLE),
    patch.object(outfit_cache_gc, "_worn_signature", lambda name: ""),
]
for p in patches:
    p.start()

TYPE = registry.get("mesh_from_tpose")
PARAMS = {"backend": "hy"}
FIG = mesh_from_tpose.FIGURE_BUILD

print("[1] the creation rule")
check("old rule (main 9af31aef7) lists every render without a mesh",
      keys(load_old_type().find_candidates(PARAMS)), [f"Ann:{A1}", f"Ann:{A2}", f"Out:{O1}", f"Rex:{R1}"])
check("new rule lists only the character off the pipeline", keys(TYPE.find_candidates(PARAMS)), [f"Rex:{R1}"])

print("[2] invalid_reason")
check("pipeline steps are wrong, the animal's is valid, a fork is no combination",
      [TYPE.invalid_reason(k, PARAMS) for k in
       (f"Ann:{A1}:t1", f"Ann:{A2}:t2", f"Out:{O1}:t3", f"Rex:{R1}:t4", f"Rex:{R1}-s0f0f0f0f")],
      [FIG, FIG, FIG, "", mesh_from_tpose.NOT_A_COMBINATION])

E = store.create(TYPE.id, "UniForge", PARAMS, "standing")["id"]
store.replace_steps_scan(E, [(f"Ann:{A1}:t1", "Ann · a1", 0, ""), (f"Ann:{A2}:t2", "Ann · a2", 0, ""),
                             (f"Out:{O1}:t3", "Out · c1", 0, ""), (f"Rex:{R1}:t4", "Rex · b1", 0, ""),
                             (f"Ann:{A0}:t0", "Ann · a0", 0, ""), (f"Ann:{A4}:t5", "Ann · a4", 0, "")])
store.mark_running(E, f"Ann:{A0}:t0")
store.mark_result(E, f"Ann:{A0}:t0", status="done", count_attempt=False)
store.mark_running(E, f"Ann:{A4}:t5")


def steps():
    return sorted((s["candidate_key"], s["status"]) for s in store.list_steps(E))


print("[3] the dry run")
dry = engine.remove_invalid(explicit=True, dry_run=True)
entry = dry["entries"][0]
check("3 wrong steps, A2's 4 files / 552 B", (dry["removed"], dry["files"], dry["bytes"]), (3, 4, 552))
check("…the wrong ones by key", sorted(s["key"] for s in entry["steps"]),
      [f"Ann:{A1}:t1", f"Ann:{A2}:t2", f"Out:{O1}:t3"])
check("…kept: A1 still reached, Out outside the world", sorted((k["key"], k["why"]) for k in entry["kept"]),
      [(f"Ann:{A1}", "still reached"), (f"Out:{O1}", "outside the world")])
check("…nothing changed", (len(steps()), exists(A1_FILES + A2_FILES + [REX_FILE, OUT_FILE])),
      (6, [True] * 8))

print("[4] the real pass")
real = engine.remove_invalid(explicit=True)
check("3 removed, 4 files / 552 B deleted", (real["removed"], real["files"], real["bytes"]), (3, 4, 552))
check("left: A0 done, A4 running, R1 pending", steps(),
      [(f"Ann:{A0}:t0", "done"), (f"Ann:{A4}:t5", "running"), (f"Rex:{R1}:t4", "pending")])
check("A1, Rex and Out keep their files", exists(A1_FILES + [REX_FILE, OUT_FILE]), [True] * 4)
check("A2's four files are gone", exists(A2_FILES), [False] * 4)

print("[5] the rescan")
with patch.object(mesh_from_tpose, "tpose_token", lambda name, sig: "t4"):
    check("adds 0, closes 0", engine.scan(E), {"added": 0, "closed": 0})

print("[6] before the run")
F = store.create(TYPE.id, "Once", PARAMS, "one_shot")["id"]
store.replace_steps_scan(F, [(f"Ann:{A1}:t9", "Ann · a1", 0, "")])
check("run_now drops the wrong step instead of starting it", engine.run_now(F)["reason"], "empty")
check("…and the worked-off one_shot is gone", store.get(F), None)
store.replace_steps_scan(E, [(f"Ann:{A1}:t8", "Ann · a1", 0, ""), (f"Rex:{R1}:t4", "Rex · b1", 0, "")])
store.mark_running(E, f"Ann:{A1}:t8")
with patch.object(TYPE, "apply", lambda *a, **k: FAILS.append("apply ran")):
    check("handle_step drops a step whose rule changed while it waited",
          engine.handle_step({"improvement_id": E, "candidate_key": f"Ann:{A1}:t8"}), {"skipped": f"invalid: {FIG}"})
check("…its row is gone", any(k == f"Ann:{A1}:t8" for k, _s in steps()), False)

print("[7] an entry the type cannot judge")
G = store.create(TYPE.id, "Unjudged", PARAMS, "one_shot")["id"]
store.replace_steps_scan(G, [(f"Ann:{A1}:t7", "Ann · a1", 0, "")])


def broken(key, params):
    raise RuntimeError("roster unreadable")


with patch.object(TYPE, "invalid_reason", broken):
    report = engine.remove_invalid(G)
check("reported with the error, nothing removed", (report["removed"], report["entries"][0]["error"]),
      (0, "roster unreadable"))
check("…its step still pending", [s["status"] for s in store.list_steps(G)], ["pending"])
store.delete(G)

print("[8] invalid_reason raises when it cannot judge")
conn = db.get_connection()
ANN_ROW = conn.execute("SELECT profile_json, template FROM characters WHERE name='Ann'").fetchone()


def ann_row(profile_json, template):
    with db.transaction() as c:
        c.execute("UPDATE characters SET profile_json=?, template=? WHERE name='Ann'", (profile_json, template))


def raised(key):
    try:
        return ("returned", TYPE.invalid_reason(key, PARAMS))
    except Exception as e:  # noqa: BLE001 — the class is what is checked
        return ("raised", isinstance(e, (ValueError, LookupError)))


ann_row("[", ANN_ROW[1])
check("unreadable profile → raises", raised(f"Ann:{A1}:t6"), ("raised", True))
H = store.create(TYPE.id, "Unreadable", PARAMS, "one_shot")["id"]
store.replace_steps_scan(H, [(f"Ann:{A1}:t6", "Ann · a1", 0, "")])
report = engine.remove_invalid(H)
check("…remove_invalid reports an error, removes nothing",
      (report["removed"], bool(report["entries"] and report["entries"][0]["error"])), (0, True))
check("…its step still pending", [s["status"] for s in store.list_steps(H)], ["pending"])
store.delete(H)
ann_row('{"character_name": "Ann", "template": "no-such-template"}', "no-such-template")
check("unknown template → raises", raised(f"Ann:{A1}:t6"), ("raised", True))
check("a character not in the roster → ''", raised(f"Gone:{A1}:t1"), ("returned", ""))
ann_row(ANN_ROW[0], ANN_ROW[1])
check("Ann restored → Figure Build again", raised(f"Ann:{A1}:t6"), ("returned", FIG))

for p in patches:
    p.stop()
print("\nOK" if not FAILS else f"\nFAILED: {', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
