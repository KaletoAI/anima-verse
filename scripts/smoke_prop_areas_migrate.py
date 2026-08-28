#!/usr/bin/env python3
"""Smoke run for the ONE-TIME migration of legacy prop-level picture-area
fields onto the model FILES (spec-bild-props-v2.md E1, ruling V0).

Usage:  ./.venv/bin/python scripts/smoke_prop_areas_migrate.py

No world, no DB, no server, no Blender: a throwaway props directory in /tmp
gets ONE prop written by hand in the OLD shape, and
``prop_areas_migrate.migrate_prop_areas_to_files()`` is asked to move it.
Every expected value below is derived BY HAND from the rule, never recorded
from a run.

THE RULE. Until 2026-08-28 ``areas``, ``leaf_bbox``, ``rotation``,
``area_defaults``, ``areas_error`` and ``areas_run_at`` sat on the PROP
sidecar, although every variant is its own img2mesh generation (measured on
a real door prop: variant `model-v3` has other axes and no leaf node). They
belong to the MODEL FILE now, and the legacy value can only ever have
described the PRIMARY variant's active full mesh — so that is where it goes:

  * the primary's active FULL file sidecar gets ``areas``, ``leaf_bbox``,
    ``rotation``, ``areas_run_at``; a legacy ``areas_error`` that is the
    no-leaf NOTE becomes ``areas_warning`` (a run that worked), any other
    text stays ``areas_error``;
  * the primary's LOW file (a store-built distance mesh, sidecar
    ``source: lod``) gets ``inherits_from: <full file name>`` plus copies of
    ``areas`` / ``leaf_bbox`` / ``rotation``, so ``file_areas(low)`` answers
    with the full file's values;
  * a VARIANT COPY (model sidecar ``source: variant-copy`` — a byte copy of
    the primary's mesh, same axes) gets the ``rotation`` too, and its own
    ``areas`` / ``leaf_bbox`` from the ``.areas.json`` companion that
    travelled with the copy (that companion IS a reading of that file);
  * a variant that is its OWN generation gets nothing — its axes are not
    the primary's, and the legacy value never described it;
  * ``area_defaults`` moves onto the PRIMARY variant's entry (checked
    against the file areas it now names);
  * the prop sidecar LOSES all six keys; ``key_areas`` stays prop-wide (V2).

Idempotent by CONTENT, not by a world_kv flag: a second run finds no legacy
key and moves nothing — the migration needs no DB at all.

THE FIXTURE, prop ``door-old``:

    sidecar (old shape)
        areas         [picture_1 (48 faces), glass_1 (12 faces)]
        leaf_bbox     {min [0.1, 0.1, -0.02], max [0.9, 2.1, 0]}
        rotation      {x 0, y 270, z 0}
        area_defaults {glass_1: {preset glass}}
        areas_error   props.NO_LEAF_NOTE            (a WORKING run's note)
        areas_run_at  "2026-08-27T10:00:00+00:00"
        key_areas     ["glass"]
        model_variants [model, model-v2, model-v3], all active
    files
        model_1.glb / .json        full, source generated   (the primary)
        model_2.glb / .json        low,  source lod, source_file model_1.glb
        model-v2_1.glb / .json     full, source variant-copy
        model-v2_1.glb.areas.json areas [picture_1 (+edges)], leaf_bbox
        model-v3_1.glb / .json     full, source generated   (own generation)
        selection.json  model: {full: model_1.glb, low: model_2.glb},
                        model-v2: {full: …}, model-v3: {full: …}

EXPECTED after the first run — ``{"props": 2, "moved": 1}`` (a second prop
``plain`` without legacy keys is counted, not moved):

    model_1.json     areas == the legacy list, leaf_bbox, rotation y 270,
                     areas_run_at as stored, areas_warning == NO_LEAF_NOTE,
                     NO areas_error
    model_2.json     inherits_from "model_1.glb", rotation y 270,
                     areas ids [picture_1, glass_1], the leaf_bbox
                     file_areas(model_2.glb) == the full file's values
    model-v2_1.json  rotation y 270, areas ids [picture_1], the companion's
                     leaf_bbox
    model-v3_1.json  untouched (no rotation, no areas key)
    sidecar          none of the six keys; key_areas ["glass"];
                     model_variants[0].area_defaults == {glass_1: glass}
    record           no prop-level areas/leaf_bbox/rotation/area_defaults;
                     variant_tiers[0]: rotation y 270, areas ids
                     [picture_1, glass_1], leaf_bbox, area_defaults;
                     variant_tiers[1]: rotation y 270, areas [picture_1];
                     variant_tiers[2]: rotation 0, areas []

Second run: ``{"props": 2, "moved": 0}`` and every file byte-identical.

A legacy prop WITHOUT any model file has nowhere to put the values: its keys
are dropped (it counts as moved), nothing else is written, nothing raises.
"""
import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-areas-migrate-smoke-"))

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402
from app.core.prop_areas_migrate import migrate_prop_areas_to_files  # noqa: E402

# No LOD threads and no Blender from the record reads.
store.request_low_tier = lambda *a, **k: None

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def glb(materials) -> bytes:
    body = json.dumps({"asset": {"version": "2.0"},
                       "materials": [{"name": m} for m in materials],
                       "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}
                      ).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)
    chunk = struct.pack("<II", len(body), 0x4E4F534A) + body
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunk)) + chunk


AREAS = [
    {"id": "picture_1", "kind": "picture", "size_m": [0.5, 0.4],
     "normal": [0, 0, 1], "source": "auto", "faces": 48},
    {"id": "glass_1", "kind": "glass", "size_m": [0.3, 0.3],
     "normal": [0, 0, 1], "source": "auto", "faces": 12},
]
LEAF = {"min": [0.1, 0.1, -0.02], "max": [0.9, 2.1, 0.0]}
COPY_LEAF = {"min": [0.2, 0.2, -0.02], "max": [0.8, 2.0, 0.0]}
RUN_AT = "2026-08-27T10:00:00+00:00"


def write_file(d: Path, name: str, sidecar: dict, materials) -> None:
    (d / name).write_bytes(glb(materials))
    (d / name).with_suffix(".json").write_text(
        json.dumps({"created_at": RUN_AT, "format": "glb", "rig": "none",
                    **sidecar}, indent=2), encoding="utf-8")


def make_legacy(pid: str, *, files: bool = True) -> Path:
    d = paths.get_storage_dir() / "props" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / store.SIDECAR_NAME).write_text(json.dumps({
        "name": "Old door", "category": "door",
        "areas": AREAS, "leaf_bbox": LEAF,
        "rotation": {"x": 0, "y": 270, "z": 0},
        "area_defaults": {"glass_1": {"preset": "glass"}},
        "areas_error": store.NO_LEAF_NOTE, "areas_run_at": RUN_AT,
        "key_areas": ["glass"],
        "model_variants": [
            {"stem": "model", "active": True, "width_m": 1.0, "depth_m": 0.1,
             "height_m": 2.2, "dims_estimated": False},
            {"stem": "model-v2", "active": True, "width_m": 1.0,
             "depth_m": 0.1, "height_m": 2.2, "dims_estimated": False},
            {"stem": "model-v3", "active": True, "width_m": 1.0,
             "depth_m": 0.1, "height_m": 2.2, "dims_estimated": False}],
    }, indent=2), encoding="utf-8")
    if not files:
        return d
    write_file(d, "model_1.glb", {"source": "generated", "tier": "full"},
               ["atlas", "slot_picture_1", "slot_glass_1"])
    write_file(d, "model_2.glb", {"source": "lod", "tier": "low",
                                  "source_file": "model_1.glb"},
               ["atlas", "slot_picture_1", "slot_glass_1"])
    write_file(d, "model-v2_1.glb", {"source": "variant-copy", "tier": "full",
                                     "source_file": "model_1.glb"},
               ["atlas", "slot_picture_1"])
    (d / "model-v2_1.glb.areas.json").write_text(json.dumps({
        "areas": [{**AREAS[0], "edges": [[[0, 0, 0], [1, 0, 0]]]}],
        "leaf_bbox": COPY_LEAF, "mesh_layout": [], "run_at": RUN_AT}),
        encoding="utf-8")
    write_file(d, "model-v3_1.glb", {"source": "generated", "tier": "full"},
               ["atlas"])
    (d / "selection.json").write_text(json.dumps({
        "model": {"full": "model_1.glb", "low": "model_2.glb"},
        "model-v2": {"full": "model-v2_1.glb"},
        "model-v3": {"full": "model-v3_1.glb"}}), encoding="utf-8")
    return d


def sidecar_of(d: Path, name: str) -> dict:
    return json.loads((d / name).with_suffix(".json").read_text(encoding="utf-8"))


def main() -> int:
    print("[1] the legacy values land on the primary's active full file")
    d = make_legacy("door-old")
    store.create_prop(name="Plain")            # no legacy keys: counted, not moved
    stats = migrate_prop_areas_to_files()
    check("stats: 2 props seen, 1 moved", stats == {"props": 2, "moved": 1}, str(stats))
    full = sidecar_of(d, "model_1.glb")
    check("full: areas == the legacy list", full.get("areas") == AREAS, str(full.get("areas")))
    check("full: leaf_bbox", full.get("leaf_bbox") == LEAF, str(full.get("leaf_bbox")))
    check("full: rotation y 270", full.get("rotation") == {"x": 0, "y": 270, "z": 0},
          str(full.get("rotation")))
    check("full: areas_run_at kept", full.get("areas_run_at") == RUN_AT, str(full.get("areas_run_at")))
    check("full: the no-leaf note is a WARNING, no areas_error",
          full.get("areas_warning") == store.NO_LEAF_NOTE and "areas_error" not in full,
          str((full.get("areas_warning"), full.get("areas_error"))))

    print("\n[2] the low file inherits")
    low = sidecar_of(d, "model_2.glb")
    check("low: inherits_from model_1.glb", low.get("inherits_from") == "model_1.glb",
          str(low.get("inherits_from")))
    check("low: rotation + areas + leaf_bbox copied",
          low.get("rotation") == {"x": 0, "y": 270, "z": 0}
          and [a["id"] for a in low.get("areas") or []] == ["picture_1", "glass_1"]
          and low.get("leaf_bbox") == LEAF, str(low))
    fa = store.file_areas(d / "model_2.glb")
    check("file_areas(low) answers with the full file's values",
          [a["id"] for a in fa["areas"]] == ["picture_1", "glass_1"]
          and fa["rotation"] == {"x": 0, "y": 270, "z": 0} and fa["leaf_bbox"] == LEAF
          and fa["areas_warning"] == store.NO_LEAF_NOTE, str(fa))

    print("\n[3] a variant COPY gets the rotation and its companion's areas; an own generation nothing")
    copy = sidecar_of(d, "model-v2_1.glb")
    check("copy: rotation y 270", copy.get("rotation") == {"x": 0, "y": 270, "z": 0},
          str(copy.get("rotation")))
    check("copy: areas from its .areas.json, edges stripped",
          copy.get("areas") == [AREAS[0]], str(copy.get("areas")))
    check("copy: leaf_bbox from its .areas.json", copy.get("leaf_bbox") == COPY_LEAF,
          str(copy.get("leaf_bbox")))
    own = sidecar_of(d, "model-v3_1.glb")
    check("own generation: no rotation, no areas",
          "rotation" not in own and "areas" not in own and "leaf_bbox" not in own, str(own))

    print("\n[4] the prop sidecar lost the keys, variant 0 carries the defaults")
    meta = store.read_sidecar("door-old")
    check("none of the six legacy keys is left",
          not any(k in meta for k in ("areas", "leaf_bbox", "rotation", "area_defaults",
                                      "areas_error", "areas_run_at")),
          str(sorted(meta)))
    check("key_areas stays prop-wide (V2)", meta.get("key_areas") == ["glass"],
          str(meta.get("key_areas")))
    entries = store._variant_list(meta)
    check("variant 0 carries area_defaults {glass_1: glass}",
          entries[0].get("area_defaults") == {"glass_1": {"preset": "glass"}},
          str(entries[0].get("area_defaults")))
    check("variants 1 and 2 carry none",
          "area_defaults" not in entries[1] and "area_defaults" not in entries[2])

    print("\n[5] the record answers per variant")
    rec = store.get_prop("door-old")
    check("no prop-level areas / leaf_bbox / rotation / area_defaults",
          not any(k in rec for k in ("areas", "leaf_bbox", "rotation", "area_defaults")),
          str([k for k in ("areas", "leaf_bbox", "rotation", "area_defaults") if k in rec]))
    tiers = rec.get("variant_tiers") or []
    check("three published variants", len(tiers) == 3, str(len(tiers)))
    t0 = tiers[0] if tiers else {}
    check("variant_tiers[0]: rotation y 270, both areas, leaf_bbox, defaults",
          t0.get("rotation") == {"x": 0, "y": 270, "z": 0}
          and [a["id"] for a in t0.get("areas") or []] == ["picture_1", "glass_1"]
          and t0.get("leaf_bbox") == LEAF
          and t0.get("area_defaults") == {"glass_1": {"preset": "glass"}}, str(t0))
    t1 = tiers[1] if len(tiers) > 1 else {}
    check("variant_tiers[1]: rotation y 270, areas [picture_1]",
          t1.get("rotation") == {"x": 0, "y": 270, "z": 0}
          and [a["id"] for a in t1.get("areas") or []] == ["picture_1"]
          and t1.get("leaf_bbox") == COPY_LEAF, str(t1))
    t2 = tiers[2] if len(tiers) > 2 else {}
    check("variant_tiers[2]: rotation 0, no areas, no leaf_bbox",
          t2.get("rotation") == {"x": 0, "y": 0, "z": 0} and t2.get("areas") == []
          and "leaf_bbox" not in t2, str(t2))

    print("\n[6] the second run is a no-op")
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    stats = migrate_prop_areas_to_files()
    check("stats: 2 props, 0 moved", stats == {"props": 2, "moved": 0}, str(stats))
    after = {p.name: p.read_bytes() for p in d.iterdir()}
    check("every file is byte-identical", before == after,
          str([n for n in before if before[n] != after.get(n)]))

    print("\n[7] a legacy prop without a model drops its keys and raises nothing")
    d2 = make_legacy("door-empty", files=False)
    stats = migrate_prop_areas_to_files()
    check("stats: 3 props, 1 moved", stats == {"props": 3, "moved": 1}, str(stats))
    meta2 = store.read_sidecar("door-empty")
    check("keys gone", "areas" not in meta2 and "rotation" not in meta2, str(sorted(meta2)))
    check("no model file was conjured", not list(d2.glob("*.glb")), str(list(d2.iterdir())))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
