#!/usr/bin/env python3
"""Hair as its own mesh, task 7: the assembly layer and its serving
(app/core/garment_assembly.py + the model3d / route / GC hooks).

Usage:
    ./.venv/bin/python scripts/smoke_garment_assembly.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no Blender, no GPU, no server
process. Synthetic GLBs only (the body/garment fixtures of
``smoke_glb_graft.py``). Stubs: ``model3d.request_lod`` (recorder — no
Blender), ``glb_delivery.delivery_path`` (identity), the backend listings of
the meta route (empty — no network probe), the extension bone
context (``breast_L`` under Spine2, the fixture's inserted bone) and
``garment_assembly.schedule`` (recorder, except where the real one is named).

Fixture: ``Demo`` (human-roleplay, female, on the base-body pipeline, hair
slot medium/blonde). H = ensure_hair_item(Demo) ("hair_demo", equipped in
the ``hair`` mesh slot). BSIG = base_signature(Demo); the base views are fake
PNGs, the base model model3d/BSIG.glb = b"base-model" -> SHA. OSIG = the
current outfit signature; model3d/OSIG.glb = the fixture body (53 joints,
one mesh ``Body``), sidecar {rig mixamo, base_signature BSIG,
base_model_sha256 SHA}. F = garment_fsig(Demo, H); the fit
garments/H_F.glb = graft(body, garment G4 (4 vertices), name
"garment_hair_hair_demo"), record {accepted: true, base_model_sha256: SHA}.

Expected, derived by hand from plan R11/R12 and the Task 7 brief:

[1] H unequipped: wanted_garments = {}; served(bare, full) is the bare path;
    versioned_model_urls = {"url": <base>?v=<content_version(bare)>} — the
    same dict as with served() patched to identity; model_revision(bare) =
    sha256 of the pre-task tier records [["full", true, size, mtime, ino],
    ["low", false, 0, 0, 0]] (no assembled record without an assembly);
    no schedule.
[2] H equipped but Demo off the pipeline -> wanted {} and served = bare.
[3] Back on the pipeline, before any build: wanted = {H: (fit, None, record)};
    served(full) = bare and schedule(Demo, OSIG) recorded.
[4] assemble(Demo, OSIG) -> {full: assembled, low: none}; assembled/OSIG.glb
    holds a node "garment_hair_hair_demo" with extras.garment {kind hair,
    item_id H, fsig F}; sidecar garments = {H: {kind hair, fsig F, sha256
    sha(fit)}}, bare_revision = bare_revision(bare), rig mixamo (copied);
    the bare OSIG.glb is byte-identical (sha) and has NO garment node;
    served(full) = the assembled path; model_revision(bare) changes;
    versioned url v = content_version(assembled); the publication token is
    unchanged (assembled files are no publication input); changed_at(Demo)
    was called. Routes (admin): GET model3d/file -> the assembled bytes,
    GET model/meta -> size = assembled size + garments, download=true -> the
    bare bytes (a download may be re-uploaded: a stored model stays bare).
    A second assemble -> {full: current}.
[5] Low tier. No bare low: ?tier=low serves the assembled FULL bytes (the
    tier fallback is unchanged), no low_url. Bare low written + garment low
    G3 (3 vertices) -> served(low) = bare low + schedule; assemble ->
    {full: current, low: assembled}; the low garment node has 3 vertices,
    the low sidecar sha256 = sha(G3 file); ?tier=low serves assembled low;
    low_url v = content_version(assembled low). G3 deleted -> served(low) is
    the bare low (state moved); assemble -> low rebuilt with the full fit
    (4 vertices), sha256 = sha(fit).
[6] Bare full republished (same bytes, new inode) -> served(full) = bare +
    schedule; the file route serves the BARE bytes (never the old assembly);
    model_revision changes; assemble -> {full: assembled, low: current}.
[7] Re-fit: the fit rewritten with G4 moved +1 cm (new sha) -> served(full)
    = bare + schedule; assemble rebuilds both tiers.
[8] Real schedule: bare republished again -> schedule(Demo, OSIG) True,
    after wait_idle served(full) = assembled. A broken fit file (garbage
    bytes, accepted record) -> the build fails, the bare file keeps being
    served, and schedule with the same inputs is refused (False); the fit
    restored -> schedule True again.
[9] _publish_signature (model3d) with a stage holding the non-assembled
    files of OSIG:
    (a) nothing changed -> both assemblies stay;
    (b) bare full rewritten in the stage -> assembled/OSIG.glb + .json gone,
        assembled/low/OSIG.* kept (the low bare did not change);
    (c) bare full rewritten + assemble(tiers=(full,)) INSIDE the stage ->
        assembled/OSIG.glb published, its bare_revision restamped to the
        published bare, served(full) = assembled.
[10] A staged op (a _serial_model probe) that rewrites the bare and calls
    schedule: the build request runs only AFTER the publication (the real
    bare already holds the new bytes when it fires), once.
[11] _purge_combination(OSIG) removes assembled/OSIG.* and
    assembled/low/OSIG.*. GC: a stale signature aaaaaaaaaaaa (pieces
    {top: missing_item}) with model + assembled files is reported stale,
    _mesh_files lists its assembled files, purge_stale removes them.
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


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def republish(path: Path, data: bytes) -> None:
    """Write like a publication does: a sibling temp file + os.replace (new inode)."""
    staging = path.with_name(f".{path.name}.staging")
    staging.write_bytes(data)
    os.replace(staging, path)


def node_names(glb: bytes):
    from app.core.model_validate import parse_glb
    return [n.get("name") for n in parse_glb(glb)["gltf"].get("nodes", [])]


def garment_node(glb: bytes, name: str):
    from app.core import glb_mesh
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf = parsed["gltf"]
    node = next(n for n in gltf["nodes"] if n.get("name") == name)
    prim = gltf["meshes"][node["mesh"]]["primitives"][0]
    count = glb_mesh.accessor_array(parsed, prim["attributes"]["POSITION"]).shape[0]
    return node, count


def old_revision(path: Path) -> str:
    """model_revision before this task: the two tier records only."""
    records = []
    for tier, candidate in (("full", path), ("low", path.parent / "low" / path.name)):
        try:
            st = candidate.stat()
            records.append((tier, True, st.st_size, st.st_mtime_ns, st.st_ino))
        except OSError:
            records.append((tier, False, 0, 0, 0))
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-assembly-") as tmp:
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

        import smoke_glb_graft as fx
        from app.core import (base_body, extension_rig, garment_assembly as ga, garment_hair,
                              garment_store as gs, glb_delivery, model3d, model_refs, sync_topics)
        from app.core import outfit_cache_gc as gc
        from app.core.http_files import content_version
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        # --- stubs -----------------------------------------------------------
        SCHEDULED = []
        LOD = []
        CHANGED = []
        real_schedule = ga.schedule
        ga.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model3d.request_lod = lambda name, path: LOD.append(path.name) or False
        glb_delivery.delivery_path = lambda path, source=None: path
        extension_rig.extension_bone_names = lambda *a, **k: {
            "breast_L": {"parent": "mixamorig:Spine2", "group": "chest"}}
        # The meta route lists the configured backends: no probing from a smoke.
        from app.imagegen import service

        class _NoBackends:
            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []
        service.get_image_service = lambda: _NoBackends()
        model3d.list_mesh_backends = lambda *a, **k: {}
        model3d.list_rig_backends = lambda *a, **k: []
        from app.imagegen import routing
        routing.explain_occasion = lambda *a, **k: {}
        real_changed = sync_topics.changed_at
        sync_topics.changed_at = lambda name, *a, **k: CHANGED.append(name)

        # --- fixture ---------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair with a side parting",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair item", (hid, inventory.get_equipped_mesh_pieces("Demo")), ("hair_demo", {"hair": "hair_demo"}))
        cdir = get_character_dir("Demo")
        bsig = base_body.base_signature("Demo")
        osig = model_refs.current_outfit_state("Demo")[2]
        refs = cdir / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / f"tpose_{bsig}.png").write_bytes(b"\x89PNG-front-" + b"a" * 40)
        (refs / f"tpose_back_{bsig}.png").write_bytes(b"\x89PNG-back-" + b"b" * 40)
        mdir = model3d.get_model3d_dir("Demo")
        (mdir / f"{bsig}.glb").write_bytes(b"base-model")
        base_sha = hashlib.sha256(b"base-model").hexdigest()
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))
        body, _names = fx.body_fixture()
        bare = mdir / f"{osig}.glb"
        bare.write_bytes(body)
        bare_meta = {"rig": "mixamo", "format": "glb", "signature": osig, "source": "base_body",
                     "base_signature": bsig, "base_model_sha256": base_sha, "pieces": {}, "items": []}
        bare.with_suffix(".json").write_text(json.dumps(bare_meta))
        bare_sha = sha(bare)
        fsig = gs.garment_fsig("Demo", hid)
        node_name = f"garment_hair_{hid}"
        extras = {"kind": "hair", "item_id": hid, "fsig": fsig}

        from app.core import glb_mesh
        g4 = fx.garment()
        fit = gs.garment_path("Demo", hid, fsig, "fit")
        fit.parent.mkdir(parents=True, exist_ok=True)
        fit_bytes = glb_mesh.graft(body, g4, name=node_name, extras=extras)
        fit.write_bytes(fit_bytes)
        gs.write_record(fit.with_suffix(".json"), {"accepted": True, "base_model_sha256": base_sha})

        enc = "/characters/Demo/model3d/file"

        print("[1] no garment worn")
        check("unequip", inventory.unequip_mesh_piece("Demo", "hair"), True)
        SCHEDULED.clear()
        check("wanted", ga.wanted_garments("Demo"), {})
        check("served = bare", ga.served("Demo", bare, "full"), bare)
        urls = model3d.versioned_model_urls("Demo", enc)
        check("urls", urls, {"url": f"{enc}?v={content_version(bare)}"})
        real_served = ga.served
        ga.served = lambda name, path, tier: path
        try:
            check("urls without the layer", model3d.versioned_model_urls("Demo", enc), urls)
        finally:
            ga.served = real_served
        rev_bare = model3d.model_revision(bare)
        check("model_revision unchanged formula", rev_bare, old_revision(bare))
        check("no schedule", SCHEDULED, [])

        print("[2] off the pipeline")
        check("equip", inventory.equip_mesh_piece("Demo", hid), True)
        check("pipeline off", base_body.set_pipeline("Demo", False), True)
        check("wanted off pipeline", ga.wanted_garments("Demo"), {})
        check("served off pipeline", ga.served("Demo", bare, "full"), bare)
        check("pipeline on", base_body.set_pipeline("Demo", True), True)

        print("[3] wanted, not built")
        SCHEDULED.clear()
        wanted = ga.wanted_garments("Demo")
        check("wanted", {k: (v[0], v[1], v[2].get("accepted")) for k, v in wanted.items()},
              {hid: (fit, None, True)})
        check("served = bare", ga.served("Demo", bare, "full"), bare)
        check("scheduled", SCHEDULED, [("Demo", osig)])

        print("[4] assemble")
        with keyed_lock("model3d_publication", str(mdir)):
            token = model3d._publication_token(mdir, osig)
        CHANGED.clear()
        res = ga.assemble("Demo", osig)
        check("result", res, {"ok": True, "tiers": {"full": "assembled", "low": "none"}})
        asm = mdir / "assembled" / f"{osig}.glb"
        check("assembled exists", asm.is_file(), True)
        node, count = garment_node(asm.read_bytes(), node_name)
        check("garment node", (node.get("extras"), count), ({"garment": extras}, 4))
        side = json.loads(asm.with_suffix(".json").read_text())
        check("sidecar garments", side.get("garments"),
              {hid: {"kind": "hair", "fsig": fsig, "sha256": sha(fit)}})
        check("sidecar bare_revision", side.get("bare_revision"), ga.bare_revision(bare))
        check("sidecar copies bare meta", (side.get("rig"), side.get("base_signature")), ("mixamo", bsig))
        check("bare unchanged", sha(bare), bare_sha)
        check("bare has no garment node", [n for n in node_names(bare.read_bytes()) if n and n.startswith("garment_")],
              [])
        check("served = assembled", ga.served("Demo", bare, "full"), asm)
        check("model_revision changed", model3d.model_revision(bare) != rev_bare, True)
        check("url = assembled", model3d.versioned_model_urls("Demo", enc),
              {"url": f"{enc}?v={content_version(asm)}"})
        with keyed_lock("model3d_publication", str(mdir)):
            check("token ignores assembled", model3d._publication_token(mdir, osig), token)
        check("changed_at", CHANGED, ["Demo"])
        check("management path stays bare", (model3d.find_model3d("Demo"), model3d.find_model3d_serving("Demo")[0]),
              (bare, bare))

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import sessions, users
        from app.routes.characters import router
        uid = users.create_user("demo-admin", "temporary-smoke-password", users.ROLE_ADMIN,
                                allowed_characters=["Demo"])
        token_admin = sessions.create_session(uid)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=True)
        client.cookies.set(sessions.SESSION_COOKIE_NAME, token_admin)

        def fetch(query=""):
            r = client.get(f"/characters/Demo/model3d/file{query}")
            return r.status_code, r.content

        check("route serves assembled", fetch() == (200, asm.read_bytes()), True)
        check("legacy route serves assembled", client.get("/characters/Demo/model").content == asm.read_bytes(), True)
        r = client.get("/characters/Demo/model/meta")
        meta = r.json() if r.status_code == 200 else {}
        check("meta size + garments", (r.status_code, meta.get("size"), sorted((meta.get("garments") or {}))),
              (200, asm.stat().st_size, [hid]))
        check("download stays bare", fetch("?download=true") == (200, bare.read_bytes()), True)
        check("second assemble", ga.assemble("Demo", osig, tiers=("full",)),
              {"ok": True, "tiers": {"full": "current"}})

        print("[5] low tier")
        LOD.clear()
        check("low fallback = assembled full", fetch("?tier=low") == (200, asm.read_bytes()), True)
        check("no low_url", sorted(model3d.versioned_model_urls("Demo", enc)), ["url"])
        bare_low = mdir / "low" / f"{osig}.glb"
        bare_low.parent.mkdir(exist_ok=True)
        bare_low.write_bytes(body)
        bare_low.with_suffix(".json").write_text(json.dumps({"rig": "mixamo", "tier": "low", "signature": osig}))
        g3 = glb_mesh.GarmentMesh(positions=g4.positions[:3], normals=g4.normals[:3], uvs=g4.uvs[:3],
                                  indices=np.array([[0, 1, 2]]), joints=g4.joints[:3], weights=g4.weights[:3],
                                  joint_names=g4.joint_names, image=g4.image, mime=g4.mime,
                                  material=g4.material)
        glow = gs.garment_path("Demo", hid, fsig, "low")
        glow.parent.mkdir(parents=True, exist_ok=True)
        glow.write_bytes(glb_mesh.graft(body, g3, name=node_name, extras=extras))
        SCHEDULED.clear()
        check("served low = bare low", ga.served("Demo", bare_low, "low"), bare_low)
        check("scheduled low", SCHEDULED, [("Demo", osig)])
        check("assemble low", ga.assemble("Demo", osig), {"ok": True, "tiers": {"full": "current", "low": "assembled"}})
        asm_low = mdir / "assembled" / "low" / f"{osig}.glb"
        check("low node uses the low garment", garment_node(asm_low.read_bytes(), node_name)[1], 3)
        check("low sidecar sha", json.loads(asm_low.with_suffix(".json").read_text())["garments"][hid]["sha256"],
              sha(glow))
        check("route low = assembled low", fetch("?tier=low") == (200, asm_low.read_bytes()), True)
        check("low_url", model3d.versioned_model_urls("Demo", enc).get("low_url"),
              f"{enc}?tier=low&v={content_version(asm_low)}")
        glow.unlink()
        check("garment low gone -> bare low", ga.served("Demo", bare_low, "low"), bare_low)
        check("assemble low from fit", ga.assemble("Demo", osig)["tiers"], {"full": "current", "low": "assembled"})
        check("low node from the fit", garment_node(asm_low.read_bytes(), node_name)[1], 4)
        check("low sidecar sha = fit", json.loads(asm_low.with_suffix(".json").read_text())["garments"][hid]["sha256"],
              sha(fit))

        print("[6] bare republished")
        rev_before = model3d.model_revision(bare)
        republish(bare, body)
        SCHEDULED.clear()
        check("served = bare", ga.served("Demo", bare, "full"), bare)
        check("scheduled", SCHEDULED, [("Demo", osig)])
        check("route serves bare, not the old assembly", fetch() == (200, bare.read_bytes()), True)
        check("model_revision moved", model3d.model_revision(bare) != rev_before, True)
        check("reassemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "current"})
        check("served = assembled", ga.served("Demo", bare, "full"), asm)

        print("[7] re-fit")
        moved = glb_mesh.GarmentMesh(**{**g4.__dict__, "positions": g4.positions + np.array([0, 0, 0.01])})
        republish(fit, glb_mesh.graft(body, moved, name=node_name, extras=extras))
        SCHEDULED.clear()
        check("served = bare after re-fit", ga.served("Demo", bare, "full"), bare)
        check("scheduled", SCHEDULED, [("Demo", osig)])
        check("reassemble both", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})
        check("new sha in sidecar", json.loads(asm.with_suffix(".json").read_text())["garments"][hid]["sha256"],
              sha(fit))

        print("[8] real schedule")
        republish(bare, body)
        check("schedule started", real_schedule("Demo", osig), True)
        check("idle", ga.wait_idle(30), True)
        check("served = assembled after the background build", ga.served("Demo", bare, "full"), asm)
        good_fit = fit.read_bytes()
        republish(fit, b"not a glb")
        check("schedule broken fit", real_schedule("Demo", osig), True)
        check("idle", ga.wait_idle(30), True)
        check("broken fit serves bare", ga.served("Demo", bare, "full"), bare)
        check("same inputs not retried", real_schedule("Demo", osig), False)
        republish(fit, good_fit)
        check("restored fit retried", real_schedule("Demo", osig), True)
        check("idle", ga.wait_idle(30), True)
        check("served = assembled", ga.served("Demo", bare, "full"), asm)

        print("[9] staged publication")
        asm_low_sha = sha(asm_low)

        def make_stage():
            stage = Path(tempfile.mkdtemp(prefix=".process-", dir=mdir))
            for rel, src in model3d._signature_files(mdir, osig).items():
                if rel.parts[0] == "assembled":
                    continue
                target = stage / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
            with keyed_lock("model3d_publication", str(mdir)):
                tok = model3d._publication_token(mdir, osig)
            return stage, tok

        # Another valid body: the same fixture with one more declared extension.
        body2 = fx.body_fixture(extensions=["KHR_materials_emissive_strength"])[0]
        check("body2 differs", body2 != body, True)
        stage, tok = make_stage()
        asm_sha = sha(asm)
        check("(a) no-op publish", model3d._publish_signature("Demo", mdir, stage, osig, tok) is not None, True)
        check("(a) assemblies kept", (asm.is_file() and sha(asm) == asm_sha, sha(asm_low) == asm_low_sha), (True, True))
        shutil.rmtree(stage)
        stage, tok = make_stage()
        (stage / f"{osig}.glb").write_bytes(body2)
        check("(b) publish", model3d._publish_signature("Demo", mdir, stage, osig, tok) is not None, True)
        check("(b) full assembly dropped", (asm.exists(), asm.with_suffix(".json").exists()), (False, False))
        check("(b) low assembly kept", sha(asm_low), asm_low_sha)
        shutil.rmtree(stage)
        stage, tok = make_stage()
        (stage / f"{osig}.glb").write_bytes(body)
        model3d._staging.directories = {"Demo": stage}
        try:
            check("(c) assemble in stage", ga.assemble("Demo", osig, tiers=("full",)),
                  {"ok": True, "tiers": {"full": "assembled"}})
        finally:
            model3d._staging.directories = {}
        check("(c) publish", model3d._publish_signature("Demo", mdir, stage, osig, tok) is not None, True)
        shutil.rmtree(stage)
        check("(c) assembly published", asm.is_file(), True)
        check("(c) restamped", json.loads(asm.with_suffix(".json").read_text())["bare_revision"],
              ga.bare_revision(bare))
        check("(c) served = assembled", ga.served("Demo", bare, "full"), asm)

        print("[10] deferred schedule from a staged op")
        FIRED = []
        real_run = ga._run

        def fake_run(key):
            FIRED.append((key, model3d._read_sidecar(bare).get("probe")))
            with ga._lock:
                ga._building.discard(key)
        ga._run = fake_run
        ga.schedule = real_schedule

        @model3d._serial_model
        def probe_op(character_name, signature=None):
            path = model3d.get_model3d_dir(character_name) / f"{signature}.glb"
            meta = model3d._read_sidecar(path)
            meta["probe"] = True
            model3d._publish_sidecar(path, meta)
            check("inside the stage: deferred", ga.schedule(character_name, signature), True)
            check("not fired inside the stage", FIRED, [])
            return {"ok": True}
        try:
            check("probe ok", probe_op("Demo", signature=osig), {"ok": True})
        finally:
            ga._run = real_run
            ga.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        check("idle", ga.wait_idle(30), True)
        check("fired once, after the publication", FIRED, [(("Demo", osig), True)])
        check("full assembly dropped by the sidecar change", asm.exists(), False)

        print("[11] purge + GC")
        check("rebuild", ga.assemble("Demo", osig)["tiers"]["full"], "assembled")
        model3d._purge_combination(mdir, osig, keep_model=bare)
        check("purge drops assemblies", (asm.exists(), asm_low.exists(),
                                         asm.with_suffix(".json").exists()), (False, False, False))
        stale = "aaaaaaaaaaaa"
        (mdir / f"{stale}.glb").write_bytes(body)
        (mdir / f"{stale}.json").write_text(json.dumps({"rig": "mixamo", "pieces": {"top": "missing_item"},
                                                        "items": []}))
        for rel in (f"assembled/{stale}.glb", f"assembled/{stale}.json",
                    f"assembled/low/{stale}.glb", f"assembled/low/{stale}.json"):
            (mdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (mdir / rel).write_bytes(b"x")
        files = sorted(str(p.relative_to(mdir)) for p in gc._mesh_files("Demo").get(stale, []))
        check("GC lists assembled files", [f for f in files if f.startswith("assembled")],
              [f"assembled/{stale}.glb", f"assembled/{stale}.json",
               f"assembled/low/{stale}.glb", f"assembled/low/{stale}.json"])
        report = gc.verify_cache("Demo")
        check("stale reported", stale in report["stale_signatures"], True)
        gc.purge_stale("Demo", [stale])
        check("GC purge removed assembled", sorted(p.name for p in (mdir / "assembled").rglob(f"{stale}.*")), [])
        check("bare stays bare", [n for n in node_names(bare.read_bytes()) if n and n.startswith("garment_")], [])

        sync_topics.changed_at = real_changed
        client.close()

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
