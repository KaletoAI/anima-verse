#!/usr/bin/env python3
"""Smoke run for the ONE slim export set (plan-marketplace-props.md Teil A).

Runs against a THROWAWAY storage directory — never touches a real world. All
model files are dummy bytes; nothing is generated. Every expected file list is
derived BY HAND below from one rule:

    EXPORT WHAT THE READERS RESOLVE, NOT WHAT LIES IN THE FOLDER.

    Per variant (ALL of them, in season or not): the tier files the gallery
    resolves (selection, else the NEWEST file for a stem without an entry,
    nothing under the ``__none__`` sentinel), each with its ``.json`` sidecar
    and ``.surface.json`` lattice; for props also the ``.areas.json`` and the
    FULL file a LOW file names in ``inherits_from`` (with ITS companions —
    ``file_areas`` reads that file while it exists); the source image of every
    view; ``sidecar.json`` + ``selection.json``. Never: gallery history,
    ``raw/``, ``scene_asset/``, and a lattice that is already invalid at
    home (its model was rewritten after the bake) — the import re-binds every
    lattice whose size matches, so a stale one would come back to life.

[1] Prop "Barrel", two variants (variant 1 tagged Winter — out of season or
    not, it is part of the object). Files written:
        model_100.glb  .json  .glb.surface.json  .glb.areas.json   v0 full, selected
        model_101.glb  .json {inherits_from: model_99.glb}          v0 low, selected
        model_99.glb   .json {rotation y=90}  .glb.areas.json       NOT selected, LOW's parent
        model_50.glb   .json                                        history
        model-v2_200.glb  .json  .glb.surface.json (STALE)          v1 full, selected
        model-v2_201.glb  .json                                     history
        raw/model_100.glb, raw/model-v2_200.glb                     refine backups
        scene_asset/1-2/mask.png                                    no reader
        source.png, source_back.png, source-v2.png                  source images
        selection.json, sidecar.json
    Expected export (16): sidecar.json, selection.json,
        model_100.glb, model_100.json, model_100.glb.surface.json,
        model_100.glb.areas.json, model_101.glb, model_101.json,
        model_99.glb, model_99.json, model_99.glb.areas.json,
        model-v2_200.glb, model-v2_200.json,
        source.png, source_back.png, source-v2.png

[2] Prop "Lamp", one variant, NO selection.json, model_1 (created 2026-01-01)
    and model_2 (created 2026-02-01) → the default tier is the NEWEST file:
    export = sidecar.json, model_2.glb, model_2.json.

[3] Prop "Ghost", selection {"model": {"full": "__none__"}} beside model_1.glb
    → the admin chose NO model: export = sidecar.json, selection.json.

[4] Location "Mill" with rooms A and B (+ the reserved ground room).
    model3d/: building_0 (history), building_1 (selected), room_A_1 (selected,
    with a lattice), room_B_5 + room_B_6 (no entry; room_B_6 is newer),
    selection {"building": building_1, "room_A": room_A_1}.
    Expected files/model3d/ (8): building_1.glb, building_1.json,
        room_A_1.glb, room_A_1.json, room_A_1.glb.surface.json,
        room_B_6.glb, room_B_6.json, selection.json
    → manifest model3d_file_count 8. "Barrel" is placed in room A, so
    props/<barrel>/ carries exactly the 16 files of [1].

[5] Roundtrip.
    Prop: import_prop_from_zip(export, overwrite=True) → the prop dir holds
    exactly the 16 files; ``file_areas`` of the LOW file still answers the
    PARENT's rotation (y=90, not its own y=0) — the proof that the parent
    travelled; the v0 full mesh's lattice is still VALID (``read_surface`` not
    None) although the import wrote the file anew (new mtime → re-anchored).
    Location: import_location_from_zip → a copy with NEW room ids; its
    room_<newA>_1.glb lattice is valid under the new name too.

Usage:  ./.venv/bin/python scripts/smoke_content_slim_export.py
"""
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="content-slim-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="content-slim-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import props  # noqa: E402
from app.core.content_io import (  # noqa: E402
    export_location_to_zip, export_prop_to_zip, import_location_from_zip,
    import_prop_from_zip)
from app.core.location_model3d import _model_dir, _owner_id  # noqa: E402
from app.core.model_surface import (  # noqa: E402
    PAYLOAD_KEYS, SURFACE_VERSION, _source_of, read_surface, surface_path)
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

FAILURES = []
ROT0 = {"x": 0, "y": 0, "z": 0}


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def put(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        path.write_bytes(data)


def lattice_for(model: Path) -> None:
    """A complete, VALID lattice for ``model`` as it lies on disk now. The
    model's mtime is moved an hour back first: the lattice stores it in WHOLE
    seconds, and an import in the same second as the seed would keep a stale
    lattice valid by accident — the check would prove nothing."""
    old = model.stat().st_mtime - 3600
    os.utime(model, (old, old))
    surface = {k: 0 for k in PAYLOAD_KEYS}
    surface.update({"version": SURFACE_VERSION, "source": _source_of(model),
                    "rotation": ROT0})
    put(surface_path(model), surface)


def zip_files(blob: bytes, prefix: str):
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return sorted(n[len(prefix):] for n in zf.namelist()
                      if n.startswith(prefix))


BARREL_EXPECTED = sorted([
    "sidecar.json", "selection.json",
    "model_100.glb", "model_100.json", "model_100.glb.surface.json",
    "model_100.glb.areas.json", "model_101.glb", "model_101.json",
    "model_99.glb", "model_99.json", "model_99.glb.areas.json",
    "model-v2_200.glb", "model-v2_200.json",
    "source.png", "source_back.png", "source-v2.png",
])

print("\n[1] prop with history, a LOD parent, backups and two variants")
barrel = props.create_prop(name="Barrel", category="furniture",
                           width_m=0.6, depth_m=0.6, height_m=1.0)["id"]
check("second variant", props.add_variant(barrel), 1)
meta = props.read_sidecar(barrel)
meta["model_variants"][1]["seasons"] = ["Winter"]
props._write_sidecar(barrel, meta)
bd = props._prop_dir(barrel)
put(bd / "model_100.glb", b"GLB-full")
put(bd / "model_100.json", {"tier": "full"})
lattice_for(bd / "model_100.glb")
put(bd / "model_100.glb.areas.json", {"areas": []})
put(bd / "model_101.glb", b"GLB-low")
put(bd / "model_101.json", {"tier": "low", "inherits_from": "model_99.glb",
                            "rotation": {"x": 0, "y": 0, "z": 0}})
put(bd / "model_99.glb", b"GLB-old-full")
put(bd / "model_99.json", {"tier": "full", "rotation": {"x": 0, "y": 90, "z": 0}})
put(bd / "model_99.glb.areas.json", {"areas": []})
put(bd / "model_50.glb", b"GLB-history")
put(bd / "model_50.json", {})
put(bd / "model-v2_200.glb", b"GLB-v2")
put(bd / "model-v2_200.json", {"tier": "full"})
lattice_for(bd / "model-v2_200.glb")
os.utime(bd / "model-v2_200.glb")          # rewritten after the bake → stale
put(bd / "model-v2_201.glb", b"GLB-v2-history")
put(bd / "model-v2_201.json", {})
put(bd / "raw" / "model_100.glb", b"RAW")
put(bd / "raw" / "model-v2_200.glb", b"RAW")
put(bd / "scene_asset" / "1-2" / "mask.png", b"PNG")
for name in ("source.png", "source_back.png", "source-v2.png"):
    put(bd / name, b"PNG")
put(bd / "selection.json", {"model": {"full": "model_100.glb", "low": "model_101.glb"},
                            "model-v2": {"full": "model-v2_200.glb"}})
check("variant 1 is tagged Winter",
      props.read_sidecar(barrel)["model_variants"][1].get("seasons"), ["Winter"])
rot_before = props.file_areas(bd / "model_101.glb")["rotation"]
check("LOW answers its parent's rotation before export", rot_before.get("y"), 90)
barrel_zip = export_prop_to_zip(barrel)
check("prop export", zip_files(barrel_zip, "files/"), BARREL_EXPECTED)

print("\n[2] a stem without selection serves its NEWEST file")
lamp = props.create_prop(name="Lamp", category="light")["id"]
ld = props._prop_dir(lamp)
put(ld / "model_1.glb", b"GLB-1")
put(ld / "model_1.json", {"created_at": "2026-01-01T00:00:00+00:00"})
put(ld / "model_2.glb", b"GLB-2")
put(ld / "model_2.json", {"created_at": "2026-02-01T00:00:00+00:00"})
(ld / "selection.json").unlink(missing_ok=True)
check("lamp export", zip_files(export_prop_to_zip(lamp), "files/"),
      ["model_2.glb", "model_2.json", "sidecar.json"])

print("\n[3] the __none__ sentinel exports no mesh, but keeps the statement")
ghost = props.create_prop(name="Ghost", category="misc")["id"]
gd = props._prop_dir(ghost)
put(gd / "model_1.glb", b"GLB")
put(gd / "model_1.json", {})
put(gd / "selection.json", {"model": {"full": "__none__"}})
check("ghost export", zip_files(export_prop_to_zip(ghost), "files/"),
      ["selection.json", "sidecar.json"])

print("\n[4] location: resolved room/building models + the slim bundled prop")
mill = add_location("Mill", "A mill.", rooms=[{"name": "A"}, {"name": "B"}])
mill_id = mill["id"]
room_a, room_b = mill["rooms"][0]["id"], mill["rooms"][1]["id"]
md = _model_dir(_owner_id(mill_id), create=True)
put(md / "building_0.glb", b"B0")
put(md / "building_0.json", {})
put(md / "building_1.glb", b"B1")
put(md / "building_1.json", {})
put(md / f"room_{room_a}_1.glb", b"RA")
put(md / f"room_{room_a}_1.json", {})
lattice_for(md / f"room_{room_a}_1.glb")
put(md / f"room_{room_b}_5.glb", b"RB5")
put(md / f"room_{room_b}_5.json", {"created_at": "2026-01-01T00:00:00+00:00"})
put(md / f"room_{room_b}_6.glb", b"RB6")
put(md / f"room_{room_b}_6.json", {"created_at": "2026-02-01T00:00:00+00:00"})
put(md / "selection.json", {"building": {"full": "building_1.glb"},
                            f"room_{room_a}": {"full": f"room_{room_a}_1.glb"}})
data = _load_world_data()
for entry in data.get("locations", []):
    if entry.get("id") == mill_id:
        for room in entry.get("rooms", []):
            if room.get("id") == room_a:
                room["layout"] = {"x": 0, "y": 0, "w": 4, "d": 3,
                                  "props": [{"prop_id": barrel, "at": [0.5, 0.5],
                                             "yaw": 0}]}
_save_world_data(data)
mill_zip = export_location_to_zip(mill_id)
check("model3d files", zip_files(mill_zip, "files/model3d/"), sorted([
    "building_1.glb", "building_1.json",
    f"room_{room_a}_1.glb", f"room_{room_a}_1.json",
    f"room_{room_a}_1.glb.surface.json",
    f"room_{room_b}_6.glb", f"room_{room_b}_6.json", "selection.json"]))
with zipfile.ZipFile(io.BytesIO(mill_zip)) as zf:
    mman = json.loads(zf.read("manifest.json"))
check("manifest model3d_file_count", mman["model3d_file_count"], 8)
check("bundled prop files", zip_files(mill_zip, f"props/{barrel}/"), BARREL_EXPECTED)

print("\n[5] roundtrip: the copy reads the same as the original")
res = import_prop_from_zip(barrel_zip, overwrite=True)
check("prop import status", res.get("status"), "success")
on_disk = sorted(p.relative_to(bd).as_posix() for p in bd.rglob("*") if p.is_file())
check("prop dir after import", on_disk, BARREL_EXPECTED)
check("LOW still answers the PARENT's rotation",
      props.file_areas(bd / "model_101.glb")["rotation"], rot_before)
check("v0 full lattice valid after import",
      read_surface(bd / "model_100.glb", ROT0) is not None, True)
lres = import_location_from_zip(mill_zip)
new_id = lres.get("location_id") or lres.get("id")
check("location import status", lres.get("status"), "success")
from app.models.world import get_location_by_id  # noqa: E402
new_loc = get_location_by_id(new_id) or {}
new_a = next((r["id"] for r in new_loc.get("rooms", []) if r.get("name") == "A"), "")
check("room A got a NEW id", bool(new_a) and new_a != room_a, True)
nmd = _model_dir(_owner_id(new_id))
check("room A lattice valid under its new name",
      read_surface(nmd / f"room_{new_a}_1.glb", ROT0) is not None, True)

print("\nall checks passed" if not FAILURES
      else f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
