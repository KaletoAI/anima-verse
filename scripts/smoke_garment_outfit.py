#!/usr/bin/env python3
"""Base body phase 5, Task 4: own-mesh outfit pieces in the outfit model build
(plan docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md,
Review Focus 1-5).

Usage:
    ./.venv/bin/python scripts/smoke_garment_outfit.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process. Needs ``git`` for the pinned signature rule of [1].

Stubs: ``garments._run_locked`` (the chain body; ``run_garment``'s run lock,
item check and the after-fit hook stay REAL) — per item a mode: ``ok``
writes an accepted fit ``garments/<item>_<fsig>.glb`` (the rigged base with
one grafted node ``garment_clothing_<item>``: a 4-vertex quad weighted 1.0
to ``mixamorig:Spine2``) whose record is accepted on the CURRENT base model
sha, and answers ``{ok, ran [worn, ghost, cutout, mesh, fit]}`` — or ``ran
[]`` when that fit exists already; ``fail`` answers ``{ok False, step "fit",
error "fit refused — stub"}``; an optional gate (threading.Event) holds the
run. ``expression_regen.render_character_image`` = a recorder writing an
8x8 RGB PNG and the sidecar render_character_image writes (equipped
pieces/items, ``mesh_variant``, ``mesh_token`` when non-empty — both from
the mesh-input profile — plus ``sidecar_extra``). ``run_rembg`` = the 8x8
matte of smoke_base_body_outfit (2 px transparent border).
``body_retexture.retexture`` = copies its input GLB to ``out`` (the
unrigged base with the rigged base's colour) and returns ``{}``.
``model3d._auto_retexture`` / ``_attach_measurement`` / ``_auto_extension_rig``
no-ops, ``request_lod`` recorder, no extension groups, identity delivery
path, ``model_refs.trigger_now`` recorder, ``schedule_outfit_render`` no-op.
Assembly, graft, validator, the signature rule, the FIFO and the GC keep are
REAL.

Fixture: Demo (human-roleplay, profile image, on the pipeline, no hair
slot -> no hair item), base images ``tpose[_<view>]_<B1>`` (8x8 RGBA) and
the base models of smoke_garment_chain (``base_bodies``: unrigged + rigged
with the 52 Mixamo joints). Offline (human, pipeline OFF), Pet
(animal-default, ``model_pipeline: base_body`` but not humanoid).
Items (explicit ids): dress {slots [top], covers [bottom], own_mesh,
"a long red dress"}, skirt {[bottom], "a blue pleated skirt"}, shorts
{[bottom], "grey denim shorts"}, coat {[outer], own_mesh, "a green wool
coat"}, shoes {[feet], "white sneakers"}. Demo and Offline hold all five.

Expected, derived by hand from the brief:

[1] Mesh token / signature (Review Focus 2, 4).
    a. PIN: model_refs of commit 0b532d33 (``git show``) signs a worn state
       as mesh_signature(p, i, n, mesh_variant(n, p)). Demo in {feet:
       shoes} (nothing flagged): token "" and current_outfit_state's
       signature == that pinned signature; outfit_batch._signature == it.
    b. Demo in X1 = {top: dress, bottom: skirt, feet: shoes}: token
       "|meshitems:dress|worn:bottom=skirt;feet=shoes;top=dress" (the FULL
       pieces — skirt is hidden under the dress by covers); signature !=
       the pinned one; outfit_signature (2D) == the pinned rule's 2D key.
    c. Covers collapse: X2 = X1 with shorts instead of skirt.
       outfit_signature(X1) == outfit_signature(X2) (the 2D collapse) but
       outfit_batch._signature(X1) != _signature(X2). Flag off:
       _signature(X1) == _signature(X2) == the pinned signature of X1, and
       current_outfit_state == pinned (flipping back restores the old key,
       Review Focus 1). Flag on again for the rest.
    d. Off the pipeline: Offline wearing X1 -> token "", signature ==
       pinned; Pet -> token "" for {top: dress}.
[2] Order + dress text (Review Focus 1). Demo wears X = {top: dress,
    bottom: skirt, outer: coat, feet: shoes}; dress ``ok``, coat ``fail``;
    world setting ``base_body.dressed_side_views`` on.
    generate_model_ref_images(Demo, kinds ("tpose",)):
    - the chains run through Demo's FIFO, sorted (coat, dress), one at a
      time (max concurrency 1), each once, on the worker thread
      "garment-Demo";
    - the dressed front (occasion outfit_front) prompt names "a blue
      pleated skirt" (covered by the dress before, painted now), "a green
      wool coat" (its chain failed), "white sneakers" — NOT "a long red
      dress"; its sidecar mesh_items = {intended [coat, dress], effective
      [dress], warnings ["Coat stays painted on: fit — fit refused — stub
      — Regenerate in the Wardrobe"]} and mesh_token = the token of X;
      garments/failed/coat_<fsig>.json {step fit, error "fit refused —
      stub"}, none for dress;
    - back, left, right: draft + fit, no outfit text in either prompt
      (none of the four fragments); every view's sidecar carries the
      front's mesh_items (the side views follow the front too);
    - after_mesh_item_ready was asked for dress (its fit was accepted in
      the run) and found nothing to rebuild (no front named it pending).
    Baseline, flag OFF (signature of X without token) — the SECOND outfit
    render after the coat failed: no chain runs at all (coat's failure is
    cached for its fsig, dress is not flagged); the front prompt names "a
    long red dress" and NOT "a blue pleated skirt" (covered); mesh_items
    {intended [coat], effective [], warnings [the coat warning]}. Flag on
    again.
[3] Failed chain -> texture + warning (Review Focus 3).
    generate_for_current_outfit(Demo) for X: ok; the bare sidecar carries
    mesh_items, mesh_token, garment_warnings[0] = the coat warning;
    outfit_info warnings contain it; the bare file has no garment node,
    model3d/assembled/<sig>.glb has "garment_clothing_dress" and NO coat
    node; outfit_model_steps: row mesh_items WARNING "own mesh: Dress ·
    painted on: Coat" and a garment_warnings row.
[3b] Later fit (coat -> ok): run_queued(Demo, [coat]) is automatic ->
    {cached True}, no run; start_garment(Demo, coat) (explicit) runs it
    once and clears the failure record -> the hook
    after_mesh_item_ready(Demo, coat) asks trigger_now(kinds ("tpose",),
    force False) once; dressed_image(front) of X is None (stale);
    model3d._on_older_base(model) True; outfit_info status "stale",
    stale_reason "mesh_item_ready"; dressed_freshness of the front: stale,
    reason "An own-mesh piece painted on here has its garment mesh now".
    A new generate_dressed_images pass: the front prompt names skirt and
    sneakers, neither dress nor coat; mesh_items effective [coat, dress],
    warnings [].
[3c] All pieces own meshes: Demo in {top: dress, outer: coat} -> the front
    is the base copy (sidecar dressed False, mesh_token
    "|meshitems:coat,dress|worn:outer=coat;top=dress", mesh_items
    effective [coat, dress]); the model build is the base copy, its
    assembly carries both garment nodes.
[4] Assembly per signature (Review Focus 1): with Demo now in {feet: shoes}
    _wanted_for(the X model) == [dress] (its effective set, not the
    current pieces), the all-mesh model -> [coat, dress]; a sidecar without
    mesh_items -> []; dress flag off -> the X model still [dress]
    (flag on again); Demo switched off the pipeline -> [] (on again).
[5] GC keep (Review Focus 5): Demo in {feet: shoes}, holding dress and
    coat: _garment_keep contains garment:dress_<fsig> and
    garment:coat_<fsig>, not a stray garment:skirt_<12 hex> group; dress
    taken out of the inventory -> its group is no longer kept.
    _entry_valid of the X model (manifest with mesh_token) True; the same
    manifest without mesh_token False.
[6] FIFO (several garments of one character): X worn, base model bytes
    rewritten (new sha -> both fits stale), coat ``ok`` with a gate:
    after_base_model True; while coat runs, Demo's queue holds [dress];
    after_base_model again -> True, queue [dress, coat] (dress reused, the
    running coat queued again); released -> runs coat, dress, coat in that
    order, max concurrency 1, idle afterwards. Off pipeline:
    after_base_model(Offline) False, resolve_mesh_items(Offline, X) {} and
    resolve_mesh_items(Pet, {top: dress}) {} without a run (Review Focus 4).
[8] Fix round 1 (a failed chain is not retried automatically): coat
    ``fail``, X worn. start_garment twice -> two runs (explicit runs ignore
    the cache). In-memory status cleared (= restart): cached_failure step
    "fit", garment_info failed.error "fit refused — stub"; resolve_mesh_items
    runs only dress (done chain), not coat, and coat's accepted fit from [6]
    still serves (effective [coat, dress]); run_queued -> cached. Coat's
    prompt fragment changed -> new fsig -> not cached, run_queued runs coat,
    the new failure is recorded. A fit failure holds on its base model sha
    only (another sha -> None: the fit depends on the base model, which the
    fsig leaves out); a mesh failure holds on any. Base model rewritten (new
    sha) with coat's mesh failure recorded: after_base_model True, runs
    only dress.
[7] _fit dispatch (Task 3, 0b532d33): garments._fit for kind clothing
    calls garment_fit.fit_clothing (slots [top], masks body + garment) and
    gates with CLOTHING_GATES; for kind hair fit_hair with GATES. Both
    stubs refuse -> _Refused(step "fit", "fit refused — stub refusal").
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

PIN = "0b532d33"
FAILS = []
BASE_PX = {"front": (200, 10, 10), "back": (10, 200, 10), "left": (10, 10, 200), "right": (200, 200, 10)}
COAT_WARN = "Coat stays painted on: fit — fit refused — stub — Regenerate in the Wardrobe"
FRAG = {"dress": "a long red dress", "skirt": "a blue pleated skirt", "shorts": "grey denim shorts",
        "coat": "a green wool coat", "shoes": "white sneakers"}


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


def pinned_model_refs():
    """``app/core/model_refs.py`` as of commit PIN, loaded as its own module."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{PIN}:app/core/model_refs.py"],
                            capture_output=True, text=True, check=True).stdout
    module = types.ModuleType(f"model_refs_{PIN}")
    module.__file__ = str(ROOT / "app/core/model_refs.py")
    exec(compile(source, f"model_refs@{PIN}", "exec"), module.__dict__)
    return module


def garment_quad(item_id: str):
    from app.core.glb_mesh import GarmentMesh
    P = np.array([[0.0, 1.0, 0.25], [0.1, 1.0, 0.25], [0.1, 1.1, 0.25], [0.0, 1.1, 0.25]])
    return GarmentMesh(positions=P, normals=None, uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float),
                       indices=np.array([[0, 1, 2], [0, 2, 3]]), joints=np.zeros((4, 4), np.int64),
                       weights=np.tile([1.0, 0, 0, 0], (4, 1)), joint_names=["mixamorig:Spine2"],
                       image=png(colour_of(item_id), 8), mime="image/png")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-outfit-") as tmp:
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
        from app.core import (base_body, body_retexture, expression_regen, extension_rig, garment_assembly,
                              garment_fit, garment_set, garments, glb_delivery, glb_mesh, model3d,
                              model_overview, model_refs, outfit_batch, outfit_cache_gc, sync_topics)
        from app.core import garment_store as gs
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        old = pinned_model_refs()

        # --- stubs -------------------------------------------------------------
        RENDERS, RUNS, TRIGGERS, HOOKS, LODS = [], [], [], [], []
        mode = {"dress": "ok", "coat": "fail"}
        gates = {}
        live = {"now": 0, "max": 0}
        live_lock = threading.Lock()

        def run_locked(character_name, item, kind, wanted, view, force):
            item_id = item["id"]
            with live_lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            try:
                RUNS.append((character_name, item_id, threading.current_thread().name))
                if item_id in gates:
                    gates[item_id].wait(30)
                fsig = gs.garment_fsig(character_name, item_id)
                if mode.get(item_id) != "ok":
                    return {"ok": False, "fsig": fsig, "step": "fit", "error": "fit refused — stub",
                            "gates": None, "ran": []}
                bsig = base_body.base_signature(character_name)
                rigged = (get_character_dir(character_name) / "model3d" / f"{bsig}.glb").read_bytes()
                sha = hashlib.sha256(rigged).hexdigest()
                fit = gs.garment_path(character_name, item_id, fsig, "fit")
                if gs.read_record(fit.with_suffix(".json")).get("base_model_sha256") == sha:
                    return {"ok": True, "fsig": fsig, "ran": []}
                fit.parent.mkdir(parents=True, exist_ok=True)
                fit.write_bytes(glb_mesh.graft(rigged, garment_quad(item_id), name=f"garment_{kind}_{item_id}",
                                               extras={"kind": kind, "item_id": item_id, "fsig": fsig}))
                gs.write_record(fit.with_suffix(".json"), {
                    "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "base_signature": bsig,
                    "base_model_sha256": sha})
                return {"ok": True, "fsig": fsig, "ran": ["worn", "ghost", "cutout", "mesh", "fit"]}
            finally:
                with live_lock:
                    live["now"] -= 1

        garments._run_locked = run_locked

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
            RENDERS.append({"stem": Path(output_stem).name, "occasion": kw.get("occasion"),
                            "prompt": kw.get("bare_prompt") or "", "extra": dict(kw.get("sidecar_extra") or {})})
            target = Path(str(output_stem) + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), colour_of(target.stem)).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            token = model_refs.mesh_items_token(character_name, equipped_pieces, profile)
            meta = {"equipped_pieces": equipped_pieces or {}, "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    **({"mesh_token": token} if token else {}), **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        def retexture(glb_in, views, out_glb, *, proof, atlas, **kw):
            Path(out_glb).write_bytes(Path(glb_in).read_bytes())
            return {}

        expression_regen.render_character_image = render
        charmod.run_rembg = rembg
        body_retexture.retexture = retexture
        model3d._auto_retexture = lambda *a, **k: None
        model3d._attach_measurement = lambda *a, **k: None
        model3d._auto_extension_rig = lambda *a, **k: None
        model3d.request_lod = lambda name, path: LODS.append(path.name) or False
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None
        model_refs.trigger_now = lambda name, kinds=None, **kw: TRIGGERS.append((name, kinds, kw)) or None
        model_refs.schedule_outfit_render = lambda name: None
        real_hook = base_body.after_mesh_item_ready

        def hook(name, item_id):
            result = real_hook(name, item_id)
            HOOKS.append((name, item_id, result))
            return result

        base_body.after_mesh_item_ready = hook
        config._CONFIG.setdefault("base_body", {})["dressed_side_views"] = True

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name in ("Demo", "Offline"):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)),
                                                           create_new=True), True)
            images = get_character_images_dir(name)
            images.mkdir(parents=True, exist_ok=True)
            (images / f"{name}_1.png").write_bytes(png((50, 60, 70)))
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"profile image {name}", save_character_profile(name, stored), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        check("create Pet", save_character_profile("Pet", {"template": "animal-default", "gender": "female",
                                                           "model_pipeline": "base_body"}, create_new=True), True)

        def piece(item_id, slots, *, covers=(), own_mesh=False):
            op = {"slots": list(slots), "covers": list(covers), "outfit_types": ["casual"]}
            if own_mesh:
                op["own_mesh"] = True
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=FRAG[item_id], outfit_piece=op)["id"]

        check("items", [piece("dress", ["top"], covers=["bottom"], own_mesh=True), piece("skirt", ["bottom"]),
                        piece("shorts", ["bottom"]), piece("coat", ["outer"], own_mesh=True),
                        piece("shoes", ["feet"])], ["dress", "skirt", "shorts", "coat", "shoes"])
        for name in ("Demo", "Offline"):
            for item in FRAG:
                inventory.add_to_inventory(name, item)

        def flag(item_id, on):
            item = inventory.get_item(item_id)
            op = dict(item.get("outfit_piece") or {})
            op["own_mesh"] = on
            inventory.update_item(item_id, {"outfit_piece": op})

        def wear(name, pieces):
            stored = get_character_profile(name)
            stored["equipped_pieces"] = dict(pieces)
            save_character_profile(name, stored)
            check(f"{name} wears", inventory.get_equipped_pieces(name), dict(pieces))

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

        def write_model(colour):
            unrigged, rigged = chain.base_bodies(colour)
            (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
            (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged)
            tmpf = mdir / f".{b1}.tmp"
            tmpf.write_bytes(rigged)
            os.replace(tmpf, mdir / f"{b1}.glb")
            (mdir / f"{b1}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": b1, "format": "glb", "source": "generated"}))

        write_model((200, 160, 140))

        def pinned_sig(name, pieces):
            return old.mesh_signature(pieces, [], name, old.mesh_variant(name, pieces))

        def nodes(path):
            return sorted(n for n in chain.node_names(Path(path).read_bytes()) if str(n).startswith("garment_"))

        # --- [1] signature ------------------------------------------------------
        print("[1] mesh token and signature")
        x1 = {"top": "dress", "bottom": "skirt", "feet": "shoes"}
        x2 = {"top": "dress", "bottom": "shorts", "feet": "shoes"}
        wear("Demo", {"feet": "shoes"})
        check("a token none", model_refs.mesh_items_token("Demo"), "")
        check("a pinned: no flag worn", model_refs.current_outfit_state("Demo")[2],
              pinned_sig("Demo", {"feet": "shoes"}))
        check("a pinned: batch", outfit_batch._signature({"feet": "shoes"}, "Demo"),
              pinned_sig("Demo", {"feet": "shoes"}))
        wear("Demo", x1)
        check("b token", model_refs.mesh_items_token("Demo"),
              "|meshitems:dress|worn:bottom=skirt;feet=shoes;top=dress")
        sig_x1 = model_refs.current_outfit_state("Demo")[2]
        check("b differs from pinned", sig_x1 != pinned_sig("Demo", x1), True)
        check("b 2D key unchanged", model_refs.outfit_signature(x1, [], "Demo"),
              old.outfit_signature(x1, [], "Demo"))
        check("b batch = worn", outfit_batch._signature(x1, "Demo"), sig_x1)
        check("c 2D collapse", model_refs.outfit_signature(x1, [], "Demo") == model_refs.outfit_signature(x2, [], "Demo"),
              True)
        check("c mesh key defeats it", outfit_batch._signature(x1, "Demo") != outfit_batch._signature(x2, "Demo"),
              True)
        flag("dress", False)
        check("c flag off: collapse back", outfit_batch._signature(x1, "Demo") == outfit_batch._signature(x2, "Demo"),
              True)
        check("c flag off: pinned", model_refs.current_outfit_state("Demo")[2], pinned_sig("Demo", x1))
        flag("dress", True)
        check("c flag on again", model_refs.current_outfit_state("Demo")[2], sig_x1)
        wear("Offline", x1)
        check("d Offline token", model_refs.mesh_items_token("Offline"), "")
        check("d Offline pinned", model_refs.current_outfit_state("Offline")[2], pinned_sig("Offline", x1))
        check("d Pet token", model_refs.mesh_items_token("Pet", {"top": "dress"}), "")

        # --- [2] order and dress text ---------------------------------------------
        print("[2] chains first, then the dress text without the effective piece")
        X = {"top": "dress", "bottom": "skirt", "outer": "coat", "feet": "shoes"}
        wear("Demo", X)
        sig_x = model_refs.current_outfit_state("Demo")[2]
        token_x = "|meshitems:coat,dress|worn:bottom=skirt;feet=shoes;outer=coat;top=dress"
        check("token X", model_refs.mesh_items_token("Demo"), token_x)
        RENDERS.clear()
        model_refs.generate_model_ref_images("Demo", kinds=("tpose",))
        check("runs: FIFO sorted, once each", [r[1] for r in RUNS], ["coat", "dress"])
        check("runs on the worker", {r[2] for r in RUNS}, {"garment-Demo"})
        check("serial", live["max"], 1)
        fronts = [r for r in RENDERS if r["occasion"] == "outfit_front"]
        check("one front", len(fronts), 1)
        prompt = fronts[0]["prompt"] if fronts else ""
        check("front names", {k: FRAG[k] in prompt for k in ("dress", "skirt", "coat", "shoes")},
              {"dress": False, "skirt": True, "coat": True, "shoes": True})
        want_mesh = {"intended": ["coat", "dress"], "effective": ["dress"],
                     "warnings": [COAT_WARN]}
        front_meta = json.loads((refs / f"tpose_{sig_x}.json").read_text())
        check("front mesh_items", front_meta.get("mesh_items"), want_mesh)
        check("front mesh_token", front_meta.get("mesh_token"), token_x)
        others = [r for r in RENDERS if r["occasion"] != "outfit_front"]
        check("draft + fit occasions", sorted({r["occasion"] for r in others}),
              ["outfit_back", "outfit_back_draft", "outfit_side", "outfit_side_draft"])
        check("no outfit text after the front", [r["stem"] for r in others
                                                 if any(f in r["prompt"] for f in FRAG.values())], [])
        for v in ("back", "left", "right"):
            meta = json.loads((refs / f"tpose_{v}_{sig_x}.json").read_text())
            check(f"{v} carries the front's record", meta.get("mesh_items"), want_mesh)
            draft = json.loads((refs / "drafts" / f"tpose_{v}_{sig_x}.json").read_text())
            check(f"{v} draft record", draft.get("mesh_items"), want_mesh)
        fail_rec = gs.read_record(gs.garment_path("Demo", "coat", gs.garment_fsig("Demo", "coat"), "failed"))
        check("coat failure on disk", (fail_rec.get("step"), fail_rec.get("error")), ("fit", "fit refused — stub"))
        check("dress has none", gs.garment_path("Demo", "dress", gs.garment_fsig("Demo", "dress"),
                                                "failed").exists(), False)
        check("hook asked for dress, nothing to rebuild", HOOKS, [("Demo", "dress", False)])
        check("no rebuild triggered", TRIGGERS, [])
        print("[2] baseline: flag off")
        flag("dress", False)
        RUNS.clear()
        RENDERS.clear()
        sig_off = model_refs.current_outfit_state("Demo")[2]
        model_refs.generate_model_ref_images("Demo", kinds=("tpose",))
        fronts = [r for r in RENDERS if r["occasion"] == "outfit_front"]
        prompt = fronts[0]["prompt"] if fronts else ""
        check("off: front names", {k: FRAG[k] in prompt for k in ("dress", "skirt", "coat", "shoes")},
              {"dress": True, "skirt": False, "coat": True, "shoes": True})
        check("off: second render starts no chain (coat failed)", [r[1] for r in RUNS], [])
        off_meta = json.loads((refs / f"tpose_{sig_off}.json").read_text())
        check("off: coat painted, dress not intended", off_meta.get("mesh_items"),
              {"intended": ["coat"], "effective": [], "warnings": [COAT_WARN]})
        flag("dress", True)
        check("flag on: key of X", model_refs.current_outfit_state("Demo")[2], sig_x)

        # --- [3] failed chain -> texture + warning ----------------------------------
        print("[3] outfit model with a failed chain")
        result = model3d.generate_for_current_outfit("Demo", force=True)
        check("outfit run ok", result.get("ok"), True)
        bare = mdir / f"{sig_x}.glb"
        assembled = mdir / "assembled" / f"{sig_x}.glb"
        meta = model3d._read_sidecar(bare)
        check("bare mesh_items", meta.get("mesh_items"), want_mesh)
        check("bare mesh_token", meta.get("mesh_token"), token_x)
        check("garment_warnings[0]", (meta.get("garment_warnings") or [None])[0], want_mesh["warnings"][0])
        check("outfit_info warning", want_mesh["warnings"][0] in base_body.outfit_info("Demo")["warnings"], True)
        check("bare is bare", nodes(bare) if bare.is_file() else None, [])
        check("assembled: dress only", nodes(assembled) if assembled.is_file() else None,
              ["garment_clothing_dress"])
        overview = model_overview.outfit_model_overview("Demo", bare)
        rows = {r["id"]: r for r in (overview[0] if overview else [])}
        check("mesh_items row", (rows.get("mesh_items") or {}).get("status"), "warning")
        check("mesh_items detail", (rows.get("mesh_items") or {}).get("detail"),
              "own mesh: Dress · painted on: Coat")
        check("garment_warnings row", "garment_warnings" in rows, True)

        print("[3b] the coat's fit arrives later")
        mode["coat"] = "ok"
        HOOKS.clear()
        TRIGGERS.clear()
        RUNS.clear()
        res = garments.run_queued("Demo", ["coat"])
        check("automatic: cached failure, no run", (res["coat"].get("cached"), RUNS), (True, []))
        check("explicit run starts", garments.start_garment("Demo", "coat")["started"], True)
        check("explicit run idle", garments.wait_idle(30), True)
        check("explicit run ran", [r[1] for r in RUNS], ["coat"])
        check("failure cleared", gs.garment_path("Demo", "coat", gs.garment_fsig("Demo", "coat"),
                                                 "failed").exists(), False)
        check("hook found the painted coat", HOOKS, [("Demo", "coat", True)])
        check("rebuild asked once", TRIGGERS, [("Demo", ("tpose",), {"force": False})])
        check("front stale", base_body.dressed_image("Demo", "front", sig_x, b1), None)
        check("model stale", model3d._on_older_base(bare, model3d._current_base("Demo")), True)
        info = base_body.outfit_info("Demo")
        check("outfit_info", (info["status"], info["stale_reason"]), ("stale", "mesh_item_ready"))
        check("front freshness", model_overview.dressed_freshness(
            front_meta, bsig=b1, base_view_sha=base_body.file_sha256(refs / f"tpose_{b1}.png"),
            mesh_ready=bool(base_body.mesh_items_ready("Demo", front_meta, bsig=b1))),
            {"state": "stale", "reason": "An own-mesh piece painted on here has its garment mesh now"})
        RENDERS.clear()
        base_body.generate_dressed_images("Demo", pieces=X, items=[], signature=sig_x)
        fronts = [r for r in RENDERS if r["occasion"] == "outfit_front"]
        prompt = fronts[0]["prompt"] if fronts else ""
        check("re-render names", {k: FRAG[k] in prompt for k in ("dress", "skirt", "coat", "shoes")},
              {"dress": False, "skirt": True, "coat": False, "shoes": True})
        check("re-render record", json.loads((refs / f"tpose_{sig_x}.json").read_text()).get("mesh_items"),
              {"intended": ["coat", "dress"], "effective": ["coat", "dress"], "warnings": []})
        check("back re-rendered too", any(r["occasion"] == "outfit_back" for r in RENDERS), True)

        print("[3c] every piece its own mesh")
        wear("Demo", {"top": "dress", "outer": "coat"})
        sig_all = model_refs.current_outfit_state("Demo")[2]
        RENDERS.clear()
        model_refs.generate_model_ref_images("Demo", kinds=("tpose",))
        check("no edit render", RENDERS, [])
        all_meta = json.loads((refs / f"tpose_{sig_all}.json").read_text())
        check("base copy", (all_meta.get("dressed"), all_meta.get("mesh_token"),
                            (all_meta.get("mesh_items") or {}).get("effective")),
              (False, "|meshitems:coat,dress|worn:outer=coat;top=dress", ["coat", "dress"]))
        result = model3d.generate_for_current_outfit("Demo", force=True)
        check("all-mesh run ok", result.get("ok"), True)
        check("all-mesh assembly", nodes(mdir / "assembled" / f"{sig_all}.glb")
              if (mdir / "assembled" / f"{sig_all}.glb").is_file() else None,
              ["garment_clothing_coat", "garment_clothing_dress"])

        # --- [4] assembly per signature ----------------------------------------------
        print("[4] assembly takes the signature's effective set")
        wear("Demo", {"feet": "shoes"})

        def wanted(sig=None, meta=None):
            if meta is not None:
                return [g["item_id"] for g in garment_assembly._wanted("Demo", bare_meta=meta)]
            return [g["item_id"] for g in garment_assembly._wanted_for("Demo", mdir, sig)]

        check("X model", wanted(sig_x), ["dress"])
        check("all-mesh model", wanted(sig_all), ["coat", "dress"])
        check("no mesh_items", wanted(meta={k: v for k, v in meta.items() if k != "mesh_items"}), [])
        flag("dress", False)
        check("flag off: X model keeps its garment", wanted(sig_x), ["dress"])
        flag("dress", True)
        base_body.set_pipeline("Demo", False)
        check("off pipeline", wanted(sig_x), [])
        base_body.set_pipeline("Demo", True)

        # --- [5] GC keep ------------------------------------------------------------------
        print("[5] GC keeps the fits of held pieces")
        stray = gs.garments_dir("Demo") / "skirt_0123456789ab.glb"
        stray.write_bytes(b"x")
        keep = outfit_cache_gc._garment_keep("Demo") or set()
        fd, fc = gs.garment_fsig("Demo", "dress"), gs.garment_fsig("Demo", "coat")
        check("keeps dress + coat", {f"garment:dress_{fd}", f"garment:coat_{fc}"} <= keep, True)
        check("stray skirt not kept", "garment:skirt_0123456789ab" in keep, False)
        inventory.remove_from_inventory("Demo", "dress")
        keep = outfit_cache_gc._garment_keep("Demo") or set()
        check("dress dropped -> not kept", f"garment:dress_{fd}" in keep, False)
        inventory.add_to_inventory("Demo", "dress")
        manifest = outfit_cache_gc.read_manifest(mdir / f"{sig_x}.json")
        owned = outfit_cache_gc._inventory_ids("Demo")
        check("GC: X entry valid", outfit_cache_gc._entry_valid(sig_x, manifest, owned, set, "Demo"), True)
        check("GC: without token invalid", outfit_cache_gc._entry_valid(
            sig_x, {**manifest, "mesh_token": ""}, owned, set, "Demo"), False)

        # --- [6] FIFO ---------------------------------------------------------------------
        print("[6] per-character FIFO")
        wear("Demo", X)
        write_model((10, 160, 140))
        RUNS.clear()
        live["max"] = 0
        gates["coat"] = threading.Event()
        check("after_base_model", garments.after_base_model("Demo"), True)
        for _ in range(200):
            if RUNS:
                break
            threading.Event().wait(0.02)
        with garments._lock:
            queued = [j.item_id for j in garments._queues.get("Demo") or []]
        check("queue while coat runs", queued, ["dress"])
        check("after_base_model again", garments.after_base_model("Demo"), True)
        with garments._lock:
            queued = [j.item_id for j in garments._queues.get("Demo") or []]
        check("queue: dress reused, coat again", queued, ["dress", "coat"])
        gates["coat"].set()
        check("idle", garments.wait_idle(30), True)
        check("runs", [r[1] for r in RUNS], ["coat", "dress", "coat"])
        check("serial", live["max"], 1)
        del gates["coat"]
        RUNS.clear()
        check("Offline: no run", garments.after_base_model("Offline"), False)
        check("Offline: resolve", base_body.resolve_mesh_items("Offline", X), {})
        check("Pet: resolve", base_body.resolve_mesh_items("Pet", {"top": "dress"}), {})
        check("no run off the pipeline", RUNS, [])

        # --- [7] _fit dispatch ---------------------------------------------------------------
        print("[7] _fit dispatch per kind")
        CALLS = []

        def refuse(name):
            def stub(*args, **kw):
                CALLS.append((name, kw.get("slots"), sorted((kw.get("masks") or {}).keys())))
                return types.SimpleNamespace(ok=False, reasons=["stub refusal"], metrics={})
            return stub

        garment_fit.fit_clothing = refuse("fit_clothing")
        garment_fit.fit_hair = refuse("fit_hair")
        hair = inventory.add_item(name="Hair", category="garment", owner="Demo", item_id="hair_demo",
                                  garment={"kind": "hair", "slot": "hair", "body_slot": "hair"})["id"]
        fsig = "0123456789ab"
        for item_id in ("dress", hair):
            prepared = gs.garment_path("Demo", item_id, fsig, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"glb")
            gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
            ghost = gs.garment_path("Demo", item_id, fsig, "image", step="ghost", view="front")
            ghost.parent.mkdir(parents=True, exist_ok=True)
            ghost.write_bytes(png((90, 60, 30)))
            gs.write_record(ghost.with_suffix(".json"), {"accepted": True})
        profile = get_character_profile("Demo")
        for item_id, kind, limits in (("dress", "clothing", garment_fit.CLOTHING_GATES),
                                      (hair, "hair", garment_fit.GATES)):
            try:
                garments._fit("Demo", item_id, kind, fsig, b1, profile)
                check(f"{kind} refused", "no refusal", "_Refused")
            except garments._Refused as e:
                check(f"{kind} refusal", (e.step, e.error), ("fit", "fit refused — stub refusal"))
                check(f"{kind} gate limits", sorted((e.gates or {}).get("limits") or {}), sorted(limits))
        check("dispatch", CALLS, [("fit_clothing", ["top"], ["body", "garment"]), ("fit_hair", None, [])])

        # --- [8] a failed chain is not retried automatically ------------------------------
        print("[8] cached failure: explicit run / fsig change retry, automatic triggers skip")
        wear("Demo", X)
        mode["coat"] = "fail"
        RUNS.clear()
        check("explicit run 1", garments.start_garment("Demo", "coat")["started"], True)
        garments.wait_idle(30)
        check("explicit run 2 (despite the failure)", garments.start_garment("Demo", "coat")["started"], True)
        garments.wait_idle(30)
        check("both explicit runs ran", [r[1] for r in RUNS], ["coat", "coat"])
        gs._failed.clear()  # a restart empties the in-memory status
        check("after restart: cached", (garments.cached_failure("Demo", "coat") or {}).get("step"), "fit")
        check("garment_info reports it", (garments.garment_info("Demo", "coat").get("failed") or {}).get("error"),
              "fit refused — stub")
        RUNS.clear()
        res = base_body.resolve_mesh_items("Demo", X)
        check("automatic: no coat run (dress's done chain answers at once)", [r[1] for r in RUNS], ["dress"])
        check("automatic: result", (garments.run_queued("Demo", ["coat"])["coat"].get("cached")), True)
        check("coat's accepted fit (from [6]) still serves", res.get("effective"), ["coat", "dress"])
        fsig_a = gs.garment_fsig("Demo", "coat")
        op = dict(inventory.get_item("coat").get("outfit_piece") or {})
        inventory.update_item("coat", {"prompt_fragment": "a dark green wool coat", "outfit_piece": op})
        fsig_b = gs.garment_fsig("Demo", "coat")
        check("fsig changed", fsig_a != fsig_b, True)
        check("new fsig: not cached", garments.cached_failure("Demo", "coat"), None)
        res = garments.run_queued("Demo", ["coat"])
        check("new fsig: the chain runs", ([r[1] for r in RUNS], res["coat"].get("cached")),
              (["dress", "coat"], None))
        check("new fsig: failure recorded", gs.garment_path("Demo", "coat", fsig_b, "failed").exists(), True)
        sha_now = base_body.current_base("Demo")[1]
        check("fit failure holds on its base model",
              gs.chain_failure("Demo", "coat", fsig_b, base_model_sha=sha_now) is not None, True)
        check("fit failure: another base model retries",
              gs.chain_failure("Demo", "coat", fsig_b, base_model_sha="0" * 64), None)
        gs.record_failure("Demo", "coat", fsig_b, step="mesh", error="mesh refused", base_model_sha=sha_now)
        check("mesh failure holds on any base model",
              (gs.chain_failure("Demo", "coat", fsig_b, base_model_sha="0" * 64) or {}).get("step"), "mesh")
        RUNS.clear()
        write_model((40, 120, 140))  # new base sha: the dress's fit is stale, coat's mesh failure holds
        check("after_base_model", garments.after_base_model("Demo"), True)
        garments.wait_idle(30)
        check("after_base_model skips the failed coat", [r[1] for r in RUNS], ["dress"])

        garments.wait_idle(30)
        garment_assembly.wait_idle(30)

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
