#!/usr/bin/env python3
"""Smoke run for the prop TEXTURE SLOTS (plan-door-props-texture-slots, task 4).

Usage:  ./.venv/bin/python scripts/smoke_props_slots.py

No world, no DB, no server: a throwaway props directory in /tmp gets a prop
written through the real store, and GLB fixtures are built here with the
stdlib (12-byte header + JSON chunk — no glTF library is installed and none is
wanted). Every expected value below is derived BY HAND from the rule, never
recorded from a run.

---------------------------------------------------------------------------
[1] THE MATERIAL NAMES COME OUT OF THE GLB
---------------------------------------------------------------------------
A slot is a MATERIAL of the mesh, so the only thing the import has to read is
`materials[].name` of the glTF JSON. Hand-derived from the fixture:

    materials [{name: "wood"}, {name: "picture"}]  -> ["wood", "picture"]
    the same file through `validate_static_glb`    -> the same list
    the same file through `glb_material_names_at`  -> the same list
    a GLB with no `materials` at all               -> []
    a material without a name                      -> left out (it can never
                                                     spell a slot)

Order is the FILE's order — the detection below carries it through, so the
slot list reads like the material list of the model.

---------------------------------------------------------------------------
[2] `detect_slots` — THE ONE RULE (Entscheid 4, made precise)
---------------------------------------------------------------------------
For every material name `m`, lower-cased:

    m starts with "slot_"  -> name = m[5:],  kind = "material" if the name is
                              one of {glass, mirror, matte}, else "image"
    m in {picture, screen, sign}  -> {name: m,      kind: "image"}
    m == "glass"                  -> {name: "glass", kind: "material"}
    otherwise                     -> no slot

Names are stored lower-case, de-duplicated, in order of FIRST appearance.
Hand-derived cases:

    ["wood", "picture"]
        wood     -> nothing (a plain material is not a slot)
        picture  -> the fixed list, image
        =>  [{"name": "picture", "kind": "image"}]

    ["slot_glass", "Slot_Poster", "glass", "SIGN"]
        slot_glass  -> prefix, name "glass", and "glass" is a MATERIAL name
        Slot_Poster -> prefix (case-insensitive), name "poster", image
        glass       -> the fixed list would say {glass, material} — but
                       "glass" is already there, so it is DROPPED (dedup by
                       name, first appearance wins)
        SIGN        -> the fixed list (case-insensitive), image
        =>  [{"glass","material"}, {"poster","image"}, {"sign","image"}]

    []              -> []
    ["slot_"]       -> [] (a prefix with nothing behind it names nothing)
    ["slot_mirror"] -> [{"mirror", "material"}]

ROTE PROBE: "glasses", "slots_x" and "picture_frame" are NOT slots — the
fixed list matches the WHOLE name and the prefix is exactly "slot_".

---------------------------------------------------------------------------
[3] DETECTION RUNS WHEN THE MODEL LANDS — AFTER the Blender steps
---------------------------------------------------------------------------
`_store_bbox` is the one post-ingest hook (generate / shrink / upload all end
there). The order matters and is asserted: the vertex-colour bake REPLACES
every material name with `baked_vc_mat_<i>`, so reading the names before it
would store slots the stored file does not have.

    bake_vc -> retexture -> low tier -> SLOTS -> bbox

After uploading the [1] fixture into a fresh prop:

    record["slots"]      == [{"name": "picture", "kind": "image"}]
    record["slots_auto"] is True        (the marker the UI shows "detected" by)

A prop that never got a model has `slots == []` — the field is ALWAYS on the
record, so no consumer has to know the difference.

---------------------------------------------------------------------------
[4] THE PATCH PATH VALIDATES, AND A REFUSAL WRITES NOTHING
---------------------------------------------------------------------------
`slots` is a `PROP_PATCH_KEYS` field, so it travels the ordinary prop patch
and the batch save. Hand-derived from the rule "list of {name, kind}, name
non-empty, kind in image|material":

    "picture"                          -> ValueError (not a list)
    [{"name": "x", "kind": "video"}]   -> ValueError (unknown kind)
    [{"name": "  ", "kind": "image"}]  -> ValueError (empty name)
    ["picture"]                        -> ValueError (an entry is an object)
    [{"name": "Poster", "kind": "image"},
     {"name": "poster", "kind": "material"}]
        -> stored as ONE slot {"poster", "image"}: lower-cased, and the first
           appearance wins exactly as in the detection

A refused patch leaves the sidecar BYTE-IDENTICAL — the batch's law.

---------------------------------------------------------------------------
[5] A HAND-EDITED LIST IS NEVER OVERWRITTEN
---------------------------------------------------------------------------
Storing `slots` clears the marker (`slots_auto` False), and the auto-fill only
ever fills a record that has NONE — so a second model of the same prop cannot
throw the admin's list away:

    patch slots [{"name": "screen", "kind": "image"}]  -> slots_auto False
    upload the [1] fixture again (picture material)    -> slots UNCHANGED

…and an admin who deletes every slot keeps that decision too: an EMPTY list
with `slots_auto` False stays empty over the next upload.

---------------------------------------------------------------------------
[6] SIDECAR ROUNDTRIP
---------------------------------------------------------------------------
Both keys live in the sidecar JSON and read back identically through
`read_sidecar`, so nothing here depends on the record being built.
"""
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-slots-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402
from app.core.model_validate import (glb_material_names_at,  # noqa: E402
                                     parse_glb, validate_static_glb)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def glb(gltf: dict) -> bytes:
    """A minimal GLB: 12-byte header + JSON chunk. Nothing reads a BIN chunk
    here — the material names sit in the JSON, which the spec puts first."""
    body = json.dumps(gltf).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)
    chunk = struct.pack("<II", len(body), 0x4E4F534A) + body
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunk)) + chunk


# The [1] fixture: a textured mesh whose two materials are a plain one and a
# slot from the fixed list.
WOOD_PICTURE = {
    "asset": {"version": "2.0"},
    "materials": [{"name": "wood"}, {"name": "picture"}],
    "images": [{"mimeType": "image/png", "bufferView": 0}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0,
                                               "TEXCOORD_0": 1}}]}],
}
NO_MATERIALS = {
    "asset": {"version": "2.0"},
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
}
UNNAMED = {
    "asset": {"version": "2.0"},
    "materials": [{"name": "wood"}, {"doubleSided": True}],
}


def main() -> int:
    print("[1] the material names come out of the GLB")
    data = glb(WOOD_PICTURE)
    check("parse_glb lists them in file order",
          parse_glb(data)["material_names"] == ["wood", "picture"],
          str(parse_glb(data).get("material_names")))
    check("the validation result carries them",
          validate_static_glb(data)["material_names"] == ["wood", "picture"],
          str(validate_static_glb(data).get("material_names")))
    check("a GLB without materials answers []",
          parse_glb(glb(NO_MATERIALS))["material_names"] == [])
    check("an unnamed material is left out",
          parse_glb(glb(UNNAMED))["material_names"] == ["wood"],
          str(parse_glb(glb(UNNAMED))["material_names"]))
    stored = WORLD / "fixture.glb"
    stored.write_bytes(data)
    check("a STORED file reads the same (header + JSON chunk only)",
          glb_material_names_at(stored) == ["wood", "picture"],
          str(glb_material_names_at(stored)))

    print("\n[2] detect_slots — the one rule")
    check("wood + picture -> the picture slot",
          store.detect_slots(["wood", "picture"])
          == [{"name": "picture", "kind": "image"}],
          str(store.detect_slots(["wood", "picture"])))
    got = store.detect_slots(["slot_glass", "Slot_Poster", "glass", "SIGN"])
    check("prefix + fixed list, case-insensitive, glass de-duplicated",
          got == [{"name": "glass", "kind": "material"},
                  {"name": "poster", "kind": "image"},
                  {"name": "sign", "kind": "image"}], str(got))
    check("nothing in, nothing out", store.detect_slots([]) == [])
    check("a bare prefix names nothing", store.detect_slots(["slot_"]) == [])
    check("slot_mirror is a MATERIAL slot",
          store.detect_slots(["slot_mirror"])
          == [{"name": "mirror", "kind": "material"}])
    near = store.detect_slots(["glasses", "slots_x", "picture_frame", "wood"])
    check("ROTE PROBE: near-misses are not slots", near == [], str(near))

    print("\n[3] detection runs when the model lands, after the Blender steps")
    order: list = []
    real_bake, real_tex = store._auto_bake_vc, store._auto_retexture
    real_low, real_fill = store.request_low_tier, store._autofill_slots
    store._auto_bake_vc = lambda *a, **k: order.append("bake_vc")
    store._auto_retexture = lambda *a, **k: order.append("retexture")
    store.request_low_tier = lambda *a, **k: order.append("low_tier")

    def _fill(prop_id):
        order.append("slots")
        return real_fill(prop_id)

    store._autofill_slots = _fill
    try:
        pid = store.create_prop(name="Framed picture", category="decor")["id"]
        check("a prop without a model has an EMPTY slot list",
              store.get_prop(pid)["slots"] == [],
              str(store.get_prop(pid)["slots"]))
        store.save_uploaded_glb(pid, data)
        ingest = list(order)
        rec = store.get_prop(pid)
        check("the post-ingest order is bake -> retexture -> low -> slots",
              ingest == ["bake_vc", "retexture", "low_tier", "slots"],
              str(ingest))
        check("the record carries the detected slot",
              rec["slots"] == [{"name": "picture", "kind": "image"}],
              str(rec["slots"]))
        check("…marked as detected", rec.get("slots_auto") is True,
              str(rec.get("slots_auto")))

        print("\n[4] the patch path validates, and a refusal writes nothing")
        before = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
        for label, value in (("a string is not a list", "picture"),
                             ("an unknown kind",
                              [{"name": "x", "kind": "video"}]),
                             ("an empty name",
                              [{"name": "  ", "kind": "image"}]),
                             ("an entry that is not an object", ["picture"])):
            try:
                store.update_prop(pid, {"slots": value})
                check(f"refused: {label}", False, "no ValueError")
            except ValueError as exc:
                after = (store._sidecar_path(pid) or Path()).read_text(
                    encoding="utf-8")
                check(f"refused: {label}", after == before, str(exc)[:60])
        out = store.update_prop(pid, {"slots": [
            {"name": "Poster", "kind": "image"},
            {"name": "poster", "kind": "material"}]})
        check("stored lower-cased and de-duplicated, first appearance wins",
              out["slots"] == [{"name": "poster", "kind": "image"}],
              str(out["slots"]))

        print("\n[5] a hand-edited list is never overwritten")
        out = store.update_prop(pid, {"slots": [{"name": "screen",
                                                 "kind": "image"}]})
        check("storing slots clears the detected marker",
              out.get("slots_auto") is False, str(out.get("slots_auto")))
        store.save_uploaded_glb(pid, data)
        rec = store.get_prop(pid)
        check("a second model leaves the authored list alone",
              rec["slots"] == [{"name": "screen", "kind": "image"}],
              str(rec["slots"]))
        store.update_prop(pid, {"slots": []})
        store.save_uploaded_glb(pid, data)
        check("…and an emptied list stays empty",
              store.get_prop(pid)["slots"] == [],
              str(store.get_prop(pid)["slots"]))

        print("\n[6] sidecar roundtrip")
        store.update_prop(pid, {"slots": [{"name": "glass",
                                           "kind": "material"}]})
        meta = store.read_sidecar(pid)
        check("both keys live in the sidecar",
              meta.get("slots") == [{"name": "glass", "kind": "material"}]
              and meta.get("slots_auto") is False,
              f"{meta.get('slots')} / {meta.get('slots_auto')}")
    finally:
        store._auto_bake_vc, store._auto_retexture = real_bake, real_tex
        store.request_low_tier, store._autofill_slots = real_low, real_fill

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
