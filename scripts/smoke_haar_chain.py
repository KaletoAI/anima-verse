#!/usr/bin/env python3
"""HAAR as a hairstyle run: the strand jobs per seed, the CPU fit of every seed, the best pick, the user's pick,
the routes and the refit sweep (strand-hair spec 2026-11-13 § 6.3.1, plan 2026-11-13-strand-hair Task 13).

Usage:
    ./.venv/bin/python scripts/smoke_haar_chain.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no Blender, no server process, and ZERO outbound connections (every socket connect /
create_connection / getaddrinfo is refused and counted; [11] asserts the count is 0). The fixture body, base
views and base model are those of scripts/smoke_garment_chain.py (imported).

Stubs:
- the image service: ``generate_strands`` writes the REAL trimmed strand job of scripts/fixtures/haar_qmtest_s7/
  (16 strands x 100 points of hub job 8132167b…, its head and info.json — the seed and prompt in info.json set
  to the job's, as the hub does) under the job's ``<input_name>_*`` names and reports the stage to its
  ``hub_stage`` like a gateway submission; ``pool`` = one txt2hair backend "HAAR";
- ``garment_haar.fit_haar``: a recorder returning a cap of radius 0.19 around (0, 1.58, 0) weighted by the REAL
  ``garment_fit.hair_weights``, with per-seed metrics (the seed is read from the folder the chain read the strands
  from) judged by the REAL ``garment_haar.gate``;
- ``refine.decimate_to`` (copies), ``garment_assembly.schedule`` (recorder), ``figure_build.request`` (recorder).
The hub operation records, the graft, the fit records, the fingerprints, the ranking and the serving are REAL.

EXPECTED VALUES, DERIVED BY HAND FROM THE SPEC (§ 6.3.1 / § 6.3.2) AND THE BRIEF
The hairstyle H = create_hairstyle(Demo, "long wavy brown hair", "haar"): the first one, so worn; length class
"long" (its first class word) -> the gate's "clearly too short" bound is −1 cm and the class target −12 cm; the
named colour "brown" #5c3b26 -> colour source "profile", the cards' linear colour = sRGB→linear of (92, 59, 38) /
255 = (0.1070, 0.0437, 0.0194) (((c + 0.055) / 1.055) ** 2.4 per channel).
Metrics per seed (inside_head_3mm, eye_cards, face_cards, tip_p50_rel_shoulder_cm):
  1: (0, 0, 2, −8)   passes (−8 <= −1);
  2: (0, 0, 1, −20)  passes;
  3: (5, 0, 0, −15)  refused: "5 strands sink more than 3 mm into the head".
[1] run_estimate before: steps ["haar", "fit"], hub_jobs 3 (HUB_JOBS hair:haar = {haar 3, fit 0}), note
    "haar 3 hub jobs (~30–55 s each) + 3 CPU fits (~25 s each)". run_garment -> ok, ran ["haar", "fit"]; 3
    generate_strands calls, prompt "long wavy brown hair", params {"seed": 1}, {"seed": 2}, {"seed": 3}, each with
    a hub stage s1/s2/s3; 3 fit calls (seeds 1, 2, 3) with length_class "long" and the colour above; the seed
    folders s1..s3 hold Demo_haar_s<n>_strands.npy, Demo_haar_s<n>_head.obj, info.json; the record's seeds
    [1, 2, 3]; no hub operation left (settled = deleted).
[2] Best: seeds 1 and 2 pass, seed 2 has fewer face cards (1 < 2) -> served 2. record.chosen 2; results "3"
    accepted False with exactly the inside-head reason. The run's fsig = garment_fsig now (seed 2) != the fsig
    before the run (seed None). The fit record: method "haar", inputs.seed 2, inputs.ssig = garment_ssig,
    fit_version = HAAR_FIT_VERSION (2), gates {ok True, reasons [], picked False}, colour {target "#5c3b26",
    source "profile", name "brown"}; accepted_fit serves it; the fit GLB has the node garment_hair_<H>.
[3] run_estimate after: steps [], hub_jobs 0 ("Everything is current" in the tab). A second run_garment: ran [],
    no call (generate 3, fit 3).
[4] set_haar_seed(H, 1): True, no call; fsig changes (seed 1); run_estimate: steps ["fit"], hub_jobs 0, note
    "fit: 1 CPU fit (~25 s each), no hub job" (every seed's result holds; the served one is re-fitted). Run ->
    ran ["fit"], generate 3, fit 4 (only seed 1); record inputs.seed 1, gates {ok True, picked True}.
[5] set_haar_seed(H, None) -> fsig = the [2] fsig again, its fit accepted (nothing to run). New metrics:
    4: (0, 0, 0, −12) — 0 face cards, |−12 − (−12)| = 0; 5: (0, 0, 0, −20) — 0 face cards, off by 8;
    6: (0, 0, 0, −12) — ties seed 4 on both, loses on the seed number. The haar step forced (its own button):
    ran ["haar", "fit"], generate 6 with seeds [4, 5, 6], fit 7 (only 4, 5, 6 — 1..3 still hold) -> served 4.
    haar_panel: seeds [1..6], served only on 4, passed [True, True, False, True, True, True], next_seeds
    [7, 8, 9], jobs 3, status "passed".
[6] H2 = create_hairstyle(Demo, "long straight hair", "haar") (not worn). Every seed (1, 2, 3) refused by
    eye_cards 2: run_garment -> ok False, step "fit", error starts "no variant passed — seed 1: 2 cards hang over
    the eyes"; generate 9, fit 10; accepted_fit(H2) None; haar_panel status "no variant passed". set_haar_seed(H2,
    2): run -> ok, ran ["fit"], fit 11; accepted_fit(H2) = that fit, inputs.seed 2, gates {ok False, picked True}.
[7] Swing (hair_motion.set_hair_motion on / off) leaves H's fsig unchanged; hair_colour "#ff8000" changes it,
    "" restores it.
[8] Routes (TestClient, admin): POST /hair/method {method "haar", item_id H} -> 200 {method "haar"}; "bogus" ->
    400. POST /hair/haar-seed {seed 99} -> 400 (not stored), {seed "x"} -> 400, {seed 5} -> 200 {seed 5, served 5};
    GET /hair?item_id=H -> haar.picked 5 and 6 seeds, step_jobs {haar 3, fit 0}; {seed null} -> 200 {seed None,
    served 4}. GET /hairstyles: built_modes ["hairdeck", "haar", "body"]. No generate / fit call.
[9] Load: H3 = create_hairstyle(Demo, "short curly hair", "haar"); the stub raises BackendBusyError: run ->
    ok False, retry_later True, nothing persisted (cached_failure None), no seed stored, no hub operation left.
    A resume of an operation whose stage never reached the hub (seed 1 of H3, no job id) collects nothing and
    asks for nothing (generate unchanged).
[10] Refit sweep: HAAR_FIT_VERSION bumped to 3 -> outdated_fits lists H and H2 (method "haar");
    refit_character -> both refitted, no generate call, fit +9 (H: 6 seeds, served 4 among them; H2: 3 seeds,
    the pick 2 among them); both records fit_version 3; H served 4, H2 served 2.
[11] Outbound connections: 0.
"""
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
FIXTURE = ROOT / "scripts" / "fixtures" / "haar_qmtest_s7"
OUTBOUND = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def _refuse(*args, **kwargs):
    OUTBOUND.append(args[:2])
    raise OSError("outbound connection refused by the smoke")


def guard_sockets() -> None:
    """Refuse and count every outbound connection (the smoke must make none)."""
    socket.socket.connect = lambda self, *a, **k: _refuse(*a)
    socket.socket.connect_ex = lambda self, *a, **k: _refuse(*a)
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse


def main() -> int:
    guard_sockets()
    with tempfile.TemporaryDirectory(prefix="haar-chain-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        # No background Blender delivery copies of the fit GLBs: the smoke runs no Blender.
        (root / "instance" / "config.json").write_text(json.dumps(
            {"image_generation": {"blender_meshopt_delivery": False}}))
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                        "base_body": {"hairstyle_default_mode": "haar"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        import smoke_garment_chain as cx
        import smoke_garment_fit as fx
        from app.blender import refine
        from app.core import (base_body, garment_assembly, garment_fit, garment_hair, garment_haar, garment_refit,
                              glb_mesh, hair_motion, hub_ops, strand_file, sync_topics)
        from app.core import garment_store as gs
        from app.core.keyed_lock import keyed_lock
        from app.imagegen import service
        from app.imagegen.base import BackendBusyError
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.core import garments

        # --- stubs -------------------------------------------------------------
        GEN, FIT = [], []
        mode = {"busy": False, "metrics": {}}
        backend = SimpleNamespace(name="HAAR", MEDIA_TYPE="mesh", category="txt2hair", instance_enabled=True,
                                  effective_cost=0, extra_params={"input_steps": 50}, api_url="")

        class FakeService:
            pool = SimpleNamespace(backends=[backend])

            def generate_strands(self, prompt, output_dir, *, backend_glob="", character_name="", params=None,
                                 hub_stage=None):
                seed = int((params or {}).get("seed"))
                GEN.append({"prompt": prompt, "params": dict(params or {}), "character": character_name,
                            "stage": getattr(hub_stage, "name", None)})
                if mode["busy"]:
                    raise BackendBusyError("HAAR is busy")
                if hub_stage is not None:
                    check(f"stage s{seed} submits", hub_stage.prepare(), "submit")
                    hub_stage.submitted(backend, f"job-{len(GEN)}", {})
                name = f"{character_name}_haar_s{seed}"
                out = Path(output_dir)
                shutil.copyfile(FIXTURE / "qmtest_haar_s7_strands.npy", out / f"{name}_strands.npy")
                shutil.copyfile(FIXTURE / "qmtest_haar_s7_head.obj", out / f"{name}_head.obj")
                info = json.loads((FIXTURE / "info.json").read_text())
                info.update(seed=seed, prompt=prompt)
                (out / "info.json").write_text(json.dumps(info))
                files = [{"name": n, "mime": "application/octet-stream", "path": str(out / n)}
                         for n in (f"{name}_strands.npy", f"{name}_head.obj", "info.json")]
                return {"files": files, "backend": "HAAR", "route": {"routing": {"occasion": "hair_strands"}},
                        "job_id": f"job-{len(GEN)}"}

        service.get_image_service = lambda: FakeService()

        read_job = strand_file.read_strand_job
        last = {"dir": None}

        def read_and_note(directory):
            last["dir"] = Path(directory)
            return read_job(directory)

        strand_file.read_strand_job = read_and_note

        def fit_stub(strands, template_head, rigged_base_glb, *, colour_linear, length_class, template_faces=None):
            seed = int(last["dir"].name[1:])
            FIT.append({"seed": seed, "item": last["dir"].parent.name, "strands": strands.shape,
                        "faces": None if template_faces is None else len(template_faces),
                        "colour": colour_linear, "length_class": length_class})
            inside, eye, face, tip = mode["metrics"][seed]
            body = glb_mesh.body_arrays(rigged_base_glb)
            P, F = fx.cap(0.19, np.array([0.0, 1.58, 0.0]), n_el=9, nlon=24)
            names, J, W = garment_fit.hair_weights(P, body)
            garment = glb_mesh.GarmentMesh(
                positions=P, normals=garment_fit.vertex_normals(P, F), uvs=np.zeros((len(P), 2)),
                indices=np.asarray(F, np.int64).reshape(-1, 3), joints=J, weights=W, joint_names=names,
                material={"doubleSided": True}, colors=np.tile([0.3, 0.2, 0.1, 1.0], (len(P), 1)))
            m = {"inside_head_3mm": inside, "eye_cards": eye, "face_cards": face, "tip_p50_rel_shoulder_cm": tip}
            ok, reasons = garment_haar.gate(m, length_class)
            return garment_fit.FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons,
                                         report={"layout": "haar", "vertices": {"hair": len(P), "cap": 0}})

        garment_haar.fit_haar = fit_stub

        def decimate_to(path_in, target_tris, out, merge_vertices=False, **_kw):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(path_in).read_bytes())
            return {"ok": True, "path": str(out), "tris": target_tris, "ratio": 0.5, "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: True
        sync_topics.changed_at = lambda *a, **k: None
        from _figure_build_fixtures import record_requests
        record_requests()

        # --- fixture (smoke_garment_chain's Demo) ------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "long", "color": "brown"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(cx.solid_png((50, 60, 70), 8))
        with keyed_lock("character_profile", "Demo"):
            stored = get_character_profile("Demo")
            stored["profile_image"] = "Demo_1.png"
            check("profile image", save_character_profile("Demo", stored), True)

        print("[8a] create_hairstyle(mode='haar')")
        hid = garment_hair.create_hairstyle("Demo", "long wavy brown hair", "haar")
        check("H mode", garment_hair.hair_mode("Demo"), "haar")
        check("world default haar", garment_hair.default_mode(), "haar")

        cdir = get_character_dir("Demo")
        refs, mdir = cdir / "model_refs", cdir / "model3d"
        b1 = base_body.base_signature("Demo")
        refs.mkdir(parents=True, exist_ok=True)
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            (refs / f"{stem}.png").write_bytes(cx.png(cx.BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        unrigged, rigged = cx.base_bodies((200, 160, 140))
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged)
        (mdir / f"{b1}.glb").write_bytes(rigged)
        (mdir / f"{b1}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": b1,
                                                     "format": "glb", "source": "generated"}))
        base_sha = base_body.current_base("Demo")[1]

        def counts():
            return len(GEN), len(FIT)

        def fit_record(item, fsig):
            return gs.read_record(gs.garment_path("Demo", item, fsig, "fit").with_suffix(".json"))

        def brief(est):
            return est.get("steps"), est.get("hub_jobs"), est.get("note")

        mode["metrics"] = {1: (0, 0, 2, -8.0), 2: (0, 0, 1, -20.0), 3: (5, 0, 0, -15.0)}

        # --- [1] -----------------------------------------------------------------
        print("[1] estimate + Run all")
        check("steps_for haar", gs.steps_for("hair", "haar"), ("haar", "fit"))
        check("estimate before", brief(garments.run_estimate("Demo", hid)),
              (["haar", "fit"], 3, "haar 3 hub jobs (~30–55 s each) + 3 CPU fits (~25 s each)"))
        f_before = gs.garment_fsig("Demo", hid)
        ssig = gs.garment_ssig("Demo", hid)
        res = garments.run_garment("Demo", hid)
        check("run ok", (res.get("ok"), res.get("ran"), res.get("error")), (True, ["haar", "fit"], None))
        check("calls", counts(), (3, 3))
        check("prompts / seeds / stages", [(c["prompt"], c["params"], c["stage"]) for c in GEN],
              [("long wavy brown hair", {"seed": s}, f"s{s}") for s in (1, 2, 3)])
        check("fit seeds / class", [(c["seed"], c["length_class"], c["strands"], c["faces"]) for c in FIT],
              [(s, "long", (16, 100, 3), 64) for s in (1, 2, 3)])
        check("fit colour", tuple(round(v, 4) for v in FIT[0]["colour"]), (0.107, 0.0437, 0.0194))
        folder = gs.haar_dir("Demo", hid, ssig)
        check("seed folders", sorted(p.name for p in folder.iterdir()), ["record.json", "s1", "s2", "s3"])
        check("s2 files", sorted(p.name for p in (folder / "s2").iterdir()),
              ["Demo_haar_s2_head.obj", "Demo_haar_s2_strands.npy", "info.json"])
        rec = gs.haar_record("Demo", hid, ssig)
        check("record seeds", rec.get("seeds"), [1, 2, 3])
        check("no hub op left", [op.kind for op in hub_ops.list_ops()], [])

        # --- [2] -----------------------------------------------------------------
        print("[2] best seed served")
        check("chosen", rec.get("chosen"), 2)
        check("seed 3 refused", (rec["results"]["3"]["accepted"], rec["results"]["3"]["reasons"]),
              (False, ["5 strands sink more than 3 mm into the head"]))
        check("seeds 1, 2 pass", (rec["results"]["1"]["accepted"], rec["results"]["2"]["accepted"]), (True, True))
        f2 = gs.garment_fsig("Demo", hid)
        check("run fsig = current", res.get("fsig"), f2)
        check("fsig moved with the served seed", f2 != f_before, True)
        r = fit_record(hid, f2)
        check("fit record", (r.get("accepted"), r.get("method"), r["inputs"].get("seed"), r["inputs"].get("ssig"),
                             r.get("fit_version"), r.get("gates")),
              (True, "haar", 2, ssig, garment_haar.HAAR_FIT_VERSION, {"ok": True, "reasons": [], "picked": False}))
        check("fit colour record", r.get("colour"), {"target": "#5c3b26", "source": "profile", "name": "brown"})
        served = gs.accepted_fit("Demo", hid, base_model_sha=base_sha)
        check("served", served[0].name if served else None, f"{hid}_{f2}.glb")
        check("graft node", "garment_hair_" + hid in cx.node_names(served[0].read_bytes()), True)

        # --- [3] -----------------------------------------------------------------
        print("[3] everything current")
        check("estimate after", brief(garments.run_estimate("Demo", hid))[:2], ([], 0))
        res = garments.run_garment("Demo", hid)
        check("rerun", (res.get("ok"), res.get("ran")), (True, []))
        check("calls", counts(), (3, 3))

        # --- [4] -----------------------------------------------------------------
        print("[4] the user's pick")
        check("pick 1", garment_hair.set_haar_seed("Demo", hid, 1), True)
        check("no call", counts(), (3, 3))
        f1 = gs.garment_fsig("Demo", hid)
        check("fsig changed", f1 != f2, True)
        check("estimate: CPU fit due", brief(garments.run_estimate("Demo", hid)),
              (["fit"], 0, "fit: 1 CPU fit (~25 s each), no hub job"))
        res = garments.run_garment("Demo", hid)
        check("refit", (res.get("ok"), res.get("ran"), res.get("fsig")), (True, ["fit"], f1))
        check("calls", counts(), (3, 4))
        check("refit seed", FIT[-1]["seed"], 1)
        r = fit_record(hid, f1)
        check("picked record", (r["inputs"].get("seed"), r["gates"]), (1, {"ok": True, "reasons": [], "picked": True}))
        for bad in (0, -1, True, "2"):
            try:
                garment_hair.set_haar_seed("Demo", hid, bad)
                check(f"pick {bad!r} raises", False, True)
            except ValueError:
                check(f"pick {bad!r} raises", True, True)

        # --- [5] -----------------------------------------------------------------
        print("[5] the haar step's own button: the next seeds")
        check("pick automatic", garment_hair.set_haar_seed("Demo", hid, None), True)
        check("fsig back to [2]", gs.garment_fsig("Demo", hid), f2)
        check("nothing to run", garments.run_estimate("Demo", hid).get("steps"), [])
        mode["metrics"].update({4: (0, 0, 0, -12.0), 5: (0, 0, 0, -20.0), 6: (0, 0, 0, -12.0)})
        check("estimate redo", brief(garments.run_estimate("Demo", hid, from_step="haar"))[:2], (["haar", "fit"], 3))
        res = garments.run_garment("Demo", hid, steps="haar", force=True)
        check("redo", (res.get("ok"), res.get("ran")), (True, ["haar", "fit"]))
        check("calls", counts(), (6, 7))
        check("new seeds", [c["params"]["seed"] for c in GEN[3:]], [4, 5, 6])
        check("fitted", [c["seed"] for c in FIT[4:]], [4, 5, 6])
        panel = garments.haar_panel("Demo", hid)
        check("panel seeds", [e["seed"] for e in panel["seeds"]], [1, 2, 3, 4, 5, 6])
        check("panel served", [e["seed"] for e in panel["seeds"] if e["served"]], [4])
        check("panel passed", [e["passed"] for e in panel["seeds"]], [True, True, False, True, True, True])
        check("panel misc", (panel["next_seeds"], panel["jobs"], panel["status"], panel["picked"],
                             panel["seeds"][0]["tile_url"]), ([7, 8, 9], 3, "passed", None, None))
        f4 = gs.garment_fsig("Demo", hid)
        check("served 4", (res.get("fsig"), fit_record(hid, f4)["inputs"].get("seed")), (f4, 4))

        # --- [6] -----------------------------------------------------------------
        print("[6] every seed refused, then a pick")
        h2 = garment_hair.create_hairstyle("Demo", "long straight hair", "haar")
        check("H still worn", garment_hair.worn_hair_id("Demo"), hid)
        mode["metrics"].update({1: (0, 2, 0, -15.0), 2: (0, 2, 0, -15.0), 3: (0, 2, 0, -15.0)})
        res = garments.run_garment("Demo", h2)
        check("refused", (res.get("ok"), res.get("step")), (False, "fit"))
        check("error", str(res.get("error") or "").startswith("no variant passed — seed 1: 2 cards hang over the eyes"),
              True)
        check("calls", counts(), (9, 10))
        check("nothing served", gs.accepted_fit("Demo", h2, base_model_sha=base_sha), None)
        check("panel status", garments.haar_panel("Demo", h2)["status"], "no variant passed")
        check("pick refused 2", garment_hair.set_haar_seed("Demo", h2, 2), True)
        res = garments.run_garment("Demo", h2)
        check("pick serves", (res.get("ok"), res.get("ran")), (True, ["fit"]))
        check("calls", counts(), (9, 11))
        hit = gs.accepted_fit("Demo", h2, base_model_sha=base_sha)
        check("served pick", (hit[1]["inputs"]["seed"], hit[1]["gates"]["ok"], hit[1]["gates"]["picked"])
              if hit else None, (2, False, True))

        # --- [7] -----------------------------------------------------------------
        print("[7] fingerprint: Swing out, colour in")
        check("swing on", hair_motion.set_hair_motion("Demo", hid, True, None), True)
        check("fsig (swing on)", gs.garment_fsig("Demo", hid), f4)
        check("swing off", hair_motion.set_hair_motion("Demo", hid, False, None), True)
        check("fsig (swing off)", gs.garment_fsig("Demo", hid), f4)
        garment_hair.set_hair_colour("Demo", hid, "#ff8000")
        check("colour changes fsig", gs.garment_fsig("Demo", hid) != f4, True)
        garment_hair.set_hair_colour("Demo", hid, "")
        check("colour back", gs.garment_fsig("Demo", hid), f4)

        # --- [8] -----------------------------------------------------------------
        print("[8] routes")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.auth_dependency import require_admin
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_admin] = lambda: {"role": "admin", "username": "demo"}
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/characters/Demo/hair/method", json={"method": "haar", "item_id": hid})
            check("method haar", (r.status_code, r.json().get("method")), (200, "haar"))
            r = client.post("/characters/Demo/hair/method", json={"method": "bogus", "item_id": hid})
            check("method bogus", r.status_code, 400)
            for body in ({"seed": 99, "item_id": hid}, {"seed": "x", "item_id": hid}):
                r = client.post("/characters/Demo/hair/haar-seed", json=body)
                check(f"seed {body['seed']!r}", r.status_code, 400)
            r = client.post("/characters/Demo/hair/haar-seed", json={"seed": 5, "item_id": hid})
            check("seed 5", (r.status_code, r.json().get("seed"), r.json().get("served")), (200, 5, 5))
            r = client.get(f"/characters/Demo/hair?item_id={hid}")
            body = r.json()
            check("hair GET haar", (r.status_code, (body.get("haar") or {}).get("picked"),
                                    len((body.get("haar") or {}).get("seeds") or []), body.get("step_jobs")),
                  (200, 5, 6, {"haar": 3, "fit": 0}))
            r = client.post("/characters/Demo/hair/haar-seed", json={"seed": None, "item_id": hid})
            check("seed null", (r.status_code, r.json().get("seed"), r.json().get("served")), (200, None, 4))
            r = client.get("/characters/Demo/hairstyles")
            check("built modes", r.json().get("built_modes"), ["hairdeck", "haar", "body"])
        check("no call", counts(), (9, 11))

        # --- [9] -----------------------------------------------------------------
        print("[9] load + resume")
        h3 = garment_hair.create_hairstyle("Demo", "short curly hair", "haar")
        mode["busy"] = True
        res = garments.run_garment("Demo", h3)
        check("deferred", (res.get("ok"), res.get("retry_later"), res.get("step")), (False, True, "haar"))
        check("not persisted", garments.cached_failure("Demo", h3), None)
        s3 = gs.garment_ssig("Demo", h3)
        check("no seed", gs.haar_seeds("Demo", h3, s3), [])
        check("no hub op left", [op.kind for op in hub_ops.list_ops()], [])
        mode["busy"] = False
        n_gen = len(GEN)
        op = hub_ops.create(garments.HAAR_OP_KIND, f"garment_haar:Demo:{h3}:{s3}",
                            {"character": "Demo", "item_id": h3, "ssig": s3, "seeds": [1], "prompt": "short curly"})
        out = garments._haar_stages(op, resume=True)
        check("resume of an unposted stage", (out.get("stored"), len(GEN) - n_gen), ([], 0))
        hub_ops.delete(op)
        check("resume kind registered", hub_ops.get_kind(garments.HAAR_OP_KIND) is not None, True)

        # --- [10] ----------------------------------------------------------------
        print("[10] refit sweep on a HAAR fit-version bump")
        garment_haar.HAAR_FIT_VERSION = 3
        listed = sorted((i, m) for i, _k, _f, m in garment_refit.outdated_fits("Demo"))
        check("outdated", listed, sorted([(hid, "haar"), (h2, "haar")]))
        before = counts()
        done = garment_refit.refit_character("Demo")
        check("refitted", sorted(done or []), sorted([hid, h2]))
        check("no generate, fits +9", (counts()[0] - before[0], counts()[1] - before[1]), (0, 9))
        for item, seed in ((hid, 4), (h2, 2)):
            hit = gs.accepted_fit("Demo", item, base_model_sha=base_sha)
            check(f"{item} refitted", (hit[1].get("fit_version"), hit[1]["inputs"]["seed"]) if hit else None,
                  (3, seed))
        check("nothing outdated", garment_refit.outdated_fits("Demo"), [])

        # --- [11] ----------------------------------------------------------------
        print("[11] outbound connections")
        check("outbound", OUTBOUND, [])

    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)" + (f": {FAILS}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
