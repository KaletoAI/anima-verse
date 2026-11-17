"""A176 — one mesh per Build, and a drape that failed is not shown as running while the Build waits elsewhere.

Usage:
    ./.venv/bin/python scripts/smoke_a176_mesh_once.py

No server, no world DB, no hub: ``paths.init(<tmpdir>)`` first; every mesher / Blender step is a stub that counts.

The live case (Dario, 2026-11-17, logs/main.log): a click "regenerate from empty" (14:10:21) meshed the sandals
twice (attempt 1 refused 14:15:14, iou 0.6273; attempt 2 refused 14:19:26, iou 0.6041 — MESH_ATTEMPTS 2). A Build
clicked at 14:15:29 queued behind it in the character's garment FIFO, and its default run re-ran the refused mesh
step at 14:19:27 — twice again (iou 0.5915, 0.6050; refused 14:27:39). Hub jobs e3bd9bc8, 97792bf3, 2eecfb52,
7b70af2d: four ~4-minute UniForge jobs for one shoe. Meanwhile the shirt's drape had failed at 14:16:16, but its
dialog read "running — The Build runs — the drape starts at its step" until the Build ended at 14:27:40.

Expected, derived by hand:
[1] the attempt caps: ``footwear_source.MESH_ATTEMPTS`` == 1 and ``garment_mesh.MAX_ATTEMPTS`` == 1 (the old code:
    2 and 2 — a gate refusal asked the mesher a second time on its own).
[2] the footwear chain on one item whose source/empty/cutout are done (records accepted, files present):
    a) the explicit mesh run (``wanted=["mesh"]``) calls the mesh step ONCE; the stub refuses by its gates
       -> ``{ok False, step "mesh"}``, mesh calls 1;
    b) a DEFAULT run (``wanted=None`` — what the Build queues) then calls the mesh step 0 more times
       -> ``{ok False, step "mesh"}``, mesh calls still 1, the error names Regenerate (old code: 2 — it re-meshed);
    c) the explicit mesh run again (the user's Regenerate) calls it once more -> mesh calls 2;
    d) a mesh step that failed at the BACKEND (failure "backend", not the gates) is run again by a default run
       -> mesh calls 3 (an outage is no refusal).
[3] ``garment_template.piece_progress`` of a worn template piece whose drape FAILED while a Build of the
    character still runs:
    a) the Build's current step is the shoe's ``pieces`` step, the template step lies BEFORE it (done)
       -> state "failed", drape step status "failed" (old code: "running" — any running Build counted);
    b) the Build's current step is before the template step (still ahead) -> state "running", detail
       ``WAITING_FOR_STEP``.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="a176-")
os.environ["STORAGE_DIR"] = TMP
os.environ["INSTANCE_DIR"] = TMP
from app.core import paths  # noqa: E402
paths.init(TMP)

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(name)


def main() -> int:
    from app.core import footwear_source as fs, garment_footwear as gf, garment_mesh as gm
    from app.core import garment_store as gs

    print("[1] attempt caps")
    check("footwear MESH_ATTEMPTS", fs.MESH_ATTEMPTS, 1)
    check("garment_mesh MAX_ATTEMPTS", gm.MAX_ATTEMPTS, 1)

    print("[2] the footwear chain")
    item = "item_a176_sandals"
    ssig = fs.current_ssig(item)
    d = fs.source_dir(item, ssig)
    d.mkdir(parents=True)
    for step in ("source", "empty", "cutout"):
        for name in fs._STEP_FILES[step]:
            (d / name).write_bytes(b"x")
        fs._set_step(d, step, fs._entry(accepted=True, gates={}))
    calls = {"mesh": 0, "insole": 0}
    mode = {"failure": fs.GATE}

    def mesh(iid, s, seed, dd):
        calls["mesh"] += 1
        fs._set_step(dd, "mesh", fs._entry(accepted=False, gates={"reasons": ["mesh_iou 0.6 < 0.75"]},
                                           failure=mode["failure"]))
        raise fs.StepRefused("shoe mesh refused", {"reasons": ["mesh_iou 0.6 < 0.75"]}, mode["failure"])

    def insole(iid, s, seed, dd):
        calls["insole"] += 1

    fs._RUNNERS["mesh"], fs._RUNNERS["insole"] = mesh, insole
    gf._fsig = lambda c, i, p: "f" * 12
    gs.start = lambda *a, **k: None
    gs.end = lambda *a, **k: None
    import app.models.character as mc
    mc.get_character_profile = lambda name: {}
    shoe = {"id": item}

    res = gf.run_chain("Demo", shoe, ["mesh"], False)
    check("a) explicit mesh run", (res.get("ok"), res.get("step"), calls["mesh"]), (False, "mesh", 1))
    res = gf.run_chain("Demo", shoe, None, False)
    check("b) default run keeps the refusal", (res.get("ok"), res.get("step"), calls["mesh"]), (False, "mesh", 1))
    check("b) error offers Regenerate", "Regenerate" in str(res.get("error")), True)
    res = gf.run_chain("Demo", shoe, ["mesh"], False)
    check("c) the user's Regenerate meshes", calls["mesh"], 2)
    mode["failure"] = fs.BACKEND
    gf.run_chain("Demo", shoe, ["mesh"], False)            # recorded as a backend failure (call 3)
    gf.run_chain("Demo", shoe, None, False)                # a default run retries an outage (call 4)
    check("d) a backend failure is run again", calls["mesh"], 4)

    print("[3] piece_progress while the Build waits on another piece")
    from app.core import base_body, figure, figure_build, garment_template as gt
    import app.models.inventory as inv

    class Sets:
        pieces = {"top": "item_shirt", "feet": item}
        own = [item]
    figure.worn_sets = lambda c, **k: Sets()
    base_body.current_base = lambda c, **k: ("base0", "sha0")
    gt.drape_state = lambda c, i, **k: {"state": "failed", "reason": "Drape failed: stretch_max 1.881 (limit 1.3)",
                                        "record": {"error": "stretch_max 1.881"}}
    gt.params_of = lambda it: {"kind": "top", "fabric": "medium"}
    gt.texture_sources = lambda c, i: {}
    inv.get_item = lambda i: {"id": i}
    steps = [{"name": "template", "item_id": "item_shirt"}, {"name": "pieces", "item_id": item}]
    with figure_build._lock:
        figure_build._active.add("Demo")
        figure_build._current["Demo"] = {"reason": "manual", "steps": steps, "step": {"index": 2}}
    p = gt.piece_progress("Demo", "item_shirt", profile={}, item={"id": "item_shirt"})
    check("a) template done, Build on the shoe", (p["state"], p["steps"][2]["status"]), ("failed", "failed"))
    with figure_build._lock:
        figure_build._current["Demo"] = {"reason": "manual", "steps": [{"name": "plain_body", "item_id": ""}] + steps,
                                         "step": {"index": 1}}
    p = gt.piece_progress("Demo", "item_shirt", profile={}, item={"id": "item_shirt"})
    check("b) template still ahead", (p["state"], p["steps"][2]["detail"]), ("running", gt.WAITING_FOR_STEP))
    with figure_build._lock:
        figure_build._active.discard("Demo")
        figure_build._current.pop("Demo", None)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
