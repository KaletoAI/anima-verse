#!/usr/bin/env python3
"""Footwear, tasks 10 and 15: the fit step — publish, state, outfit bodies, width cap, the body cut and its gates
(plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Tasks 10 and 15; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.5–§ 5.8, § 6.1, § 7.1, § 8).

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
width 0.085, height 0.02; 1056 faces / 816 vertices: per foot 516 / 384 — sole, top, two sides, heel, toe
grids — plus 12 / 24 per leg column) with its sidecar and
unrigged copy. Item ``heels`` (feet, own mesh) held by Demo; its current source folder holds the closed flat
clog of ``_footwear_fixtures.clog`` as ``prepared.glb`` (``glb_mesh.static_glb``), ``insole.json`` =
``footwear_insole.analyse`` of it and every item step recorded accepted (insole version 5, fit version 8: the
cut applied and gated, toes conformed, the foot measured below the ankle, a boot split at the ankle) — the item steps are done, a run only fits. Item ``boots``: the
closed flat boot ``flat_boot(shaft=0.16)`` of the boots round (the clog with a 16-cm tube over x in [0, 0.10]),
its prepared.glb's material ``doubleSided`` False; item ``pumps``: the wedge pump itself. The clog is the one
fixture shoe a RIGID box foot passes the cut gates in: on the wedge the box, pitched 24.29 deg by the chord,
floats over the shank and pokes through the heel counter and the walls (``smoke_footwear_cut.py`` [X7]/[X8]:
deep_outside 0.28 and visible_poke 0.25 — gate refusals since fit version 3, used in [P7]).

Expected, by hand (``smoke_footwear_cut.py`` [X7] derives the clog's fit: the fit reads the same clog, only
through float32 GLB accessors — 1e-7 relative, far inside the tolerances). The insole width at the ball is read
on the analysis grid's lateral columns, 73 over the footprint (spacing 0.08 / 72), the outermost two exactly ON
the side walls z = +-0.04: through the GLB the walls are float32(0.04) = 0.039999999 and the grid in insole.json
is rounded to 7 digits, so those rays sit ~1e-9 outside the sole-top triangles — ``footwear_insole.vertical_hits``
counts a ray within EDGE_EPS_SHARE (1e-6) x the span of an edge as a hit, so the width stays the full 0.08 raw.
The clog's insole starts at the first station >= 0.01 (station 10 of 240 over 0.26: 0.0108787 raw) and runs flat
at 0.01 to 0.26; the roof (0.04, cavity 0.03 k >= the toes' 0.02) holds the toes to the last station, so the arc
is 0.26 - 0.0108787 = 0.2491213 and k = (0.25 + ALLOW_M 0.005) / 0.2491213 = 1.023599. A flat insole and a flat
foot: chord 0, rest pitch 0 -> extension 0, toe counter 0; root lift = the sole top 0.01 k = 0.010236; insole
width at the ball 0.08 k = 81.89 mm, width needed 0.085 / 0.081888 = 1.0380 = the factor (under the cap 1.10),
slim_needed 0; boot = (0.05 k - (0.08 + 0.010236 + 0.03)) = -69.1 mm. The cut (X7): in the cut frame the whole
box lies inside the footprint prism below the wall top and the vamp -> every foot face goes (2 x 516 = 1032
removed, nothing bisected, no new vertex), the leg columns (24 faces, 48 vertices) remain; slim share 1 -
(0.04 k 1.0380 - 0.002) / 0.0425 = 0.047059 per side; should-be-enclosed 384 vertices per side, deep_outside 0,
visible_n 0 -> visible_poke 0, throat ledge 0.

[P1] run_garment(Demo, heels) -> {ok True, ran ["fit"], fit "accepted"}, HUB 0, the assembly not scheduled.
     The fit GLB garments/heels_<F>.glb: exactly two nodes ``garment_footwear_heels_*`` — ``_left`` / ``_right``
     with extras.garment {kind "footwear", item_id "heels", fsig F, side, part "foot"} (a shoe has no shaft
     node, fit version 6); its body (garment nodes excluded) is
     the CUT base: 24 faces / 48 vertices (fewer than the bare body's 1056 / 816), and in both sides' cut
     frames no remaining vertex lies below the cap inside the footprint (``footwear_cut._Side.g`` >= -1e-9 for
     every one). Record: method "shoe", kind "footwear", version 8, fit_version 8, accepted, ssig = the current
     ssig, body_id = bsig, body_sha256 = base_model_sha256 = sha(base) (the UNCUT bytes), base_signature bsig,
     parents {body_id, body_sha256, base_model_sha256, base_signature, source {ssig, empty_sha256 =
     sha(empty.png), mesh_sha256 = sha(prepared.glb), insole_version 5}}; scale.k_m_per_unit 1.023599
     (+-2e-4); sides.left.extension.deg 0 (|deg| <= 1e-6) both sides; root_lift_m 0.010236 (+-1e-5);
     insole_w_ball_mm 81.89 (+-0.05), width needed 1.0380 (+-0.002), applied 1.0380 (+-0.002), width_cap 1.10;
     slim_needed 0 (both sides); cut {version 3, sides left + right with foot_joint LeftFoot / RightFoot,
     toe_joint LeftToeBase / RightToeBase}; gates = the eight of footwear_fit.FIT_GATES + footwear_cut.CUT_GATES
     (the round-1 ``boot`` gate is gone since fit version 6; a shoe carries no shaft gate), every one ok and
     gating True; deep_outside / visible_poke / throat_ledge_p95_mm / toe_conform_m 0 (the box foot
     lies under the clog's roof: no toe to push); cut_stats {removed_faces
     1032, bisected_faces 0, new_vertices 0}; diagnostics.left.cut {should_enclosed 384, visible_n 0, slim_share
     0.047059 (+-1e-4), throat_moved 0}; foot_pose bones LeftFoot deg 0, root_lift_m 0.010236, source {item_id
     heels, fsig F, glb_sha256 = sha(fit GLB)}; low/heels_<F>.glb exists, record.low.ok. info: steps.fit {status
     accepted, metrics.width_factor 1.038, metrics.extension_deg_left 0, gates with the eight entries}, width_cap
     1.1. A second run -> ran [] (nothing to do); a forced Re-fit (steps "fit", force) -> ran ["fit"], HUB still 0.
[P2] fit_state(Demo, heels, F, sha(base)) "accepted"; prepared.glb replaced by other bytes -> "outdated"
     (restored -> "accepted"); the base model rewritten with other bytes (same geometry, another asset
     generator) -> fit_state with the NEW sha "stale", info steps.fit {status stale, freshness reason "Body
     changed — refit pending"}; the next run refits (ran ["fit"]) -> accepted on the new sha; fsig unchanged
     (no base in it).
[P3] set_width_cap(Demo, heels, 1.02) -> True, profile footwear_width_cap {heels: 1.02}, fsig F2 != F; the run
     fits F2 with scale.width_factor = min(1.02, 1.0380) = 1.02 and width_cap 1.02, slim_needed 1 - 0.081888 x
     1.02 / 0.085 = 0.01735 (+-1e-3); F's fit stays on disk. The route: cap 1.2 -> 400, cap "wide" -> 400, cap
     1.02 -> {width_cap 1.02, fsig F2}; cap null -> width cap 1.10, the profile key gone, fsig back to F.
     set_width_cap on a non-footwear item -> ValueError.
[P4] Mesh mode, outfit body A (its own bytes: the joints renamed "mixamorig:<name>", the Mixamo chain): with the
     base-fit readers (garment_store.accepted_fit / newest_accepted_fits, garments.fit_on_body /
     body_fit_state) replaced by raisers, garments.body_fit(…, base_fit=(missing path, {}), build False) ->
     pending True, fit None; garment_footwear.body_fit(build True) -> fit garments/bodies/<A>/heels_<F>.glb +
     low/, record body_id A, body_sha256 sha(A), base_signature bsig, NO base_model_sha256 (neither top level
     nor in parents) and no base_fit_sha256; extension 0, root lift 0.010236 (the same feet); the body cut
     the same way (24 faces); foot_pose bones "mixamorig:LeftFoot" (the body's own joint names); two shoe
     nodes. garments.body_fit (build False)
     then returns that file; fit_state(…, sha(A), body=A) accepted, with sha(base) stale; with a wrong body sha
     -> fit None, not pending. HUB 0.
[P5] The boot is SPLIT, not refused (fit version 6, boots plan Task 6; scripts/smoke_footwear_split.py has the
     split's numbers on the same clog-shaped foot part: k 1.023599, lift 0.010236, y_split 0.090236, topline
     0.16 k = 0.163776 -> collar_above_ankle_mm +73.5 > SPLIT_MARGIN_M): fit(Demo, boots) publishes
     garments/boots_<FB>.glb with FOUR nodes garment_footwear_boots_{left,right} (extras.garment.part "foot")
     + …_shaft (part "shaft"); the shaft nodes' material doubleSided True, the foot nodes' False (the source's);
     record split.is_boot True, sides.left.split.y_m 0.090236 (+-1e-5), collar 73.5 mm (+-0.1), gates = the
     8 of P1 + the 6 footwear_fit.SHAFT_GATES + footwear_cut's shaft_poke (15; seam_stretch_max {ok False, gating
     False} — recorded, the fit accepted; shaft_poke 0 over the 12 shin vertices per side in the shaft's height
     range — the round-1 column's bottom corners at body y 0.10, 12.5 mm inside the tube; boots plan Task 9,
     CUT_VERSION 3), shaft_push_max_m 0 (the round-1 leg column stands 12.5 mm inside the shaft); the body cut
     is the clog's (24 faces / 48 vertices: the removal's cap is bounded at the band's bottom y_split - 0.02 =
     0.0702, under the leg columns at 0.1102, spec § 7); foot_pose (bones, root_lift_m, contacts, rest) equal
     to the heels' (the split changes no pose); the assembly reads each node by exact name
     (garment_arrays(exact=True)); run_garment(Demo, boots) afterwards -> ran [] . On body A a stored boots fit of
     an older fit version (fit_version 0, accepted on sha(A)) is NOT served: body_fit(build True) refits on A
     (fit_pair calls +1) and publishes bodies/A/boots_<FB>.glb with four nodes, fit_state accepted; a second
     build does not fit again.
[P6] Without a base model (Mira: on the pipeline, no model file) run_garment(Mira, heels) -> {ok True, ran [],
     fit "no_base"}; info steps.fit.status "missing".
[P7] The cut gates refuse (Task 15). fit(Demo, pumps) — the wedge pump, whose fit gates pass (smoke_footwear_fit.py)
     — raises garments._Refused (step "fit", error naming deep_outside and visible_poke, gates with the eight
     entries: deep_outside {ok False, gating True}, slim_needed {ok True}), no fit file; run_garment -> {ok False,
     step "fit", error_type "GateRefused"}, cached_failure(Demo, pumps) = {step "fit", fsig} and info
     steps.fit.status "refused". The base replaced by the 0.10 m wide feet (foot_body_glb(0.10), sha changes):
     run_garment(Demo, pumps) -> refused BEFORE any cut by the fit's own gate, error containing
     "slim_needed 0.2209 > 0.18" (Task 9's hand value 1 - 0.07790 / 0.10 = 0.2210, +-1e-3; gates.slim_needed
     {ok False, gating True}). An older fit reads stale: a pumps record of fit_version 7 (and 6), accepted on
     the current base bytes -> fit_state "stale" (fit_version 8 -> "accepted").
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
        from app.core import (base_body, footwear_cut, footwear_fit, footwear_insole, footwear_source as fs,
                              garment_assembly, garment_footwear as gf, garment_store as gs, garments, glb_mesh,
                              model_refs)
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

        def shoe_item(item_id, shaft=0.0, colour=(20, 20, 20), mesh=None, material=None):
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
            P, F = mesh if mesh is not None else fx.wedge(shaft=shaft)
            prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)), material=material)
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
        heels, ssig, src = shoe_item("heels", mesh=fx.clog())
        boots, _bssig, _bsrc = shoe_item("boots", mesh=fx.flat_boot(shaft=0.16), colour=(90, 60, 30),
                                         material={"doubleSided": False})
        pumps, _pssig, _psrc = shoe_item("pumps", colour=(120, 20, 40))
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
            f"garment_footwear_{heels}_left": {"kind": "footwear", "item_id": heels, "fsig": F, "side": "left", "part": "foot"},
            f"garment_footwear_{heels}_right": {"kind": "footwear", "item_id": heels, "fsig": F, "side": "right", "part": "foot"}})
        bare = glb_mesh.body_arrays(base_glb)
        cut_body = glb_mesh.body_arrays(blob)
        check("P1 bare body 1056 faces / 816 vertices", (len(bare.faces), len(bare.positions)), (1056, 816))
        check("P1 cut body 24 faces / 48 vertices", (len(cut_body.faces), len(cut_body.positions)), (24, 48))
        rec = gs.read_record(fit_path.with_suffix(".json"))
        cut = rec.get("cut") or {}
        check("P1 cut description", (cut.get("version"), sorted(cut.get("sides") or {}),
                                     {s: (d.get("foot_joint"), d.get("toe_joint")) for s, d in (cut.get("sides") or {}).items()}),
              (3, ["left", "right"], {"left": ("LeftFoot", "LeftToeBase"), "right": ("RightFoot", "RightToeBase")}))
        worst = 0.0
        prims = glb_mesh.body_primitive_arrays(blob)
        for prim in prims:
            for s_, desc in (cut.get("sides") or {}).items():
                m = footwear_cut._Map(desc, glb_mesh.joint_bind_matrices(blob), prim)
                gval = footwear_cut._Side(desc).g(m.to_cut(np.asarray(prim.positions, np.float64)))
                worst = min(worst, float(gval.min()))
        check("P1 no remaining vertex below the cap inside the footprint", worst >= -1e-9, True)
        check("P1 record identity", {k: rec.get(k) for k in (
            "method", "kind", "item_id", "fsig", "ssig", "version", "fit_version", "accepted", "body_id",
            "body_sha256", "base_model_sha256", "base_signature")},
            {"method": "shoe", "kind": "footwear", "item_id": heels, "fsig": F, "ssig": ssig, "version": 8,
             "fit_version": 8, "accepted": True, "body_id": bsig, "body_sha256": base_sha,
             "base_model_sha256": base_sha, "base_signature": bsig})
        # a shoe's record: the fit gates + the cut gates without the split-only ones (footwear_cut.SHAFT_CUT_GATES)
        gate_names = list(footwear_fit.FIT_GATES) + [k for k in footwear_cut.CUT_GATES if k not in footwear_cut.SHAFT_CUT_GATES]
        check("P1 eight gates, all ok and gating", {k: (g.get("ok"), g.get("gating")) for k, g in rec["gates"].items()},
              {k: (True, True) for k in gate_names})
        check("P1 cut gates at 0 (a shoe: no shaft_poke)", {k: rec["gates"][k]["value"] for k in footwear_cut.CUT_GATES if k in rec["gates"]},
              {"deep_outside": 0.0, "visible_poke": 0.0, "throat_ledge_p95_mm": 0.0, "toe_conform_m": 0.0})
        check("P1 cut stats", rec.get("cut_stats"), {"removed_faces": 1032, "bisected_faces": 0, "new_vertices": 0})
        dcut = rec["diagnostics"]["left"].get("cut") or {}
        check("P1 cut diagnostics left", (dcut.get("should_enclosed"), dcut.get("visible_n"), dcut.get("throat_moved")),
              (384, 0, 0))
        near("P1 slim share left", dcut.get("slim_share"), 0.047059, 1e-4)
        check("P1 parents", rec.get("parents"), {
            "body_id": bsig, "body_sha256": base_sha, "base_model_sha256": base_sha, "base_signature": bsig,
            "source": {"ssig": ssig, "empty_sha256": sha(src / "empty.png"),
                       "mesh_sha256": sha(src / "prepared.glb"), "insole_version": 5}})
        scale = rec.get("scale") or {}
        near("P1 k", scale.get("k_m_per_unit"), 1.023599, 2e-4)
        for side in ("left", "right"):
            near(f"P1 extension {side}", rec["sides"][side]["extension"]["deg"], 0.0, 1e-6)
            near(f"P1 insole width at the ball {side}", rec["sides"][side]["insole_w_ball_mm"], 81.89, 0.05)
            near(f"P1 width needed {side}", scale["width_needed"][side], 1.0380, 0.002)
            near(f"P1 slim needed {side}", scale["slim_needed"][side], 0.0, 1e-6)
        near("P1 root lift", rec.get("root_lift_m"), 0.010236, 1e-5)
        near("P1 width factor", scale.get("width_factor"), 1.0380, 0.002)
        check("P1 width cap", scale.get("width_cap"), 1.1)
        fp = rec.get("foot_pose") or {}
        near("P1 foot_pose LeftFoot", fp["bones"]["LeftFoot"]["deg"], 0.0, 1e-6)
        near("P1 foot_pose lift", fp.get("root_lift_m"), 0.010236, 1e-5)
        check("P1 foot_pose source", fp.get("source"), {"item_id": heels, "fsig": F, "glb_sha256": sha(fit_path)})
        low = gs.garment_path("Demo", heels, F, "low")
        check("P1 low tier", (low.is_file(), (rec.get("low") or {}).get("ok")), (True, True))
        info = garments.garment_info("Demo", heels)
        fstep = info["steps"]["fit"]
        check("P1 info fit", (fstep["status"], info.get("width_cap"), sorted(fstep["gates"])),
              ("accepted", 1.1, sorted(gate_names)))
        near("P1 info width factor", fstep["metrics"].get("width_factor"), 1.0380, 0.002)
        near("P1 info extension left", fstep["metrics"].get("extension_deg_left"), 0.0, 1e-6)
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
        check("P3 set 1.02", gf.set_width_cap("Demo", heels, 1.02), True)
        check("P3 profile key", get_character_profile("Demo").get("footwear_width_cap"), {heels: 1.02})
        F2 = gs.garment_fsig("Demo", heels)
        check("P3 new fsig", F2 != F, True)
        res = garments.run_garment("Demo", heels)
        check("P3 run", (res.get("ok"), res.get("fsig"), res.get("ran")), (True, F2, ["fit"]))
        rec2 = gs.read_record(gs.garment_path("Demo", heels, F2, "fit").with_suffix(".json"))
        check("P3 width factor / cap", ((rec2.get("scale") or {}).get("width_factor"),
                                        (rec2.get("scale") or {}).get("width_cap")), (1.02, 1.02))
        near("P3 slim needed left", (rec2.get("scale") or {}).get("slim_needed", {}).get("left"), 0.01735, 1e-3)
        check("P3 old fsig fit kept", fit_path.is_file(), True)

        def route(cap):
            try:
                return routes.set_character_footwear_width_cap("Demo", heels, routes.FootwearWidthCapRequest(cap=cap),
                                                               _={})
            except HTTPException as e:
                return e.status_code
        check("P3 route 1.2", route(1.2), 400)
        check("P3 route 'wide'", route("wide"), 400)
        check("P3 route 1.02", route(1.02), {"item_id": heels, "width_cap": 1.02, "fsig": F2})
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
        near("P4 extension", rec_a["sides"]["left"]["extension"]["deg"], 0.0, 1e-6)
        near("P4 root lift", rec_a["root_lift_m"], 0.010236, 1e-5)
        check("P4 body cut on A", len(glb_mesh.body_arrays(body_fit_path.read_bytes()).faces), 24)
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
        print("[P5] a boot is split at the ankle: four nodes")
        FB = gs.garment_fsig("Demo", boots)
        check("P5 own fsig (another item image)", FB != F, True)
        boot_path = gf.fit("Demo", boots, FB, profile=profile)
        check("P5 fit published", boot_path, gs.garment_path("Demo", boots, FB, "fit"))
        bblob = boot_path.read_bytes()
        bnodes = shoe_nodes(bblob, boots)
        check("P5 four nodes", bnodes, {
            f"garment_footwear_{boots}_left": {"kind": "footwear", "item_id": boots, "fsig": FB, "side": "left", "part": "foot"},
            f"garment_footwear_{boots}_right": {"kind": "footwear", "item_id": boots, "fsig": FB, "side": "right", "part": "foot"},
            f"garment_footwear_{boots}_left_shaft": {"kind": "footwear", "item_id": boots, "fsig": FB, "side": "left", "part": "shaft"},
            f"garment_footwear_{boots}_right_shaft": {"kind": "footwear", "item_id": boots, "fsig": FB, "side": "right", "part": "shaft"}})
        bgltf = gltf_of(bblob)

        def double_sided(name):
            node = next(n for n in bgltf["nodes"] if n.get("name") == name)
            prim = bgltf["meshes"][node["mesh"]]["primitives"][0]
            return bool(bgltf["materials"][prim["material"]].get("doubleSided", False))
        check("P5 shaft nodes doubleSided, foot nodes not",
              tuple(double_sided(f"garment_footwear_{boots}_{s_}") for s_ in ("left_shaft", "right_shaft", "left", "right")),
              (True, True, False, False))
        brec = gs.read_record(boot_path.with_suffix(".json"))
        check("P5 split", (brec["split"]["is_boot"], brec["sides"]["left"]["split"]["is_boot"],
                           sorted(brec["sides"]["left"]["parts"])), (True, True, ["foot", "shaft"]))
        near("P5 y_split", brec["sides"]["left"]["split"]["y_m"], 0.090236, 1e-5)
        near("P5 collar above the ankle", brec["sides"]["left"]["split"]["collar_above_ankle_mm"], 73.5, 0.1)
        near("P5 diagnostics collar", brec["diagnostics"]["left"]["collar_above_ankle_mm"], 73.5, 0.1)
        check("P5 fifteen gates", sorted(brec["gates"]),
              sorted(gate_names + list(footwear_fit.SHAFT_GATES) + list(footwear_cut.SHAFT_CUT_GATES)))
        check("P5 shaft_poke 0 (the round-1 leg column's 12 bottom corners per side sit inside the tube)",
              (brec["gates"]["shaft_poke"]["value"], brec["gates"]["shaft_poke"]["ok"], brec["gates"]["shaft_poke"]["gating"],
               brec["diagnostics"]["left"]["cut"].get("shin_n")), (0.0, True, True, 12))
        check("P5 gates ok except the recorded stretch", {k: (g.get("ok"), g.get("gating")) for k, g in brec["gates"].items()
                                                          if k != "seam_stretch_max"},
              {k: (True, True) for k in brec["gates"] if k != "seam_stretch_max"})
        check("P5 seam_stretch_max recorded, not gating", (brec["gates"]["seam_stretch_max"]["ok"],
                                                           brec["gates"]["seam_stretch_max"]["gating"], brec["accepted"]),
              (False, False, True))
        check("P5 no push (shin 12.5 mm inside the shaft)", brec["shaft"]["push_max_m"], 0.0)
        check("P5 body cut = the clog's", (len(glb_mesh.body_arrays(bblob).faces), len(glb_mesh.body_arrays(bblob).positions)), (24, 48))
        check("P5 cut cap bounded at the band", brec["cut"]["sides"]["left"].get("split"), {"y_m": brec["sides"]["left"]["split"]["y_m"], "band_m": 0.02})
        pose_keys = ("bones", "root_lift_m", "contacts", "rest", "version")
        check("P5 foot_pose = the heels'", {k: brec["foot_pose"].get(k) for k in pose_keys}, {k: rec["foot_pose"].get(k) for k in pose_keys})
        exact = glb_mesh.garment_arrays(bblob, node_prefix=f"garment_footwear_{boots}_left", exact=True)
        check("P5 exact node read", len(exact.indices) == brec["sides"]["left"]["parts"]["foot"], True)
        res = garments.run_garment("Demo", boots)
        check("P5 run after the fit", (res.get("ok"), res.get("ran"), res.get("fit")), (True, [], "accepted"))
        check("P5 info accepted", garments.garment_info("Demo", boots)["steps"]["fit"]["status"], "accepted")
        old = gs.garment_path("Demo", boots, FB, "fit", body=A)
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(body_fit_path, old)
        gs.write_record(old.with_suffix(".json"), {"accepted": True, "kind": "footwear", "item_id": boots,
                                                   "fsig": FB, "body_id": A, "body_sha256": sha_a,
                                                   "fit_version": 0})
        calls = len(FIT_CALLS)
        entry = gf.body_fit("Demo", boots, body_id=A, body_sha=sha_a, profile=profile, build=True)
        check("P5 older fit version never served: refitted on A", (entry["fit"], entry["pending"], entry["error"]),
              (old, False, ""))
        check("P5 refit on A: four nodes", sorted(shoe_nodes(old.read_bytes(), boots)),
              sorted([f"garment_footwear_{boots}_{s_}" for s_ in ("left", "right", "left_shaft", "right_shaft")]))
        check("P5 fit_state on A", gf.fit_state("Demo", boots, FB, sha_a, body=A), "accepted")
        check("P5 one fit call", len(FIT_CALLS) - calls, 1)
        gf.body_fit("Demo", boots, body_id=A, body_sha=sha_a, profile=profile, build=True)
        check("P5 no second attempt", len(FIT_CALLS) - calls, 1)
        gs.accepted_fit, gs.newest_accepted_fits, garments.fit_on_body, garments.body_fit_state = saved

        # --- [P6] ---------------------------------------------------------------------------------------------
        print("[P6] no base model yet")
        res = garments.run_garment("Mira", heels)
        check("P6 run", (res.get("ok"), res.get("ran"), res.get("fit")), (True, [], "no_base"))
        check("P6 info", garments.garment_info("Mira", heels)["steps"]["fit"]["status"], "missing")
        check("P6 no hub, no assembly", (HUB, SCHEDULED), ([], []))

        # --- [P7] ---------------------------------------------------------------------------------------------
        print("[P7] the cut gates refuse; the fit's slim gate refuses; an older fit version is stale")
        profile = get_character_profile("Demo")
        FP = gs.garment_fsig("Demo", pumps)
        try:
            gf.fit("Demo", pumps, FP, profile=profile)
            check("P7 cut gates refuse", "published", "_Refused")
        except garments._Refused as e:
            g7 = e.gates or {}
            check("P7 cut gates refuse", (e.step, "deep_outside" in e.error, "visible_poke" in e.error,
                                          sorted(k for k in g7 if k not in ("ok", "reasons")),
                                          (g7.get("deep_outside") or {}).get("ok"),
                                          (g7.get("deep_outside") or {}).get("gating"),
                                          (g7.get("slim_needed") or {}).get("ok")),
                  ("fit", True, True, sorted(gate_names), False, True, True))
        check("P7 no fit file", gs.garment_path("Demo", pumps, FP, "fit").exists(), False)
        res = garments.run_garment("Demo", pumps)
        check("P7 run", (res.get("ok"), res.get("step"), res.get("error_type"), "deep_outside" in str(res.get("error"))),
              (False, "fit", "GateRefused", True))
        failure = garments.cached_failure("Demo", pumps) or {}
        check("P7 failure per fsig", (failure.get("step"), failure.get("fsig")), ("fit", FP))
        check("P7 info refused", garments.garment_info("Demo", pumps)["steps"]["fit"]["status"], "refused")
        wide_sha = write_base(fx.foot_body_glb(0.10))
        check("P7 wide feet", (wide_sha != base_sha, base_body.current_base("Demo")), (True, (bsig, wide_sha)))
        res = garments.run_garment("Demo", pumps)
        check("P7 slim gate refuses", (res.get("ok"), res.get("step"), "slim_needed 0.2209 > 0.18" in str(res.get("error")),
                                       "deep_outside" in str(res.get("error"))), (False, "fit", True, False))
        gw = (res.get("gates") or {}).get("slim_needed") or {}
        near("P7 slim_needed", gw.get("value"), 0.2210, 1e-3)
        check("P7 slim_needed refuses", (gw.get("ok"), gw.get("gating")), (False, True))
        check("P7 no hub", HUB, [])
        old = gs.garment_path("Demo", pumps, FP, "fit")
        shutil.copyfile(fit_path, old)
        for version, want in ((7, "stale"), (6, "stale"), (8, "accepted")):
            gs.write_record(old.with_suffix(".json"), {
                "accepted": True, "kind": "footwear", "item_id": pumps, "fsig": FP, "body_id": bsig,
                "body_sha256": wide_sha, "base_model_sha256": wide_sha, "fit_version": version,
                "parents": {"source": {"ssig": fs.current_ssig(pumps), "mesh_sha256": sha(_psrc / "prepared.glb"),
                                       "insole_version": footwear_insole.INSOLE_VERSION}}})
            check(f"P7 fit_version {version} -> {want}", gf.fit_state("Demo", pumps, FP, wide_sha), want)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
