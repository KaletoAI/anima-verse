#!/usr/bin/env python3
"""Smoke run for the prop PICTURE AREAS — sidecar fields, prompt fragments,
slot kind rule (spec-picture-props.md § 1–3, plan task 3, part 1: no Blender).

Usage:  ./.venv/bin/python scripts/smoke_props_areas.py

No world, no DB, no server: a throwaway props directory in /tmp gets a prop
written through the real store. Every expected value below is derived BY HAND
from the spec, never recorded from a run.

---------------------------------------------------------------------------
[1] SIDECAR ROUND-TRIP: key_areas / areas / area_defaults
---------------------------------------------------------------------------
`create_prop(..., key_areas=["glass", "picture", "picture"])` stores the
requested key colours de-duplicated in the fixed kind order of
`picture_areas.KINDS` = (picture, glass):

    key_areas -> ["picture", "glass"]

A prop without a detection run carries `areas == []` and `area_defaults == {}`
on its record — both fields are ALWAYS present, so no consumer has to know the
difference between "none" and "not detected yet".

`areas` written through `sanitize_areas` reads back identically:

    [{"id": "picture_1", "kind": "picture", "size_m": [0.5, 0.4],
      "normal": [0, 0, 1], "source": "auto", "faces": 48},
     {"id": "glass_1", "kind": "glass", "size_m": [0.3, 0.3],
      "normal": [1, 0, 0], "source": "manual", "faces": 12}]

An unknown kind in `key_areas` is a ValueError (a silently dropped kind would
report "Saved" over a request that reached nothing).

`key_areas` is a prop patch field too (ruling R7), same sanitizer:

    {"key_areas": ["glass"]}   -> stored ["glass"]
    {"key_areas": []}          -> the key is removed (record reads [])
    {"key_areas": ["neon"]}    -> ValueError, sidecar byte-identical

---------------------------------------------------------------------------
[2] area_defaults ARE CHECKED AGAINST THE AREAS
---------------------------------------------------------------------------
`area_defaults` travels the ordinary prop patch (`PROP_PATCH_KEYS`). With the
two areas of [1] stored:

    {"glass_1": {"preset": "glass"}}    -> stored as is
    {"nope": {"preset": "glass"}}       -> ValueError (unknown area)
    {"glass_1": {"preset": "mirror"}}   -> ValueError (preset not in SLOT_PRESETS)
    {"glass_1": {}}                     -> ValueError (a default needs a preset)
    "glass"                             -> ValueError (not an object)

A refused patch leaves the sidecar BYTE-IDENTICAL.

---------------------------------------------------------------------------
[3] detect_slots: THE PREFIX RULE FOR glass
---------------------------------------------------------------------------
A split writes materials `slot_picture_<k>` / `slot_glass_<k>`. The kind rule
of `detect_slots` gains the prefix `glass` -> material:

    ["slot_glass_1", "slot_picture_2"]
        -> [{"name": "glass_1", "kind": "material"},
            {"name": "picture_2", "kind": "image"}]

    "slot_glassy" is NOT a material slot (the prefix has to be the whole
    first token: glass, glass_<k>), "slot_glass" stays one (unchanged rule).

---------------------------------------------------------------------------
[4] compose_prompt APPENDS THE KEY-AREA FRAGMENTS
---------------------------------------------------------------------------
With `key_areas=["picture"]` the composed prompt ends with the picture
fragment of `config.KEY_AREA_PROMPTS` and the negative carries
`config.KEY_AREA_NEGATIVES["picture"]` = "painting, artwork, photo, poster,
landscape in frame". Without `key_areas` neither text appears. `glass`
likewise with the magenta fragment and "transparent glass, reflections".
With both kinds both fragments appear, picture first.

---------------------------------------------------------------------------
PART 2 — PICTURE VARIANTS + RECIPE (plan task 4, still no Blender)
---------------------------------------------------------------------------
The fixture mesh is built here with the stdlib (12-byte header + JSON chunk,
exactly as `scripts/smoke_props_slots.py` does it) and names three materials:

    ["atlas", "slot_picture_1", "slot_glass_1"]

so `detect_slots` reads the two areas off it and `_reconcile_areas` keeps
them over every landing. The sidecar `areas` are written through
`sanitize_areas` (the split itself is Blender's job and is proven in
`scripts/smoke_picture_areas_blender.py`):

    picture_1 (kind picture)   glass_1 (kind glass)

IMG = "/world/locations/demo/gallery/x.png" — one of the two URL forms
`_SLOT_IMAGE_RE` allows.

---------------------------------------------------------------------------
[5] A PICTURE VARIANT IS A VARIANT WITH A COPY OF THE MESH (§ 1, D2, R4)
---------------------------------------------------------------------------
`add_picture_variant(pid, {"picture_1": {"image": IMG}}, "x")` on a prop with
ONE variant returns index 1 and, hand-derived from the rule "copy the primary's
active full GLB under the new stem":

    the new stem is `model-v2` (`_free_stem`: `model` is taken)
    -> `model_gallery(pid, 1).find("full")` exists, name starts "model-v2_"
    -> its BYTES equal the primary's file byte for byte
    -> the prop's `slots` list is UNCHANGED — the copy names the same
       materials, so the same two fillable surfaces
    -> the `<model>.glb.areas.json` companion travels with the mesh
       (same content), and so does the variant's source image
    -> the copy's model sidecar carries
       `copied_from {"file": <primary file name>, "signature": <…>}`
    -> `list_variants(pid)[1]` has `slot_values == {"picture_1": {"image": IMG}}`,
       `label == "x"`, `stale is False`
    -> the PRIMARY entry has `slot_values == {}`, `label == ""`, `stale False`

A label the admin leaves out is derived from the picture FILE NAMES (basename
without extension), joined by ", ":

    {"picture_1": {"image": ".../sunset.png"}}          -> "sunset"
    a glass-only variant {"glass_1": {"preset": "glass"}} -> "glass"

---------------------------------------------------------------------------
[6] THE VALUES ARE CHECKED — THE AREA'S KIND DECIDES THE SHAPE
---------------------------------------------------------------------------
`sanitize_variant_slot_values` is the ONE gate (the recipe has no second one).
Hand-derived from the rule "key must be an area of THIS prop; picture -> image
URL, glass -> preset in SLOT_PRESETS":

    {"nope": {"image": IMG}}              -> ValueError (unknown area)
    {"picture_1": {"image": "https://x/y.png"}} -> ValueError (URL form)
    {"picture_1": {"image": "/foo/x.png"}}      -> ValueError (URL form)
    {"picture_1": {"preset": "glass"}}    -> ValueError (preset on a picture)
    {"glass_1": {"image": IMG}}           -> ValueError (image on a pane)
    {"glass_1": {"preset": "mirror"}}     -> ValueError (not in SLOT_PRESETS)
    "picture_1"                           -> ValueError (not an object)

A refused `add_picture_variant` creates NOTHING: the variant count stays put
and no new stem file appears. A refused `set_variant_slot_values` leaves the
sidecar BYTE-IDENTICAL.

---------------------------------------------------------------------------
[7] THE VARIANT CAP APPLIES TO PICTURE VARIANTS TOO (R5)
---------------------------------------------------------------------------
`variant_max()` is 4 by default. With four ACTIVE variants the fifth picture
variant is a ValueError, and the prop still has exactly four.

---------------------------------------------------------------------------
[8] THE RECIPE: slots = area_defaults ∪ the RESOLVED variant's slot_values
---------------------------------------------------------------------------
A 10 m location with room "a" (x −4, y −4, w 4, d 3) carrying two placements
of the frame prop and one S door with the door prop. With `area_defaults` still
empty:

    placement {"variant": 1}   -> spec["slots"] == {"picture_1": {"image": IMG}}
    placement without variant  -> no "slots" key at all (nothing to say)
    door prop without defaults -> no "slots" key

After `area_defaults = {"glass_1": {"preset": "glass"}}` on both props:

    placement {"variant": 1}   -> {"glass_1": {"preset": "glass"},
                                   "picture_1": {"image": IMG}}
    placement without variant  -> {"glass_1": {"preset": "glass"}}
    the door spec              -> {"glass_1": {"preset": "glass"}}

A variant index nobody has wraps (`_variant_index`), it never 404s: with two
variants `variant: 3` is position 1 — the picture variant again.

---------------------------------------------------------------------------
[9] A SWAPPED PICTURE MOVES THE SIGNATURE
---------------------------------------------------------------------------
Neither a new image nor a new default changes a mesh, a tier or a URL, so
without them in the key a running client would keep the old poster:

    `model_signature` and the scene `signature` both differ after
    set_variant_slot_values(..., {"picture_1": {"image": OTHER}})
    …and both differ after a changed `area_defaults`

---------------------------------------------------------------------------
[10] STALE + RE-COPY (R4)
---------------------------------------------------------------------------
`stale` = "the primary's ACTIVE full file is no longer the one this copy was
taken from" (`copied_from.file`). Uploading a second mesh onto the primary
therefore flips it:

    after `save_uploaded_glb(pid, FRAME2)`   -> list_variants[1]["stale"] True
    after `recopy_variant_mesh(pid, 1)`      -> False, `slot_values` KEPT,
        the variant's active file has the new primary's BYTES, and the old
        copy stays in the gallery as history (2 files under the stem)
    `recopy_variant_mesh(pid, 0)` (the primary itself) -> ValueError

---------------------------------------------------------------------------
[11] LABEL RULE (R10), EMPTY ASSIGNMENT, AND PRUNING WITH THE AREAS
---------------------------------------------------------------------------
The label is THREE-valued, because "the body said nothing" and "the admin
cleared the field" are different statements:

    set_variant_slot_values(..., label="Wall")  -> stored verbatim
    set_variant_slot_values(..., <no label>)    -> "Wall" STANDS
    set_variant_slot_values(..., label="")      -> derived again -> "x"

`add_picture_variant(pid, {})` is a ValueError: a variant that shows nothing
of its own is a plain `add_variant`, and that one copies no mesh.
`recopy_variant_mesh` is refused while the variant generates (the run is about
to write the very file the copy lands in) — the core says so, not only the
route.

PRUNING: an area that leaves the mesh takes BOTH halves of a spec's `slots`
with it, and the label stays. Driven through `_reconcile_areas` by uploading a
mesh that names `slot_picture_1` only:

    areas         ["picture_1", "glass_1"] -> ["picture_1"]
    area_defaults {"glass_1": …}           -> {}
    slot_values   {"picture_1": …, "glass_1": …} -> {"picture_1": …}
    label         "Both"                   -> "Both"   (untouched)
    spec slots                             -> {"picture_1": {"image": IMG}}

And a PRIMARY without an active full mesh makes nothing stale — there is
nothing to compare `copied_from.file` against, and the tab must not offer a
re-copy that can only fail.
"""
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-areas-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import config  # noqa: E402
from app.core import props as store  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class FakeBackend:
    """Just what `compose_prompt` reads off a backend."""
    name = "fake"
    model = ""
    image_family = "keywords"


AREAS = [
    {"id": "picture_1", "kind": "picture", "size_m": [0.5, 0.4],
     "normal": [0, 0, 1], "source": "auto", "faces": 48},
    {"id": "glass_1", "kind": "glass", "size_m": [0.3, 0.3],
     "normal": [1, 0, 0], "source": "manual", "faces": 12},
]


# ── Part 2: picture variants + recipe ───────────────────────────────────

IMG = "/world/locations/demo/gallery/x.png"
IMG2 = "/world/locations/demo/gallery/sunset.png"
CHAR_IMG = "/characters/demo/images/portrait.png"

FRAME_AREAS = [
    {"id": "picture_1", "kind": "picture", "size_m": [0.5, 0.4],
     "normal": [0, 0, 1], "source": "auto", "faces": 48},
    {"id": "glass_1", "kind": "glass", "size_m": [0.3, 0.3],
     "normal": [0, 0, 1], "source": "auto", "faces": 12},
]
GLASS_AREAS = [
    {"id": "glass_1", "kind": "glass", "size_m": [0.6, 1.2],
     "normal": [0, 0, 1], "source": "auto", "faces": 24},
]


def glb(gltf: dict) -> bytes:
    """A minimal GLB: 12-byte header + JSON chunk — the material names sit in
    the JSON, which the spec puts first (same writer as smoke_props_slots)."""
    body = json.dumps(gltf).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)
    chunk = struct.pack("<II", len(body), 0x4E4F534A) + body
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunk)) + chunk


def frame_glb(extra: str = "") -> bytes:
    """The frame fixture: an atlas plus the two split panels."""
    mats = [{"name": "atlas"}, {"name": "slot_picture_1"},
            {"name": "slot_glass_1"}]
    if extra:
        mats.append({"name": extra})
    return glb({"asset": {"version": "2.0"}, "materials": mats,
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]})


def door_glb() -> bytes:
    return glb({"asset": {"version": "2.0"},
                "materials": [{"name": "atlas"}, {"name": "slot_glass_1"}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]})


def make_prop(name: str, blob: bytes, areas: list) -> str:
    """A prop with a landed mesh and hand-written sidecar areas — the split
    itself is Blender's job (scripts/smoke_picture_areas_blender.py)."""
    pid = store.create_prop(name=name, category="decor")["id"]
    store.save_uploaded_glb(pid, blob)
    meta = store.read_sidecar(pid)
    meta[store.AREAS_KEY] = store.sanitize_areas(areas)
    store._write_sidecar(pid, meta)
    return pid


def location_fixture(frame_pid: str, door_pid: str, variant: int = 1) -> dict:
    """10 m location, room "a" (x −4, y −4, w 4, d 3 → world x −4…0,
    z −4…−1) with two placements of the frame prop — one on ``variant``, one
    on none — and the S door carrying the door prop."""
    return {
        "id": "loc",
        "map3d": {"plan_width_m": 10.0, "storey_height_m": 3.0,
                  "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]]},
        "rooms": [{"id": "a", "name": "A", "layout": {
            "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0,
            "surfaces": {"floor": "wood", "wall": "plaster"},
            # [1, 1] and [2, 1] metres from the min corner are world
            # (−3, −3) and (−2, −3).
            "props": [{"prop_id": frame_pid, "at": [1.0, 1.0],
                       "variant": variant},
                      {"prop_id": frame_pid, "at": [2.0, 1.0]}],
            "openings": [{"edge": 2, "at": 0.5, "type": "door",
                          "width_m": 1.0, "height_m": 2.1, "to": "outside",
                          "prop_id": door_pid}],
        }}],
    }


def prop_specs(sc: dict) -> dict:
    """The room-prop specs by their world anchor — placement order is not the
    fact under test here."""
    return {tuple(m["anchor"]): m for m in sc["models"]
            if m.get("role") == "prop" and not m.get("door")}


def scene_of(frame_pid: str, door_pid: str, variant: int = 1) -> dict:
    from app.core import scene_recipe
    return scene_recipe.compose_scene(
        location_fixture(frame_pid, door_pid, variant), plan_width_m=10.0)


def part2() -> None:
    # No Blender and no LOD threads: the three post-ingest hooks are stubbed
    # exactly as `scripts/smoke_props_slots.py` stubs them.
    store._auto_bake_vc = lambda *a, **k: None
    store._auto_retexture = lambda *a, **k: None
    store.request_low_tier = lambda *a, **k: None

    print("\n[5] a picture variant is a variant with a COPY of the mesh")
    pid = make_prop("Frame", frame_glb(), FRAME_AREAS)
    prim_file = store.model_gallery(pid, 0).find("full")
    # The `.areas.json` companion a split would leave beside the mesh.
    companion = store.areas_sidecar_path(prim_file)
    companion.write_text(json.dumps(
        {"areas": [{**a, "edges": []} for a in FRAME_AREAS],
         "mesh_layout": [], "run_at": "x"}), encoding="utf-8")
    store._source_file(pid, 0, create=True).write_bytes(b"\x89PNG-source")
    slots_before = store.get_prop(pid)["slots"]

    idx = store.add_picture_variant(pid, {"picture_1": {"image": IMG}}, "x")
    check("the new variant is index 1", idx == 1, str(idx))
    copy_gal = store.model_gallery(pid, 1)
    copy_file = copy_gal.find("full") if copy_gal else None
    check("a file under the new stem model-v2 is active",
          bool(copy_file) and copy_file.name.startswith("model-v2_"),
          str(copy_file))
    check("the copy is the primary's mesh byte for byte",
          bool(copy_file) and copy_file.read_bytes() == prim_file.read_bytes())
    check("the prop's slot list is unchanged",
          store.get_prop(pid)["slots"] == slots_before,
          str(store.get_prop(pid)["slots"]))
    copy_companion = store.areas_sidecar_path(copy_file)
    check("the .areas.json companion travelled with the mesh",
          copy_companion.exists()
          and copy_companion.read_text(encoding="utf-8")
          == companion.read_text(encoding="utf-8"))
    copy_img = store.source_path(pid, 1)
    check("…and so did the source image",
          bool(copy_img) and copy_img.read_bytes() == b"\x89PNG-source",
          str(copy_img))
    ref = store.read_model_sidecar(copy_file).get("copied_from") or {}
    check("copied_from names the primary's file",
          ref.get("file") == prim_file.name, str(ref))
    check("…and carries the source signature", bool(ref.get("signature")),
          str(ref))
    entries = store.list_variants(pid)
    check("the variant carries slot_values, label and stale False",
          entries[1]["slot_values"] == {"picture_1": {"image": IMG}}
          and entries[1]["label"] == "x"
          and entries[1]["stale"] is False, str(entries[1].get("slot_values")))
    check("the PRIMARY entry says nothing about pictures",
          entries[0]["slot_values"] == {} and entries[0]["label"] == ""
          and entries[0]["stale"] is False, str(entries[0].get("label")))
    named = store.add_picture_variant(pid, {"picture_1": {"image": IMG2}})
    check("a label the admin left out comes from the file name",
          store.list_variants(pid)[named]["label"] == "sunset",
          store.list_variants(pid)[named]["label"])
    glassy = store.add_picture_variant(pid, {"glass_1": {"preset": "glass"}})
    check("…and from the preset for a glass-only variant",
          store.list_variants(pid)[glassy]["label"] == "glass",
          store.list_variants(pid)[glassy]["label"])
    check("a character image is the second allowed URL form",
          store.set_variant_slot_values(
              pid, named, {"picture_1": {"image": CHAR_IMG}}) is True
          and store.list_variants(pid)[named]["slot_values"]
          == {"picture_1": {"image": CHAR_IMG}})

    print("\n[6] the values are checked — the area's kind decides the shape")
    # A prop of its own, so the cap of [7] cannot answer for the validation.
    pid6 = make_prop("Frame check", frame_glb(), FRAME_AREAS)
    store.add_picture_variant(pid6, {"picture_1": {"image": IMG}})
    before = (store._sidecar_path(pid6) or Path()).read_text(encoding="utf-8")
    count = len(store.list_variants(pid6))
    files = len(store.model_gallery(pid6, 1).files())
    for label, value in (
            ("an unknown area", {"nope": {"image": IMG}}),
            ("a foreign URL", {"picture_1": {"image": "https://x/y.png"}}),
            ("a path outside the two galleries",
             {"picture_1": {"image": "/foo/x.png"}}),
            ("a preset on a picture area", {"picture_1": {"preset": "glass"}}),
            ("an image on a pane", {"glass_1": {"image": IMG}}),
            ("a preset outside SLOT_PRESETS",
             {"glass_1": {"preset": "mirror"}}),
            ("a string instead of an object", "picture_1")):
        try:
            store.set_variant_slot_values(pid6, 1, value)
            check(f"set refused: {label}", False, "no ValueError")
        except ValueError as exc:
            after = (store._sidecar_path(pid6) or Path()).read_text(
                encoding="utf-8")
            check(f"set refused: {label}", after == before, str(exc)[:60])
        try:
            store.add_picture_variant(pid6, value)
            check(f"add refused: {label}", False, "no ValueError")
        except ValueError:
            check(f"add refused: {label}",
                  len(store.list_variants(pid6)) == count
                  and len(store.model_gallery(pid6, 1).files()) == files)

    print("\n[7] the variant cap applies to picture variants too")
    check("the cap is 4 by default", store.variant_max() == 4,
          str(store.variant_max()))
    check("…and the frame prop now has exactly four variants",
          len(store.list_variants(pid)) == 4,
          str(len(store.list_variants(pid))))
    try:
        store.add_picture_variant(pid, {"picture_1": {"image": IMG}})
        check("the fifth picture variant is refused", False, "no ValueError")
    except ValueError as exc:
        check("the fifth picture variant is refused",
              len(store.list_variants(pid)) == 4, str(exc)[:60])

    print("\n[8] recipe: slots = area_defaults ∪ the resolved variant's values")
    door_pid = make_prop("Glass door", door_glb(), GLASS_AREAS)
    sc = scene_of(pid, door_pid)
    specs = prop_specs(sc)
    doors = [m for m in sc["models"] if m.get("door")]
    check("both placements and one door prop are in the scene",
          len(specs) == 2 and len(doors) == 1, f"{len(specs)}/{len(doors)}")
    check("the placement on variant 1 shows its picture",
          specs.get((-3.0, -3.0), {}).get("slots")
          == {"picture_1": {"image": IMG}},
          str(specs.get((-3.0, -3.0), {}).get("slots")))
    check("a placement without a variant says nothing (no key)",
          "slots" not in specs.get((-2.0, -3.0), {}),
          str(specs.get((-2.0, -3.0), {}).get("slots")))
    check("a door prop without defaults says nothing either",
          "slots" not in doors[0], str(doors[0].get("slots")))

    store.update_prop(pid, {"area_defaults": {"glass_1": {"preset": "glass"}}})
    store.update_prop(door_pid,
                      {"area_defaults": {"glass_1": {"preset": "glass"}}})
    sc = scene_of(pid, door_pid)
    specs = prop_specs(sc)
    doors = [m for m in sc["models"] if m.get("door")]
    check("the default and the picture are merged on the variant placement",
          specs.get((-3.0, -3.0), {}).get("slots")
          == {"glass_1": {"preset": "glass"}, "picture_1": {"image": IMG}},
          str(specs.get((-3.0, -3.0), {}).get("slots")))
    check("the placement without a variant gets the defaults alone",
          specs.get((-2.0, -3.0), {}).get("slots")
          == {"glass_1": {"preset": "glass"}},
          str(specs.get((-2.0, -3.0), {}).get("slots")))
    check("the door prop gets its pane from the prop defaults",
          doors[0].get("slots") == {"glass_1": {"preset": "glass"}},
          str(doors[0].get("slots")))
    # Four active variants, so `variant: 5` is position 5 mod 4 = 1 — the
    # first picture variant again, never a 404.
    wrapped = prop_specs(scene_of(pid, door_pid, variant=5))
    check("an out-of-range variant wraps to position 1",
          wrapped.get((-3.0, -3.0), {}).get("slots")
          == {"glass_1": {"preset": "glass"}, "picture_1": {"image": IMG}},
          str(wrapped.get((-3.0, -3.0), {}).get("slots")))

    print("\n[9] a swapped picture moves the signature")
    sig_before = store.get_prop(pid)["model_signature"]
    scene_before = scene_of(pid, door_pid)["signature"]
    store.set_variant_slot_values(pid, 1, {"picture_1": {"image": IMG2}})
    sig_after = store.get_prop(pid)["model_signature"]
    check("the prop signature moves with the picture", sig_before != sig_after,
          f"{sig_before} -> {sig_after}")
    check("…and so does the scene signature",
          scene_of(pid, door_pid)["signature"] != scene_before)
    store.update_prop(pid, {"area_defaults": {}})
    check("a changed area_defaults moves it too",
          store.get_prop(pid)["model_signature"] != sig_after,
          store.get_prop(pid)["model_signature"])

    print("\n[10] stale + re-copy")
    store.save_uploaded_glb(pid, frame_glb(extra="trim"))
    check("a new primary mesh makes the copy stale",
          store.list_variants(pid)[1]["stale"] is True,
          str(store.list_variants(pid)[1]["stale"]))
    check("…and the primary is never stale itself",
          store.list_variants(pid)[0]["stale"] is False)
    files_before = len(store.model_gallery(pid, 1).files())
    check("recopy answers True", store.recopy_variant_mesh(pid, 1) is True)
    entry = store.list_variants(pid)[1]
    check("…the copy is fresh again", entry["stale"] is False,
          str(entry["stale"]))
    check("…the values are kept",
          entry["slot_values"] == {"picture_1": {"image": IMG2}},
          str(entry["slot_values"]))
    check("…the mesh is the NEW primary's bytes",
          store.model_gallery(pid, 1).find("full").read_bytes()
          == store.model_gallery(pid, 0).find("full").read_bytes())
    check("…and the old copy stays in the gallery as history",
          len(store.model_gallery(pid, 1).files()) == files_before + 1,
          str(len(store.model_gallery(pid, 1).files())))
    try:
        store.recopy_variant_mesh(pid, 0)
        check("re-copying the PRIMARY onto itself is refused", False,
              "no ValueError")
    except ValueError as exc:
        check("re-copying the PRIMARY onto itself is refused", True,
              str(exc)[:60])

    print("\n[11] the label rule (R10), an empty assignment, and pruning")
    # R10 — the label is three-valued. Variant 1 is named "sunset" right now
    # (derived when it was hung), so:
    store.set_variant_slot_values(pid, 1, {"picture_1": {"image": IMG2}}, "Wall")
    check("a text is stored verbatim",
          store.list_variants(pid)[1]["label"] == "Wall",
          store.list_variants(pid)[1]["label"])
    store.set_variant_slot_values(pid, 1, {"picture_1": {"image": IMG}})
    check("label None (the body said nothing) KEEPS the stored name",
          store.list_variants(pid)[1]["label"] == "Wall",
          store.list_variants(pid)[1]["label"])
    store.set_variant_slot_values(pid, 1, {"picture_1": {"image": IMG}}, "")
    check("label '' re-derives it from the file names",
          store.list_variants(pid)[1]["label"] == "x",
          store.list_variants(pid)[1]["label"])
    try:
        store.add_picture_variant(pid, {})
        check("an EMPTY assignment is not a picture variant", False,
              "no ValueError")
    except ValueError as exc:
        check("an EMPTY assignment is not a picture variant", True,
              str(exc)[:60])

    # A generating variant is refused in the core, not only in the route.
    real_gen = store.variant_generating
    store.variant_generating = lambda *a, **k: True
    try:
        check("recopy is refused while the variant generates",
              store.recopy_variant_mesh(pid, 1) is False)
    finally:
        store.variant_generating = real_gen

    # PRUNING: an area that leaves the mesh takes BOTH halves of `slots` with
    # it — the prop-wide default and every variant's value — and leaves the
    # label alone. Driven through `_reconcile_areas`, the path a re-selected
    # or re-uploaded mesh takes: the new mesh names `slot_picture_1` only, so
    # `glass_1` is gone.
    store.set_variant_slot_values(pid, 1, {"picture_1": {"image": IMG},
                                           "glass_1": {"preset": "glass"}},
                                  "Both")
    store.update_prop(pid, {"area_defaults": {"glass_1": {"preset": "glass"}}})
    only_picture = glb({"asset": {"version": "2.0"},
                        "materials": [{"name": "atlas"},
                                      {"name": "slot_picture_1"}],
                        "meshes": [{"primitives": [
                            {"attributes": {"POSITION": 0}}]}]})
    store.save_uploaded_glb(pid, only_picture)
    rec = store.get_prop(pid)
    entry = store.list_variants(pid)[1]
    check("the vanished area is gone from the prop's areas",
          [a["id"] for a in rec["areas"]] == ["picture_1"],
          str([a["id"] for a in rec["areas"]]))
    check("…from the prop-wide defaults", rec["area_defaults"] == {},
          str(rec["area_defaults"]))
    check("…and from the variant's slot_values",
          entry["slot_values"] == {"picture_1": {"image": IMG}},
          str(entry["slot_values"]))
    check("…while the label the admin gave it stands",
          entry["label"] == "Both", entry["label"])
    check("the spec carries only the surviving area",
          prop_specs(scene_of(pid, door_pid)).get((-3.0, -3.0), {}).get("slots")
          == {"picture_1": {"image": IMG}},
          str(prop_specs(scene_of(pid, door_pid)).get((-3.0, -3.0),
                                                      {}).get("slots")))

    # A primary variant with NO active full mesh has nothing to compare
    # against — the tab must not offer a re-copy that can only fail.
    prim = store.model_gallery(pid, 0)
    prim.select("", "full")
    check("no primary mesh -> nothing is stale",
          all(v["stale"] is False for v in store.list_variants(pid)),
          str([v["stale"] for v in store.list_variants(pid)]))


def main() -> int:
    print("[1] sidecar round-trip: key_areas / areas / area_defaults")
    pid = store.create_prop(name="Picture frame", category="decor",
                            key_areas=["glass", "picture", "picture"])["id"]
    meta = store.read_sidecar(pid)
    check("key_areas stored de-duplicated in kind order",
          meta.get("key_areas") == ["picture", "glass"],
          str(meta.get("key_areas")))
    rec = store.get_prop(pid)
    check("the record carries key_areas",
          rec.get("key_areas") == ["picture", "glass"], str(rec.get("key_areas")))
    check("no run yet: areas == []", rec.get("areas") == [], str(rec.get("areas")))
    check("no run yet: area_defaults == {}", rec.get("area_defaults") == {},
          str(rec.get("area_defaults")))
    try:
        store.create_prop(name="Bad", key_areas=["neon"])
        check("an unknown key kind is refused", False, "no ValueError")
    except ValueError as exc:
        check("an unknown key kind is refused", True, str(exc)[:60])
    out = store.update_prop(pid, {"key_areas": ["glass"]})
    check("R7: key_areas is patchable", out.get("key_areas") == ["glass"],
          str(out.get("key_areas")))
    out = store.update_prop(pid, {"key_areas": []})
    check("R7: an empty list removes the key",
          "key_areas" not in out and store.get_prop(pid)["key_areas"] == [],
          str(out.get("key_areas")))
    before = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
    try:
        store.update_prop(pid, {"key_areas": ["neon"]})
        check("R7: an unknown kind is refused", False, "no ValueError")
    except ValueError as exc:
        after = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
        check("R7: an unknown kind is refused, nothing written", after == before,
              str(exc)[:50])
    store.update_prop(pid, {"key_areas": ["picture", "glass"]})
    meta = store.read_sidecar(pid)
    meta[store.AREAS_KEY] = store.sanitize_areas(AREAS)
    store._write_sidecar(pid, meta)
    got = store.get_prop(pid)["areas"]
    check("areas read back as written", got == AREAS, str(got))

    print("\n[2] area_defaults are checked against the areas")
    out = store.update_prop(pid, {"area_defaults": {"glass_1": {"preset": "glass"}}})
    check("a default on an existing area is stored",
          out.get("area_defaults") == {"glass_1": {"preset": "glass"}},
          str(out.get("area_defaults")))
    check("…and on the record",
          store.get_prop(pid)["area_defaults"] == {"glass_1": {"preset": "glass"}})
    before = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
    for label, value in (("an unknown area", {"nope": {"preset": "glass"}}),
                         ("a preset outside SLOT_PRESETS",
                          {"glass_1": {"preset": "mirror"}}),
                         ("a default without preset", {"glass_1": {}}),
                         ("a string instead of an object", "glass")):
        try:
            store.update_prop(pid, {"area_defaults": value})
            check(f"refused: {label}", False, "no ValueError")
        except ValueError as exc:
            after = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
            check(f"refused: {label}", after == before, str(exc)[:60])

    print("\n[3] detect_slots: the prefix rule for glass")
    got = store.detect_slots(["slot_glass_1", "slot_picture_2"])
    check("slot_glass_1 -> material, slot_picture_2 -> image",
          got == [{"name": "glass_1", "kind": "material"},
                  {"name": "picture_2", "kind": "image"}], str(got))
    check("slot_glass stays a material slot",
          store.detect_slots(["slot_glass"]) == [{"name": "glass", "kind": "material"}])
    check("slot_glassy is an image slot (the prefix is a whole token)",
          store.detect_slots(["slot_glassy"]) == [{"name": "glassy", "kind": "image"}],
          str(store.detect_slots(["slot_glassy"])))

    print("\n[4] compose_prompt appends the key-area fragments")
    pic = config.KEY_AREA_PROMPTS["picture"].strip(" ,")
    gl = config.KEY_AREA_PROMPTS["glass"].strip(" ,")
    pic_neg = config.KEY_AREA_NEGATIVES["picture"]
    gl_neg = config.KEY_AREA_NEGATIVES["glass"]
    check("the picture negative is the spec text",
          pic_neg == "painting, artwork, photo, poster, landscape in frame", pic_neg)
    check("the glass negative is the spec text",
          gl_neg == "transparent glass, reflections", gl_neg)
    plain = store.compose_prompt("a wooden frame", FakeBackend())
    check("without key_areas: no picture fragment",
          pic not in plain["prompt"] and pic_neg not in plain["negative"])
    check("without key_areas: no glass fragment",
          gl not in plain["prompt"] and gl_neg not in plain["negative"])
    with_pic = store.compose_prompt("a wooden frame", FakeBackend(),
                                    key_areas=["picture"])
    check("picture: fragment in the prompt", pic in with_pic["prompt"],
          with_pic["prompt"][-90:])
    check("picture: negative addition", pic_neg in with_pic["negative"],
          with_pic["negative"])
    check("picture: no glass text",
          gl not in with_pic["prompt"] and gl_neg not in with_pic["negative"])
    check("picture: the subject is still woven in",
          "wooden frame" in with_pic["prompt"])
    with_gl = store.compose_prompt("a door", FakeBackend(), key_areas=["glass"])
    check("glass: fragment in the prompt", gl in with_gl["prompt"])
    check("glass: negative addition", gl_neg in with_gl["negative"])
    check("glass: no picture text",
          pic not in with_gl["prompt"] and pic_neg not in with_gl["negative"])
    both = store.compose_prompt("a door", FakeBackend(),
                                key_areas=["glass", "picture"])
    check("both: picture fragment before glass",
          0 <= both["prompt"].find(pic) < both["prompt"].find(gl),
          both["prompt"][-200:])
    check("both: both negatives",
          pic_neg in both["negative"] and gl_neg in both["negative"])
    check("style is returned RAW (no fragment)",
          pic not in both["style"] and gl not in both["style"])

    part2()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
