#!/usr/bin/env python3
"""HairDeck as the second hair method in the garment chain (plan
docs/superpowers/plans/2026-11-09-hairdeck-hair.md, Task 4):
garment_hair.hair_method, garment_store.steps_for / garment_hsig / the
method-aware fsig and accepted_fit, garments' ``hairdeck`` step, its fit with
the seed-43 retry, and the serving after a method switch.

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
[1] hair_method: the profile key ``hair_method`` wins when it names a method
    ("edit_chain"/"hairdeck", source "character"); "" or an unknown value
    falls to the world key ``base_body.hair_method`` (source "world"); an
    absent or unknown world value is the default "edit_chain". Schema:
    field_default("base_body", "hair_method") == "edit_chain", the path is
    world-scope (config_scope.scope_of) and the section names a world_group
    that is one of WORLD_GROUPS (so Game-Admin -> Setup shows it).
[2] steps_for("hair", "edit_chain") == ("haired", "ghost", "cutout", "mesh",
    "fit") == GARMENT_STEPS["hair"] (unchanged); steps_for("hair",
    "hairdeck") == ("hairdeck", "fit"); an unknown method is a ValueError.
    Edit-chain fsig unchanged: garment_fsig of the fixture equals the fsig
    computed by garment_store as of commit 0522ef42 (loaded from git, same
    fixture) — with no method set, with the world set to "edit_chain" and
    with the character set to "edit_chain".
    Then Demo's hair_method = "hairdeck", backend extra_params
    {"input_steps": 30}: run_garment -> ok, ran ["hairdeck", "fit"]; ONE
    generate_hair call, input = Demo's profile picture, params {"seed": 42};
    raw/H_<hsig>/ holds the 7 job files + record.json {accepted True,
    attempt 1, seed 42, notes ["input_alpha"], error None}; ONE fit call
    with the seed-42 hair and proxy bytes and colour_target None (R4: no
    override = HairDeck's own colours); the fit garments/H_<fsig>.glb has
    the node "garment_hair_H"; its record says method "hairdeck",
    inputs.hsig = hsig, inputs.seed 42, colour {target None, source
    "hairdeck"}; the fsig differs from the edit-chain fsig; prepared/ holds
    nothing. garment_info: method "hairdeck" (source "character"), steps
    ["hairdeck", "fit"], hairdeck status "accepted", fit "accepted",
    served_fsig = fsig. A second run: ran [], no call.
[3] Review Focus 2 — the base model rewritten under the same B1 (another
    texture colour -> another sha): after_base_model re-runs the fit only:
    generate_hair calls stay 1, fit calls 2, the record's base_model_sha256
    = the new sha, fsig and hsig unchanged. R2 — hair_colour "#FF8000":
    hsig unchanged, fsig changes; run_garment -> ran ["fit"], generate_hair
    still 1, colour_target (255/255, 128/255, 0/255) = (1.0, 0.50196,
    0.0); record colour {target "#ff8000", source "override"}. Back to "":
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
    names both attempts; no fit file under the current fsig; the job record
    keeps both fit_attempts; status failed.step "fit", running_step None.
    c. A plain re-run of b: the cached seed-43 job is attempt 2, so the
    refusal does not run HairDeck again (generate_hair count unchanged),
    one more fit call, refused with 1 attempt (totals (7, 8)).
[6] Review Focus 3 — serving after a switch (no generation call anywhere
    in [6]: generate_hair and fit counts unchanged). A synthetic accepted
    edit-chain fit E = garments/H_<edit fsig>.glb (record without
    "method", accepted on the current base model, written LAST = newest).
    Method hairdeck, current fsig refused ([5b]): wanted_garments serves the
    [5a] fit (newest accepted HAIRDECK fit), not E. Method edit_chain:
    serves E (= its current fsig). E removed: wanted_garments == {} (no
    hair), garment_info served_fsig None, preview_url None, steps = the
    five edit-chain steps. Method hairdeck again: the [5a] fit, no call.
[7] Fix round 1 — cache GC (outfit_cache_gc) keeps, per hair item, the
    current fsig, the served fit and the newest accepted fit of EACH method.
    Two synthetic edit-chain fits accepted on the current base model:
    E_old = H_aaaaaaaaaaaa (written first) and E = H_<edit fsig> (written
    second, newer). Method hairdeck: current fsig = the [5b] fsig (no
    garment files: the HairDeck job folders are not garment groups), served
    = newest hairdeck = [5a]. Stale garment keys = exactly the superseded
    fits: the [2]/[3] hairdeck fit H_<f_hd>, the [3] colour fit H_<f_col>
    and E_old. purge_stale(those + E + [5a]) skips 2 (E, [5a]) and removes
    the three; the four HairDeck job folders stay; switching to edit_chain
    serves E and back serves [5a], no generation call.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
PIN_COMMIT = "0522ef42"
JOB_FILES = ("hair_seed{s}_nohead.glb", "hair_seed{s}.glb", "chains_seed{s}.json", "cards_seed{s}.json",
             "info.json", "prep.png", "model_input.png")


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def old_garment_store():
    """garment_store as of PIN_COMMIT, loaded from git under its own name."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PIN_COMMIT}:app/core/garment_store.py"],
                         check=True, capture_output=True, text=True).stdout
    spec = importlib.util.spec_from_loader(f"garment_store_{PIN_COMMIT}", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(src, f"garment_store@{PIN_COMMIT}", "exec"), module.__dict__)
    return module


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
        mode = {"notes": ["input_alpha"], "fit_ok": []}
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

        def fit_stub(nohead_glb, proxy_glb, rigged_base_glb, *, colour_target, forward_m=None, tilt_deg=None):
            import smoke_garment_fit as fx
            FIT_CALLS.append({"nohead": nohead_glb, "proxy": proxy_glb, "colour_target": colour_target})
            ok = mode["fit_ok"].pop(0) if mode["fit_ok"] else True
            body = glb_mesh.body_arrays(rigged_base_glb)
            P, F = fx.cap(0.19, np.array([0.0, 1.58, 0.0]), n_el=9, nlon=24)
            names, J, W = garment_fit.hair_weights(P, body)
            garment = glb_mesh.GarmentMesh(
                positions=P, normals=garment_fit.vertex_normals(P, F), uvs=np.zeros((len(P), 2)),
                indices=np.asarray(F, np.int64).reshape(-1, 3), joints=J, weights=W, joint_names=names,
                material={"doubleSided": True}, colors=np.tile([0.3, 0.2, 0.1, 1.0], (len(P), 1)))
            m = {"max_push_m": 0.01 if ok else 0.2, "moved_share": 0.3, "icp_resid_p95_m": 0.004}
            gate_ok, reasons = garment_hairdeck.gate(m)
            return garment_fit.FitResult(garment=garment, metrics=m, ok=gate_ok, reasons=reasons, report={})

        garment_hairdeck.fit_hairdeck = fit_stub

        def decimate_to(path_in, target_tris, out, merge_vertices=False):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(path_in).read_bytes())
            return {"ok": True, "path": str(out), "tris": target_tris, "ratio": 0.5, "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        sync_topics.changed_at = lambda *a, **k: None

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
        check("pipeline", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair item worn", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hid})
        cdir = get_character_dir("Demo")
        refs, mdir = cdir / "model_refs", cdir / "model3d"

        def write_model(bsig, colour):
            unrigged, rigged = cx.base_bodies(colour)
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

        # --- [1] hair_method --------------------------------------------------------
        print("[1] hair_method resolution")
        profile = get_character_profile("Demo")
        check("default", garment_hair.hair_method_source("Demo", profile=profile), ("edit_chain", "world"))
        config._CONFIG["base_body"] = {"hair_method": "hairdeck"}
        check("world", garment_hair.hair_method_source("Demo", profile=profile), ("hairdeck", "world"))
        check("character wins", garment_hair.hair_method_source("Demo", profile={**profile,
                                                                              "hair_method": "edit_chain"}),
              ("edit_chain", "character"))
        check("character empty -> world", garment_hair.hair_method("Demo", profile={**profile, "hair_method": ""}),
              "hairdeck")
        check("character unknown -> world",
              garment_hair.hair_method("Demo", profile={**profile, "hair_method": "bogus"}), "hairdeck")
        config._CONFIG["base_body"] = {"hair_method": "bogus"}
        check("world unknown -> default", garment_hair.hair_method("Demo", profile=profile), "edit_chain")
        config._CONFIG.pop("base_body", None)
        check("schema default", field_default("base_body", "hair_method"), "edit_chain")
        check("world scope", config_scope.scope_of("base_body.hair_method"), "world")
        check("world group listed", SECTIONS["base_body"].get("world_group") in {g["id"] for g in WORLD_GROUPS},
              True)

        # --- [2] steps, pinned edit-chain fsig, the first HairDeck run ------------
        print("[2] steps + first run")
        check("edit chain steps", gs.steps_for("hair", "edit_chain"), ("haired", "ghost", "cutout", "mesh", "fit"))
        check("GARMENT_STEPS unchanged", gs.GARMENT_STEPS["hair"], ("haired", "ghost", "cutout", "mesh", "fit"))
        check("hairdeck steps", gs.steps_for("hair", "hairdeck"), ("hairdeck", "fit"))
        try:
            gs.steps_for("hair", "bogus")
            check("unknown method raises", False, True)
        except ValueError:
            check("unknown method raises", True, True)
        old = old_garment_store()
        f_edit = gs.garment_fsig("Demo", hid)
        check(f"edit fsig = {PIN_COMMIT} fsig", f_edit, old.garment_fsig("Demo", hid))
        config._CONFIG["base_body"] = {"hair_method": "edit_chain"}
        check("edit fsig, world edit_chain", gs.garment_fsig("Demo", hid), f_edit)
        config._CONFIG.pop("base_body", None)
        set_profile(hair_method="edit_chain")
        check("edit fsig, character edit_chain", gs.garment_fsig("Demo", hid), f_edit)
        check("old module agrees (character edit_chain)", old.garment_fsig("Demo", hid), f_edit)

        set_profile(hair_method="hairdeck")
        h1 = gs.garment_hsig("Demo", hid)
        f_hd = gs.garment_fsig("Demo", hid)
        check("hairdeck fsig differs", f_hd != f_edit, True)
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
        fit = gs.garment_path("Demo", hid, f_hd, "fit")
        check("fit node", "garment_hair_" + hid in cx.node_names(fit.read_bytes()), True)
        r = fit_record(f_hd)
        check("fit record", (r.get("accepted"), r.get("method"), r["inputs"].get("hsig"), r["inputs"].get("seed"),
                             r.get("colour")),
              (True, "hairdeck", h1, 42, {"target": None, "source": "hairdeck"}))
        prepared = gs._root("Demo") / "prepared"
        check("prepared unused", sorted(p.name for p in prepared.iterdir()) if prepared.is_dir() else [], [])
        info = garments.garment_info("Demo", hid)
        check("info", (info["method"], info["method_source"], list(info["steps"]),
                       info["steps"]["hairdeck"]["status"], info["steps"]["fit"]["status"], info["served_fsig"]),
              ("hairdeck", "character", ["hairdeck", "fit"], "accepted", "accepted", f_hd))
        res = garments.run_garment("Demo", hid)
        check("second run", (res.get("ok"), res.get("ran"), counts()), (True, [], (1, 1)))

        # --- [3] base change and colour override re-fit only ----------------------
        print("[3] base change / colour: fit only")
        write_model(b1, (120, 90, 80))
        new_sha = base_body.current_base("Demo")[1]
        check("base sha changed", new_sha != r.get("base_model_sha256"), True)
        check("after_base_model started", garments.after_base_model("Demo"), True)
        check("idle", garments.wait_idle(60), True)
        check("calls", counts(), (1, 2))
        check("fsig/hsig unchanged", (gs.garment_fsig("Demo", hid), gs.garment_hsig("Demo", hid)), (f_hd, h1))
        check("re-fitted on the new base", fit_record(f_hd).get("base_model_sha256"), new_sha)
        set_profile(hair_colour="#FF8000")
        f_col = gs.garment_fsig("Demo", hid)
        check("colour: hsig same, fsig new", (gs.garment_hsig("Demo", hid), f_col != f_hd), (h1, True))
        res = garments.run_garment("Demo", hid)
        check("colour run", (res.get("ok"), res.get("ran"), counts()), (True, ["fit"], (1, 3)))
        check("colour target", tuple(round(c, 5) for c in FIT_CALLS[-1]["colour_target"]), (1.0, 0.50196, 0.0))
        check("colour record", fit_record(f_col).get("colour"), {"target": "#ff8000", "source": "override"})
        set_profile(hair_colour="")
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
        check("b: error names both", "both HairDeck attempts" in (res.get("error") or ""), True)
        check("b: calls", counts(), (7, 7))
        check("b: no fit", gs.garment_path("Demo", hid, f5b, "fit").is_file(), False)
        rec = gs.read_record(gs.hairdeck_dir("Demo", hid, h5b) / "record.json")
        check("b: job record attempts", len(rec.get("fit_attempts") or []), 2)
        st = gs.status("Demo", hid)
        check("b: status", ((st["failed"] or {}).get("step"), st["running_step"]), ("fit", None))
        mode["fit_ok"] = [False]
        res = garments.run_garment("Demo", hid)
        check("c: cached attempt 2 refuses without HairDeck",
              (res.get("ok"), res.get("step"), len((res.get("gates") or {}).get("attempts") or []), counts()),
              (False, "fit", 1, (7, 8)))

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
        set_profile(hair_method="edit_chain")
        check("edit fsig back", gs.garment_fsig("Demo", hid), f_edit)
        check("edit_chain serves E", served(), f"{hid}_{f_edit}.glb")
        edit_fit.unlink()
        edit_fit.with_suffix(".json").unlink()
        check("no edit fit -> no hair", garment_assembly.wanted_garments("Demo"), {})
        info = garments.garment_info("Demo", hid)
        check("info without fit", (info["method"], info["served_fsig"], info["preview_url"], list(info["steps"])),
              ("edit_chain", None, None, ["haired", "ghost", "cutout", "mesh", "fit"]))
        set_profile(hair_method="hairdeck")
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
        rep = gc.verify_cache("Demo")
        stale = sorted(k for k in rep["stale_signatures"] if k.startswith("garment:"))
        want = sorted(f"garment:{hid}_{f}" for f in (f_hd, f_col, e_old))
        check("stale = superseded fits only", stale, want)
        res = gc.purge_stale("Demo", stale + [f"garment:{hid}_{f_edit}", f"garment:{hid}_{f5a}"])
        check("purge skips both kept fits", res["skipped"], 2)
        check("kept on disk", [gs.garment_path("Demo", hid, f, "fit").is_file() for f in (f5a, f_edit)],
              [True, True])
        check("removed", [gs.garment_path("Demo", hid, f, "fit").is_file() for f in (f_hd, f_col, e_old)],
              [False, False, False])
        check("HairDeck job folders untouched",
              [gs.hairdeck_dir("Demo", hid, h).is_dir() for h in (h1, h4, h5a, h5b)], [True] * 4)
        set_profile(hair_method="edit_chain")
        check("switch back serves E", served(), f"{hid}_{f_edit}.glb")
        set_profile(hair_method="hairdeck")
        check("and back to [5a]", served(), f"{hid}_{f5a}.glb")
        check("no generation in [7]", counts(), before)

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
