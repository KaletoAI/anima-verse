#!/usr/bin/env python3
"""Hair as its own mesh, task 5: the routed garment mesh and its decimation
(app/core/garment_mesh.py, app/blender/refine.py::decimate_to).

Usage:
    ./.venv/bin/python scripts/smoke_garment_mesh.py [--no-blender]

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no server. The image service is a recorder
that writes synthetic GLBs; ``runner.run`` is stubbed for the generate checks.
Section [8] runs ONE real Blender decimation on a synthetic grid when a usable
Blender (5.2) is found; ``--no-blender`` or a missing Blender skips it.
Every expectation is derived by hand below from plan
2026-11-09-base-body-phase4-hair (R8, R10, R13, Task 5).

Fixture: ``Demo`` (human-roleplay, on the base-body pipeline, hair slot
{length: medium, color: blonde}); ensure_hair_item gives H = "hair_demo",
kind "hair". F = "0123456789ab" (any 12-hex fsig: generate takes it as given).
Cut-outs: garments/images/H_F_cutout_{front,back}.png (fake PNG bytes).

Fixture GLBs (positions, TEXCOORD_0, uint32 indices; 2 disjoint quads = 4 tris):
    GOOD: quad A side sqrt(0.99) -> area 0.99, quad B side 0.1 -> area 0.01;
          largest component share = 0.99 / 1.00 = 0.99 >= 0.98 -> pass.
    BAD:  quad A area 0.97, quad B area 0.03 -> share 0.97 < 0.98 -> fail.

[1] generate(Demo, H, F) with the service writing GOOD:
    - ONE generate_mesh call with occasion "hair_views_mesh" (kind hair; a
      clothing piece runs on "mesh_garment"), face_num 100000,
      view_images {"back": <cutout back>} (keys {"back"}),
      source_image_path = <cutout front>, output_path = garments/raw/H_F.glb,
      mesh_name "Demo-hair", character_name "Demo", material "dielectric",
      alpha "opaque";
    - runner: "measure" on the raw file (4 tris), then "lod" with
      ratios [min(0.999, 25000/4 = 6250)] = [0.999], keep_uvs True and
      merge_vertices True (bug B of the 2026-11-09 end-to-end run);
    - returns garments/prepared/H_F.glb (exists, bytes = GOOD);
    - record prepared/H_F.json: accepted True, tris_raw 4, tris_prepared 4,
      target_tris 25000, largest_component_share 0.99 (+-1e-6), backend
      "FakeMesh", routing {"occasion": "hair_views_mesh"} copied from the result,
      1 attempt.
[2] Cache: a second generate makes NO service call and returns the same path;
    force=True makes exactly one more call.
[3] BAD on both attempts (fsig G = "00000000bad0"): 2 service calls, then
    MeshGateRefused with 2 records; record accepted False,
    largest_component_share 0.97 (+-1e-6), attempts [0.97, 0.97], both ok
    False with a reason naming "largest component"; no prepared GLB left,
    no candidate file left in prepared/.
[4] BAD then GOOD (fsig M = "0000000000c4"): 2 calls, accepted at attempt 2;
    record attempts[0].ok False (0.97), attempts[1].ok True (0.99).
[5] A missing back cut-out (fsig N = "0000000000d5", front only) ->
    FileNotFoundError, no service call.
[6] The service answering {"ok": False, "error": "down"} (fsig E =
    "0000000000e6") -> RuntimeError naming "down", no record, no prepared GLB.
[6b] BAD on attempt 1, then the service RAISING "no backend available ..."
    on attempt 2 (fsig R = "0000000000f7"; bug C1 of the 2026-11-09 end-to-end
    run): MeshAttemptFailed (a RuntimeError) with 2 records — [attempt 1 ok
    False, share 0.97; attempt 2 ok False, error naming "no backend"]; the
    message names the error and "attempt 1 refused"; record accepted False
    with both attempts, share 0.97 (the gated attempt), error set; no
    prepared GLB, no candidate. The service raising on attempt 1 (fsig
    S = "0000000000f6"): MeshAttemptFailed with ONE record, no step record.
[7] decimate_to with stubbed runner:
    - measure reports 100000 tris, target 25000 -> ratio 0.25, the lod output
      "model_lod25000.glb" is moved to the given out path, result
      {ok True, tris_before 100000, tris 25000, ratio 0.25};
    - measure fails -> ok False, error non-empty, out not written.
[8] Real Blender (optional): a flat 20x20 grid = 800 tris, target 200 ->
    ratio min(0.999, 200/800) = 0.25; ok True, out exists, tris_before 800,
    tris within [150, 250] (Decimate hits the ratio approximately), no
    "*_lod*" file left beside out.
[9] Real Blender (optional), the UV-seam tear (bug B): a closed lat-long
    unit sphere, 32 longitudes x 16 latitudes = 32 x (2 x 16 - 2) = 960
    tris, stored as 4 latitude bands of 4 rows, each band its own UV island
    with its OWN vertices (glTF splits a vertex per UV, so a generator's
    mesh arrives cut at every seam). Welded by position it is one closed
    surface: largest component share 1.0. decimate_to(..., 240,
    merge_vertices=True) -> ratio 240/960 = 0.25; the import welds the
    bands back into one surface, so the result is still one component:
    share >= 0.98 (the garment gate). Control: merge_vertices=False on the
    same file must tear (share < 0.98 — each band shrinks on its own), or
    the fixture does not exercise the bug. Old lod.py ignores the param ->
    the merged run tears too and fails.
"""
import json
import math
import os
import shutil
import struct
import sys
import tempfile
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


# --- Synthetic GLBs -----------------------------------------------------------

def make_glb(quads, *, grid=0) -> bytes:
    """A static GLB. ``quads``: list of (x0, side) axis-aligned squares in the
    z=0 plane, each its own 4 vertices (disjoint). ``grid`` > 0 instead builds
    one flat grid of grid x grid quads (shared vertices, continuous UVs)."""
    pos, uv, idx = [], [], []
    if grid:
        n = grid + 1
        for j in range(n):
            for i in range(n):
                pos.append((i / grid, j / grid, 0.0))
                uv.append((i / grid, j / grid))
        for j in range(grid):
            for i in range(grid):
                a = j * n + i
                idx += [a, a + 1, a + n + 1, a, a + n + 1, a + n]
    else:
        for x0, side in quads:
            base = len(pos)
            for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1)):
                pos.append((x0 + dx * side, dy * side, 0.0))
                uv.append((float(dx), float(dy)))
            idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    pb = b"".join(struct.pack("<3f", *p) for p in pos)
    ub = b"".join(struct.pack("<2f", *u) for u in uv)
    ib = b"".join(struct.pack("<I", i) for i in idx)
    blob = pb + ub + ib
    mins = [min(p[k] for p in pos) for k in range(3)]
    maxs = [max(p[k] for p in pos) for k in range(3)]
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "garment", "mesh": 0}],
        "meshes": [{"name": "garment", "primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pb), "target": 34962},
            {"buffer": 0, "byteOffset": len(pb), "byteLength": len(ub), "target": 34962},
            {"buffer": 0, "byteOffset": len(pb) + len(ub), "byteLength": len(ib), "target": 34963}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": mins, "max": maxs},
            {"bufferView": 1, "componentType": 5126, "count": len(uv), "type": "VEC2"},
            {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"}],
    }
    js = json.dumps(gltf).encode("utf-8")
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def split_sphere_glb(n_lon=32, n_lat=16, band=4) -> bytes:
    """Closed lat-long unit sphere; every latitude band of ``band`` rows is
    its own UV island with its own vertices (a glTF UV-seam split)."""
    pos, uv, idx = [], [], []
    for b0 in range(0, n_lat, band):
        index = {}
        for j in range(b0, b0 + band + 1):
            th = math.pi * j / n_lat
            for i in range(n_lon + 1):
                ph = 2 * math.pi * (i % n_lon) / n_lon
                index[(j, i)] = len(pos)
                pos.append((math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)))
                uv.append((i / n_lon, b0 / n_lat + (j - b0) / band * 0.2))
        for j in range(b0, b0 + band):
            for i in range(n_lon):
                a, b, c, d = index[(j, i)], index[(j, i + 1)], index[(j + 1, i + 1)], index[(j + 1, i)]
                if j != 0:
                    idx += [a, b, c]
                if j != n_lat - 1:
                    idx += [a, c, d]
    return glb_from_arrays(pos, uv, idx)


def glb_from_arrays(pos, uv, idx) -> bytes:
    pb = b"".join(struct.pack("<3f", *p) for p in pos)
    ub = b"".join(struct.pack("<2f", *u) for u in uv)
    ib = b"".join(struct.pack("<I", i) for i in idx)
    blob = pb + ub + ib
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "garment", "mesh": 0}],
        "meshes": [{"name": "garment", "primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pb), "target": 34962},
            {"buffer": 0, "byteOffset": len(pb), "byteLength": len(ub), "target": 34962},
            {"buffer": 0, "byteOffset": len(pb) + len(ub), "byteLength": len(ib), "target": 34963}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": [min(p[k] for p in pos) for k in range(3)],
             "max": [max(p[k] for p in pos) for k in range(3)]},
            {"bufferView": 1, "componentType": 5126, "count": len(uv), "type": "VEC2"},
            {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"}],
    }
    js = json.dumps(gltf).encode("utf-8")
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


GOOD = make_glb([(0.0, math.sqrt(0.99)), (5.0, 0.1)])
BAD = make_glb([(0.0, math.sqrt(0.97)), (5.0, math.sqrt(0.03))])


class Recorder:
    """Stands in for the image service: writes ``script[i]`` per call."""

    def __init__(self):
        self.calls = []
        self.script = []
        self.answer = None
        self.raise_at = 0

    def generate_mesh(self, **kw):
        self.calls.append(kw)
        if self.raise_at and len(self.calls) == self.raise_at:
            raise RuntimeError("no backend available for hair_views_mesh: FakeMesh (cooling down)")
        if self.answer is not None:
            return dict(self.answer)
        blob = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        out = Path(kw["output_path"])
        out.write_bytes(blob)
        return {"ok": True, "path": str(out), "format": "glb", "backend": "FakeMesh",
                "routing": {"occasion": "hair_views_mesh"}}


def main() -> int:
    use_blender = "--no-blender" not in sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="garment-mesh-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.blender import refine, runner
        from app.core import base_body, garment_assembly, garment_hair
        from app.core import garment_store as gs
        from app.imagegen import service as service_mod
        from app.models.character import save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        try:
            from app.core import garment_mesh as gm
        except ImportError as e:
            check("garment_mesh importable", str(e), "importable")
            print("FAILED: " + ", ".join(FAILS))
            return 1

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair item id", hid, "hair_demo")

        def cutouts(fsig, views=("front", "back")):
            out = {}
            for view in views:
                p = gs.garment_path("Demo", hid, fsig, "image", step="cutout", view=view)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"\x89PNG-" + view.encode() + b"-" + fsig.encode())
                out[view] = p
            return out

        rec = Recorder()
        service_mod.get_image_service = lambda: rec

        # Stubbed Blender: "measure" counts the fixture's triangles from its
        # index accessor; "lod" copies the input to <stem>_lod<N>.glb.
        runner_calls = []
        real_run, real_version = runner.run, runner.version

        def glb_tris(path):
            data = Path(path).read_bytes()
            jlen = struct.unpack_from("<I", data, 12)[0]
            gltf = json.loads(data[20:20 + jlen])
            return sum(gltf["accessors"][p["indices"]]["count"] // 3
                       for m in gltf["meshes"] for p in m["primitives"])

        def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
            runner_calls.append((script, dict(params or {}), Path(inputs["model"])))
            src = Path(inputs["model"])
            tris = glb_tris(src)
            if script == "measure":
                return {"ok": True, "error": "", "data": {"tris": tris}, "outputs": {}}
            if script == "lod":
                dst = Path(out_dir) / f"model_lod{tris}.glb"
                shutil.copyfile(src, dst)
                return {"ok": True, "error": "",
                        "data": {"stages": [{"ratio": params["ratios"][0], "tris_before": tris,
                                             "tris": tris, "file": dst.name}],
                                 "source_tris": tris},
                        "outputs": {f"lod{tris}": str(dst)}}
            return {"ok": False, "error": "unexpected script", "data": {}, "outputs": {}}

        runner.run = fake_run
        runner.version = lambda executable="": "5.2.2"

        print("[1] generate")
        F = "0123456789ab"
        cut = cutouts(F)
        rec.script = [GOOD]
        prepared = gm.generate("Demo", hid, F)
        check("one service call", len(rec.calls), 1)
        kw = rec.calls[0] if rec.calls else {}
        check("occasion", kw.get("occasion"), "hair_views_mesh")
        check("face_num", kw.get("face_num"), 100000)
        check("view_images keys", set((kw.get("view_images") or {}).keys()), {"back"})
        check("back view path", (kw.get("view_images") or {}).get("back"), str(cut["back"]))
        check("front path", str(kw.get("source_image_path")), str(cut["front"]))
        check("output_path", str(kw.get("output_path")), str(gs.garment_path("Demo", hid, F, "raw")))
        check("mesh_name", kw.get("mesh_name"), "Demo-hair")
        check("character_name", kw.get("character_name"), "Demo")
        check("material", kw.get("material"), "dielectric")
        check("alpha", kw.get("alpha"), "opaque")
        check("runner scripts", [c[0] for c in runner_calls], ["measure", "lod"])
        lod_params = runner_calls[1][1] if len(runner_calls) > 1 else {}
        check("decimate ratio", lod_params.get("ratios"), [min(0.999, 25000 / 4)])
        check("ratio is 0.999", lod_params.get("ratios"), [0.999])
        check("keep_uvs", lod_params.get("keep_uvs"), True)
        check("merge_vertices", lod_params.get("merge_vertices"), True)
        check("prepared path", prepared, gs.garment_path("Demo", hid, F, "prepared"))
        check("prepared bytes", prepared.read_bytes() == GOOD, True)
        record = gs.read_record(prepared.with_suffix(".json"))
        check("accepted", record.get("accepted"), True)
        check("tris_raw", record.get("tris_raw"), 4)
        check("tris_prepared", record.get("tris_prepared"), 4)
        check("target_tris", record.get("target_tris"), 25000)
        near("largest share", record.get("largest_component_share"), 0.99, 1e-6)
        check("backend", record.get("backend"), "FakeMesh")
        check("routing", record.get("routing"), {"occasion": "hair_views_mesh"})
        check("attempts", len(record.get("attempts") or []), 1)
        check("TARGET_TRIS", gm.TARGET_TRIS, 25000)

        print("[2] cache")
        again = gm.generate("Demo", hid, F)
        check("cached: no call", len(rec.calls), 1)
        check("cached path", again, prepared)
        gm.generate("Demo", hid, F, force=True)
        check("force: one more call", len(rec.calls), 2)

        print("[3] two failed attempts")
        G = "00000000bad0"
        cutouts(G)
        rec.calls.clear()
        rec.script = [BAD]
        refused = None
        try:
            gm.generate("Demo", hid, G)
        except gm.MeshGateRefused as e:
            refused = e
        check("refused", refused is not None, True)
        check("two calls", len(rec.calls), 2)
        check("refusal records", len(getattr(refused, "records", []) or []), 2)
        check("refusal step", getattr(refused, "step", None), "mesh")
        prep_g = gs.garment_path("Demo", hid, G, "prepared")
        rec_g = gs.read_record(prep_g.with_suffix(".json"))
        check("failure record accepted", rec_g.get("accepted"), False)
        near("failure share", rec_g.get("largest_component_share"), 0.97, 1e-6)
        shares = [round(a.get("largest_component_share", -1), 6) for a in rec_g.get("attempts") or []]
        check("attempt shares", shares, [0.97, 0.97])
        check("attempts not ok", [a.get("ok") for a in rec_g.get("attempts") or []], [False, False])
        check("reason names the gate",
              all("largest component" in " ".join(a.get("reasons") or []) for a in rec_g.get("attempts") or []),
              True)
        check("no prepared GLB", prep_g.exists(), False)
        leftovers = sorted(p.name for p in prep_g.parent.iterdir() if p.name.startswith("."))
        check("no candidate left", leftovers, [])

        print("[4] fail then pass")
        M = "0000000000c4"
        cutouts(M)
        rec.calls.clear()
        rec.script = [BAD, GOOD]
        p_m = gm.generate("Demo", hid, M)
        check("two calls", len(rec.calls), 2)
        rec_m = gs.read_record(p_m.with_suffix(".json"))
        check("accepted at 2", rec_m.get("accepted"), True)
        check("attempt oks", [a.get("ok") for a in rec_m.get("attempts") or []], [False, True])
        check("attempt shares", [round(a.get("largest_component_share", -1), 6)
                                 for a in rec_m.get("attempts") or []], [0.97, 0.99])

        print("[5] missing cut-out")
        N = "0000000000d5"
        cutouts(N, views=("front",))
        rec.calls.clear()
        try:
            gm.generate("Demo", hid, N)
            check("missing back raises", "no error", "FileNotFoundError")
        except FileNotFoundError:
            check("missing back raises", "FileNotFoundError", "FileNotFoundError")
        check("no call", len(rec.calls), 0)

        print("[6] backend error")
        E = "0000000000e6"
        cutouts(E)
        rec.answer = {"ok": False, "error": "down"}
        try:
            gm.generate("Demo", hid, E)
            check("error raises", "no error", "RuntimeError")
        except RuntimeError as e:
            check("error raises", "down" in str(e), True)
        rec.answer = None
        prep_e = gs.garment_path("Demo", hid, E, "prepared")
        check("no record", prep_e.with_suffix(".json").exists(), False)
        check("no prepared", prep_e.exists(), False)

        print("[6b] attempt 2 fails at the backend")
        R = "0000000000f7"
        cutouts(R)
        rec.calls.clear()
        rec.script, rec.raise_at = [BAD], 2
        failed = None
        try:
            gm.generate("Demo", hid, R)
        except RuntimeError as e:
            failed = e
        rec.raise_at = 0
        check("MeshAttemptFailed", type(failed).__name__, "MeshAttemptFailed")
        records = list(getattr(failed, "records", []) or [])
        check("two records", [r.get("attempt") for r in records], [1, 2])
        if len(records) == 2:
            check("record 1 = gate", (records[0].get("ok"), round(records[0].get("largest_component_share", -1), 6)),
                  (False, 0.97))
            check("record 2 = error", (records[1].get("ok"), "no backend" in (records[1].get("error") or "")),
                  (False, True))
        check("message names both", ("no backend" in str(failed), "attempt 1 refused" in str(failed)), (True, True))
        prep_r = gs.garment_path("Demo", hid, R, "prepared")
        rec_r = gs.read_record(prep_r.with_suffix(".json"))
        check("record refused with both", (rec_r.get("accepted"), len(rec_r.get("attempts") or []),
                                           "no backend" in (rec_r.get("error") or "")), (False, 2, True))
        near("record share = gated attempt", rec_r.get("largest_component_share"), 0.97, 1e-6)
        check("no prepared / candidate", (prep_r.exists(),
                                          sorted(p.name for p in prep_r.parent.iterdir() if p.name.startswith("."))),
              (False, []))
        S = "0000000000f6"
        cutouts(S)
        rec.calls.clear()
        rec.raise_at = 1
        failed = None
        try:
            gm.generate("Demo", hid, S)
        except RuntimeError as e:
            failed = e
        rec.raise_at = 0
        check("first attempt raising", (type(failed).__name__, len(getattr(failed, "records", []) or [])),
              ("MeshAttemptFailed", 1))
        check("first attempt: no record",
              gs.garment_path("Demo", hid, S, "prepared").with_suffix(".json").exists(), False)

        print("[7] decimate_to (stubbed)")
        work = root / "dec"
        work.mkdir()
        src = work / "big.glb"
        src.write_bytes(GOOD)
        runner_calls.clear()

        def run_100k(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
            runner_calls.append((script, dict(params or {})))
            if script == "measure":
                return {"ok": True, "error": "", "data": {"tris": 100000}, "outputs": {}}
            dst = Path(out_dir) / "model_lod25000.glb"
            shutil.copyfile(inputs["model"], dst)
            return {"ok": True, "error": "",
                    "data": {"stages": [{"ratio": params["ratios"][0], "tris_before": 100000,
                                         "tris": 25000, "file": dst.name}], "source_tris": 100000},
                    "outputs": {"lod25000": str(dst)}}

        runner.run = run_100k
        out = work / "small.glb"
        res = refine.decimate_to(src, 25000, out)
        check("ok", res.get("ok"), True)
        check("ratio", res.get("ratio"), 0.25)
        check("lod ratios", runner_calls[-1][1].get("ratios"), [0.25])
        check("tris_before", res.get("tris_before"), 100000)
        check("tris", res.get("tris"), 25000)
        check("out written", out.read_bytes() == GOOD, True)
        check("only out in dir", sorted(p.name for p in work.iterdir()), ["big.glb", "small.glb"])
        runner.run = lambda script, **k: {"ok": False, "error": "no blender", "data": {}, "outputs": {}}
        out2 = work / "none.glb"
        res2 = refine.decimate_to(src, 25000, out2)
        check("measure fails: ok False", res2.get("ok"), False)
        check("measure fails: error", bool(res2.get("error")), True)
        check("measure fails: no out", out2.exists(), False)

        print("[8] real Blender decimation")
        runner.run, runner.version = real_run, real_version
        if not use_blender or not runner.is_available():
            print("  SKIP (no usable Blender or --no-blender)")
        else:
            grid = work / "grid.glb"
            grid.write_bytes(make_glb([], grid=20))
            gout = work / "grid_small.glb"
            res3 = refine.decimate_to(grid, 200, gout)
            check("blender ok", res3.get("ok"), True)
            check("blender ratio", res3.get("ratio"), 0.25)
            check("blender tris_before", res3.get("tris_before"), 800)
            tris3 = res3.get("tris") or 0
            check("blender tris in [150, 250]", 150 <= tris3 <= 250, True)
            check("blender out exists", gout.is_file(), True)
            check("no lod leftovers", sorted(p.name for p in work.iterdir() if "_lod" in p.name), [])

        print("[9] real Blender: UV-seam split sphere")
        if not use_blender or not runner.is_available():
            print("  SKIP (no usable Blender or --no-blender)")
        else:
            sphere = work / "sphere.glb"
            sphere.write_bytes(split_sphere_glb())
            near("sphere raw share", gm.largest_component_share(sphere), 1.0, 1e-9)
            merged, torn = work / "sphere_merged.glb", work / "sphere_torn.glb"
            res_m = refine.decimate_to(sphere, 240, merged, merge_vertices=True)
            res_t = refine.decimate_to(sphere, 240, torn, merge_vertices=False)
            check("sphere ok", (res_m.get("ok"), res_t.get("ok")), (True, True))
            check("sphere tris_before / ratio", (res_m.get("tris_before"), res_m.get("ratio")), (960, 0.25))
            share_m = gm.largest_component_share(merged) if merged.is_file() else 0.0
            share_t = gm.largest_component_share(torn) if torn.is_file() else 1.0
            check(f"merged stays one surface (share {share_m:.4f} >= 0.98)", share_m >= gm.MIN_COMPONENT_SHARE,
                  True)
            check(f"control: unmerged tears (share {share_t:.4f} < 0.98)", share_t < gm.MIN_COMPONENT_SHARE, True)

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
