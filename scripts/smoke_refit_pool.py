#!/usr/bin/env python3
"""CPU refits on a process pool across characters, tracked in the header (spec
docs/superpowers/specs/2026-11-12-parallel-cpu-refits-design.md; app/core/refit_pool.py, garment_refit.sweep).

Usage:
    ./.venv/bin/python scripts/smoke_refit_pool.py

Runs against a THROWAWAY storage + instance directory — no real world, no hub, no GPU, no Blender, no server
process. The instance config sets ``server.refit_workers`` = 2. Spawned worker processes import THIS file as
``__mp_main__``: everything with a side effect sits in ``main()``; the module level holds only the worker-side
stand-ins below.

Server side (the parent process) is stubbed like smoke_garment_refit_sweep: ``base_body.current_base`` = (BSIG,
sha(RIGGED)), ``_snapshot_base_model`` = {rigged: RIGGED}, profiles {}, ``garment_store.garment_fsig`` /
``garment_method`` (hairdeck) / ``garment_hsig`` from a table, ``garments._stored_seeds`` = [1],
``_hairdeck_files`` non-None, ``garments._kind_inputs`` = {description: item}, the hair colour / length readers
fixed, ``garment_source.backfill`` 0, the posture listers empty, ``refine.decimate_to`` copies (the low tier),
``garment_assembly.schedule`` records, ``timeutils.utc_now_iso`` fixed. REAL: the sweep and its scheduling, the
refit pool, ``garments._refit_hairdeck`` / ``_fit_seed`` / ``_publish_hairdeck`` / ``_publish_fit``, the graft
(``refit_pool.graft_file`` → ``glb_mesh.graft`` onto RIGGED, a skinned cylinder R 0.100, y 0.60..1.60, Spine2) and
the task queue. The HairDeck fit itself is ``hair_fit`` below (worker side, picklable): it reads its mode from the
seed's hair bytes ``HAIR|<character>|<item>|<mode>`` and returns a passing ``FitResult`` whose garment is an open
tube r = 0.110 + 0.001 · (item number), y 1.00..1.40 (Spine2) — ``timed``: sleeps 0.8 s and names its pid and
start/end (time.time) in ``report.smoke``; ``raise``: ValueError("smoke refusal"); ``crash``: ``os._exit(3)``
after 0.2 s; ``det``: no sleep, no pid (byte-identical across processes).

Fixture per character X, items ``hair_<x>_<n>``: fit record accepted, kind hair, method hairdeck, fit_version 1
(< FIT_VERSION hair 13: outdated), base_model_sha256 sha(RIGGED), inputs {seed 1, hsig H}; the old fit GLB b"OLD";
hairdeck_dir(X, item, H)/hair_seed1_nohead.glb = the hair bytes, hair_seed1.glb = b"PROXY".

Expected, derived by hand from the spec:

[0] Setting: configured_workers() = 2 (the instance layer's server.refit_workers); with the key 0 →
    auto_workers() = max(1, min(8, os.cpu_count() − 2)); scope_of("server.refit_workers") = "instance".
    Pool off (not enabled) → workers() = 1.
[1] Worker isolation (pool on, 2 workers): ``probe_sqlite`` in a worker → WorkerDatabaseAccess raised here (the
    initializer's guard); ``probe_modules`` after importing every compute module (garment_fit, garment_hairdeck,
    garment_footwear, garment_layers, glb_mesh, footwear_fit, footwear_cut, footwear_rest, garment_fit_layers,
    refit_pool) → none of app.server, app.core.db, app.core.config, app.core.task_queue, app.models.* loaded, the
    storage root NOT initialised (StorageNotInitialised), its pid != this pid.
[2] Byte-identity: Ann (items 1, 2, mode det). Refit in-process (pool off) → files F1 = every fit GLB / record /
    low tier / hairdeck record.json under garments/; Ann's garments restored; refit with the pool on → F2 = F1
    byte for byte (same names, same bytes), and the pool exists (the compute did run in workers). Real compute
    too: ``garment_layers._layer_compute`` (layering of smoke_garment_layering: coat r 0.1080 y 0.80..1.40 over
    slip r 0.1125 y 1.00..1.40, real SDF + push + graft) in-process vs in a worker → both output files and the
    report JSON identical.
[3] Overlap, order, tracking (pool on, 2 workers): Bea, Cat (2 items each), Dan (1 item), all ``timed``; Eli
    with no work. sweep([Bea, Cat, Dan, Eli], pause 0) →
    {Bea: [hair_bea_1, hair_bea_2], Cat: [...1, ...2], Dan: [hair_dan_1]}. Per fit record report.smoke:
    pid != this pid; within Bea: fit 1 ends before fit 2 starts (t1 ≤ t0'), same for Cat; Bea's fit 1 and Cat's
    fit 1 overlap (max of starts < min of ends) — two characters at once. Tracked rows (task_type cpu_refit):
    exactly Bea, Cat, Dan (Eli has no work → none), labels "Refit · Bea (2 fits)", "Refit · Cat (2 fits)",
    "Refit · Dan (1 fit)", provider CPU; Dan (3rd with 2 slots) observed pending → running → completed;
    every row completed at the end; /queue/status (the route) listed rows with provider CPU while they ran, at
    least one running AND one pending at the same poll; active_tasks empty afterwards. Records fit_version 13.
[4] Failure: Fay (mode raise) and Gus (timed) in one sweep → Fay's fit refused (old fit kept, its failure
    recorded with "smoke refusal"), Gus's accepted. Hal (mode crash) and Ida (timed, in flight while Hal's worker
    dies) → Ida accepted (its call ran once more on its own), Hal refused with "crashed"; afterwards a probe
    runs on a NEW pool (refit_pool._pool is not the broken one) and returns a pid.
[5] workers = 1 (pool off): Jon (1 item, timed) → refitted, report.smoke.pid == this pid, refit_pool._pool None,
    the tracked row "Refit · Jon (1 fit)" completed — in-process, today's behaviour, still visible.
    garment_refit.tracked: a run returning None leaves no row; one returning [x] a completed row.

"Fails on the old code": against 0a6a2f2a (the commit this work started from) app/core/refit_pool.py does not
exist, and garments.py / garment_footwear.py / garment_layers.py call their compute (fit_clothing, fit_hairdeck,
fit_pair, layer_over) directly, never through ``refit_pool.run`` — [6] checks the seam on both trees.
"""
import os
import sys
import time

BASELINE = "0a6a2f2a"


# --- worker side (picklable, no side effects at import) --------------------------------------------------------

def _tube(radius, y0, y1, nseg=48):
    import math
    import numpy as np
    from app.core.glb_mesh import GarmentMesh
    nrings = int(round((y1 - y0) / 0.02)) + 1
    ys = np.linspace(y0, y1, nrings)
    cols = nseg + 1
    P, U = [], []
    for i, y in enumerate(ys):
        for j in range(cols):
            a = (j % nseg) * 2 * math.pi / nseg
            P.append((radius * math.cos(a), y, radius * math.sin(a)))
            U.append((j / nseg, i / max(nrings - 1, 1)))
    F = []
    for i in range(nrings - 1):
        for j in range(nseg):
            a, b = i * cols + j, i * cols + j + 1
            c, d = (i + 1) * cols + j + 1, (i + 1) * cols + j
            F += [(a, c, b), (a, d, c)]
    n = len(P)
    P = np.array(P, float)
    radial = P * np.array([1.0, 0.0, 1.0])
    N = radial / np.linalg.norm(radial, axis=1, keepdims=True)
    J = np.zeros((n, 4), np.int64)
    W = np.zeros((n, 4))
    W[:, 0] = 1.0
    return GarmentMesh(positions=P, normals=N, uvs=np.array(U, float), indices=np.array(F, np.int64), joints=J,
                       weights=W, joint_names=["mixamorig:Spine2"], image=_png(), mime="image/png",
                       material={"name": "hair"})


def _png():
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (4, 4), (90, 60, 30)).save(out, "PNG")
    return out.getvalue()


def hair_fit(hair_bytes, proxy_bytes, rigged, *, colour_target=None, colour_profile=None, length_class=None,
             forward_m=None, tilt_deg=None, swing=False):
    """Stand-in for garment_hairdeck.fit_hairdeck (module docstring)."""
    from app.core.garment_fit import FitResult
    _tag, _char, item, mode = hair_bytes.decode().split("|")
    t0 = time.time()
    if mode == "raise":
        raise ValueError("smoke refusal")
    if mode == "crash":
        time.sleep(0.2)
        os._exit(3)
    if mode == "timed":
        time.sleep(0.8)
    garment = _tube(0.110 + 0.001 * int(item.rsplit("_", 1)[1]), 1.00, 1.40)
    report = {"placement": {}, "colour": {}}
    if mode == "timed":
        report["smoke"] = {"pid": os.getpid(), "t0": t0, "t1": time.time()}
    return FitResult(garment=garment, metrics={"tris": len(garment.indices) // 3, "max_push_m": 0.001}, ok=True,
                     reasons=[], report=report)


def probe_sqlite():
    import sqlite3
    sqlite3.connect(":memory:")
    return "opened"


def probe_modules():
    import importlib
    for name in ("garment_fit", "garment_hairdeck", "garment_footwear", "garment_layers", "glb_mesh",
                 "footwear_fit", "footwear_cut", "footwear_rest", "garment_fit_layers", "refit_pool"):
        importlib.import_module(f"app.core.{name}")
    loaded = sorted(m for m in sys.modules if m == "app.server" or m.startswith("app.models")
                    or m in ("app.core.db", "app.core.config", "app.core.task_queue"))
    from app.core import paths
    try:
        paths.get_storage_dir()
        storage = "initialised"
    except Exception as e:  # noqa: BLE001
        storage = type(e).__name__
    return {"pid": os.getpid(), "loaded": loaded, "storage": storage}


def probe_pid():
    return os.getpid()


# --- the smoke ---------------------------------------------------------------------------------------------------

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    import hashlib
    import json
    import shutil
    import subprocess
    import tempfile
    import threading
    from pathlib import Path
    root_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root_dir))
    sys.path.insert(0, str(root_dir / "scripts"))

    with tempfile.TemporaryDirectory(prefix="refit-pool-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        (root / "instance" / "config.json").write_text(json.dumps({"server": {"refit_workers": 2}}))
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()

        import numpy as np
        import smoke_garment_chain as chain
        import smoke_garment_fit as fx
        from app.blender import refine
        from app.core import (base_body, config_scope, garment_assembly, garment_fit, garment_hair, garment_layers,
                              garment_refit, garment_source, garments, glb_mesh, outfit_bodies, refit_pool, timeutils)
        from app.core import garment_store as gs
        from app.core.rig_contract import BASE_JOINT_NAMES
        from app.core.task_queue import get_task_queue
        from app.models import character as charmod

        # --- RIGGED: the skinned cylinder -----------------------------------------------------------------------
        P, F = fx.cylinder(0.100, 0.60, 1.60, nseg=48, nrings=26)
        n = len(P)
        U = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
        J = np.zeros((n, 4), np.int64)
        J[:, 0] = list(BASE_JOINT_NAMES).index("Spine2")
        Wt = np.zeros((n, 4))
        Wt[:, 0] = 1.0
        RIGGED = chain.rigged_glb(P, F, U, J, Wt, _png())
        SHA = hashlib.sha256(RIGGED).hexdigest()
        BSIG, H = "base0000a11c", "1" * 12

        # --- server-side stubs ----------------------------------------------------------------------------------
        base_body.current_base = lambda name, profile=None: (BSIG, SHA)
        base_body._snapshot_base_model = lambda name, bsig: {"rigged": RIGGED}
        charmod.get_character_profile = lambda name: {}
        FSIG = {}
        gs.garment_fsig = lambda name, item_id, profile=None: FSIG[item_id]
        gs.garment_method = lambda name, item_id, profile=None: gs.HAIRDECK
        gs.garment_hsig = lambda name, item_id, profile=None: H
        garments._stored_seeds = lambda name, item_id, hsig: [1]
        garments._hairdeck_files = lambda name, item_id, hsig: (Path("hair"), Path("proxy"))
        garments._kind_inputs = lambda kind, name, profile, item_id: {"description": item_id}
        garment_hair.hair_length_class = lambda name, profile=None, text=None: "short"
        garment_hair.profile_hair_colour = lambda name, profile=None, text=None: None
        garment_source.backfill = lambda name: 0
        outfit_bodies.match_stale_postures = lambda name: []
        outfit_bodies.stale_posture_bodies = lambda name, profile=None: []
        timeutils.utc_now_iso = lambda: "2026-11-12T00:00:00+00:00"
        refine.lod_ratio = lambda kind: 0.5
        SCHEDULED = []
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append(name) or True

        def decimate(src, target, out, **_kw):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(src).read_bytes())
            return {"ok": True, "tris": target, "ratio": 0.5}
        refine.decimate_to = decimate
        import app.core.garment_hairdeck as ghd
        ghd.fit_hairdeck = hair_fit

        def put(name, count, mode):
            charmod.get_character_dir(name, create=True)
            gs._root(name).mkdir(parents=True, exist_ok=True)
            items = []
            for k in range(1, count + 1):
                item = f"hair_{name.lower()}_{k}"
                fsig = hashlib.md5(item.encode()).hexdigest()[:12]
                FSIG[item] = fsig
                fit = gs.garment_path(name, item, fsig, "fit")
                fit.write_bytes(b"OLD")
                gs.write_record(fit.with_suffix(".json"), {
                    "accepted": True, "kind": "hair", "method": gs.HAIRDECK, "item_id": item, "fsig": fsig,
                    "base_signature": BSIG, "base_model_sha256": SHA, "fit_version": 1,
                    "inputs": {"seed": 1, "hsig": H}})
                folder = gs.hairdeck_dir(name, item, H)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "hair_seed1_nohead.glb").write_bytes(f"HAIR|{name}|{item}|{mode}".encode())
                (folder / "hair_seed1.glb").write_bytes(b"PROXY")
                items.append(item)
            return items

        def record(name, item):
            return gs.read_record(gs.garment_path(name, item, FSIG[item], "fit").with_suffix(".json"))

        def files(name):
            base = gs._root(name)
            return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*"))
                    if p.is_file() and not p.name.startswith(".") and "status" not in p.name}

        tq = get_task_queue()

        def rows(name=None):
            with tq._connect() as conn:
                out = [dict(r) for r in conn.execute(
                    "SELECT task_id, task_type, status, label, provider, agent_name FROM tasks "
                    "WHERE task_type=? ORDER BY created_at", (refit_pool.TASK_TYPE,)).fetchall()]
            return [r for r in out if name is None or r["agent_name"] == name]

        # --- [0] the setting ---------------------------------------------------------------------------------
        print("[0] server.refit_workers")
        check("configured (instance layer)", refit_pool.configured_workers(), 2)
        check("scope", config_scope.scope_of("server.refit_workers"), "instance")
        check("pool off -> 1", refit_pool.workers(), 1)
        saved = config._CONFIG["server"]["refit_workers"]
        config._CONFIG["server"]["refit_workers"] = 0
        check("0 = auto", refit_pool.configured_workers(), max(1, min(8, (os.cpu_count() or 1) - 2)))
        config._CONFIG["server"]["refit_workers"] = saved
        refit_pool.enable()
        check("pool on -> 2", refit_pool.workers(), 2)

        # --- [1] isolation ------------------------------------------------------------------------------------
        print("[1] a worker never opens a database")
        try:
            got = refit_pool.run(probe_sqlite)
        except refit_pool.WorkerDatabaseAccess as e:
            got = f"refused: {e}"
        check("sqlite in a worker", got.startswith("refused"), True)
        info = refit_pool.run(probe_modules)
        check("worker pid differs", info["pid"] != os.getpid(), True)
        check("no server / db / models / config in the worker", info["loaded"], [])
        check("no storage root in the worker", info["storage"], "StorageNotInitialised")

        # --- [2] byte-identity --------------------------------------------------------------------------------
        print("[2] pool and in-process publish the same bytes")
        put("Ann", 2, "det")
        snapshot = root / "ann-before"
        shutil.copytree(gs._root("Ann"), snapshot)
        refit_pool.enable(False)
        check("in-process refit", garment_refit.refit_character("Ann"), ["hair_ann_1", "hair_ann_2"])
        f1 = files("Ann")
        shutil.rmtree(gs._root("Ann"))
        shutil.copytree(snapshot, gs._root("Ann"))
        refit_pool.enable()
        check("pool refit", garment_refit.refit_character("Ann"), ["hair_ann_1", "hair_ann_2"])
        f2 = files("Ann")
        check("pool used", refit_pool._pool is not None, True)
        check("same files", sorted(f2), sorted(f1))
        check("same bytes", [k for k in f1 if f1[k] != f2.get(k)], [])
        check("fit_version 13", [record("Ann", i).get("fit_version") for i in ("hair_ann_1", "hair_ann_2")], [13, 13])
        check("no temp file left", [p.name for p in gs._root("Ann").rglob(".*.refit.tmp")], [])

        coat, slip = _tube(0.1080, 0.80, 1.40), _tube(0.1125, 1.00, 1.40)
        coat_fit = glb_mesh.graft(RIGGED, coat, name="garment_clothing_coat", extras={"kind": "clothing"})
        slip_fit = glb_mesh.graft(RIGGED, slip, name="garment_clothing_slip", extras={"kind": "clothing"})
        outs = []
        for on in (False, True):
            refit_pool.enable(on)
            a, b = root / f"layer-{on}.glb", root / f"layer-{on}-low.glb"
            res = refit_pool.run(garment_layers._layer_compute, RIGGED, coat_fit, None, [slip_fit], [None], None,
                                 "coat", "c" * 12, ["slip"], str(a), str(b))
            outs.append((a.read_bytes(), b.is_file(), json.dumps(res, sort_keys=True, default=str)))
        check("layered compute: same bytes / report", outs[0] == outs[1], True)
        check("layered compute moved the coat", json.loads(outs[1][2])["report"].get("moved", 0) > 0, True)

        # --- [3] overlap, order, tracking ---------------------------------------------------------------------
        print("[3] two characters at once, one character's fits in order, tracked")
        put("Bea", 2, "timed")
        put("Cat", 2, "timed")
        put("Dan", 1, "timed")
        charmod.get_character_dir("Eli", create=True)
        seen = {}
        polls = []
        stop = threading.Event()

        def monitor():
            import asyncio
            from app.routes import queue as queue_route
            while not stop.is_set():
                for r in rows():
                    seq = seen.setdefault(r["agent_name"], [])
                    if not seq or seq[-1] != r["status"]:
                        seq.append(r["status"])
                try:
                    active = asyncio.run(queue_route.queue_status())["active_tasks"]
                    polls.append([(t.get("agent_name"), t.get("status"), t.get("provider")) for t in active
                                  if t.get("task_type") == refit_pool.TASK_TYPE])
                except Exception as e:  # noqa: BLE001
                    polls.append([("error", str(e), "")])
                time.sleep(0.05)

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        result = garment_refit.sweep(["Bea", "Cat", "Dan", "Eli"], pause=0)
        time.sleep(0.2)
        stop.set()
        watcher.join()
        check("sweep result", result, {"Bea": ["hair_bea_1", "hair_bea_2"], "Cat": ["hair_cat_1", "hair_cat_2"],
                                       "Dan": ["hair_dan_1"]})
        smoke = {i: record(n, i).get("report", {}).get("smoke") or {} for n, items in
                 (("Bea", ["hair_bea_1", "hair_bea_2"]), ("Cat", ["hair_cat_1", "hair_cat_2"]),
                  ("Dan", ["hair_dan_1"])) for i in items}
        check("computed in workers", all(s.get("pid") and s["pid"] != os.getpid() for s in smoke.values()), True)
        check("Bea in order", smoke["hair_bea_1"]["t1"] <= smoke["hair_bea_2"]["t0"], True)
        check("Cat in order", smoke["hair_cat_1"]["t1"] <= smoke["hair_cat_2"]["t0"], True)
        b1, c1 = smoke["hair_bea_1"], smoke["hair_cat_1"]
        check("Bea and Cat overlap", max(b1["t0"], c1["t0"]) < min(b1["t1"], c1["t1"]), True)
        tracked = rows()
        check("tracked rows", sorted((r["agent_name"], r["label"], r["provider"], r["status"]) for r in tracked),
              [("Bea", "Refit · Bea (2 fits)", "CPU", "completed"), ("Cat", "Refit · Cat (2 fits)", "CPU", "completed"),
               ("Dan", "Refit · Dan (1 fit)", "CPU", "completed")])
        check("Dan pending -> running -> completed", seen.get("Dan"), ["pending", "running", "completed"])
        check("/queue/status listed them with provider CPU",
              any(p and all(t[2] == "CPU" for t in p) for p in polls), True)
        check("a poll with running AND pending",
              any({"running", "pending"} <= {t[1] for t in p} for p in polls), True)
        import asyncio
        from app.routes import queue as queue_route
        check("active_tasks empty afterwards", [t for t in asyncio.run(queue_route.queue_status())["active_tasks"]
                                                if t.get("task_type") == refit_pool.TASK_TYPE], [])

        # --- [4] failure ---------------------------------------------------------------------------------------
        print("[4] a raising or crashing worker fails only its character")
        put("Fay", 1, "raise")
        put("Gus", 1, "timed")
        result = garment_refit.sweep(["Fay", "Gus"], pause=0)
        check("raise: Gus refitted, Fay not", result, {"Gus": ["hair_gus_1"]})
        check("Fay keeps the old fit", (record("Fay", "hair_fay_1").get("fit_version"),
                                        gs.garment_path("Fay", "hair_fay_1", FSIG["hair_fay_1"], "fit").read_bytes()),
              (1, b"OLD"))
        failure = gs.read_record(gs.garment_path("Fay", "hair_fay_1", FSIG["hair_fay_1"], "failed"))
        check("Fay's failure recorded", "smoke refusal" in json.dumps(failure), True)
        put("Hal", 1, "crash")
        put("Ida", 1, "timed")
        result = garment_refit.sweep(["Hal", "Ida"], pause=0)
        check("crash: Ida refitted, Hal not", result, {"Ida": ["hair_ida_1"]})
        failure = gs.read_record(gs.garment_path("Hal", "hair_hal_1", FSIG["hair_hal_1"], "failed"))
        check("Hal's failure names the crash", "crashed" in json.dumps(failure), True)
        check("pool recovered", isinstance(refit_pool.run(probe_pid), int), True)

        # --- [5] workers = 1 -----------------------------------------------------------------------------------
        print("[5] workers = 1: in-process, today's behaviour, still tracked")
        refit_pool.shutdown(wait=True)
        put("Jon", 1, "timed")
        check("sweep", garment_refit.sweep(["Jon"], pause=0), {"Jon": ["hair_jon_1"]})
        check("computed here", record("Jon", "hair_jon_1")["report"]["smoke"]["pid"], os.getpid())
        check("no pool", refit_pool._pool, None)
        check("Jon tracked", [(r["label"], r["status"]) for r in rows("Jon")], [("Refit · Jon (1 fit)", "completed")])
        before = len(rows("Ann"))
        check("tracked None", garment_refit.tracked("Ann", lambda: None), None)
        check("no row for a busy run", len(rows("Ann")), before)
        check("tracked [x]", garment_refit.tracked("Ann", lambda: ["x"]), ["x"])
        check("a completed row", [r["status"] for r in rows("Ann")][before:], ["completed"])

        # --- [6] the seam, on both trees -----------------------------------------------------------------------
        print(f"[6] compute behind refit_pool.run (fails on {BASELINE})")
        seams = {"app/core/garments.py": ["garment_fit.fit_clothing", "garment_hairdeck.fit_hairdeck"],
                 "app/core/garment_footwear.py": ["fit_compute"],
                 "app/core/garment_layers.py": ["_layer_compute"]}

        def seam_ok(read):
            if read("app/core/refit_pool.py") is None:
                return False
            return all(f"refit_pool.run({fn}" in (read(path) or "") for path, fns in seams.items() for fn in fns)

        def head(path):
            p = root_dir / path
            return p.read_text() if p.is_file() else None

        def old(path):
            try:
                return subprocess.run(["git", "show", f"{BASELINE}:{path}"], cwd=root_dir, capture_output=True,
                                      text=True, check=True).stdout
            except (OSError, subprocess.CalledProcessError):
                return None
        check("seam now", seam_ok(head), True)
        if old("app/core/garments.py") is None:
            print(f"  SKIP baseline {BASELINE} not in this checkout")
        else:
            check(f"seam at {BASELINE}", seam_ok(old), False)
        refit_pool.shutdown(wait=True)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
