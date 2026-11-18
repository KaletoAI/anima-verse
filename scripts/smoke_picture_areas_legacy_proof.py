#!/usr/bin/env python3
"""Host-side proof of an OLD (pre-marker) picture-area split
(``props._legacy_atlas_backup_proven`` and its wiring in ``props._areas_run``).

Usage:  ./.venv/bin/python scripts/smoke_picture_areas_legacy_proof.py

Pure Python, no Blender, no server: a throw-away storage root in /tmp, one
prop with two variants, and model files written straight into the variants'
galleries with the sidecars the store itself writes (``_land_split``:
``source: areas`` + ``source_file`` = the chain origin; ``copy_variant_mesh``:
``source: variant-copy`` + ``copied_from.file``). The GLBs are JSON-only
stand-ins: the proof reads nothing but the JSON chunk (TEXCOORD sets per
primitive, mesh extras) and, for a variant copy, the bytes.

THE RULE UNDER TEST (expected values derived from it by hand):
  proven(src) = src carries NO ``av_atlas_uv`` mesh extra
                AND some primitive of src has >= 2 TEXCOORD sets
                AND lineage(src), where
  lineage(f)  = f.source == "areas"  -> f's chain origin is still stored in
                its gallery AND (that origin has <= 1 TEXCOORD per primitive
                OR the origin is a variant-copy with lineage(origin))
              | f.source == "variant-copy" -> the copied_from file is stored
                in some variant's gallery, byte-identical to f, and
                lineage(that file)
              | anything else -> False

  H1 origin O (upload, 1 set) <- split S (areas, 2 sets, no marker)  -> True
  H2 S2 = S with the marker extra                                   -> False
  H3 S3 split of O with only 1 set (nothing to claim)               -> False
  H4 origin L with 2 sets (a lightmap) <- split SL (2 sets)         -> False
  H5 split SG whose source_file names a file that is gone           -> False
  H6 U: an upload with 2 sets and a slot material, never split      -> False
  H7 variant 1: C = byte copy of S (variant-copy, copied_from S)    -> True
  H8 C' = variant-copy naming S but with DIFFERENT bytes            -> False
  H9 variant 1: split S1 whose origin is C (C has 2 sets, proven)   -> True
  H10 pre-E4 chain: Sb (areas, source_file Sa) <- Sa (areas,
      source_file O) — the walk ends on O                          -> True
  W1 ``_areas_run`` on the variant whose active file is S: the params
     handed to the runner carry ``unmarked_backup_is_last_layer: True``
     next to the caller's own (mode delete, area picture_1).
  W2 the same with U active: the key is ABSENT (not False — the run is
     exactly the strict one).
"""
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="picture-areas-proof-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402
from app.core.model_store import write_sidecar as write_model_sidecar  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def glb(sets: int, *, marked: bool = False, materials=("atlas",), tag: str = "") -> bytes:
    """A JSON-only GLB: one mesh, one primitive per material, ``sets``
    TEXCOORD attributes each; ``marked`` adds the mesh extra; ``tag`` only
    changes the bytes (a mesh name)."""
    attrs = {"POSITION": 0, **{f"TEXCOORD_{i}": 1 + i for i in range(sets)}}
    mesh = {"name": "plate" + tag,
            "primitives": [{"attributes": dict(attrs), "material": k}
                           for k in range(len(materials))]}
    if marked:
        mesh["extras"] = {"av_atlas_uv": 1}
    gltf = {"asset": {"version": "2.0"}, "meshes": [mesh],
            "materials": [{"name": m} for m in materials]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js))
            + struct.pack("<II", len(js), 0x4E4F534A) + js)


def put(gallery, data: bytes, sidecar: dict, select: bool = False) -> Path:
    p = gallery.new_path()
    p.write_bytes(data)
    write_model_sidecar(p, {"format": "glb", "rig": "none", "tier": "full", **sidecar})
    if select:
        gallery.select(p.name, store.DEFAULT_TIER)
    return p


def main() -> int:
    pid = store.create_prop(name="Legacy plate", category="decor")["id"]
    v1 = store.add_variant(pid)
    check("setup: a second variant exists", v1 == 1, str(v1))
    g0, g1 = store.model_gallery(pid, 0), store.model_gallery(pid, 1)
    split_mats = ("atlas", "slot_picture_1")

    o = put(g0, glb(1), {"source": "upload"})
    s = put(g0, glb(2, materials=split_mats), {"source": "areas", "source_file": o.name})
    s2 = put(g0, glb(2, marked=True, materials=split_mats), {"source": "areas", "source_file": o.name})
    s3 = put(g0, glb(1, materials=split_mats), {"source": "areas", "source_file": o.name})
    lm = put(g0, glb(2), {"source": "upload"})
    sl = put(g0, glb(2, materials=split_mats), {"source": "areas", "source_file": lm.name})
    sg = put(g0, glb(2, materials=split_mats), {"source": "areas",
                                                "source_file": g0.stem + "_1.glb"})
    u = put(g0, glb(2, materials=split_mats), {"source": "upload"})
    sa = put(g0, glb(2, materials=split_mats, tag="a"), {"source": "areas", "source_file": o.name})
    sb = put(g0, glb(2, materials=split_mats, tag="b"), {"source": "areas", "source_file": sa.name})
    c = put(g1, s.read_bytes(), {"source": "variant-copy", "source_file": s.name,
                                 store.COPIED_FROM_KEY: {"file": s.name, "signature": ""}})
    cx = put(g1, glb(2, materials=split_mats, tag="x"),
             {"source": "variant-copy", "source_file": s.name,
              store.COPIED_FROM_KEY: {"file": s.name, "signature": ""}})
    s1 = put(g1, glb(2, materials=split_mats, tag="1"), {"source": "areas", "source_file": c.name})

    proven = store._legacy_atlas_backup_proven
    print("\n[H] the proof")
    check("H1 split of a one-set origin, unmarked, 2 sets -> proven", proven(pid, s) is True)
    check("H2 the same with the marker -> not", proven(pid, s2) is False)
    check("H3 a split with 1 set -> not (nothing to claim)", proven(pid, s3) is False)
    check("H4 origin with 2 sets (lightmap) -> not", proven(pid, sl) is False)
    check("H5 origin gone -> not", proven(pid, sg) is False)
    check("H6 an upload with 2 sets and a slot material -> not", proven(pid, u) is False)
    check("H7 byte copy of a proven split in another variant -> proven", proven(pid, c) is True)
    check("H8 a copy whose bytes differ -> not", proven(pid, cx) is False)
    check("H9 a split whose origin is a proven copy -> proven", proven(pid, s1) is True)
    check("H10 pre-E4 chain Sb -> Sa -> O -> proven", proven(pid, sb) is True)

    print("\n[W] the run parameter")
    from app.blender import refine, runner
    seen = []
    orig = (runner.run, refine.unavailable_reason, refine.take_lod_slot, refine.free_lod_slot)

    def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
        seen.append(dict(params or {}))
        return {"ok": False, "error": "stopped by the smoke", "data": {}, "outputs": {}}
    runner.run = fake_run
    refine.unavailable_reason = lambda: ""
    refine.take_lod_slot = lambda wait_s=0.0: True
    refine.free_lod_slot = lambda: None
    try:
        for label, active, want in (("W1", s, True), ("W2", u, None)):
            g0.select(active.name, store.DEFAULT_TIER)
            seen.clear()
            try:
                store._areas_run(pid, 0, {"mode": "delete", "area": "picture_1"},
                                 default_source="manual", wait_s=0.0)
            except store.AreaProcessingError:
                pass
            got = seen[0] if seen else {}
            check(f"{label}: runner called once", len(seen) == 1, str(seen))
            check(f"{label}: caller params kept",
                  got.get("mode") == "delete" and got.get("area") == "picture_1", str(got))
            check(f"{label}: unmarked_backup_is_last_layer = {want}",
                  got.get("unmarked_backup_is_last_layer") is want
                  and (want is not None or "unmarked_backup_is_last_layer" not in got), str(got))
    finally:
        runner.run, refine.unavailable_reason, refine.take_lod_slot, refine.free_lod_slot = orig

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
