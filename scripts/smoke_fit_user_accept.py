#!/usr/bin/env python3
"""Ruling A31 (plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``): the last refused fit of a piece
is kept per (item, body), shown per body in the Details preview, and an admin may ACCEPT it — then it counts as
accepted everywhere until its fit, its body or the fit version changes, or the acceptance is undone.

Usage:
    ./.venv/bin/python scripts/smoke_fit_user_accept.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no GPU, no server, no Blender (the
distance tier's ``refine.decimate_to`` copies the file). The resolver (``figure._delivered``), the plan
(``figure_build.plan`` / ``cost``), ``_run_assemble``, ``_worn_rows``, ``garments.body_fit`` (the real usable
rule, on files written here), ``garment_store`` (paths, records, failures) and ``fit_attempts`` are real; the rest
are the tables of ``scripts/smoke_figure_fit_refused.py``: ``inventory.get_item`` serves ITEMS, ``base_body``
answers BSIG / "basesha" / the dress text of the visible ids, ``figure.stored_shape`` a sidecar for every key,
``garment_store.accepted_fit`` the jacket's base fit ``garments/jacket_<FSIG>.glb`` (a file written here),
``garments.body_sha256`` -> BODY["sha"], ``model3d.find_model3d`` -> MODEL for the worn signature,
``find_model3d_serving`` -> that model ("nearest"), ``_read_sidecar`` -> MODEL["meta"].

Fixture: "Demo", items blouse [top] IN THE BODY, jacket [outer] own mesh. The wanted figure: shape SB = the shape
of {blouse} (stored, meshed), own (jacket,). The model of the worn outfit was built BEFORE as Fb = the wanted
figure with the jacket left out (own (), left_out {jacket}) — the figure that stays shown while the jacket's fit
on SB is refused. The jacket's base fit is accepted (sha BSHA of its bytes "base-fit-1"); its fit on SB was
refused: the failure record E = "fit on the outfit body refused — left leg: off the thigh — 0.1478 of its
vertices beyond the limb + 4 cm (source 0.0, limit +0.1)" on (body "bodysha", base fit BSHA, fit version FV), and
the attempt kept by ``fit_attempts.store`` (GLB bytes "attempt-A", 3 limb marks).

Expected, derived by hand from Ruling A31:

[1] Refused: ``figure._fit_on`` -> (False, E); delivered = Fb, kept, fit_refused {jacket: E}; the automatic plan
    has no assemble step (Ruling A23 b holds a refusal); ``_run_assemble`` -> "Not assembled: Jacket fit the plain
    body but not the body shape (Blouse). The figure built before stays shown."; the worn row: state
    "fit_refused", fit_refused "the left trouser leg stands off the thigh (15 % of it more than 4 cm from it)"
    (0.1478 -> 15 %), refused_on "Blouse", piece_broken False, regenerate_jobs None (a body problem: no new mesh
    offered). The attempt files: ``bodies/SB/attempts/jacket_<FSIG>.{glb,json,npz}``. ``bodies`` -> two entries:
    "Plain body" accepted, "Body shape (Blouse)" refused with that plain reason, the limb mark count 3,
    can_accept True, a model url.
[2] Non-admin: POST …/fits/SB/accept as a user -> 403 and nothing changes (the failure record stays).
[3] Accept (admin, route): 200; the fit path now holds "attempt-A" with ``accepted`` True and ``user_accepted``
    (attempt sha = sha256("attempt-A")); the failure record is gone; ``_fit_on`` -> (True, ""); delivered on SB,
    own (jacket,), fit_refused {}; the estimate (``follow_up`` = ``figure_build.cost``): hub_jobs 0, steps
    [("assemble", "Assemble the figure", 0)] — the re-assembly, CPU only; ``bodies``: SB "user_accepted" with the
    reason; the worn row "ready" with accepted_by_user.on "Body shape (Blouse)". Accepting again is a no-op (200).
[4] Changed base fit (its bytes "base-fit-2"): the accepted fit is void — ``body_fit`` serves nothing from it
    (fit None), ``bodies`` no longer says "user_accepted" — "stale" (the kept attempt was made from the old base
    fit: nothing to accept, ``can_accept`` False); bytes back -> it holds again.
[5] Changed body (BODY["sha"] "bodysha2"): void — fit None; back -> holds.
[6] Changed fit version (record fit_version FV - 1): ``body_fit`` fit None (``body_fit_state`` stale); back -> holds.
[7] Undo (route): 200; the fit path is empty (nothing was displaced), the failure record E is back; ``_fit_on``
    -> (False, E) again; delivered kept Fb.
[8] A new attempt with OTHER bytes after a re-accept undoes the acceptance by itself (the failure back); the
    same bytes keep it.
[9] A gate-accepted fit drops the attempt (``fit_attempts.drop``): no attempt files left.
"""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
BSIG = "base0123abcd"
FSIG = "0123456789ab"
E = ("fit on the outfit body refused — left leg: off the thigh — 0.1478 of its vertices beyond the limb + 4 cm "
     "(source 0.0, limit +0.1)")
GATES = {"ok": False, "reasons": [E.split(" — ", 1)[1]],
         "limbs": {"ok": False, "failing": [["left_leg", 0]], "fit": {"left_leg": {"off": [0.1478, 0.0]}},
                   "source": {"left_leg": {"off": [0.0, 0.0]}}}}
PLAIN = "the left trouser leg stands off the thigh (15 % of it more than 4 cm from it)"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def _item(item_id, slots, mode, **extra):
    return {"id": item_id, "name": item_id.title(), "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode, **extra}}


ITEMS = {"blouse": _item("blouse", ["top"], "in_body"),
         "jacket": _item("jacket", ["outer"], "own_mesh"),
         "hair_body": {"id": "hair_body", "name": "Short hair", "category": "garment", "owner": "Demo",
                       "garment": {"kind": "hair", "mesh_mode": "body", "description": "short hair"}}}
W = {"top": "blouse", "outer": "jacket"}
MODEL = {"sig": None, "path": None, "meta": None}
BODY = {"sha": "bodysha"}


def profile():
    return {"model_pipeline": "base_body", "base_hairstyle": "hair_body", "equipped_pieces": dict(W),
            "equipped_mesh_pieces": {"hair": "hair_body"}, "equipped_items": []}


def stub_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=(), **_kw):
    meshed = {str(i) for i in mesh_items or ()}
    visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
    return ("wear:" + "+".join(visible)) if visible else ""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fit-user-accept-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")

        import numpy as np
        from app.blender import refine
        from app.core import (base_body, figure, figure_build, fit_attempts, garment_fit, garment_refit,
                              garment_store as gs, garments, model3d, model_refs, motion_item_cache)
        from app.models import character as character_model, inventory
        character_model.get_character_dir("Demo", create=True)
        inventory.get_item = lambda item_id, **_kw: copy.deepcopy(ITEMS.get(str(item_id)))
        motion_item_cache.item_snapshot = lambda **_kw: copy.deepcopy(ITEMS)
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.base_signature = lambda *_a, **_kw: BSIG
        base_body.base_model_sha256 = lambda *_a, **_kw: "basesha"
        base_body.current_base = lambda *_a, **_kw: (BSIG, "basesha")
        base_body.dress_text = stub_dress_text
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
        figure.stored_shape = lambda _c, key, **_kw: {"outfit_body": {"body_id": key}}
        FV = garment_fit.FIT_VERSION["clothing"]

        base_fit = gs.garment_path("Demo", "jacket", FSIG, "fit")
        base_fit.parent.mkdir(parents=True, exist_ok=True)
        base_fit.write_bytes(b"base-fit-1")
        prepared = gs.garment_path("Demo", "jacket", FSIG, "prepared")
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_bytes(b"prepared")
        gs.write_record(base_fit.with_suffix(".json"), {
            "accepted": True, "kind": "clothing", "item_id": "jacket", "fsig": FSIG, "fit_version": FV,
            "base_signature": BSIG, "base_model_sha256": "basesha", "body_id": BSIG, "body_sha256": "basesha",
            "inputs": {"prepared_sha256": sha(b"prepared")}})
        BSHA = sha(b"base-fit-1")
        gs.accepted_fit = (lambda _c, item_id, **_kw:
                           (base_fit, gs.read_record(base_fit.with_suffix(".json"))) if item_id == "jacket" else None)
        gs.garment_fsig = lambda *_a, **_kw: FSIG
        garments.body_sha256 = lambda *_a, **_kw: BODY["sha"]
        garments.cached_failure = lambda *_a, **_kw: None
        garments.run_estimate = lambda *_a, **_kw: {"hub_jobs": 0, "steps": [], "note": ""}
        garment_refit.work_count = lambda *_a, **_kw: 0
        model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "rig"]
        model3d.find_model3d = (lambda _c, sig=None, **_kw:
                                MODEL["path"] if sig is not None and sig == MODEL["sig"] else None)
        model3d.find_model3d_serving = lambda *_a, **_kw: (MODEL["path"], "nearest" if MODEL["path"] else "")
        model3d._read_sidecar = lambda _p: copy.deepcopy(MODEL["meta"] or {})
        figure_build._read_profile = lambda _c: profile()
        figure_build.base_step_in_flight = lambda *_a, **_kw: ""
        figure_build._tracked = lambda *_a, **_kw: (None, "")
        character_model.get_character_profile = lambda *_a, **_kw: profile()
        from app.core import garment_footwear
        garment_footwear.stored_outfit_bodies = lambda _c: [SB]

        def decimate(src, _target, low, *, tris=None):
            shutil.copyfile(src, low)
            return {"ok": True, "tris": tris, "ratio": 1.0}
        refine.decimate_to = decimate

        def delivered():
            figure.invalidate()
            return figure._delivered("Demo", profile=profile())

        wanted, _ = delivered()
        SB = wanted.shape
        model_refs.current_outfit_state = lambda _c: (dict(W), [], wanted.signature)
        built = {**wanted.as_dict(), "own": [], "left_out": {"jacket": "Fit refused — earlier"}}
        MODEL.update(sig=wanted.signature, path=root / "model.glb", meta={"figure": built})
        check("wanted: shape of {blouse}, the jacket own", (figure.is_plain(SB), wanted.in_body, wanted.own),
              (False, ("blouse",), ("jacket",)))

        print("[1] the jacket's fit on SB refused, its attempt kept")
        gs.record_body_failure("Demo", "jacket", FSIG, SB, error=E, body_sha="bodysha", base_fit_sha=BSHA,
                               fit_version=FV)
        attempt_glb = root / "attempt.glb"
        attempt_glb.write_bytes(b"attempt-A")
        mark = {"positions": np.zeros((3, 3)), "joints": np.zeros((3, 4), np.int64),
                "weights": np.tile([1.0, 0, 0, 0], (3, 1)), "joint_names": ["Hips"]}
        record = {"kind": "clothing", "item_id": "jacket", "fsig": FSIG, "body_id": SB, "body_sha256": "bodysha",
                  "base_fit_sha256": BSHA, "base_signature": BSIG, "fit_version": FV}

        def store(data: bytes):
            attempt_glb.write_bytes(data)
            fit_attempts.store("Demo", "jacket", FSIG, body=SB, kind="clothing", record=dict(record), error=E,
                               gates=GATES, glb=attempt_glb, tris=10, marks={"limb": mark})
        store(b"attempt-A")
        folder = gs.body_root("Demo", SB) / "attempts"
        check("attempt files", sorted(p.name for p in folder.iterdir() if p.is_file()),
              [f"jacket_{FSIG}.glb", f"jacket_{FSIG}.json", f"jacket_{FSIG}.npz"])
        check("_fit_on: refused", figure._fit_on("Demo", "jacket", shape=SB, base_sha="basesha", profile=profile()),
              (False, E))
        _w, got = delivered()
        check("delivered: the figure built before, kept", (got.kept, got.own, got.fit_refused, got.fit_refused_on),
              (True, (), {"jacket": E}, SB))
        auto = [s.name for s in figure_build._runnable(figure_build.plan("Demo", profile=profile(), explicit=False),
                                                       False)]
        check("automatic plan: no assemble", "assemble" in auto, False)
        check("assemble refuses", figure_build._run_assemble("Demo", None),
              "Not assembled: Jacket fit the plain body but not the body shape (Blouse). The figure built before "
              "stays shown.")
        wanted_now, got = delivered()
        row = [r for r in figure_build._worn_rows("Demo", wanted_now, got, {}, False, profile())
               if r["item_id"] == "jacket"][0]
        check("worn row", (row["state"], row["fit_refused"], row["refused_on"], row["piece_broken"],
                           row["regenerate_jobs"]),
              ("fit_refused", PLAIN, "Blouse", False, None))
        entries = fit_attempts.bodies("Demo", "jacket", profile=profile())
        check("bodies", [(e["key"], e["label"], e["status"], e["reason"], [m["count"] for m in e["marks"]],
                          e["can_accept"], bool(e["url"])) for e in entries],
              [("plain", "Plain body", "accepted", "", [], False, True),
               (SB, "Body shape (Blouse)", "refused", PLAIN, [3], True, True)])

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes import characters as characters_route
        app = FastAPI()
        app.include_router(characters_route.router)
        client = TestClient(app)
        failure_path = gs.garment_path("Demo", "jacket", FSIG, "failed", body=SB)
        fit_path = gs.garment_path("Demo", "jacket", FSIG, "fit", body=SB)

        print("[2] a non-admin cannot accept")
        auth_dependency.get_current_user = lambda _r: {"role": "user", "username": "demo"}
        res = client.post(f"/characters/Demo/garments/jacket/fits/{SB}/accept")
        check("403", (res.status_code, failure_path.is_file(), fit_path.is_file()), (403, True, False))
        res = client.post(f"/characters/Demo/garments/jacket/fits/{SB}/unaccept")
        check("403 undo", res.status_code, 403)

        print("[3] accept")
        auth_dependency.get_current_user = lambda _r: {"role": "admin", "username": "demo"}
        res = client.post(f"/characters/Demo/garments/jacket/fits/{SB}/accept")
        body = res.json() if res.status_code == 200 else {}
        published = gs.read_record(fit_path.with_suffix(".json"))
        check("200, published", (res.status_code, fit_path.read_bytes() if fit_path.is_file() else None,
                                 published.get("accepted"),
                                 (published.get("user_accepted") or {}).get("attempt_sha256"),
                                 failure_path.is_file()),
              (200, b"attempt-A", True, sha(b"attempt-A"), False))
        check("_fit_on: fitted", figure._fit_on("Demo", "jacket", shape=SB, base_sha="basesha", profile=profile()),
              (True, ""))
        _w, got = delivered()
        check("delivered: on SB with the jacket", (got.shape, got.own, got.fit_refused, got.kept),
              (SB, ("jacket",), {}, False))
        follow = body.get("follow_up") or {}
        check("estimate: the re-assembly, CPU only",
              (follow.get("hub_jobs"), [(s["name"], s["label"], s["jobs"]) for s in follow.get("steps") or []]),
              (0, [("assemble", "Assemble the figure", 0)]))
        entries = {e["key"]: e for e in fit_attempts.bodies("Demo", "jacket", profile=profile())}
        check("bodies: accepted by you", (entries[SB]["status"], entries[SB]["reason"], entries[SB]["can_accept"]),
              ("user_accepted", PLAIN, False))
        wanted_now, got = delivered()
        row = [r for r in figure_build._worn_rows("Demo", wanted_now, got, {}, False, profile())
               if r["item_id"] == "jacket"][0]
        check("worn row: ready, accepted by you", (row["state"], (row["accepted_by_user"] or {}).get("on"),
                                                    (row["accepted_by_user"] or {}).get("reason")),
              ("ready", "Body shape (Blouse)", PLAIN))
        res = client.post(f"/characters/Demo/garments/jacket/fits/{SB}/accept")
        check("accept again: no-op", (res.status_code, fit_path.read_bytes()), (200, b"attempt-A"))

        def served():
            return garments.body_fit("Demo", "jacket", body_id=SB, body_sha=BODY["sha"],
                                     base_fit=gs.accepted_fit("Demo", "jacket"), profile=profile())["fit"]

        print("[4] a changed base fit voids it")
        base_fit.write_bytes(b"base-fit-2")
        entries = {e["key"]: e for e in fit_attempts.bodies("Demo", "jacket", profile=profile())}
        check("void", (served(), entries[SB]["status"], entries[SB]["can_accept"]), (None, "stale", False))
        base_fit.write_bytes(b"base-fit-1")
        check("back: holds", served(), fit_path)

        print("[5] a changed body voids it")
        BODY["sha"] = "bodysha2"
        check("void", served(), None)
        BODY["sha"] = "bodysha"
        check("back: holds", served(), fit_path)

        print("[6] a changed fit version voids it")
        rec = gs.read_record(fit_path.with_suffix(".json"))
        gs.write_record(fit_path.with_suffix(".json"), {**rec, "fit_version": FV - 1})
        check("void", served(), None)
        gs.write_record(fit_path.with_suffix(".json"), rec)
        check("back: holds", served(), fit_path)

        print("[7] undo")
        res = client.post(f"/characters/Demo/garments/jacket/fits/{SB}/unaccept")
        check("200, the refusal back", (res.status_code, fit_path.is_file(),
                                        gs.read_record(failure_path).get("error")), (200, False, E))
        check("_fit_on: refused again",
              figure._fit_on("Demo", "jacket", shape=SB, base_sha="basesha", profile=profile()), (False, E))
        _w, got = delivered()
        check("delivered: kept again", (got.kept, got.fit_refused), (True, {"jacket": E}))
        res = client.post(f"/characters/Demo/garments/jacket/fits/{SB}/unaccept")
        check("undo again: 409", res.status_code, 409)

        print("[8] a new attempt: other bytes undo the acceptance, the same keep it")
        client.post(f"/characters/Demo/garments/jacket/fits/{SB}/accept")
        store(b"attempt-A")
        check("same bytes: still accepted", (fit_path.is_file(), failure_path.is_file()), (True, False))
        store(b"attempt-B")
        check("other bytes: undone", (fit_path.is_file(), gs.read_record(failure_path).get("error")), (False, E))

        print("[9] a gate-accepted fit drops the attempt")
        fit_attempts.drop("Demo", "jacket", body=SB)
        check("no attempt files", sorted(p.name for p in folder.rglob("*") if p.is_file()), [])
        json.dumps(entries[SB])  # the payload is JSON

    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
