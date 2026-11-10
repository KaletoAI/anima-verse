#!/usr/bin/env python3
"""The subtract hair method in the garment chain (plan docs/superpowers/plans/2026-11-10-hair-subtract-method.md,
Task 1): garment_store's steps / fingerprints, garments' dispatch to ``garment_subtract`` (mesh_source -> cut ->
fit), the caching rules, the gates per length class, the fit on an outfit body and the artefact GC.

Usage:
    ./.venv/bin/python scripts/smoke_hair_subtract.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no Blender, no server process. Stubs: ``expression_regen.render_character_image`` (recorder writing
the haired view), ``character.run_rembg`` (every pixel more than 2 away from grey 128), the image service
(``generate_mesh`` = recorder writing the haired source mesh), ``refine.decimate_to`` (copies),
``garment_assembly.schedule`` and ``sync_topics.changed_at``. The cut (``garment_cut.cut_hair``), the placed fit
(``garment_fit.fit_hair``), the records, fingerprints, serving and the GC judgement are REAL.

Fixture = scripts/smoke_garment_cut.py's geometry and images: base = head sphere R 0.100 + nose + one ear + torso
(rigged 1.7 x + (0, 0.05, 0)); the source mesh = the same body with the crown cap (theta <= 60 deg) at R 0.112,
delivered in its own frame (2 x + (0.3, -0.2, 0.1)); base views = the bald image, haired views = bald + the cap's
silhouette (rendered onto the square 1200 edit canvas like smoke_garment_chain). Demo's hair slot medium / blonde.

EXPECTED, BY HAND
[1] Steps: steps_for("hair", "subtract") == ("haired", "mesh_source", "cut", "fit"); the edit-chain steps and fsig
    are those of the edit chain (method edit_chain); with hair_method "subtract": image_fsig == the edit-chain fsig,
    garment_fsig differs from it and changes again once the haired views exist (their sha256 is in it). run_garment -> ok, ran the four steps; renders 2 (haired front + back), ONE mesh
    job (occasion "hair_source_mesh", the front cut-out as source, the back cut-out as view "back"); source/H_<ssig>/
    holds haired.glb + haired_front_cut.png + haired_back_cut.png + record.json (accepted); prepared/H_<F>.json
    {accepted, method subtract, shape "cut" (medium hair), ssig, image_fsig = edit fsig}; the fit H_<F>.glb has
    the node garment_hair_H, record method "subtract", inputs.ssig / image_fsig, gates.limits with moved_share
    (medium hair); garment_info: method subtract, steps mesh_source / cut / fit accepted, served_fsig F.
[2] A second run: ran [], no render, no mesh job.
[3] Method away and back: edit_chain -> garment_fsig = the edit fsig; subtract again -> F again; run -> ran [],
    no job. other_methods_info under edit_chain lists exactly the subtract fit ([{method subtract, on_current_base
    True}], hairdeck has none). With both other methods holding a fit (``_other_fit`` stubbed: hairdeck file
    mtime 2000 s, subtract 1000 s, subtract off the current base) under edit_chain: [hairdeck, subtract] — newest
    first — with on_current_base [True, False] and preview_url ending "&method=<method>"; under hairdeck only
    [subtract] (the selected method is never listed).
[4] The base model rewritten under the same base signature (another texture colour -> another sha): the subtract
    fsig changes (base model in it), the edit fsig and the ssig do not; garment_info cut "missing"; run -> ran
    ["cut", "fit"], renders and mesh jobs unchanged; cut record unrigged_sha256 unchanged (only the texture moved),
    fit record base_model_sha256 = the new sha.
[5] Gates per length class: hair_gates("medium") has moved_share, hair_gates("short") / ("very short") /
    (shell=True) do not. set_hair_subtract("shell", 5) -> subtract fsig changes, run -> ran ["cut", "fit"], no
    job; cut record shape "shell", shell_mm 5.0; fit gates.limits without moved_share. Bad values (shape "helmet",
    shell 30 mm) -> ValueError, nothing stored. Before the shell run garment_info serves F4 with stale_reasons
    ["shape_changed"]; after it, shell 7 mm -> served F5 with ["shell_changed"]; back to 5 mm -> fsig F5 again, [].
[6] Outfit body A (the same geometry, another texture colour, front view = the bald image): garments.fit_on_body ->
    bodies/<A>/H_<F>.glb; record method subtract, body_id A, inputs.ssig; no render, no mesh job.
[7] GC dry run (artefact_graph.collect(dry_run, explicit)): garment / hair-source orphans = exactly the superseded subtract groups
    garment:H_<F1> ([1]) and garment:H_<F4> ([4]) plus a planted older source hairsource:H_aaaaaaaaaaaa; kept:
    garment:H_<F5>, the edit-chain group garment:H_<edit fsig> (the haired views) and hairsource:H_<ssig>.
[8] The route POST /characters/Demo/hair/subtract (called directly): {shape "", shell_mm 4} -> shape "cut" from the
    length class, no override, 4.0 mm; shape "helmet" -> HTTP 400, nothing stored.
[9] NaN: garment_cut._finite(NaN) None, 1.234 -> 1.23; write_record of {hairline_cm NaN, x [inf, 1.5]} reads back
    as null / [null, 1.5]; a cut record holding a literal NaN on disk (written by the code before this fix) ->
    garment_info encodes with allow_nan=False, cut "refused", hairline_cm None.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-subtract-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        import smoke_garment_chain as cx
        import smoke_garment_cut as gx
        import smoke_garment_fit as fx
        from app.blender import refine
        from app.core import (artefact_graph, base_body, expression_regen, garment_assembly, garment_fit,
                              garment_hair, sync_topics)
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.core import garments

        # --- fixture images / meshes -------------------------------------------------
        bald, _bm, haired, _hm = gx.images()
        BALD, HAIRED = bald.astype(np.uint8), haired.astype(np.uint8)
        Pt, Ft, _cap = gx.haired_truth()
        U = np.stack([(np.arange(len(Pt)) % 997) / 997.0, (np.arange(len(Pt)) // 997) / 997.0], 1)
        SOURCE = fx.make_glb(2.0 * Pt + np.array([0.3, -0.2, 0.1]), Ft, U, image=cx.solid_png(gx.HAIR))

        def base_glbs(colour):
            from app.core.rig_contract import BASE_JOINT_NAMES
            P, F, head = gx.bodies()
            n = len(P)
            Ub = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
            names = list(BASE_JOINT_NAMES)
            J = np.zeros((n, 4), np.int64)
            J[:, 0] = np.where(head, names.index("Head"), names.index("Spine2"))
            Wt = np.zeros((n, 4))
            Wt[:, 0] = 1.0
            return (fx.make_glb(P, F, Ub, image=cx.solid_png((90, 90, 90))),
                    cx.rigged_glb(gx.K * P + np.array([0, 0.05, 0]), F, Ub, J, Wt, cx.solid_png(colour)))

        # --- stubs -------------------------------------------------------------------
        RENDERS, MESHES = [], []
        charmod.run_rembg = cx.rembg_stub

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            RENDERS.append((g["step"], g["view"], g["attempt"], g["fsig"]))
            arr = HAIRED if g["step"] == "haired" else cx.GHOST
            side = kw["override_width"]
            canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
            dy, dx = (canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
            canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(cx.png(canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g["attempt"], **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder

        class FakeService:
            def generate_mesh(self, **kw):
                MESHES.append(kw)
                Path(kw["output_path"]).write_bytes(SOURCE)
                return {"ok": True, "path": kw["output_path"], "backend": "FakeMesh",
                        "routing": {"occasion": kw.get("occasion")}}

            def upscale_image(self, data, **kw):
                raise RuntimeError("no upscaler in the smoke")

            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []

        service.get_image_service = lambda: FakeService()

        def decimate_to(path_in, target_tris, out, merge_vertices=False):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(path_in).read_bytes())
            return {"ok": True, "path": str(out), "tris": target_tris, "ratio": 0.5, "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: True
        sync_topics.changed_at = lambda *a, **k: None

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(cx.solid_png((50, 60, 70), 8))
        from app.core.keyed_lock import keyed_lock

        def set_profile(**values):
            with keyed_lock("character_profile", "Demo"):
                stored = get_character_profile("Demo")
                stored.update(values)
                check(f"profile {sorted(values)}", save_character_profile("Demo", stored), True)

        set_profile(profile_image="Demo_1.png")
        check("pipeline", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair item worn", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hid})
        cdir = get_character_dir("Demo")
        refs, mdir = cdir / "model_refs", cdir / "model3d"

        def write_model(bsig, colour):
            unrigged, rigged = base_glbs(colour)
            (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
            (mdir / "unrigged" / f"{bsig}.glb").write_bytes(unrigged)
            tmpf = mdir / f".{bsig}.tmp"
            tmpf.write_bytes(rigged)
            os.replace(tmpf, mdir / f"{bsig}.glb")
            (mdir / f"{bsig}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated"}))

        b1 = base_body.base_signature("Demo")
        refs.mkdir(parents=True, exist_ok=True)
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            (refs / f"{stem}.png").write_bytes(cx.png(BALD))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        write_model(b1, (200, 160, 140))

        def counts():
            return len(RENDERS), len(MESHES)

        def fit_record(fsig, body=""):
            return gs.read_record(gs.garment_path("Demo", hid, fsig, "fit", body=body).with_suffix(".json"))

        def cut_record(fsig):
            return gs.read_record(gs.garment_path("Demo", hid, fsig, "prepared").with_suffix(".json"))

        # --- [1] steps + first run ------------------------------------------------------------
        print("[1] steps + first run")
        check("subtract steps", gs.steps_for("hair", "subtract"), ("haired", "mesh_source", "cut", "fit"))
        f_edit = gs.garment_fsig("Demo", hid)
        set_profile(hair_method="subtract")
        check("image fsig = edit fsig", gs.image_fsig("Demo", hid), f_edit)
        f0 = gs.garment_fsig("Demo", hid)
        check("subtract fsig differs", f0 != f_edit, True)
        res = garments.run_garment("Demo", hid)
        f1 = gs.garment_fsig("Demo", hid)
        check("the haired views name the fsig", f1 != f0, True)
        check("run", (res.get("ok"), res.get("fsig"), res.get("ran"), res.get("error")),
              (True, f1, ["haired", "mesh_source", "cut", "fit"], None))
        check("renders (haired f/b), one mesh job", (sorted((r[0], r[1]) for r in RENDERS), len(MESHES)),
              ([("haired", "back"), ("haired", "front")], 1))
        job = MESHES[0] if MESHES else {}
        check("mesh job", (job.get("occasion"), Path(str(job.get("source_image_path"))).name,
                           {k: Path(v).name for k, v in (job.get("view_images") or {}).items()}),
              ("hair_source_mesh", "haired_front_cut.png", {"back": "haired_back_cut.png"}))
        ssig = gs.subtract_ssig("Demo", hid)
        folder = gs.source_dir("Demo", hid, ssig)
        check("source folder", sorted(p.name for p in folder.iterdir()) if folder.is_dir() else [],
              ["haired.glb", "haired_back_cut.png", "haired_front_cut.png", "record.json"])
        check("source record accepted", gs.read_record(folder / "record.json").get("accepted"), True)
        cr = cut_record(f1)
        print(f"       cut metrics {cr.get('metrics')}")
        check("cut record", {k: cr.get(k) for k in ("accepted", "method", "shape", "ssig", "image_fsig")},
              {"accepted": True, "method": "subtract", "shape": "cut", "ssig": ssig, "image_fsig": f_edit})
        fit = gs.garment_path("Demo", hid, f1, "fit")
        check("fit node", fit.is_file() and "garment_hair_" + hid in cx.node_names(fit.read_bytes()), True)
        r = fit_record(f1)
        print(f"       fit metrics {r.get('metrics')}")
        check("fit record", (r.get("accepted"), r.get("method"), (r.get("inputs") or {}).get("ssig"),
                             (r.get("inputs") or {}).get("image_fsig"),
                             "moved_share" in ((r.get("gates") or {}).get("limits") or {})),
              (True, "subtract", ssig, f_edit, True))
        info = garments.garment_info("Demo", hid)
        check("info", (info["method"], list(info["steps"]), info["steps"]["mesh_source"]["status"],
                       info["steps"]["cut"]["status"], info["steps"]["fit"]["status"], info["served_fsig"]),
              ("subtract", ["haired", "mesh_source", "cut", "fit"], "accepted", "accepted", "accepted", f1))

        # --- [2] second run --------------------------------------------------------------------
        print("[2] second run")
        before = counts()
        res = garments.run_garment("Demo", hid)
        check("nothing to do", (res.get("ok"), res.get("ran"), counts()), (True, [], before))

        # --- [3] method away and back ----------------------------------------------------------
        print("[3] method away and back")
        set_profile(hair_method="edit_chain")
        check("edit fsig", gs.garment_fsig("Demo", hid), f_edit)
        others = garments.other_methods_info("Demo", hid)
        check("other methods = subtract", [(o.get("method"), o.get("on_current_base")) for o in others],
              [("subtract", True)])
        fake = Path(tempfile.mkdtemp(prefix="hair-others-"))
        fits = {}
        for m, mtime, on_base in (("hairdeck", 2000, True), ("subtract", 1000, False)):
            f = fake / f"{m}.glb"
            f.write_bytes(m.encode())
            os.utime(f, (mtime, mtime))
            fits[m] = (f, {"created_at": f"t{mtime}", "metrics": {}}, on_base)
        real_other_fit = garments._other_fit
        garments._other_fit = lambda _c, _i, m, _p: fits.get(m)
        try:
            both = garments.other_methods_info("Demo", hid)
            check("both others, newest first",
                  [(o["method"], o["on_current_base"], o["created_at"], (o["preview_url"] or "").endswith(f"&method={o['method']}"))
                   for o in both],
                  [("hairdeck", True, "t2000", True), ("subtract", False, "t1000", True)])
            set_profile(hair_method="hairdeck")
            check("selected never listed", [o["method"] for o in garments.other_methods_info("Demo", hid)],
                  ["subtract"])
            set_profile(hair_method="edit_chain")
        finally:
            garments._other_fit = real_other_fit
            shutil.rmtree(fake, ignore_errors=True)
        set_profile(hair_method="subtract")
        check("subtract fsig again", gs.garment_fsig("Demo", hid), f1)
        res = garments.run_garment("Demo", hid)
        check("no job", (res.get("ok"), res.get("ran"), counts()), (True, [], before))

        # --- [4] base model changed: CPU recut ---------------------------------------------------
        print("[4] base model changed")
        unrigged_sha = cr.get("unrigged_sha256")
        write_model(b1, (180, 140, 120))
        new_sha = sha(mdir / f"{b1}.glb")
        f4 = gs.garment_fsig("Demo", hid)
        check("fsig changes, edit fsig / ssig do not",
              (f4 != f1, gs.image_fsig("Demo", hid), gs.subtract_ssig("Demo", hid)), (True, f_edit, ssig))
        info = garments.garment_info("Demo", hid)
        check("cut missing", info["steps"]["cut"]["status"], "missing")
        res = garments.run_garment("Demo", hid)
        check("recut", (res.get("ok"), res.get("ran"), counts()), (True, ["cut", "fit"], before))
        check("cut on the same unrigged source", cut_record(f4).get("unrigged_sha256"), unrigged_sha)
        check("fit on the new base model", fit_record(f4).get("base_model_sha256"), new_sha)

        # --- [5] gates per length class / shell ---------------------------------------------------
        print("[5] gates / shell")
        check("medium has moved_share", "moved_share" in garment_fit.hair_gates("medium"), True)
        check("short / very short / shell without",
              ["moved_share" in garment_fit.hair_gates(c) for c in ("short", "very short")]
              + ["moved_share" in garment_fit.hair_gates("long", shell=True)], [False, False, False])
        for shape, mm in (("helmet", None), ("shell", 30)):
            try:
                garment_hair.set_hair_subtract("Demo", shape, mm)
                check(f"{shape}/{mm} refused", "stored", "ValueError")
            except ValueError:
                check(f"{shape}/{mm} refused", "ValueError", "ValueError")
        check("nothing stored", gs.garment_fsig("Demo", hid), f4)
        check("set shell", garment_hair.set_hair_subtract("Demo", "shell", 5), True)
        f5 = gs.garment_fsig("Demo", hid)
        check("fsig changes", f5 not in (f1, f4), True)
        info = garments.garment_info("Demo", hid)
        check("old cut fit served, marked shape_changed", (info["served_fsig"], info["stale_reasons"]),
              (f4, ["shape_changed"]))
        res = garments.run_garment("Demo", hid)
        check("shell run", (res.get("ok"), res.get("ran"), counts(), res.get("error")),
              (True, ["cut", "fit"], before, None))
        c5 = cut_record(f5)
        print(f"       shell cut metrics {c5.get('metrics')}; fit {fit_record(f5).get('metrics')}")
        check("shell cut", (c5.get("shape"), c5.get("shell_mm")), ("shell", 5.0))
        check("shell fit gates without moved_share",
              "moved_share" in ((fit_record(f5).get("gates") or {}).get("limits") or {}), False)
        check("shell 7 mm", garment_hair.set_hair_subtract("Demo", "shell", 7), True)
        info = garments.garment_info("Demo", hid)
        check("5 mm shell served, marked shell_changed", (info["served_fsig"], info["stale_reasons"]),
              (f5, ["shell_changed"]))
        garment_hair.set_hair_subtract("Demo", "shell", 5)
        info = garments.garment_info("Demo", hid)
        check("back to 5 mm: current, no reason", (gs.garment_fsig("Demo", hid), info["stale_reasons"]), (f5, []))

        # --- [6] outfit body ----------------------------------------------------------------------
        print("[6] outfit body")
        bid = base_body.outfit_body_id("tex" + "a" * 12)
        unrigged_a, rigged_a = base_glbs((190, 150, 130))
        (mdir / f"{bid}.glb").write_bytes(rigged_a)
        (mdir / f"{bid}.json").write_text(json.dumps({
            "rig": "mixamo", "format": "glb", "signature": bid,
            "outfit_body": {"body_id": bid, "mode": "mesh", "version": 1, "texture_signature": "tex" + "a" * 12,
                            "base_signature": b1}}))
        (mdir / "unrigged" / f"{bid}.glb").write_bytes(unrigged_a)
        (refs / f"tpose_{bid}.png").write_bytes(cx.png(BALD))
        base_fit = (gs.garment_path("Demo", hid, f5, "fit"), fit_record(f5))
        try:
            out = garments.fit_on_body("Demo", hid, body_id=bid, base_fit=base_fit, schedule=False)
            check("body fit file", out == gs.garment_path("Demo", hid, f5, "fit", body=bid) and out.is_file(), True)
        except Exception as e:  # noqa: BLE001
            check("body fit", f"{type(e).__name__}: {e}", "ok")
        rb = fit_record(f5, body=bid)
        check("body fit record", (rb.get("accepted"), rb.get("method"), rb.get("body_id"),
                                  (rb.get("inputs") or {}).get("ssig")), (True, "subtract", bid, ssig))
        check("no job", counts(), before)

        # --- [7] artefact GC -----------------------------------------------------------------------
        print("[7] artefact GC")
        old = gs.source_dir("Demo", hid, "aaaaaaaaaaaa")
        old.mkdir(parents=True)
        (old / "haired.glb").write_bytes(SOURCE)
        report = artefact_graph.collect("Demo", dry_run=True, explicit=True)
        orphans = sorted(e["key"] for e in report["orphans"] if e["kind"] in ("garment", "hair_source"))
        check("orphans", orphans, sorted([f"garment:{hid}_{f1}", f"garment:{hid}_{f4}",
                                          f"hairsource:{hid}_aaaaaaaaaaaa"]))
        analysis = artefact_graph.analyse("Demo", explicit=True)
        kept = {n.key for n in analysis.nodes if n.reachable}
        check("kept", sorted(k for k in (f"garment:{hid}_{f5}", f"garment:{hid}_{f_edit}",
                                         f"hairsource:{hid}_{ssig}") if k in kept),
              sorted([f"garment:{hid}_{f5}", f"garment:{hid}_{f_edit}", f"hairsource:{hid}_{ssig}"]))
        check("nothing deleted (dry run)", (old / "haired.glb").is_file(), True)

        # --- [8] the Hair tab route ------------------------------------------------------------------
        print("[8] POST /hair/subtract")
        from fastapi import HTTPException
        from app.routes import characters as routes
        got = routes.set_character_hair_subtract("Demo", routes.HairSubtractRequest(shape="", shell_mm=4), {})
        check("automatic shape, 4 mm", (got["shape"], got["shape_source"], got["shape_override"], got["shell_mm"]),
              ("cut", "length", "", 4.0))
        try:
            routes.set_character_hair_subtract("Demo", routes.HairSubtractRequest(shape="helmet"), {})
            check("helmet -> 400", "no error", 400)
        except HTTPException as e:
            check("helmet -> 400", e.status_code, 400)
        check("helmet stored nothing", garment_hair.shell_mm(get_character_profile("Demo")), 4.0)

        # --- [9] NaN in a record -----------------------------------------------------------------------
        print("[9] NaN never reaches the Hair tab")
        from app.core import garment_cut
        check("garment_cut: unmeasured -> None", (garment_cut._finite(float("nan"), 2), garment_cut._finite(1.234, 2)),
              (None, 1.23))
        probe = Path(tmp) / "probe.json"
        gs.write_record(probe, {"metrics": {"hairline_cm": float("nan"), "x": [float("inf"), 1.5]}})
        check("written as null", json.loads(probe.read_text())["metrics"], {"hairline_cm": None, "x": [None, 1.5]})
        prepared = gs.garment_path("Demo", hid, gs.garment_fsig("Demo", hid), "prepared").with_suffix(".json")
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text('{"accepted": false, "method": "subtract", "shape": "cut", '
                            '"metrics": {"hairline_cm": NaN, "registration_p95_cm": 0.5}}', encoding="utf-8")
        info = garments.garment_info("Demo", hid)
        try:
            json.dumps(info, allow_nan=False)
            encodes = True
        except ValueError:
            encodes = False
        check("NaN on disk: tab encodes, cut refused, hairline None",
              (encodes, info["steps"]["cut"]["status"], info["steps"]["cut"]["metrics"].get("hairline_cm")),
              (True, "refused", None))
        prepared.unlink()

    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
