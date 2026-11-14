#!/usr/bin/env python3
"""Ruling A69: a refused result the user accepted — a refused fit (``fit_attempts.accept``, Ruling A31), a stored
image or a kept mesh used by hand (``garments.use_attempt`` / ``use_mesh``, Rulings A37 / A58) — makes the piece's
status follow the accepted result: green with "Accepted by you", never "Failed". A later NEW refusal still says
"Failed".

Usage:
    ./.venv/bin/python scripts/smoke_accepted_refusal_status.py

Runs against a THROWAWAY storage + instance directory — no world DB, no hub, no GPU, no server, no Blender (the
distance tier's ``refine.decimate_to`` copies the file). Real: the Build's run loop (``figure_build._run_planned``
with its plan and its ``pieces`` step → ``_chain``), its state, ``_worn_rows`` / ``_build_problem``,
``fit_attempts`` (store, accept through the route, the marker), ``garment_store`` (paths, records, the run status,
the failure records), ``garments._fit_info`` / ``user_taken``, ``garment_set.piece_status``. Tables: the items, the
base body (BSIG / "basesha"), the fsig, the estimate; ``garments.run_queued`` is the garment chain as it ends when
its fit is refused (``garments._refusal`` + ``_note_outcome``: the run status failed at ``fit``, the failure
record, the kept attempt of ``fit_attempts.store``); the other Build steps answer "".

The incident (Kai, 2026-11-14): the Build of 22:03:28 ran the jeans' chain, its fit was refused ("deep_push_share
0.1512 > 0.12"), the Build recorded ``failed["pieces"]`` for the jeans. At 22:04:15 the user accepted the refused fit
(Details preview, plain body); the figure was assembled with it at 22:06:04 — the Figure tab's row still said
"Failed": ``figure_build._last`` kept the Build's failure, and ``_worn_rows`` puts a failure above everything.

Fixture: "Demo" wears jeans [bottom] own mesh on the plain body ``BSIG``; the prepared mesh of fsig F1 exists, no
fit yet. E = "fit refused — deep_push_share 0.1512 > 0.12 (share of vertices pushed out more than 3 cm)".

Expected, derived by hand:

[1] A manual Build: plan = the jeans' chain step ``pieces`` (its fit missing); the chain refuses at the fit →
    ``state()["failed"]`` = {pieces: {error "fit — " + E, item_id jeans}}; the jeans' row ``failed`` with that
    failure; the run status (``gs.status``) failed at ``fit``; the failure record of F1 holds; the attempt kept on
    the plain body (``attempts/jeans_F1.glb``).
[2] Accept (route ``POST …/fits/plain/accept``, admin): 200; the plain fit of F1 = the attempt's bytes, ``accepted``
    True with ``user_accepted``; the failure record and the run status' failure are gone (unchanged A31 behaviour);
    NEW: the Build's state names no failure of the jeans (``{}``), the row is ``ready`` with ``accepted_by_user``
    {step "fit", on "Plain body", reason REASON} (``fit_attempts.plain_reason`` of E: the "fit refused — " prefix
    stripped, no plain-word rule for ``deep_push_share``); ``_build_problem`` None; the fit row of the garment window
    (``garments._fit_info``) ``accepted`` with ``user_accepted.reason`` REASON; the Wardrobe chip
    (``piece_status`` of that fit row) ``fitted`` with ``accepted_by_user.step`` "fit".
[3] A newer refusal: the piece changes (fsig F2: a new prepared mesh), a manual Build runs its chain, refused again
    → the Build's ``failed["pieces"]`` names the jeans again, the row says ``failed`` (no marker), the run status is
    failed at ``fit``. The acceptance of F1 stays on disk (another fsig) but does not hide the new refusal.
[4] "Use this" on an image (A37) answers a Build failure at that step or later: a Build whose chain failed at
    ``ghost`` ("ghost — gate refused: …"); ``garments.use_attempt`` (the image layer ``garment_images.use_attempt``
    stubbed: it publishes the final image with a ``user_accepted`` block) → the Build's state names no failure of
    the jeans; ``garments.user_taken`` = {step "ghost", view "back", reasons ["piece_share 0.02 < 0.03"]}. A Build
    failure at ``worn`` (BEFORE ghost) is NOT answered by a ghost image.
[5] "Use this" on a kept mesh (A58) answers a Build failure at ``mesh``: ``garments.use_mesh`` (``garment_mesh.
    use_kept`` stubbed: the prepared record ``user_accepted``, ``user_reasons``; the fit start stubbed) → the Build's
    state names no failure of the jeans; ``user_taken`` = {step "mesh", reasons ["largest component 0.82 < 0.9"]}.
[6] Fails on the old code: the same [1] + [2] run on BASELINE (``git archive`` of ``app/`` into a temp dir, the
    smoke re-run with that tree first on ``sys.path``) — after the accept the row is still ``failed`` and the
    Build's state still names the jeans' failure.
"""
import copy
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(os.environ.get("A69_APP_ROOT") or ROOT)
sys.path.insert(0, str(APP_ROOT))

BASELINE = "2c743fb54"
FAILS = []
BSIG = "base0123abcd"
F1, F2 = "0123456789ab", "ba9876543210"
REASON = "deep_push_share 0.1512 > 0.12 (share of vertices pushed out more than 3 cm)"
E = "fit refused — " + REASON
GATES = {"ok": False, "reasons": [REASON], "metrics": {"deep_push_share": 0.1512},
         "limits": {"deep_push_share": ["max", 0.12]}}
CUR = {"fsig": F1}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


ITEMS = {"jeans": {"id": "jeans", "name": "Jeans", "category": "outfit_piece",
                   "outfit_piece": {"slots": ["bottom"], "mesh_mode": "own_mesh"}},
         "hair_body": {"id": "hair_body", "name": "Short hair", "category": "garment", "owner": "Demo",
                       "garment": {"kind": "hair", "mesh_mode": "body", "description": "short hair"}}}
W = {"bottom": "jeans"}


def profile():
    return {"model_pipeline": "base_body", "base_hairstyle": "hair_body", "equipped_pieces": dict(W),
            "equipped_mesh_pieces": {"hair": "hair_body"}, "equipped_items": []}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def setup(root: Path):
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    from app.blender import refine
    from app.core import (base_body, figure, figure_build, garment_refit, garment_store as gs, garments, model3d,
                          motion_item_cache)
    from app.models import character as character_model, inventory
    character_model.get_character_dir("Demo", create=True)
    inventory.get_item = lambda item_id, **_kw: copy.deepcopy(ITEMS.get(str(item_id)))
    motion_item_cache.item_snapshot = lambda **_kw: copy.deepcopy(ITEMS)
    base_body.is_base_pipeline = lambda *_a, **_kw: True
    base_body.base_signature = lambda *_a, **_kw: BSIG
    base_body.base_model_sha256 = lambda *_a, **_kw: "basesha"
    base_body.current_base = lambda *_a, **_kw: (BSIG, "basesha")
    base_body.dress_text = lambda *_a, **_kw: ""
    base_body.side_views_dressed = lambda: False
    base_body.dressed_views = lambda: ("front", "back")
    base_body.shape_view_shas = lambda *_a, **_kw: {}
    base_body.shape_view = lambda *_a, **_kw: None
    base_body.stored_base_haired = lambda *_a, **_kw: True
    base_body.prompts_current = lambda *_a, **_kw: True
    base_body.base_refresh_plan = lambda *_a, **_kw: {}
    base_body.dressed_image = lambda *_a, **_kw: root / "view.png"
    base_body.dressed_view_estimate = lambda *_a, **_kw: 3
    base_body.dressed_view_refusals = lambda *_a, **_kw: {}
    base_body.mesh_view_mismatch = lambda *_a, **_kw: None
    gs.garment_fsig = lambda *_a, **_kw: CUR["fsig"]
    garments.cached_failure = lambda *_a, **_kw: None
    garments.run_estimate = lambda *_a, **_kw: (
        {"hub_jobs": 0, "steps": [], "note": ""} if _fitted() else {"hub_jobs": 0, "steps": ["fit"], "note": "fit"})
    garment_refit.work_count = lambda *_a, **_kw: 0
    model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "rig"]
    model3d.find_model3d = lambda *_a, **_kw: None
    model3d._read_sidecar = lambda _p: {}
    figure_build._read_profile = lambda _c: profile()
    figure_build.base_step_in_flight = lambda *_a, **_kw: ""
    figure_build._tracked = lambda *_a, **_kw: (None, "")
    figure_build._base_snapshot = lambda *_a, **_kw: None
    figure_build._base_changed = lambda *_a, **_kw: []
    figure_build._pin = lambda *_a, **_kw: None
    figure_build._check_pin = lambda *_a, **_kw: None
    figure_build._RUNNERS = {**figure_build._RUNNERS, **{k: (lambda *_a, **_kw: "") for k in figure_build._RUNNERS
                                                          if k != "pieces"}}
    character_model.get_character_profile = lambda *_a, **_kw: profile()

    def decimate(src, _target, low, *, tris=None):
        shutil.copyfile(src, low)
        return {"ok": True, "tris": tris, "ratio": 1.0}
    refine.decimate_to = decimate
    _prepared(b"prepared-1")


def _prepared(data: bytes):
    from app.core import garment_store as gs
    path = gs.garment_path("Demo", "jeans", CUR["fsig"], "prepared")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    gs.write_record(path.with_suffix(".json"), {"accepted": True, "kind": "clothing", "item_id": "jeans",
                                                "fsig": CUR["fsig"]})
    return path


def _fitted() -> bool:
    from app.core import garments
    return garments._fit_state("Demo", "jeans", CUR["fsig"], "basesha", profile=profile()) == "accepted"


def refusing_chain(root: Path, step: str = "fit", error: str = E):
    """``garments.run_queued`` as the chain ends refused at ``step`` (``_refusal`` + ``_note_outcome``; a refused fit
    keeps its attempt — ``garments._fit`` → ``fit_attempts.store``)."""
    from app.core import fit_attempts, garment_fit, garment_store as gs

    def run_queued(c, ids, explicit=False):
        out = {}
        for item_id in ids:
            fsig = CUR["fsig"]
            gs.start(c, item_id, step)
            if step == "fit":
                prepared = gs.garment_path(c, item_id, fsig, "prepared")
                glb = root / "attempt.glb"
                glb.write_bytes(b"attempt-" + fsig.encode())
                record = {"kind": "clothing", "item_id": item_id, "fsig": fsig, "body_id": BSIG,
                          "body_sha256": "basesha", "base_model_sha256": "basesha", "base_signature": BSIG,
                          "fit_version": garment_fit.FIT_VERSION["clothing"],
                          "inputs": {"prepared_sha256": sha(prepared.read_bytes())}, "metrics": GATES["metrics"],
                          "gates": GATES}
                fit_attempts.store(c, item_id, fsig, body="", kind="clothing", record=record, error=error,
                                   gates=GATES, glb=glb, tris=10)
            gs.end(c, item_id, step, error=error, gates=GATES)
            gs.record_failure(c, item_id, fsig, step=step, error=error, base_model_sha="basesha")
            out[item_id] = {"ok": False, "fsig": fsig, "step": step, "error": error, "gates": GATES}
        return out
    return run_queued


def build(root: Path, step: str = "fit", error: str = E):
    from app.core import figure, figure_build, garments
    garments.run_queued = refusing_chain(root, step, error)
    figure.invalidate()
    figure_build._run_planned("Demo", "smoke", profile(), automatic=False)


def row():
    from app.core import figure, figure_build
    figure.invalidate()
    wanted, delivered = figure._delivered("Demo", profile=profile())
    failures = figure_build._with_cached_failures(figure_build.state("Demo")["failed"], [])
    return [r for r in figure_build._worn_rows("Demo", wanted, delivered, failures, False, profile())
            if r["item_id"] == "jeans"][0]


def jeans_failures():
    from app.core import figure_build
    failed = figure_build.state("Demo")["failed"]
    return {name: entry.get("error") for name, entry in failed.items()
            if "jeans" in (entry.get("items") or {entry.get("item_id"): 1})}


def accept_section(root: Path, *, old: bool = False):
    """[1] + [2]; ``old``: on the baseline tree, only what the bug shows."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core import auth_dependency, garment_store as gs
    from app.routes import characters as characters_route
    print("[1] the Build's chain refused at the fit")
    build(root)
    check("[1] the Build's failure", jeans_failures(), {"pieces": "fit — " + E})
    r = row()
    check("[1] the row: failed", (r["state"], r["failure"]), ("failed", "fit — " + E))
    check("[1] the run status", (gs.status("Demo", "jeans")["failed"] or {}).get("step"), "fit")
    check("[1] the failure record", gs.chain_failure("Demo", "jeans", F1, base_model_sha="basesha")["error"], E)
    attempt = gs.garment_path("Demo", "jeans", F1, "attempt")
    check("[1] the attempt kept", attempt.read_bytes() if attempt.is_file() else None, b"attempt-" + F1.encode())

    print("[2] the user accepts the refused fit")
    app = FastAPI()
    app.include_router(characters_route.router)
    auth_dependency.get_current_user = lambda _r: {"role": "admin", "username": "demo"}
    res = TestClient(app).post("/characters/Demo/garments/jeans/fits/plain/accept")
    fit = gs.garment_path("Demo", "jeans", F1, "fit")
    record = gs.read_record(fit.with_suffix(".json"))
    check("[2] 200, published", (res.status_code, fit.read_bytes() if fit.is_file() else None,
                                 record.get("accepted"), isinstance(record.get("user_accepted"), dict)),
          (200, b"attempt-" + F1.encode(), True, True))
    check("[2] failure record + run status gone",
          (gs.chain_failure("Demo", "jeans", F1, base_model_sha="basesha"), gs.status("Demo", "jeans")["failed"]),
          (None, None))
    r = row()
    if old:
        check(f"[6] {BASELINE}: the Build still names the jeans' failure", jeans_failures(), {"pieces": "fit — " + E})
        check(f"[6] {BASELINE}: the row still says failed", r["state"], "failed")
        return
    check("[2] the Build names no failure of the jeans", jeans_failures(), {})
    marker = r["accepted_by_user"] or {}
    words = REASON
    check("[2] the row: ready, accepted by you",
          (r["state"], r["failure"], marker.get("step"), marker.get("on"), marker.get("reason")),
          ("ready", "", "fit", "Plain body", words))
    from app.core import figure, figure_build
    wanted, delivered = figure._delivered("Demo", profile=profile())
    check("[2] no Build problem", figure_build._build_problem(
        "Demo", [], figure_build._with_cached_failures(figure_build.state("Demo")["failed"], []), delivered), None)
    from app.core import garment_set, garments
    info = garments._fit_info("Demo", "jeans", F1, "basesha")
    check("[2] the garment window's fit row",
          (info["status"], (info["user_accepted"] or {}).get("reason")), ("accepted", words))
    chip = garment_set.piece_status({"fsig": F1, "steps": {"fit": info}}, worn=True, base_model_ready=True)
    check("[2] the Wardrobe chip", (chip["state"], (chip.get("accepted_by_user") or {}).get("step")),
          ("fitted", "fit"))


def newer_section(root: Path):
    from app.core import garment_store as gs
    print("[3] a newer refusal (another fsig) says failed again")
    CUR["fsig"] = F2
    _prepared(b"prepared-2")
    build(root)
    check("[3] the Build's failure", jeans_failures(), {"pieces": "fit — " + E})
    r = row()
    check("[3] the row: failed, no marker", (r["state"], r["accepted_by_user"]), ("failed", None))
    check("[3] the run status", (gs.status("Demo", "jeans")["failed"] or {}).get("step"), "fit")
    check("[3] F1's acceptance stays on disk",
          isinstance(gs.read_record(gs.garment_path("Demo", "jeans", F1, "fit").with_suffix(".json"))
                     .get("user_accepted"), dict), True)


def use_sections(root: Path):
    from app.core import figure_build, garment_images, garment_mesh, garment_store as gs, garments
    from app.core.base_body import file_sha256
    print("[4] \"Use this\" on an image answers a Build failure at that step or later")
    CUR["fsig"] = F2
    garments._view_context = lambda *_a, **_kw: {"kind": "clothing", "fsig": CUR["fsig"]}

    def use_attempt(c, item_id, fsig, step, view, attempt):
        final = gs.garment_path(c, item_id, fsig, "image", step=step, view=view)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"ghost-back-attempt-2")
        gs.write_record(final.with_suffix(".json"), {"accepted": True, "user_accepted": {
            "at": "2026-11-14T21:10:00+00:00", "attempt": attempt, "attempt_sha256": file_sha256(final),
            "inputs": {}, "reasons": ["piece_share 0.02 < 0.03"]}})
        return {"changed": True, "passing": False, "user_accepted": True}
    garment_images.use_attempt = use_attempt
    build(root, step="worn", error="gate refused: worn")
    garments.use_attempt("Demo", "jeans", "ghost", "back", 2, profile=profile())
    check("[4] a failure at worn (before ghost) stays", jeans_failures(), {"pieces": "worn — gate refused: worn"})
    build(root, step="ghost", error="gate refused: ghost")
    check("[4] the Build's failure at ghost", jeans_failures(), {"pieces": "ghost — gate refused: ghost"})
    garments.use_attempt("Demo", "jeans", "ghost", "back", 2, profile=profile())
    check("[4] answered", jeans_failures(), {})
    check("[4] user_taken", garments.user_taken("Demo", "jeans", profile=profile()),
          {"step": "ghost", "view": "back", "reasons": ["piece_share 0.02 < 0.03"],
           "at": "2026-11-14T21:10:00+00:00"})

    print("[5] \"Use this\" on a kept mesh answers a Build failure at the mesh")
    build(root, step="mesh", error="largest component 0.82 < 0.9")
    check("[5] the Build's failure at mesh", jeans_failures(), {"pieces": "mesh — largest component 0.82 < 0.9"})

    def use_kept(c, item_id, fsig, n):
        prepared = _prepared(b"kept-mesh-1")
        gs.write_record(prepared.with_suffix(".json"), {
            "accepted": True, "kind": "clothing", "item_id": item_id, "fsig": fsig, "picked_from": n,
            "picked_at": "2026-11-14T21:12:00+00:00", "user_accepted": True,
            "user_reasons": ["largest component 0.82 < 0.9"]})
        return {"n": n, "user_accepted": True, "during_job": False}
    garment_mesh.use_kept = use_kept
    garments.start_garment = lambda *_a, **_kw: {"status": "started"}
    garments.use_mesh("Demo", "jeans", 1, profile=profile())
    check("[5] answered", jeans_failures(), {})
    check("[5] user_taken", garments.user_taken("Demo", "jeans", profile=profile()),
          {"step": "mesh", "view": "", "reasons": ["largest component 0.82 < 0.9"],
           "at": "2026-11-14T21:12:00+00:00"})
    check("[5] the answer is idempotent", figure_build.answer_piece_failure("Demo", "jeans", ("mesh",)), False)


def run_part(part: str) -> int:
    with tempfile.TemporaryDirectory(prefix=f"a69-{part}-") as tmp:
        root = Path(tmp)
        setup(root)
        if part == "old":
            accept_section(root, old=True)
        else:
            accept_section(root)
            newer_section(root)
            use_sections(root)
    if FAILS:
        print(f"FAIL ({part}): {', '.join(FAILS)}")
        return 1
    return 0


def baseline() -> int:
    """[6]: the same [1] + [2] on BASELINE's ``app/`` (``shared/`` linked in for the templates it reads)."""
    print(f"[6] fails on {BASELINE}", flush=True)
    with tempfile.TemporaryDirectory(prefix="a69-baseline-") as tmp:
        old = Path(tmp)
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", BASELINE, "app"], capture_output=True)
        if archive.returncode != 0:
            print(f"  FAIL git archive {BASELINE}: {archive.stderr.decode()[:200]}")
            return 1
        subprocess.run(["tar", "-x", "-C", str(old)], input=archive.stdout, check=True)
        for name in ("shared", "plugins"):
            (old / name).symlink_to(ROOT / name)
        env = {**os.environ, "A69_APP_ROOT": str(old)}
        return subprocess.run([sys.executable, __file__, "old"], env=env).returncode


def main() -> int:
    if len(sys.argv) > 1:
        return run_part(sys.argv[1])
    codes = [subprocess.run([sys.executable, __file__, "new"]).returncode, baseline()]
    if any(codes):
        print("\nFAIL")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
