#!/usr/bin/env python3
"""Footwear, task 10: the fit step — publish, state, outfit bodies, width cap (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 10; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.5–§ 5.8, § 6.1).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_fit_step.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no Blender, no server. Stubs: ``service.get_image_service`` raises and counts into HUB (the
fit is CPU only), ``refine.decimate_to`` copies the fit GLB as its ``low/`` tier, ``garment_assembly.schedule``
records (P2: the fit never schedules the assembly). The fit (``footwear_fit.fit_pair``), the graft, the store,
the garment run and the route function are REAL.

Fixture. Demo (human, on the base-body pipeline). Base model = ``foot_body_glb()`` of
``scripts/_footwear_fixtures.py`` (two box feet skinned to the Foot / ToeBase chain, joints without a prefix,
identity bind rotations: Foot at (0, 0.08, +-0.10), ToeBase at (0.13, 0.01, +-0.10), foot x in [-0.06, 0.19],
width 0.085) with its sidecar and unrigged copy. Item ``heels`` (feet, own mesh) held by Demo; its current
source folder holds the Task 5 wedge pump as ``prepared.glb`` (``glb_mesh.static_glb``), ``insole.json`` =
``footwear_insole.analyse`` of it and every item step recorded accepted (insole version 1, fit version 2: the extension on the skinned ball) — the item steps are
done, a run only fits. Item ``boots``: the same with the wedge's boot variant (``wedge(shaft=0.2098)``).

Expected, by hand (the numbers are Task 9's, ``smoke_footwear_fit.py`` [F1]–[F8], derived there: the fit reads
the same wedge, only through float32 GLB accessors — 1e-7 relative, far inside the tolerances). The insole
width at the ball is read on the analysis grid's lateral columns, 73 over the footprint (spacing 0.08 / 72), the
outermost two exactly ON the side walls z = +-0.04: through the GLB the walls are float32(0.04) = 0.039999999
and the grid in insole.json is rounded to 7 digits, so those rays sit ~1e-9 outside the sole-top triangles —
``footwear_insole.vertical_hits`` counts a ray within EDGE_EPS_SHARE (1e-6) x the span of an edge as a hit, so
the width stays the full 0.08 raw = 0.08 k = 70.83 mm, as in Task 9 (without that tolerance 70 / 72 x 0.08 =
68.86 mm, width needed 1.2344):

[P1] run_garment(Demo, heels) -> {ok True, ran ["fit"], fit "accepted"}, HUB 0, the assembly not scheduled.
     The fit GLB garments/heels_<F>.glb: exactly two nodes ``garment_footwear_heels_*`` — ``_left`` / ``_right``
     with extras.garment {kind "footwear", item_id "heels", fsig F, side}; its body primitives (garment nodes
     excluded) are the base model's (same vertex count). Record: method "shoe", kind "footwear", version 2,
     fit_version 2, accepted, ssig = the current ssig, body_id = bsig, body_sha256 = base_model_sha256 =
     sha(base), base_signature bsig, parents {body_id, body_sha256, base_model_sha256, base_signature, source
     {ssig, empty_sha256 = sha(empty.png), mesh_sha256 = sha(prepared.glb), insole_version 1}};
     scale.k_m_per_unit = 0.255 / 0.288062 = 0.88522 (+-2e-4); sides.left.extension.deg = 24.29 (+-0.05) both
     sides; root_lift_m = 0.07967 + 0.05646 - 0.08 = 0.05613 (+-5e-4); insole_w_ball_mm 0.08 k = 70.83 (+-0.05), width
     needed 0.085 / 0.07082 = 1.2003 (+-0.002), applied 1.10, width_cap 1.10; slim_needed
     1 - 0.07790 / 0.085 = 0.0835 (+-0.001); foot_pose
     bones LeftFoot deg 24.29, root_lift_m 0.05613, source {item_id heels, fsig F, glb_sha256 = sha(fit GLB)};
     low/heels_<F>.glb exists, record.low.ok. info: steps.fit {status accepted, metrics.width_factor 1.1,
     metrics.extension_deg_left 24.29}, width_cap 1.1. A second run -> ran [] (nothing to do); a forced Re-fit
     (steps "fit", force) -> ran ["fit"], HUB still 0.
[P2] fit_state(Demo, heels, F, sha(base)) "accepted"; prepared.glb replaced by other bytes -> "outdated"
     (restored -> "accepted"); the base model rewritten with other bytes (same geometry, another asset
     generator) -> fit_state with the NEW sha "stale", info steps.fit {status stale, freshness reason "Body
     changed — refit pending"}; the next run refits (ran ["fit"]) -> accepted on the new sha; fsig unchanged
     (no base in it).
[P3] set_width_cap(Demo, heels, 1.05) -> True, profile footwear_width_cap {heels: 1.05}, fsig F2 != F; the run
     fits F2 with scale.width_factor = min(1.05, 1.2003) = 1.05 and width_cap 1.05; F's fit stays on disk. The
     route: cap 1.2 -> 400, cap "wide" -> 400, cap 1.05 -> {width_cap 1.05, fsig F2}; cap null -> width cap 1.10,
     the profile key gone, fsig back to F. set_width_cap on a non-footwear item -> ValueError.
[P4] Mesh mode, outfit body A (its own bytes: the joints renamed "mixamorig:<name>", the Mixamo chain): with the
     base-fit readers (garment_store.accepted_fit / newest_accepted_fits, garments.fit_on_body /
     body_fit_state) replaced by raisers, garments.body_fit(…, base_fit=(missing path, {}), build False) ->
     pending True, fit None; garment_footwear.body_fit(build True) -> fit garments/bodies/<A>/heels_<F>.glb +
     low/, record body_id A, body_sha256 sha(A), base_signature bsig, NO base_model_sha256 (neither top level
     nor in parents) and no base_fit_sha256; extension 24.29, root lift 0.05613 (the same feet); foot_pose
     bones "mixamorig:LeftFoot" (the body's own joint names); two shoe nodes. garments.body_fit (build False)
     then returns that file; fit_state(…, sha(A), body=A) accepted, with sha(base) stale; with a wrong body sha
     -> fit None, not pending. HUB 0.
[P5] The boot (topline 0.2098 k = 0.18572 vs the shod ankle 0.13574 + 0.03 -> +20.0 mm > 0): fit(Demo, boots)
     raises garments._Refused (step "fit", error naming BOOT_REFUSED, gates.reasons[0] = BOOT_REFUSED), no fit
     file; run_garment -> {ok False, step "fit"}, cached_failure(Demo, boots) = {step "fit", fsig, error with
     BOOT_REFUSED, base_model_sha256 = sha(base)} — recorded per fsig; info steps.fit.status "refused". On body
     A a stored boots fit of an older fit version (fit_version 0, accepted on sha(A)) is NOT served:
     body_fit(build True) refits, is refused, records the failure on A (body_failure holds for (sha(A), "", 1))
     and returns fit None with the BOOT_REFUSED error; a second build does not fit again (fit_pair calls 1).
[P6] Without a base model (Mira: on the pipeline, no model file) run_garment(Mira, heels) -> {ok True, ran [],
     fit "no_base"}; info steps.fit.status "missing".
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

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(float(got) - float(want)) <= tol
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r} (want {want} +- {tol})")
    if not ok:
        FAILS.append(label)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gltf_of(glb: bytes) -> dict:
    from app.core import glb_mesh
    return glb_mesh._parse(glb, "Test")["gltf"]


def repack(glb: bytes, *, generator: str = "", prefix: str = "") -> bytes:
    """The same GLB with another asset generator (other bytes, same geometry) and/or prefixed joint names."""
    from app.core import glb_mesh
    parsed = glb_mesh._parse(glb, "Test")
    gltf = json.loads(json.dumps(parsed["gltf"]))
    if generator:
        gltf["asset"]["generator"] = generator
    if prefix:
        for node in gltf["nodes"]:
            if "mesh" not in node:
                node["name"] = prefix + node["name"]
    return glb_mesh.pack_glb(gltf, parsed["bin"])


def png_bytes(colour) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buf, format="PNG")
    return buf.getvalue()


def shoe_nodes(glb: bytes, item_id: str):
    return {n["name"]: (n.get("extras") or {}).get("garment") for n in gltf_of(glb)["nodes"]
            if str(n.get("name") or "").startswith(f"garment_footwear_{item_id}")}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-fit-step-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from fastapi import HTTPException
        from app.blender import refine
        from app.core import (base_body, footwear_fit, footwear_insole, footwear_source as fs, garment_assembly,
                              garment_footwear as gf, garment_store as gs, garments, glb_mesh, model_refs)
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile
        from app.routes import characters as routes

        # --- stubs ------------------------------------------------------------------------------------------
        HUB, SCHEDULED, FIT_CALLS = [], [], []

        def no_hub(*a, **k):
            HUB.append("image_service")
            raise RuntimeError("the fit step must never reach the image service")
        service.get_image_service = no_hub
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append(name) or True

        def decimate(src, target, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate
        real_fit_pair = footwear_fit.fit_pair

        def counting_fit_pair(*a, **k):
            FIT_CALLS.append(1)
            return real_fit_pair(*a, **k)
        footwear_fit.fit_pair = counting_fit_pair

        # --- fixture ----------------------------------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        for name in ("Demo", "Mira"):
            check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)

        def shoe_item(item_id, shaft=0.0, colour=(20, 20, 20)):
            iid = inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                     prompt_fragment=f"black {item_id}",
                                     outfit_piece={"slots": ["feet"], "outfit_types": ["casual"],
                                                   "own_mesh": True})["id"]
            folder = inventory._get_item_dir(iid, create=True)
            (folder / "image.png").write_bytes(png_bytes(colour))
            check(f"{iid} image", inventory.set_item_image(iid, "image.png"), True)
            for who in ("Demo", "Mira"):
                inventory.add_to_inventory(who, iid)
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True, exist_ok=True)
            for n, colour in (("upscaled.png", (1, 1, 1)), ("empty.png", (2, 2, 2)), ("cutout.png", (3, 3, 3))):
                (d / n).write_bytes(png_bytes(colour))
            P, F = fx.wedge(shaft=shaft)
            prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
            (d / "raw.glb").write_bytes(prepared)
            (d / "prepared.glb").write_bytes(prepared)
            insole = footwear_insole.analyse(prepared)
            gs.write_record(d / "insole.json", insole)
            check(f"{iid} insole gates ok", insole["gates"]["ok"], True)
            steps = {s: {"accepted": True, "gates": {}, "backend": "", "routing": {}, "created_at": "x"}
                     for s in fs.ITEM_STEPS}
            steps["insole"]["version"] = footwear_insole.INSOLE_VERSION
            gs.write_record(d / "record.json", {"steps": steps})
            return iid, ssig, d
        heels, ssig, src = shoe_item("heels")
        boots, _bssig, _bsrc = shoe_item("boots", shaft=0.2098, colour=(90, 60, 30))
        check("item steps done", all(gf.step_done(heels, s) for s in fs.ITEM_STEPS), True)

        mdir = get_character_dir("Demo") / "model3d"
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")

        def write_base(data: bytes) -> str:
            (mdir / f"{bsig}.glb").write_bytes(data)
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            (mdir / "unrigged" / f"{bsig}.glb").write_bytes(data)
            return hashlib.sha256(data).hexdigest()
        base_glb = fx.foot_body_glb()
        base_sha = write_base(base_glb)
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))

        # --- [P1] ---------------------------------------------------------------------------------------------
        print("[P1] the fit step publishes the shod base")
        F = gs.garment_fsig("Demo", heels)
        res = garments.run_garment("Demo", heels)
        check("P1 run", (res.get("ok"), res.get("fsig"), res.get("ran"), res.get("fit")),
              (True, F, ["fit"], "accepted"))
        if not res.get("ok"):
            print("     ", res)
        check("P1 no hub, no assembly", (HUB, SCHEDULED), ([], []))
        fit_path = gs.garment_path("Demo", heels, F, "fit")
        check("P1 fit path", fit_path, get_character_dir("Demo") / "garments" / f"heels_{F}.glb")
        blob = fit_path.read_bytes()
        nodes = shoe_nodes(blob, heels)
        check("P1 two shoe nodes", nodes, {
            f"garment_footwear_{heels}_left": {"kind": "footwear", "item_id": heels, "fsig": F, "side": "left"},
            f"garment_footwear_{heels}_right": {"kind": "footwear", "item_id": heels, "fsig": F, "side": "right"}})
        check("P1 body unchanged", len(glb_mesh.body_arrays(blob).positions),
              len(glb_mesh.body_arrays(base_glb).positions))
        rec = gs.read_record(fit_path.with_suffix(".json"))
        check("P1 record identity", {k: rec.get(k) for k in (
            "method", "kind", "item_id", "fsig", "ssig", "version", "fit_version", "accepted", "body_id",
            "body_sha256", "base_model_sha256", "base_signature")},
            {"method": "shoe", "kind": "footwear", "item_id": heels, "fsig": F, "ssig": ssig, "version": 2,
             "fit_version": 2, "accepted": True, "body_id": bsig, "body_sha256": base_sha,
             "base_model_sha256": base_sha, "base_signature": bsig})
        check("P1 parents", rec.get("parents"), {
            "body_id": bsig, "body_sha256": base_sha, "base_model_sha256": base_sha, "base_signature": bsig,
            "source": {"ssig": ssig, "empty_sha256": sha(src / "empty.png"),
                       "mesh_sha256": sha(src / "prepared.glb"), "insole_version": 1}})
        scale = rec.get("scale") or {}
        near("P1 k", scale.get("k_m_per_unit"), 0.88522, 2e-4)
        for side in ("left", "right"):
            near(f"P1 extension {side}", rec["sides"][side]["extension"]["deg"], 24.29, 0.05)
            near(f"P1 insole width at the ball {side}", rec["sides"][side]["insole_w_ball_mm"], 70.83, 0.05)
            near(f"P1 width needed {side}", scale["width_needed"][side], 1.2003, 0.002)
            near(f"P1 slim needed {side}", scale["slim_needed"][side], 0.0835, 0.001)
        near("P1 root lift", rec.get("root_lift_m"), 0.05613, 5e-4)
        check("P1 width factor / cap", (scale.get("width_factor"), scale.get("width_cap")), (1.1, 1.1))
        fp = rec.get("foot_pose") or {}
        near("P1 foot_pose LeftFoot", fp["bones"]["LeftFoot"]["deg"], 24.29, 0.05)
        near("P1 foot_pose lift", fp.get("root_lift_m"), 0.05613, 5e-4)
        check("P1 foot_pose source", fp.get("source"), {"item_id": heels, "fsig": F, "glb_sha256": sha(fit_path)})
        low = gs.garment_path("Demo", heels, F, "low")
        check("P1 low tier", (low.is_file(), (rec.get("low") or {}).get("ok")), (True, True))
        info = garments.garment_info("Demo", heels)
        fstep = info["steps"]["fit"]
        check("P1 info fit", (fstep["status"], fstep["metrics"].get("width_factor"), info.get("width_cap")),
              ("accepted", 1.1, 1.1))
        near("P1 info extension left", fstep["metrics"].get("extension_deg_left"), 24.29, 0.05)
        res = garments.run_garment("Demo", heels)
        check("P1 second run", (res.get("ok"), res.get("ran")), (True, []))
        res = garments.run_garment("Demo", heels, steps="fit", force=True)
        check("P1 forced re-fit", (res.get("ok"), res.get("ran"), HUB), (True, ["fit"], []))

        # --- [P2] ---------------------------------------------------------------------------------------------
        print("[P2] fit state")
        check("P2 accepted", gf.fit_state("Demo", heels, F, base_sha), "accepted")
        prepared_bytes = (src / "prepared.glb").read_bytes()
        (src / "prepared.glb").write_bytes(prepared_bytes + b"\0\0\0\0")
        check("P2 source mesh replaced -> outdated", gf.fit_state("Demo", heels, F, base_sha), "outdated")
        (src / "prepared.glb").write_bytes(prepared_bytes)
        check("P2 restored -> accepted", gf.fit_state("Demo", heels, F, base_sha), "accepted")
        new_sha = write_base(repack(base_glb, generator="another export"))
        check("P2 other base bytes", (new_sha != base_sha, base_body.current_base("Demo")), (True, (bsig, new_sha)))
        check("P2 body bytes changed -> stale", gf.fit_state("Demo", heels, F, new_sha), "stale")
        fstep = garments.garment_info("Demo", heels)["steps"]["fit"]
        check("P2 info stale", (fstep["status"], fstep["freshness"]["reason"]),
              ("stale", "Body changed — refit pending"))
        res = garments.run_garment("Demo", heels)
        check("P2 refit", (res.get("ok"), res.get("fsig"), res.get("ran"), res.get("fit")),
              (True, F, ["fit"], "accepted"))
        check("P2 accepted on the new body", gs.read_record(fit_path.with_suffix(".json")).get("base_model_sha256"),
              new_sha)
        base_sha = new_sha

        # --- [P3] ---------------------------------------------------------------------------------------------
        print("[P3] width cap")
        check("P3 set 1.05", gf.set_width_cap("Demo", heels, 1.05), True)
        check("P3 profile key", get_character_profile("Demo").get("footwear_width_cap"), {heels: 1.05})
        F2 = gs.garment_fsig("Demo", heels)
        check("P3 new fsig", F2 != F, True)
        res = garments.run_garment("Demo", heels)
        check("P3 run", (res.get("ok"), res.get("fsig"), res.get("ran")), (True, F2, ["fit"]))
        rec2 = gs.read_record(gs.garment_path("Demo", heels, F2, "fit").with_suffix(".json"))
        check("P3 width factor / cap", ((rec2.get("scale") or {}).get("width_factor"),
                                        (rec2.get("scale") or {}).get("width_cap")), (1.05, 1.05))
        check("P3 old fsig fit kept", fit_path.is_file(), True)

        def route(cap):
            try:
                return routes.set_character_footwear_width_cap("Demo", heels, routes.FootwearWidthCapRequest(cap=cap),
                                                               _={})
            except HTTPException as e:
                return e.status_code
        check("P3 route 1.2", route(1.2), 400)
        check("P3 route 'wide'", route("wide"), 400)
        check("P3 route 1.05", route(1.05), {"item_id": heels, "width_cap": 1.05, "fsig": F2})
        check("P3 route null", route(None), {"item_id": heels, "width_cap": 1.1, "fsig": F})
        check("P3 key removed", "footwear_width_cap" in get_character_profile("Demo"), False)
        hair = inventory.add_item(name="Scarf", category="outfit_piece", item_id="scarf",
                                  outfit_piece={"slots": ["neck"], "outfit_types": ["casual"],
                                                "own_mesh": True})["id"]
        inventory.add_to_inventory("Demo", hair)
        try:
            gf.set_width_cap("Demo", hair, 1.05)
            check("P3 non-footwear refused", "stored", "ValueError")
        except ValueError:
            check("P3 non-footwear refused", "ValueError", "ValueError")

        # --- [P4] ---------------------------------------------------------------------------------------------
        print("[P4] mesh mode: fitted on the outfit body from the source")
        A = base_body.outfit_body_id("tex" + "a" * 12)
        body_a = repack(base_glb, generator="outfit body A", prefix="mixamorig:")
        (mdir / f"{A}.glb").write_bytes(body_a)
        (mdir / f"{A}.json").write_text(json.dumps({
            "rig": "mixamo", "format": "glb", "signature": A,
            "outfit_body": {"body_id": A, "mode": "mesh", "version": 1, "texture_signature": "tex" + "a" * 12,
                            "base_signature": bsig}}))
        (mdir / "unrigged" / f"{A}.glb").write_bytes(body_a)
        sha_a = hashlib.sha256(body_a).hexdigest()
        READ_BASE = []

        def base_reader(name):
            def stub(*a, **k):
                READ_BASE.append(name)
                raise AssertionError(f"{name} must not be read for a footwear body fit")
            return stub
        saved = (gs.accepted_fit, gs.newest_accepted_fits, garments.fit_on_body, garments.body_fit_state)
        gs.accepted_fit = base_reader("accepted_fit")
        gs.newest_accepted_fits = base_reader("newest_accepted_fits")
        garments.fit_on_body = base_reader("fit_on_body")
        garments.body_fit_state = base_reader("body_fit_state")
        profile = get_character_profile("Demo")
        no_base_fit = (root / "missing.glb", {})
        entry = garments.body_fit("Demo", heels, body_id=A, body_sha=sha_a, base_fit=no_base_fit, profile=profile)
        check("P4 before the build", (entry["pending"], entry["fit"], entry["fsig"]), (True, None, F))
        entry = gf.body_fit("Demo", heels, body_id=A, body_sha=sha_a, profile=profile, build=True)
        body_fit_path = get_character_dir("Demo") / "garments" / "bodies" / A / f"heels_{F}.glb"
        check("P4 build", (entry["fit"], entry["pending"], entry["error"]), (body_fit_path, False, ""))
        check("P4 low tier", entry["low"], body_fit_path.parent / "low" / f"heels_{F}.glb")
        rec_a = entry["record"]
        check("P4 record", ({k: rec_a.get(k) for k in ("body_id", "body_sha256", "base_signature")},
                            "base_model_sha256" in rec_a, "base_model_sha256" in rec_a.get("parents", {}),
                            "base_fit_sha256" in rec_a),
              ({"body_id": A, "body_sha256": sha_a, "base_signature": bsig}, False, False, False))
        near("P4 extension", rec_a["sides"]["left"]["extension"]["deg"], 24.29, 0.05)
        near("P4 root lift", rec_a["root_lift_m"], 0.05613, 5e-4)
        check("P4 foot_pose bones", sorted(rec_a["foot_pose"]["bones"]),
              ["mixamorig:LeftFoot", "mixamorig:LeftToeBase", "mixamorig:RightFoot", "mixamorig:RightToeBase"])
        check("P4 two shoe nodes", sorted(shoe_nodes(body_fit_path.read_bytes(), heels)),
              [f"garment_footwear_{heels}_left", f"garment_footwear_{heels}_right"])
        entry = garments.body_fit("Demo", heels, body_id=A, body_sha=sha_a, base_fit=no_base_fit, profile=profile)
        check("P4 served via garments.body_fit", (entry["fit"], entry["pending"]), (body_fit_path, False))
        check("P4 fit_state on A", (gf.fit_state("Demo", heels, F, sha_a, body=A),
                                    gf.fit_state("Demo", heels, F, base_sha, body=A)), ("accepted", "stale"))
        entry = gf.body_fit("Demo", heels, body_id=A, body_sha="0" * 64, profile=profile, build=True)
        check("P4 wrong body bytes", (entry["fit"], entry["pending"]), (None, False))
        check("P4 base fit never read, no hub", (READ_BASE, HUB), ([], []))

        # --- [P5] ---------------------------------------------------------------------------------------------
        print("[P5] a boot is refused at the fit")
        FB = gs.garment_fsig("Demo", boots)
        check("P5 own fsig (another item image)", FB != F, True)
        try:
            gf.fit("Demo", boots, FB, profile=profile)
            check("P5 fit refused", "published", "_Refused")
        except garments._Refused as e:
            check("P5 fit refused", (e.step, footwear_insole.BOOT_REFUSED in e.error, (e.gates or {}).get(
                "reasons", [None])[0]), ("fit", True, footwear_insole.BOOT_REFUSED))
        check("P5 no fit file", gs.garment_path("Demo", boots, FB, "fit").exists(), False)
        res = garments.run_garment("Demo", boots)
        check("P5 run", (res.get("ok"), res.get("step"), footwear_insole.BOOT_REFUSED in str(res.get("error"))),
              (False, "fit", True))
        failure = garments.cached_failure("Demo", boots) or {}
        check("P5 failure per fsig", (failure.get("step"), failure.get("fsig"), failure.get("base_model_sha256"),
                                      footwear_insole.BOOT_REFUSED in str(failure.get("error"))),
              ("fit", FB, base_sha, True))
        check("P5 info refused", garments.garment_info("Demo", boots)["steps"]["fit"]["status"], "refused")
        old = gs.garment_path("Demo", boots, FB, "fit", body=A)
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(body_fit_path, old)
        gs.write_record(old.with_suffix(".json"), {"accepted": True, "kind": "footwear", "item_id": boots,
                                                   "fsig": FB, "body_id": A, "body_sha256": sha_a,
                                                   "fit_version": 0})
        calls = len(FIT_CALLS)
        entry = gf.body_fit("Demo", boots, body_id=A, body_sha=sha_a, profile=profile, build=True)
        check("P5 older fit version never served", (entry["fit"], entry["pending"],
                                                     footwear_insole.BOOT_REFUSED in entry["error"]),
              (None, False, True))
        check("P5 failure on A", (gs.body_failure("Demo", boots, FB, A, body_sha=sha_a, base_fit_sha="",
                                                  fit_version=footwear_fit.FOOTWEAR_FIT_VERSION) or {}).get("step"), "fit")
        gf.body_fit("Demo", boots, body_id=A, body_sha=sha_a, profile=profile, build=True)
        check("P5 no second attempt", len(FIT_CALLS) - calls, 1)
        gs.accepted_fit, gs.newest_accepted_fits, garments.fit_on_body, garments.body_fit_state = saved

        # --- [P6] ---------------------------------------------------------------------------------------------
        print("[P6] no base model yet")
        res = garments.run_garment("Mira", heels)
        check("P6 run", (res.get("ok"), res.get("ran"), res.get("fit")), (True, [], "no_base"))
        check("P6 info", garments.garment_info("Mira", heels)["steps"]["fit"]["status"], "missing")
        check("P6 no hub, no assembly", (HUB, SCHEDULED), ([], []))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
