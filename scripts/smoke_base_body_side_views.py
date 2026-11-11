#!/usr/bin/env python3
"""Base body: dressed side views (opt-in) and the back refit (finding 6).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_side_views.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no image backend, no server process. The fixtures
and the render/matte stubs are those of ``scripts/smoke_base_body_outfit.py``
(its helpers are imported): every render writes an opaque 8x8 PNG of
``colour_of(<stem name>)`` plus the sidecar render_character_image would
write; the matte stub makes a 2 px transparent border; the base views
``tpose[_<view>]_<bsig>.png`` are transparent 8x8 with pixel (4,4) =
``BASE_PX[view]``.

The worker is a REAL subprocess (fake repo ``<tmp>/worker``). Per call ``n``
(0-based over the whole run) it records argv, the ``--glb`` input, every
``--view`` pair and the ``--arm-rig-glb`` file into ``<tmp>/calls/<n>/``,
writes as ``--out`` the input GLB with a 16x16 atlas of colour (n, 7, 7) and
the proof ``{"call": n, "views": {"back": {"dressed_alignment":
{"unchanged_delta_e": d}}}}`` where ``d`` is the next entry of the plan file
``<tmp>/delta_plan.json`` (None once the plan is empty).

Expected, derived by hand from the brief (fix 6, user test 2026-11-09):

[1] Settings. Without a ``base_body`` section: dressed_views() = (front,
    back), side_arm_margin() = 0.03. dressed_side_views true -> (front,
    back, left, right); the string "true" is no bool -> off. Margin 0.05 ->
    0.05, 0.5 -> 0.2 (max), -1 -> 0.0, "x" -> 0.03. Schema: both fields in
    section base_body, scope world (config_scope.scope_of), defaults False
    and 0.03, the margin bounded 0..0.2.
[2] Worker argv (body_retexture.build_argv, python /py, glb /w/in.glb):
    views {front, back} with margin 0.03 and rig /w/rig.glb -> exactly
    [/py, -m, body_core, --glb, /w/in.glb, --view front=/w/f.png,/w/rf.png,
    --view back=/w/b.png,/w/rb.png, --out /w/o.glb, --proof /w/p.json,
    --atlas /w/a.png] (no side flag without a side view). With left and
    right added (given in the order right, left): the views in the order
    front, back, left, right, then --side-arm-margin 0.03 --arm-rig-glb
    /w/rig.glb. No rig given: only the margin flag.
    view_delta_e: 5.87 from views.back.dressed_alignment; missing view ->
    None; null value -> None; True -> None; proof None -> None.
[3] Occasions and routing. outfit_side_draft: fields
    [outfit_side_draft_workflow, outfit_back_draft_workflow,
    tpose_view_workflow], use case base_view_side, no ref slot; outfit_side:
    [outfit_side_workflow, outfit_back_workflow, tpose_view_workflow], use
    case outfit_fit, ref slot; both mesh-input occasions, both hints name
    "Dressed side views"; the catalog order has them right after
    outfit_back. Seeding (config._apply_file_migrations on routing
    {tpose_view: [b*], outfit_back: [mine]}): outfit_back_draft [b*] (the
    base-body seed), outfit_side_draft [b*], outfit_side [mine]; a second
    _migrate_outfit_side_routing -> False; an existing outfit_side [own]
    stays. Per character {tpose_view_workflow v, outfit_back_workflow ob}:
    outfit_side ob, outfit_side_draft v; plus outfit_side_workflow os ->
    os. BASE_BODY_MATCH_FIELDS ends with the two side fields.
[4] OFF (the default) — byte-identical to the front+back pipeline. Demo
    wears the dress (osig), delta plan [2.9]: the tpose pass renders front
    edit, back draft, back fit (dirs model_refs, drafts, attempt1;
    occasions outfit_front, outfit_back_draft, outfit_back); one worker call
    whose argv has views [back, front] and neither --side-arm-margin nor
    --arm-rig-glb; dE 2.9 <= 4 -> no refit, the model sidecar has no
    back_refit; model_refs info: views {back, face}, drafts {back} only;
    a left render -> ValueError SIDE_VIEW_NOT_DRESSED;
    _require_dressable_view(left) -> 409.
[5] Back refit (side views off, view_guard scripted ok for every image,
    the noise gate unmeasurable on the opaque stubs -> passes):
    (a) plan [5.87, 3.1], forced rebuild: the build renders ONE more fit
        (dir "refit", occasion outfit_back, use case outfit_fit, reference
        tpose_back_<bsig>.png, extra reference the stored back draft) and
        runs the worker twice; the second call's back dressed input is the
        refit, front unchanged. Kept: model atlas (n2, 7, 7) of that second
        call, retexture_proof.call = n2; sidecar back_refit = {limit 4.0,
        attempts [{unchanged_delta_e 5.87}, {gate {ok True, ...},
        unchanged_delta_e 3.1}], chosen 2}; the published back sidecar
        carries the same back_refit and fit_gate {chosen 2, 2 attempts,
        ok True, warning None}.
    (b) plan [5.87, 6.2]: refit rendered, two worker calls, chosen 1, model
        atlas = the FIRST call's colour, back image bytes and sidecar
        unchanged (no back_refit in it).
    (c) plan [3.9]: no refit render, one worker call, no back_refit.
    (d) plan [5.0] with the stored draft changed: back_refit {chosen 1,
        skipped "the back's draft is missing or changed"}, no render, one
        worker call.
    (e) plan [5.0], view_guard fails for the refit image only: one refit
        render, ONE worker call, attempts[1].error "turned toward the
        camera", chosen 1.
[6] ON (dressed_side_views true, margin 0.05). Demo puts on the scarf
    (sig2), plan [2.0]: the pass renders front edit, back draft, back fit,
    left draft, left fit, right draft, right fit — dirs [model_refs, drafts,
    attempt1, drafts, attempt1, drafts, attempt1], occasions [outfit_front,
    outfit_back_draft, outfit_back, outfit_side_draft, outfit_side,
    outfit_side_draft, outfit_side], use cases [outfit_edit, base_view_back,
    outfit_fit, base_view_side, outfit_fit, base_view_side, outfit_fit],
    back_view [None, True, True, False, False, False, False]. The left draft:
    prompt = DRAFT_PROMPTS["left"] with DRAFT_OUTFIT_TEXT in its slot (review
    2026-11-11: an edit of the dressed front — the turn, then the outfit,
    then the frame), no character block (None),
    reference = the dressed front tpose_<sig2>.png. The left fit: reference
    tpose_left_<bsig>.png cut out ((0,0) black, (4,4) BASE_PX left), extra
    = the cut-out left draft ((4,4) = colour_of("tpose_left_<sig2>")),
    prompt FIT_PROMPT, size 8 x 8, sidecar_extra {base_signature, dressed,
    base_image_sha256 = sha(tpose_left_<bsig>.png), left_draft = its name,
    left_draft_sha256}. Stored: tpose_left/right_<sig2> with fit_gate ok,
    the drafts in drafts/. One worker call: views [back, front, left,
    right], argv ends with --side-arm-margin 0.05 --arm-rig-glb <file>,
    the recorded rig file = the rigged base bytes; the model sidecar
    view_images names back, left and right. model_refs info: views {back,
    left, right, face}, drafts {back, left, right} with file names;
    _require_dressable_view(left) passes; dressed_warnings [].
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_base_body_outfit import (BASE_PX, FIT_PROMPT, colour_of, make_glb,  # noqa: E402
                                    pixel, png)

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {repr(got)[:200]}"
          + ("" if ok else f" — expected {repr(want)[:400]}"))
    if not ok:
        FAILS.append(label)


WORKER = r'''
import io, json, os, shutil, sys
from pathlib import Path
ROOT, TMP = {root!r}, Path({tmp!r})
sys.path[:0] = [ROOT, *{site!r}]
a = sys.argv[1:]
calls = TMP / "calls"
calls.mkdir(exist_ok=True)
n = len(list(calls.iterdir()))
call = calls / str(n)
call.mkdir()
glb = a[a.index("--glb") + 1]
views = {{}}
for i, arg in enumerate(a):
    if arg == "--view":
        name, files = a[i + 1].split("=", 1)
        dressed, registration = files.split(",")
        shutil.copyfile(dressed, call / f"{{name}}_dressed.png")
        shutil.copyfile(registration, call / f"{{name}}_registration.png")
        views[name] = [os.path.basename(dressed), os.path.basename(registration)]
if "--arm-rig-glb" in a:
    shutil.copyfile(a[a.index("--arm-rig-glb") + 1], call / "arm_rig.glb")
(call / "argv.json").write_text(json.dumps({{"argv": a, "views": views}}))
plan_file = TMP / "delta_plan.json"
plan = json.loads(plan_file.read_text()) if plan_file.exists() else []
delta = plan.pop(0) if plan else None
plan_file.write_text(json.dumps(plan))
from PIL import Image
buf = io.BytesIO()
Image.new("RGB", (16, 16), (n, 7, 7)).save(buf, "PNG")
from app.core.base_body import replace_base_color
Path(a[a.index("--out") + 1]).write_bytes(replace_base_color(Path(glb).read_bytes(), buf.getvalue(), "image/png"))
Path(a[a.index("--atlas") + 1]).write_bytes(buf.getvalue())
Path(a[a.index("--proof") + 1]).write_text(json.dumps(
    {{"call": n, "views": {{"back": {{"dressed_alignment": {{"unchanged_delta_e": delta}}}}}}}}))
'''

RENDERS, REMBG = [], []


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-sides-") as tmp:
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

        from app.core import (base_body, body_retexture, character_ops, config_scope, expression_regen,
                              extension_rig, glb_delivery, model3d, model_refs)
        from app.core.config_schema import SECTIONS, field_default
        from app.blender import refine
        from app.imagegen import occasions, routing
        from app.models import inventory
        import app.models.character as character_module
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)

        # --- [1] settings ---------------------------------------------------------
        print("[1] settings")
        config._CONFIG.pop("base_body", None)
        check("default views", base_body.dressed_views(), ("front", "back"))
        check("default margin", base_body.side_arm_margin(), 0.03)
        config._CONFIG["base_body"] = {"dressed_side_views": True}
        check("on", base_body.dressed_views(), ("front", "back", "left", "right"))
        config._CONFIG["base_body"] = {"dressed_side_views": "true"}
        check("string is not on", base_body.dressed_views(), ("front", "back"))
        for raw, want in ((0.05, 0.05), (0.5, 0.2), (-1, 0.0), ("x", 0.03)):
            config._CONFIG["base_body"] = {"side_arm_margin": raw}
            check(f"margin {raw!r}", base_body.side_arm_margin(), want)
        config._CONFIG.pop("base_body", None)
        fields = SECTIONS["base_body"]["fields"]
        check("schema defaults", (field_default("base_body", "dressed_side_views"),
                                  field_default("base_body", "side_arm_margin")), (False, 0.03))
        check("margin bounds", (fields["side_arm_margin"].get("min"), fields["side_arm_margin"].get("max")), (0, 0.2))
        check("world scope", (config_scope.scope_of("base_body.dressed_side_views"),
                              config_scope.scope_of("base_body.side_arm_margin")), ("world", "world"))

        # --- [2] argv + proof reader ---------------------------------------------
        print("[2] worker argv")
        w = Path("/w")
        two = {"front": (w / "f.png", w / "rf.png"), "back": (w / "b.png", w / "rb.png")}
        head = ["/py", "-m", "body_core", "--glb", "/w/in.glb"]
        tail = ["--out", "/w/o.glb", "--proof", "/w/p.json", "--atlas", "/w/a.png"]
        argv = body_retexture.build_argv(Path("/py"), w / "in.glb", two, w / "o.glb", w / "p.json", w / "a.png",
                                         side_arm_margin=0.03, arm_rig_glb=w / "rig.glb")
        check("front+back: no side flags", argv,
              head + ["--view", "front=/w/f.png,/w/rf.png", "--view", "back=/w/b.png,/w/rb.png"] + tail)
        four = {"right": (w / "r.png", w / "rr.png"), "left": (w / "l.png", w / "rl.png"), **two}
        argv = body_retexture.build_argv(Path("/py"), w / "in.glb", four, w / "o.glb", w / "p.json", w / "a.png",
                                         side_arm_margin=0.03, arm_rig_glb=w / "rig.glb")
        check("four views: order + side flags", argv,
              head + ["--view", "front=/w/f.png,/w/rf.png", "--view", "back=/w/b.png,/w/rb.png",
                      "--view", "left=/w/l.png,/w/rl.png", "--view", "right=/w/r.png,/w/rr.png"] + tail
              + ["--side-arm-margin", "0.03", "--arm-rig-glb", "/w/rig.glb"])
        argv = body_retexture.build_argv(Path("/py"), w / "in.glb", four, w / "o.glb", w / "p.json", w / "a.png",
                                         side_arm_margin=0.03)
        check("no rig: margin only", argv[-2:], ["--side-arm-margin", "0.03"])
        proof = {"views": {"back": {"dressed_alignment": {"unchanged_delta_e": 5.87}}}}
        check("delta", base_body.view_delta_e(proof, "back"), 5.87)
        check("delta missing view", base_body.view_delta_e(proof, "front"), None)
        check("delta null", base_body.view_delta_e(
            {"views": {"back": {"dressed_alignment": {"unchanged_delta_e": None}}}}, "back"), None)
        check("delta bool", base_body.view_delta_e(
            {"views": {"back": {"dressed_alignment": {"unchanged_delta_e": True}}}}, "back"), None)
        check("delta no proof", base_body.view_delta_e(None, "back"), None)

        # --- [3] occasions + routing ---------------------------------------------
        print("[3] occasions")
        sd, sf = occasions.OCCASIONS["outfit_side_draft"], occasions.OCCASIONS["outfit_side"]
        check("side draft fields", occasions.spec_fields(sd),
              ["outfit_side_draft_workflow", "outfit_back_draft_workflow", "tpose_view_workflow"])
        check("side fit fields", occasions.spec_fields(sf),
              ["outfit_side_workflow", "outfit_back_workflow", "tpose_view_workflow"])
        check("use cases", (sd.get("style_use_cases"), sf.get("style_use_cases")), (["base_view_side"], ["outfit_fit"]))
        check("ref slot", (bool(sd.get("needs_ref_slot")), bool(sf.get("needs_ref_slot"))), (False, True))
        check("mesh input", ("outfit_side_draft" in occasions.MESH_INPUT_OCCASIONS,
                             "outfit_side" in occasions.MESH_INPUT_OCCASIONS), (True, True))
        check("hints", ("Dressed side views" in sd.get("hint", ""), "Dressed side views" in sf.get("hint", "")),
              (True, True))
        ids = occasions.occasion_ids()
        i = ids.index("outfit_back")
        check("catalog order", ids[i:i + 3], ["outfit_back", "outfit_side_draft", "outfit_side"])
        union = {"image_generation": {"routing": {"tpose_view": ["b*"], "outfit_back": ["mine"]}}}
        config._apply_file_migrations(union)
        r = union["image_generation"]["routing"]
        check("seeded", [r.get(k) for k in ("outfit_back_draft", "outfit_side_draft", "outfit_side")],
              [["b*"], ["b*"], ["mine"]])
        check("second run unchanged", config._migrate_outfit_side_routing(union), False)
        own = {"image_generation": {"routing": {"outfit_back": ["x"], "outfit_side": ["own"]}}}
        config._migrate_outfit_side_routing(own)
        check("own chain kept", own["image_generation"]["routing"]["outfit_side"], ["own"])
        real_profile = character_module.get_character_profile
        record = {"tpose_view_workflow": "v", "outfit_back_workflow": "ob"}
        character_module.get_character_profile = lambda name: {"outfit_imagegen": dict(record)}
        try:
            check("fallbacks", [routing._character_spec(occasions.OCCASIONS[o], "Demo")
                                for o in ("outfit_side", "outfit_side_draft")], ["ob", "v"])
            record["outfit_side_workflow"] = "os"
            check("own field", routing._character_spec(sf, "Demo"), "os")
        finally:
            character_module.get_character_profile = real_profile
        check("match fields", character_ops.BASE_BODY_MATCH_FIELDS[-2:],
              ("outfit_side_draft_workflow", "outfit_side_workflow"))

        # --- fixtures ---------------------------------------------------------------
        worker = root / "worker"
        (worker / ".venv" / "bin").mkdir(parents=True)
        (worker / ".venv" / "bin" / "python").symlink_to(Path(sys.executable).resolve())
        (worker / "body_core").mkdir()
        (worker / "body_core" / "__init__.py").write_text("")
        import site
        (worker / "body_core" / "__main__.py").write_text(
            WORKER.format(root=str(ROOT), tmp=str(root), site=site.getsitepackages()))
        config._CONFIG["body_retexture"] = {"worker_dir": str(worker), "timeout_seconds": 60}
        plan_file = root / "delta_plan.json"

        def calls():
            d = root / "calls"
            return sorted((p for p in d.iterdir()), key=lambda p: int(p.name)) if d.is_dir() else []

        def argv_of(call):
            return json.loads((call / "argv.json").read_text())

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(png((50, 60, 70)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        check("pipeline", base_body.set_pipeline("Demo", True), True)
        dress = inventory.add_item(name="dress", category="outfit_piece",
                                   prompt_fragment="a fitted red cotton dress with white sneakers",
                                   outfit_piece={"slots": ["top"], "covers": [], "outfit_types": ["casual"]})["id"]
        scarf = inventory.add_item(name="scarf", category="outfit_piece", prompt_fragment="a green wool scarf",
                                   outfit_piece={"slots": ["neck"], "covers": [], "outfit_types": ["casual"]})["id"]
        for item in (dress, scarf):
            check(f"inventory {item}", inventory.add_to_inventory("Demo", item), True)
        bsig = base_body.base_signature("Demo")
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            im.putpixel((4, 4), BASE_PX[v] + (255,))
            im.save(refs / f"{stem}.png")
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
        groups = [{"id": "jiggle", "op": "jiggle", "params": {}, "chains": [], "depends_on": ""}]
        jiggle_fp = extension_rig.extension_rig_fingerprint(groups, {})
        rigged = make_glb(1.0, png((10, 20, 30)), rig=True)
        model_dir = get_character_dir("Demo") / "model3d"
        for sub in ("unrigged", "prerig"):
            (model_dir / sub).mkdir(parents=True, exist_ok=True)
        (model_dir / f"{bsig}.glb").write_bytes(rigged)
        (model_dir / f"{bsig}.json").write_text(json.dumps({
            "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated",
            "extension_rig": {"fingerprint": jiggle_fp, "groups": ["jiggle"], "group_ops": {"jiggle": "jiggle"},
                              "status": "applied", "attempted": True, "has_applied": True, "metrics": {}}}))
        (model_dir / "prerig" / f"{bsig}.glb").write_bytes(rigged)
        (model_dir / "prerig" / f"{bsig}.json").write_text(json.dumps({"rig": "mixamo"}))
        (model_dir / "unrigged" / f"{bsig}.glb").write_bytes(make_glb(5.0, png((90, 90, 90))))

        originals = {
            (expression_regen, "render_character_image"): expression_regen.render_character_image,
            (refine, "apply_script"): refine.apply_script,
            (model3d, "_auto_retexture"): model3d._auto_retexture,
            (model3d, "_attach_measurement"): model3d._attach_measurement,
            (model3d, "request_lod"): model3d.request_lod,
            (extension_rig, "rig_groups_for"): extension_rig.rig_groups_for,
            (extension_rig, "resolved_extension_groups"): extension_rig.resolved_extension_groups,
            (glb_delivery, "delivery_path"): glb_delivery.delivery_path,
            (character_module, "run_rembg"): character_module.run_rembg,
            (base_body, "view_guard"): base_body.view_guard,
        }

        def rembg(data, model="u2net", **kw):
            REMBG.append(model)
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
            ref = kw.get("reference_image")
            extras = kw.get("extra_reference_images") or []
            RENDERS.append({"stem": Path(output_stem).name, "dir": Path(output_stem).parent.name, **kw,
                            "reference_name": ref.name if ref else None,
                            "extra_names": [Path(x).name for x in extras],
                            "extra_px": [(pixel(Path(x).read_bytes(), (0, 0)), pixel(Path(x).read_bytes()))
                                         for x in extras],
                            "reference_px": (pixel(Path(ref).read_bytes(), (0, 0)), pixel(Path(ref).read_bytes()))
                            if ref else None})
            target = Path(str(output_stem) + ".png")
            Image.new("RGB", (8, 8), colour_of(target.stem)).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            meta = {"equipped_pieces": equipped_pieces or {}, "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        guard_fail_dirs = set()

        def guard(view, path, base_views):
            ok = Path(path).parent.name not in guard_fail_dirs
            return {"ok": ok, "scores": {}, "best": view if ok else "front"}

        expression_regen.render_character_image = render
        character_module.run_rembg = rembg
        refine.apply_script = lambda *a, **k: {"applied": True, "data": {}}
        model3d._auto_retexture = lambda *a, **k: None
        model3d._attach_measurement = lambda *a, **k: None
        model3d.request_lod = lambda name, path: False
        extension_rig.rig_groups_for = lambda *a, **k: [dict(g) for g in groups]
        extension_rig.resolved_extension_groups = lambda *a, **k: [
            {**g, "enabled": True, "flip": False} for g in groups]
        glb_delivery.delivery_path = lambda path, **kw: path
        base_body.view_guard = guard

        def wait_idle(timeout=30.0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and ("Demo" in model3d._generating
                                                   or "Demo" in model3d._outfit_followups):
                time.sleep(0.05)
            check("generation finished", "Demo" in model3d._generating, False)

        def equip(item):
            check(f"equip {item}", inventory.equip_piece("Demo", item, source="smoke")["status"], "ok")
            model_refs._cancel_timers("Demo", model_refs.REF_KINDS)

        def plan(values):
            plan_file.write_text(json.dumps(values))

        def atlas_call(path):
            return pixel(base_body.base_color_image(path.read_bytes())[0])[0]

        from fastapi import HTTPException
        from app.routes import characters as character_routes

        def dressable(view):
            try:
                character_routes._require_dressable_view("Demo", view, base_ready=False)
                return "ok"
            except HTTPException as e:
                return (e.status_code, e.detail)

        try:
            # --- [4] off -----------------------------------------------------------
            print("[4] side views off")
            config._CONFIG.pop("base_body", None)
            plan([2.9])
            equip(dress)
            osig = model_refs.current_outfit_state("Demo")[2]
            model_refs._run_generation("Demo", "tpose")
            wait_idle()
            check("three renders", [(r["dir"], r.get("occasion")) for r in RENDERS],
                  [("model_refs", "outfit_front"), ("drafts", "outfit_back_draft"), ("attempt1", "outfit_back")])
            runs = calls()
            check("one worker call", len(runs), 1)
            if runs:
                a = argv_of(runs[0])
                check("views front, back", sorted(a["views"]), ["back", "front"])
                check("no side flags", ("--side-arm-margin" in a["argv"], "--arm-rig-glb" in a["argv"]),
                      (False, False))
            model = model_dir / f"{osig}.glb"
            meta = model3d._read_sidecar(model)
            check("no refit at dE 2.9", "back_refit" in meta, False)
            info = model_refs.get_model_refs_info("Demo")
            check("info views", sorted(info["views"]), ["back", "face"])
            check("info drafts", {k: (v or {}).get("filename") for k, v in info["drafts"].items()},
                  {"back": f"tpose_back_{osig}.png"})
            try:
                base_body.generate_dressed_images("Demo", pieces={"top": dress}, items=[], signature=osig,
                                                  view="left")
                check("left refused", "no error", "ValueError")
            except ValueError as e:
                check("left refused", str(e), base_body.SIDE_VIEW_NOT_DRESSED)
            check("route refuses left", dressable("left"), (409, base_body.SIDE_VIEW_NOT_DRESSED))
            check("no side dressed image", base_body.dressed_image("Demo", "left", osig, bsig), None)

            # --- [5] back refit -------------------------------------------------------
            print("[5] back refit")
            back_png = refs / f"tpose_back_{osig}.png"
            back_json = back_png.with_suffix(".json")
            draft_png = refs / "drafts" / f"tpose_back_{osig}.png"

            def rebuild(values):
                plan(values)
                start_calls, start_renders = len(calls()), len(RENDERS)
                result = model3d.generate_for_current_outfit("Demo", force=True)
                check(f"rebuild {values} ok", result.get("ok"), True)
                return calls()[start_calls:], RENDERS[start_renders:], model3d._read_sidecar(model)

            # (a) kept
            new_calls, new_renders, meta = rebuild([5.87, 3.1])
            check("(a) one refit render", [(r["dir"], r.get("occasion"), r.get("image_use_case"))
                                           for r in new_renders], [("refit", "outfit_back", "outfit_fit")])
            if new_renders:
                fr = new_renders[0]
                check("(a) refit references", (fr["reference_name"], fr["extra_names"], fr.get("bare_prompt")),
                      (f"tpose_back_{bsig}.png", [f"tpose_back_{osig}.png"], FIT_PROMPT))
            check("(a) two worker calls", len(new_calls), 2)
            if len(new_calls) == 2:
                n2 = int(new_calls[1].name)
                second_argv = argv_of(new_calls[1])["argv"]
                back_arg = next((x for x in second_argv if x.startswith("back=")), "")
                check("(a) second call gets the refit back",
                      (sorted(argv_of(new_calls[1])["views"]), Path(back_arg[5:].split(",")[0]).parent.name),
                      (["back", "front"], "refit"))
                check("(a) front input unchanged", (new_calls[1] / "front_dressed.png").read_bytes(),
                      (new_calls[0] / "front_dressed.png").read_bytes())
                check("(a) refit kept: atlas + proof", (atlas_call(model), (meta.get("retexture_proof") or {})
                                                        .get("call")), (n2, n2))
                br = meta.get("back_refit") or {}
                check("(a) back_refit", (br.get("limit"), br.get("chosen"),
                                         [x.get("unchanged_delta_e") for x in br.get("attempts") or []],
                                         ((br.get("attempts") or [{}, {}])[1].get("gate") or {}).get("ok")),
                      (4.0, 2, [5.87, 3.1], True))
                stored_back = json.loads(back_json.read_text())
                gate = stored_back.get("fit_gate") or {}
                check("(a) published back", ((stored_back.get("back_refit") or {}).get("chosen"),
                                             gate.get("chosen"), len(gate.get("attempts") or []),
                                             gate.get("ok"), gate.get("warning")), (2, 2, 2, True, None))
            check("(a) no staging left", sorted(p.name for p in refs.iterdir() if p.name.startswith(".")), [])

            # (b) not better
            before = (back_png.read_bytes(), back_json.read_text())
            new_calls, new_renders, meta = rebuild([5.87, 6.2])
            check("(b) refit rendered, two calls", ([r["dir"] for r in new_renders], len(new_calls)),
                  (["refit"], 2))
            br = meta.get("back_refit") or {}
            check("(b) first kept", (br.get("chosen"), [x.get("unchanged_delta_e") for x in br.get("attempts") or []]),
                  (1, [5.87, 6.2]))
            if new_calls:
                check("(b) atlas of the first call", atlas_call(model), int(new_calls[0].name))
            check("(b) back unchanged", (back_png.read_bytes(), back_json.read_text()), before)

            # (c) below the limit
            new_calls, new_renders, meta = rebuild([3.9])
            check("(c) no refit", (len(new_renders), len(new_calls), "back_refit" in meta), (0, 1, False))

            # (d) draft changed
            draft_bytes = draft_png.read_bytes()
            draft_png.write_bytes(png((1, 1, 1)))
            new_calls, new_renders, meta = rebuild([5.0])
            br = meta.get("back_refit") or {}
            check("(d) skipped", (br.get("chosen"), br.get("skipped"), len(new_renders), len(new_calls)),
                  (1, "the back's draft is missing or changed", 0, 1))
            draft_png.write_bytes(draft_bytes)

            # (e) refit turned toward the camera
            guard_fail_dirs.add("refit")
            new_calls, new_renders, meta = rebuild([5.0])
            guard_fail_dirs.clear()
            br = meta.get("back_refit") or {}
            check("(e) turned refit dropped", (len(new_renders), len(new_calls), br.get("chosen"),
                                               (br.get("attempts") or [{}, {}])[1].get("error")),
                  (1, 1, 1, "turned toward the camera"))

            # --- [6] on ----------------------------------------------------------------
            print("[6] side views on")
            config._CONFIG["base_body"] = {"dressed_side_views": True, "side_arm_margin": 0.05}
            plan([2.0])
            start_calls, start_renders = len(calls()), len(RENDERS)
            equip(scarf)
            sig2 = model_refs.current_outfit_state("Demo")[2]
            model_refs._run_generation("Demo", "tpose")
            wait_idle()
            rs = RENDERS[start_renders:]
            check("seven renders", [r["dir"] for r in rs],
                  ["model_refs", "drafts", "attempt1", "drafts", "attempt1", "drafts", "attempt1"])
            check("occasions", [r.get("occasion") for r in rs],
                  ["outfit_front", "outfit_back_draft", "outfit_back", "outfit_side_draft", "outfit_side",
                   "outfit_side_draft", "outfit_side"])
            check("use cases", [r.get("image_use_case") for r in rs],
                  ["outfit_edit", "base_view_back", "outfit_fit", "base_view_side", "outfit_fit", "base_view_side",
                   "outfit_fit"])
            check("back_view", [r.get("back_view") for r in rs], [None, True, True, False, False, False, False])
            check("stems", [r["stem"] for r in rs],
                  [f"tpose_{sig2}", f"tpose_back_{sig2}", f"tpose_back_{sig2}", f"tpose_left_{sig2}",
                   f"tpose_left_{sig2}", f"tpose_right_{sig2}", f"tpose_right_{sig2}"])
            if len(rs) == 7:
                ld, lf = rs[3], rs[4]
                check("left draft prompt", ld.get("bare_prompt"),
                      base_body.DRAFT_PROMPTS["left"].format(outfit=base_body.DRAFT_OUTFIT_TEXT))
                check("left draft prompt carries the outfit text after the turn",
                      ld.get("bare_prompt", "").startswith("The same person turned to a strict left side profile view")
                      and ", completely bald, " + base_body.DRAFT_OUTFIT_TEXT + ", the whole figure" in ld.get("bare_prompt", ""),
                      True)
                check("left draft block", ld.get("style_character"), None)
                check("left draft reference", ld["reference_name"], f"tpose_{sig2}.png")
                check("left fit references", (lf["reference_name"], lf["reference_px"], lf["extra_names"],
                                              lf["extra_px"]),
                      (f"tpose_left_{bsig}.png", ((0, 0, 0), BASE_PX["left"]), [f"tpose_left_{sig2}.png"],
                       [((0, 0, 0), colour_of(f"tpose_left_{sig2}"))]))
                check("left fit prompt + size", (lf.get("bare_prompt"), lf.get("override_width"),
                                                 lf.get("override_height")), (FIT_PROMPT, 8, 8))
                left_draft = refs / "drafts" / f"tpose_left_{sig2}.png"
                # Texture fields (plan 2026-11-10) checked by smoke_texture_body_reuse.
                check("left fit sidecar extra", {k: v for k, v in (lf.get("sidecar_extra") or {}).items()
                                                 if k not in ("texture_signature", "dress_text")},
                      {"base_signature": bsig, "dressed": True,
                       "base_image_sha256": hashlib.sha256((refs / f"tpose_left_{bsig}.png").read_bytes())
                       .hexdigest(),
                       "left_draft": left_draft.name,
                       "left_draft_sha256": hashlib.sha256(left_draft.read_bytes()).hexdigest()})
            for v in ("left", "right"):
                side = json.loads((refs / f"tpose_{v}_{sig2}.json").read_text())
                check(f"{v} stored with fit gate", ((side.get("fit_gate") or {}).get("ok"),
                                                    (refs / "drafts" / f"tpose_{v}_{sig2}.png").is_file()),
                      (True, True))
            runs = calls()[start_calls:]
            check("one worker call", len(runs), 1)
            if runs:
                a = argv_of(runs[0])
                check("four views", sorted(a["views"]), ["back", "front", "left", "right"])
                check("side flags", (a["argv"][-4], a["argv"][-3], a["argv"][-2]),
                      ("--side-arm-margin", "0.05", "--arm-rig-glb"))
                check("arm rig = rigged base", (runs[0] / "arm_rig.glb").read_bytes(), rigged)
            meta2 = model3d._read_sidecar(model_dir / f"{sig2}.glb")
            check("view images", sorted((meta2.get("view_images") or {})), ["back", "left", "right"])
            info = model_refs.get_model_refs_info("Demo")
            check("info views", sorted(info["views"]), ["back", "face", "left", "right"])
            check("info drafts", {k: (v or {}).get("filename") for k, v in info["drafts"].items()},
                  {v: f"tpose_{v}_{sig2}.png" for v in ("back", "left", "right")})
            check("route allows left", dressable("left"), "ok")
            check("dressed warnings", base_body.dressed_warnings("Demo", sig2, bsig), [])
        finally:
            for (module, attr), value in originals.items():
                setattr(module, attr, value)
            config._CONFIG.pop("base_body", None)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
