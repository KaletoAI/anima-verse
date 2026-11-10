#!/usr/bin/env python3
"""Fetch a finished mesh job by its id for the garment mesh steps (garment_mesh.collect_job,
garment_subtract.collect_source_job, footwear_source.collect_mesh_job, garments.collect_mesh_job and the
routes POST /characters/{c}/garments/{item}/mesh/fetch + .../footwear/mesh/fetch).

Usage:
    ./.venv/bin/python scripts/smoke_garment_mesh_fetch.py

Throwaway storage + instance (``paths.init(<tmp>/world)`` before any world module) with a copy of the repo's
``human`` package — no real world, no hub, no server, no Blender. Stubbed: ``get_image_service()`` = a stand-in
whose ``fetch_mesh_job`` / ``_store_mesh_files`` are the REAL ``ImageService`` methods over ONE fake mesh
backend (``list_available_backends``), whose ``fetch_job`` answers from a table by job id;
``refine.decimate_to`` copies the raw GLB (tris_before = tris = the fixture's triangle count);
``garment_images._mask_image`` (subtract cut-outs) = a fully opaque mask. The route functions are called
directly (``_`` = the admin dependency's value).

Fixtures (hand-derived):
    GOOD  2 disjoint quads, areas 0.99 + 0.01 -> 4 tris, largest component share 0.99 >= 0.98 (accepted).
    BAD   areas 0.97 + 0.03 -> share 0.97 < 0.98 (refused).
    SHOE  box A 0.25 x 0.13 x 0.09 m with box B inside it (smoke_footwear_source S5): 24 tris,
          component_share 1.0 >= 0.98; cut-out alpha = one 192 x 100 rectangle (aspect 1.92 = 0.25 / 0.13)
          -> mesh_iou 1.0 +- 0.02 >= 0.80 (accepted).
    Every GLB embeds a 16 x 16 PNG base colour: ``_store_mesh_files`` validates an unrigged delivery
    (``validate_source``: an embedded texture >= 8 px), as for a real gateway result.
    Jobs: "good1" done GOOD (the gateway reports the full id "good1-full"), "bad1" done BAD, "run1" running
    at progress 0.4, "shoe1" done SHOE, "src1" done GOOD; any other id -> 404 "unknown".

[1] Hair H of Demo (edit chain, fsig F = garment_fsig). A persisted failure {step mesh} + an in-memory one
    exist before. garments.collect_mesh_job(Demo, H, "Job good1") via the route ->
    200 {status accepted, step mesh, job_id "good1-full"}; raw/H_F.glb = prepared/H_F.glb = GOOD bytes;
    record accepted True, collected_job "good1-full", 1 attempt with collected_job, tris_raw 4,
    tris_prepared 4, target_tris 25000, share 0.99 +- 1e-6, backend "FakeMesh"; the failure record is gone
    and gs.status(...).failed None; no ".fetch-*" staging left; the next run reuses the pair (R13):
    garment_mesh.generate(Demo, H, F) returns the prepared path without a generation (the stand-in has no
    generate_mesh: a call would raise AttributeError).
[2] "run1" -> 200 {status running, progress 0.4}; NOTHING written: the file list under garments/ (names,
    sizes, mtimes) is identical before and after.
[3] "zzzz9999" -> 404 (unknown); nothing written. "../x" -> 400 (no job id), fetch_job not asked.
[4] "bad1" NEXT TO the accepted mesh of [1] -> 200 {status refused, kept True, reasons naming "largest
    component"}; NOTHING written: raw, prepared and the record byte-identical, no failure record, no
    in-memory failure (a wrong pasted id must never destroy a good mesh).
[4b] The accepted pair removed (no accepted mesh) -> "bad1" is recorded like a refused step: record
    accepted False, share 0.97, collected_job "bad1", no prepared GLB, the persisted failure names "mesh".
[5] gs.char_lock(Demo) held (a mesh step running) -> 409, fetch_job not asked, nothing written.
[6] Footwear item "shoe_w" (store level, item lock): cut-out recorded as accepted under the current ssig.
    The item lock held by another thread -> SourceBusy, nothing asked. "run1" -> running, no raw/prepared.
    "shoe1" -> accepted: prepared.glb + raw.glb, record mesh {accepted True, collected_job "shoe1",
    gates.component_share 1.0, gates.mesh_iou 1.0 +- 0.02, tris_raw 24}; an earlier insole.json is dropped
    (the step and every later one, like a step run). Without a cut-out -> FileNotFoundError.
    Then an insole is recorded and "shoebad" (box B moved 0.5 m OUTSIDE A: component_share
    0.1334 / 0.1494 = 0.8929 < 0.98) -> refused, kept True; prepared.glb, raw.glb, record.json and
    insole.json byte-identical.
[7] Subtract source (store level): haired views accepted under an image fsig I, ssig S. "src1" -> accepted:
    source/H_S/haired.glb = GOOD, both cut-outs written, record accepted True, collected_job "src1",
    tris 4; garment_subtract.source_glb(...) is that file. "run1" -> running, the source folder is not
    even created.
"""
import io
import json
import math
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(float(got) - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want} ± {tol}"))
    if not ok:
        FAILS.append(label)


def png16() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (120, 90, 60)).save(buf, format="PNG")
    return buf.getvalue()


def quads_glb(areas) -> bytes:
    """Disjoint axis-aligned squares of the given areas in z=0, each its own 4 vertices, textured."""
    from app.core import glb_mesh
    P, F, U = [], [], []
    x0 = 0.0
    for area in areas:
        side = math.sqrt(area)
        base = len(P)
        for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1)):
            P.append((x0 + dx * side, dy * side, 0.0))
            U.append((float(dx), float(dy)))
        F += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        x0 += 5.0
    return glb_mesh.static_glb(P, F, U, image=png16(), mime="image/png")


def box(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (3, 6, 2), (3, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return P, F


def shoe_glb(inside=True) -> bytes:
    from app.core import glb_mesh
    pa, fa = box((0.0, 0.0, -0.045), (0.25, 0.13, 0.045))
    off = 0.0 if inside else 0.5
    pb, fb = box((0.075 + off, 0.01, -0.025), (0.175 + off, 0.03, 0.025))
    P = pa + pb
    F = fa + [(a + 8, b + 8, c + 8) for a, b, c in fb]
    return glb_mesh.static_glb(P, F, [(0.0, 0.0)] * len(P), image=png16(), mime="image/png")


class FakeMeshBackend:
    name = "FakeMesh"
    api_url = "http://gateway.invalid"
    api_key = "k"
    model = "fake-mesh"

    def __init__(self, jobs):
        self.jobs = jobs
        self.asked = []

    def fetch_job(self, job_id):
        self.asked.append(job_id)
        job = self.jobs.get(job_id)
        if job is None:
            return {"status": "unknown", "job_id": job_id, "error": f"{self.name}: the gateway does not know job {job_id}"}
        if job[0] == "running":
            return {"status": "running", "job_id": job_id, "progress": 0.4, "elapsed_s": 12.0}
        blob, full = job[1], job[2]
        return {"status": "done", "job_id": full, "progress": 1.0, "rig": "none", "model": self.model,
                "blobs": [blob], "files": [{"name": "mesh_00001_.glb", "mime": "model/gltf-binary", "kind": "model"}]}


def snapshot(folder: Path):
    if not folder.exists():
        return []
    return sorted((str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in folder.rglob("*") if p.is_file())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-mesh-fetch-") as tmp:
        root = Path(tmp)
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

        import numpy as np
        from fastapi import HTTPException
        from PIL import Image
        from app.blender import refine
        from app.core import base_body, footwear_source as fs, garment_assembly, garment_hair, garment_images
        from app.core import garment_mesh as gm, garment_store as gs, garment_subtract, garments
        from app.core.keyed_lock import keyed_lock
        from app.imagegen import service as service_mod
        from app.imagegen.service import ImageService
        from app.models.character import save_character_profile
        from app.routes import characters as routes
        garment_assembly.schedule = lambda *a, **k: False

        GOOD, BAD, SHOE = quads_glb([0.99, 0.01]), quads_glb([0.97, 0.03]), shoe_glb()
        backend = FakeMeshBackend({"good1": ("done", GOOD, "good1-full"), "bad1": ("done", BAD, "bad1"),
                                   "run1": ("running",), "shoe1": ("done", SHOE, "shoe1"),
                                   "src1": ("done", GOOD, "src1"),
                                   "shoebad": ("done", shoe_glb(inside=False), "shoebad")})

        class Svc:
            """Stand-in for the image service: the real fetch over the one fake mesh backend."""
            _store_mesh_files = staticmethod(ImageService._store_mesh_files)
            fetch_mesh_job = ImageService.fetch_mesh_job

            def list_available_backends(self, media="image", **_kw):
                return [backend] if media == "mesh" else []

        service_mod.get_image_service = lambda: Svc()

        decimations = []

        def fake_decimate(path_in, target_tris, out, *, merge_vertices=False):
            from app.core import glb_mesh
            tris = int(len(glb_mesh.static_arrays(Path(path_in).read_bytes())[1]))
            decimations.append((target_tris, merge_vertices))
            shutil.copyfile(path_in, out)
            return {"ok": True, "path": str(out), "tris_before": tris, "tris": tris, "ratio": 0.999, "error": ""}

        refine.decimate_to = fake_decimate

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        F = gs.garment_fsig("Demo", hid)
        garments_dir = gs.garments_dir("Demo")

        def fetch(job, *, footwear=False, item=None):
            body = routes.GarmentMeshFetchRequest(job_id=job)
            route = routes.fetch_character_footwear_mesh_job if footwear else routes.fetch_character_garment_mesh_job
            try:
                return 200, route("Demo", item or hid, body, _={})
            except HTTPException as e:
                return e.status_code, e.detail

        print("[1] done -> accepted")
        gs.record_failure("Demo", hid, F, step="mesh", error="poll timed out")
        gs.end("Demo", hid, "mesh", error="poll timed out")
        code, res = fetch("Job good1")
        check("200", code, 200)
        check("status / step / job", (res.get("status"), res.get("step"), res.get("job_id")),
              ("accepted", "mesh", "good1-full"))
        raw, prepared = gs.garment_path("Demo", hid, F, "raw"), gs.garment_path("Demo", hid, F, "prepared")
        check("raw = GOOD", raw.is_file() and raw.read_bytes() == GOOD, True)
        check("prepared = GOOD", prepared.is_file() and prepared.read_bytes() == GOOD, True)
        rec = gs.read_record(prepared.with_suffix(".json"))
        check("record accepted / collected_job", (rec.get("accepted"), rec.get("collected_job")), (True, "good1-full"))
        check("one attempt, noted", [(a.get("attempt"), a.get("collected_job")) for a in rec.get("attempts") or []],
              [(1, "good1-full")])
        check("tris / target", (rec.get("tris_raw"), rec.get("tris_prepared"), rec.get("target_tris")), (4, 4, 25000))
        near("share", rec.get("largest_component_share"), 0.99, 1e-6)
        check("backend", rec.get("backend"), "FakeMesh")
        check("decimation (target, welded)", decimations[-1], (25000, True))
        check("failure record gone", gs.garment_path("Demo", hid, F, "failed").exists(), False)
        check("in-memory failure gone", gs.status("Demo", hid).get("failed"), None)
        check("no staging left", [p.name for p in raw.parent.iterdir() if p.name.startswith(".")], [])
        try:
            again = gm.generate("Demo", hid, F)
        except AttributeError as e:
            again = f"generated: {e}"
        check("next run reuses the pair (R13)", again, prepared)

        print("[2] running -> nothing written")
        before = snapshot(garments_dir)
        code, res = fetch("run1")
        check("200 running", (code, res.get("status"), res.get("progress")), (200, "running", 0.4))
        check("nothing written", snapshot(garments_dir), before)

        print("[3] unknown / not a job id")
        code, detail = fetch("zzzz9999")
        check("404 unknown", code, 404)
        check("error names the job", "zzzz9999" in str(detail), True)
        check("nothing written", snapshot(garments_dir), before)
        asked = len(backend.asked)
        code, _detail = fetch("../x")
        check("400 not a job id", code, 400)
        check("fetch_job not asked", len(backend.asked), asked)

        print("[4] refused next to an accepted mesh -> nothing written")
        failed_path = gs.garment_path("Demo", hid, F, "failed")
        kept = {p: p.read_bytes() for p in (raw, prepared, prepared.with_suffix(".json"))}
        code, res = fetch("bad1")
        check("200 refused, kept", (code, res.get("status"), res.get("kept")), (200, "refused", True))
        check("reasons name the gate", any("largest component" in r for r in res.get("reasons") or []), True)
        check("raw / prepared / record byte-identical", {p.name: p.read_bytes() == b for p, b in kept.items()},
              {p.name: True for p in kept})
        check("no failure record", failed_path.exists(), False)
        check("no in-memory failure", gs.status("Demo", hid).get("failed"), None)

        print("[4b] refused without an accepted mesh -> recorded like a refused step")
        prepared.unlink()
        prepared.with_suffix(".json").unlink()
        code, res = fetch("bad1")
        check("200 refused, not kept", (code, res.get("status"), res.get("kept")), (200, "refused", False))
        rec = gs.read_record(prepared.with_suffix(".json"))
        check("record refused / collected_job", (rec.get("accepted"), rec.get("collected_job")), (False, "bad1"))
        near("refused share", rec.get("largest_component_share"), 0.97, 1e-6)
        check("older prepared gone", prepared.exists(), False)
        check("failure persisted at mesh", gs.read_record(gs.garment_path("Demo", hid, F, "failed")).get("step"), "mesh")

        print("[5] a mesh step running -> 409")
        before = snapshot(garments_dir)
        asked = len(backend.asked)
        lock = gs.char_lock("Demo")
        lock.acquire()
        try:
            code, detail = fetch("good1")
        finally:
            lock.release()
        check("409", code, 409)
        check("fetch_job not asked", len(backend.asked), asked)
        check("nothing written", snapshot(garments_dir), before)

        print("[6] footwear source (store level)")
        iid = "shoe_w"
        ssig = fs.current_ssig(iid)
        d = fs.source_dir(iid, ssig)
        d.mkdir(parents=True)
        try:
            fs.collect_mesh_job(iid, "shoe1")
            check("no cut-out raises", "no error", "FileNotFoundError")
        except FileNotFoundError:
            check("no cut-out raises", "FileNotFoundError", "FileNotFoundError")
        alpha = np.zeros((256, 256), np.uint8)
        alpha[78:178, 32:224] = 255
        cut = Image.new("RGBA", (256, 256), (40, 40, 40, 0))
        cut.putalpha(Image.fromarray(alpha, "L"))
        cut.save(d / "cutout.png", format="PNG")
        fs._set_step(d, "cutout", fs._entry(accepted=True, gates={}))
        (d / "insole.json").write_text("{}")
        fs._set_step(d, "insole", fs._entry(accepted=True, gates={}))
        held, release = threading.Event(), threading.Event()

        def hold():
            with keyed_lock("footwear_source", iid):
                held.set()
                release.wait(10)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(5)
        asked = len(backend.asked)
        try:
            fs.collect_mesh_job(iid, "shoe1")
            check("busy raises", "no error", "SourceBusy")
        except fs.SourceBusy:
            check("busy raises", "SourceBusy", "SourceBusy")
        finally:
            release.set()
            t.join()
        check("busy: fetch_job not asked", len(backend.asked), asked)
        res = fs.collect_mesh_job(iid, "run1")
        check("running", (res.get("status"), (d / "raw.glb").exists(), (d / "prepared.glb").exists()),
              ("running", False, False))
        check("running: insole kept", (d / "insole.json").exists(), True)
        res = fs.collect_mesh_job(iid, "shoe1")
        check("shoe accepted", (res.get("status"), res.get("ssig")), ("accepted", ssig))
        check("prepared + raw", ((d / "prepared.glb").is_file(), (d / "raw.glb").read_bytes() == SHOE), (True, True))
        rec = fs.step_record(iid, ssig, "mesh")
        g = rec.get("gates") or {}
        check("mesh record", (rec.get("accepted"), rec.get("collected_job"), rec.get("tris_raw")), (True, "shoe1", 24))
        near("component_share", g.get("component_share"), 1.0, 1e-6)
        near("mesh_iou", g.get("mesh_iou"), 1.0, 0.02)
        check("decimation (target, welded)", decimations[-1], (30000, True))
        check("insole dropped", ((d / "insole.json").exists(), "insole" in (fs._read(d)["steps"])), (False, False))
        check("no staging / candidate", sorted(p.name for p in d.iterdir() if p.name.startswith(".")), [])
        (d / "insole.json").write_text('{"insole_cover": 1.0}')
        fs._set_step(d, "insole", fs._entry(accepted=True, gates={}))
        kept = {name: (d / name).read_bytes() for name in ("prepared.glb", "raw.glb", "record.json", "insole.json")}
        res = fs.collect_mesh_job(iid, "shoebad")
        check("shoebad refused, kept", (res.get("status"), res.get("kept")), ("refused", True))
        check("shoebad reasons name component_share",
              any("component_share" in r for r in res.get("reasons") or []), True)
        check("shoe files + insole byte-identical", {n: (d / n).read_bytes() == b for n, b in kept.items()},
              {n: True for n in kept})

        print("[7] subtract source (store level)")
        I, S = "0000000000a1", "0000000000b2"
        for view in gs.GARMENT_VIEWS:
            path = gs.garment_path("Demo", hid, I, "image", step="haired", view=view)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 64), (200, 180, 160)).save(path, format="PNG")
            gs.write_record(path.with_suffix(".json"), {"accepted": True})
        garment_images._mask_image = lambda data, size: Image.new("L", size, 255)
        folder = gs.source_dir("Demo", hid, S)
        res = garment_subtract.collect_source_job("Demo", hid, I, S, "run1")
        check("running: no source folder", (res.get("status"), folder.exists()), ("running", False))
        res = garment_subtract.collect_source_job("Demo", hid, I, S, "src1")
        check("source accepted", res.get("status"), "accepted")
        glb = folder / garment_subtract.SOURCE_GLB
        check("haired.glb = GOOD", glb.is_file() and glb.read_bytes() == GOOD, True)
        check("cut-outs", sorted(p.name for p in folder.glob("haired_*_cut.png")),
              ["haired_back_cut.png", "haired_front_cut.png"])
        rec = garment_subtract.source_record("Demo", hid, S)
        check("source record", (rec.get("accepted"), rec.get("collected_job"), rec.get("tris")), (True, "src1", 4))
        check("source_glb", garment_subtract.source_glb("Demo", hid, S), glb)
        check("no staging left", [p.name for p in folder.parent.iterdir() if p.name.startswith(".")], [])

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
