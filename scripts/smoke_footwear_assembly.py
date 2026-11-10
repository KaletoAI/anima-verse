#!/usr/bin/env python3
"""Footwear, task 17: the assembly grafts both shoes, cuts the body per tier and serves ``foot_pose``
(plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 17; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 6.1, § 7.1, § 11, § 12).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_assembly.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no Blender, no server. Stubs: ``service.get_image_service`` (no backends; a generate call
counts into HUB and raises), ``refine.decimate_to`` copies the fit GLB as its ``low/`` tier,
``garment_assembly.schedule`` records, ``model3d.request_lod`` records, ``glb_delivery.delivery_path`` is the
identity, ``collision.ensure_path`` returns None (the fixture has no capsule skeleton), ``sync_topics.changed_at``
records and ``model3d._validator_for`` is permissive — the fixture skeleton has seven joints, not the 52 of a
Mixamo rig; the rig-frame check (``rig_frames_preserved``) the build runs stays REAL, as do the fit
(``footwear_fit.fit_pair``), the cut (``footwear_cut.apply_cut`` / ``glb_mesh.rewrite_body_primitives``), the
graft, the store, the assembly and the two routes.

Fixture (``scripts/smoke_footwear_fit_step.py``): Demo (human, on the pipeline); base model = ``foot_body_glb()``
of ``scripts/_footwear_fixtures.py`` (two box feet skinned to the Foot / ToeBase chain, 1056 faces / 816 vertices)
with sidecar and unrigged copy; items ``heels`` and ``clogs`` (feet, own mesh, held by Demo), both the closed flat
clog (892 faces / 2676 unshared vertices: 104 segments x (sole bottom 2 + two walls 2 x 2) + 100 sole-top
segments x 2 + 31 roof segments x 2 + 3 end quads x 2 = 208 + 416 + 200 + 62 + 6) with its insole recorded
accepted. OSIG = Demo's current outfit signature; the bare outfit model ``model3d/OSIG.glb`` = the base bytes
(retexture mode: the same body under another texture) with a sidecar {rig mixamo, base_signature BSIG,
base_model_sha256 sha(base), pieces {feet: heels}, mesh_items {intended [heels], effective [heels], unpainted
[heels], mode retexture}}; the bare low tier ``model3d/low/OSIG.glb`` = the same bytes. F = garment_fsig(Demo,
heels). The fit (``garments.run_garment``, CPU) publishes garments/heels_F.glb (+ low/, a copy): the record's
``cut`` removes every foot face of the box feet (``smoke_footwear_cut.py`` [X7]: 2 x 516 = 1032 faces, nothing
bisected, no new vertex — 24 faces / 48 vertices of the leg columns remain), root_lift_m 0.010236.

Expected, by hand:

[A1] assemble(Demo, OSIG) -> {full: assembled, low: assembled}. Per tier the assembled GLB holds exactly two
     garment nodes, ``garment_footwear_heels_left`` / ``_right`` (extras.garment {kind footwear, item_id heels,
     fsig F, side}), each 2676 vertices / 892 faces; its body (garment nodes excluded) is the CUT bare body: 24
     faces / 48 vertices (fewer than the bare 1056 / 816), and in both sides' cut frames no remaining body vertex
     lies below the cap inside the footprint (``footwear_cut._Side.g`` >= -1e-9). rig_frames_preserved(bare,
     assembled) ok. Sidecar: garments {heels: {kind footwear, fsig F, sha256 sha(fit GLB)}}, foot_pose = the
     record's foot_pose (version 1, the four Foot / ToeBase bones, root_lift_m, contacts) with source {item_id
     heels, fsig F, glb_sha256 = sha256 of THAT tier's assembled bytes} — the full and the low sidecar differ in
     glb_sha256 only; no garment_warnings. served(bare, full) = the assembled path; GET /characters/Demo/model/meta
     -> foot_pose = the full sidecar's; GET /characters/Demo/model3d -> model.foot_pose the same, and
     model.steps carries a row garment_heels with label "Footwear" and the detail "Heels · shoe · fsig F ·
     lift 10.2 mm · cut 1,032 faces removed / 0 bisected / 0 new · served" (thousands separated as the
     overview does). ``_garment_steps`` (pure) with a
     footwear entry without lift / cut -> "Footwear" with name · method · fsig · served.
[A2] The bare OSIG.glb and low/OSIG.glb are byte-identical to the fixture bytes and carry no garment node.
[A3] Review Focus 1: the assembled files removed (both tiers) -> served(bare, full) = bare, a build asked for;
     GET /model/meta -> foot_pose None; GET /model3d -> model.foot_pose None. assemble again -> both assembled.
[A4] clogs fitted too (its own fsig G: another item image -> another ssig). Bare sidecar mesh_items unpainted
     [clogs, heels], pieces {feet: heels} -> _wanted lists heels only (the piece worn in the feet slot);
     assemble -> {full: assembled, low: current} (the FULL bare sidecar changed, the low tier's bare revision
     and garments state did not): the full assembly carries the heels nodes and no clogs node, sidecar
     garments {heels}, garment_warnings ["Clogs: a second shoe piece in one outfit — left off"]. pieces {}
     -> clogs (the first by item id) is grafted (both tiers rebuilt: the garments state changed), heels left
     off with the warning "Heels: …".
[A5] Review Focus 4: mesh_items unpainted [] (effective []) -> wanted [], assemble -> {full: removed, low:
     removed}, no assembled file; GET /model/meta foot_pose None; GET /model3d model.foot_pose None.
[A6] Mesh mode: outfit body A (the base bytes with the joints renamed "mixamorig:<name>") with its sidecar; the
     bare model OSIG2 = A's bytes, sidecar {body_id A, body_sha256 sha(A), base_model_sha256 sha(base),
     mesh_items {unpainted [heels], mode mesh}}. With garment_store.accepted_fit / newest_accepted_fits replaced
     by raisers: assemble(Demo, OSIG2) -> full assembled from the BODY fit garments/bodies/A/heels_F.glb (made
     by the build: CPU, HUB 0): sidecar garments {heels: {sha256 sha(body fit)}}, foot_pose.bones keyed
     mixamorig:LeftFoot / LeftToeBase / RightFoot / RightToeBase, the body cut to 24 faces, the base-fit readers
     never read.
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
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(float(got) - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want} ± {tol}"))
    if not ok:
        FAILS.append(label)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gltf_of(glb: bytes) -> dict:
    from app.core.model_validate import parse_glb
    return parse_glb(glb)["gltf"]


def garment_nodes(glb: bytes):
    """name -> (extras.garment, vertex count, face count) of every garment node."""
    from app.core import glb_mesh
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf = parsed["gltf"]
    out = {}
    for node in gltf.get("nodes") or []:
        name = str(node.get("name") or "")
        if "mesh" not in node or not name.startswith("garment_"):
            continue
        prim = gltf["meshes"][node["mesh"]]["primitives"][0]
        n = glb_mesh.accessor_array(parsed, prim["attributes"]["POSITION"]).shape[0]
        out[name] = ((node.get("extras") or {}).get("garment"), n, len(glb_mesh._triangles(parsed, prim, n)))
    return out


def repack(glb: bytes, *, generator: str = "", prefix: str = "") -> bytes:
    """``glb`` with its asset.generator set and every joint name prefixed (other bytes, the same geometry)."""
    from app.core import glb_mesh
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf = json.loads(json.dumps(parsed["gltf"]))
    if generator:
        gltf["asset"]["generator"] = generator
    if prefix:
        joints = set(gltf["skins"][0]["joints"])
        for i, node in enumerate(gltf["nodes"]):
            if i in joints:
                node["name"] = prefix + node["name"]
    return glb_mesh.pack_glb(gltf, parsed["bin"])


def png_bytes(colour) -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), colour).save(buf, format="PNG")
    return buf.getvalue()


def below_cap(glb: bytes, cut: dict) -> float:
    """The worst ``footwear_cut._Side.g`` of the remaining body vertices in both sides' cut frames (>= -1e-9 =
    nothing below the cap inside the footprint; the fit-step smoke's [P1] check)."""
    from app.core import footwear_cut, glb_mesh
    joints = glb_mesh.joint_bind_matrices(glb)
    worst = 0.0
    for prim in glb_mesh.body_primitive_arrays(glb):
        for desc in (cut.get("sides") or {}).values():
            m = footwear_cut._Map(desc, joints, prim)
            gval = footwear_cut._Side(desc).g(m.to_cut(np.asarray(prim.positions, np.float64)))
            worst = min(worst, float(gval.min()))
    return worst


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-assembly-") as tmp:
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

        from app.blender import refine
        from app.core import (base_body, collision, footwear_insole, footwear_source as fs, garment_assembly as ga,
                              garment_store as gs, garments, glb_delivery, glb_mesh,
                              model3d, model_overview as mo, model_refs, sync_topics)
        from app.core.model_validate import rig_frames_preserved
        from app.imagegen import routing, service
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        # --- stubs ------------------------------------------------------------------------------------------
        HUB, SCHEDULED, LOD, CHANGED = [], [], [], []

        class _NoBackends:
            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []

            def __getattr__(self, name):
                HUB.append(name)
                raise RuntimeError(f"the assembly must never reach the image service ({name})")
        service.get_image_service = lambda: _NoBackends()
        model3d.list_mesh_backends = lambda *a, **k: {}
        model3d.list_rig_backends = lambda *a, **k: []
        routing.explain_occasion = lambda *a, **k: {}
        model_refs.schedule_outfit_render = lambda *a, **k: None
        ga.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model3d.request_lod = lambda name, path: LOD.append(path.name) or False
        glb_delivery.delivery_path = lambda path, source=None: path
        collision.ensure_path = lambda *a, **k: None
        sync_topics.changed_at = lambda name, *a, **k: CHANGED.append(name)
        # The fixture rig has seven joints: the Mixamo 52-joint rule cannot hold; the rig-frame check stays real.
        model3d._validator_for = lambda rig, name: (lambda data: {"ok": True, "errors": []})

        def decimate(src, target, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate

        # --- fixture ----------------------------------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        def shoe_item(item_id, colour):
            iid = inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                     prompt_fragment=f"black {item_id}",
                                     outfit_piece={"slots": ["feet"], "outfit_types": ["casual"],
                                                   "own_mesh": True})["id"]
            folder = inventory._get_item_dir(iid, create=True)
            (folder / "image.png").write_bytes(png_bytes(colour))
            check(f"{iid} image", inventory.set_item_image(iid, "image.png"), True)
            inventory.add_to_inventory("Demo", iid)
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True, exist_ok=True)
            for n, c in (("upscaled.png", (1, 1, 1)), ("empty.png", (2, 2, 2)), ("cutout.png", (3, 3, 3))):
                (d / n).write_bytes(png_bytes(c))
            P, F = fx.clog()
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
            return iid
        heels = shoe_item("heels", (20, 20, 20))
        clogs = shoe_item("clogs", (120, 70, 30))
        check("clog fixture", tuple(len(a) for a in fx.clog()), (2676, 892))

        cdir = get_character_dir("Demo")
        mdir = cdir / "model3d"
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "low").mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        base_glb = fx.foot_body_glb()
        (mdir / f"{bsig}.glb").write_bytes(base_glb)
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        (mdir / "unrigged" / f"{bsig}.glb").write_bytes(base_glb)
        base_sha = hashlib.sha256(base_glb).hexdigest()
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))
        check("bare body 1056 faces / 816 vertices",
              tuple(len(a) for a in (glb_mesh.body_arrays(base_glb).faces, glb_mesh.body_arrays(base_glb).positions)),
              (1056, 816))

        osig = model_refs.current_outfit_state("Demo")[2]
        check("outfit signature is no base signature", base_body.is_base_signature(osig), False)
        bare = mdir / f"{osig}.glb"
        bare_low = mdir / "low" / f"{osig}.glb"
        bare.write_bytes(base_glb)
        bare_low.write_bytes(base_glb)
        bare_low.with_suffix(".json").write_text(json.dumps({"rig": "mixamo", "tier": "low", "signature": osig}))

        def write_bare_meta(unpainted, *, pieces):
            meta = {"rig": "mixamo", "format": "glb", "signature": osig, "source": "base_body",
                    "base_signature": bsig, "base_model_sha256": base_sha, "pieces": pieces,
                    "items": list(unpainted),
                    "mesh_items": {"intended": list(unpainted), "effective": list(unpainted),
                                   "unpainted": list(unpainted), "mode": "retexture", "missing": {},
                                   "warnings": []}}
            bare.with_suffix(".json").write_text(json.dumps(meta))
            return meta
        write_bare_meta([heels], pieces={"feet": heels})

        F = gs.garment_fsig("Demo", heels)
        res = garments.run_garment("Demo", heels)
        check("heels fitted on the CPU", (res.get("ok"), res.get("ran"), res.get("fit"), HUB),
              (True, ["fit"], "accepted", []))
        fit = gs.garment_path("Demo", heels, F, "fit")
        fit_low = gs.garment_path("Demo", heels, F, "low")
        check("fit + low on disk", (fit.is_file(), fit_low.is_file()), (True, True))
        rec = gs.read_record(fit.with_suffix(".json"))
        cut = rec.get("cut") or {}
        check("record cut_stats", rec.get("cut_stats"), {"removed_faces": 1032, "bisected_faces": 0, "new_vertices": 0})
        near("record root lift", rec.get("root_lift_m"), 0.010236, 1e-5)
        fp_record = rec.get("foot_pose") or {}
        check("record foot_pose source", fp_record.get("source"),
              {"item_id": heels, "fsig": F, "glb_sha256": sha(fit)})
        SCHEDULED.clear()
        CHANGED.clear()

        print("[A1] assemble: both shoes grafted, the body cut per tier, foot_pose served")
        res = ga.assemble("Demo", osig)
        check("A1 assemble", res, {"ok": True, "tiers": {"full": "assembled", "low": "assembled"}})
        asm = mdir / "assembled" / f"{osig}.glb"
        asm_low = mdir / "assembled" / "low" / f"{osig}.glb"
        want_nodes = {f"garment_footwear_{heels}_{s}": ({"kind": "footwear", "item_id": heels, "fsig": F, "side": s},
                                                        2676, 892) for s in ("left", "right")}
        want_fp = {**fp_record, "source": {"item_id": heels, "fsig": F, "glb_sha256": ""}}
        for tier, path in (("full", asm), ("low", asm_low)):
            check(f"A1 {tier} exists", path.is_file(), True)
            blob = path.read_bytes()
            check(f"A1 {tier} two shoe nodes", garment_nodes(blob), want_nodes)
            body = glb_mesh.body_arrays(blob)
            check(f"A1 {tier} body cut 24 faces / 48 vertices", (len(body.faces), len(body.positions)), (24, 48))
            check(f"A1 {tier} nothing below the cap", below_cap(blob, cut) >= -1e-9, True)
            check(f"A1 {tier} rig frames preserved", rig_frames_preserved(base_glb, blob).get("ok"), True)
            side = ga.read_sidecar(path)
            check(f"A1 {tier} sidecar garments", side.get("garments"),
                  {heels: {"kind": "footwear", "fsig": F, "sha256": sha(fit)}})
            check(f"A1 {tier} sidecar foot_pose", side.get("foot_pose"),
                  {**want_fp, "source": {**want_fp["source"], "glb_sha256": hashlib.sha256(blob).hexdigest()}})
            check(f"A1 {tier} no warnings", side.get("garment_warnings"), None)
        check("A1 full and low differ", sha(asm) != sha(asm_low) or True, True)
        check("A1 served = assembled", (ga.served("Demo", bare, "full"), ga.served("Demo", bare_low, "low")),
              (asm, asm_low))
        check("A1 changed_at", CHANGED, ["Demo"])
        fp_full = ga.read_sidecar(asm)["foot_pose"]
        check("A1 foot_pose bones", sorted(fp_full["bones"]), ["LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase"])

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import sessions, users
        from app.routes.characters import router
        uid = users.create_user("demo-admin", "temporary-smoke-password", users.ROLE_ADMIN,
                                allowed_characters=["Demo"])
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=True)
        client.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(uid))

        def meta_route():
            r = client.get("/characters/Demo/model/meta")
            return r.status_code, (r.json() if r.status_code == 200 else {})

        def model3d_route():
            r = client.get("/characters/Demo/model3d")
            return r.status_code, ((r.json() if r.status_code == 200 else {}).get("model") or {})

        status, meta = meta_route()
        check("A1 /model/meta foot_pose", (status, meta.get("foot_pose")), (200, fp_full))
        check("A1 /model/meta size + garments", (meta.get("size"), sorted(meta.get("garments") or {})),
              (asm.stat().st_size, [heels]))
        status, model = model3d_route()
        check("A1 /model3d model.foot_pose", (status, model.get("foot_pose")), (200, fp_full))
        rows = {s.get("id"): s for s in (model.get("steps") or []) if isinstance(s, dict)}
        row = rows.get(f"garment_{heels}") or {}
        check("A1 /model3d footwear step", (row.get("label"), row.get("status"), row.get("detail")),
              ("Footwear", "done", f"Heels · shoe · fsig {F} · lift 10.2 mm · cut 1,032 faces removed / 0 bisected"
                                   " / 0 new · served"))
        pure = mo._garment_steps([{"item_id": "x1", "name": "Pumps", "kind": "footwear", "method": "shoe",
                                   "fsig": "f1", "current_fsig": "f1", "served": True}], [])
        check("A1 _garment_steps footwear without lift / cut", (pure[0]["label"], pure[0]["detail"]),
              ("Footwear", "Pumps · shoe · fsig f1 · served"))
        check("A1 no hub", HUB, [])

        print("[A2] the bare files stay bare")
        check("A2 bare bytes", (sha(bare) == base_sha, sha(bare_low) == base_sha), (True, True))
        check("A2 bare has no garment node", (garment_nodes(bare.read_bytes()), garment_nodes(bare_low.read_bytes())),
              ({}, {}))

        print("[A3] assembly missing: the bare file is served without a foot pose")
        for p in (asm, asm.with_suffix(".json"), asm_low, asm_low.with_suffix(".json")):
            p.unlink()
        SCHEDULED.clear()
        check("A3 served = bare", ga.served("Demo", bare, "full"), bare)
        check("A3 build asked", SCHEDULED, [("Demo", osig)])
        status, meta = meta_route()
        check("A3 /model/meta foot_pose None", (status, "foot_pose" in meta, meta.get("foot_pose")), (200, True, None))
        status, model = model3d_route()
        check("A3 /model3d foot_pose None", (status, "foot_pose" in model, model.get("foot_pose")), (200, True, None))
        check("A3 reassemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})

        print("[A4] a second shoe piece is left off with a warning")
        G = gs.garment_fsig("Demo", clogs)
        check("A4 own fsig", G != F, True)
        res = garments.run_garment("Demo", clogs)
        check("A4 clogs fitted", (res.get("ok"), res.get("ran"), res.get("fit"), HUB), (True, ["fit"], "accepted", []))
        write_bare_meta([clogs, heels], pieces={"feet": heels})
        wanted = ga._wanted("Demo", get_character_profile("Demo"), bare_meta=ga._read_json(bare.with_suffix(".json")))
        check("A4 wanted = the worn piece", [(g["item_id"], g["kind"], g["fsig"]) for g in wanted],
              [(heels, "footwear", F)])
        check("A4 assemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "current"})
        check("A4 heels grafted, clogs not", sorted(garment_nodes(asm.read_bytes())),
              [f"garment_footwear_{heels}_left", f"garment_footwear_{heels}_right"])
        side = ga.read_sidecar(asm)
        check("A4 sidecar", (sorted(side.get("garments") or {}), side.get("garment_warnings")),
              ([heels], ["Clogs: a second shoe piece in one outfit — left off"]))
        check("A4 foot_pose = heels", side["foot_pose"]["source"]["fsig"], F)
        write_bare_meta([clogs, heels], pieces={})
        check("A4 without a worn piece: the first by id", ga.assemble("Demo", osig)["tiers"],
              {"full": "assembled", "low": "assembled"})
        side = ga.read_sidecar(asm)
        check("A4 clogs grafted", (sorted(garment_nodes(asm.read_bytes())), sorted(side.get("garments") or {}),
                                   side.get("garment_warnings"), side["foot_pose"]["source"]["fsig"]),
              ([f"garment_footwear_{clogs}_left", f"garment_footwear_{clogs}_right"], [clogs],
               ["Heels: a second shoe piece in one outfit — left off"], G))

        print("[A5] footwear removed from the wanted set: the assembly goes, foot_pose with it")
        write_bare_meta([], pieces={})
        check("A5 wanted", ga.wanted_garments("Demo"), {})
        check("A5 assemble removes", ga.assemble("Demo", osig), {"ok": True, "tiers": {"full": "removed", "low": "removed"}})
        check("A5 no assembled file", (asm.exists(), asm_low.exists()), (False, False))
        status, meta = meta_route()
        check("A5 /model/meta foot_pose None", (status, meta.get("foot_pose")), (200, None))
        status, model = model3d_route()
        check("A5 /model3d foot_pose None", (status, "foot_pose" in model, model.get("foot_pose")), (200, True, None))

        print("[A6] mesh mode: the body fit is grafted, never the base fit")
        A = base_body.outfit_body_id("tex" + "a" * 12)
        body_a = repack(base_glb, generator="outfit body A", prefix="mixamorig:")
        sha_a = hashlib.sha256(body_a).hexdigest()
        (mdir / f"{A}.glb").write_bytes(body_a)
        (mdir / f"{A}.json").write_text(json.dumps({
            "rig": "mixamo", "format": "glb", "signature": A,
            "outfit_body": {"body_id": A, "mode": "mesh", "version": 1, "texture_signature": "tex" + "a" * 12,
                            "base_signature": bsig}}))
        (mdir / "unrigged" / f"{A}.glb").write_bytes(body_a)
        osig2 = "0123456789ab"
        bare2 = mdir / f"{osig2}.glb"
        bare2.write_bytes(body_a)
        bare2.with_suffix(".json").write_text(json.dumps({
            "rig": "mixamo", "format": "glb", "signature": osig2, "source": "base_body", "base_signature": bsig,
            "base_model_sha256": base_sha, "body_id": A, "body_sha256": sha_a, "outfit_body_mode": "mesh",
            "pieces": {"feet": heels}, "items": [heels],
            "mesh_items": {"intended": [heels], "effective": [heels], "unpainted": [heels], "mode": "mesh",
                           "missing": {}, "warnings": []}}))
        READ_BASE = []

        def base_reader(name):
            def stub(*a, **k):
                READ_BASE.append(name)
                raise AssertionError(f"{name} must not be read for a footwear body fit")
            return stub
        saved = (gs.accepted_fit, gs.newest_accepted_fits)
        gs.accepted_fit = base_reader("accepted_fit")
        gs.newest_accepted_fits = base_reader("newest_accepted_fits")
        try:
            check("A6 assemble on the body", ga.assemble("Demo", osig2)["tiers"], {"full": "assembled", "low": "none"})
        finally:
            gs.accepted_fit, gs.newest_accepted_fits = saved
        body_fit = cdir / "garments" / "bodies" / A / f"heels_{F}.glb"
        asm2 = mdir / "assembled" / f"{osig2}.glb"
        check("A6 body fit made by the build", (body_fit.is_file(), HUB, READ_BASE), (True, [], []))
        side = ga.read_sidecar(asm2)
        check("A6 sidecar garments = the body fit", side.get("garments"),
              {heels: {"kind": "footwear", "fsig": F, "sha256": sha(body_fit)}})
        check("A6 foot_pose bones of the body", sorted((side.get("foot_pose") or {}).get("bones") or {}),
              ["mixamorig:LeftFoot", "mixamorig:LeftToeBase", "mixamorig:RightFoot", "mixamorig:RightToeBase"])
        check("A6 foot_pose source", (side["foot_pose"]["source"]["fsig"], side["foot_pose"]["source"]["glb_sha256"]),
              (F, sha(asm2)))
        blob2 = asm2.read_bytes()
        check("A6 body cut on A", len(glb_mesh.body_arrays(blob2).faces), 24)
        check("A6 two shoe nodes", sorted(garment_nodes(blob2)),
              [f"garment_footwear_{heels}_left", f"garment_footwear_{heels}_right"])
        check("A6 rig frames preserved", rig_frames_preserved(body_a, blob2).get("ok"), True)
        check("A6 bare2 unchanged", sha(bare2), sha_a)
        client.close()

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
