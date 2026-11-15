#!/usr/bin/env python3
"""HairDeck as the second hair method in the garment chain (plan
docs/superpowers/plans/2026-11-09-hairdeck-hair.md, Task 4):
garment_hair.hairstyle_mode / default_mode, garment_store.steps_for / garment_hsig / the
method-aware fsig and accepted_fit, garments' ``hairdeck`` step, its fit with
the seed-43 retry, the choice among the stored seeds, and the serving after a
method switch.

Usage:
    ./.venv/bin/python scripts/smoke_garment_hairdeck_chain.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process. The fixture body, base views and base model are those of
scripts/smoke_garment_chain.py (imported). Stubs: the image service
(``generate_hair`` = recorder writing the files of a HairDeck job, ``pool`` =
one fake img2hair backend "HairDeck" whose ``extra_params`` the smoke
changes), ``garment_hairdeck.fit_hairdeck`` (recorder; returns a cap of
radius 0.19 around the rigged head centre (0, 1.58, 0) weighted by the REAL
``garment_fit.hair_weights``, ok per a queue), ``refine.decimate_to``
(copies) and ``garment_assembly.schedule`` (recorder). The graft, the fit
records, the fingerprints and the serving are REAL.

EXPECTED VALUES, DERIVED BY HAND FROM THE TASK BRIEF AND THE RULINGS
[1] The hairstyle's mode (plan 2026-11-12-unified-worn-pieces Task 13): the
    hairstyle H (``ensure_hairstyle``, the character's first) got the world's
    default mode ``base_body.hairstyle_default_mode`` = "hairdeck" (this
    smoke's world pins it); ``hairstyle_mode`` reads ``garment.mesh_mode``
    ("body"/"hairdeck"/"haar"), an item without one or with an unknown /
    removed value ("bogus", "edit_chain", "subtract") is "hairdeck" (hair items
    were made for HairDeck only before hairstyles). ``default_mode``: an
    absent, unknown or removed world value is "body", "haar" stays "haar"
    (built since strand-hair Task 13). ``set_hairstyle_mode(H, "")`` = the
    world default "hairdeck"; "haar" is stored (then back to "hairdeck"),
    "bogus" a ValueError naming the modes.
    Schema: field_default("base_body", "hairstyle_default_mode") == "body",
    the path is world-scope (config_scope.scope_of) and the section names a
    world_group that is one of WORLD_GROUPS (so Game-Admin -> Setup shows it).
[2] steps_for("hair", "hairdeck") == ("hairdeck", "fit") == GARMENT_STEPS["hair"];
    steps_for("hair", "body") == (); "edit_chain", "subtract" and any other
    method are a ValueError.
    Then H's mode = "hairdeck", backend extra_params
    {"input_steps": 30}: run_garment -> ok, ran ["hairdeck", "fit"]; ONE
    generate_hair call, input = Demo's profile picture, params {"seed": 42};
    raw/H_<hsig>/ holds the 7 job files + record.json {accepted True,
    attempt 1, seed 42, notes ["input_alpha"], error None}; ONE fit call
    with the seed-42 hair and proxy bytes and colour_target None (R4: no
    override), colour_profile = Demo's "blonde" #d3b497 = (211, 180, 151) /
    255 and length_class "medium" (the hair slot's length); the fit
    garments/H_<fsig>.glb has the node "garment_hair_H"; its record says
    method "hairdeck", inputs.hsig = hsig, inputs.seed 42, colour {target
    "#d3b497", source "profile", name "blonde", applied True, ΔE 20.0 -> 0.0
    (the stub echoes a recolour whenever a colour was asked for)}; the fsig
    is a HairDeck one; prepared/ holds
    nothing. garment_info: method "hairdeck" (source "hairstyle": the mode is the item's), steps
    ["hairdeck", "fit"], hairdeck status "accepted", fit "accepted",
    served_fsig = fsig. A second run: ran [], no call.
[3] Review Focus 2 — the base model rewritten under the same B1 with only
    another texture colour (another sha, SAME geometry): the fit stays
    accepted (Ruling A107, ``model_geometry``) — the Build's hair step finds
    nothing, calls stay (1, 1). Then rewritten with its top vertex 0.5 mm
    lower too (another geometry): after_base_model asks the Build
    ("body_change", recorded — Task 8 of plan 2026-11-12-unified-worn-pieces)
    and the Build's hair step (``build_chains``; was: after_base_model
    queued the chain itself) re-runs the fit only:
    generate_hair calls stay 1, fit calls 2, the record's base_model_sha256
    = the new sha, fsig and hsig unchanged. R2 — hair_colour "#FF8000":
    hsig unchanged, fsig changes; run_garment -> ran ["fit"], generate_hair
    still 1, colour_target (255/255, 128/255, 0/255) = (1.0, 0.50196,
    0.0); record colour {target "#ff8000", source "override", name None,
    applied True, ΔE 20.0 -> 0.0}. Back to "":
    fsig = the [3] fsig again (accepted, nothing to run).
[4] Review Focus 1 — extra_params {"input_steps": 31} (new hsig) and a job
    whose info.json notes ["no hair found"]: {ok False, step "hairdeck",
    error "HairDeck found no hair in the profile picture"}; generate_hair 2,
    fit calls unchanged; the job record accepted False with that error and
    the notes; status failed.step "hairdeck"; the served fit is still the
    [3] hairdeck fit (newest accepted fit of the method). A plain re-run
    with the note "No person found in the picture" refuses the same way
    (case-insensitive phrase match), generate_hair 3.
[5] a. extra_params {"input_steps": 32}, the fit gate refuses once, then
    accepts: ok, ran ["hairdeck", "fit"]; the two new generate_hair calls
    have seeds [42, 43]; the second fit call got the seed-43 hair; the job
    record attempt 2, seed 43, fit_attempts = 1 (attempt 1, seed 42, ok
    False); the fit record inputs seed 43 / attempt 2, refused_attempts 1.
    Running totals (generate_hair, fit): after [4] (3, 3), after a (5, 5).
    b. extra_params {"input_steps": 33}, both fits refuse (totals (7, 7)):
    {ok False, step "fit"}, gates.attempts = [(1, 42, False), (2, 43, False)], the error
    says "fit refused for every stored HairDeck seed (42, 43)"; no fit file
    under the current fsig; the job record keeps both fit_attempts; status
    failed.step "fit", running_step None.
    c. A plain re-run of b: both stored seeds (42, 43) are fitted again (2
    fit calls, both refused) and, with HAIRDECK_ATTEMPTS = 2 seeds stored,
    HairDeck is NOT asked for a third (generate_hair unchanged): refused
    with 2 attempts (totals (7, 9)).
[6] Review Focus 3 — serving after a switch (no generation call anywhere
    in [6]: generate_hair and fit counts unchanged). A synthetic accepted
    LEFTOVER edit-chain fit E = garments/H_e0e0e0e0e0e0.glb (record without
    "method" = the removed edit chain, accepted on the current base model,
    written LAST = newest). Method hairdeck, current fsig refused ([5b]):
    wanted_garments serves the [5a] fit (newest accepted HAIRDECK fit), not
    E. H's stored mode set to the removed "edit_chain" (written into the item
    directly — no setter takes it): read as hairdeck -> still [5a], never E.
    Mode body: no hair served ({}: the hair is in the body mesh), no hair
    summary. E removed, mode hairdeck again: the [5a] fit, no call.
[7] Fix round 1 — cache GC (outfit_cache_gc) keeps, per hair item, the
    current fsig, the served fit and the newest accepted fit of EACH method.
    Two synthetic edit-chain fits accepted on the current base model:
    E_old = H_aaaaaaaaaaaa (written first) and E = H_<edit fsig> (written
    second, newer). Method hairdeck: current fsig = the [5b] fsig (no
    garment files: the HairDeck job folders are not garment groups), served
    = newest hairdeck = [5a]. Stale garment keys = exactly the superseded
    fits: the [2]/[3] hairdeck fit H_<f_hd>, the [3] colour fit H_<f_col>
    and E_old. purge_stale(those + E + [5a]) skips 2 (E, [5a]) and removes
    the three; the four HairDeck job folders stay (E stays too: the GC keeps
    the newest fit of every method a record names — deleting the leftovers
    is the migration's, Task 3); H's stored mode "edit_chain" still serves
    [5a], no generation call.
[8] Coordinator ruling 2026-11-09 — every stored seed is weighed. Back on
    the [5a] hsig (extra_params {"input_steps": 32}): the job folder stores
    seeds [42, 43]; the [5a] fit chose 43 (42 was refused then). The stub
    now answers per seed: 42 -> max_push_m 0.05, 43 -> 0.08 (both pass the
    0.12 gate). run_garment(steps "fit", force) -> ok, ran ["fit"], NO
    generate_hair call, 2 fit calls (one per stored seed, ascending: the
    seed-42 then the seed-43 bytes); the [5a] fit record now names seed 42
    (inputs.seed 42, attempt 1 = 42's position, nohead_sha256 = sha of the
    seed-42 file, max_push_m 0.05) and lists seeds [(42, True, 0.05), (43,
    True, 0.08)]; refused_attempts []; the job record keeps seed 43 (the
    newest run) and fitted_seeds the same two; garment_info's fit step is
    "accepted" (freshness follows the fit's own seed file). hairdeck_panel:
    seed 42, job_seed 43, seeds_tried 2. A tie (both 0.07) -> the lower
    seed, 42, again 2 fit calls. Seed 43 better (42 -> 0.09, 43 -> 0.03) ->
    43. Bound: a folder with the files of seeds 40..45 (the 4 seed-file
    kinds each) pruned with keep_also 41 keeps 41 + the newest four (42..45)
    and returns [40]; _stored_seeds of the [5a] folder = [42, 43] (info.json
    / prep.png carry no seed).
[9] HairDeck fixes 2026-11-09 — length class and named colour. Demo (hair
    slot medium / blonde): hair_length_class "medium", profile_hair_colour
    {blonde, #d3b497}. From the appearance alone (hair slot empty; the
    Appearance's hair text passed as ``text``): "brown
    eyes and black hair" -> (None, "black": the colour word nearest before
    "hair"); "short dark brown hair, a full beard" -> ("short", "dark
    brown"); "long hair" -> ("long", None). (``length_phrase`` went with the
    hair edit chain.)
    The stub's moved_share 0.93 (Kai's seed 43), push 0.01. The hairstyle's
    description set to "short brunette hair" (plan Task 13: the text is the
    hairstyle's; not the Appearance's, so its length is the class word):
    description changes -> fsig new, hsig the [8] one;
    run_garment -> ok, ran ["fit"], no HairDeck call, 2 fit calls (seeds 42,
    43) with length_class "short" and colour_profile (92, 59, 38) / 255;
    both pass (0.93 <= 0.97) -> tie -> seed 42; record length_class "short",
    gates.limits.moved_share ["max", 0.97], colour {"#5c3b26", profile,
    brunette, applied, 20.0 -> 0.0}; hairdeck_panel colour {target None,
    source "profile", profile {brunette, #5c3b26}, fitted = that record
    colour}. Description "medium brunette hair": both seeds refused ("moved_share
    0.93 > 0.9"), 2 seeds stored -> no HairDeck call: {ok False, step
    "fit"}, fit calls +2.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
#: sRGB 0..1 of the named colours (garment_hair.HAIR_COLOURS), rounded like the checks.
BLONDE = (round(211 / 255, 5), round(180 / 255, 5), round(151 / 255, 5))
BRUNETTE = (round(92 / 255, 5), round(59 / 255, 5), round(38 / 255, 5))
#: The fsig of the leftover edit-chain fit E ([6], [7]): any 12-hex fsig the current method never names.
F_EDIT = "e0e0e0e0e0e0"
JOB_FILES = ("hair_seed{s}_nohead.glb", "hair_seed{s}.glb", "chains_seed{s}.json", "cards_seed{s}.json",
             "info.json", "prep.png", "model_input.png")


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-hairdeck-chain-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        # A hair method that makes a hair item (the default "body" of the hair-from-body spec 2026-11-11 makes none).
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                        "base_body": {"hairstyle_default_mode": "hairdeck"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        import smoke_garment_chain as cx
        from app.blender import refine
        from app.core import (base_body, config_scope, garment_assembly, garment_fit, garment_hair,
                              garment_hairdeck, glb_mesh, sync_topics)
        from app.core import garment_store as gs
        from app.core.config_schema import SECTIONS, WORLD_GROUPS, field_default
        from app.core.keyed_lock import keyed_lock
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.core import garments

        # --- stubs -------------------------------------------------------------
        HAIR_CALLS, FIT_CALLS, SCHEDULED = [], [], []
        mode = {"notes": ["input_alpha"], "fit_ok": [], "push": {}, "moved": None}
        backend = SimpleNamespace(name="HairDeck", MEDIA_TYPE="mesh", category="img2hair", instance_enabled=True,
                                  effective_cost=0, extra_params={"input_steps": 30})

        class FakeService:
            pool = SimpleNamespace(backends=[backend])

            def generate_hair(self, image_path, output_dir, *, backend_glob="", character_name="", params=None,
                              hub_stage=None):
                n = len(HAIR_CALLS) + 1
                seed = int((params or {}).get("seed"))
                HAIR_CALLS.append({"image": image_path, "params": dict(params or {}), "seed": seed,
                                   "character": character_name})
                files = []
                for pattern in JOB_FILES:
                    name = pattern.format(s=seed)
                    path = Path(output_dir) / name
                    if name == "info.json":
                        path.write_text(json.dumps({"ok": True, "notes": list(mode["notes"]),
                                                    "box": [1, 2, 3, 4]}))
                    else:
                        path.write_bytes(f"{name}-call{n}".encode())
                    files.append({"name": name, "mime": "application/octet-stream", "path": str(path)})
                return {"files": files, "backend": "HairDeck", "route": {"routing": {"occasion": "hair_mesh"}},
                        "job_id": f"job-{n}"}

        service.get_image_service = lambda: FakeService()

        def fit_stub(nohead_glb, proxy_glb, rigged_base_glb, *, colour_target, forward_m=None, tilt_deg=None,
                     colour_profile=None, length_class=None, chains_json=None, cards_json=None, swing=False):
            import smoke_garment_fit as fx
            FIT_CALLS.append({"nohead": nohead_glb, "proxy": proxy_glb, "colour_target": colour_target,
                              "colour_profile": colour_profile, "length_class": length_class, "swing": swing})
            seed = int(bytes(nohead_glb).split(b"_seed")[1].split(b"_")[0])
            push = mode["push"].get(seed)
            ok = True if push is not None else (mode["fit_ok"].pop(0) if mode["fit_ok"] else True)
            body = glb_mesh.body_arrays(rigged_base_glb)
            P, F = fx.cap(0.19, np.array([0.0, 1.58, 0.0]), n_el=9, nlon=24)
            names, J, W = garment_fit.hair_weights(P, body)
            garment = glb_mesh.GarmentMesh(
                positions=P, normals=garment_fit.vertex_normals(P, F), uvs=np.zeros((len(P), 2)),
                indices=np.asarray(F, np.int64).reshape(-1, 3), joints=J, weights=W, joint_names=names,
                material={"doubleSided": True}, colors=np.tile([0.3, 0.2, 0.1, 1.0], (len(P), 1)))
            m = {"max_push_m": push if push is not None else (0.01 if ok else 0.2),
                 "moved_share": mode["moved"] if mode["moved"] is not None else 0.3, "icp_resid_p95_m": 0.004}
            gate_ok, reasons = garment_hairdeck.gate(m, length_class)
            # The real fit's colour report, echoed: a recolour happened whenever a colour was asked for.
            colour = ({"applied": True, "delta_e_before": 20.0, "delta_e_after": 0.0}
                      if colour_target or colour_profile else {})
            return garment_fit.FitResult(garment=garment, metrics=m, ok=gate_ok, reasons=reasons,
                                         report={"colour": colour})

        garment_hairdeck.fit_hairdeck = fit_stub

        def decimate_to(path_in, target_tris, out, merge_vertices=False, **_kw):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(path_in).read_bytes())
            return {"ok": True, "path": str(out), "tris": target_tris, "ratio": 0.5, "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        sync_topics.changed_at = lambda *a, **k: None
        # Task 8 (plan 2026-11-12-unified-worn-pieces): every hook is a Build request now — recorded, so no
        # automatic Build runs beside the chain; the body change runs the Build's chain steps (build_chains).
        from _figure_build_fixtures import build_chains, record_requests
        REQUESTS = record_requests()

        # --- fixture (smoke_garment_chain's Demo) ------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(cx.solid_png((50, 60, 70), 8))

        def set_profile(**values):
            with keyed_lock("character_profile", "Demo"):
                stored = get_character_profile("Demo")
                stored.update(values)
                check(f"profile {sorted(values)}", save_character_profile("Demo", stored), True)

        set_profile(profile_image="Demo_1.png")
        hid = garment_hair.ensure_hairstyle("Demo")
        check("hair item worn", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hid})
        cdir = get_character_dir("Demo")
        refs, mdir = cdir / "model_refs", cdir / "model3d"

        def write_model(bsig, colour, nudge=0.0):
            unrigged, rigged = cx.base_bodies(colour)
            if nudge:  # a geometry change: one top vertex moved down
                from app.core import glb_mesh
                prims = glb_mesh.body_primitive_arrays(rigged)
                top = max(range(len(prims)), key=lambda i: prims[i].positions[:, 1].max())
                prims[top].positions[int(prims[top].positions[:, 1].argmax()), 1] -= nudge
                rigged = glb_mesh.rewrite_body_primitives(rigged, {top: prims[top]})
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
            (refs / f"{stem}.png").write_bytes(cx.png(cx.BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        write_model(b1, (200, 160, 140))

        def counts():
            return len(HAIR_CALLS), len(FIT_CALLS)

        def fit_record(fsig):
            return gs.read_record(gs.garment_path("Demo", hid, fsig, "fit").with_suffix(".json"))

        def served():
            wanted = garment_assembly.wanted_garments("Demo")
            return wanted[hid][0].name if hid in wanted else None

        def set_mode(mode):
            """Write H's stored mode directly (any string — the removed ones too)."""
            garment = dict(inventory.get_item(hid)["garment"])
            garment["mesh_mode"] = mode
            check(f"stored mode {mode!r}", inventory.update_item(hid, {"garment": garment}) is not None, True)

        # --- [1] the hairstyle's mode ----------------------------------------------
        print("[1] hairstyle mode resolution")
        check("first hairstyle: the world default", garment_hair.hairstyle_mode(inventory.get_item(hid)), "hairdeck")
        check("worn mode", garment_hair.hair_mode("Demo"), "hairdeck")
        for gone in ("bogus", "edit_chain", "subtract"):
            check(f"stored {gone} -> hairdeck",
                  garment_hair.hairstyle_mode({"garment": {"kind": "hair", "mesh_mode": gone}}), "hairdeck")
        check("no mode -> hairdeck", garment_hair.hairstyle_mode({"garment": {"kind": "hair"}}), "hairdeck")
        for stored in ("body", "hairdeck", "haar"):
            check(f"stored {stored}",
                  garment_hair.hairstyle_mode({"garment": {"kind": "hair", "mesh_mode": stored}}), stored)
        for gone in ("bogus", "edit_chain", "subtract"):
            config._CONFIG["base_body"] = {"hairstyle_default_mode": gone}
            check(f"world {gone} -> default", garment_hair.default_mode(), "body")
        config._CONFIG["base_body"] = {"hairstyle_default_mode": "haar"}
        check("world haar", garment_hair.default_mode(), "haar")
        config._CONFIG["base_body"] = {"hairstyle_default_mode": "hairdeck"}
        check("world hairdeck", garment_hair.default_mode(), "hairdeck")
        check("set body", garment_hair.set_hairstyle_mode("Demo", hid, "body"), True)
        check("body stored", garment_hair.hair_mode("Demo"), "body")
        check("set '' -> world default", (garment_hair.set_hairstyle_mode("Demo", hid, ""),
                                         garment_hair.hair_mode("Demo")), (True, "hairdeck"))
        check("set haar", (garment_hair.set_hairstyle_mode("Demo", hid, "haar"), garment_hair.hair_mode("Demo")),
              (True, "haar"))
        check("set hairdeck again", (garment_hair.set_hairstyle_mode("Demo", hid, "hairdeck"),
                                     garment_hair.hair_mode("Demo")), (True, "hairdeck"))
        try:
            garment_hair.set_hairstyle_mode("Demo", hid, "bogus")
            check("set bogus raises", False, True)
        except ValueError as e:
            check("set bogus raises", "hair mode must be one of" in str(e), True)
        check("schema default", field_default("base_body", "hairstyle_default_mode"), "body")
        check("world scope", config_scope.scope_of("base_body.hairstyle_default_mode"), "world")
        check("world group listed", SECTIONS["base_body"].get("world_group") in {g["id"] for g in WORLD_GROUPS},
              True)

        # --- [2] steps, pinned edit-chain fsig, the first HairDeck run ------------
        print("[2] steps + first run")
        check("hairdeck steps", gs.steps_for("hair", "hairdeck"), ("hairdeck", "fit"))
        check("GARMENT_STEPS hair = HairDeck's", gs.GARMENT_STEPS["hair"], ("hairdeck", "fit"))
        check("body: no steps", gs.steps_for("hair", "body"), ())
        for gone in ("bogus", "edit_chain", "subtract"):
            try:
                gs.steps_for("hair", gone)
                check(f"{gone} raises", False, True)
            except ValueError:
                check(f"{gone} raises", True, True)
        f_edit = F_EDIT

        garment_hair.set_hairstyle_mode("Demo", hid, "hairdeck")
        h1 = gs.garment_hsig("Demo", hid)
        f_hd = gs.garment_fsig("Demo", hid)
        res = garments.run_garment("Demo", hid)
        check("ok", (res.get("ok"), res.get("fsig"), res.get("ran")), (True, f_hd, ["hairdeck", "fit"]))
        check("calls", counts(), (1, 1))
        check("hair input", (Path(HAIR_CALLS[0]["image"]).name, HAIR_CALLS[0]["params"]),
              ("Demo_1.png", {"seed": 42}))
        job = gs.hairdeck_dir("Demo", hid, h1)
        check("job files", sorted(p.name for p in job.iterdir()),
              sorted([n.format(s=42) for n in JOB_FILES] + ["record.json"]))
        rec = gs.read_record(job / "record.json")
        check("job record", {k: rec.get(k) for k in ("accepted", "attempt", "seed", "notes", "error")},
              {"accepted": True, "attempt": 1, "seed": 42, "notes": ["input_alpha"], "error": None})
        check("fit inputs", (FIT_CALLS[0]["nohead"], FIT_CALLS[0]["proxy"], FIT_CALLS[0]["colour_target"]),
              (b"hair_seed42_nohead.glb-call1", b"hair_seed42.glb-call1", None))
        check("fit swing: the default (on, Ruling H-R1)", FIT_CALLS[0]["swing"], True)
        check("fit profile colour / class", (tuple(round(c, 5) for c in FIT_CALLS[0]["colour_profile"] or ()),
                                             FIT_CALLS[0]["length_class"]), (BLONDE, "medium"))
        fit = gs.garment_path("Demo", hid, f_hd, "fit")
        check("fit node", "garment_hair_" + hid in cx.node_names(fit.read_bytes()), True)
        r = fit_record(f_hd)
        check("fit record", (r.get("accepted"), r.get("method"), r["inputs"].get("hsig"), r["inputs"].get("seed"),
                             r.get("colour")),
              (True, "hairdeck", h1, 42, {"target": "#d3b497", "source": "profile", "name": "blonde",
                                          "applied": True, "delta_e_before": 20.0, "delta_e_after": 0.0}))
        prepared = gs._root("Demo") / "prepared"
        check("prepared unused", sorted(p.name for p in prepared.iterdir()) if prepared.is_dir() else [], [])
        info = garments.garment_info("Demo", hid)
        check("info", (info["method"], info["method_source"], list(info["steps"]),
                       info["steps"]["hairdeck"]["status"], info["steps"]["fit"]["status"], info["served_fsig"]),
              ("hairdeck", "hairstyle", ["hairdeck", "fit"], "accepted", "accepted", f_hd))
        res = garments.run_garment("Demo", hid)
        check("second run", (res.get("ok"), res.get("ran"), counts()), (True, [], (1, 1)))

        # --- [3] base change and colour override re-fit only ----------------------
        print("[3] base change / colour: fit only")
        write_model(b1, (120, 90, 80))
        tex_sha = base_body.current_base("Demo")[1]
        check("texture only: base sha changed", tex_sha != r.get("base_model_sha256"), True)
        check("texture only: nothing to fit (A107)", (build_chains("Demo"), counts()), (False, (1, 1)))
        write_model(b1, (120, 90, 80), nudge=0.0005)
        new_sha = base_body.current_base("Demo")[1]
        check("base sha changed", new_sha not in (r.get("base_model_sha256"), tex_sha), True)
        check("after_base_model asks the Build", (garments.after_base_model("Demo"), REQUESTS[-1:]),
              (True, [("Demo", "body_change")]))
        check("the Build's hair step runs", build_chains("Demo"), True)
        check("idle", garments.wait_idle(60), True)
        check("calls", counts(), (1, 2))
        check("fsig/hsig unchanged", (gs.garment_fsig("Demo", hid), gs.garment_hsig("Demo", hid)), (f_hd, h1))
        check("re-fitted on the new base", fit_record(f_hd).get("base_model_sha256"), new_sha)
        check("set colour", garment_hair.set_hair_colour("Demo", hid, "#FF8000"), True)
        f_col = gs.garment_fsig("Demo", hid)
        check("colour: hsig same, fsig new", (gs.garment_hsig("Demo", hid), f_col != f_hd), (h1, True))
        res = garments.run_garment("Demo", hid)
        check("colour run", (res.get("ok"), res.get("ran"), counts()), (True, ["fit"], (1, 3)))
        check("colour target", tuple(round(c, 5) for c in FIT_CALLS[-1]["colour_target"]), (1.0, 0.50196, 0.0))
        check("colour record", fit_record(f_col).get("colour"),
              {"target": "#ff8000", "source": "override", "name": None, "applied": True, "delta_e_before": 20.0,
               "delta_e_after": 0.0})
        check("reset colour", garment_hair.set_hair_colour("Demo", hid, ""), True)
        check("colour reset -> old fsig", gs.garment_fsig("Demo", hid), f_hd)

        # --- [4] no hair found ----------------------------------------------------
        print("[4] no hair found")
        backend.extra_params = {"input_steps": 31}
        h4 = gs.garment_hsig("Demo", hid)
        check("extra_params change hsig", h4 != h1, True)
        mode["notes"] = ["no hair found"]
        res = garments.run_garment("Demo", hid)
        check("refused", (res.get("ok"), res.get("step"), res.get("error")),
              (False, "hairdeck", "HairDeck found no hair in the profile picture"))
        check("calls", counts(), (2, 3))
        rec = gs.read_record(gs.hairdeck_dir("Demo", hid, h4) / "record.json")
        check("job record", (rec.get("accepted"), rec.get("error"), rec.get("notes")),
              (False, "HairDeck found no hair in the profile picture", ["no hair found"]))
        check("status", (gs.status("Demo", hid)["failed"] or {}).get("step"), "hairdeck")
        check("still served: the [3] fit", served(), f"{hid}_{f_col}.glb")
        mode["notes"] = ["input_alpha", "No person found in the picture"]
        res = garments.run_garment("Demo", hid)
        check("no person refused", (res.get("ok"), res.get("error"), counts()),
              (False, "HairDeck found no hair in the profile picture", (3, 3)))
        mode["notes"] = ["input_alpha"]

        # --- [5] gate refusal -> seed 43 ------------------------------------------
        print("[5] fit refusal and the seed-43 retry")
        backend.extra_params = {"input_steps": 32}
        h5a, f5a = gs.garment_hsig("Demo", hid), gs.garment_fsig("Demo", hid)
        mode["fit_ok"] = [False, True]
        res = garments.run_garment("Demo", hid)
        check("a: ok", (res.get("ok"), res.get("ran")), (True, ["hairdeck", "fit"]))
        check("a: seeds", [c["seed"] for c in HAIR_CALLS[3:]], [42, 43])
        check("a: fit calls", (counts()[1], FIT_CALLS[-1]["nohead"]), (5, b"hair_seed43_nohead.glb-call5"))
        rec = gs.read_record(gs.hairdeck_dir("Demo", hid, h5a) / "record.json")
        check("a: job record", (rec.get("accepted"), rec.get("attempt"), rec.get("seed"),
                                [(a.get("attempt"), a.get("seed"), a.get("ok")) for a in rec.get("fit_attempts")]),
              (True, 2, 43, [(1, 42, False)]))
        r = fit_record(f5a)
        check("a: fit record", (r.get("accepted"), r["inputs"].get("seed"), r["inputs"].get("attempt"),
                                len(r.get("refused_attempts") or [])), (True, 43, 2, 1))

        backend.extra_params = {"input_steps": 33}
        h5b, f5b = gs.garment_hsig("Demo", hid), gs.garment_fsig("Demo", hid)
        mode["fit_ok"] = [False, False]
        res = garments.run_garment("Demo", hid)
        attempts = (res.get("gates") or {}).get("attempts") or []
        check("b: refused", (res.get("ok"), res.get("step")), (False, "fit"))
        check("b: attempts", [(a.get("attempt"), a.get("seed"), a.get("ok")) for a in attempts],
              [(1, 42, False), (2, 43, False)])
        check("b: error names both", "every stored HairDeck seed (42, 43)" in (res.get("error") or ""), True)
        check("b: calls", counts(), (7, 7))
        check("b: no fit", gs.garment_path("Demo", hid, f5b, "fit").is_file(), False)
        rec = gs.read_record(gs.hairdeck_dir("Demo", hid, h5b) / "record.json")
        check("b: job record attempts", len(rec.get("fit_attempts") or []), 2)
        st = gs.status("Demo", hid)
        check("b: status", ((st["failed"] or {}).get("step"), st["running_step"]), ("fit", None))
        mode["fit_ok"] = [False, False]
        res = garments.run_garment("Demo", hid)
        check("c: both stored seeds refuse without HairDeck",
              (res.get("ok"), res.get("step"), [(a.get("attempt"), a.get("seed"))
                                                for a in (res.get("gates") or {}).get("attempts") or []], counts()),
              (False, "fit", [(1, 42), (2, 43)], (7, 9)))

        # --- [6] method switch ----------------------------------------------------
        print("[6] method switch serves that method's fit, no generation")
        before = counts()
        edit_fit = gs.garment_path("Demo", hid, f_edit, "fit")
        shutil.copyfile(gs.garment_path("Demo", hid, f5a, "fit"), edit_fit)
        gs.write_record(edit_fit.with_suffix(".json"), {
            "accepted": True, "kind": "hair", "item_id": hid, "fsig": f_edit, "base_signature": b1,
            "base_model_sha256": base_body.current_base("Demo")[1], "inputs": {}})
        check("E is newest", edit_fit.stat().st_mtime_ns > gs.garment_path("Demo", hid, f5a, "fit").stat().st_mtime_ns,
              True)
        check("hairdeck (current refused) serves [5a]", served(), f"{hid}_{f5a}.glb")
        set_mode("edit_chain")
        check("removed edit_chain -> hairdeck", garment_hair.hair_mode("Demo"), "hairdeck")
        check("the leftover E is never served", served(), f"{hid}_{f5a}.glb")
        set_mode("body")
        check("body: no hair mesh served", garment_assembly.wanted_garments("Demo"), {})
        check("body: no hair summary", garments.hair_summary("Demo"), None)
        edit_fit.unlink()
        edit_fit.with_suffix(".json").unlink()
        set_mode("hairdeck")
        check("hairdeck again serves [5a]", served(), f"{hid}_{f5a}.glb")
        check("no generation in [6]", counts(), before)

        # --- [7] cache GC keeps the newest fit of EACH method -----------------------
        print("[7] cache GC keeps each method's newest fit")
        from app.core import outfit_cache_gc as gc
        sha_now = base_body.current_base("Demo")[1]
        e_old = "aaaaaaaaaaaa"
        for fsig in (e_old, f_edit):  # written in this order: E is the newer one
            path = gs.garment_path("Demo", hid, fsig, "fit")
            shutil.copyfile(gs.garment_path("Demo", hid, f5a, "fit"), path)
            gs.write_record(path.with_suffix(".json"), {
                "accepted": True, "kind": "hair", "item_id": hid, "fsig": fsig, "base_signature": b1,
                "base_model_sha256": sha_now, "inputs": {}})
        # E strictly newer than E_old (two copies in a row may share an mtime).
        old_ns = gs.garment_path("Demo", hid, e_old, "fit").stat().st_mtime_ns
        os.utime(gs.garment_path("Demo", hid, f_edit, "fit"), ns=(old_ns + 10**9, old_ns + 10**9))
        rep = gc.verify_cache("Demo")
        stale = sorted(k for k in rep["stale_signatures"] if k.startswith("garment:"))
        # A superseded fsig whose only file is a failed-run record
        # (garments/failed/, plan 2026-11-09-base-body-phase5 Task 4 fix
        # round 1: an earlier refused run) is stale as well.
        failed_only = {f"garment:{i}_{f}" for (i, f), files in gs.stored_groups("Demo").items()
                       if i == hid and all(p.parent.name == "failed" for p in files)
                       and f != gs.garment_fsig("Demo", hid)}
        check("failed-run records of superseded fsigs", len(failed_only) >= 1, True)
        want = sorted({f"garment:{hid}_{f}" for f in (f_hd, f_col, e_old)} | failed_only)
        check("stale = superseded fits only", stale, want)
        res = gc.purge_stale("Demo", stale + [f"garment:{hid}_{f_edit}", f"garment:{hid}_{f5a}"])
        check("purge skips both kept fits", res["skipped"], 2)
        check("kept on disk", [gs.garment_path("Demo", hid, f, "fit").is_file() for f in (f5a, f_edit)],
              [True, True])
        check("removed", [gs.garment_path("Demo", hid, f, "fit").is_file() for f in (f_hd, f_col, e_old)],
              [False, False, False])
        check("HairDeck job folders untouched",
              [gs.hairdeck_dir("Demo", hid, h).is_dir() for h in (h1, h4, h5a, h5b)], [True] * 4)
        set_mode("edit_chain")
        check("removed edit_chain still serves [5a]", served(), f"{hid}_{f5a}.glb")
        set_mode("hairdeck")
        check("and back to [5a]", served(), f"{hid}_{f5a}.glb")
        check("no generation in [7]", counts(), before)

        # --- [8] every stored seed is weighed --------------------------------------
        print("[8] re-fit picks the best stored seed without HairDeck")
        backend.extra_params = {"input_steps": 32}
        check("[5a] hsig again", (gs.garment_hsig("Demo", hid), gs.garment_fsig("Demo", hid)), (h5a, f5a))
        folder = gs.hairdeck_dir("Demo", hid, h5a)
        check("stored seeds", garments._stored_seeds("Demo", hid, h5a), [42, 43])
        check("[5a] chose 43", fit_record(f5a)["inputs"].get("seed"), 43)
        for push, want in (({42: 0.05, 43: 0.08}, 42), ({42: 0.07, 43: 0.07}, 42), ({42: 0.09, 43: 0.03}, 43)):
            mode["push"] = push
            before = counts()
            n0 = len(FIT_CALLS)
            res = garments.run_garment("Demo", hid, steps="fit", force=True)
            check(f"{push}: ok", (res.get("ok"), res.get("ran")), (True, ["fit"]))
            check(f"{push}: no HairDeck, one fit per seed", counts(), (before[0], before[1] + 2))
            check(f"{push}: fitted in seed order", [c["nohead"].split(b"-")[0] for c in FIT_CALLS[n0:]],
                  [b"hair_seed42_nohead.glb", b"hair_seed43_nohead.glb"])
            r = fit_record(f5a)
            check(f"{push}: fit record", (r["inputs"].get("seed"), r["inputs"].get("attempt"),
                                          r["inputs"].get("nohead_sha256"), r["metrics"].get("max_push_m"),
                                          [(x["seed"], x["ok"], x["max_push_m"]) for x in r.get("seeds") or []],
                                          r.get("refused_attempts")),
                  (want, [42, 43].index(want) + 1, sha(folder / f"hair_seed{want}_nohead.glb"), push[want],
                   [(42, True, push[42]), (43, True, push[43])], []))
            job = gs.read_record(folder / "record.json")
            check(f"{push}: job record", (job.get("seed"), [x["seed"] for x in job.get("fitted_seeds") or []]),
                  (43, [42, 43]))
            info = garments.garment_info("Demo", hid)
            check(f"{push}: fit fresh", (info["steps"]["fit"]["status"], info["served_fsig"]), ("accepted", f5a))
            panel = garments.hairdeck_panel("Demo", hid)
            check(f"{push}: panel", (panel["seed"], panel["job_seed"], panel["seeds_tried"]), (want, 43, 2))
        mode["push"] = {}
        bound = Path(tmp) / "prune"
        bound.mkdir()
        for s_ in range(40, 46):
            for pat in ("hair_seed{s}_nohead.glb", "hair_seed{s}.glb", "chains_seed{s}.json", "cards_seed{s}.json"):
                (bound / pat.format(s=s_)).write_bytes(b"x")
        (bound / "info.json").write_text("{}")
        check("prune returns", garments._prune_seeds(bound, 41), [40])
        check("prune keeps", sorted({int(p.name.split("seed")[1].split("_")[0].split(".")[0])
                                     for p in bound.iterdir() if "seed" in p.name}), [41, 42, 43, 44, 45])
        check("prune leaves info.json", (bound / "info.json").is_file(), True)

        # --- [9] length class and named colour -----------------------------------
        print("[9] length class gates + profile colour")
        demo = get_character_profile("Demo")
        check("class / colour of Demo", (garment_hair.hair_length_class("Demo", profile=demo),
                                         garment_hair.profile_hair_colour("Demo", profile=demo)),
              ("medium", {"name": "blonde", "hex": "#d3b497"}))
        for appearance, want in (("brown eyes and black hair", (None, "black")),
                                 ("short dark brown hair, a full beard", ("short", "dark brown")),
                                 ("long hair", ("long", None))):
            free = {**demo, "body_slots": {**demo["body_slots"], "hair": {}}, "character_appearance": appearance}
            text = garment_hair.appearance_hair_text("Demo", profile=free)
            check(f"from appearance {appearance!r}", (garment_hair.hair_length_class("Demo", profile=free, text=text),
                                                      garment_hair.hair_colour_name("Demo", profile=free, text=text)),
                  want)

        def describe(text):
            garment = dict(inventory.get_item(hid)["garment"])
            check(f"description {text!r}",
                  inventory.update_item(hid, {"garment": {**garment, "description": text}}) is not None, True)
        mode["push"], mode["moved"] = {}, 0.93
        describe("short brunette hair")
        f9 = gs.garment_fsig("Demo", hid)
        check("short: hsig kept, fsig new", (gs.garment_hsig("Demo", hid), f9 != f5a), (h5a, True))
        before = counts()
        n0 = len(FIT_CALLS)
        res = garments.run_garment("Demo", hid)
        check("short: ok, fit only", (res.get("ok"), res.get("ran"), counts()), (True, ["fit"], (before[0], before[1] + 2)))
        check("short: fit calls", [(c["length_class"], tuple(round(v, 5) for v in c["colour_profile"] or ()))
                                   for c in FIT_CALLS[n0:]], [("short", BRUNETTE)] * 2)
        r = fit_record(f9)
        check("short: record", (r["inputs"].get("seed"), r.get("length_class"), r["gates"]["limits"]["moved_share"],
                                r["metrics"].get("moved_share"), r.get("colour")),
              (42, "short", ["max", 0.97], 0.93, {"target": "#5c3b26", "source": "profile", "name": "brunette",
                                                  "applied": True, "delta_e_before": 20.0, "delta_e_after": 0.0}))
        panel = garments.hairdeck_panel("Demo", hid)
        check("short: panel colour", {k: panel["colour"].get(k) for k in ("target", "source", "profile", "fitted")},
              {"target": None, "source": "profile", "profile": {"name": "brunette", "hex": "#5c3b26"},
               "fitted": r.get("colour")})
        describe("medium brunette hair")
        before = counts()
        res = garments.run_garment("Demo", hid)
        check("medium: refused on moved_share, no HairDeck call",
              (res.get("ok"), res.get("step"), "moved_share 0.93 > 0.9" in (res.get("error") or ""), counts()),
              (False, "fit", True, (before[0], before[1] + 2)))
        mode["moved"] = None

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
