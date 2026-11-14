#!/usr/bin/env python3
"""Ruling A50: Re-fit in the piece dialog works on the SELECTED body, each body's result carries its own numbers, a
refused body says why, and a figure that paints nothing assembles without asking the texture store.

Usage:
    ./.venv/bin/python scripts/smoke_refit_selected_body.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no GPU, no server. What is real and what
is a table is named per section. Expected values, derived by hand from Ruling A50:

[1] ``garments.check_body_run`` (``garment_store._garment_kind`` and ``garment_footwear.stored_outfit_bodies``
    tables: item_jacket clothing, item_shoe footwear, hair_x hair; stored bodies [OB]): no body -> nothing raised;
    steps "fit" + OB on the jacket and on the shoe -> nothing raised; steps None + OB -> ValueError (a body is only
    named for a Re-fit); steps "fit" on hair_x + OB -> ValueError; steps "fit" + "ob00000000" (not stored) and +
    "../x" -> ValueError.
[2] ``_Job``: a job with a body is not ``plain`` and its ``key`` differs from the same job without one.
    ``garments._execute`` (``fit_attempts.fit_status``, ``run_garment`` and ``refit_on_body`` recorded):
    a) body OB, the plain body's fit accepted -> calls == [("refit", OB)], result ok True, body OB;
    b) body OB, the plain body's fit stale -> calls == [("run", "fit", force True, only True), ("refit", OB)];
    c) body OB, plain stale and its run refused ("refused - stub") -> calls == [("run", …)] only, result ok False,
       error "refused - stub", body "";
    d) no body -> calls == [("run", …)] only: the plain body is refitted, never a body shape.
[3] ``garments.refit_on_body`` (tables: ``body_sha256`` "bodysha" for OB, "" otherwise;
    ``base_body.current_base`` ("bsig", "basesha"); ``garment_store.accepted_fit`` the base fit
    ``item_jacket_0123456789ab.glb``; ``clear_failure_on_body``, ``garments.body_fit``,
    ``garment_footwear.body_fit`` and ``figure.invalidate`` recorded):
    a) the fit refused ("torso front: 0.75 … (source 0.85, limit -0.1)") -> the order is clear(item_jacket,
       0123456789ab, OB) THEN body_fit(OB, build True) THEN invalidate; {ok False, body OB, fsig 0123456789ab,
       error = that refusal};
    b) the fit accepted (fit a path, no error) -> {ok True, error ""};
    c) no base fit (accepted_fit None) -> {ok False, error NO_BASE_FIT_TO_DERIVE}, body_fit never called;
    d) a body that is no longer stored (body_sha256 "") -> error "The body shape is no longer stored";
    e) the shoe (footwear) -> ``garment_footwear.body_fit`` with build True, its fsig the shoe's
       ``garment_fsig`` ("shoefsig"), the cached refusal of THAT fsig cleared first.
[4] ``fit_attempts.body_numbers`` and ``_entry`` (tables: ``fit_status`` -> a refused body shape: state
    "outdated", failure {error "torso front: 0.75 of the area the source covers is covered within 4 cm (source
    0.85, limit -0.1)"}; ``attempt_of`` -> the kept attempt; ``body_label`` "Body shape (T-shirt)"; ``_current``
    ""): the plain fit record {metrics: sleeve skin 1.8 / 1.5, deep 0.0085, tight 0.1614, scale 1.08} and the
    body's attempt {metrics: sleeve skin 2.8 / 3.5, deep 0.202, tight 0.1867, scale 1.0; attempt.gates.torso.shares
    front 0.7488 / 0.8521, side 0.8503 / 0.915, back 0.8845 / 0.95}:
    a) body_numbers(plain) == its own five numbers, torso None (a plain fit has no torso frame);
    b) body_numbers(attempt) == 2.8 / 3.5 / 0.202 / 0.1867 / 1.0 and the three torso shares as stored — none of
       the plain body's numbers;
    c) a fit record with frame.torso.shares (an accepted body fit) -> those shares;
    d) the entry: status "refused", reason non-empty (the plain words of the refusal), numbers == b), arm_light
       the attempt's, ``_shown`` the attempt's GLB (the viewer shows the refused attempt), can_accept True.
[5] A figure with no texture needs on a meshed shape assembles without the texture store
    (``base_body.build_outfit_model``; tables: pipeline on, ``base_signature`` "bsig", the front view of the
    signature stored with sidecar dressed True — a view edited for an earlier PAINTED figure —, the delivered
    figure on shape OB with texture "", fit_refused {}, ``_snapshot_shape`` {unrigged: "u.glb"},
    ``_sync_texture_views`` no-op, ``_build_on_shape`` -> {ok True, on_shape True}; ``stored_texture_body`` REAL):
    the result is {ok True, on_shape True} — the shape itself, no ValueError "not a texture signature: ''".
    ``dressed_image`` (tables: the view's sidecar on OB, its base sha matching): a view with dressed True is None
    for a figure with texture "" and the path for texture "tex0123456789ab"; dressed False the other way round.
[6] Fails on the old code (main before Ruling A50, ``BASELINE``): [5]'s build run on BASELINE's base_body.py
    (loaded as a separate module, same tables) answers {ok False, error "not a texture signature: ''"};
    BASELINE's garments.py has no ``refit_on_body`` and ``start_garment`` takes no ``body``; its route model has no
    ``body`` field; its fit_attempts.py has no ``body_numbers``; its figure.py keys the texture on
    ``{item_id: sets.own[item_id] for item_id in own}`` (a piece left out for a refused fit counted as painted).
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = "7e65f3caf"
OB = "ob12345678"
FAILS: list = []


def check(label: str, got, want=True) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def raises(fn, exc=ValueError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def test_check_body_run() -> None:
    print("[1] check_body_run")
    from app.core import garment_footwear, garment_store as gs, garments
    kinds = {"item_jacket": "clothing", "item_shoe": "footwear", "hair_x": "hair"}
    real = (gs._garment_kind, garment_footwear.stored_outfit_bodies)
    gs._garment_kind = lambda item_id: kinds[item_id]
    garment_footwear.stored_outfit_bodies = lambda name: [OB]
    try:
        check("[1] no body", raises(lambda: garments.check_body_run("Demo", "item_jacket", steps=None, body="")),
              False)
        check("[1] fit + stored body (clothing)",
              raises(lambda: garments.check_body_run("Demo", "item_jacket", steps="fit", body=OB)), False)
        check("[1] fit + stored body (footwear)",
              raises(lambda: garments.check_body_run("Demo", "item_shoe", steps=["fit"], body=OB)), False)
        check("[1] a body without the fit step",
              raises(lambda: garments.check_body_run("Demo", "item_jacket", steps=None, body=OB)))
        check("[1] hair is not fitted per body",
              raises(lambda: garments.check_body_run("Demo", "hair_x", steps="fit", body=OB)))
        check("[1] a body that is not stored",
              raises(lambda: garments.check_body_run("Demo", "item_jacket", steps="fit", body="ob00000000")))
        check("[1] not a body id",
              raises(lambda: garments.check_body_run("Demo", "item_jacket", steps="fit", body="../x")))
    finally:
        gs._garment_kind, garment_footwear.stored_outfit_bodies = real


def test_execute() -> None:
    print("[2] the job runs on the selected body")
    from app.core import fit_attempts, garments
    with_body = garments._Job("item_jacket", "fit", None, True, only=True, body=OB)
    without = garments._Job("item_jacket", "fit", None, True, only=True)
    check("[2] a body job is not plain", with_body.plain, False)
    check("[2] the body is part of the key", with_body.key() != without.key(), True)
    calls: list = []
    state = {"plain": "accepted", "run_ok": True}
    real = (fit_attempts.fit_status, garments.run_garment, garments.refit_on_body)

    def run_garment(name, item_id, *, steps=None, view=None, force=False, state=None, only=False, beside=False,
                    **_):
        calls.append(("run", steps, force, only))
        return {"ok": True, "ran": ["fit"]} if STATE["run_ok"] else {"ok": False, "error": "refused - stub"}

    STATE = state
    fit_attempts.fit_status = lambda name, item_id, body, **_: {"state": STATE["plain"], "fsig": "f", "failure": None}
    garments.run_garment = run_garment
    garments.refit_on_body = lambda name, item_id, body, **_: (calls.append(("refit", body))
                                                               or {"ok": True, "body": body, "fsig": "f",
                                                                   "error": ""})
    try:
        garments._execute("Demo", garments._Job("item_jacket", "fit", None, True, only=True, body=OB))
        check("[2a] plain accepted: only the body", calls, [("refit", OB)])
        calls.clear()
        state["plain"] = "stale"
        job = garments._Job("item_jacket", "fit", None, True, only=True, body=OB)
        garments._execute("Demo", job)
        check("[2b] plain stale: the plain fit first, then the body", calls,
              [("run", "fit", True, True), ("refit", OB)])
        check("[2b] the result names the body", (job.result.get("ok"), job.result.get("body")), (True, OB))
        calls.clear()
        state["run_ok"] = False
        job = garments._Job("item_jacket", "fit", None, True, only=True, body=OB)
        garments._execute("Demo", job)
        check("[2c] plain refused: the body is not fitted", calls, [("run", "fit", True, True)])
        check("[2c] the plain refusal is the result",
              (job.result.get("ok"), job.result.get("error"), job.result.get("body")), (False, "refused - stub", ""))
        calls.clear()
        state.update(plain="accepted", run_ok=True)
        garments._execute("Demo", garments._Job("item_jacket", "fit", None, True, only=True))
        check("[2d] no body: the plain body only", calls, [("run", "fit", True, True)])
    finally:
        fit_attempts.fit_status, garments.run_garment, garments.refit_on_body = real


def test_refit_on_body() -> None:
    print("[3] refit_on_body")
    from app.core import base_body, figure, garment_footwear, garment_store as gs, garments
    order: list = []
    table = {"fit": None, "error": "torso front: 0.75 of the area the source covers is covered within 4 cm "
                                   "(source 0.85, limit -0.1)", "base_fit": True, "sha": "bodysha"}
    kinds = {"item_jacket": "clothing", "item_shoe": "footwear"}
    real = (gs._garment_kind, garments.body_sha256, base_body.current_base, gs.accepted_fit,
            gs.clear_failure_on_body, garments.body_fit, garment_footwear.body_fit, figure.invalidate,
            gs.garment_fsig)
    gs._garment_kind = lambda item_id: kinds[item_id]
    garments.body_sha256 = lambda name, body: table["sha"] if body == OB else ""
    base_body.current_base = lambda name, **_: ("bsig", "basesha")
    gs.accepted_fit = lambda name, item_id, **_: (
        (Path("/nowhere/item_jacket_0123456789ab.glb"), {"kind": "clothing"}) if table["base_fit"] else None)
    gs.clear_failure_on_body = lambda name, item_id, fsig, body: order.append(("clear", item_id, fsig, body))

    def body_fit(name, item_id, *, body_id, body_sha, base_fit=None, profile=None, build=False):
        order.append(("fit", item_id, body_id, body_sha, build))
        return {"fit": table["fit"], "error": table["error"]}

    garments.body_fit = body_fit
    garment_footwear.body_fit = lambda name, item_id, *, body_id, body_sha, profile, build=False: (
        order.append(("shoe", item_id, body_id, build)) or {"fit": Path("/x.glb"), "error": ""})
    figure.invalidate = lambda *a, **k: order.append(("invalidate",))
    gs.garment_fsig = lambda name, item_id, **_: "shoefsig"
    try:
        out = garments.refit_on_body("Demo", "item_jacket", OB, profile={})
        check("[3a] cleared, fitted with build, then invalidated", order,
              [("clear", "item_jacket", "0123456789ab", OB), ("fit", "item_jacket", OB, "bodysha", True),
               ("invalidate",)])
        check("[3a] the refusal is the result", out,
              {"ok": False, "body": OB, "fsig": "0123456789ab", "error": table["error"]})
        order.clear()
        table.update(fit=Path("/fit.glb"), error="")
        out = garments.refit_on_body("Demo", "item_jacket", OB, profile={})
        check("[3b] accepted", (out["ok"], out["error"]), (True, ""))
        order.clear()
        table["base_fit"] = False
        out = garments.refit_on_body("Demo", "item_jacket", OB, profile={})
        check("[3c] no base fit", (out["ok"], out["error"]), (False, garments.NO_BASE_FIT_TO_DERIVE))
        check("[3c] nothing fitted", [o for o in order if o[0] == "fit"], [])
        table.update(base_fit=True, sha="")
        out = garments.refit_on_body("Demo", "item_jacket", OB, profile={})
        check("[3d] a body no longer stored", out["error"], "The body shape is no longer stored")
        table["sha"] = "bodysha"
        order.clear()
        out = garments.refit_on_body("Demo", "item_shoe", OB, profile={})
        check("[3e] the shoe: its own fsig cleared, then its body fit with build", order,
              [("clear", "item_shoe", "shoefsig", OB), ("shoe", "item_shoe", OB, True), ("invalidate",)])
        check("[3e] accepted", (out["ok"], out["fsig"]), (True, "shoefsig"))
        check("[3] not a body id", raises(lambda: garments.refit_on_body("Demo", "item_jacket", "../x", profile={})))
    finally:
        (gs._garment_kind, garments.body_sha256, base_body.current_base, gs.accepted_fit, gs.clear_failure_on_body,
         garments.body_fit, garment_footwear.body_fit, figure.invalidate, gs.garment_fsig) = real


PLAIN_RECORD = {"metrics": {"sleeve_skin_left_cm2": 1.8, "sleeve_skin_right_cm2": 1.5, "deep_push_share": 0.0085,
                            "torso_tight_share": 0.1614, "scale_retry": 1.08},
                "report": {"arm_light": {"state": "yellow", "sides": {"left": "yellow", "right": "yellow"},
                                         "worst_cm2": 1.8}}}
SHARES = {"front": {"fit": 0.7488, "source": 0.8521}, "side": {"fit": 0.8503, "source": 0.915},
          "back": {"fit": 0.8845, "source": 0.95}}
REFUSAL = ("torso front: 0.75 of the area the source covers is covered within 4 cm (source 0.85, limit -0.1)")
ATTEMPT = {"fsig": "0123456789ab",
           "metrics": {"sleeve_skin_left_cm2": 2.8, "sleeve_skin_right_cm2": 3.5, "deep_push_share": 0.202,
                       "torso_tight_share": 0.1867, "scale_retry": 1.0},
           "report": {"arm_light": {"state": "yellow", "sides": {"left": "yellow", "right": "yellow"},
                                    "worst_cm2": 3.5}},
           "attempt": {"error": REFUSAL, "at": "2026-11-14T19:00:00Z", "glb_sha256": "abc", "marks": {},
                       "gates": {"ok": False, "reasons": [REFUSAL],
                                 "torso": {"ok": False, "failing": ["front"], "reasons": [REFUSAL],
                                           "shares": SHARES}}}}


def test_numbers(tmp: Path) -> None:
    print("[4] each body carries its own numbers; a refused body says why")
    from app.core import fit_attempts as fa, garment_store as gs
    plain = fa.body_numbers(PLAIN_RECORD)
    check("[4a] the plain fit's numbers", plain,
          {"sleeve_skin_left_cm2": 1.8, "sleeve_skin_right_cm2": 1.5, "deep_push_share": 0.0085,
           "torso_tight_share": 0.1614, "scale_retry": 1.08, "torso": None})
    own = fa.body_numbers(ATTEMPT)
    want = {"sleeve_skin_left_cm2": 2.8, "sleeve_skin_right_cm2": 3.5, "deep_push_share": 0.202,
            "torso_tight_share": 0.1867, "scale_retry": 1.0, "torso": SHARES}
    check("[4b] the body's attempt: its own numbers", own, want)
    check("[4b] none of the plain body's", any(own[k] == plain[k] for k in fa.BODY_NUMBER_KEYS), False)
    fitted = {"metrics": dict(ATTEMPT["metrics"]), "frame": {"torso": {"ok": True, "shares": {"front": {
        "fit": 0.8157, "source": 0.8521}, "side": {"fit": 0.9252, "source": 0.915}, "back": {"fit": 0.9988,
                                                                                            "source": 0.95}}}}}
    check("[4c] an accepted body fit: its frame's shares", fa.body_numbers(fitted)["torso"]["front"],
          {"fit": 0.8157, "source": 0.8521})
    check("[4] nothing shown, no numbers", fa.body_numbers({}), {})
    glb = tmp / "attempt.glb"
    glb.write_bytes(b"glTF")
    real = (fa.fit_status, fa.attempt_of, fa.body_label, fa._current, gs.garment_path, gs.read_record)
    fa.fit_status = lambda name, item_id, body, **_: {
        "fsig": "0123456789ab", "state": "outdated", "failure": {"error": REFUSAL}, "body_sha": "s",
        "base_fit_sha": "b"}
    fa.attempt_of = lambda name, item_id, body, slot="": (glb, ATTEMPT, None)
    fa.body_label = lambda *a, **k: "Body shape (T-shirt)"
    fa._current = lambda *a, **k: ""
    gs.garment_path = lambda *a, **k: tmp / "no_fit.glb"
    gs.read_record = lambda path: {}
    try:
        entry = fa._entry("Demo", "item_jacket", OB, {})
        check("[4d] refused", entry["status"], "refused")
        check("[4d] the reason in words", bool(entry["reason"]), True)
        check("[4d] its own numbers", entry["numbers"], want)
        check("[4d] its own arm light", entry["arm_light"], ATTEMPT["report"]["arm_light"])
        check("[4d] the viewer shows the refused attempt", entry["_shown"], (glb, False))
        check("[4d] it may be accepted", entry["can_accept"], True)
    finally:
        fa.fit_status, fa.attempt_of, fa.body_label, fa._current, gs.garment_path, gs.read_record = real


class _Fig:
    def __init__(self, texture: str):
        self.signature, self.bsig, self.shape, self.texture = "sig000000001", "bsig", OB, texture
        self.own, self.left_out, self.in_body, self.painted = ("item_jacket",), (), ("item_shirt",), ()
        self.fit_refused, self.interim, self.notes = {}, {}, {}

    def as_dict(self):
        return {"signature": self.signature, "texture": self.texture}


def _build_tables(bb, tmp: Path) -> dict:
    """Stub [5]'s collaborators on the module ``bb`` (the current or BASELINE's base_body); returns the undo."""
    from app.core import figure as figure_mod, model3d, model_refs, task_queue
    front = tmp / "tpose_sig000000001.png"
    front.write_bytes(b"png")
    saved = {}

    def put(obj, name, value):
        saved[(obj, name)] = getattr(obj, name)
        setattr(obj, name, value)

    put(bb, "_outfit_start", lambda *a, **k: None)
    put(bb, "_outfit_end", lambda *a, **k: None)
    put(bb, "_profile_of", lambda name, profile: {})
    put(bb, "is_base_pipeline", lambda *a, **k: True)
    put(bb, "base_signature", lambda *a, **k: "bsig")
    put(bb, "_snapshot_base_model", lambda *a, **k: {"rigged": "b.glb", "unrigged": "bu.glb"})
    put(bb, "dressed_image", lambda name, view, sig, bsig, **k: front if view == "front" else None)
    put(bb, "_ref_sidecar", lambda path: {"dressed": True, "base_signature": OB})
    put(bb, "_worn_profile", lambda profile, pieces, items: {})
    put(bb, "figure_texts", lambda *a, **k: {})
    put(bb, "_snapshot_shape", lambda *a, **k: {"rigged": "r.glb", "unrigged": "u.glb"})
    put(bb, "_sync_texture_views", lambda *a, **k: None)
    put(bb, "texture_view_shas", lambda *a, **k: {})
    put(bb, "_build_on_shape", lambda *a, **k: {"ok": True, "on_shape": True})
    put(model_refs, "find_ref_image", lambda *a, **k: front)
    put(model3d, "_ref_manifest", lambda path: {"pieces": {"outer": "item_jacket"}, "items": []})
    put(figure_mod, "delivered_figure", lambda *a, **k: _Fig(""))
    put(figure_mod, "predicted_variant", lambda *a, **k: "rigged")
    put(figure_mod, "worn_sets", lambda *a, **k: None)
    put(task_queue, "get_task_queue", lambda: types.SimpleNamespace(track_start=lambda *a, **k: "",
                                                                     track_finish=lambda *a, **k: None))
    return saved


def _undo(saved: dict) -> None:
    for (obj, name), value in saved.items():
        setattr(obj, name, value)


def test_assemble(tmp: Path) -> None:
    print("[5] a figure that paints nothing assembles without the texture store")
    from app.core import base_body as bb, model_refs
    saved = _build_tables(bb, tmp)
    try:
        out = bb.build_outfit_model("Demo", "sig000000001")
        check("[5] the shape itself, no error", out, {"ok": True, "on_shape": True})
    finally:
        _undo(saved)
    # dressed_image: the view's dressed flag must agree with whether the figure paints anything
    view = tmp / "tpose_sig000000002.png"
    view.write_bytes(b"png")
    meta = {"base_signature": OB, "base_image_sha256": "viewsha", "dressed": True}
    saved = {}
    for obj, name, value in ((model_refs, "find_ref_image", lambda *a, **k: view),
                             (bb, "dressed_views", lambda: ("front", "back")),
                             (bb, "_ref_sidecar", lambda path: dict(meta)),
                             (bb, "file_sha256", lambda path: "viewsha"),
                             (bb, "mesh_items_unpainted", lambda m: ["item_jacket"])):
        saved[(obj, name)] = getattr(obj, name)
        setattr(obj, name, value)
    try:
        check("[5] dressed view, figure paints nothing -> None",
              bb.dressed_image("Demo", "front", "sig000000002", "bsig", fig=_Fig("")), None)
        check("[5] dressed view, painted figure -> the view",
              bb.dressed_image("Demo", "front", "sig000000002", "bsig", fig=_Fig("tex0123456789ab")), view)
        meta["dressed"] = False
        check("[5] undressed view, figure paints nothing -> the view",
              bb.dressed_image("Demo", "front", "sig000000002", "bsig", fig=_Fig("")), view)
        check("[5] undressed view, painted figure -> None",
              bb.dressed_image("Demo", "front", "sig000000002", "bsig", fig=_Fig("tex0123456789ab")), None)
    finally:
        _undo(saved)


def _old(path: str) -> str:
    res = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:{path}"], capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else ""


def _params(src: str, func: str) -> list:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return [a.arg for a in node.args.args + node.args.kwonlyargs]
    return []


def test_old_code(tmp: Path) -> None:
    print(f"[6] fails on the old code ({BASELINE})")
    src = _old("app/core/base_body.py")
    check(f"[6] {BASELINE}: base_body.py readable", bool(src))
    if src:
        old = types.ModuleType("base_body_baseline")
        old.__package__ = "app.core"
        old.__file__ = str(ROOT / "app/core/base_body.py")
        exec(compile(src, "base_body_baseline", "exec"), old.__dict__)
        saved = _build_tables(old, tmp)
        try:
            out = old.build_outfit_model("Demo", "sig000000001")
        finally:
            _undo(saved)
        check(f"[6] {BASELINE}: the same assembly raised the empty texture signature", out,
              {"ok": False, "error": "not a texture signature: ''"})
    garments_src = _old("app/core/garments.py")
    check(f"[6] {BASELINE}: no refit_on_body", bool(garments_src) and "def refit_on_body" not in garments_src)
    check(f"[6] {BASELINE}: start_garment takes no body", "body" in _params(garments_src, "start_garment"), False)
    routes = _old("app/routes/characters.py")
    run_request = routes[routes.find("class GarmentRunRequest"):routes.find("class GarmentMeshFetchRequest")]
    check(f"[6] {BASELINE}: the run request has no body", bool(run_request) and "body:" not in run_request)
    attempts = _old("app/core/fit_attempts.py")
    check(f"[6] {BASELINE}: no body_numbers", bool(attempts) and "def body_numbers" not in attempts)
    fig = _old("app/core/figure.py")
    check(f"[6] {BASELINE}: a refused piece was keyed as painted",
          "own={item_id: sets.own[item_id] for item_id in own})" in fig)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="refit-selected-body-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        paths.init_instance(Path(tmp) / "instance")
        test_check_body_run()
        test_execute()
        test_refit_on_body()
        test_numbers(Path(tmp))
        test_assemble(Path(tmp))
        test_old_code(Path(tmp))
    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
