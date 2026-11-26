#!/usr/bin/env python3
"""Smoke: "Accept anyway" of a refused footwear source step (2026-11-25, ``footwear_source.accept_step`` /
``undo_accept_step``, the routes ``POST /characters/{c}/garments/{item}/footwear/steps/{step}/accept|unaccept``).

Usage:  ./.venv/bin/python scripts/smoke_footwear_accept_anyway.py

Temp storage (``paths.init`` before any world module), no world DB rows, no hub, no Blender: the source folder is
written by hand — the source, empty, cut-out and mesh steps accepted with their files, ``raw.glb`` = ``prepared.glb``
and the mesh record's ``prepared_sha256`` = its hash, so the insole step measures the file as it is (no decimation).

Expected, by hand:

[A1] The insole of ``wedge(shaft=0.26, open_side=True)`` (scripts/smoke_footwear_insole.py [I11]: the +z shaft wall
     stays at the pump's height, so above the sole's end face every slab is open, closed_share 0) is refused:
     run_source(steps ["insole"], force) -> {ok False, step "insole", failure "gate"}, the insole record accepted
     False, failure "gate", gates.refusal = footwear_insole.SHAFT_OPEN_REFUSED, step_done False.
[A2] accept_step(item, "mesh") -> ValueError (the mesh is accepted: nothing to accept); accept_step(item, "cutout")
     -> ValueError (no gate: not in ACCEPTABLE_STEPS = (empty, mesh, insole)); undo_accept_step(item, "insole")
     -> ValueError (not accepted by the user).
[A3] accept_step(item, "insole") -> the record accepted True, no ``failure``, gates unchanged (refusal
     SHAFT_OPEN_REFUSED), user_accepted {ssig = the current ssig, reasons = the refused gates' reasons (same list),
     error non-empty, no ``carried``}; step_done True; prepared.glb byte-identical (no cap: the open wedge has none).
[A4] The same refusal again (run_source insole, force — what a new INSOLE_VERSION does): fit_attempts.carries —
     same gates, none worse -> the record stays accepted, user_accepted.carried.from = the first acceptance's ``at``.
[A5] undo_accept_step(item, "insole") -> accepted False, failure "gate", error = the acceptance's error, no
     user_accepted; step_done False; a second undo -> ValueError.
[A6] Accept again, then a DIFFERENT refusal (``wedge(solid=True)``: STRAPLESS_REFUSED, strap_share 0 < 0.08 —
     another gate than shaft_closed_share) -> not carried:
     run_source -> ok False, accepted False, no user_accepted.
[A7] The empty shoe: the empty record refused (failure gate, attempts [1, 2], empty.try1.png / empty.try2.png kept,
     no empty.png) -> accept_step(item, "empty"): empty.png == the bytes of empty.try2.png (the LAST kept attempt),
     record accepted True, attempt 2, user_accepted.reasons = attempt 2's; the later steps' records and outputs
     (cutout.png, prepared.glb, insole.json) are gone (the chain runs them from it). Undo -> empty.png gone, refused.
[A7b] garments.cached_failure (what a Build and every automatic trigger honour): a persisted failure of another
     wearer at step "insole" (garment_store.chain_failure, faked) blocks while the insole is refused (-> the failure)
     and no longer once the step is accepted by the user (-> None; the source is one per item).
[A8] The three routes are registered under /characters and each carries ``require_admin`` (a player is refused
     before the core runs): manual, steps/{step}/accept, steps/{step}/unaccept.
"""
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAILS.append(label)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        (root / "world" / "config.json").write_text("{}", encoding="utf-8")
        (root / "instance" / "config.json").write_text("{}", encoding="utf-8")
        config.load(root / "world" / "config.json", root / "instance" / "config.json")
        import _footwear_fixtures as fx
        from app.core import footwear_insole as fi
        from app.core import footwear_source as fs
        from app.core import glb_mesh
        from app.core.garment_store import read_record

        img = root / "shoe.png"
        Image.new("RGB", (64, 32), (90, 60, 40)).save(img)
        iid = "shoe_acc"

        def png(color) -> bytes:
            buf = io.BytesIO()
            Image.new("RGB", (16, 16), color).save(buf, format="PNG")
            return buf.getvalue()

        with patch("app.models.inventory.get_item_image_path", lambda i: str(img) if i == iid else ""):
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True)

            def put_mesh(P, F):
                blob = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
                (d / "raw.glb").write_bytes(blob)
                (d / "prepared.glb").write_bytes(blob)
                fs._set_step(d, "mesh", fs._entry(accepted=True, gates={"ok": True, "reasons": []},
                                                  prepared_sha256=sha(blob)))
                return blob

            (d / "upscaled.png").write_bytes(png((1, 1, 1)))
            (d / "empty.png").write_bytes(png((2, 2, 2)))
            (d / "cutout.png").write_bytes(png((3, 3, 3)))
            for step in ("source", "empty", "cutout"):
                fs._set_step(d, step, fs._entry(accepted=True, gates={"ok": True, "reasons": []}))
            blob = put_mesh(*fx.wedge(shaft=0.26, open_side=True))

            print("[A1] the open-sided boot's insole is refused")
            res = fs.run_source(iid, steps=["insole"], force=True)
            rec = fs.step_record(iid, ssig, "insole")
            check("A1 run", (res.get("ok"), res.get("step"), res.get("failure")), (False, "insole", fs.GATE))
            check("A1 record", (rec.get("accepted"), rec.get("failure"), (rec.get("gates") or {}).get("refusal")),
                  (False, fs.GATE, fi.SHAFT_OPEN_REFUSED))
            check("A1 step_done", fs.step_done(iid, ssig, "insole"), False)
            refused_reasons = list((rec.get("gates") or {}).get("reasons") or [])
            check("A1 reasons named", bool(refused_reasons), True)

            print("[A2] nothing to accept / undo")
            for label, call in (("A2 mesh accepted: nothing to accept", lambda: fs.accept_step(iid, "mesh")),
                                ("A2 cutout has no gate", lambda: fs.accept_step(iid, "cutout")),
                                ("A2 undo without acceptance", lambda: fs.undo_accept_step(iid, "insole"))):
                try:
                    call()
                    check(label, "no error", "ValueError")
                except ValueError:
                    check(label, "ValueError", "ValueError")

            print("[A3] accept the insole anyway")
            out = fs.accept_step(iid, "insole")
            rec = fs.step_record(iid, ssig, "insole")
            ua = rec.get("user_accepted") or {}
            check("A3 record", (rec.get("accepted"), "failure" in rec, (rec.get("gates") or {}).get("refusal")),
                  (True, False, fi.SHAFT_OPEN_REFUSED))
            check("A3 user_accepted", (ua.get("ssig"), ua.get("reasons"), bool(ua.get("error")), "carried" in ua),
                  (ssig, refused_reasons, True, False))
            check("A3 answer", (out.get("ssig"), out.get("step"), (out.get("user_accepted") or {}).get("at")),
                  (ssig, "insole", ua.get("at")))
            check("A3 step_done", fs.step_done(iid, ssig, "insole"), True)
            check("A3 prepared.glb unchanged", (d / "prepared.glb").read_bytes() == blob, True)
            first_at = ua.get("at")

            print("[A4] the same refusal again: the acceptance carries over")
            res = fs.run_source(iid, steps=["insole"], force=True)
            rec = fs.step_record(iid, ssig, "insole")
            check("A4 run ok", (res.get("ok"), res.get("ran")), (True, ["insole"]))
            check("A4 carried", (rec.get("accepted"), ((rec.get("user_accepted") or {}).get("carried") or {}).get("from")),
                  (True, first_at))

            print("[A5] undo")
            fs.undo_accept_step(iid, "insole")
            rec = fs.step_record(iid, ssig, "insole")
            check("A5 record", (rec.get("accepted"), rec.get("failure"), "user_accepted" in rec, bool(rec.get("error"))),
                  (False, fs.GATE, False, True))
            check("A5 step_done", fs.step_done(iid, ssig, "insole"), False)
            try:
                fs.undo_accept_step(iid, "insole")
                check("A5 second undo", "no error", "ValueError")
            except ValueError:
                check("A5 second undo", "ValueError", "ValueError")

            print("[A6] another refusal is not carried")
            fs.accept_step(iid, "insole")
            put_mesh(*fx.wedge(solid=True))
            res = fs.run_source(iid, steps=["insole"], force=True)
            rec = fs.step_record(iid, ssig, "insole")
            check("A6 refused, not carried", (res.get("ok"), rec.get("accepted"), "user_accepted" in rec,
                                              (rec.get("gates") or {}).get("refusal")),
                  (False, False, False, fi.STRAPLESS_REFUSED))

            print("[A7] the empty shoe: the last kept attempt")
            (d / "empty.png").unlink()
            try1, try2 = png((10, 20, 30)), png((40, 50, 60))
            (d / "empty.try1.png").write_bytes(try1)
            (d / "empty.try2.png").write_bytes(try2)
            a1 = {"attempt": 1, "ok": False, "gates": {"ok": False, "reasons": ["leg: one"]}}
            a2 = {"attempt": 2, "ok": False, "gates": {"ok": False, "reasons": ["leg: two"]}}
            fs._set_step(d, "empty", fs._entry(accepted=False, gates=a2["gates"], attempts=[a1, a2],
                                               failure=fs.GATE, error="empty shoe refused after 2 attempts"))
            fs.accept_step(iid, "empty")
            rec = fs.step_record(iid, ssig, "empty")
            check("A7 empty.png = try 2", (d / "empty.png").read_bytes() == try2, True)
            check("A7 record", (rec.get("accepted"), rec.get("attempt"), (rec.get("user_accepted") or {}).get("reasons")),
                  (True, 2, ["leg: two"]))
            steps = read_record(d / "record.json").get("steps") or {}
            check("A7 later steps gone", (sorted(steps), (d / "cutout.png").exists(), (d / "prepared.glb").exists(),
                                          (d / "insole.json").exists()),
                  (["empty", "source"], False, False, False))
            fs.undo_accept_step(iid, "empty")
            rec = fs.step_record(iid, ssig, "empty")
            check("A7 undo", ((d / "empty.png").exists(), rec.get("accepted"), rec.get("failure")),
                  (False, False, fs.GATE))

            print("[A7b] a Build honours the acceptance")
            from app.core import garments
            for step in ("source", "empty", "cutout"):
                (d / fs._STEP_FILES[step][0]).write_bytes(png((5, 5, 5)))
                fs._set_step(d, step, fs._entry(accepted=True, gates={"ok": True, "reasons": []}))
            put_mesh(*fx.wedge(shaft=0.26, open_side=True))
            fs.run_source(iid, steps=["insole"], force=True)
            persisted = {"item_id": iid, "fsig": "f" * 12, "step": "insole", "error": "insole refused"}
            with patch("app.core.garment_store.garment_fsig", lambda *a, **k: "f" * 12), \
                 patch("app.core.garment_store.chain_failure", lambda *a, **k: dict(persisted)), \
                 patch("app.core.base_body.current_base", lambda *a, **k: ("b", "s")), \
                 patch.object(garments, "_item", lambda c, i: ({}, garments._footwear())), \
                 patch.object(garments, "_rejudge_pending", lambda *a, **k: False):
                blocked = (garments.cached_failure("Other", iid) or {}).get("step")
                fs.accept_step(iid, "insole")
                after = garments.cached_failure("Other", iid)
            check("A7b refused: blocks, accepted: free", (blocked, after), ("insole", None))

        print("[A8] the routes are admin-only")
        os.environ.setdefault("STORAGE_DIR", str(root / "world"))
        os.environ.setdefault("INSTANCE_DIR", str(root / "instance"))
        from app.core.auth_dependency import require_admin
        from app.routes import characters

        def admin_only(path_end: str) -> bool:
            for r in characters.router.routes:
                if getattr(r, "path", "").endswith(path_end):
                    return any(dep.call is require_admin for dep in r.dependant.dependencies)
            return False
        check("A8 routes", [admin_only(p) for p in ("/footwear/manual", "/footwear/steps/{step}/accept",
                                                     "/footwear/steps/{step}/unaccept")], [True, True, True])

    print()
    print(f"{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
