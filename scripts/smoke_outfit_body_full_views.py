#!/usr/bin/env python3
"""Outfit body in mesh mode: EVERY dressed view or no mesh (ruling 2026-11-10,
spec docs/superpowers/specs/2026-11-10-outfit-body-mesh-mode-design.md).

Finding (logs 2026-11-10 22:05, Kira; 21:37, Kai): "Regenerate · Main view"
renders the dressed FRONT alone (``tpose_view="main"`` -> ``generate_dressed_images
(view="front")``); the T-pose lane's auto-mesh hook then built the outfit body
and ``prepare_outfit_body`` meshed whatever views existed — a UniForge job
from ['front'], wasted once the back arrived. A restart resumed that record
with images=1.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_full_views.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no server. Stubs as
smoke_outfit_body_mesh: the image service (``generate_mesh`` / ``generate_rig``
write fixture GLBs, each call ONE HUB JOB), ``expression_regen.render_character_image``
(one call = ONE IMAGE JOB), the post-steps as no-op recorders. Every image
and mesh job goes into EVENTS in call order. The dressed-view render, the
fit gate, the view guard, the texture store, ``prepare_outfit_body``, the
hub-op records and the registered resume entry are REAL.

Fixture: Demo (on the pipeline, side views OFF -> dressed views front + back,
``outfit_body_mode: "mesh"``); items under {[underwear_bottom]}, shoes
{[feet]}, skirt {[bottom]}. Outfits: A {under, shoes}; G {under, shoes,
skirt}; H {under, skirt}; K {shoes, skirt}; L {shoes} — five different dress
texts, so five tsigs and five bodies.

Expected, derived by hand from the ruling:

[0] Message rule: views_missing_message(["back"], ["front"]) =
    "Back view missing — not meshed from the front alone";
    (["back", "left"], ["front", "right"]) = "Back and left views missing —
    not meshed from the front and right alone"; a reason goes in brackets.
[1] A, front only ("Regenerate · Main view"): 1 image job (the front edit),
    no back. The build then renders the back FIRST — EVENTS of the build =
    [image back draft, image back fit, mesh <bA>]: exactly 1 mesh job, its
    inputs the front + views {back} (images=2); the body's parent record
    used_views [front, back]; ok.
[2] G, front only, the back REFUSED (``_dress_view`` raises OutfitError
    "fit refused"): the build makes 0 mesh jobs and 0 hub-op records; result
    ok False, error "Back view missing — not meshed from the front alone (fit
    refused)"; outfit_info(G) status "failed" with that error; no body file.
    The refusal lifted: the next build renders the back (2 image jobs) and
    meshes ONCE with views {back}.
[3] H, every view rendered beforehand (no view picked: 3 image jobs): the
    build makes 0 image jobs and exactly 1 mesh job with views {back}.
[4] Resume of a front-only record (K): a build with the OLD behaviour
    (dressed views patched to ("front",)) dies in its mesh job (a
    BaseException, as a process death) and leaves its record: views sent
    {front} only. Back to front + back, the registered resume entry of
    "character_mesh" DROPS it: 0 mesh jobs, the record is gone, outfit_info(K)
    "failed" with "Back view missing — not meshed from the front alone — its
    mesh job from before the restart was dropped".
[5] Control (L): the same death with front + back sent -> the resume entry
    resumes it: exactly 1 mesh job, ok, the record is gone.
"""
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = []
BASE_PX = {"front": (200, 10, 10), "back": (10, 200, 10), "left": (10, 10, 200), "right": (200, 200, 10)}
FRAG = {"under": "plain grey underwear", "shoes": "white sneakers", "skirt": "a blue pleated skirt"}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(rgb, size=8) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(out, "PNG")
    return out.getvalue()


def colour_of(name: str):
    d = hashlib.md5(name.encode()).digest()
    return d[0], d[1], d[2]


def fixture_glb(rig: bool = False) -> bytes:
    from app.core.rig_contract import BASE_JOINT_NAMES
    color = png((180, 120, 90), 16)
    doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"material": 0}]}],
           "buffers": [{"byteLength": len(color)}],
           "bufferViews": [{"byteOffset": 0, "byteLength": len(color)}],
           "images": [{"bufferView": 0, "mimeType": "image/png"}],
           "textures": [{"source": 0}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    if rig:
        doc["nodes"] = [{"name": n} for n in BASE_JOINT_NAMES]
        doc["skins"] = [{"joints": list(range(len(BASE_JOINT_NAMES)))}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    color += b"\0" * (-len(color) % 4)
    body = (struct.pack("<II", len(raw), 0x4e4f534a) + raw
            + struct.pack("<II", len(color), 0x004e4942) + color)
    return b"glTF" + struct.pack("<II", 2, len(body) + 12) + body


class _Died(BaseException):
    """A process death: passes every ``except Exception``, settles nothing."""


EVENTS, MESH_CALLS, CREATED = [], [], []
DIE = {"mesh": False}


class FakeService:
    def generate_mesh(self, *, source_image_path, output_path, view_images=None, occasion="", **kw):
        if DIE["mesh"]:
            raise _Died("process gone")
        stem = Path(output_path).stem
        EVENTS.append(("mesh", stem))
        MESH_CALLS.append({"source": Path(source_image_path).name, "views": sorted(view_images or {})})
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fixture_glb())
        return {"ok": True, "path": output_path, "backend": "fake-mesh"}

    def generate_rig(self, *, mesh_path, output_path, rig, **kw):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fixture_glb(True))
        return {"ok": True, "path": output_path, "backend": "fake-rig", "rig": rig}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-body-full-views-") as tmp:
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

        import smoke_garment_chain as chain
        from app.core import (base_body, collision, expression_regen, extension_rig, glb_delivery, hub_ops,
                              model3d, model_refs, sync_topics)
        from app.imagegen import service
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        # --- stubs -------------------------------------------------------------
        def rembg(data, model="u2net", **kw):
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                rgba = im.convert("RGBA")
            for x in range(8):
                for y in range(8):
                    if min(x, y) < 2 or max(x, y) > 5:
                        rgba.putpixel((x, y), (0, 0, 0, 0))
            out = io.BytesIO()
            rgba.save(out, "PNG")
            return out.getvalue()

        def render(character_name, *, output_stem, equipped_pieces, equipped_items, **kw):
            from PIL import Image
            EVENTS.append(("image", Path(output_stem).name))
            target = Path(str(output_stem) + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), colour_of(target.stem)).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            token = model_refs.mesh_items_token(character_name, equipped_pieces, profile)
            meta = {"prompt": kw.get("bare_prompt") or "", "equipped_pieces": equipped_pieces or {},
                    "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    "created_at": f"2026-11-10T00:00:{len(EVENTS) % 60:02d}+00:00",
                    **({"mesh_token": token} if token else {}), **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        def recording_create(kind, subject, inputs, **kw):
            CREATED.append(json.loads(json.dumps(inputs)))
            return real_create(kind, subject, inputs, **kw)

        def noop(*a, **k):
            return None

        real_create = hub_ops.create
        expression_regen.render_character_image = render
        charmod.run_rembg = rembg
        service.get_image_service = lambda: FakeService()
        hub_ops.create = recording_create
        model3d._auto_retexture = noop
        model3d._auto_normalize = noop
        model3d._extension_rig_once = lambda *a, **k: {"ok": True, "noop": True}
        collision.refresh = lambda *a, **k: False
        model3d._attach_measurement = noop
        model3d._auto_lod_enabled = lambda: False
        model3d.maybe_auto_generate_for_outfit = lambda *a, **k: False
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None
        model_refs.trigger_now = lambda *a, **k: None
        model_refs.schedule_outfit_render = lambda name: None
        config._CONFIG.setdefault("base_body", {})["dressed_side_views"] = False

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(png((50, 60, 70)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        stored["outfit_body_mode"] = "mesh"
        check("profile", save_character_profile("Demo", stored), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        check("mode mesh", base_body.outfit_body_mode("Demo"), "mesh")
        check("dressed views", base_body.dressed_views(), ("front", "back"))

        for item_id, slot in (("under", "underwear_bottom"), ("shoes", "feet"), ("skirt", "bottom")):
            inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                               prompt_fragment=FRAG[item_id],
                               outfit_piece={"slots": [slot], "covers": [], "outfit_types": ["casual"]})
            inventory.add_to_inventory("Demo", item_id)

        def wear(pieces):
            stored = get_character_profile("Demo")
            stored["equipped_pieces"] = dict(pieces)
            save_character_profile("Demo", stored)
            return model_refs.current_outfit_state("Demo")[2]

        cdir = get_character_dir("Demo")
        refs = cdir / "model_refs"
        mdir = cdir / "model3d"
        refs.mkdir(parents=True, exist_ok=True)
        b1 = base_body.base_signature("Demo")
        from PIL import Image
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            im.putpixel((4, 4), BASE_PX[v] + (255,))
            im.save(refs / f"{stem}.png")
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        unrigged, rigged = chain.base_bodies((200, 160, 140))
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged)
        (mdir / f"{b1}.glb").write_bytes(rigged)
        (mdir / f"{b1}.json").write_text(json.dumps({
            "base": True, "rig": "mixamo", "signature": b1, "format": "glb", "source": "generated"}))

        def render_views(view=None):
            e0 = len(EVENTS)
            model_refs.generate_model_ref_images("Demo", kinds=("tpose",), tpose_view=view)
            return [e for e in EVENTS[e0:] if e[0] == "image"]

        def build():
            e0, c0 = len(EVENTS), len(CREATED)
            result = model3d.generate_for_current_outfit("Demo")
            return result, EVENTS[e0:], len(CREATED) - c0

        def dressed(sig, view):
            return base_body.dressed_image("Demo", view, sig, b1) is not None

        def body_of(sig):
            front = base_body.dressed_image("Demo", "front", sig, b1)
            tsig = base_body._outfit_texture("Demo", front, bsig=b1, profile=get_character_profile("Demo"))["tsig"]
            return base_body.outfit_body_id(tsig)

        def kinds(events):
            return [e[0] for e in events]

        # --- [0] ------------------------------------------------------------------------
        print("[0] message rule")
        check("one view", base_body.views_missing_message(["back"], ["front"]),
              "Back view missing — not meshed from the front alone")
        check("two views", base_body.views_missing_message(["back", "left"], ["front", "right"]),
              "Back and left views missing — not meshed from the front and right alone")
        check("reason", base_body.views_missing_message(["back"], ["front"], "x"),
              "Back view missing — not meshed from the front alone (x)")

        # --- [1] front only -> the back first, then ONE mesh job ---------------------------
        print("[1] front only: the back is rendered first, then one mesh job with images=2")
        sig_a = wear({"underwear_bottom": "under", "feet": "shoes"})
        jobs = render_views("main")
        check("A main view: 1 image job, front only", (len(jobs), dressed(sig_a, "front"), dressed(sig_a, "back")),
              (1, True, False))
        b_a = body_of(sig_a)
        m0 = len(MESH_CALLS)
        result, events, ops = build()
        check("A build: ok", result.get("ok"), True)
        check("A build: back draft + fit, then the mesh", (kinds(events)[:3], events[2:3]),
              (["image", "image", "mesh"], [("mesh", b_a)]))
        check("A build: exactly 1 mesh job, front + back", (len(MESH_CALLS) - m0, MESH_CALLS[-1] if MESH_CALLS else None),
              (1, {"source": f"tpose_{b_a}.png", "views": ["back"]}))
        parent = model3d._read_sidecar(mdir / f"{b_a}.glb").get("outfit_body") or {}
        check("A body: used_views", parent.get("used_views"), ["front", "back"])

        # --- [2] back refused -> no mesh job, a status ----------------------------------------
        print("[2] back refused: 0 mesh jobs, the status names the missing view")
        sig_g = wear({"underwear_bottom": "under", "feet": "shoes", "bottom": "skirt"})
        check("G main view: 1 image job", len(render_views("main")), 1)
        b_g = body_of(sig_g)
        real_dress_view = base_body._dress_view

        def refused(*a, **k):
            raise base_body.OutfitError("fit refused")

        base_body._dress_view = refused
        m0 = len(MESH_CALLS)
        result, events, ops = build()
        want = "Back view missing — not meshed from the front alone (fit refused)"
        check("G refused: 0 mesh jobs, 0 hub ops", (len(MESH_CALLS) - m0, ops), (0, 0))
        check("G refused: result", (result.get("ok"), result.get("error")), (False, want))
        info = base_body.outfit_info("Demo", signature=sig_g)
        check("G refused: status", (info.get("status"), info.get("error")), ("failed", want))
        check("G refused: no body file", (mdir / f"{b_g}.glb").exists(), False)
        base_body._dress_view = real_dress_view
        m0 = len(MESH_CALLS)
        result, events, ops = build()
        check("G lifted: back (2 image jobs) then 1 mesh job",
              (result.get("ok"), kinds(events)[:3], len(MESH_CALLS) - m0, MESH_CALLS[-1]["views"]),
              (True, ["image", "image", "mesh"], 1, ["back"]))

        # --- [3] every view present -> 1 mesh job ----------------------------------------------
        print("[3] all views present: no image job, one mesh job")
        sig_h = wear({"underwear_bottom": "under", "bottom": "skirt"})
        check("H full render: 3 image jobs", len(render_views()), 3)
        m0 = len(MESH_CALLS)
        result, events, ops = build()
        check("H build: ok, 0 image jobs, 1 mesh job",
              (result.get("ok"), kinds(events).count("image"), len(MESH_CALLS) - m0, MESH_CALLS[-1]["views"]),
              (True, 0, 1, ["back"]))

        # --- [4] resume of a front-only record is dropped ----------------------------------------
        print("[4] a front-only record from before the restart is dropped on resume")

        def died_record(sig):
            """Build ``sig`` and die in its mesh job; the record it left."""
            c0 = len(CREATED)
            DIE["mesh"] = True
            try:
                model3d.generate_for_current_outfit("Demo")
            except _Died:
                pass
            finally:
                DIE["mesh"] = False
            body = body_of(sig)
            ops = [o for o in hub_ops.list_ops() if o.inputs.get("signature") == body]
            return (ops[0] if ops else None), CREATED[c0:]

        def gone(op_id):
            for _ in range(50):
                if hub_ops.get(op_id) is None:
                    return True
                time.sleep(0.1)
            return False

        sig_k = wear({"feet": "shoes", "bottom": "skirt"})
        check("K full render: 3 image jobs", len(render_views()), 3)
        real_views = base_body.dressed_views
        base_body.dressed_views = lambda: ("front",)  # the old behaviour: meshed from the front alone
        try:
            op, created = died_record(sig_k)
        finally:
            base_body.dressed_views = real_views
        check("K record left, front only", (op is not None, (created[-1].get("view_images") if created else None)),
              (True, {}))
        m0 = len(MESH_CALLS)
        resumed = hub_ops.get_kind("character_mesh").resume(op) if op else {}
        want = "Back view missing — not meshed from the front alone — its mesh job from before the restart was dropped"
        check("K resume: dropped, 0 mesh jobs", (resumed.get("ok"), len(MESH_CALLS) - m0, gone(op.op_id) if op else None),
              (False, 0, True))
        info = base_body.outfit_info("Demo", signature=sig_k)
        check("K resume: status", (info.get("status"), info.get("error")), ("failed", want))

        # --- [5] control: a full record is resumed ------------------------------------------------
        print("[5] a front + back record is resumed")
        wear({"feet": "shoes"})
        sig_l = model_refs.current_outfit_state("Demo")[2]
        check("L full render: 3 image jobs", len(render_views()), 3)
        op, created = died_record(sig_l)
        check("L record left, front + back", (op is not None, sorted((created[-1].get("view_images") or {})
                                                                     if created else [])), (True, ["back"]))
        m0 = len(MESH_CALLS)
        resumed = hub_ops.get_kind("character_mesh").resume(op) if op else {}
        check("L resume: ok, 1 mesh job, record gone",
              (bool(resumed.get("ok")), len(MESH_CALLS) - m0, gone(op.op_id) if op else None), (True, 1, True))

    print()
    if FAILS:
        print(f"FAIL: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
