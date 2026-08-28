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
[2b] THE DOOR LEAF IS A KIND WITHOUT A COLOUR (spec § 6, ruling R9)
---------------------------------------------------------------------------
`COLOUR_KINDS` = picture_areas.KINDS = (picture, glass); `AREA_KINDS` =
COLOUR_KINDS + ("leaf",). Hand-derived consequences:

    sanitize_key_areas(["leaf", "picture"])  -> ["picture", "leaf"]  (kind order)
    apply_key_areas("p", "n", ["leaf"])      -> ("p", "n")  (no fragment)
    sanitize_areas([... + {"id": "leaf", "kind": "leaf", size_m [0.8, 2.0],
        normal [0,0,1], source "auto", faces 12}])  -> round-trips
    {"id": "leaf", "kind": "picture"}        -> ValueError (id spells its kind)
    {"id": "leaf_1", "kind": "leaf"}         -> ValueError (no numbering)
    area_defaults {"leaf": {"preset": "glass"}} -> ValueError (a node, not
        a surface), sidecar byte-identical
    slot_values {"leaf": {"preset": "glass"}}   -> ValueError, same reason
    rename_area_kind(pid, "picture_1", "leaf")  -> ValueError
    rename_area_kind(pid, "leaf", "glass")      -> ValueError
    sanitize_leaf_bbox({"min": [0.1, 0.1, -0.02], "max": [0.9, 2.1, 0]})
        -> {"min": [0.1, 0.1, -0.02], "max": [0.9, 2.1, 0.0]}
    sanitize_leaf_bbox({"min": [1, 0, 0], "max": [0, 0, 0]}) -> ValueError
    sanitize_leaf_bbox(None) -> None
    a sidecar `leaf_bbox` shows on the full record and in areas_info;
    without one the record has NO `leaf_bbox` key and areas_info says None
    is_door_prop: category "Door" -> True; tags [" door "] -> True;
        category "decor", tags ["wood"] -> False

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
        (+ the stubbed split of FRAME2 written onto the new FILE — v2 E1: a
        fresh upload names no area until a run writes them)
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

---------------------------------------------------------------------------
[12] A GALLERY CLICK KEEPS EVERY HUNG PICTURE (ruling R15)
---------------------------------------------------------------------------
The two halves of a spec's `slots` do NOT share a fate. `area_defaults`
describe the PRIMARY mesh, so they follow whatever file is selected for it. A
variant's `slot_values` describe THAT VARIANT'S OWN copied mesh, which still
carries `slot_picture_1` / `slot_glass_1` while the admin clicks through the
primary's gallery — so a select must not touch them. Hand-derived, with the
frame prop of [5] (areas picture_1 + glass_1, defaults `{glass_1: glass}`, one
picture variant showing both):

    select the PRE-SPLIT file (materials: atlas)
        -> areas []            (the file names no slot material)
        -> area_defaults {}    (they described the primary)
        -> slot_values {picture_1: IMG, glass_1: glass}   UNCHANGED
    select the split file back (its `.areas.json` states the list)
        -> areas [picture_1, glass_1]
        -> slot_values still {picture_1: IMG, glass_1: glass}

The re-copy in [11] is the counterpart: THERE the variant takes the primary's
mesh, so there its values are re-read against the prop's current areas.

---------------------------------------------------------------------------
[13] A RENAME DROPS BOTH HALVES OF THE DEAD ID
---------------------------------------------------------------------------
`rename_area_kind(pid, "glass_1", "picture")` on the frame of [12]: picture_1
is taken, so the target id is `picture_2` and the areas read
[(picture_1, picture), (picture_2, picture)].

A rename is ALWAYS a kind change, so nothing stored under the old id can
survive it — a glass preset on a picture panel is the very value both
sanitizers refuse, and moving it onto `picture_2` would only move the invalid
value. Hence `area_defaults == {}` and `slot_values == {picture_1: IMG}`; the
`label` stands. The symptom this closes: the dialog renders existing areas
only, so a stale `glass_1` key could never be removed by hand and every save
of that variant answered 400 — the smoke saves it again to prove it passes.

---------------------------------------------------------------------------
[14] A FAILED RUN SAYS SO AND DELETES NOTHING
---------------------------------------------------------------------------
`_areas_after_landing` with `detect_areas` raising `BlenderUnavailable`
("busy") — the LOAD condition, not a statement about the prop:

    areas          []      (the freshly landed mesh really is unsplit)
    area_defaults  {glass_1: glass}   KEPT
    slot_values    {picture_1: IMG}   KEPT
    areas_info     error "…busy…", warning ""

Both halves wait for the next SUCCESSFUL run to prune them. And the note a
run that WORKED leaves when a door has no cuttable leaf (`NO_LEAF_NOTE`) is a
`warning`, never an `error` — two file-sidecar keys since v2 (`areas_error`
/ `areas_warning`), so the tab cannot report "Last automatic run failed" over
a working detection.

---------------------------------------------------------------------------
PART 3 — AREAS, LEAF AND ORIENTATION BELONG TO THE MODEL FILE
          (spec-bild-props-v2.md E1; still no Blender — the run is stubbed)
---------------------------------------------------------------------------
Every variant is its own img2mesh generation (measured 2026-08-28: variant
`model-v3` of a real door has other axes and no leaf node), so `areas`,
`leaf_bbox` and `rotation` live on the FULL file's sidecar, `area_defaults`
on the VARIANT entry, and nothing of the kind on the prop any more. The
record publishes them per `variant_tiers[i]`; `key_areas` (a wish for the
next generation) stays prop-wide (ruling V2).

Parts 1 and 2 above were rewritten to that model: `make_prop` writes the
areas onto the primary's FILE (`set_file_areas`), defaults go through
`set_variant_area_defaults(pid, i, …)`, a prop patch naming `area_defaults`
is refused with the variant route, and the record's `areas` / `leaf_bbox` /
`rotation` / `area_defaults` are read off `variant_tiers[i]`. Consequences
that CHANGED a hand-derived expectation:

    [8]  defaults are per VARIANT: a placement on variant 1 merges variant
         1's OWN defaults, so the smoke sets them on variant 1 too; a
         picture variant created AFTER the defaults were set copies them
         from the source variant (`_COPIED_ON_ADD`) — checked in [12]
    [11] a fresh upload without a split NAMES NO AREA (areas [] on its
         file; the material-name heuristic is gone — E6 `adopt` is its
         successor); the smoke then hands the file a stubbed split result
         naming picture_1 only, and the re-copy prunes the variant's values
         against THAT file's areas
    [13] a rename on variant 0 touches variant 0's values only: the picture
         variant hangs on its OWN copy, which still carries glass_1, so its
         slot_values / area_defaults STAND and a save of them still passes
         (validated against ITS file); a rename ON the variant prunes them

[15] EVERY VARIANT CARRIES ITS OWN — Blender stubbed: `runner.run` answers
  the store with a fixed result (areas [glass_1, manual, 2 faces, size_m
  [0.5, 0.5], normal [0, 0, 1], 4 edges], mesh_layout [{m, 8}]) and a GLB
  naming [atlas, slot_glass_1]; `refine.unavailable_reason` "", the slot
  gate open, `validate_static_glb` ok. Prop "Two frames" (category decor,
  no key_areas): variant 0 = frame_glb() + file areas [picture_1] (the
  split is Blender's), variant 1 = `add_variant` + upload of a plain GLB
  (materials [atlas]) → `areas_info(pid, 1)["areas"] == []`, variant 0's
  [picture_1].

    set_rotation(pid, {"y": 90}, variant=1)
        -> {variant 1, filename <v1 full>, rotation {0, 90, 0}}
        -> areas_info(pid, 1)["rotation"] == {0, 90, 0}; (pid, 0) -> 0
        -> the v1 full file's sidecar carries rotation; the prop sidecar
           carries NO rotation key
    detect_areas(pid, variant=1, mode="manual", faces=[6, 7], kind="glass")
        -> returns [glass_1]; variant 1's gallery has 2 files, the active one
           is the split (source "areas", areas_mode manual, source_file =
           the upload) and INHERITS the upload's rotation y 90 (`_land_split`
           copies it — the split is the same mesh)
        -> areas_info(pid, 1): areas [glass_1] with the 4 edges, last_run set
        -> areas_info(pid, 0): STILL [picture_1] (untouched)
        -> the prop sidecar has none of areas/leaf_bbox/rotation/area_defaults
    set_variant_area_defaults(pid, 1, {"glass_1": {"preset": "glass"}})
        -> list_variants(pid)[1]["area_defaults"] == that
    set_variant_area_defaults(pid, 0, {"glass_1": …})
        -> ValueError (variant 0's file has no glass_1), sidecar byte-identical
    get_prop(pid)
        -> no prop-level areas / leaf_bbox / rotation / area_defaults
        -> variant_tiers[1]: rotation y 90, areas [glass_1], area_defaults
        -> variant_tiers[0]: rotation y 0, areas [picture_1], area_defaults {}
    build_low_tier(pid, ratio=0.5, variant=1)  (refine.build_static_lod
      stubbed: the source bytes back, tris 4 / 8)
        -> the low file's sidecar: inherits_from == <v1 full name>,
           rotation y 90, areas [glass_1]
        -> file_areas(<low>) == the full file's values
    set_rotation(pid, {"y": 180}, variant=1)
        -> the full file 180, the low file's copy 180, file_areas(low) 180
        -> bake_surfaces was asked for (pid, 1) — the lattice is per file
        -> model_signature moved (a turned variant invalidates its scenes)

[16] THE LANDING HOOK RUNS FOR EVERY VARIANT — prop with key_areas
  ["picture"], `detect_areas` monkeypatched to record its kwargs:
    save_uploaded_glb(pid, glb, variant=1)  -> recorded variant == 1, mode auto
    _generate(pid, …, mesh_only=True, variant=1) with a fake mesh service
                                           -> recorded variant == 1

[17] THE ORIENTATION IS THE FILE'S — AND A NEW FILE STARTS FROM THE ONE IT
  REPLACES: on "Two frames" variant 1 (rotation 180) a further upload lands
  a file whose sidecar rotation is 180 (the dial the admin set is the
  default for the variant's next file; a re-generation with other axes is
  re-dialled), `areas_info(pid, 1)["rotation"]["y"] == 180`, while variant
  0 stays 0.

---------------------------------------------------------------------------
PART 4 — HISTORY = ORIGIN + CURRENT STATE, AND THE GALLERY SAYS WHAT A FILE IS
          (spec-bild-props-v2.md E4; Blender stubbed as in part 3)
---------------------------------------------------------------------------
Measured symptom (befunde-bild-props-2026-08-28 § 8): every detect/draw/
rename/delete click landed ANOTHER gallery file — 8 full files for one
variant in 10 minutes, and the row said nothing but a minute and a backend.

[18] A SPLIT REPLACES ITS PREDECESSOR. Prop "History frame" (decor, no
  key_areas — the landing hook stays shut), one uploaded `frame_glb()`; the
  stub of [15] answers every run with glass_1 on SPLIT_GLB. Hand-derived
  from the rule "the previous split of the SAME origin goes, the origin
  stays":

    upload                  -> gallery [O]                       1 file
    detect_areas #1  O  -> S1   -> gallery {O, S1}               2 files
    detect_areas #2  S1 -> S2   -> gallery {O, S2}               2 files
        S1's .glb, its .json sidecar and its .areas.json companion are GONE
        S2's `source_file` is O (the ORIGIN, not S1 — a split of a split
        carries the origin forward, so the chain never grows a third link)
    detect_areas #3  S2 -> S3   -> gallery {O, S3}               2 files

  The origin file exists after all three runs, and its sidecar still says
  `source: upload` — a run never rewrites what it worked on.

[19] A RENAME GOES THROUGH THE SAME LANDING. `rename_area_kind(pid,
  "glass_1", "picture")` on the state of [18] (areas [glass_1], so the free
  target id is `picture_1`):

    -> gallery {O, S4}          still 2 files, S3 gone with its companions
    -> S4's sidecar: source areas, areas_mode "rename", source_file O,
       areas_area "picture_1"
    -> areas_info(pid)["areas"] ids == ["picture_1"]

[20] A SPLIT SELECTED FOR ANOTHER TIER IS NOT DELETED. `select_model(pid,
  S4, "low")` makes S4 the LOW file as well; the next run therefore lands S5
  for the full tier and must LEAVE S4:

    -> gallery {O, S4, S5}      3 files
    -> S4 still selected for "low", S5 for "full"

  (`_drop_stale_low` does not take it either: it removes a mesh THIS store
  reduced itself — sidecar `source: lod` — and S4 is a split.)

[21] THE ROW SAYS WHAT THE FILE IS. `list_models` publishes `label_parts`
  per file — the grouped view the gallery's second line is built from:

    S5   {source "areas", areas_mode "manual", areas_area "",
          area_ids ["glass_1"], source_file O, copied_from {}, inherits_from ""}
    O    {source "upload", areas_mode "", area_ids [], source_file "", …}

  and on the picture-variant copy of a second prop:

    copy {source "variant-copy", copied_from {"file": <primary file>,
          "variant": 0}}
"""
import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-areas-smoke-"))

from app.core import paths  # noqa: E402

# `paths.init` IS the selection (project rule: no env config) — the throwaway
# storage needs nothing else, and an env var here would only be a second,
# silently disagreeing source.
paths.init(WORLD)

from app.core import config  # noqa: E402
from app.core import props as store  # noqa: E402

# No Blender and no LOD threads: the three post-ingest hooks are stubbed
# exactly as `scripts/smoke_props_slots.py` stubs them — for every part, the
# file-level areas of Part 1 need a landed mesh as well.
store._auto_bake_vc = lambda *a, **k: None
store._auto_retexture = lambda *a, **k: None
store.request_low_tier = lambda *a, **k: None

FAILURES = []


def sidecar_text(pid: str) -> str:
    return (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")


def full_file(pid: str, variant=None) -> Path:
    """The ACTIVE full-tier file of one variant (the file the areas live on)."""
    return store.model_gallery(pid, variant).find(store.DEFAULT_TIER, fallback=False)


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
    """A prop with a landed mesh and hand-written areas on that mesh's FILE
    sidecar — the split itself is Blender's job
    (scripts/smoke_picture_areas_blender.py)."""
    pid = store.create_prop(name=name, category="decor")["id"]
    store.save_uploaded_glb(pid, blob)
    store.set_file_areas(full_file(pid), areas=areas)
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

    # Defaults are PER VARIANT (E1): variant 0's for the bare placement, the
    # door's primary for the door spec, and variant 1's own for the picture
    # placement — the copy of [5] predates them, so they are set there too.
    store.set_variant_area_defaults(pid, 0, {"glass_1": {"preset": "glass"}})
    store.set_variant_area_defaults(pid, 1, {"glass_1": {"preset": "glass"}})
    store.set_variant_area_defaults(door_pid, 0, {"glass_1": {"preset": "glass"}})
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
    store.set_variant_area_defaults(pid, 0, {})
    sig_defaults = store.get_prop(pid)["model_signature"]
    check("a changed area_defaults moves it too", sig_defaults != sig_after,
          sig_defaults)
    store.set_rotation(pid, {"y": 90}, variant=1)
    check("…and so does a turned variant (its fix is part of the scene)",
          store.get_prop(pid)["model_signature"] != sig_defaults,
          store.get_prop(pid)["model_signature"])
    store.set_rotation(pid, {"y": 0}, variant=1)

    print("\n[10] stale + re-copy")
    store.save_uploaded_glb(pid, frame_glb(extra="trim"))
    # …and the (stubbed) split of the new frame — its areas are the new
    # FILE's (E1); a fresh upload names none until a run writes them.
    store.set_file_areas(full_file(pid), areas=FRAME_AREAS)
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

    # PRUNING, R15 per variant — the two halves of `slots` do NOT share a
    # fate. A landing on variant 0 (`_reconcile_areas(pid, 0)`) reads THAT
    # variant's active mesh, so it prunes what describes it: variant 0's
    # `area_defaults`. Variant 1 hangs on its OWN copy, which still carries
    # `slot_glass_1`, so its values stay — and the label, which is a name and
    # no description at all, stays as it always did.
    store.set_variant_slot_values(pid, 1, {"picture_1": {"image": IMG},
                                           "glass_1": {"preset": "glass"}},
                                  "Both")
    store.set_variant_area_defaults(pid, 0, {"glass_1": {"preset": "glass"}})
    only_picture = glb({"asset": {"version": "2.0"},
                        "materials": [{"name": "atlas"},
                                      {"name": "slot_picture_1"}],
                        "meshes": [{"primitives": [
                            {"attributes": {"POSITION": 0}}]}]})
    store.save_uploaded_glb(pid, only_picture)
    rec = store.get_prop(pid)
    check("a fresh upload without a split names NO area on its file",
          rec["variant_tiers"][0]["areas"] == []
          and store.read_model_sidecar(full_file(pid)).get("areas") == [],
          str(rec["variant_tiers"][0]["areas"]))
    # …and a (stubbed) split result naming picture_1 only on that file:
    store.set_file_areas(full_file(pid), areas=[FRAME_AREAS[0]])
    store._reconcile_areas(pid, 0)
    rec = store.get_prop(pid)
    entry = store.list_variants(pid)[1]
    check("the vanished area is gone from variant 0's areas",
          [a["id"] for a in rec["variant_tiers"][0]["areas"]] == ["picture_1"],
          str([a["id"] for a in rec["variant_tiers"][0]["areas"]]))
    check("…from variant 0's defaults", rec["variant_tiers"][0]["area_defaults"] == {},
          str(rec["variant_tiers"][0]["area_defaults"]))
    check("…but NOT from the variant's slot_values (R15)",
          entry["slot_values"] == {"picture_1": {"image": IMG},
                                   "glass_1": {"preset": "glass"}},
          str(entry["slot_values"]))
    check("…while the label the admin gave it stands",
          entry["label"] == "Both", entry["label"])
    check("the spec still carries what the variant's own mesh shows",
          prop_specs(scene_of(pid, door_pid)).get((-3.0, -3.0), {}).get("slots")
          == {"picture_1": {"image": IMG}, "glass_1": {"preset": "glass"}},
          str(prop_specs(scene_of(pid, door_pid)).get((-3.0, -3.0),
                                                      {}).get("slots")))
    # A RE-COPY is the moment the variant takes the primary's mesh — and the
    # primary FILE's areas with it (`_copy_variant_mesh` copies the sidecar
    # fields), so THERE its values are re-read against them: `glass_1`
    # describes nothing on the new copy and goes; the picture stays.
    check("re-copy answers True", store.recopy_variant_mesh(pid, 1) is True)
    entry = store.list_variants(pid)[1]
    check("…the copy carries the primary file's areas",
          [a["id"] for a in store.file_areas(full_file(pid, 1))["areas"]] == ["picture_1"],
          str(store.file_areas(full_file(pid, 1))["areas"]))
    check("…and prunes THIS variant's values to them",
          entry["slot_values"] == {"picture_1": {"image": IMG}}
          and entry["area_defaults"] == {},
          str((entry["slot_values"], entry["area_defaults"])))
    check("…without touching the label", entry["label"] == "Both",
          entry["label"])

    # A primary variant with NO active full mesh has nothing to compare
    # against — the tab must not offer a re-copy that can only fail.
    prim = store.model_gallery(pid, 0)
    prim.select("", "full")
    check("no primary mesh -> nothing is stale",
          all(v["stale"] is False for v in store.list_variants(pid)),
          str([v["stale"] for v in store.list_variants(pid)]))

    print("\n[12] a GALLERY CLICK keeps every hung picture (R15)")
    pid12 = make_prop("Gallery frame", frame_glb(), FRAME_AREAS)
    split_file = store.model_gallery(pid12, 0).find("full")
    store.areas_sidecar_path(split_file).write_text(json.dumps(
        {"areas": [{**a, "edges": []} for a in FRAME_AREAS],
         "mesh_layout": [], "run_at": "x"}), encoding="utf-8")
    store._source_file(pid12, 0, create=True).write_bytes(b"\x89PNG-source")
    store.set_variant_area_defaults(pid12, 0, {"glass_1": {"preset": "glass"}})
    v12 = store.add_picture_variant(
        pid12, {"picture_1": {"image": IMG}, "glass_1": {"preset": "glass"}},
        "Sunset")
    check("a picture variant copies the source variant's area_defaults",
          store.list_variants(pid12)[v12]["area_defaults"]
          == {"glass_1": {"preset": "glass"}},
          str(store.list_variants(pid12)[v12]["area_defaults"]))
    check("…and its file carries the primary file's areas",
          [a["id"] for a in store.file_areas(full_file(pid12, v12))["areas"]]
          == ["picture_1", "glass_1"])
    # The admin selects the PRE-SPLIT file — one that names no slot material.
    plain = glb({"asset": {"version": "2.0"}, "materials": [{"name": "atlas"}],
                 "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]})
    store.save_uploaded_glb(pid12, plain)
    plain_file = store.model_path(pid12)
    store.select_model(pid12, plain_file.name)
    t0 = store.get_prop(pid12)["variant_tiers"][0]
    check("the pre-split file names no area", t0["areas"] == [], str(t0["areas"]))
    check("variant 0's defaults follow ITS active mesh and go",
          t0["area_defaults"] == {}, str(t0["area_defaults"]))
    check("…but the picture variant still hangs its picture AND its pane",
          store.list_variants(pid12)[v12]["slot_values"]
          == {"picture_1": {"image": IMG}, "glass_1": {"preset": "glass"}}
          and store.list_variants(pid12)[v12]["area_defaults"]
          == {"glass_1": {"preset": "glass"}},
          str(store.list_variants(pid12)[v12]["slot_values"]))
    # …and back: the split file carries its own list on its sidecar.
    store.select_model(pid12, split_file.name)
    check("selecting the split file back restores the areas",
          [a["id"] for a in store.get_prop(pid12)["variant_tiers"][0]["areas"]]
          == ["picture_1", "glass_1"],
          str([a["id"] for a in store.get_prop(pid12)["variant_tiers"][0]["areas"]]))
    check("…and the assignment came through the round trip untouched",
          store.list_variants(pid12)[v12]["slot_values"]
          == {"picture_1": {"image": IMG}, "glass_1": {"preset": "glass"}},
          str(store.list_variants(pid12)[v12]["slot_values"]))

    print("\n[13] a RENAME drops both halves of the dead id — on THAT variant")
    pid13 = make_prop("Rename frame", frame_glb(), FRAME_AREAS)
    store._source_file(pid13, 0, create=True).write_bytes(b"\x89PNG-source")
    store.set_variant_area_defaults(pid13, 0, {"glass_1": {"preset": "glass"}})
    v13 = store.add_picture_variant(
        pid13, {"picture_1": {"image": IMG}, "glass_1": {"preset": "glass"}},
        "Both")
    # glass_1 becomes a PICTURE area: picture_1 is taken, so it is picture_2.
    renamed = store.rename_area_kind(pid13, "glass_1", "picture")
    check("glass_1 -> picture_2 (the next free number of the target kind)",
          [(a["id"], a["kind"]) for a in renamed]
          == [("picture_1", "picture"), ("picture_2", "picture")],
          str([(a["id"], a["kind"]) for a in renamed]))
    check("the glass preset is NOT moved onto the renamed picture panel",
          store.get_prop(pid13)["variant_tiers"][0]["area_defaults"] == {},
          str(store.get_prop(pid13)["variant_tiers"][0]["area_defaults"]))
    check("the picture variant hangs on its OWN copy: its values STAND",
          store.list_variants(pid13)[v13]["slot_values"]
          == {"picture_1": {"image": IMG}, "glass_1": {"preset": "glass"}}
          and store.list_variants(pid13)[v13]["area_defaults"]
          == {"glass_1": {"preset": "glass"}},
          str(store.list_variants(pid13)[v13]["slot_values"]))
    check("…its file still names glass_1",
          [a["id"] for a in store.file_areas(full_file(pid13, v13))["areas"]]
          == ["picture_1", "glass_1"])
    store.set_variant_slot_values(pid13, v13, {"picture_1": {"image": IMG2},
                                               "glass_1": {"preset": "glass"}})
    check("…and saving them is validated against ITS file — it passes",
          store.list_variants(pid13)[v13]["slot_values"]
          == {"picture_1": {"image": IMG2}, "glass_1": {"preset": "glass"}},
          str(store.list_variants(pid13)[v13]["slot_values"]))
    # The rename ON the variant is what drops the dead id there.
    renamed = store.rename_area_kind(pid13, "glass_1", "picture", variant=v13)
    check("renaming on the variant: its file reads picture_1, picture_2",
          [(a["id"], a["kind"]) for a in renamed]
          == [("picture_1", "picture"), ("picture_2", "picture")],
          str([(a["id"], a["kind"]) for a in renamed]))
    check("…and the variant's value for the dead id is gone with it",
          store.list_variants(pid13)[v13]["slot_values"]
          == {"picture_1": {"image": IMG2}}
          and store.list_variants(pid13)[v13]["area_defaults"] == {},
          str(store.list_variants(pid13)[v13]["slot_values"]))
    check("…the label stands", store.list_variants(pid13)[v13]["label"] == "Both")
    # THE SYMPTOM the stale key caused: every save of that variant 400s,
    # because the dialog can only send back what it renders.
    store.set_variant_slot_values(pid13, v13, {"picture_1": {"image": IMG}})
    check("saving the variant works again",
          store.list_variants(pid13)[v13]["slot_values"]
          == {"picture_1": {"image": IMG}},
          str(store.list_variants(pid13)[v13]["slot_values"]))

    print("\n[14] a FAILED run says so and deletes nothing")
    pid14 = store.create_prop(name="Doomed frame", key_areas=["picture"])["id"]
    real_detect = store.detect_areas

    def unavailable(*_a, **_k):
        raise store.BlenderUnavailable("blender is busy with another model")

    # The landing itself must not run the (real) detection here.
    store.detect_areas = unavailable
    try:
        store.save_uploaded_glb(pid14, frame_glb())
    finally:
        store.detect_areas = real_detect
    store.set_file_areas(full_file(pid14), areas=FRAME_AREAS, areas_error=None)
    store._source_file(pid14, 0, create=True).write_bytes(b"\x89PNG-source")
    store.set_variant_area_defaults(pid14, 0, {"glass_1": {"preset": "glass"}})
    v14 = store.add_picture_variant(pid14, {"picture_1": {"image": IMG}}, "Keep")
    store.detect_areas = unavailable
    try:
        store._areas_after_landing(pid14, 0)
    finally:
        store.detect_areas = real_detect
    t14 = store.get_prop(pid14)["variant_tiers"][0]
    check("the unsplit mesh names no area — that much IS a reading",
          t14["areas"] == [], str(t14["areas"]))
    check("variant 0's defaults SURVIVE a load condition",
          t14["area_defaults"] == {"glass_1": {"preset": "glass"}},
          str(t14["area_defaults"]))
    check("…and so does the picture variant's picture",
          store.list_variants(pid14)[v14]["slot_values"]
          == {"picture_1": {"image": IMG}},
          str(store.list_variants(pid14)[v14]["slot_values"]))
    info14 = store.areas_info(pid14, 0)
    check("areas_info: the busy Blender is an ERROR",
          "busy" in info14["error"] and info14["warning"] == "",
          str((info14["error"], info14["warning"])))
    check("…stored on the FILE's sidecar",
          "busy" in str(store.read_model_sidecar(full_file(pid14)).get("areas_error")))
    # A run that WORKED and found no leaf is a note, not a failure — two
    # file-sidecar keys since v2, so the tab tells them apart by key.
    store.set_file_areas(full_file(pid14), areas_error=None,
                         areas_warning=store.NO_LEAF_NOTE)
    info14 = store.areas_info(pid14)
    check("the no-leaf note is a WARNING, and `error` stays empty",
          info14["warning"] == store.NO_LEAF_NOTE and info14["error"] == "",
          str((info14["error"], info14["warning"])))
    check("…and variant_tiers[0].areas_warning carries it",
          store.get_prop(pid14)["variant_tiers"][0]["areas_warning"] == store.NO_LEAF_NOTE)


PLAIN_GLB = glb({"asset": {"version": "2.0"}, "materials": [{"name": "atlas"}],
                 "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]})
SPLIT_GLB = glb({"asset": {"version": "2.0"},
                 "materials": [{"name": "atlas"}, {"name": "slot_glass_1"}],
                 "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]})
GLASS_EDGES = [[[0.0, -0.5, 0.0], [0.5, -0.5, 0.0]], [[0.5, -0.5, 0.0], [0.5, 0.0, 0.0]],
               [[0.5, 0.0, 0.0], [0.0, 0.0, 0.0]], [[0.0, 0.0, 0.0], [0.0, -0.5, 0.0]]]


class FakeMeshService:
    """`generate_mesh` writes the given bytes into the output path — the
    pattern of scripts/smoke_props_slots.py [3b]."""

    def __init__(self, blob: bytes) -> None:
        self.blob = blob

    def generate_mesh(self, *, output_path: str, **_kw) -> dict:
        Path(output_path).write_bytes(self.blob)
        return {"ok": True, "path": output_path, "format": "glb",
                "rig": "none", "backend": "fake-mesh", "stages": []}


def stub_blender_split(faces_seen: list):
    """Stub the Blender run of `_areas_run`: the slot gate opens, the script
    'finds' glass_1 on the picked faces and hands back SPLIT_GLB. Returns the
    restore function."""
    from app.blender import refine, runner
    from app.core import model_validate
    saved = (refine.unavailable_reason, refine.take_lod_slot,
             refine.free_lod_slot, runner.run, model_validate.validate_static_glb)

    def fake_run(script, *, inputs, params, out_dir, timeout_s=0):
        faces_seen.append(dict(params))
        out = Path(out_dir) / "split.glb"
        out.write_bytes(SPLIT_GLB)
        return {"ok": True, "outputs": {"model": str(out)}, "data": {
            "areas": [{"id": "glass_1", "kind": "glass", "size_m": [0.5, 0.5],
                       "normal": [0, 0, 1], "faces": len(params.get("faces") or []),
                       "origin": "atlas", "centroid": [0.25, -0.25, 0.0],
                       "edges": GLASS_EDGES}],
            "mesh_layout": [{"name": "m", "tri_count": 8}]}}

    refine.unavailable_reason = lambda: ""
    refine.take_lod_slot = lambda *_a, **_k: True
    refine.free_lod_slot = lambda *_a, **_k: None
    runner.run = fake_run
    model_validate.validate_static_glb = lambda _blob: {"ok": True, "errors": []}

    def restore() -> None:
        (refine.unavailable_reason, refine.take_lod_slot, refine.free_lod_slot,
         runner.run, model_validate.validate_static_glb) = saved
    return restore


def part3() -> None:
    print("\n[15] every variant carries its own areas, leaf and orientation")
    pid = store.create_prop(name="Two frames", category="decor")["id"]
    store.save_uploaded_glb(pid, frame_glb())
    store.set_file_areas(full_file(pid, 0), areas=[FRAME_AREAS[0]])
    v1 = store.add_variant(pid)
    check("variant 1 added", v1 == 1, str(v1))
    store.save_uploaded_glb(pid, PLAIN_GLB, variant=1)
    upload_v1 = full_file(pid, 1)
    check("variant 1's file names no area, variant 0's names picture_1",
          store.areas_info(pid, 1)["areas"] == []
          and [a["id"] for a in store.areas_info(pid, 0)["areas"]] == ["picture_1"],
          str((store.areas_info(pid, 1)["areas"], store.areas_info(pid, 0)["areas"])))
    bakes = []
    real_bake = store.bake_surfaces
    store.bake_surfaces = lambda p, v=None, **k: bakes.append((p, v))
    try:
        out = store.set_rotation(pid, {"y": 90}, variant=1)
    finally:
        store.bake_surfaces = real_bake
    check("set_rotation answers variant 1, the v1 full file and {0, 90, 0}",
          out and out.get("variant") == 1 and out.get("filename") == upload_v1.name
          and out.get("rotation") == {"x": 0, "y": 90, "z": 0}, str(out))
    check("areas_info(pid, 1) rotation y 90; variant 0 stays 0",
          store.areas_info(pid, 1)["rotation"] == {"x": 0, "y": 90, "z": 0}
          and store.areas_info(pid, 0)["rotation"] == {"x": 0, "y": 0, "z": 0},
          str((store.areas_info(pid, 1)["rotation"], store.areas_info(pid, 0)["rotation"])))
    check("the FILE sidecar carries the rotation, the prop sidecar does not",
          store.read_model_sidecar(upload_v1).get("rotation") == {"x": 0, "y": 90, "z": 0}
          and "rotation" not in store.read_sidecar(pid))
    check("the dial asked for variant 1's surface bake", bakes == [(pid, 1)], str(bakes))

    seen: list = []
    restore = stub_blender_split(seen)
    try:
        areas = store.detect_areas(pid, variant=1, mode="manual", faces=[6, 7],
                                   kind="glass")
    finally:
        restore()
    check("detect on variant 1 returns [glass_1]",
          [(a["id"], a["source"], a["faces"]) for a in areas] == [("glass_1", "manual", 2)],
          str(areas))
    check("the run saw manual faces [6, 7], kind glass",
          len(seen) == 1 and seen[0].get("mode") == "manual"
          and seen[0].get("faces") == [6, 7] and seen[0].get("kind") == "glass",
          str(seen))
    g1 = store.model_gallery(pid, 1)
    split_v1 = full_file(pid, 1)
    check("variant 1's gallery has 2 files; the split is active",
          len(g1.files()) == 2 and split_v1 != upload_v1, str([f.name for f in g1.files()]))
    smeta = store.read_model_sidecar(split_v1)
    check("the split file: source areas, mode manual, source_file = the upload",
          smeta.get("source") == "areas" and smeta.get("areas_mode") == "manual"
          and smeta.get("source_file") == upload_v1.name, str(smeta))
    check("…and it INHERITS the upload's rotation y 90 (same mesh)",
          smeta.get("rotation") == {"x": 0, "y": 90, "z": 0}, str(smeta.get("rotation")))
    info1 = store.areas_info(pid, 1)
    check("areas_info(pid, 1): glass_1 with its 4 edges, last_run set, variant 1",
          [a["id"] for a in info1["areas"]] == ["glass_1"]
          and info1["areas"][0].get("edges") == GLASS_EDGES and bool(info1["last_run"])
          and info1.get("variant") == 1, str(info1))
    check("areas_info(pid, 0) is untouched: [picture_1]",
          [a["id"] for a in store.areas_info(pid, 0)["areas"]] == ["picture_1"],
          str(store.areas_info(pid, 0)["areas"]))
    check("the prop sidecar carries none of the moved keys",
          not any(k in store.read_sidecar(pid)
                  for k in ("areas", "leaf_bbox", "rotation", "area_defaults",
                            "areas_error", "areas_run_at")),
          str(sorted(store.read_sidecar(pid))))

    out = store.set_variant_area_defaults(pid, 1, {"glass_1": {"preset": "glass"}})
    check("defaults on variant 1 are stored on ITS entry",
          out and out.get("area_defaults") == {"glass_1": {"preset": "glass"}}
          and store.list_variants(pid)[1]["area_defaults"] == {"glass_1": {"preset": "glass"}},
          str(out and out.get("area_defaults")))
    before = sidecar_text(pid)
    try:
        store.set_variant_area_defaults(pid, 0, {"glass_1": {"preset": "glass"}})
        check("the same default on variant 0 is refused (its file has no glass_1)",
              False, "no ValueError")
    except ValueError as exc:
        check("the same default on variant 0 is refused (its file has no glass_1)",
              sidecar_text(pid) == before, str(exc)[:70])

    rec = store.get_prop(pid)
    check("the record has no prop-level areas / leaf_bbox / rotation / area_defaults",
          not any(k in rec for k in ("areas", "leaf_bbox", "rotation", "area_defaults")),
          str([k for k in ("areas", "leaf_bbox", "rotation", "area_defaults") if k in rec]))
    t = rec["variant_tiers"]
    check("variant_tiers[1]: rotation y 90, areas [glass_1], its defaults",
          len(t) == 2 and t[1]["rotation"] == {"x": 0, "y": 90, "z": 0}
          and [a["id"] for a in t[1]["areas"]] == ["glass_1"]
          and t[1]["area_defaults"] == {"glass_1": {"preset": "glass"}}
          and "leaf_bbox" not in t[1], str(t[1:] if len(t) > 1 else t))
    check("variant_tiers[0]: rotation 0, areas [picture_1], defaults {}",
          t[0]["rotation"] == {"x": 0, "y": 0, "z": 0}
          and [a["id"] for a in t[0]["areas"]] == ["picture_1"]
          and t[0]["area_defaults"] == {}, str(t[0]))

    from app.blender import refine
    real_lod = refine.build_static_lod
    refine.build_static_lod = lambda src, ratio: {
        "ok": True, "blob": Path(src).read_bytes(), "tris": 4, "tris_before": 8}
    try:
        lod = store.build_low_tier(pid, ratio=0.5, variant=1)
    finally:
        refine.build_static_lod = real_lod
    check("the low tier was built", lod.get("ok") is True, str(lod))
    low = g1.find(store.LOW_TIER, fallback=False)
    lmeta = store.read_model_sidecar(low) if low else {}
    check("the low file inherits_from the split full file",
          lmeta.get("inherits_from") == split_v1.name, str(lmeta.get("inherits_from")))
    check("…and carries copies of rotation and areas",
          lmeta.get("rotation") == {"x": 0, "y": 90, "z": 0}
          and [a["id"] for a in lmeta.get("areas") or []] == ["glass_1"], str(lmeta))
    check("file_areas(low) answers with the full file's values",
          low is not None and store.file_areas(low)["areas"] == store.file_areas(split_v1)["areas"]
          and store.file_areas(low)["rotation"] == {"x": 0, "y": 90, "z": 0})
    sig = store.get_prop(pid)["model_signature"]
    store.set_rotation(pid, {"y": 180}, variant=1)
    check("a further turn: the full file 180, the low file's copy 180",
          store.read_model_sidecar(split_v1).get("rotation") == {"x": 0, "y": 180, "z": 0}
          and store.read_model_sidecar(low).get("rotation") == {"x": 0, "y": 180, "z": 0}
          and store.file_areas(low)["rotation"]["y"] == 180,
          str((store.read_model_sidecar(split_v1).get("rotation"),
               store.read_model_sidecar(low).get("rotation"))))
    check("a turned variant moves the prop's model_signature",
          store.get_prop(pid)["model_signature"] != sig)
    rows = store.list_models(pid, 1)
    check("list_models publishes each file's rotation",
          all("rotation" in r for r in rows)
          and next(r for r in rows if r["filename"] == split_v1.name)["rotation"]["y"] == 180,
          str([(r["filename"], r.get("rotation")) for r in rows]))

    print("\n[16] the landing hook runs for EVERY variant")
    pid2 = store.create_prop(name="Keyed pair", key_areas=["picture"])["id"]
    calls: list = []
    real_detect = store.detect_areas

    def recording(prop_id, **kw):
        calls.append({"prop_id": prop_id, **kw})
        return []

    store.detect_areas = recording
    try:
        store.save_uploaded_glb(pid2, frame_glb())
        store.add_variant(pid2)
        store.save_uploaded_glb(pid2, PLAIN_GLB, variant=1)
    finally:
        store.detect_areas = real_detect
    check("the upload on variant 0 ran the hook for variant 0, mode auto",
          len(calls) >= 1 and calls[0]["mode"] == "auto"
          and calls[0].get("variant") in (0, None), str(calls[:1]))
    check("the upload on variant 1 ran the hook for variant 1",
          len(calls) == 2 and calls[1]["mode"] == "auto" and calls[1].get("variant") == 1,
          str(calls))
    import app.imagegen.service as image_service
    real_service = image_service.get_image_service
    image_service.get_image_service = lambda: FakeMeshService(PLAIN_GLB)
    store._source_file(pid2, 1, create=True).write_bytes(b"\x89PNG fake")
    calls.clear()
    store.detect_areas = recording
    try:
        out = store._generate(pid2, "", "", "", "fake-mesh", mesh_only=True, variant=1)
    finally:
        store.detect_areas = real_detect
        image_service.get_image_service = real_service
    check("the generation chain into variant 1 succeeded", out.get("ok") is True, str(out))
    check("…and ran the hook for variant 1 as well",
          len(calls) == 1 and calls[0].get("variant") == 1 and calls[0]["mode"] == "auto",
          str(calls))

    print("\n[17] a new file of a variant starts from the rotation of the one it replaces")
    store.save_uploaded_glb(pid, PLAIN_GLB, variant=1)
    newest = full_file(pid, 1)
    check("the new upload is a fourth file of variant 1 (upload, split, low, upload)",
          len(store.model_gallery(pid, 1).files()) == 4
          and newest not in (upload_v1, split_v1, low),
          str([f.name for f in store.model_gallery(pid, 1).files()]))
    check("…whose sidecar starts with the previous file's rotation y 180",
          store.read_model_sidecar(newest).get("rotation") == {"x": 0, "y": 180, "z": 0},
          str(store.read_model_sidecar(newest)))
    check("areas_info(pid, 1) rotation 180, areas [] (a fresh, unsplit file); variant 0 still 0",
          store.areas_info(pid, 1)["rotation"]["y"] == 180
          and store.areas_info(pid, 1)["areas"] == []
          and store.areas_info(pid, 0)["rotation"]["y"] == 0,
          str(store.areas_info(pid, 1)))


def part4() -> None:
    print("\n[18] a split replaces its predecessor — history = origin + current")
    pid = store.create_prop(name="History frame", category="decor")["id"]
    store.save_uploaded_glb(pid, frame_glb())
    origin = full_file(pid)
    gal = store.model_gallery(pid, 0)
    check("the upload is the only file", [f.name for f in gal.files()] == [origin.name],
          str([f.name for f in gal.files()]))

    seen: list = []
    restore = stub_blender_split(seen)
    try:
        store.detect_areas(pid, mode="manual", faces=[0, 1], kind="glass")
        s1 = full_file(pid)
        names = sorted(f.name for f in store.model_gallery(pid, 0).files())
        check("run #1 lands a split beside the origin (2 files)",
              names == sorted([origin.name, s1.name]) and s1 != origin, str(names))
        s1_side = s1.with_suffix(".json")
        s1_comp = store.areas_sidecar_path(s1)
        check("the split has a sidecar and an .areas.json companion",
              s1_side.exists() and bool(s1_comp) and s1_comp.exists(),
              str((s1_side.exists(), s1_comp and s1_comp.exists())))

        store.detect_areas(pid, mode="manual", faces=[2, 3], kind="glass")
        s2 = full_file(pid)
        names = sorted(f.name for f in store.model_gallery(pid, 0).files())
        check("run #2: still 2 files — the origin and the NEW split",
              names == sorted([origin.name, s2.name]) and s2 not in (origin, s1),
              str(names))
        check("…the predecessor's mesh, sidecar and companion are gone",
              not s1.exists() and not s1_side.exists()
              and not (s1_comp and s1_comp.exists()),
              str((s1.exists(), s1_side.exists(), bool(s1_comp and s1_comp.exists()))))
        check("…and the new split names the ORIGIN as its source_file",
              store.read_model_sidecar(s2).get("source_file") == origin.name,
              str(store.read_model_sidecar(s2).get("source_file")))

        store.detect_areas(pid, mode="manual", faces=[4, 5], kind="glass")
        s3 = full_file(pid)
        names = sorted(f.name for f in store.model_gallery(pid, 0).files())
        check("run #3: STILL 2 files (the chain never grows)",
              names == sorted([origin.name, s3.name]), str(names))
        check("the origin survived all three runs, still `source: upload`",
              origin.exists()
              and store.read_model_sidecar(origin).get("source") == "upload",
              str(store.read_model_sidecar(origin).get("source")))

        print("\n[19] a rename goes through the same landing")
        areas = store.rename_area_kind(pid, "glass_1", "picture")
        s4 = full_file(pid)
        names = sorted(f.name for f in store.model_gallery(pid, 0).files())
        check("the rename answers [picture_1]",
              [a["id"] for a in areas] == ["picture_1"], str(areas))
        check("still 2 files — the renamed file replaced the split it came from",
              names == sorted([origin.name, s4.name]) and s4 != s3, str(names))
        check("…and s3 is gone with its companions",
              not s3.exists() and not s3.with_suffix(".json").exists(),
              str((s3.exists(), s3.with_suffix(".json").exists())))
        m4 = store.read_model_sidecar(s4)
        check("the renamed file: source areas, mode rename, origin O, area picture_1",
              m4.get("source") == "areas" and m4.get("areas_mode") == "rename"
              and m4.get("source_file") == origin.name
              and m4.get("areas_area") == "picture_1", str(m4))

        print("\n[20] a split that another tier uses is NOT deleted")
        check("s4 becomes the LOW file too",
              store.select_model(pid, s4.name, "low") is True)
        store.detect_areas(pid, mode="manual", faces=[6, 7], kind="glass")
        s5 = full_file(pid)
        names = sorted(f.name for f in store.model_gallery(pid, 0).files())
        check("3 files now: origin, the low-tier split, the new full split",
              names == sorted([origin.name, s4.name, s5.name]), str(names))
        rows = {r["filename"]: r for r in store.list_models(pid, 0)}
        check("s4 still serves `low`, s5 serves `full`",
              rows[s4.name]["selected_for"] == ["low"]
              and rows[s5.name]["selected_for"] == ["full"],
              str({k: v["selected_for"] for k, v in rows.items()}))
    finally:
        restore()

    print("\n[21] the row says what the file is")
    parts = rows[s5.name].get("label_parts") or {}
    check("the split's label_parts name source, mode and its areas",
          parts.get("source") == "areas" and parts.get("areas_mode") == "manual"
          and parts.get("area_ids") == ["glass_1"]
          and parts.get("source_file") == origin.name, str(parts))
    oparts = rows[origin.name].get("label_parts") or {}
    check("the origin's label_parts say `upload` and name no run",
          oparts.get("source") == "upload" and not oparts.get("areas_mode")
          and oparts.get("area_ids") == [] and not oparts.get("source_file"),
          str(oparts))

    pid2 = make_prop("Copy label", frame_glb(), FRAME_AREAS)
    store.add_picture_variant(pid2, {"picture_1": {"image": IMG}}, "x")
    crow = store.list_models(pid2, 1)[0]
    cparts = crow.get("label_parts") or {}
    check("the picture variant's copy says which VARIANT it came from",
          cparts.get("source") == "variant-copy"
          and (cparts.get("copied_from") or {}).get("variant") == 0
          and (cparts.get("copied_from") or {}).get("file")
          == full_file(pid2, 0).name, str(cparts))


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
    check("the record has NO prop-level areas / area_defaults / leaf_bbox / rotation (E1)",
          not any(k in rec for k in ("areas", "area_defaults", "leaf_bbox", "rotation")),
          str([k for k in ("areas", "area_defaults", "leaf_bbox", "rotation") if k in rec]))
    check("no mesh yet: areas_info answers areas [] and area_defaults {}",
          store.areas_info(pid)["areas"] == [] and store.areas_info(pid)["area_defaults"] == {},
          str(store.areas_info(pid)))
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
    # The areas live on the FILE: a landed mesh first (while no key colour is
    # requested, so the landing only reconciles), then the list.
    store.save_uploaded_glb(pid, frame_glb())
    store.update_prop(pid, {"key_areas": ["picture", "glass"]})
    mp = full_file(pid)
    store.set_file_areas(mp, areas=AREAS)
    got = store.get_prop(pid)["variant_tiers"][0]["areas"]
    check("areas read back as written, on variant_tiers[0]", got == AREAS, str(got))
    check("…and the file sidecar carries them, the prop sidecar does not",
          store.read_model_sidecar(mp).get("areas") == AREAS
          and "areas" not in store.read_sidecar(pid))
    check("file_areas: rotation 0, no leaf, no warning, no run",
          store.file_areas(mp) == {"areas": AREAS, "leaf_bbox": None,
                                   "rotation": {"x": 0, "y": 0, "z": 0},
                                   "areas_run_at": "", "areas_error": "",
                                   "areas_warning": "", "key_areas_run": []},
          str(store.file_areas(mp)))

    print("\n[2] area_defaults are checked against the VARIANT's file areas")
    out = store.set_variant_area_defaults(pid, 0, {"glass_1": {"preset": "glass"}})
    check("a default on an existing area is stored on the variant entry",
          out and out.get("area_defaults") == {"glass_1": {"preset": "glass"}},
          str(out and out.get("area_defaults")))
    check("…and on the record's variant_tiers[0]",
          store.get_prop(pid)["variant_tiers"][0]["area_defaults"]
          == {"glass_1": {"preset": "glass"}})
    check("…and in areas_info",
          store.areas_info(pid, 0)["area_defaults"] == {"glass_1": {"preset": "glass"}})
    before = sidecar_text(pid)
    for label, value in (("an unknown area", {"nope": {"preset": "glass"}}),
                         ("a preset outside SLOT_PRESETS",
                          {"glass_1": {"preset": "mirror"}}),
                         ("a default without preset", {"glass_1": {}}),
                         # The KIND decides the shape, as it does for a
                         # variant's slot_values: a default is the LOOK of a
                         # pane, so a picture area takes none.
                         ("a preset on a PICTURE area",
                          {"picture_1": {"preset": "glass"}}),
                         ("a string instead of an object", "glass")):
        try:
            store.set_variant_area_defaults(pid, 0, value)
            check(f"refused: {label}", False, "no ValueError")
        except ValueError as exc:
            check(f"refused: {label}", sidecar_text(pid) == before, str(exc)[:60])
    try:
        store.update_prop(pid, {"area_defaults": {"glass_1": {"preset": "glass"}}})
        check("a PROP patch naming area_defaults is refused (moved to the variant)",
              False, "no ValueError")
    except ValueError as exc:
        check("a PROP patch naming area_defaults is refused (moved to the variant)",
              "variants/{i}/area-defaults" in str(exc) and sidecar_text(pid) == before,
              str(exc)[:80])
    check("an unknown variant index answers None",
          store.set_variant_area_defaults(pid, 7, {}) is None)

    print("\n[2b] the door leaf is a kind without a colour (R9)")
    check("COLOUR_KINDS = picture_areas.KINDS, AREA_KINDS adds leaf last",
          tuple(store.COLOUR_KINDS) == ("picture", "glass")
          and store.AREA_KINDS == ("picture", "glass", "leaf"),
          str((store.COLOUR_KINDS, store.AREA_KINDS)))
    check("sanitize_key_areas accepts leaf, in kind order",
          store.sanitize_key_areas(["leaf", "picture"]) == ["picture", "leaf"],
          str(store.sanitize_key_areas(["leaf", "picture"])))
    check("apply_key_areas: leaf adds no fragment",
          store.apply_key_areas("p", "n", ["leaf"]) == ("p", "n"),
          str(store.apply_key_areas("p", "n", ["leaf"])))
    LEAF = {"id": "leaf", "kind": "leaf", "size_m": [0.8, 2.0],
            "normal": [0, 0, 1], "source": "auto", "faces": 12}
    check("sanitize_areas round-trips a leaf entry",
          store.sanitize_areas(AREAS + [LEAF]) == AREAS + [LEAF],
          str(store.sanitize_areas(AREAS + [LEAF])[-1]))
    for label, bad in (("id leaf of kind picture", {**LEAF, "kind": "picture"}),
                       ("a numbered leaf_1", {**LEAF, "id": "leaf_1"})):
        try:
            store.sanitize_areas([bad])
            check(f"refused: {label}", False, "no ValueError")
        except ValueError as exc:
            check(f"refused: {label}", True, str(exc)[:60])
    store.set_file_areas(mp, areas=AREAS + [LEAF])
    before = sidecar_text(pid)
    try:
        store.set_variant_area_defaults(pid, 0, {"leaf": {"preset": "glass"}})
        check("area_defaults on the leaf is refused", False, "no ValueError")
    except ValueError as exc:
        check("area_defaults on the leaf is refused, nothing written",
              sidecar_text(pid) == before, str(exc)[:60])
    try:
        store.sanitize_variant_slot_values({"leaf": {"preset": "glass"}}, AREAS + [LEAF])
        check("slot_values on the leaf is refused", False, "no ValueError")
    except ValueError as exc:
        check("slot_values on the leaf is refused", True, str(exc)[:60])
    for label, args in (("picture_1 -> leaf", ("picture_1", "leaf")),
                        ("leaf -> glass", ("leaf", "glass"))):
        try:
            store.rename_area_kind(pid, *args)
            check(f"rename refused: {label}", False, "no ValueError")
        except ValueError as exc:
            check(f"rename refused: {label}", "node" in str(exc), str(exc)[:60])
    bb = store.sanitize_leaf_bbox({"min": [0.1, 0.1, -0.02], "max": [0.9, 2.1, 0]})
    check("sanitize_leaf_bbox round-trips",
          bb == {"min": [0.1, 0.1, -0.02], "max": [0.9, 2.1, 0.0]}, str(bb))
    try:
        store.sanitize_leaf_bbox({"min": [1, 0, 0], "max": [0, 0, 0]})
        check("leaf_bbox min > max is refused", False, "no ValueError")
    except ValueError as exc:
        check("leaf_bbox min > max is refused", True, str(exc)[:50])
    check("sanitize_leaf_bbox(None) is None", store.sanitize_leaf_bbox(None) is None)
    check("no leaf_bbox: variant_tiers[0] has no key, areas_info says None",
          "leaf_bbox" not in store.get_prop(pid)["variant_tiers"][0]
          and store.areas_info(pid)["leaf_bbox"] is None)
    store.set_file_areas(mp, leaf_bbox=bb)
    check("a FILE leaf_bbox shows on variant_tiers[0] and in areas_info",
          store.get_prop(pid)["variant_tiers"][0].get("leaf_bbox") == bb
          and store.areas_info(pid)["leaf_bbox"] == bb,
          str(store.get_prop(pid)["variant_tiers"][0].get("leaf_bbox")))
    store.set_file_areas(mp, areas=AREAS, leaf_bbox=None)
    check("leaf_bbox=None removes the key again",
          "leaf_bbox" not in store.read_model_sidecar(mp))
    check("is_door_prop: category Door / tag ' door ' / neither",
          store.is_door_prop({"category": "Door"}) is True
          and store.is_door_prop({"tags": [" door "]}) is True
          and store.is_door_prop({"category": "decor", "tags": ["wood"]}) is False)

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
    part3()
    part4()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
