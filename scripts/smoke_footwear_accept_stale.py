#!/usr/bin/env python3
"""Smoke: "Accept anyway" of a shoe source step whose record an OLDER analysis made (2026-11-26 review: Kai's
Sneekers — the insole refused under analysis version 10 while ``footwear_insole.INSOLE_VERSION`` is 11; the accept
answered 200, the chain then ran from the fit and failed "The shoe source is not ready", and that failure was cached).

Usage:  ./.venv/bin/python scripts/smoke_footwear_accept_stale.py

Temp storage (``paths.init`` before any world module), no world DB rows, no hub, no Blender. The source folder is
written by hand as in ``scripts/smoke_footwear_accept_anyway.py`` (source / empty / cut-out / mesh accepted with their
files, ``raw.glb`` = ``prepared.glb`` and the mesh record's ``prepared_sha256`` its hash, so the insole step measures
the file as it is). The character folder exists (``_require_character``); the item counts as the character's
footwear piece (``garments._item`` patched, as in that smoke). The accept goes through the ROUTE function
``routes.characters.accept_character_footwear_step``; the chain through ``garment_footwear.run_chain`` with the
step ``fit`` (what the UI sends after an acceptance: ``{step: fit, force, chain}``). The fit itself is replaced by a
stand-in that does exactly the real fit's first check — ``garment_footwear.source_ready`` or
``base_body.MissingInput(SOURCE_NOT_READY)`` — and records that it was reached (a real fit needs a rigged body).

OLD = ``footwear_insole.INSOLE_VERSION - 1`` (an insole record of the analysis before the current one).

Expected, by hand:

[S1] The open-sided boot ``wedge(shaft=0.26, open_side=True)`` (smoke_footwear_accept_anyway [A1]) is refused by the
     insole step; its record is then stamped ``version`` OLD — the state of Kai's Sneekers. ``garment_footwear.
     step_done(item, "insole")`` False (refused), ``footwear_source.stale_record("insole", record)`` True.
[S2] The accept ROUTE answers ``remeasured`` True with ``user_accepted`` set (the current analysis refuses the boot
     again, for the same SHAFT_OPEN_REFUSED): the insole record has ``version`` = INSOLE_VERSION, accepted True,
     ``user_accepted.reasons`` = the FRESH record's reasons; ``garment_footwear.step_done(item, "insole")`` True and
     ``source_ready`` True. (Before the fix the acceptance kept ``version`` OLD: step_done False, the fit refused
     "The shoe source is not ready".)
[S3] ``run_chain(c, item, ["fit"], force=True)`` reaches the fit with the source ready: ``{ok True, ran ["fit"]}``,
     the stand-in saw source_ready True.
[S4] The re-measure PASSES: the closed pump ``wedge()`` (smoke_footwear_insole: gates ok) under an insole record
     refused with ``failure`` gate and ``version`` OLD. The accept ROUTE answers ``remeasured`` True,
     ``user_accepted`` None; the record is accepted by its gates (accepted True, no ``user_accepted``, ``version``
     INSOLE_VERSION); a second accept -> HTTP 409 (nothing is refused any more).
[S5] A run from the fit with an insole ACCEPTED by its gates but of version OLD: ``run_chain(["fit"], force)`` measures
     it again first: ``ran`` = ["insole", "fit"], the record's version = INSOLE_VERSION.
[S6] The cached failure follows the inputs: the S1 state again (stale refused insole), a fit failure
     "The shoe source is not ready" handed to ``garments._note_outcome`` by ``garment_footwear._failure`` (which
     stamps ``inputs_state`` = ``footwear_source.state_token``) -> ``garments.cached_failure`` returns it (step "fit")
     — and still does after an unrelated read; after the accept ROUTE (the source record changed) -> None. A
     ``state_token`` is 12 hex characters and changes with the record (before != after).
"""
import hashlib
import io
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


def main() -> int:
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        import os
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        (root / "world" / "config.json").write_text("{}", encoding="utf-8")
        (root / "instance" / "config.json").write_text("{}", encoding="utf-8")
        config.load(root / "world" / "config.json", root / "instance" / "config.json")
        import _footwear_fixtures as fx
        from fastapi import HTTPException
        from app.core import base_body, footwear_insole as fi, footwear_source as fs, garment_footwear as gf
        from app.core import garment_store as gs, garments, glb_mesh
        from app.routes import characters as routes

        OLD = fi.INSOLE_VERSION - 1
        char, iid = "Walker", "shoe_stale"
        (root / "world" / "characters" / char).mkdir(parents=True)
        img = root / "shoe.png"
        Image.new("RGB", (64, 32), (90, 60, 40)).save(img)

        def png(color) -> bytes:
            buf = io.BytesIO()
            Image.new("RGB", (16, 16), color).save(buf, format="PNG")
            return buf.getvalue()

        reached = []

        def fit_stand_in(character_name, item_id, fsig, **kw):
            ready = gf.source_ready(item_id)
            reached.append(ready)
            if not ready:
                raise base_body.MissingInput(gf.SOURCE_NOT_READY)
            return Path("fit.glb")

        with patch("app.models.inventory.get_item_image_path", lambda i: str(img) if i == iid else ""), \
             patch.object(garments, "_item", lambda c, i: ({"id": i}, garments._footwear())), \
             patch("app.models.character.get_character_profile", lambda c: {}), \
             patch.object(gs, "garment_fsig", lambda *a, **k: "f" * 12), \
             patch.object(base_body, "current_base", lambda *a, **k: ("b" * 12, "s" * 64)), \
             patch.object(gf, "fit_state", lambda *a, **k: "missing"), \
             patch.object(gf, "fit", fit_stand_in), \
             patch.object(garments, "_rejudge_pending", lambda *a, **k: False):
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True)

            def put_mesh(P, F):
                blob = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
                (d / "raw.glb").write_bytes(blob)
                (d / "prepared.glb").write_bytes(blob)
                fs._set_step(d, "mesh", fs._entry(accepted=True, gates={"ok": True, "reasons": []},
                                                  prepared_sha256=hashlib.sha256(blob).hexdigest()))

            def stamp_old(**extra):
                rec = fs.step_record(iid, ssig, "insole")
                fs._set_step(d, "insole", {**rec, "version": OLD, **extra})

            def accept():
                return routes.accept_character_footwear_step(char, iid, "insole", _={})

            (d / "upscaled.png").write_bytes(png((1, 1, 1)))
            (d / "empty.png").write_bytes(png((2, 2, 2)))
            (d / "cutout.png").write_bytes(png((3, 3, 3)))
            for step in ("source", "empty", "cutout"):
                fs._set_step(d, step, fs._entry(accepted=True, gates={"ok": True, "reasons": []}))

            print("[S1] a refused insole of the previous analysis version")
            put_mesh(*fx.wedge(shaft=0.26, open_side=True))
            fs.run_source(iid, steps=["insole"], force=True)
            stamp_old()
            rec = fs.step_record(iid, ssig, "insole")
            check("S1 record", (rec.get("accepted"), rec.get("version"), (rec.get("gates") or {}).get("refusal")),
                  (False, OLD, fi.SHAFT_OPEN_REFUSED))
            check("S1 step_done / stale", (gf.step_done(iid, "insole"), fs.stale_record("insole", rec)), (False, True))

            print("[S2] accept through the route: measured again, refused again, the fresh record accepted")
            out = accept()
            rec = fs.step_record(iid, ssig, "insole")
            ua = rec.get("user_accepted") or {}
            check("S2 answer", (out.get("remeasured"), bool(out.get("user_accepted"))), (True, True))
            check("S2 record", (rec.get("accepted"), rec.get("version"), (rec.get("gates") or {}).get("refusal")),
                  (True, fi.INSOLE_VERSION, fi.SHAFT_OPEN_REFUSED))
            check("S2 reasons = the fresh record's", ua.get("reasons"), list((rec.get("gates") or {}).get("reasons")))
            check("S2 step_done / source_ready", (gf.step_done(iid, "insole"), gf.source_ready(iid)), (True, True))

            print("[S3] the chain from the fit reaches a ready source")
            reached.clear()
            res = gf.run_chain(char, {"id": iid}, ["fit"], True)
            check("S3 run", (res.get("ok"), res.get("ran"), reached), (True, ["fit"], [True]))

            print("[S4] the re-measure passes: nothing to accept")
            put_mesh(*fx.wedge())
            fs.run_source(iid, steps=["insole"], force=True)
            stamp_old(accepted=False, failure=fs.GATE, error="insole refused (older analysis)")
            out = accept()
            rec = fs.step_record(iid, ssig, "insole")
            check("S4 answer", (out.get("remeasured"), out.get("user_accepted")), (True, None))
            check("S4 record", (rec.get("accepted"), "user_accepted" in rec, rec.get("version")),
                  (True, False, fi.INSOLE_VERSION))
            try:
                accept()
                check("S4 second accept", "200", 409)
            except HTTPException as e:
                check("S4 second accept", e.status_code, 409)

            print("[S5] a run from the fit measures an older accepted insole again")
            stamp_old()
            reached.clear()
            res = gf.run_chain(char, {"id": iid}, ["fit"], True)
            check("S5 run", (res.get("ok"), res.get("ran"), reached), (True, ["insole", "fit"], [True]))
            check("S5 version", fs.step_record(iid, ssig, "insole").get("version"), fi.INSOLE_VERSION)

            print("[S6] a cached failure holds only while the source is unchanged")
            put_mesh(*fx.wedge(shaft=0.26, open_side=True))
            fs.run_source(iid, steps=["insole"], force=True)
            stamp_old()
            (root / "world" / "characters" / char / "garments").mkdir(exist_ok=True)
            before = fs.state_token(iid)
            garments._note_outcome(char, iid, gf._failure(char, iid, "f" * 12, "fit", gf.SOURCE_NOT_READY, None, [],
                                                          "MissingInput"))
            held = (garments.cached_failure(char, iid) or {}).get("step")
            again = (garments.cached_failure(char, iid) or {}).get("step")
            accept()
            after = fs.state_token(iid)
            check("S6 token", (len(before), all(ch in "0123456789abcdef" for ch in before), before != after),
                  (12, True, True))
            check("S6 held, held, free", (held, again, garments.cached_failure(char, iid)), ("fit", "fit", None))

    print()
    print(f"{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
