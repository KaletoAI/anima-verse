#!/usr/bin/env python3
"""Ruling A61 — a paint step that the same inputs refuse again is not retried by every automatic Build, and a body
whose mesh does not match its own views is due for a new mesh (``app/core/base_body.py`` block "Refusals of the
outfit model's paint step", ``app/core/figure_build.py`` ``plan`` / ``_run_assemble`` / ``_build_problem``).

Usage:
    ./.venv/bin/python scripts/smoke_figure_build_a61.py [--kira <character folder>]

Runs against a THROWAWAY storage + instance directory (the instance holds only ``body_retexture.worker_dir``) — no
world DB, no hub, no GPU, no server. Section [1] works on READ-ONLY COPIES of Kira's files (default
``worlds/Anima Divide/characters/Kira``; ``--kira`` or ``A61_KIRA_DIR`` another folder) and runs the LOCAL body
retexture worker (CPU, ~25 s per run, ``nice``); without that folder or the worker it is SKIPPED (said once).
Section [2] stubs the resolver and the producers by tables (``smoke_figure_build_plan.World``).

The incident (Finding A38, Ruling A61): Kira's stored base mesh ``base20d5701a`` is the mesh of 2026-11-12 (a stale
mesher original was re-cleaned and published on 2026-11-13 23:57), its views are those of 2026-11-13. Every Build
of the figure ``d5320a5297d2`` (painted thong + stockings on the plain body) failed in the paint step with the
worker's refusal of the BACK registration fit, and every automatic Build (one per trigger, every minute or two)
ran it again.

Expected, by hand:

[1] (the copy) ``build_outfit_model`` with the figure resolution stubbed (plain body ``base20d5701a``, texture
    ``texbff0a795dc70``, the dressed views ``tpose[_back]_d5320a5297d2`` — the store's copies — and the base
    views ``tpose[_back]_base20d5701a`` as registrations; nothing stored to reuse, no view guard):
    ``ok`` False with the worker's own words "back view: the image silhouette does not match the mesh render (fit
    needs -10 deg rotation, axis ratio 1.48)" (the A38 measurement: angle −10.1°, axis ratio 1.477 > 1.35);
    ``registration_refusal_view`` of it = "back"; ``mesh_view_mismatch(base20d5701a)`` = back (recorded by the
    run); ``outfit_refusal`` = that error (a refusal, not load); ``base_refresh_plan(missing=True)`` = reason
    ``mesh_mismatch``, views [], model True — without ``missing`` reason "" (the improvement never spends on it);
    ``base_rebuild_cost`` with the stages of Kira's last base mesh run (hub op of 2026-11-13 23:49: mesh, face, rig)
    = 3 hub jobs, the note opens "the mesh does not match its views"; ``_build_problem`` of the figure on the plain
    body = kind ``mesh_mismatch``, step ``assemble``, view back, body plain, action ``rebuild_mesh``, jobs 3 (the
    plain-body step's), held. The assembly refusal recorded for the figure holds while nothing changes and lets go
    once the dressed back changes. A new unrigged source (another file) ends the mesh record.
    Control: the same views on the FRESH 2026-11-13 23:53 mesh (``rollback/base20d5701a/facefix/base20d5701a.glb``,
    68074 vertices — the mesh those views were made for) → the worker passes (A38: front IoU 0.92, back 0.91).
[2] (stubbed World: a plain body with a painted blouse, no outfit model yet)
    (a) the first automatic Build runs the paint step once (calls ``model no-prepare``), fails with the worker's
        refusal → ``failed == {"assemble": …}``; the plan of an automatic Build then lists ``assemble`` "failed —
        Retry" and nothing runnable; a second automatic Build calls NOTHING (``start`` → "current"); the Figure
        payload says status ``failed`` and ``problem`` = {kind failed, step assemble, view back, held True}; with a
        mesh record on the plain body its row in the payload is ``older_prompts`` with the note "The mesh does not
        match its back view — …" (the Figure tab says Outdated, not Current).
    (b) a manual Build runs the paint step again (once): calls ``model no-prepare``.
    (c) an input change (the stubbed ``assemble_inputs`` moves) → the automatic plan lists ``assemble`` without
        ``failed`` again.
    (d) a worker that is MISSING (``RetextureUnavailable`` — no refusal) is no cached failure: the next automatic
        plan lists ``assemble`` to run.
[3] Fails on the old code: at cbc6a75ee ``base_body.py`` has no ``assemble_refusal`` / ``mesh_view_mismatch`` and
    ``base_refresh_plan`` knows no ``mesh_mismatch``; ``figure_build.plan`` appends "Assemble the figure" with no
    held branch. Run on cbc6a75ee (the smoke copied into a worktree of it), [1] fails at the first check after the
    worker run (no ``registration_refusal_view``) and [2] (a) fails: the second automatic Build calls
    ``model no-prepare`` again.
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BASELINE = "cbc6a75ee"
WORKER = Path(os.path.expanduser(os.environ.get("A61_WORKER_DIR") or "~/projekte/ComfyUI-GLB-Body-Retexture"))
BSIG, SIG, TEX = "base20d5701a", "d5320a5297d2", "texbff0a795dc70"
REFUSAL = ("GLBBodyRetexture: back view: the image silhouette does not match the mesh render (fit needs -10 deg "
           "rotation, axis ratio 1.48); check view name, framing and mask")
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def setup(root: Path, worker_dir: str = ""):
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
    instance = root / "instance" / "config.json"
    instance.write_text(json.dumps({"body_retexture": {"worker_dir": worker_dir}} if worker_dir else {}))
    from app.core import config
    config.load(paths.get_config_path(), instance_path=instance)
    from app.core import db
    db.init_schema()


# --- [1] the copy ---------------------------------------------------------------------------------------------

def _copy_kira(source: Path, character: Path) -> None:
    """Read-only copies of what the paint step of ``SIG`` reads."""
    files = [f"model3d/{BSIG}.glb", f"model3d/{BSIG}.json", f"model3d/unrigged/{BSIG}.glb",
             f"model3d/unrigged/{BSIG}.json"]
    for view in ("", "_back", "_left", "_right"):
        files += [f"model_refs/tpose{view}_{BSIG}.png", f"model_refs/tpose{view}_{BSIG}.json"]
    files += [f"model_refs/tpose_{SIG}.png", f"model_refs/tpose_{SIG}.json",
              f"model_refs/tpose_back_{SIG}.png", f"model_refs/tpose_back_{SIG}.json"]
    for rel in files:
        target = character / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, target)


def copy_section(root: Path, source: Path):
    from app.core import base_body, body_retexture, figure, figure_build as fb, model3d, model_overview
    from app.core import task_queue
    print("[1] the paint step on a copy of Kira's files")
    character = root / "world" / "characters" / "Kira"
    _copy_kira(source, character)
    refs = character / "model_refs"
    fig = figure.Figure(signature=SIG, bsig=BSIG, shape=BSIG, texture=TEX, in_body=(), own=(),
                        painted=("item_black_lace_thong",), pieces={"underwear_bottom": "item_black_lace_thong"})

    class Tracks:
        def track_start(self, *a, **k):
            return ""
    task_queue.get_task_queue = lambda: Tracks()
    base_body._profile_of = lambda c, p: {}
    base_body.is_base_pipeline = lambda c, profile=None: True
    base_body.base_signature = lambda c, profile=None: BSIG
    base_body.dressed_views = lambda: ("front", "back")
    base_body.dressed_image = lambda c, v, sig, bsig, fig=None: refs / f"tpose{'' if v == 'front' else '_' + v}_{SIG}.png"
    model3d._ref_manifest = lambda path: {"pieces": dict(fig.pieces), "items": []}
    figure.delivered_figure = lambda c, **kw: fig
    figure.predicted_variant = lambda *a, **k: "rigged"
    base_body.figure_texts = lambda *a, **k: {}
    base_body._sync_texture_views = lambda *a, **k: None
    base_body.texture_inputs = lambda *a, **k: {}
    base_body.stored_texture_body = lambda *a, **k: None
    base_body._guard_dressed_views = lambda *a, **k: ({}, [])

    started = time.monotonic()
    result = base_body.build_outfit_model("Kira", SIG)
    print(f"       (worker run {time.monotonic() - started:.0f} s)")
    error = str(result.get("error") or "")
    check("[1] the paint step fails", result.get("ok"), False)
    check("[1] … with the worker's refusal of the back fit", error, REFUSAL)
    check("[1] registration_refusal_view", base_body.registration_refusal_view(error), "back")
    mismatch = base_body.mesh_view_mismatch("Kira", BSIG) or {}
    check("[1] mesh_view_mismatch recorded by the run", mismatch.get("view"), "back")
    check("[1] outfit_refusal (a refusal, not load)", base_body.outfit_refusal("Kira", SIG), REFUSAL)

    saved = (base_body.base_prompts_freshness, base_body.base_view_states, model3d.mesh_hub_stages)
    base_body.base_prompts_freshness = lambda c, profile=None: {"state": model_overview.CURRENT}
    base_body.base_view_states = lambda c, profile=None: {v: {"state": model_overview.CURRENT}
                                                          for v in base_body.BASE_VIEWS}
    # Kira's last base mesh run (hub op hop_636f7b13db9c, 2026-11-13 23:49): stages mesh, face, rig.
    model3d.mesh_hub_stages = lambda c, sig: ["mesh", "face", "rig"]
    plan = base_body.base_refresh_plan("Kira", profile={}, missing=True)
    check("[1] base_refresh_plan(missing=True)", (plan["reason"], plan["views"], plan["model"]),
          ("mesh_mismatch", [], True))
    check("[1] base_refresh_plan without missing", base_body.base_refresh_plan("Kira", profile={})["reason"], "")
    cost = base_body.base_rebuild_cost("Kira", profile={}, plan=plan)
    check("[1] base_rebuild_cost hub_jobs", cost["hub_jobs"], 3)
    check("[1] base_rebuild_cost note", cost["note"].split(":")[0], "the mesh does not match its views")
    steps = [fb.Step("plain_body", fb.MESH_MISMATCH_LABEL.format(body="Plain body", parts="mesh + face + rig"), 3,
                     manual=figure.BASE_OUTDATED)]
    problem = fb._build_problem("Kira", steps, {}, fig) or {}
    check("[1] problem", {k: problem.get(k) for k in ("kind", "step", "view", "body", "action", "jobs", "held")},
          {"kind": "mesh_mismatch", "step": "assemble", "view": "back", "body": "plain", "action": "rebuild_mesh",
           "jobs": 3, "held": True})

    base_body.record_assemble_refusal("Kira", SIG, fig, error)
    check("[1] assembly refusal holds for the same inputs",
          (base_body.assemble_refusal("Kira", SIG, fig) or {}).get("error"), REFUSAL)
    back = refs / f"tpose_back_{SIG}.png"
    original = back.read_bytes()
    back.write_bytes(original + b"\0")
    check("[1] … and lets go once the dressed back changes", base_body.assemble_refusal("Kira", SIG, fig), None)
    back.write_bytes(original)

    control = source / "model3d" / "rollback" / BSIG / "facefix" / f"{BSIG}.glb"
    if control.is_file():
        unrigged = character / "model3d" / "unrigged" / f"{BSIG}.glb"
        shutil.copyfile(control, unrigged)
        check("[1] a new unrigged source ends the mesh record", base_body.mesh_view_mismatch("Kira", BSIG), None)
        check("[1] … and the plain body is not due for it any more",
              base_body.base_refresh_plan("Kira", profile={}, missing=True)["reason"], "")
        work = root / "control"
        work.mkdir()
        views = {"front": (refs / f"tpose_{SIG}.png", refs / f"tpose_{BSIG}.png"),
                 "back": (refs / f"tpose_back_{SIG}.png", refs / f"tpose_back_{BSIG}.png")}
        try:
            proof = body_retexture.retexture(unrigged, views, work / "out.glb", proof=work / "proof.json",
                                             atlas=work / "atlas.png")
            check("[1] control: the fresh 23:53 mesh passes the worker", bool(proof), True)
        except body_retexture.RetextureFailed as e:
            check("[1] control: the fresh 23:53 mesh passes the worker", str(e), "")
    else:
        print(f"  SKIP control: {control} missing")
    base_body.base_prompts_freshness, base_body.base_view_states, model3d.mesh_hub_stages = saved


# --- [2] the Build, stubbed -------------------------------------------------------------------------------------

def build_section(root: Path):
    import smoke_figure_build_plan as sfb
    from app.core import base_body, body_retexture, figure_build as fb, model3d
    print("[2] the Build holds a refused paint step until a person or an input change")
    sfb.install_stubs()
    sfb.W = sfb.World(painted=("blouse",), model=False)
    (root / "world" / "characters" / "Kira" / "model_refs").mkdir(parents=True)   # the records live there
    inputs = [1]
    base_body.assemble_inputs = lambda c, sig, fig: {"figure": fig.as_dict(), "inputs": inputs[0]}
    outcome = {"error": REFUSAL, "refused": True}

    def outfit_model(c, *, force=False, signature=None, prepare=True, **kw):
        sfb.W.record("model", "prepare" if prepare else "no-prepare")
        if outcome["error"]:
            # What build_outfit_model records for its failure (``_outfit_end`` in its ``finally``).
            base_body._outfit_end(c, signature, "model", outcome["error"], refused=outcome["refused"])
            return {"ok": False, "error": outcome["error"]}
        sfb.W.model_fig = sfb.W.delivered().as_dict()
        return {"ok": True}
    model3d.generate_for_current_outfit = outfit_model

    def run(automatic):
        sfb.W.calls.clear()
        status = fb.start("Kira", reason="smoke", automatic=automatic)["status"]
        sfb.wait_idle(fb)
        return status, [c for c in sfb.W.calls if c != "slot"]

    status, calls = run(True)
    check("[2a] first automatic Build runs the paint step", "model no-prepare" in calls, True)
    check("[2a] … and fails there", fb.state("Kira")["failed"].get("assemble", {}).get("error"), REFUSAL)
    auto = fb.plan("Kira", profile={}, explicit=False)
    check("[2a] automatic plan: assemble failed — Retry",
          [(s.name, s.failed == REFUSAL) for s in auto if s.name == "assemble"], [("assemble", True)])
    check("[2a] automatic plan: nothing runnable", fb._runnable(auto, False), [])
    status, calls = run(True)
    check("[2a] second automatic Build: start", status, "current")
    check("[2a] second automatic Build calls nothing", calls, [])
    info = fb.figure_info("Kira")
    problem = info.get("problem") or {}
    check("[2a] figure status", info["status"], "failed")
    check("[2a] problem", {k: problem.get(k) for k in ("kind", "step", "view", "action", "held")},
          {"kind": "failed", "step": "assemble", "view": "back", "action": "retry", "held": True})

    from app.core import figure
    saved = base_body.mesh_view_mismatch, figure._pending
    base_body.mesh_view_mismatch = lambda c, b: {"view": "back", "error": REFUSAL} if b == sfb.BSIG else None
    figure._pending = lambda *a, **k: []   # the stubbed World has no stored base model: no body change pending
    plain = fb.figure_info("Kira")["body"]["plain"]
    check("[2a] a mesh record: the Figure tab's plain body row is outdated, with the view",
          (plain["state"], plain["note"]),
          ("older_prompts", "The mesh does not match its back view — the outfit cannot be painted onto it"))
    base_body.mesh_view_mismatch, figure._pending = saved

    status, calls = run(False)
    check("[2b] a manual Build retries the paint step once", calls.count("model no-prepare"), 1)

    inputs[0] = 2
    auto = fb.plan("Kira", profile={}, explicit=False)
    check("[2c] an input change: assemble planned to run",
          [(s.name, s.failed) for s in auto if s.name == "assemble"], [("assemble", "")])

    inputs[0] = 3
    outcome.update(error="Body retexture worker not installed: python not found", refused=False)
    run(True)
    auto = fb.plan("Kira", profile={}, explicit=False)
    check("[2d] a missing worker is no cached failure",
          [(s.name, s.failed) for s in auto if s.name == "assemble"], [("assemble", "")])
    check("[2d] body_retexture.TIMED_OUT", body_retexture.TIMED_OUT, "Body retexture worker timed out")


def baseline_section():
    print(f"[3] fails on {BASELINE}")
    body = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/base_body.py"],
                          capture_output=True, text=True).stdout
    build = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/figure_build.py"],
                           capture_output=True, text=True).stdout
    check(f"[3] base_body.py at {BASELINE} readable", "def build_outfit_model" in body, True)
    check(f"[3] no assemble_refusal at {BASELINE}", "def assemble_refusal" in body, False)
    check(f"[3] no mesh_view_mismatch at {BASELINE}", "def mesh_view_mismatch" in body, False)
    check(f"[3] no mesh_mismatch reason at {BASELINE}", '"mesh_mismatch"' in body, False)
    check(f"[3] assemble appended unconditionally at {BASELINE}",
          'steps.append(Step("assemble", "Assemble the figure", 0))' in build and "_assemble_held" not in build, True)


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("copy", "build"):
        part, rest = args[0], args[1:]
        with tempfile.TemporaryDirectory(prefix=f"a61-{part}-") as tmp:
            root = Path(tmp)
            if part == "copy":
                setup(root, str(WORKER))
                copy_section(root, Path(rest[0]))
            else:
                setup(root)
                build_section(root)
        if FAILS:
            print(f"FAIL ({part}): {', '.join(FAILS)}")
            return 1
        return 0
    source = Path(os.environ.get("A61_KIRA_DIR") or (args[args.index("--kira") + 1] if "--kira" in args
                                                     else ROOT / "worlds" / "Anima Divide" / "characters" / "Kira"))
    codes = []
    if source.is_dir() and (WORKER / ".venv" / "bin" / "python").is_file():
        codes.append(subprocess.run(["nice", "-n", "15", sys.executable, __file__, "copy", str(source)]).returncode)
    else:
        print(f"[1] SKIP: no character folder at {source} or no local worker at {WORKER}")
    codes.append(subprocess.run([sys.executable, __file__, "build"]).returncode)
    baseline_section()
    if any(codes) or FAILS:
        print(f"\nFAIL: {', '.join(FAILS) or 'see above'}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
