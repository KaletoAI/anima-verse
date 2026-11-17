"""A187 — the shoe mesh's silhouette limit is an instance setting (default 0.55), a refused stored mesh that passes
it is accepted without a mesher call, and a refused SHOE step no longer reads as a refused base body.

Usage:
    ./.venv/bin/python scripts/smoke_a187_shoe_iou.py

No server, no world DB, no hub: ``paths.init(<tmpdir>)`` first; the mesher, Blender and the fit readers are stubs.

The live case (Dario, 2026-11-17): six UniForge meshes of the braided leather sandals (hub e3bd9bc8, 97792bf3,
2eecfb52, 7b70af2d, 91d5532d, 024f2fe1) read mesh_iou 0.59-0.63 against the cut-out and were refused at 0.75; the
piece dialog's body switch then said "Base body: refused — shoe mesh refused (...)".

Expected, derived by hand:
[1] ``mesh_iou_min``: unset -> 0.55 (the new default); 0.7 -> 0.7; 2 -> 0.95 (schema max); 0.1 -> 0.3 (schema
    min); "x" -> 0.55. ``check_gates`` of {component_share 1.0, mesh_iou 0.6273} against ``mesh_gates()`` at the
    default -> ok (old code: refused, 0.6273 < 0.75); mesh_iou 0.5 -> refused with one reason naming mesh_iou.
[2] ``run_source`` on a source whose source/empty/cutout are done and whose mesh record is a GATE refusal with
    component_share 1.0, mesh_iou 0.6273 and a stored raw.glb, run with ``keep_refused=("mesh",)`` (a Build):
    a) limit 0.75 (setting): the refusal is kept -> {ok False, kept_refused True}, prepare calls 0, mesh calls 0;
    b) limit unset (0.55): prepare calls 1 (the stored file re-gated), mesh calls 0 (no hub job), the mesh record
       accepted with ``regated`` True, the insole ran once -> ok True, ran ["mesh", "insole"];
    c) a record with failure "backend" (no gate refusal) is not re-gated: prepare calls stay 1, the mesh step runs
       (mesh calls 1).
[3] ``fit_attempts.fit_status`` of a shoe on the plain body whose chain failure is the step "mesh":
    failure None, source_failure the record (old code: failure = the mesh record -> "refused");
    with a chain failure of step "fit": failure the record, source_failure None.
[4] the mesh Regenerate's backend pick:
    a) inside ``mesh_pick.use("mesh-x")`` the shoe's mesh attempt calls ``generate_mesh`` with backend_glob "mesh-x",
       outside it with "" (Auto); the garment mesh attempt the same;
    b) two runs differing only in the pick are two requests (``_Job.key``), a picked run is no default run;
    c) the route: backend "mesh-x" with step "fit" -> 400, nothing started; with step "mesh" and the pick not
       available -> 503, nothing started; available -> started with backend "mesh-x"; no backend -> started with "".
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="a187-")
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
    from app.core import config, footwear_gates as fg, footwear_source as fs
    setting = {}
    real_get = config.get
    config.get = lambda path, default=None: (setting["v"] if path == "server.footwear_mesh_iou_min" and "v" in setting
                                             else real_get(path, default))

    print("[1] the limit")
    for value, want in ((None, 0.55), (0.7, 0.7), (2, 0.95), (0.1, 0.3), ("x", 0.55)):
        setting.clear()
        if value is not None:
            setting["v"] = value
        check(f"mesh_iou_min({value!r})", round(fg.mesh_iou_min(), 4), want)
    setting.clear()
    ok, reasons = fg.check_gates({"component_share": 1.0, "mesh_iou": 0.6273}, fg.mesh_gates())
    check("0.6273 passes the default", (ok, reasons), (True, []))
    ok, reasons = fg.check_gates({"component_share": 1.0, "mesh_iou": 0.5}, fg.mesh_gates())
    check("0.5 refused", (ok, len(reasons), reasons[0].startswith("mesh_iou 0.5 < 0.55")), (False, 1, True))

    print("[2] re-gating the stored delivery")
    item = "item_a187_sandals"
    ssig = fs.current_ssig(item)
    d = fs.source_dir(item, ssig)
    d.mkdir(parents=True)
    for step in ("source", "empty", "cutout"):
        for name in fs._STEP_FILES[step]:
            (d / name).write_bytes(b"x")
        fs._set_step(d, step, fs._entry(accepted=True, gates={}))
    calls = {"mesh": 0, "insole": 0, "prepare": 0}
    gates = {"ok": False, "component_share": 1.0, "mesh_iou": 0.6273,
             "reasons": ["mesh_iou 0.6273 < 0.75 (side-silhouette IoU against the empty-shoe cut-out)"]}

    def refused(failure):
        (d / "raw.glb").write_bytes(b"raw")
        fs._set_step(d, "mesh", fs._entry(accepted=False, gates=dict(gates), failure=failure,
                                          attempts=[{"attempt": 1, "ok": False, "gates": dict(gates)}]))

    def prepare(raw, candidate, alpha, attempt, res):
        calls["prepare"] += 1
        Path(candidate).write_bytes(b"prepared")
        ok_, reasons_ = fg.check_gates({"component_share": 1.0, "mesh_iou": 0.6273}, fg.mesh_gates())
        return {"attempt": attempt, "ok": ok_, "gates": {"ok": ok_, "reasons": reasons_, "component_share": 1.0,
                                                          "mesh_iou": 0.6273}, "backend": "stub", "routing": {}}

    def mesh(iid, s, seed, dd):
        calls["mesh"] += 1
        raise fs.StepRefused("stub mesher", {}, fs.GATE)

    def insole(iid, s, seed, dd):
        calls["insole"] += 1
    fs._prepare_mesh, fs._cutout_alpha = prepare, (lambda p: None)
    fs._RUNNERS["mesh"], fs._RUNNERS["insole"] = mesh, insole

    refused(fs.GATE)
    setting["v"] = 0.75
    res = fs.run_source(item, keep_refused=("mesh",))
    check("a) limit 0.75 keeps the refusal", (res["ok"], res.get("kept_refused"), calls["prepare"], calls["mesh"]),
          (False, True, 0, 0))
    setting.clear()
    res = fs.run_source(item, keep_refused=("mesh",))
    rec = fs.step_record(item, ssig, "mesh")
    check("b) re-gated without a mesher call", (res["ok"], res["ran"], calls["prepare"], calls["mesh"],
                                                 calls["insole"]), (True, ["mesh", "insole"], 1, 0, 1))
    check("b) record accepted + regated", (rec.get("accepted"), rec.get("regated"), (d / "prepared.glb").is_file()),
          (True, True, True))
    refused(fs.BACKEND)
    fs.run_source(item, steps=["mesh"])
    check("c) a backend failure is meshed, not re-gated", (calls["prepare"], calls["mesh"]), (1, 1))

    print("[3] fit_status of a shoe whose mesh was refused")
    from app.core import base_body, fit_attempts, garment_footwear, garment_store as gs
    gs._garment_kind = lambda i: "footwear"
    gs.garment_fsig = lambda c, i, profile=None: "f" * 12
    base_body.current_base = lambda c, profile=None: ("base0", "sha0")
    garment_footwear.fit_state = lambda c, i, f, b, body="": "missing"
    mesh_failure = {"step": "mesh", "error": "shoe mesh refused after 1 attempts (...)"}
    gs.chain_failure = lambda c, i, f, base_model_sha="": mesh_failure
    st = fit_attempts.fit_status("Demo", item, "", profile={})
    check("mesh failure -> source_failure", (st["failure"], st["source_failure"]), (None, mesh_failure))
    fit_failure = {"step": "fit", "error": "toe_gap 0.03 > 0.02"}
    gs.chain_failure = lambda c, i, f, base_model_sha="": fit_failure
    st = fit_attempts.fit_status("Demo", item, "", profile={})
    check("fit failure -> failure", (st["failure"], st["source_failure"]), (fit_failure, None))

    print("[4] the backend pick")
    from app.core import garment_mesh, garments, mesh_pick
    import app.imagegen.service as svc_mod
    seen = []

    class Svc:
        def generate_mesh(self, **kw):
            seen.append(kw.get("backend_glob"))
            return {"ok": False, "error": "stub"}
    svc_mod.get_image_service = lambda: Svc()
    for pick in ("mesh-x", ""):
        with mesh_pick.use(pick):
            for call in (lambda: fs._mesh_attempt(item, d / "cutout.png", d / "raw.glb", d / ".c.glb", None, 1),
                         lambda: garment_mesh._attempt("Demo", "clothing", {"front": d / "cutout.png"},
                                                       d / "raw2.glb", d / ".c2.glb", 1)):
                try:
                    call()
                except RuntimeError:
                    pass
    check("a) backend_glob per pick", seen, ["mesh-x", "mesh-x", "", ""])
    a = garments._Job(item, "mesh", None, True, backend="mesh-x")
    b = garments._Job(item, "mesh", None, True)
    check("b) the pick is part of the request", (a.key() != b.key(), garments._Job(item, None, None, False,
                                                                                    backend="x").plain), (True, False))
    from fastapi import HTTPException
    from app.routes import characters as rc
    import app.core.explicit_backend as eb
    started = []
    rc._require_character = lambda n: None
    garments.check_run = lambda *a, **k: None
    base_body.current_base = lambda c, profile=None: ("base0", "sha0")
    garments.start_garment = lambda c, i, **k: started.append(k.get("backend")) or {"started": True}
    available = {"ok": False}

    def require(name, media="image", has_input_image=False):
        if not available["ok"]:
            raise HTTPException(status_code=503, detail="not available")
        return object()
    eb.require_explicit_backend = require

    def post(**body):
        try:
            rc.run_character_garment("Demo", item, rc.GarmentRunRequest(**body), {})
            return 202
        except HTTPException as e:
            return e.status_code
    check("c) pick on the fit step", (post(step="fit", backend="mesh-x"), started), (400, []))
    check("c) pick not available", (post(step="mesh", force=True, backend="mesh-x"), started), (503, []))
    available["ok"] = True
    check("c) pick available", (post(step="mesh", force=True, backend="mesh-x"), started), (202, ["mesh-x"]))
    check("c) Auto", (post(step="mesh", force=True), started[-1]), (202, ""))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
