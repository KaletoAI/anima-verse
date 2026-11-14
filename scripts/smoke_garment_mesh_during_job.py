#!/usr/bin/env python3
"""Ruling A58: while a mesh job of a piece runs, another kept mesh of the piece can be chosen ("Use this") and
fitted, and a Re-fit runs at once on any body — CPU only, no hub job; the job's result then stays a kept mesh with
the ``chosen_during_job`` marker. Without a pick during the run the result is applied as before.
(app/core/garment_mesh.py ``generate`` / ``_publish`` / ``use_kept`` / ``running_job`` / ``mesh_lock``;
app/core/garments.py ``use_mesh`` / ``_during_mesh_ok_locked`` / ``_fit_during_mesh`` / ``_mesh_info``; the route
``POST /characters/{c}/garments/{item}/mesh/attempts/{n}/use`` in app/routes/characters.py.)

Usage:
    ./.venv/bin/python scripts/smoke_garment_mesh_during_job.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server process; ``requests`` is patched to raise, and the count of outbound calls is checked
(0). The garment queue, worker thread, run locks, the mesh step and the publish are REAL. Stubs: the image
service's ``generate_mesh`` (a stub mesh backend: writes a box GLB to ``output_path``; each call waits on its own
event — "the job is held"), ``refine.decimate_to`` (copies the raw mesh, triangle count of the file),
``base_body.current_base``, ``garments._refresh_description`` / ``_base_view_shas`` / ``_regate_accepted``
(nothing to re-render), ``garments._fit_locked`` (records the fsig and the SHA-256 of the prepared mesh it fits),
``garments.refit_on_body`` (records the body), ``base_body.after_mesh_item_ready``,
``garment_footwear.stored_outfit_bodies`` (one stored body shape ``ob0000aaaa``).

Meshes (``box(n)``: the six faces of the cube [-1, 1]³, each an n × n quad grid, two triangles per quad ->
12 n² triangles, one welded component -> largest component share 1.0, the gate passes):
    M0 = box 2 (48 tris)   the mesh in use (V neckline closed)       raw R0 = M0 + b"R0"
    K1 = box 3 (108 tris)  kept slot 1, origin "previous" (open V)    raw = K1 + b"K1"
    J  = box 4 (192 tris)  the first job's result
    J2 = box 5 (300 tris)  the second job's result
    J3 = box 6 (432 tris)  the old-code proof's job result

[1] Job held: ``start_garment(mesh, force, only)`` -> started; the stub backend is in its first call. ``running_job``
    -> fsig F, hub_jobs 1, max_hub_jobs 2 (``MAX_ATTEMPTS``), phase "hub". The panel's ``steps.mesh.job`` names the
    same id, hub_jobs 1, chosen False; ``view.attempts`` = [slot 1, origin previous, ok, use_block ""]. The status
    running_step is "mesh". The raw file of the mesh in use is still R0 (the generator writes a staging file).
[2] "Use this" on slot 1 through the route while held -> 200, during_job True, user_accepted False, the fit's start
    answer beside True (it runs beside its own run's mesh job). The fit runs once (``wait_beside``): fsig F, the
    SHA-256 of K1. Afterwards prepared = K1, raw = K1's raw, slot 1 = M0 (+ R0) with origin "previous", the
    record's ``chosen_during_job`` = {job: the running job's id, n: 1}; the run status is still "mesh".
[3] Re-fit while held: plain -> {started True, beside True}, fit call 2 (K1 again); on body ``ob0000aaaa`` ->
    beside True; the plain body's fit is not accepted (the recorder writes no fit) -> fit call 3, then
    ``refit_on_body`` once with ``ob0000aaaa``. Still held: running_job present, status "mesh".
[4] Release: the run ends ok with ``not_applied`` True. prepared is still K1 (the pick stays); ``kept`` = slot 1
    M0 (previous) + slot 2 = J (origin "job", ok True, chosen_during_job True, tris_prepared 192, its files kept);
    the panel shows slot 2 with chosen_during_job True and use_block ""; running_job None; status idle, no
    failure. The stub backend was called once (the first attempt passed the gate).
[5] No pick during the run: a second forced run, held, raw still K1's during the hold, released -> applied:
    prepared = J2, no ``chosen_during_job`` in the record, the mesh it replaced (K1) kept in slot 3 (the lowest
    free slot) with origin "previous"; slots 1 and 2 unchanged. Backend calls 2.
[6] "Use this" on a slot without a kept mesh (5) -> 409; slot 7 -> 400; another step holding the run lock and no
    mesh job -> ``UseBusy``.
[7] Fails on the old code (``aaf2fc349957b92e6186161becbf6f125cb8174f``, the HEAD this ruling starts from):
    a. the old ``garments._beside_ok_locked`` with the item's own run in flight -> False (a Re-fit queues behind
       the hub job); the new ``_during_mesh_ok_locked`` in the same state with a mesh job -> True.
    b. the old ``garment_mesh.generate(force)`` held at the hub: the kept slots 1..3 are gone (old: every kept
       file dropped at the run's start — nothing left to choose during the job); a choice made during the hold
       (prepared swapped to J, as ``use_kept`` does) is overwritten by the old publish: prepared = J3, not J. The
       new code keeps the slots and the pick ([1], [2], [4]).
[8] 0 outbound requests.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The HEAD Ruling A58 starts from (the "fails on the old code" proof).
OLD_COMMIT = "aaf2fc349957b92e6186161becbf6f125cb8174f"

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def box(n):
    """The six faces of the cube [-1, 1]³, each an n × n quad grid (two triangles per quad), unwelded."""
    import numpy as np
    P, F = [], []
    for axis in range(3):
        u, v = [a for a in range(3) if a != axis]
        for side in (-1.0, 1.0):
            base = sum(len(p) for p in P)
            g = np.linspace(-1, 1, n + 1)
            pts = np.zeros(((n + 1) ** 2, 3))
            uu, vv = np.meshgrid(g, g, indexing="ij")
            pts[:, axis] = side
            pts[:, u] = uu.ravel()
            pts[:, v] = vv.ravel()
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1) + base
            a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
            F.append(np.stack([a, b, c], -1).reshape(-1, 3))
            F.append(np.stack([a, c, d], -1).reshape(-1, 3))
            P.append(pts)
    from app.core.glb_mesh import static_glb
    pos = np.concatenate(P)
    return static_glb(pos, np.concatenate(F), np.zeros((len(pos), 2)))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    outbound = []
    import requests

    def no_net(*args, **kwargs):
        outbound.append(args[1] if len(args) > 1 else kwargs.get("url"))
        raise AssertionError("outbound request in a smoke")
    requests.Session.request = no_net
    requests.request = no_net

    with tempfile.TemporaryDirectory(prefix="garment-mesh-during-job-") as tmp:
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

        from app.blender import refine
        from app.core import (base_body, garment_assembly, garment_footwear, garment_mesh, garments, model_refs,
                              sessions, users)
        from app.core import garment_store as gs
        from app.core.glb_mesh import static_arrays
        from app.imagegen import service as image_service
        from app.models import inventory
        from app.models.character import save_character_profile

        meshes = {name: box(n) for name, n in (("M0", 2), ("K1", 3), ("J", 4), ("J2", 5), ("J3", 6))}
        check("triangles M0 K1 J J2 J3", [len(static_arrays(meshes[k])[1]) for k in ("M0", "K1", "J", "J2", "J3")],
              [48, 108, 192, 300, 432])

        # --- stubs -------------------------------------------------------------------------------------------
        garment_assembly.schedule = lambda name, signature=None: True
        model_refs.schedule_outfit_render = lambda *a, **k: None
        calls = []
        events = {}       # call number -> threading.Event (release)
        in_hub = {}       # call number -> threading.Event (the call waits)
        results = {1: "J", 2: "J2", 3: "J3"}

        class StubMeshService:
            def generate_mesh(self, source_image_path, output_path, **kwargs):
                calls.append(kwargs.get("occasion"))
                n = len(calls)
                in_hub.setdefault(n, threading.Event()).set()
                events.setdefault(n, threading.Event()).wait(30)
                Path(output_path).write_bytes(meshes[results[n]])
                return {"ok": True, "path": output_path, "backend": "stub-mesh", "routing": {}}

        image_service.get_image_service = lambda: StubMeshService()

        def fake_decimate(src, target, out, merge_vertices=False):
            data = Path(src).read_bytes()
            Path(out).write_bytes(data)
            tris = len(static_arrays(data)[1])
            return {"ok": True, "tris_before": tris, "tris": tris, "ratio": 1.0}
        refine.decimate_to = fake_decimate

        fits = []
        fit_seen = threading.Event()

        def fake_fit(character_name, item_id, kind, fsig, bsig, profile):
            prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
            fits.append((fsig, sha(prepared.read_bytes())))
            fit_seen.set()
            return prepared
        garments._fit_locked = fake_fit
        bodies = []

        def fake_refit_on_body(character_name, item_id, body_id, *, profile=None):
            bodies.append(body_id)
            return {"ok": True, "body": body_id, "fsig": "", "error": ""}
        garments.refit_on_body = fake_refit_on_body
        garments._refresh_description = lambda *a, **k: None
        garments._base_view_shas = lambda *a, **k: {}
        garments._regate_accepted = lambda *a, **k: None
        base_body.after_mesh_item_ready = lambda *a, **k: None
        garment_footwear.stored_outfit_bodies = lambda name: ["ob0000aaaa"]

        # --- fixture -----------------------------------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        op = {"slots": ["top"], "outfit_types": ["casual"], "mesh_mode": "own_mesh", "covers": []}
        dress = inventory.add_item(name="Blazer", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a plain blazer", outfit_piece=op)["id"]
        check("give", inventory.add_to_inventory("Demo", dress), True)
        check("equip", inventory.equip_piece("Demo", dress, source="smoke")["status"], "ok")
        bsig = base_body.base_signature("Demo")
        base_body.current_base = lambda name, profile=None: (bsig, "body-sha")
        F = gs.garment_fsig("Demo", dress)
        for view in gs.GARMENT_VIEWS:
            cut = gs.garment_path("Demo", dress, F, "image", step="cutout", view=view)
            cut.parent.mkdir(parents=True, exist_ok=True)
            cut.write_bytes(b"\x89PNG-cutout-" + view.encode())
        prepared = gs.garment_path("Demo", dress, F, "prepared")
        raw = gs.garment_path("Demo", dress, F, "raw")
        record_path = prepared.with_suffix(".json")
        prepared.parent.mkdir(parents=True, exist_ok=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_bytes(meshes["M0"])
        raw.write_bytes(meshes["M0"] + b"R0")
        k1 = root / "k1.glb"
        k1.write_bytes(meshes["K1"])
        k1_raw = root / "k1_raw.glb"
        k1_raw.write_bytes(meshes["K1"] + b"K1")
        garment_mesh.keep_attempt("Demo", dress, F, 1, k1, k1_raw)
        gs.write_record(record_path, {
            "accepted": True, "kind": "clothing", "item_id": dress, "fsig": F, "tris_raw": 48, "tris_prepared": 48,
            "ratio": 1.0, "backend": "stub-mesh", "routing": {}, "largest_component_share": 1.0,
            "gate_version": garment_mesh.GATE_VERSION, "created_at": "2026-11-14T19:45:00+00:00",
            "attempts": [{"attempt": 1, "ok": True, "reasons": []}],
            "kept": [{"n": 1, "origin": "previous", "ok": True, "reasons": [], "tris_raw": 108,
                      "tris_prepared": 108, "largest_component_share": 1.0, "backend": "stub-mesh",
                      "created_at": "2026-11-14T15:50:00+00:00"}]})

        tokens = {}
        for role in (users.ROLE_ADMIN,):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role, allowed_characters=["Demo"])
            tokens[role] = sessions.create_session(uid)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)

        def wait_beside():
            return wait_for(lambda: not garments.queue_state("Demo", dress)["queue_beside"])

        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            print("[1] the mesh job, held at the stub backend")
            answer = garments.start_garment("Demo", dress, steps="mesh", force=True, only=True)
            check("started", (answer.get("started"), answer.get("queued")), (True, False))
            check("in the hub call", in_hub.setdefault(1, threading.Event()).wait(20), True)
            job = garment_mesh.running_job("Demo", dress) or {}
            check("running job", (job.get("fsig"), job.get("hub_jobs"), job.get("max_hub_jobs"), job.get("phase")),
                  (F, 1, 2, "hub"))
            panel = client.get(f"/characters/Demo/garments/{dress}").json()
            mesh = ((panel.get("garment") or {}).get("steps") or {}).get("mesh") or {}
            check("panel job", ((mesh.get("job") or {}).get("id"), (mesh.get("job") or {}).get("hub_jobs"),
                                (mesh.get("job") or {}).get("chosen")), (job.get("id"), 1, False))
            tiles = (mesh.get("view") or {}).get("attempts") or []
            check("panel tiles", [(a.get("attempt"), a.get("origin"), a.get("ok"), a.get("use_block"))
                                  for a in tiles], [(1, "previous", True, "")])
            check("status mesh", gs.status("Demo", dress)["running_step"], "mesh")
            check("raw in use intact during the job", raw.read_bytes() == meshes["M0"] + b"R0", True)

            print("[2] Use this on slot 1 while the job is held")
            r = client.post(f"/characters/Demo/garments/{dress}/mesh/attempts/1/use")
            body = r.json() if r.status_code == 200 else {"detail": r.text}
            check("use 200", (r.status_code, body.get("during_job"), body.get("user_accepted"),
                              (body.get("fit") or {}).get("beside")), (200, True, False, True))
            check("fit ran", fit_seen.wait(20) and wait_beside(), True)
            check("fit of the chosen mesh", fits, [(F, sha(meshes["K1"]))])
            check("prepared = K1", prepared.read_bytes() == meshes["K1"], True)
            check("raw = K1's raw", raw.read_bytes() == meshes["K1"] + b"K1", True)
            slot1 = garment_mesh.attempt_files("Demo", dress, F, 1)
            check("slot 1 = M0", (slot1["prepared"].read_bytes() == meshes["M0"],
                                  slot1["raw"].read_bytes() == meshes["M0"] + b"R0"), (True, True))
            rec = gs.read_record(record_path)
            check("slot 1 entry", [(e.get("n"), e.get("origin"), e.get("ok"), e.get("tris_prepared"))
                                   for e in rec.get("kept") or []], [(1, "previous", True, 48)])
            check("chosen_during_job", ((rec.get("chosen_during_job") or {}).get("job"),
                                        (rec.get("chosen_during_job") or {}).get("n")), (job.get("id"), 1))
            check("status still mesh", gs.status("Demo", dress)["running_step"], "mesh")

            print("[3] Re-fit while the job is held: plain body and a body shape")
            fit_seen.clear()
            a = garments.start_garment("Demo", dress, steps="fit", force=True, only=True)
            check("plain re-fit beside", (a.get("started"), a.get("beside")), (True, True))
            check("plain fit ran", fit_seen.wait(20) and wait_beside(), True)
            check("fit call 2", fits[1:], [(F, sha(meshes["K1"]))])
            fit_seen.clear()
            a = garments.start_garment("Demo", dress, steps="fit", force=True, only=True, body="ob0000aaaa")
            check("body re-fit beside", (a.get("started"), a.get("beside")), (True, True))
            check("body fit ran", wait_for(lambda: bodies == ["ob0000aaaa"]) and wait_beside(), True)
            check("plain fit first (not accepted)", len(fits), 3)
            check("still held", (garment_mesh.running_job("Demo", dress) or {}).get("id"), job.get("id"))
            check("status still mesh after the re-fits", gs.status("Demo", dress)["running_step"], "mesh")

            print("[4] release: the result stays a kept mesh")
            events.setdefault(1, threading.Event()).set()
            check("idle", garments.wait_idle(30), True)
            check("prepared still K1", prepared.read_bytes() == meshes["K1"], True)
            rec = gs.read_record(record_path)
            kept = {e["n"]: e for e in rec.get("kept") or []}
            check("kept", sorted((n, e.get("origin")) for n, e in kept.items()), [(1, "previous"), (2, "job")])
            j = kept.get(2) or {}
            check("job entry", (j.get("ok"), j.get("chosen_during_job"), j.get("tris_prepared"), j.get("job")),
                  (True, True, 192, job.get("id")))
            slot2 = garment_mesh.attempt_files("Demo", dress, F, 2)
            check("slot 2 files = J", (slot2["prepared"] is not None and slot2["prepared"].read_bytes() == meshes["J"],
                                       slot2["raw"] is not None), (True, True))
            check("marker kept", (rec.get("chosen_during_job") or {}).get("job"), job.get("id"))
            panel = client.get(f"/characters/Demo/garments/{dress}").json()
            mesh = ((panel.get("garment") or {}).get("steps") or {}).get("mesh") or {}
            tiles = {a.get("attempt"): a for a in (mesh.get("view") or {}).get("attempts") or []}
            check("panel job tile", ((tiles.get(2) or {}).get("chosen_during_job"), (tiles.get(2) or {}).get("ok"),
                                     (tiles.get(2) or {}).get("use_block")), (True, True, ""))
            check("no job any more", (garment_mesh.running_job("Demo", dress), mesh.get("job")), (None, None))
            st = gs.status("Demo", dress)
            check("status idle", (st["running_step"], st["failed"]), (None, None))
            check("backend calls", len(calls), 1)

            print("[5] no pick during the run: the result is applied")
            answer = garments.start_garment("Demo", dress, steps="mesh", force=True, only=True)
            check("second run started", answer.get("started"), True)
            check("second call waits", in_hub.setdefault(2, threading.Event()).wait(20), True)
            check("raw in use intact during the second job", raw.read_bytes() == meshes["K1"] + b"K1", True)
            events.setdefault(2, threading.Event()).set()
            check("idle again", garments.wait_idle(30), True)
            check("prepared = J2", prepared.read_bytes() == meshes["J2"], True)
            rec = gs.read_record(record_path)
            kept = {e["n"]: e for e in rec.get("kept") or []}
            check("no marker", "chosen_during_job" in rec, False)
            check("kept after apply", sorted((n, e.get("origin"), e.get("tris_prepared")) for n, e in kept.items()),
                  [(1, "previous", 48), (2, "job", 192), (3, "previous", 108)])
            slot3 = garment_mesh.attempt_files("Demo", dress, F, 3)
            check("slot 3 = K1", slot3["prepared"] is not None and slot3["prepared"].read_bytes() == meshes["K1"],
                  True)
            check("record numbers = J2", (rec.get("accepted"), rec.get("tris_prepared")), (True, 300))
            check("backend calls", len(calls), 2)

            print("[6] refusals")
            check("empty slot 409", client.post(f"/characters/Demo/garments/{dress}/mesh/attempts/5/use").status_code,
                  409)
            check("slot 7 400", client.post(f"/characters/Demo/garments/{dress}/mesh/attempts/7/use").status_code,
                  400)
            lock = gs.run_item_lock("Demo", dress)
            lock.acquire()
            try:
                try:
                    garments.use_mesh("Demo", dress, 1)
                    busy = None
                except garments.UseBusy as e:
                    busy = str(e)
                check("another step holds the run lock", busy, garments.MESH_USE_BUSY)
            finally:
                lock.release()

        print(f"[7] fails on the old code ({OLD_COMMIT})")

        def old_module(rel, name):
            src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:{rel}"], capture_output=True,
                                 text=True)
            if src.returncode != 0:
                check(f"old {rel} readable", src.stderr.strip(), "")
                return None
            path = root / f"{name}.py"
            path.write_text(src.stdout)
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        old_garments = old_module("app/core/garments.py", "old_garments")
        if old_garments is not None:
            old_garments._active.add("Demo")
            old_garments._current["Demo"] = old_garments._Job(dress, "mesh", None, True)
            check("old: a Re-fit during the item's own run may not start beside",
                  old_garments._beside_ok_locked("Demo", dress), False)
            job_id = garment_mesh._begin_job("Demo", dress, F)
            with garments._lock:
                garments._active.add("Demo")
                garments._current["Demo"] = garments._Job(dress, "mesh", None, True)
                try:
                    check("new: it may (the run is in its mesh job)", garments._during_mesh_ok_locked("Demo", dress),
                          True)
                finally:
                    garments._current.pop("Demo", None)
                    garments._active.discard("Demo")
            garment_mesh._end_job("Demo", dress, job_id)
        old_mesh = old_module("app/core/garment_mesh.py", "old_garment_mesh")
        if old_mesh is not None:
            out = {}
            worker = threading.Thread(target=lambda: out.setdefault(
                "path", old_mesh.generate("Demo", dress, F, force=True)), daemon=True)
            worker.start()
            check("old job held", in_hub.setdefault(3, threading.Event()).wait(20), True)
            check("old: the kept meshes survive the run's start",
                  [garment_mesh.attempt_files("Demo", dress, F, n)["prepared"] is not None for n in (1, 2, 3)],
                  [False, False, False])
            # The old code has no pick: the user's choice during the job is the file swap the new ``use_kept`` does.
            prepared.write_bytes(meshes["J"])
            events.setdefault(3, threading.Event()).set()
            worker.join(30)
            check("old: the pick survives the job", prepared.read_bytes() == meshes["J"], False)
            check("old: the job's result replaced it", prepared.read_bytes() == meshes["J3"], True)

        print("[8] no outbound requests")
        check("outbound", outbound, [])

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
