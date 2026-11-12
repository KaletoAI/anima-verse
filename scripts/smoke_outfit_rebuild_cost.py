#!/usr/bin/env python3
"""``base_body.rebuild_cost`` — the hub cost of rebuilding a stale outfit model
(spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md
§ 6.4, the cost table).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_rebuild_cost.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server. The
fixture is a slim cut of scripts/smoke_base_body_outfit.py: Kira on the
pipeline with a ready base (``model3d/<bsig>.glb`` + sidecar rig mixamo) and
the four base views ``tpose[_<view>]_<bsig>.png`` (sidecar base_signature),
wearing a plain Dress (slot top, mode painted — chosen: since Ruling A10 the
default is in the body) → the worn signature ``sig``. "The views
current" = ``tpose_<sig>.png`` / ``tpose_back_<sig>.png`` with sidecar
``base_signature`` = bsig, ``base_image_sha256`` = sha256 of the base view,
``dressed`` true, the equipped Dress and ``texture_signature`` = the texture
of the figure delivered now (``dressed_image`` returns them; plan
2026-11-12-unified-worn-pieces Task 6: a view counts for its figure only).
The outfit model ``model3d/<sig>.glb``: sidecar base_signature
"base00000000" (an older base) unless a case says otherwise. Nothing is
rendered — the function only reads.

Derived by hand from the cost table (front 1, every other dressed view 2 =
draft + fit; an outfit body 2 = img2mesh + rig; retexture repaint = CPU):

[O1] retexture mode, older base, NO dressed view of the current base, side
     views off (dressed views front + back) → views_needed True, image
     1 + 2·1 = 3, mesh 0, hub 3; body_needed False; note "older base: views 3
     (first attempts)".
[O2] the world setting ``base_body.dressed_side_views`` on (dressed views
     front, back, left, right) → image 1 + 2·3 = 7, hub 7.
[O3] side views off again; the Dress switched to mode in_body ("mesh"; back
     to painted = "retexture"): the wanted figure stands on a meshed shape
     that is not stored → body 2, plus the shape's own views (none stored)
     3; nothing is painted on the shape (the Dress is in it: texture "") so
     the outfit's views are copies, 0 → {image 3, mesh 2, hub 5}, note
     "older base: views 3 + body 2 (first attempts)".
[O4] "mesh", the outfit's dressed front + back current (made on the plain
     body meanwhile): the shape is still missing with its views → still
     {image 3, mesh 2, hub 5}; ``figure.stored_shape`` patched to answer a
     body → no body, and the outfit's views on the shape are copies → hub 0,
     note "older base: outfit body stored, CPU only".
[O5] retexture mode, views current, the model built on the CURRENT base but
     ``variant_current`` patched False → outfit_info stale_reason
     "detail_changed" → hub 0, note "other body detail: repaint on the CPU".
[O6] "retexture", views current, the model on the current base records a
     figure whose texture is another one ("tex000000000000") → outfit_info
     stale_reason "figure" → hub 0, note "other figure: repaint on the
     CPU"; switched to "mesh" → the shape with its views: 3 + 2 = 5.
[O7] ``dressed_views`` patched to raise → hub_jobs None, image/mesh None,
     note starts "cost unknown".

Fails on 505c3076: AttributeError — module 'app.core.base_body' has no
attribute 'rebuild_cost'.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(rgb) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (8, 8), rgb).save(out, "PNG")
    return out.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-rebuild-cost-") as tmp:
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

        from app.core import base_body, glb_delivery, model_refs
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        glb_delivery.delivery_path = lambda path, **kw: path   # no background meshopt copy of fixture bytes

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create Kira", save_character_profile("Kira", dict(human), create_new=True), True)
        check("pipeline Kira", base_body.set_pipeline("Kira", True), True)
        bsig = base_body.base_signature("Kira")
        cdir = get_character_dir("Kira")
        mdir, refs = cdir / "model3d", cdir / "model_refs"
        mdir.mkdir(parents=True, exist_ok=True)
        refs.mkdir(parents=True, exist_ok=True)
        (mdir / f"{bsig}.glb").write_bytes(b"glb-Kira")
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        check("base ready", (base_body.base_model_info("Kira") or {}).get("status"), "ready")
        shas = {}
        for i, v in enumerate(base_body.BASE_VIEWS):
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png((10 * i, 20, 30)))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
            shas[v] = hashlib.sha256((refs / f"{stem}.png").read_bytes()).hexdigest()

        dress = inventory.add_item(name="Dress", category="outfit_piece", prompt_fragment="a green dress",
                                   outfit_piece={"slots": ["top"], "covers": [], "outfit_types": ["casual"],
                                                 "mesh_mode": "painted"})["id"]
        check("Kira holds the dress", inventory.add_to_inventory("Kira", dress), True)
        check("Kira wears the dress", inventory.equip_piece("Kira", dress, source="smoke")["status"], "ok")
        pieces, items, sig = model_refs.current_outfit_state("Kira")

        def set_mode(mode):
            """The outfit body mode follows the worn pieces (interim rule, plan 2026-11-12-unified-worn-pieces
            Task 2): the dress goes in the body for "mesh", back to painted for "retexture"."""
            op = dict(inventory.get_item(dress)["outfit_piece"])
            op["mesh_mode"] = "in_body" if mode == "mesh" else "painted"
            inventory.update_item(dress, {"outfit_piece": op})
            from app.core import figure
            check(f"mode {mode}", "mesh" if figure.wanted_figure("Kira").in_body else "retexture", mode)

        def write_model(**extra):
            (mdir / f"{sig}.glb").write_bytes(b"outfit-model")
            (mdir / f"{sig}.json").write_text(json.dumps({
                "character": "Kira", "signature": sig, "pieces": dict(pieces), "items": list(items),
                "dressed": True, "base_signature": "base00000000", "base_model_sha256": "old", **extra}))

        from app.core import figure

        def write_views():
            for v in ("front", "back"):
                stem = f"tpose_{sig}" if v == "front" else f"tpose_{v}_{sig}"
                (refs / f"{stem}.png").write_bytes(png((99, 1 if v == "front" else 2, 3)))
                (refs / f"{stem}.json").write_text(json.dumps({
                    "base_signature": bsig, "base_image_sha256": shas[v], "dressed": True,
                    "equipped_pieces": dict(pieces), "equipped_items": list(items), "mesh_variant": "",
                    "texture_signature": figure.delivered_figure("Kira").texture}))

        def drop_views():
            for p in refs.glob(f"tpose*_{sig}.*"):
                p.unlink()

        def cost():
            out = base_body.rebuild_cost("Kira", sig)
            return {k: out[k] for k in ("image_jobs", "mesh_jobs", "hub_jobs")}, out

        def side_views(on):
            config._CONFIG.setdefault("base_body", {})["dressed_side_views"] = on

        # --- [O1] -------------------------------------------------------------------
        print("[O1] retexture, older base, no dressed view")
        write_model()
        check("outfit_info stale older_base", base_body.outfit_info("Kira", signature=sig)["stale_reason"],
              "older_base")
        got, full = cost()
        check("cost", got, {"image_jobs": 3, "mesh_jobs": 0, "hub_jobs": 3})
        check("views/body needed", (full["views_needed"], full["body_needed"]), (True, False))
        check("note", full["note"], "older base: views 3 (first attempts)")

        # --- [O2] -------------------------------------------------------------------
        print("[O2] dressed side views on")
        side_views(True)
        check("dressed views", base_body.dressed_views(), ("front", "back", "left", "right"))
        got, _ = cost()
        check("cost", got, {"image_jobs": 7, "mesh_jobs": 0, "hub_jobs": 7})
        side_views(False)

        # --- [O3] -------------------------------------------------------------------
        print("[O3] mesh mode, no dressed view, no body")
        set_mode("mesh")
        got, full = cost()
        check("cost", got, {"image_jobs": 3, "mesh_jobs": 2, "hub_jobs": 5})
        check("note", full["note"], "older base: views 3 + body 2 (first attempts)")

        # --- [O4] -------------------------------------------------------------------
        print("[O4] mesh mode, views current")
        write_views()
        check("dressed front current", base_body.dressed_image("Kira", "front", sig, bsig) is not None, True)
        got, full = cost()
        check("no body stored: the shape and its views", (got, full["note"]),
              ({"image_jobs": 3, "mesh_jobs": 2, "hub_jobs": 5}, "older base: views 3 + body 2 (first attempts)"))
        with patch.object(figure, "stored_shape", return_value={"rig": "mixamo"}):
            got, full = cost()
        check("body stored: nothing", (got, full["note"]),
              ({"image_jobs": 0, "mesh_jobs": 0, "hub_jobs": 0}, "older base: outfit body stored, CPU only"))

        # --- [O5] -------------------------------------------------------------------
        print("[O5] retexture, views current, detail changed")
        set_mode("retexture")
        write_model(base_signature=bsig, base_model_sha256=base_body.base_model_sha256("Kira", bsig))
        with patch.object(base_body, "variant_current", return_value=False):
            check("stale detail_changed", base_body.outfit_info("Kira", signature=sig)["stale_reason"],
                  "detail_changed")
            got, full = cost()
        check("cost 0", (got, full["note"]),
              ({"image_jobs": 0, "mesh_jobs": 0, "hub_jobs": 0}, "other body detail: repaint on the CPU"))

        # --- [O6] -------------------------------------------------------------------
        print("[O6] the model was built as another figure")
        other = {**figure.delivered_figure("Kira").as_dict(), "texture": "tex000000000000"}
        write_model(base_signature=bsig, base_model_sha256=base_body.base_model_sha256("Kira", bsig), figure=other)
        check("stale figure", base_body.outfit_info("Kira", signature=sig)["stale_reason"], "figure")
        check("views themselves current", base_body.dressed_image("Kira", "back", sig, bsig) is not None, True)
        got, full = cost()
        check("repaint on the CPU", (got, full["note"]),
              ({"image_jobs": 0, "mesh_jobs": 0, "hub_jobs": 0}, "other figure: repaint on the CPU"))
        set_mode("mesh")
        got, _ = cost()
        check("in the body: views 3 + body 2", got, {"image_jobs": 3, "mesh_jobs": 2, "hub_jobs": 5})
        set_mode("retexture")

        # --- [O7] -------------------------------------------------------------------
        print("[O7] unreadable input")
        with patch.object(base_body, "dressed_views", side_effect=RuntimeError("broken")):
            out = base_body.rebuild_cost("Kira", sig)
        check("unknown", (out["image_jobs"], out["mesh_jobs"], out["hub_jobs"], out["note"].startswith("cost unknown")),
              (None, None, None, True))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
