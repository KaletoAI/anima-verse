"""Prop library — single 3D objects (chair, table, plant, …) for room furnishing.

Plan: ``development_instructions/plan-room-props.md``. Unlike the room-diorama
models (``location_model3d.py``), a prop is ONE isolated object generated from a
dedicated product-shot render (use case ``prop``) → img2mesh (rig "none"). Each
prop carries OBJECT-LOCAL place markers — a figure taking that place snaps to
the marker in the object's own space, so markers live on the OBJECT
instead of being set per room.

Storage: ``worlds/<world>/props/<prop_id>/``:

    model_<ts>.glb   — the meshes (unrigged GLB, embedded texture)
    model_<ts>.json  — one sidecar per mesh: {created_at, source, format,
                       tier, backend, face_num, texture_size} plus what is
                       MEASURED ON THAT MESH (spec-bild-props-v2.md E1):
                       {areas[], leaf_bbox, rotation{x,y,z}, areas_run_at,
                       areas_error, areas_warning, key_areas_run[]}; a LOW
                       file says `inherits_from: <full file>` instead
    selection.json   — {"model": {"<tier>": "<filename>"}}
    source.png       — the product-shot render THIS variant's meshes were made
                       from (one per variant, see the source-image law below)
    sidecar.json     — the prop MASTER record: {name, category, tags[],
                       bbox[3], sway_factor, slots[], slots_auto,
                       key_areas[], created_at, source, prompt,
                       model_variants[{…, area_defaults{}, slot_values{}}]}
    model_<ts>.glb.areas.json — outline edges + mesh layout of the picture
                       areas of THAT mesh (spec-picture-props.md § 2)

The mesh files are a GALLERY like the location/room models — same mechanics,
same module (``app/core/model_store.py``): several files per prop, one active
per resolution tier (``full`` / ``low``), selected in ``selection.json``.
Everything that describes ONE generation run (backend, face_num,
texture_size) lives on that run's sidecar; the master record describes the
OBJECT (2026-08-03, plan-3d-lod-und-betreten.md).

MODEL VARIANTS (2026-08-19, "Prop-Welt statt Dioramen" E2.3). One prop may
carry SEVERAL active meshes of the same object, so a scattered wood is not the
same tree twenty times. A variant is a whole gallery of its own — its own
resolution tiers, its own history — and the variants are an ORDERED LIST on
the master record::

    "model_variants": [{"stem": "model", "active": true},
                       {"stem": "model-v2", "active": true}]

The stem is what separates them on disk: variant 0 keeps the historic
``model`` stem (``model_<ts>.glb``), every further one gets ``model-v<n>``, and
``selection.json`` is already keyed BY STEM, so each variant selects its own
tiers without a second mechanism. The stem is STORED, not derived from the
position — deleting a variant in the middle must not rename the files of the
one behind it. A record without the key has exactly one variant, the primary.

SEASONS (E2c, 2026-08-20). A variant may name the seasons it depicts::

    "model_variants": [{"stem": "model", "active": true},
                       {"stem": "model-v2", "active": true,
                        "seasons": ["Winter"]}]

Names from the world's ``game_seasons``, matched case-insensitively against
the current season's key/name; the key is stored only when it names something,
because "no dependency" is the default and absence is how a default is stored.
EFFECTIVELY active = manually active AND in season, and that single gate
(``_effective_indices``) is what the scatter, the placements, the world props
and the serving URLs all read. A prop whose variants carry no tag never even
reads the clock.

THE SOURCE IMAGE FOLLOWS THE MESH (2026-08-20). A variant is not just a mesh
gallery, it is a whole object version: the product-shot render it was meshed
from belongs to the VARIANT, not to the prop. The file name follows the mesh
stem by the SAME suffix::

    model      → source.png          (variant 0, the historic name)
    model-v2   → source-v2.png
    model-v<n> → source-v<n>.png

That naming IS the no-migration path, exactly as ``model`` vs ``model-v<n>``
is for the meshes: an existing prop's image stays where it is, untouched.
Everything the image is part of is variant-scoped with it — generating,
uploading, re-meshing, serving and deleting; deleting a variant takes ITS
image and no other. Without the law a second variant's render overwrote the
one image, and a later re-mesh of an older variant produced a mesh of the
WRONG picture. The image's provenance (backend, prompt, negative, timestamp)
is stored by the same law: the base stem keeps the master-record keys
(``backend_image`` / ``prompt`` / ``negative`` / ``source_generated_at``),
every further variant carries its own under ``image`` on its variant entry.

How many ACTIVE variants a prop may have is ``image_generation.prop_variant_max``
(default 4). The FIRST ACTIVE variant is the **primary** one: it is what
``/assets/props/<id>/model`` serves without a ``variant`` parameter, what the
dims/bbox are measured from, and what every payload publishes as its single
``variants`` map — a consumer that knows nothing about variants keeps rendering
exactly what it rendered before.

``prop_id`` = slug of the name + a short hash (stable, file-safe).

THE VARIANT OWNS WHAT IT LOOKS LIKE (2026-08-25, user decision). Five fields
that used to sit on the PROP with an optional per-variant override are now
stored ON THE VARIANT and nowhere else — there is no prop-level copy and no
fallback reader:

===================  ========================================================
``width_m``          real extent in metres after the orientation fix (x),
``depth_m``          … (z), ``height_m`` … (y), each in (0, 100]
``dims_estimated``   True while the three are still a placeholder cube that
                     the mesh proportions have not informed
``description``      the GENERATION SUBJECT this variant's product shot is
                     rendered from (absent = fall back to the prop's NAME)
``ground_offset_m``  how deep THIS version stands in the ground (absent = 0)
``markers``          the OBJECT-LOCAL place markers of THIS mesh
===================  ========================================================

so one entry reads::

    "model_variants": [{"stem": "model", "active": true,
                        "width_m": 0.6, "depth_m": 0.6, "height_m": 4.0,
                        "dims_estimated": false,
                        "description": "a tall pine tree",
                        "ground_offset_m": -0.1,
                        "markers": [{"id": "a7k2m9xq", "group": "seat",
                                     "at": [.5, .4, .5]}]},
                       {"stem": "model-v2", "active": true,
                        "width_m": 0.3, "depth_m": 0.3, "height_m": 1.4,
                        "dims_estimated": false,
                        "description": "a pine sapling"}]

WHY. A variant is a whole VERSION of the object — a sapling beside the grown
pine, a broken chair beside the whole one — and those differ in exactly these
five ways. The mesh normalization destroys the real scale (the height_m /
width_m lesson), so the size has to be authored; it belongs to the mesh it
describes, and so do the seat markers, the sink into the ground and the
sentence the picture was rendered from.

THE DIMS ARE MANDATORY, the other three follow the "absence is the statement"
law. Every variant answers with three usable metres (:func:`variant_dims`) —
there is nothing left to inherit, so a missing key is not a statement but a
hand-edit, and the reader falls back to the ``DEFAULT_DIM_M`` cube.
``description`` / ``ground_offset_m`` / ``markers`` are stored only when they
say something, because their default (no subject / on the ground / no marker)
is a real answer that must exist in ONE shape.

A reader with no variant in hand answers for the PRIMARY variant — the first
effectively active one — exactly like every other unqualified read here
(``/model`` without a parameter, the payload's single ``variants`` map). That
is what ``prop_scatter_facts``, the lean prop record and every admin listing
resolve to.

A NEW VARIANT COPIES the whole set from the variant the admin has open (the
PRIMARY one when none is named): the admin authors a version of THIS object,
so every field opens filled and is EDITED ("…as a sapling") instead of being
written from nothing. It is a copy, not a link.

``bbox`` = ``[bx, by, bz]``, the AABB edge lengths of model.glb in MESH units
on the RAW mesh axes (before the orientation fix), rounded to 5 decimals. It
stays on the PROP: it is measured on the PRIMARY variant's mesh when that
model arrives (generation or upload) and lazily backfilled for older props on
the first listing. Together with ``rotation`` it is what turns one real-world
size into proportional dims (``oriented_dims`` / ``_dims_from_size``), and the
redistribution it feeds writes into the PRIMARY variant's three numbers.

``markers[].at`` is an OBJECT-LOCAL ``[u, v, w]`` (fractions of the model
bounding box, which MAY exceed 0..1 by half a box for seats and poses that
sit on or outside the hull — range ``[-0.5, 1.5]``); the vocabulary is
identical to ``layout.markers`` (id + group + capacity + facing), only the
frame is the object instead of the room rectangle.

The one-time move of the five fields out of the prop record lives in
``app/core/prop_field_migration.py`` (boot, guarded by ``world_kv``).
"""

import hashlib
import json
import math
import os
import random
import re
import shutil
import struct
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.core.game_time import (current_season_tokens, sanitize_season_tags,
                                season_tags_active)
from app.core.log import get_logger
from app.core.model_store import (DEFAULT_TIER, ModelGallery, normalize_tier,
                                  read_sidecar as read_model_sidecar,
                                  write_sidecar as write_model_sidecar)
from app.core.model_validate import (MeshNotShrinkable, glb_bounds,
                                     glb_material_names_at, parse_glb,
                                     shrink_capability)
from app.core.picture_areas import KINDS as COLOUR_KINDS
from app.core.timeutils import utc_now_iso
from app.core.view_prompts import EXTRA_VIEWS, VIEWS, is_view
from app.core.world_ops import _capacity, _place_id, _slot_axis, _spacing

logger = get_logger(__name__)

MODEL_STEM = "model"
SOURCE_NAME = "source.png"
SIDECAR_NAME = "sidecar.json"
# Tier a mesh→mesh reduction always writes into (see trigger_shrink).
LOW_TIER = "low"

# ── Model variants (E2.3) ───────────────────────────────────────────────
#: Sidecar key holding the ordered variant list.
VARIANTS_KEY = "model_variants"
#: How many ACTIVE variants a prop may carry when nothing is configured.
DEFAULT_VARIANT_MAX = 4
#: Hard ceiling for the configured value — a prop is placed many times over,
#: and every active variant is another mesh every client downloads.
VARIANT_MAX_CAP = 16
#: The stems a variant may carry: the historic base stem, or ``model-v<n>``
#: with n = 2…99. Validated on read, because the stem decides which files a
#: gallery matches and must never become a path escape.
_VARIANT_STEM_RE = re.compile(rf"^{MODEL_STEM}(-v([2-9]|1[0-9]))?$")
# ^ v2..v19: the dispenser (`_free_stem`) can hand out v10..v17 at the
#   configurable cap of 16, and the old `[2-9][0-9]?` never matched a
#   leading 1 — such a variant was silently dropped on the next read
#   (latent-bug find 2026-08-20). v1 stays excluded: the base stem IS
#   variant 0, a stray "model-v1" must not be claimed.
#: What a variant records about ITS source image. The base stem keeps these
#: four on the MASTER record under their historic names (see ``_image_meta``);
#: every further variant carries them under ``image`` on its own entry.
IMAGE_META_KEYS = ("backend", "prompt", "negative", "generated_at")
#: Master-record name of each of them, for the base stem.
_IMAGE_META_MASTER = {"backend": "backend_image", "prompt": "prompt",
                      "negative": "negative",
                      "generated_at": "source_generated_at"}
#: Variant-entry / master-record key holding the provenance of the EXTRA
#: views (``{"back": {...}, "left": {...}, "right": {...}}``); the front
#: stays in ``image`` / the master fields.
IMAGE_VIEWS_KEY = "image_views"
#: SEASON TAGS of a variant (E2c, 2026-08-20). Optional list of season names
#: from the world's ``game_seasons``; stored only when non-empty, because
#: absence IS the default "no dependency" and an empty list beside a missing
#: key would be the same fact in two shapes. See ``_effective_indices``.
SEASONS_KEY = "seasons"

#: The GENERATION SUBJECT of a variant (2026-08-24, variant-only since
#: 2026-08-25). A variant is a whole version of the object — a sapling beside
#: the grown pine — so the sentence its product shot is rendered from belongs
#: to it and to nothing else. Same "absence is the statement" law as
#: ``seasons``: stored only when it says something, and a variant without the
#: key renders from the prop's NAME (the fallback that predates the field).
#: See :func:`variant_description` and :func:`add_variant`, which COPIES the
#: source variant's text into a new slot so the admin edits a filled field.
DESCRIPTION_KEY = "description"
#: Runaway guard on that text — it is a prompt subject, not an essay, and it
#: rides in every sidecar read.
DESCRIPTION_MAX = 2000

DEFAULT_DIM_M = 1.0
DIM_KEYS = ("width_m", "depth_m", "height_m")
#: The three dims live ON THE VARIANT and are MANDATORY there (2026-08-25):
#: every entry answers with three usable metres, because there is no prop-level
#: value left to inherit. A missing key is a hand-edit, not a statement, and
#: reads back as the ``DEFAULT_DIM_M`` cube. See :func:`variant_dims`.
#: Companion flag of exactly those three numbers — True while they are still a
#: placeholder cube the mesh proportions have not informed. Per variant for the
#: same reason the dims are: it is a statement ABOUT them.
DIMS_ESTIMATED_KEY = "dims_estimated"
#: How deep ONE VERSION of the object stands in the ground, on its own entry
#: (2026-08-25). Absence is the statement "on the ground" — see
#: :data:`GROUND_OFFSET_DEFAULT` and :func:`variant_ground_offset`.
GROUND_OFFSET_KEY = "ground_offset_m"
#: The OBJECT-LOCAL animation markers of ONE variant's mesh (2026-08-25).
#: Absence is the statement "no markers"; the fractions are of THAT mesh's
#: bounding box, which is why they cannot be shared with another version.
MARKERS_KEY = "markers"

#: How hard THIS prop bends in the wind — a multiplier on the sway of the
#: ground it grows on (§ A9), not a length. How far a meadow waves is the
#: terrain KIND's business (``meta.sway_m``); how much of that a single prop
#: takes part in is the prop's, so a boulder scattered over a waving meadow can
#: stand still (0.0) while the ferns beside it bend fully (1.0).
SWAY_FACTOR_DEFAULT = 1.0
SWAY_FACTOR_MIN, SWAY_FACTOR_MAX = 0.0, 1.0

#: How deep THIS VARIANT stands in the ground, in metres, WHEREVER it stands —
#: negative sinks it, positive lifts it. A property of the MESH, not of one
#: placement: a tree whose mesh carries no root ball has to sink by the same
#: few centimetres in every room, every yard, every painted wood and at every
#: hand-set spot on the world plane, and dialling that per instance is the
#: same number typed a hundred times. It sits on the VARIANT (2026-08-25)
#: because it is a fact about one bake: the sapling's trunk and the grown
#: tree's are not buried by the same amount.
#:
#: The per-PLACEMENT ``offset_y`` stays what it is — the additive trim of ONE
#: instance ("this one stone a bit deeper"). Effective base of an instance =
#: automatic base + ``ground_offset_m`` + ``offset_y``.
GROUND_OFFSET_DEFAULT = 0.0
GROUND_OFFSET_MIN, GROUND_OFFSET_MAX = -5.0, 5.0

# ── Texture slots (plan-door-props-texture-slots) ───────────────────────
#: The surfaces of a prop's mesh that can later be FILLED: a picture frame that
#: takes a gallery image, a window pane that takes a material. A slot is a
#: MATERIAL of the model — the modeller (or the img2mesh prompt) names it, the
#: import reads the names off the GLB (:func:`detect_slots`), and the admin
#: corrects the list in the prop editor. Room props only: the map props
#: (``app/models/world_props.py``) are a different namespace and get none.
#:
#: Sidecar key holding the list of ``{"name": …, "kind": …}``.
SLOTS_KEY = "slots"
#: Marker beside it: True = the list is what the model's materials said, False
#: = an admin edited it. The auto-fill only ever fills a record it has not
#: touched and no admin has — a hand-authored list is never overwritten, not
#: even an EMPTY one (deleting every slot is a decision too).
SLOTS_AUTO_KEY = "slots_auto"
#: What a slot can be filled WITH. ``image`` takes a picture (a gallery URL),
#: ``material`` takes a look (glass, mirror, matte).
SLOT_KINDS = ("image", "material")
#: A material named ``slot_<name>`` IS a slot — the explicit, open half of the
#: convention (Entscheid 4). Everything behind the prefix is the slot name.
SLOT_PREFIX = "slot_"
#: …and these material names are slots WITHOUT the prefix, because they are
#: what a mesh generator calls those surfaces on its own — the closed half of
#: the convention. The name must match WHOLE: "glasses" is a pair of glasses,
#: not a pane.
BARE_SLOT_NAMES = ("picture", "screen", "sign", "glass")
#: Which slot NAMES mean a look rather than a picture. The kind is decided by
#: the NAME and by nothing else, so ``slot_glass`` and ``glass`` can never
#: describe the same surface differently.
MATERIAL_SLOT_NAMES = ("glass", "mirror", "matte")
#: WHICH LOOKS a ``material`` slot can actually be set to. The list's home is
#: the code that DRAWS them — ``MATERIAL_PRESETS`` in
#: ``packages/scene-render/src/slotMaterials.ts``, the one routine both
#: renderers use. A preset no renderer can draw is not a preset, so this tuple
#: is a mirror of that list and never grows on its own. (It is deliberately
#: shorter than :data:`MATERIAL_SLOT_NAMES`: a mesh may NAME a ``mirror``
#: surface long before anything can render one.)
#: Kept for variant slot values (picture props).
SLOT_PRESETS = ("glass",)

# ── Picture areas (spec-picture-props.md) ───────────────────────────────
#: A frame prop's PANELS — the faces of its mesh that take a picture (kind
#: ``picture``) or a pane (kind ``glass``). An area IS a material of the GLB,
#: ``slot_<kind>_<k>``, with planar 0..1 UVs on exactly its faces; the face
#: assignment lives ONLY in the GLB, the sidecar keeps the metadata per area
#: (``AREAS_KEY``) and the outline edges + mesh layout of the active mesh sit
#: in ``<model>.glb.areas.json`` beside it (:func:`areas_sidecar_path`).
#: Detection and split run headless in Blender
#: (``app/blender/scripts/picture_areas.py``) — automatically when a mesh
#: lands and the prop asked for key colours, by hand from the Areas tab.
#:
#: THE KINDS (ruling R9). ``COLOUR_KINDS`` = ``picture_areas.KINDS`` — the
#: chroma-key kinds with a colour predicate and a prompt fragment; an area of
#: one of them IS a material. ``leaf`` (spec § 6, D7) is the DOOR LEAF: a
#: NODE of the GLB cut out by geometry, no colour, no prompt, never a slot,
#: never a default — it is in ``AREA_KINDS`` so the request list, the area
#: list, the manual pick and the kind check know it, and in nothing else.
#: (Not the WALL-piece kind ``leaf`` of the scene payload, the flat panel in
#: a door hole — same word, a different thing.)
LEAF_KIND = "leaf"
AREA_KINDS = tuple(COLOUR_KINDS) + (LEAF_KIND,)
#: Sidecar key: which key colours the generation was asked for — a subset of
#: ``AREA_KINDS`` in that order (``leaf`` = "cut the door leaf out on every
#: landing", no prompt text). Non-empty = detect on every landing.
KEY_AREAS_KEY = "key_areas"
#: THE MEASURED FACTS LIVE ON THE MODEL FILE (spec-bild-props-v2.md E1,
#: 2026-08-28). Every variant is its own img2mesh generation — measured on a
#: real door prop: one variant had other axes and no leaf node — so what a
#: split found, where the leaf sits and which way is up are facts of ONE
#: FILE, kept on that file's own ``.json`` sidecar (``model_store``) and read
#: through :func:`file_areas`. A LOW file inherits them from its full file
#: (:data:`INHERITS_FROM_KEY`). The prop record publishes them per
#: ``variant_tiers[i]``; nothing of the kind is on the prop any more (the
#: legacy prop-level values were moved once, ``prop_areas_migrate``).
#:
#: FILE-sidecar key: ``[{id, kind, size_m: [w, h], normal: [x, y, z], source,
#: faces, origin?, centroid?}, …]``; ``id`` = the slot name (``picture_1``),
#: or ``leaf`` for the door leaf node.
AREAS_KEY = "areas"
#: FILE-sidecar key: ``{"min": [x, y, z], "max": [x, y, z]}`` of the ``leaf``
#: node in glTF y-up RAW model metres (before the placement's fit scaling) —
#: what the scene recipe copies into ``door.leaf_bbox`` so a renderer hangs
#: its pivot without measuring (§ B5a). Present exactly while the model has
#: a leaf node; written by the same run that writes ``areas``.
LEAF_BBOX_KEY = "leaf_bbox"
#: FILE-sidecar key: the admin's orientation fix ``{x, y, z}`` in degrees
#: (pattern ``location_model3d.set_rotation``, per file). A new file of a
#: variant starts from the fix of the file it replaces (the dial is the
#: default for the variant's next mesh); a split copies its input's.
ROTATION_KEY = "rotation"
#: Variant key: ``{"<area id>": {"preset": "glass"}}`` — what this variant
#: shows in its panes when nobody hung anything (a door's glass). Checked
#: against THAT variant's file areas; the recipe lays ``slot_values`` over it.
AREA_DEFAULTS_KEY = "area_defaults"
#: FILE-sidecar key: why the last automatic run on this file stored no areas
#: ("" / absent when it succeeded) — the tab shows it, the landing never
#: fails on it.
AREAS_ERROR_KEY = "areas_error"
#: FILE-sidecar key: the note of a run that WORKED and found nothing to cut
#: (today only :data:`NO_LEAF_NOTE`). Its own key since v2, so no reader has
#: to tell a note from a failure by its text.
AREAS_WARNING_KEY = "areas_warning"
#: FILE-sidecar key: ISO stamp of the last detection/split run (system time).
AREAS_RUN_AT_KEY = "areas_run_at"
#: FILE-sidecar key: which kinds the last AUTOMATIC run on this file actually
#: searched (ruling V2: ``key_areas`` is the prop's wish for the next
#: generation, this is what a run did).
KEY_AREAS_RUN_KEY = "key_areas_run"
#: MODEL-sidecar key of a split file: the ONE area the run that made it was
#: ABOUT — the renamed or the dissolved id. A detection is about the mesh and
#: leaves it empty; a rename or a delete names exactly one area, and that is
#: what the gallery row has to say instead of listing the whole result (v2 E4).
AREAS_AREA_KEY = "areas_area"
#: FILE-sidecar key of a LOW file: the FULL file it inherits areas, leaf box
#: and orientation from — Decimate keeps node names and materials (measured),
#: so the distance mesh is the same object and re-measures nothing.
INHERITS_FROM_KEY = "inherits_from"
#: Every area field a model FILE's sidecar may carry — what
#: :func:`set_file_areas` accepts and :func:`_copy_variant_mesh` carries over.
FILE_AREAS_KEYS = (AREAS_KEY, LEAF_BBOX_KEY, ROTATION_KEY, AREAS_RUN_AT_KEY,
                   AREAS_ERROR_KEY, AREAS_WARNING_KEY, KEY_AREAS_RUN_KEY)
#: The three of them a LOW file copies from its full file at the LOD build.
_INHERITED_AREAS_KEYS = (AREAS_KEY, LEAF_BBOX_KEY, ROTATION_KEY)
#: The ``areas_warning`` of a run that looked for the door leaf and found
#: none — the tab shows it; the areas the run DID find stay as they are.
NO_LEAF_NOTE = "no door leaf found — draw it with the polygon tool"
#: The ``areas_warning`` of a run that left a leaf with frame faces still
#: standing inside its outline (``leaf_residual`` of the script, spec
#: -bild-props-v2.md E2): a skin cut that is "shut and open at once" must
#: never stay silent. ``{n}`` is the count; the client renders the English
#: text and its translation from the same template.
LEAF_RESIDUAL_NOTE = ("{n} frame faces remain inside the leaf footprint — "
                      "draw the leaf again or check the door")
#: How an area came to be: found on the atlas, drawn by the admin, or
#: ADOPTED from a material the modeller named (E6). Only ``auto`` areas
#: are dissolved by the next automatic run (R14: what somebody authored —
#: by hand or by naming — stays).
AREA_SOURCES = ("auto", "manual", "adopt")
#: The size filter of the automatic detection (§ 2 "Mindestgrößen"): a patch
#: below EITHER bound is noise at a frame edge, not a panel.
MIN_AREA_M2 = 0.02
MIN_AREA_FACES = 12
#: Ceiling on a hand-picked face list — a polygon pick over a real prop mesh
#: is thousands of triangles, never hundreds of thousands; more than this is
#: a client defect, refused before a Blender process is spent on it.
MAX_MANUAL_FACES = 200_000
#: The per-mesh companion file: ``model_<ts>.glb`` -> ``model_<ts>.glb.areas.json``.
#: Not a gallery name (the stem pattern wants ``.glb`` last) and not the
#: mesh's own ``.json`` sidecar, which describes the generation run.
AREAS_SIDECAR_SUFFIX = ".areas.json"
_AREA_ID_RE = re.compile(r"^(" + "|".join(COLOUR_KINDS) + r")_([1-9][0-9]*)$")
#: Variant key: WHAT this variant shows in which area (spec-picture-props.md
#: § 1, D2) — ``{"picture_1": {"image": "<url>"}, "glass_1": {"preset":
#: "glass"}}``. A picture assignment IS a variant of the frame prop, so the
#: values ride on the variant entry and nowhere else; the recipe merges them
#: over :data:`AREA_DEFAULTS_KEY`.
SLOT_VALUES_KEY = "slot_values"
#: Variant key: the name the strip lists a picture variant under (derived
#: from the picture file names when the admin types none).
VARIANT_LABEL_KEY = "label"
#: MODEL-sidecar key of a mesh that was COPIED from another variant (R4):
#: ``{"file": <source file name>, "signature": <source gallery signature>}``.
#: A picture variant carries a copy of the frame, so it goes stale as soon as
#: the primary variant's ACTIVE full mesh is no longer that file.
COPIED_FROM_KEY = "copied_from"
#: What a variant COPY carries over from the run that made its source mesh —
#: the same three facts :func:`_land_split` keeps.
_COPIED_RUN_KEYS = ("backend", "face_num", "texture_size")
#: Ceiling on a variant label — a name, not a description.
VARIANT_LABEL_MAX = 120

#: Variant keys: what THIS version of the object should cost in triangles
#: (spec-bild-props-v2.md E5). Absence is the default — the backend's own
#: face count for the full mesh, the configured ratio for the distance mesh —
#: so a prop nobody dialled behaves exactly as it did before the fields
#: existed. Set, they are the DEFAULT of three readers: :func:`_generate`,
#: the automatic improvement (which goes through it) and the CPU distance
#: mesh; an explicit run argument always wins over them.
TARGET_FACES_HIGH_KEY = "target_faces_high"
TARGET_FACES_LOW_KEY = "target_faces_low"
#: The window a face budget has to fall in. The floor is what separates a
#: budget from a typing slip (a 99-triangle prop is not a thing anybody
#: wants), the ceiling is well above every backend's own cap — the clamp to
#: the BACKEND happens per run, this is only the field's own sanity.
FACE_TARGET_MIN = 100
FACE_TARGET_MAX = 2_000_000
#: MODEL-sidecar key: why the file has fewer faces than its variant asked for
#: ('' / absent = it got what was asked). Written when the effective target
#: was over the backend's ``face_num_max``, shown on the gallery row.
FACE_TARGET_NOTE_KEY = "face_target_note"
#: Bounds of the Decimate ratio an absolute low target is turned into. Blender
#: reduces by FRACTION, so the target only becomes a ratio against the source's
#: own triangle count — and a ratio outside these bounds is either a mesh that
#: collapses into nothing or a "reduction" that reduces nothing.
LOD_RATIO_MIN = 0.02
LOD_RATIO_MAX = 0.95

#: How much of a placed prop's DEPTH survives its cut (§ B2 addendum
#: 2026-08-23) — a fraction, 1.0 = the whole prop. The floor never reaches 0:
#: an infinitely thin slab is a prop nobody can see and an authoring slip that
#: looks like a lost placement, so the dial stops at 5 %.
CUT_KEEP_MIN = 0.05

# Marker fractions may leave the raw bounding box: half a box below and a
# full box above on every axis — the HEIGHT axis also reaches a full box
# below (deep seats in tall machines); see ``sanitize_markers``.
# Flag for the one-time "marker names the surface" lift (see
# migrate_marker_surface_once).
_MARKER_SURFACE_FLAG = "world.migration.prop_marker_surface"
MARKER_AT_MIN = -0.5
MARKER_AT_MAX = 2.0
MARKER_AT_Y_MIN = -1.0

_PROP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
#: The canonical model URL this module hands out — site-relative, no query,
#: nothing after ``/model``. Parsing it back (``prop_id_from_model_url``) is
#: how a stored reference becomes a prop id again.
_MODEL_URL_RE = re.compile(r"^/assets/props/([^/?#]+)/model$")

_lock = threading.Lock()
# Running generation job keys "<prop_id>|<backend glob>" (see A2 generation
# chain) — a prop may be regenerated on a DIFFERENT backend concurrently (each
# serializes on its own GPU channel); only the same prop+backend double-click
# is rejected.
_generating: set = set()
# Props whose distance mesh is being built right now (one build per prop).
_lod_building: set = set()
# Props whose walking surface is being baked right now (spec-surface-height
# § 5). The bake writes a file per variant under the PROP's orientation fix, so
# two runs on one prop would race for the same files and the loser's rotation
# on disk makes every reader reject the lattice.
_surface_building: set = set()


class SurfaceBakeRunning(RuntimeError):
    """A bake of this prop's surface is running — the caller asked for
    something that would race it (:func:`delete_surface_for`). The route turns
    this into 409: the very next thing the running job does is write the file
    again, so a delete that "succeeded" would leave the admin looking at a
    lattice they just removed."""


# Props asked for again WHILE their bake was running, and whether that request
# wanted a forced bake. Dropping such a request would lose exactly the fix the
# admin just dialled, so the running job takes one more turn instead.
_surface_dirty: Dict[str, bool] = {}
# Props whose distance-mesh build FAILED in this process. The automatic path
# skips them from then on: the demand comes from payload builds, so without
# this memory every poll would start the same doomed reduction again. The
# admin's explicit button ignores it and clears the entry on success. Not
# persisted — a restart (new Blender, new config) is a fair reason to retry.
# A FAILED button click lands in here too, and thereby also silences the
# automatic path for that prop: deliberate. The failure is an environment
# problem (Blender missing, mesh broken) — fix it and press the button again.
_lod_failed: set = set()
# Models whose bbox extraction already failed, keyed by (prop_id, model mtime)
# — keeps the lazy backfill from re-parsing an unmeasurable GLB on every
# listing. A restart or a re-upload retries.
_bbox_failed: set = set()


# ── Directories / id helpers ────────────────────────────────────────────

def _props_dir(*, create: bool = False) -> Path:
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "props"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def safe_prop_id(prop_id: str) -> str:
    """Normalized prop id ('' = invalid) — lowercase, url/file-safe, no escapes."""
    prop_id = (prop_id or "").strip().lower()
    return prop_id if _PROP_ID_RE.match(prop_id) else ""


def _prop_dir(prop_id: str, *, create: bool = False) -> Optional[Path]:
    """``props/<prop_id>`` — created only on write paths (a read must not
    conjure a ghost directory). None for an invalid id."""
    pid = safe_prop_id(prop_id)
    if not pid:
        return None
    d = _props_dir() / pid
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def prop_dir(prop_id: str, *, create: bool = False) -> Optional[Path]:
    """The prop's directory, for callers that store their own artefacts beside
    its model. Same rule as the internal reader: nothing is created unless
    asked for."""
    return _prop_dir(prop_id, create=create)


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:40] or "prop"


def _new_prop_id(name: str) -> str:
    """slug(name) + short hash; bumps the hash on the (very unlikely) collision."""
    slug = _slugify(name)
    n = 0
    while True:
        seed = f"{slug}:{time.time()}:{n}"
        pid = f"{slug}-{hashlib.md5(seed.encode()).hexdigest()[:6]}"
        if not (_props_dir() / pid).exists():
            return pid
        n += 1


# ── Sidecar read / write ────────────────────────────────────────────────

def _sidecar_path(prop_id: str) -> Optional[Path]:
    d = _prop_dir(prop_id)
    return (d / SIDECAR_NAME) if d else None


def read_sidecar(prop_id: str) -> Dict[str, Any]:
    sp = _sidecar_path(prop_id)
    if sp and sp.exists():
        try:
            meta = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                return meta
        except (OSError, ValueError):
            pass
    return {}


def _write_sidecar(prop_id: str, meta: Dict[str, Any]) -> None:
    d = _prop_dir(prop_id, create=True)
    if not d:
        raise ValueError("bad prop id")
    (d / SIDECAR_NAME).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    # A prop's markers are part of the seat inventory of every room it
    # stands in — the sidecar is where they change.
    from app.core import places; places.invalidate()


# ── Model variants ──────────────────────────────────────────────────────

def variant_max() -> int:
    """How many ACTIVE model variants one prop may carry — config
    ``image_generation.prop_variant_max`` (default 4), clamped to 1…16.

    The cap is on the ACTIVE ones, because that is what costs: every active
    variant is another mesh a client downloads for the same object."""
    from app.core import config as _cfg
    try:
        v = int(_cfg.get("image_generation.prop_variant_max",
                         DEFAULT_VARIANT_MAX) or DEFAULT_VARIANT_MAX)
    except (TypeError, ValueError):
        v = DEFAULT_VARIANT_MAX
    return max(1, min(v, VARIANT_MAX_CAP))


def _variant_list(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The prop's ordered variant records, sanitized:
    ``[{"stem": str, "active": bool}, …]``.

    A record without the key — every prop that predates the feature — has
    exactly ONE variant on the historic ``model`` stem. Entries with an
    unusable or duplicate stem are dropped individually; an empty result
    falls back to that same single primary variant, so this never answers
    with "this prop has no variants at all".

    A non-primary variant's SOURCE-IMAGE provenance rides along under
    ``image`` (the base stem keeps its four master-record keys instead) —
    every writer stores the sanitized list back, so it has to survive here.

    A PICTURE VARIANT's ``slot_values`` and its ``label`` survive here too
    (spec-picture-props.md § 1) — the pictures ARE what makes that variant a
    version of the frame prop.

    ``seasons`` (E2c) survives by the same law as ``description``,
    ``ground_offset_m`` and ``markers`` (2026-08-25): kept when it says
    something, dropped when it is empty/blank/zero — the default is stored as
    ABSENCE and in no other shape.

    THE THREE DIMS ARE DIFFERENT: they are MANDATORY, because nothing is left
    to inherit. Every entry comes out with three usable metres, clamped exactly
    as the field is written (:func:`_coerce_dim_m`, (0, 100]); junk, zero, a
    negative value or a missing key are hand-edits, not statements, and read
    back as the ``DEFAULT_DIM_M`` cube rather than as "no size".
    """
    raw = meta.get(VARIANTS_KEY) if isinstance(meta, dict) else None
    out: List[Dict[str, Any]] = []
    seen: set = set()
    if isinstance(raw, list):
        for entry in raw[:VARIANT_MAX_CAP]:
            if not isinstance(entry, dict):
                continue
            stem = str(entry.get("stem") or "").strip()
            if not _VARIANT_STEM_RE.match(stem) or stem in seen:
                continue
            seen.add(stem)
            rec: Dict[str, Any] = {"stem": stem,
                                   "active": bool(entry.get("active", True))}
            img = entry.get("image")
            if isinstance(img, dict):
                rec["image"] = {k: str(img.get(k) or "") for k in IMAGE_META_KEYS}
            # Provenance of the EXTRA views (design 2026-09-02) — same shape
            # as `image`, one record per view that has one.
            views = entry.get(IMAGE_VIEWS_KEY)
            if isinstance(views, dict):
                kept = {v: {k: str((r or {}).get(k) or "") for k in IMAGE_META_KEYS}
                        for v, r in views.items()
                        if v in EXTRA_VIEWS and isinstance(r, dict)}
                if kept:
                    rec[IMAGE_VIEWS_KEY] = kept
            seasons = sanitize_season_tags(entry.get(SEASONS_KEY))
            if seasons:
                rec[SEASONS_KEY] = seasons
            desc = _coerce_description(entry.get(DESCRIPTION_KEY))
            if desc:
                rec[DESCRIPTION_KEY] = desc
            for key in DIM_KEYS:
                rec[key] = _coerce_dim_m(entry.get(key))
            rec[DIMS_ESTIMATED_KEY] = bool(entry.get(DIMS_ESTIMATED_KEY))
            off = _coerce_ground_offset_m(entry.get(GROUND_OFFSET_KEY))
            if off is not None:
                rec[GROUND_OFFSET_KEY] = off
            markers = sanitize_markers(entry.get(MARKERS_KEY))
            if markers:
                rec[MARKERS_KEY] = markers
            values = _coerce_slot_values(entry.get(SLOT_VALUES_KEY))
            if values:
                rec[SLOT_VALUES_KEY] = values
            # …and its PANE DEFAULTS (v2 E1): they describe this variant's
            # own mesh, so they live beside the pictures hung on it.
            defaults = _coerce_area_defaults(entry.get(AREA_DEFAULTS_KEY))
            if defaults:
                rec[AREA_DEFAULTS_KEY] = defaults
            label = _coerce_variant_label(entry.get(VARIANT_LABEL_KEY))
            if label:
                rec[VARIANT_LABEL_KEY] = label
            # …and what this version should COST in triangles (v2 E5). Same
            # law as `seasons` and the ground offset: a variant that states
            # nothing stores no key, and the backend/config default stands.
            for key in (TARGET_FACES_HIGH_KEY, TARGET_FACES_LOW_KEY):
                faces = _coerce_face_target(entry.get(key))
                if faces:
                    rec[key] = faces
            out.append(rec)
    return out or [_new_variant_entry(MODEL_STEM)]


def _new_variant_entry(stem: str) -> Dict[str, Any]:
    """A variant record with nothing authored on it: the placeholder cube,
    still estimated, no subject, on the ground, no markers.

    This is what a record WITHOUT the variants key answers with — a prop whose
    sidecar was hand-emptied — and the seed :func:`add_variant` copies over.
    """
    return {"stem": stem, "active": True,
            **{k: DEFAULT_DIM_M for k in DIM_KEYS},
            DIMS_ESTIMATED_KEY: True}


def _free_stem(entries: List[Dict[str, Any]]) -> str:
    """The next unused variant stem — the base stem when it is free, else
    ``model-v<n>`` with the smallest free n. A DELETED variant frees its stem
    again; that is fine, its files went with it."""
    used = {e["stem"] for e in entries}
    if MODEL_STEM not in used:
        return MODEL_STEM
    for n in range(2, VARIANT_MAX_CAP + 2):
        stem = f"{MODEL_STEM}-v{n}"
        if stem not in used:
            return stem
    return ""


def _active_indices(entries: List[Dict[str, Any]]) -> List[int]:
    """Indices of the ACTIVE variants, in order, capped at :func:`variant_max`.
    A list without a single active entry answers with the first one — a prop
    that renders nothing at all is a state the ``__none__`` selection sentinel
    already owns, and it must not be reachable by toggling."""
    idx = [i for i, e in enumerate(entries) if e.get("active")]
    return (idx or [0])[:variant_max()]


def _effective_indices(entries: List[Dict[str, Any]]) -> List[int]:
    """Indices of the variants that render RIGHT NOW — manually active AND in
    season (E2c).

    A variant may declare the seasons it depicts (``seasons``, names from the
    world's ``game_seasons``, matched case-insensitively). Effectively active =
    manually active AND (no seasons OR the current GAME season is among them).
    This is the ONE gate: the scene payload, the terrain scatter, the world
    props and every serving URL inherit it from here.

    Two guarantees hold it together:

    * NO TAG ANYWHERE, NO CLOCK. A prop whose variants carry no ``seasons``
      takes the first branch and never reads the calendar — its answer is
      character for character the pre-feature one, and the feature costs it
      nothing.
    * A PLACEMENT IS NEVER A HOLE. If the season filter empties the set — every
      variant of the prop is out of season — the manual set stands. Seasonal
      DISAPPEARANCE is not what this does: a prop nobody tagged for summer must
      not vanish from every room for three seasons, the same reason
      :func:`_active_indices` refuses to answer with an empty list. Tag ONE
      variant per season to swap them; tag all of them with the same season and
      you get that season's look all year.
    """
    idx = _active_indices(entries)
    if not any(e.get(SEASONS_KEY) for e in entries):
        return idx
    now = current_season_tokens()
    in_season = [i for i in idx
                 if season_tags_active(entries[i].get(SEASONS_KEY), now)]
    return in_season or idx


def _stem_of(prop_id: str, variant: Any = None,
             meta: Optional[Dict[str, Any]] = None) -> str:
    """File stem of ONE variant of a prop — ``None`` (or a negative index)
    means the PRIMARY variant, i.e. the first EFFECTIVELY active one. ``''``
    when the index names no variant this prop has."""
    entries = _variant_list(read_sidecar(prop_id) if meta is None else meta)
    if variant is None:
        return entries[_effective_indices(entries)[0]]["stem"]
    try:
        i = int(variant)
    except (TypeError, ValueError):
        return ""
    if i < 0:
        return entries[_effective_indices(entries)[0]]["stem"]
    return entries[i]["stem"] if i < len(entries) else ""


def primary_variant(prop_id: str) -> int:
    """Index of the prop's PRIMARY variant — the first EFFECTIVELY active one
    (:func:`_effective_indices`). This is what every unqualified read resolves
    to (``/model`` without a ``variant`` parameter, the bbox measurement, the
    payload's single ``variants`` map).

    Season-aware ON PURPOSE (E2c): every payload publishes element 0 of the
    effective list under the BARE URL, so the file that URL serves has to be
    the same one — otherwise a season-swapped prop would ship a winter entry
    and serve the summer mesh under it."""
    return _effective_indices(_variant_list(read_sidecar(prop_id)))[0]


def scatter_variant_index(seed: Any, instance: Any, count: Any) -> int:
    """WHICH active variant one scattered copy shows: ``(seed + instance) mod
    count``.

    The one formula behind the whole feature, in one place (§ B2 addendum).
    It is deliberately the cheapest thing that varies: the server resolves it
    per copy into the placement's ``variant`` index, and both renderers read
    that number instead of deriving it — the same copy shows the same mesh in
    the 3D client, in the admin preview and in the numeric smoke.

    ``count`` 0 or less has nothing to choose from and answers 0."""
    try:
        n = int(count)
        if n <= 0:
            return 0
        return (int(seed) + int(instance)) % n
    except (TypeError, ValueError):
        return 0


# ── Field coercion ──────────────────────────────────────────────────────

def _coerce_dim_m(value: Any, fallback: float = DEFAULT_DIM_M) -> float:
    """One real edge in metres — mandatory > 0; clamped to (0, 100], round 3."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if v <= 0:
        return fallback
    return round(min(v, 100.0), 3)


def _coerce_description(value: Any) -> str:
    """A variant's generation subject as it is STORED: stripped free text,
    capped at :data:`DESCRIPTION_MAX`. ``""`` means "write no key at all" —
    a blank line is not an authoring statement, it is the sentence "this
    variant renders from the prop's description"."""
    text = str(value or "").strip()
    return text[:DESCRIPTION_MAX]


def _coerce_sway_factor(value: Any) -> Optional[float]:
    """The wind factor as it is STORED: 0..1 with two decimals, or ``None`` for
    "write no key at all".

    The catalog-number shape rule (``terrain_types._clamped_meta_number``) with
    the ONE difference that matters here: zero is a real answer. A stone that
    stands still in a waving meadow is the whole point of the field, so the
    value that says nothing is not 0.0 but the DEFAULT — an absent key and a
    stored 1.0 would mean exactly the same thing to every reader, and only one
    of them may exist.

    Junk (non-numbers, NaN, inf, an empty string) is no authoring statement
    either and loses the key too. Numbers outside the range are CLAMPED rather
    than refused: a typing slip should cost the limit, never the record.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    v = round(min(max(v, SWAY_FACTOR_MIN), SWAY_FACTOR_MAX), 2)
    return None if v == SWAY_FACTOR_DEFAULT else v


def sway_factor_of(meta: Dict[str, Any]) -> float:
    """The EFFECTIVE wind factor of one sidecar — ``SWAY_FACTOR_DEFAULT``
    whenever the key is absent or unusable.

    Reading is as forgiving as writing is strict: a hand-edited sidecar makes
    its prop bend at the limit instead of at NaN, which would scale a whole
    meadow into an invisible matrix.
    """
    v = _coerce_sway_factor(meta.get("sway_factor"))
    return SWAY_FACTOR_DEFAULT if v is None else v


def _coerce_ground_offset_m(value: Any) -> Optional[float]:
    """A variant's vertical ground offset as it is STORED: ±5 m in CENTIMETRE
    steps, or ``None`` for "write no key at all".

    The same one-representation rule as :func:`_coerce_sway_factor`, with the
    default at the other end of the range: here the value that says nothing IS
    0.0, so a stored 0.0 and an absent key would mean the same thing to every
    reader and only one of them may exist — ABSENCE is the statement.

    Junk (non-numbers, NaN, inf, an empty string) is no authoring statement
    either and loses the key. Numbers outside the range are CLAMPED rather
    than refused: a typing slip should cost the limit, never the record — and
    5 m is already far more than "sink the trunk into the soil" needs.

    Rounded to centimetres, because that is the precision the dial offers and
    the precision a base is worth: a millimetre under a tree is noise that
    would still move every scene signature that hashes it.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    v = round(min(max(v, GROUND_OFFSET_MIN), GROUND_OFFSET_MAX), 2)
    return None if v == GROUND_OFFSET_DEFAULT else v


def _coerce_face_target(value: Any) -> Optional[int]:
    """A face budget as it is READ BACK — ``None`` for "no statement".

    Never raises: a hand-edited sidecar must not take a whole prop record
    down, exactly like :func:`_coerce_ground_offset_m`. The WRITE path is
    :func:`sanitize_face_target`, which refuses junk instead of swallowing it —
    a number the admin typed and that reached nothing is the worse answer.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if FACE_TARGET_MIN <= n <= FACE_TARGET_MAX else None


def sanitize_face_target(value: Any) -> Optional[int]:
    """A face budget as it is WRITTEN: ``None`` (or an empty string) CLEARS
    the field, an integer in ``FACE_TARGET_MIN … FACE_TARGET_MAX`` is stored,
    anything else raises ``ValueError``.

    Out-of-window numbers are REFUSED, not clamped — unlike the ground offset,
    where a slip costs the limit. A face budget is what a GPU job is billed
    for: 99 is a slipped digit and 5,000,000 is a run nobody meant to start,
    and quietly turning either into the nearest legal value would hide the
    typo behind a green "Saved".
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"face target must be a whole number: {value!r}") from None
    if not FACE_TARGET_MIN <= n <= FACE_TARGET_MAX:
        raise ValueError(f"face target must be between {FACE_TARGET_MIN} and "
                         f"{FACE_TARGET_MAX}: {n}")
    return n


def _variant_entry(meta: Dict[str, Any], variant: Any = None) -> Dict[str, Any]:
    """ONE sanitized variant record — THE index resolution every per-variant
    read shares (2026-08-25).

    ``variant`` is the STORE index (the position in ``model_variants``, the
    same number every variant-scoped route and every serving URL uses).
    ``None``, a negative index or one this prop has no variant for answers for
    the PRIMARY variant — the first effectively active one, exactly like every
    other unqualified read in this module (``/model`` without a parameter, the
    bbox measurement, the payload's single ``variants`` map).

    Written once and called by :func:`variant_dims`,
    :func:`variant_description`, :func:`variant_ground_offset`,
    :func:`variant_markers` and :func:`variant_face_targets`, so "which
    variant is this" cannot drift between the fields the variant owns.
    """
    entries = _variant_list(meta)
    try:
        i = -1 if variant is None else int(variant)
    except (TypeError, ValueError):
        i = -1
    if not 0 <= i < len(entries):
        i = _effective_indices(entries)[0]
    return entries[i]


def oriented_dims(bbox: Any, rotation: Any = None) -> List[float]:
    """``[width, height, depth]`` = the AABB extents of the raw mesh box AFTER
    the orientation fix: the 8 corners are rotated by Rx·Ry·Rz (degrees,
    three.js 'XYZ' Euler order) and re-measured. Empty list when the box is
    unusable.

    Rotating an AABB overestimates for non-90° fixes (it measures a box around
    the box), which is fine and deterministic — the numbers are used as
    PROPORTIONS, not as a hull. Kept in lockstep with
    ``frontend/src/tabs/props/dims.ts`` (``orientedDims``) — change both or
    neither.
    """
    try:
        b = [abs(float(bbox[i])) for i in range(3)]
    except (TypeError, ValueError, IndexError, KeyError):
        return []
    if max(b) <= 0:
        return []
    rot = rotation if isinstance(rotation, dict) else {}
    try:
        rx = math.radians(float(rot.get("x") or 0))
        ry = math.radians(float(rot.get("y") or 0))
        rz = math.radians(float(rot.get("z") or 0))
    except (TypeError, ValueError):
        rx = ry = rz = 0.0
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # M = Rx · Ry · Rz
    m = [
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]
    half = [v / 2 for v in b]
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in (-1, 1):
        for j in (-1, 1):
            for k in (-1, 1):
                p = (i * half[0], j * half[1], k * half[2])
                for r in range(3):
                    v = m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2]
                    lo[r] = min(lo[r], v)
                    hi[r] = max(hi[r], v)
    return [round(hi[r] - lo[r], 5) for r in range(3)]


def _dims_from_size(size_m: Any, bbox: Any = None,
                    rotation: Any = None) -> Dict[str, float]:
    """Spread ONE real size (the largest edge in metres) over the three dims
    using the model's proportions. Without a bbox every dim becomes that size
    (a placeholder cube). ESTIMATES round to 2 decimals — centimetres are
    plenty for furniture, longer tails just look like precision that is not
    there (admin-typed values keep the 3-decimal coercion)."""
    size = _coerce_dim_m(size_m, DEFAULT_DIM_M)
    od = oriented_dims(bbox, rotation) if bbox else []
    if od and max(od) > 0:
        f = size / max(od)
        return {"width_m": max(round(od[0] * f, 2), 0.01),
                "height_m": max(round(od[1] * f, 2), 0.01),
                "depth_m": max(round(od[2] * f, 2), 0.01)}
    return {"width_m": size, "depth_m": size, "height_m": size}


def variant_dims(meta: Dict[str, Any], variant: Any = None) -> Dict[str, float]:
    """The three real metres ONE variant renders at —
    ``{"width_m", "depth_m", "height_m"}``.

    Variant-only since 2026-08-25: there is no prop-level size to fall back to,
    so this is a plain read of the entry :func:`_variant_entry` resolves, with
    the same clamp the field is written under. A hand-emptied entry reads back
    as the ``DEFAULT_DIM_M`` cube — a prop that renders at nothing is not a
    state a payload may carry.
    """
    entry = _variant_entry(meta, variant)
    return {key: _coerce_dim_m(entry.get(key)) for key in DIM_KEYS}


def variant_dims_estimated(meta: Dict[str, Any], variant: Any = None) -> bool:
    """Are this variant's three dims still the placeholder cube? True until an
    admin types a size or the mesh proportions redistribute them."""
    return bool(_variant_entry(meta, variant).get(DIMS_ESTIMATED_KEY))


def variant_description(meta: Dict[str, Any], variant: Any = None) -> str:
    """The GENERATION SUBJECT one variant's product shot is rendered from —
    ``""`` when it authors none, and then the caller falls back to the prop's
    NAME (``_render_source``), which is the rule that predates the field.

    Variant-only since 2026-08-25: every render of a product shot goes through
    here, so "which sentence was this picture made from" has one answer and not
    one per call site.
    """
    return _coerce_description(_variant_entry(meta, variant).get(DESCRIPTION_KEY))


def variant_ground_offset(meta: Dict[str, Any], variant: Any = None) -> float:
    """How deep ONE variant stands in the ground — ``GROUND_OFFSET_DEFAULT``
    whenever the key is absent or unusable.

    Reading is as forgiving as writing is strict: a hand-edited sidecar puts
    its prop on the ground instead of at NaN, which would take a whole scene
    payload down with it.
    """
    v = _coerce_ground_offset_m(_variant_entry(meta, variant).get(GROUND_OFFSET_KEY))
    return GROUND_OFFSET_DEFAULT if v is None else v


def variant_markers(meta: Dict[str, Any], variant: Any = None) -> List[Dict[str, Any]]:
    """The OBJECT-LOCAL place markers of ONE variant (``[]`` when it has
    none). The fractions are of THAT mesh's bounding box, which is why they
    are the variant's and never the prop's (2026-08-25)."""
    return sanitize_markers(_variant_entry(meta, variant).get(MARKERS_KEY))


def variant_slot_values(meta: Dict[str, Any],
                        variant: Any = None) -> Dict[str, Dict[str, str]]:
    """WHAT one variant shows in the prop's picture areas (``{}`` when it
    shows nothing of its own) — the picture rides on the VARIANT, so this is
    the only place a payload asks for it (spec-picture-props.md § 1)."""
    return _coerce_slot_values(
        _variant_entry(meta, variant).get(SLOT_VALUES_KEY))


def variant_area_defaults(meta: Dict[str, Any],
                          variant: Any = None) -> Dict[str, Dict[str, str]]:
    """What one variant shows in its PANES when nobody hung anything
    (``{}`` = nothing) — the defaults ride on the variant since v2 E1,
    because they describe that variant's own mesh."""
    return _coerce_area_defaults(
        _variant_entry(meta, variant).get(AREA_DEFAULTS_KEY))


def _coerce_area_defaults(raw: Any) -> Dict[str, Dict[str, str]]:
    """A stored ``area_defaults`` object as it is READ BACK — junk dropped
    entry by entry, like :func:`_coerce_slot_values`; the check against the
    file's areas belongs where the value is WRITTEN
    (:func:`sanitize_area_defaults`)."""
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    for area_id, value in raw.items():
        aid = str(area_id or "").strip().lower()
        if not _AREA_ID_RE.match(aid) or not isinstance(value, dict):
            continue
        preset = str(value.get("preset") or "").strip()
        if preset:
            out[aid] = {"preset": preset}
    return out


def _coerce_tags(raw: Any) -> List[str]:
    """Free-text tags — accepts a list or a comma/newline string; deduped
    case-insensitively, capped at 30."""
    if isinstance(raw, str):
        raw = re.split(r"[,\n]", raw)
    if not isinstance(raw, (list, tuple)):
        return []
    seen: set = set()
    out: List[str] = []
    for t in raw:
        t = str(t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:30]


def _sanitize_rotation(raw: Any, cur: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Orientation fix {x,y,z} in degrees — FREE values, 0.1° resolution
    (meshes come out slightly tilted, not just axis-swapped; pattern
    ``location_model3d.set_rotation``). Whole numbers stay ints (no 90.0 noise)."""
    cur = cur if isinstance(cur, dict) else {}
    src = raw if isinstance(raw, dict) else {}
    rot: Dict[str, float] = {}
    for axis in ("x", "y", "z"):
        try:
            v = float(src.get(axis, cur.get(axis, 0)) or 0)
        except (TypeError, ValueError):
            try:
                v = float(cur.get(axis, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
        v = round(v % 360, 1)
        rot[axis] = int(v) if float(v).is_integer() else v
    return rot


def sanitize_markers(raw: Any) -> List[Dict[str, Any]]:
    """Object-local place markers (A4, plan-posen-plaetze.md). Same vocabulary
    as ``layout.markers`` — ``group`` = a PLACE TYPE of the pose catalog
    (``pose_catalog.get_groups()``), ``id`` stable,
    ``capacity``/``spacing_m``/``slot_axis`` for a place that seats several,
    ``facing`` = degrees (0 south / 90 east / 180 north / 270
    west, absent = client default) — but ``at`` is an OBJECT-LOCAL
    ``[u, v, w]`` (three fractions of the model bounding box) instead of a
    room ``[x, y]``.

    The fractions may exceed 0..1 — half a box below, a full box above
    (``[-0.5, 2.0]``): a seat or lying surface often sits ON the hull edge or
    outside it, and the old hard 0..1 clamp made those markers impossible to
    place (the Seated Row Machine finding); the top of a bed with the restored
    hips law needs the full box above. ``compose_prop_marker``
    multiplies the fractions linearly, so out-of-range values compose
    correctly without any change there.

    Invalid entries are dropped individually; capped at 50."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        group = str(m.get("group") or "").strip().lower()
        at = m.get("at")
        if not group or not isinstance(at, (list, tuple)) or len(at) != 3:
            continue
        try:
            at3 = [round(min(max(float(at[i]),
                                 MARKER_AT_Y_MIN if i == 1 else MARKER_AT_MIN),
                             MARKER_AT_MAX), 4)
                   for i in range(3)]
        except (TypeError, ValueError):
            continue
        entry: Dict[str, Any] = {"id": _place_id(m.get("id")), "group": group,
                                 "at": at3}
        cap = _capacity(m.get("capacity"))
        if cap > 1:
            entry["capacity"] = cap
            entry["spacing_m"] = _spacing(m.get("spacing_m"))
            entry["slot_axis"] = _slot_axis(m.get("slot_axis"))
        fac = m.get("facing")
        if fac is not None and f"{fac}".strip() != "":
            try:
                entry["facing"] = int(round(float(fac))) % 360
            except (TypeError, ValueError):
                pass
        out.append(entry)
    return out[:50]


# ── Texture slots ───────────────────────────────────────────────────────

def _slot_kind(name: str) -> str:
    """Whether a slot of this NAME takes a picture or a look. One rule for both
    spellings, so ``slot_glass`` and ``glass`` never disagree.

    The PREFIX rule (spec-picture-props.md § 1): a split writes numbered
    areas ``slot_glass_<k>`` / ``slot_picture_<k>``, so the first ``_``-token
    of the name decides too — ``glass_1`` is a material slot, ``picture_2``
    an image one. Whole token only: ``glassy`` is not glass.
    """
    if name in MATERIAL_SLOT_NAMES:
        return "material"
    return "material" if name.split("_", 1)[0] in MATERIAL_SLOT_NAMES else "image"


def detect_slots(material_names: Any) -> List[Dict[str, str]]:
    """THE detection rule (Entscheid 4): which of a model's MATERIAL NAMES are
    texture slots. This function is the only place it is stated.

    For every name, lower-cased and stripped:

    * ``slot_<name>`` → a slot called ``<name>``; its kind is ``material`` for
      the names in :data:`MATERIAL_SLOT_NAMES` (whole, or as the first
      ``_``-token: ``glass_1``), ``image`` otherwise. The prefix is the OPEN
      half of the convention — anything can be a slot if the modeller says so.
    * a whole name out of :data:`BARE_SLOT_NAMES` → the same slot under that
      name (so ``picture`` / ``screen`` / ``sign`` are image slots and ``glass``
      is a material one),
    * anything else → no slot.

    Names come back LOWER-CASE, de-duplicated, in order of first appearance —
    so the list reads like the material list of the model, and a mesh that
    names the same surface twice yields one slot.
    """
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in (material_names or []):
        key = str(raw or "").strip().lower()
        if key.startswith(SLOT_PREFIX):
            # Stripped AGAIN behind the prefix: "slot_ poster" is a modeller's
            # typo, not a slot called " poster" that nothing would ever match.
            name = key[len(SLOT_PREFIX):].strip()
        elif key in BARE_SLOT_NAMES:
            name = key
        else:
            continue
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "kind": _slot_kind(name)})
    return out


def sanitize_slots(raw: Any) -> List[Dict[str, str]]:
    """The stored shape of an AUTHORED slot list — or ``ValueError``.

    Junk is refused rather than dropped: unlike the markers, where an unusable
    entry costs one spot on a mesh, a silently swallowed slot would report
    "Saved" over a surface that stays unfillable. Names are lower-cased (the
    detection stores them that way, and a slot is matched against a material
    name), and a name given twice collapses to its FIRST entry.
    """
    if not isinstance(raw, list):
        raise ValueError("slots must be a list of {name, kind} objects")
    out: List[Dict[str, str]] = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("each slot must be an object {name, kind}")
        name = str(entry.get("name") or "").strip().lower()
        if not name:
            raise ValueError("a slot needs a name")
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in SLOT_KINDS:
            raise ValueError(f"unknown slot kind {kind!r} (known: "
                             + ", ".join(SLOT_KINDS) + ")")
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "kind": kind})
    return out


def sanitize_key_areas(raw: Any) -> List[str]:
    """The requested kinds as a subset of ``AREA_KINDS`` in that order,
    de-duplicated — or ``ValueError`` for an unknown kind (a silently
    dropped kind would report "Saved" over a request that reached nothing).
    ``leaf`` is accepted: it asks for the door-leaf cut on every landing and
    adds no prompt text. ``None`` / an empty list is "no key areas"."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("key_areas must be a list of kinds "
                         + "(" + ", ".join(AREA_KINDS) + ")")
    wanted = set()
    for entry in raw:
        kind = str(entry or "").strip().lower()
        if kind not in AREA_KINDS:
            raise ValueError(f"unknown key area kind {kind!r} (known: "
                             + ", ".join(AREA_KINDS) + ")")
        wanted.add(kind)
    return [k for k in AREA_KINDS if k in wanted]


def _coerce_vec(raw: Any, n: int, label: str) -> List[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != n:
        raise ValueError(f"{label} must be a list of {n} numbers")
    try:
        return [float(v) for v in raw]
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a list of {n} numbers") from None


def sanitize_areas(raw: Any) -> List[Dict[str, Any]]:
    """The stored shape of the area list — or ``ValueError``.

    Every entry is ``{id, kind, size_m, normal, source, faces}``, with the
    ``id`` spelling its kind (``picture_1`` is a picture; the door leaf is
    ``id == kind == "leaf"``, at most once) and optional ``origin`` (material
    the faces came from) / ``centroid``. Optional keys are kept only when
    given — the list round-trips byte for byte."""
    if not isinstance(raw, list):
        raise ValueError("areas must be a list")
    out: List[Dict[str, Any]] = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("each area must be an object")
        area_id = str(entry.get("id") or "").strip().lower()
        m = _AREA_ID_RE.match(area_id)
        if area_id == LEAF_KIND:
            id_kind = LEAF_KIND
        elif m:
            id_kind = m.group(1)
        else:
            raise ValueError(f"bad area id {area_id!r} (expected <kind>_<k> or leaf)")
        kind = str(entry.get("kind") or id_kind).strip().lower()
        if kind != id_kind:
            raise ValueError(f"area {area_id!r} cannot be of kind {kind!r}")
        if area_id in seen:
            raise ValueError(f"area {area_id!r} listed twice")
        seen.add(area_id)
        source = str(entry.get("source") or "auto").strip().lower()
        if source not in AREA_SOURCES:
            raise ValueError(f"unknown area source {source!r}")
        try:
            faces = int(entry.get("faces") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"area {area_id!r}: faces must be an integer") from None
        if faces < 0:
            raise ValueError(f"area {area_id!r}: faces must be >= 0")
        item: Dict[str, Any] = {
            "id": area_id,
            "kind": kind,
            "size_m": _coerce_vec(entry.get("size_m"), 2, f"area {area_id!r}: size_m"),
            "normal": _coerce_vec(entry.get("normal"), 3, f"area {area_id!r}: normal"),
            "source": source,
            "faces": faces,
        }
        if entry.get("origin"):
            item["origin"] = str(entry["origin"])
        if entry.get("centroid") is not None:
            item["centroid"] = _coerce_vec(entry.get("centroid"), 3,
                                           f"area {area_id!r}: centroid")
        out.append(item)
    return out


def sanitize_area_defaults(raw: Any,
                           areas: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """``{"<area id>": {"preset": <SLOT_PRESETS>}}`` checked against the
    prop's areas — an unknown area or preset is ``ValueError``, never a
    silently stored default that no surface answers to.

    The KIND decides, exactly as in :func:`sanitize_variant_slot_values`: a
    prop-wide default is the LOOK of a pane (spec § 1), so only a ``glass``
    area takes one. A picture is hung on a VARIANT of the prop — a prop-wide
    picture would hang the same poster in every room the prop stands in —
    and the door leaf is a node, not a surface (R9)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("area_defaults must be an object {area_id: {preset}}")
    kinds = {str(a.get("id") or ""): str(a.get("kind") or "")
             for a in (areas or [])}
    known = set(kinds)
    out: Dict[str, Dict[str, str]] = {}
    for area_id, value in raw.items():
        aid = str(area_id or "").strip().lower()
        if aid not in known:
            raise ValueError(f"area_defaults names an unknown area {aid!r} "
                             f"(the prop has: {', '.join(sorted(known)) or 'none'})")
        if kinds[aid] == LEAF_KIND:
            # R9: the leaf is a node, not a material — nothing to fill.
            raise ValueError("area_defaults cannot name the door leaf — it is "
                             "a node of the mesh, not a surface")
        if kinds[aid] != "glass":
            raise ValueError(
                f"area_defaults[{aid!r}] is a {kinds[aid]} area — a prop-wide "
                "default is the LOOK of a pane; a picture is hung on a "
                "variant of the prop")
        if not isinstance(value, dict):
            raise ValueError(f"area_defaults[{aid!r}] must be an object {{preset}}")
        preset = str(value.get("preset") or "").strip().lower()
        if not preset:
            raise ValueError(f"area_defaults[{aid!r}] needs a preset "
                             f"(known: {', '.join(SLOT_PRESETS)})")
        if preset not in SLOT_PRESETS:
            raise ValueError(f"area_defaults[{aid!r}]: unknown preset "
                             f"{preset!r} (known: {', '.join(SLOT_PRESETS)})")
        out[aid] = {"preset": preset}
    return out


def sanitize_leaf_bbox(raw: Any) -> Optional[Dict[str, List[float]]]:
    """``{"min": [x, y, z], "max": [x, y, z]}`` with ``min <= max`` per axis
    — or None for ``None``/``{}`` (no leaf), or ``ValueError``."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("leaf_bbox must be an object {min, max}")
    lo = _coerce_vec(raw.get("min"), 3, "leaf_bbox.min")
    hi = _coerce_vec(raw.get("max"), 3, "leaf_bbox.max")
    if any(a > b for a, b in zip(lo, hi)):
        raise ValueError("leaf_bbox: min must not exceed max")
    return {"min": lo, "max": hi}


def is_door_prop(meta: Dict[str, Any]) -> bool:
    """THE convention (plan-door-props-texture-slots.md, mirrored by the
    admin's ``DoorPropPicker``): a door prop is filed under category ``door``
    or carries the tag ``door`` — free strings, compared trimmed and
    case-insensitively. A door prop gets its leaf cut out on every landing
    (spec § 6) even without ``key_areas``."""
    if str(meta.get("category") or "").strip().lower() == "door":
        return True
    return any(str(t or "").strip().lower() == "door" for t in (meta.get("tags") or []))


#: THE TWO URL FORMS a filled image slot may name, and no third. Both are
#: same-origin routes of this server (``routes/world.py`` serves the location
#: gallery, ``routes/characters.py`` the character images), so a value can only
#: ever point at a picture this world owns — never at a foreign host, never at
#: a path outside the two galleries. The shape is the whole check: the file
#: does not have to exist (a picture may be deleted after it was hung, exactly
#: as a prop may be), but its ADDRESS has to be one of these.
#: Kept for variant slot values (picture props).
_SLOT_IMAGE_RE = re.compile(
    r"^/(?:world/locations/[^/?#]+/gallery"
    r"|characters/[^/?#]+/images)/[^/?#]+$")


def sanitize_variant_slot_values(raw: Any,
                                 areas: Sequence[Dict[str, Any]],
                                 ) -> Dict[str, Dict[str, str]]:
    """What ONE picture variant shows, checked against the prop's areas — or
    ``ValueError`` (spec-picture-props.md § 1).

    ``{"<area id>": {"image": "<url>"}}`` on a ``picture`` area,
    ``{"<area id>": {"preset": "<SLOT_PRESETS>"}}`` on a ``glass`` one, and no
    third shape: the KIND of the area decides which key it takes, so a preset
    can never end up on a panel that wants a picture and a picture never on a
    pane. The URL form is one of the two galleries this world serves
    (:data:`_SLOT_IMAGE_RE`) — the file need not exist (a picture may be
    deleted after it was hung, exactly as a prop may be), its ADDRESS has to
    be one of them.

    THIS IS THE ONE GATE. The recipe reads the stored values verbatim and
    validates nothing, so everything that writes them comes through here:
    :func:`set_variant_slot_values` and, before it creates anything,
    :func:`add_picture_variant`.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("slot_values must be an object {area_id: {…}}")
    kinds = {str(a.get("id") or ""): str(a.get("kind") or "")
             for a in (areas or [])}
    out: Dict[str, Dict[str, str]] = {}
    for area_id, value in raw.items():
        aid = str(area_id or "").strip().lower()
        kind = kinds.get(aid)
        if not kind:
            raise ValueError(
                f"slot_values names an unknown area {aid!r} (the prop has: "
                f"{', '.join(sorted(kinds)) or 'none'})")
        if not isinstance(value, dict):
            raise ValueError(f"slot_values[{aid!r}] must be an object")
        if kind == LEAF_KIND:
            # R9: the leaf is a node of the mesh, not a fillable surface.
            raise ValueError(f"slot_values[{aid!r}]: the door leaf is a node, "
                             "not a surface — nothing can be hung on it")
        if kind == "picture":
            if set(value) - {"image"}:
                raise ValueError(f"slot_values[{aid!r}] is a picture area and "
                                 "takes an image and nothing else")
            url = str(value.get("image") or "").strip()
            if not url:
                raise ValueError(f"slot_values[{aid!r}] needs an image URL")
            if not _SLOT_IMAGE_RE.match(url):
                raise ValueError(
                    f"slot_values[{aid!r}]: {url!r} is not a picture of this "
                    "world (/world/locations/<loc>/gallery/<file> or "
                    "/characters/<name>/images/<file>)")
            out[aid] = {"image": url}
        else:
            if set(value) - {"preset"}:
                raise ValueError(f"slot_values[{aid!r}] is a {kind} area and "
                                 "takes a preset and nothing else")
            preset = str(value.get("preset") or "").strip().lower()
            if not preset:
                raise ValueError(f"slot_values[{aid!r}] needs a preset "
                                 f"(known: {', '.join(SLOT_PRESETS)})")
            if preset not in SLOT_PRESETS:
                raise ValueError(f"slot_values[{aid!r}]: unknown preset "
                                 f"{preset!r} (known: "
                                 f"{', '.join(SLOT_PRESETS)})")
            out[aid] = {"preset": preset}
    return out


def _coerce_slot_values(raw: Any) -> Dict[str, Dict[str, str]]:
    """A stored ``slot_values`` object as it is READ BACK: junk is dropped
    entry by entry, exactly like every other variant field.

    Deliberately lenient, unlike :func:`sanitize_variant_slot_values`: a read
    has no area list in hand (the areas describe the PRIMARY mesh and may have
    been re-detected since), and an area deleted after the fact must not make
    the whole variant unreadable. The check belongs where the value is
    WRITTEN."""
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    for area_id, value in raw.items():
        aid = str(area_id or "").strip().lower()
        if not _AREA_ID_RE.match(aid) or not isinstance(value, dict):
            continue
        for key in ("image", "preset"):
            text = str(value.get(key) or "").strip()
            if text:
                out[aid] = {key: text}
                break
    return out


def _coerce_variant_label(value: Any) -> str:
    """A variant's display name as it is STORED: stripped, capped. ``""``
    means "write no key at all" — the strip then shows the derived one."""
    return str(value or "").strip()[:VARIANT_LABEL_MAX]


def default_variant_label(slot_values: Dict[str, Dict[str, str]]) -> str:
    """The name a picture variant lists itself under when the admin typed
    none: the picture FILE NAMES (basename without extension), joined by
    ", ", and the preset name for a glass-only variant.

    Area order, so the same assignment always reads the same way."""
    from urllib.parse import unquote
    parts: List[str] = []
    for aid in sorted(slot_values or {}):
        value = slot_values[aid] or {}
        url = str(value.get("image") or "")
        if url:
            parts.append(unquote(url.rsplit("/", 1)[-1]).rsplit(".", 1)[0])
        elif value.get("preset"):
            parts.append(str(value["preset"]))
    return _coerce_variant_label(", ".join(p for p in parts if p))


def _autofill_slots(prop_id: str) -> None:
    """Re-read the texture slots off the PRIMARY variant's mesh.

    Called from EVERY path on which a mesh lands: :func:`_store_bbox` (upload,
    gallery selection, a deleted mesh) and the generation chain's own landing
    block (:func:`_generate`). Always AFTER the refinement of the same ingest —
    the vertex-colour bake replaces every material name with one of its own, so
    a list read before it would describe a file that no longer exists. The
    other steps (re-encode, reduction, normalisation) never touch a material
    name. The shrink paths need no call: they only ever select into the ``low``
    tier, and the slots are read off the FULL mesh.

    An AUTO list is RE-DETECTED, so a regenerated model brings its own
    surfaces instead of leaving the previous mesh's list behind a "detected"
    badge — an emptied result included. A list the admin has stored
    (``slots_auto`` False) is never touched again, an empty one included:
    deleting every slot is a decision too. A result equal to what is stored
    writes nothing, so the ordinary prop costs no extra sidecar write.
    """
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta or meta.get(SLOTS_AUTO_KEY) is False:
        return
    mp = model_path(prop_id)
    if not mp or mp.suffix.lower() != ".glb":
        return
    try:
        names = glb_material_names_at(mp)
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            UnicodeDecodeError):
        # Only a POSITIVE finding may change the list — an unreadable mesh is
        # not a statement that the prop has no slots.
        return
    slots = detect_slots(names)
    if slots == (meta.get(SLOTS_KEY) or []):
        return
    meta[SLOTS_KEY] = slots
    meta[SLOTS_AUTO_KEY] = True
    try:
        _write_sidecar(pid, meta)
    except (OSError, ValueError):
        return
    logger.info("Prop %s: %d texture slot(s) detected (%s)", pid, len(slots),
                ", ".join(s["name"] for s in slots) or "none")


# ── Picture areas: detection, split, rename, delete ─────────────────────
# The GLB is the truth (spec-picture-props.md § 1): an area is a material
# ``slot_<kind>_<k>`` on exactly its faces. Every change to that assignment
# runs through Blender (``scripts/picture_areas.py``) and lands as a NEW
# gallery file that is then selected — the signature moves, the history
# stays (the input file remains in the gallery; no ``raw/`` copy, ruling R6).
# The one exception is a KIND RENAME: it only
# changes a material NAME, which the JSON chunk of the GLB carries verbatim,
# so it is rewritten in Python without a Blender round trip.

class BlenderUnavailable(RuntimeError):
    """Blender cannot run right now — missing, disabled or every slot busy.
    A state of the host, not a defect of the mesh: the route answers 503."""


def areas_sidecar_path(model_path: Optional[Path]) -> Optional[Path]:
    """``model_<ts>.glb`` -> ``model_<ts>.glb.areas.json`` — the outline
    edges and the mesh layout (R1) of THAT mesh's areas. Beside the mesh,
    because they describe it and are meaningless for any other file."""
    if not model_path:
        return None
    mp = Path(model_path)
    return mp.with_name(mp.name + AREAS_SIDECAR_SUFFIX)


def read_areas_sidecar(model_path: Optional[Path]) -> Dict[str, Any]:
    sp = areas_sidecar_path(model_path)
    if sp and sp.exists():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def _write_areas_sidecar(model_path: Path, areas: List[Dict[str, Any]],
                         edges: Dict[str, Any], mesh_layout: Any,
                         leaf_bbox: Optional[Dict[str, Any]] = None) -> None:
    """The per-mesh record: the FULL area entries of that file (what the
    sidecar carries, plus the outline ``edges``), the R1 layout and the
    ``leaf_bbox`` of its leaf node (when it has one). Full, not just edges,
    so a re-selected file brings its own area list back
    (:func:`_reconcile_areas`)."""
    sp = areas_sidecar_path(model_path)
    if not sp:
        return
    sp.write_text(json.dumps({
        "areas": [{**a, "edges": edges.get(a["id"]) or []} for a in areas],
        **({"leaf_bbox": leaf_bbox} if leaf_bbox else {}),
        "mesh_layout": [{"name": str(m.get("name") or ""),
                         "tri_count": int(m.get("tri_count") or 0)}
                        for m in (mesh_layout or []) if isinstance(m, dict)],
        "run_at": utc_now_iso(),
    }, ensure_ascii=False), encoding="utf-8")


def _sidecar_areas_from_script(script_areas: List[Dict[str, Any]],
                               previous: List[Dict[str, Any]],
                               default_source: str) -> List[Dict[str, Any]]:
    """The sidecar list from what the script reported: an area that existed
    before keeps its ``source``, a new one gets ``default_source``."""
    before = {a.get("id"): a for a in (previous or [])}
    out = []
    for a in script_areas:
        prev = before.get(a.get("id")) or {}
        out.append({
            "id": a.get("id"),
            "kind": a.get("kind"),
            "size_m": a.get("size_m"),
            "normal": a.get("normal"),
            "source": prev.get("source") or default_source,
            "faces": a.get("faces"),
            "origin": a.get("origin") or prev.get("origin") or "",
            "centroid": a.get("centroid"),
        })
    return sanitize_areas(out)


# ── The measured facts of ONE model file ────────────────────────────────
# (spec-bild-props-v2.md E1.) What a split found, where the leaf node sits
# and which way is up are facts of ONE FILE — every variant is its own
# generation — and live on that file's ``.json`` sidecar. `file_areas` is the
# ONE reader (a LOW file answers through `inherits_from`), `set_file_areas`
# the ONE writer; nothing reads a prop-level value for any of them.

def _file_areas_owner(model_path: Path) -> Tuple[Path, Dict[str, Any]]:
    """``(file, its sidecar)`` that answers for ``model_path``: the file
    itself — or, for a LOW file that says ``inherits_from``, the full file it
    was reduced from while that file still exists (its sidecar is read, the
    logic is not duplicated). A low file whose full file is gone answers
    with the copies it carries itself."""
    meta = read_model_sidecar(model_path)
    parent = str(meta.get(INHERITS_FROM_KEY) or "")
    if parent:
        pp = model_path.with_name(parent)
        if pp.exists():
            return pp, read_model_sidecar(pp)
    return model_path, meta


def _coerce_file_areas(meta: Dict[str, Any]) -> Dict[str, Any]:
    """The seven fields as READ BACK — junk is a missing value, never a
    crash: a hand-edited sidecar must not take a whole prop record down."""
    try:
        areas = (sanitize_areas(meta.get(AREAS_KEY))
                 if isinstance(meta.get(AREAS_KEY), list) else [])
    except ValueError:
        areas = []
    try:
        leaf = sanitize_leaf_bbox(meta.get(LEAF_BBOX_KEY))
    except ValueError:
        leaf = None
    try:
        run = sanitize_key_areas(meta.get(KEY_AREAS_RUN_KEY))
    except ValueError:
        run = []
    return {
        AREAS_KEY: areas,
        LEAF_BBOX_KEY: leaf,
        ROTATION_KEY: _sanitize_rotation(meta.get(ROTATION_KEY)),
        AREAS_RUN_AT_KEY: str(meta.get(AREAS_RUN_AT_KEY) or ""),
        AREAS_ERROR_KEY: str(meta.get(AREAS_ERROR_KEY) or ""),
        AREAS_WARNING_KEY: str(meta.get(AREAS_WARNING_KEY) or ""),
        KEY_AREAS_RUN_KEY: run,
    }


def file_areas(model_path: Optional[Path]) -> Dict[str, Any]:
    """``{areas, leaf_bbox, rotation, areas_run_at, areas_error,
    areas_warning, key_areas_run}`` of ONE model file, read off the FULL
    file's sidecar — a LOW file answers with its full file's values
    (sidecar ``inherits_from``). ``None`` / a missing file answers with the
    empty shape (no areas, no leaf, rotation 0), never raises."""
    if not model_path:
        return _coerce_file_areas({})
    _, meta = _file_areas_owner(Path(model_path))
    return _coerce_file_areas(meta)


def set_file_areas(model_path: Path, **fields: Any) -> None:
    """Write ONLY the given area fields onto a model file's sidecar
    (:data:`FILE_AREAS_KEYS`); every other key of the sidecar stands. A
    value of ``None`` removes the key (``leaf_bbox=None`` = no leaf,
    ``areas_error=None`` = the run succeeded); ``areas=[]`` is a positive
    reading ("no areas") and is stored. ``ValueError`` for an unknown field
    or an unusable value — the same sanitizers every other writer runs."""
    unknown = sorted(set(fields) - set(FILE_AREAS_KEYS))
    if unknown:
        raise ValueError("unknown file area field(s): " + ", ".join(unknown))
    meta = read_model_sidecar(model_path)
    for key, value in fields.items():
        if value is None:
            meta.pop(key, None)
            continue
        if key == AREAS_KEY:
            value = sanitize_areas(value)
        elif key == LEAF_BBOX_KEY:
            value = sanitize_leaf_bbox(value)
            if value is None:
                meta.pop(key, None)
                continue
        elif key == ROTATION_KEY:
            value = _sanitize_rotation(value, meta.get(ROTATION_KEY))
        elif key == KEY_AREAS_RUN_KEY:
            value = sanitize_key_areas(value)
        else:
            value = str(value)
            if not value:
                meta.pop(key, None)
                continue
        meta[key] = value
    write_model_sidecar(model_path, meta)


def _variant_full_file(prop_id: str, variant: Any = None) -> Optional[Path]:
    """The ACTIVE full-tier file of one variant — the file the areas live
    on — or None (no gallery, no full tier, the ``__none__`` sentinel)."""
    g = model_gallery(prop_id, variant)
    return g.find(DEFAULT_TIER, fallback=False) if g else None


def _resolve_variant(prop_id: str, variant: Any,
                     meta: Optional[Dict[str, Any]] = None) -> int:
    """The STORE index ``variant`` names: ``None`` / negative = the primary
    variant, an index this prop has = itself, anything else = ``-1``."""
    entries = _variant_list(read_sidecar(prop_id) if meta is None else meta)
    if variant is None:
        return _effective_indices(entries)[0]
    try:
        i = int(variant)
    except (TypeError, ValueError):
        return -1
    if i < 0:
        return _effective_indices(entries)[0]
    return i if i < len(entries) else -1


def _drop_stale_low(gallery: ModelGallery) -> None:
    """A CPU-built distance mesh of the file that was just superseded shows
    the atlas where the picture is — remove it so the on-demand build makes
    a new one from the split file. Only a mesh this store reduced ITSELF
    (sidecar ``source: lod``); an uploaded or backend-delivered low mesh is
    the admin's and stays."""
    low = gallery.tiers().get(LOW_TIER)
    if not low:
        return
    if read_model_sidecar(low).get("source") != "lod":
        return
    gallery.delete(low.name)
    # `delete` re-points a dangling DEFAULT selection only; the low entry is
    # dropped, so the auto-LOD demand rebuilds it from the current full mesh.


def _split_origin(gallery: ModelGallery, src: Path,
                  meta: Optional[Dict[str, Any]] = None) -> str:
    """The file a split CHAIN started from — the ORIGIN, never the immediate
    predecessor (v2 E4, ruling V6).

    A split written since E4 carries the origin forward, so one hop over its
    ``source_file`` already answers. A file from BEFORE E4 names the file it
    was cut from, so the name is FOLLOWED as long as it points at another
    SPLIT of this gallery: one run on a legacy chain O → A → B → C then
    resolves to O for every link, and the landing collapses the whole chain
    instead of leaving every second file behind (the measured prop's eight
    files drop to two, not four).

    A predecessor that is gone ends the walk on ITS NAME — that name is what
    the remaining links of the chain still share. The walk is capped at the
    gallery size: a hand-edited sidecar pointing in a circle must not spin."""
    name = src.name
    current = read_model_sidecar(src) if meta is None else meta
    for _ in range(len(gallery.files()) + 1):
        if current.get("source") != "areas":
            return name
        nxt = str(current.get("source_file") or "")
        if not nxt:
            return name
        p = gallery.file(nxt)
        if not p:
            return nxt
        name, current = p.name, read_model_sidecar(p)
    return name


def _drop_superseded_splits(gallery: ModelGallery, target: Path, origin: str,
                            protected: Set[str]) -> None:
    """A split REPLACES its predecessor (v2 E4): every OTHER file of this
    gallery that came out of a run on the same ``origin`` goes, with its
    ``.json`` sidecar and its ``.areas.json`` companion.

    What a prop keeps is therefore exactly two entries per variant — the
    origin the runs work on and the current cut — instead of one file per
    click (measured 2026-08-28: eight full files of one variant inside ten
    minutes, indistinguishable in the list).

    Never removed: the ORIGIN itself (it is no split, and it is what every
    further run starts from), anything the admin uploaded or generated, and
    a split that is still the active file of ANOTHER tier — a distance mesh
    somebody selected by hand is a choice, not a leftover.

    Every candidate resolves its OWN origin through the same walk the target
    used (ruling V6), so a chain written before E4 — where each link names
    its immediate predecessor — collapses on the next click instead of
    leaving every second file standing. The doomed list is computed in full
    BEFORE the first delete: the walks read files that the deletes remove."""
    doomed: List[Path] = []
    for p in gallery.files():
        if p.name in (target.name, origin) or p.name in protected:
            continue
        meta = read_model_sidecar(p)
        if meta.get("source") != "areas":
            continue
        if _split_origin(gallery, p, meta) == origin:
            doomed.append(p)
    for p in doomed:
        gallery.delete(p.name)
    _drop_areas_sidecars(doomed)


def _land_split(gallery: ModelGallery, src: Path, blob: bytes,
                mode: str, area: str = "") -> Path:
    """The split result as a NEW gallery file, selected for the full tier,
    REPLACING the split it came from.

    NO ``raw/`` copy (ruling R6): that rule belongs to the in-place
    refinements of ``refine.apply_script``, where the original would be
    overwritten. Here the ORIGIN stays in the gallery as history — but only
    the origin: since v2 E4 the history of a variant is the file the runs
    work on plus the current cut, and every earlier cut of that same origin
    is dropped by :func:`_drop_superseded_splits`.

    The new file is the SAME MESH cut differently, so it inherits what
    describes the mesh rather than the cut: the input's orientation fix and
    the kinds its last automatic run searched. The areas themselves are
    written by the caller, off the run's report. ``area`` names the ONE area
    the run is about (the renamed or dissolved id) — what the gallery row
    needs to say "Renamed picture_1" instead of "another file"."""
    prev = read_model_sidecar(src)
    origin = _split_origin(gallery, src, prev)
    # Read the selection BEFORE the new file takes the full tier, so
    # "another tier" means exactly that and not "the tier being replaced".
    protected = {name for tier, name in gallery.selection().items()
                 if tier != DEFAULT_TIER and name}
    target = gallery.new_path()
    target.write_bytes(blob)
    write_model_sidecar(target, {
        "created_at": utc_now_iso(),
        "source": "areas",
        "format": "glb",
        "rig": "none",
        "tier": DEFAULT_TIER,
        "source_file": origin,
        "areas_mode": mode,
        **({AREAS_AREA_KEY: area} if area else {}),
        **({"backend": prev["backend"]} if prev.get("backend") else {}),
        **({"face_num": prev["face_num"]} if prev.get("face_num") else {}),
        **({"texture_size": prev["texture_size"]}
           if prev.get("texture_size") else {}),
        **({ROTATION_KEY: prev[ROTATION_KEY]}
           if isinstance(prev.get(ROTATION_KEY), dict)
           and any(prev[ROTATION_KEY].values()) else {}),
        **({KEY_AREAS_RUN_KEY: prev[KEY_AREAS_RUN_KEY]}
           if prev.get(KEY_AREAS_RUN_KEY) else {}),
    })
    gallery.select(target.name, DEFAULT_TIER)
    _drop_superseded_splits(gallery, target, origin, protected)
    _drop_stale_low(gallery)
    return target


def _areas_run(prop_id: str, variant: Any, params: Dict[str, Any], *,
               default_source: str, wait_s: float) -> List[Dict[str, Any]]:
    """ONE Blender run of ``scripts/picture_areas.py`` on a variant's full
    mesh and everything that lands from it: the new gallery file, ITS
    sidecar ``areas`` / ``leaf_bbox`` / run stamps, the ``.areas.json``
    beside the mesh, the pruning of THAT variant's defaults and values
    (ruling R15, per variant) and the texture slots.

    Raises :class:`BlenderUnavailable` when Blender is missing or busy (503),
    ``RuntimeError`` when the script fails (500), ``ValueError`` for a prop or
    variant without a full-tier GLB."""
    from app.blender import refine, runner
    from app.core.model_validate import validate_static_glb
    reason = refine.unavailable_reason()
    if reason:
        raise BlenderUnavailable(reason)
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    index = _resolve_variant(pid, variant, meta) if meta else -1
    g = model_gallery(pid, index) if index >= 0 else None
    src = g.find(DEFAULT_TIER, fallback=False) if g else None
    if not src or src.suffix.lower() != ".glb":
        raise ValueError("this variant has no full-tier GLB to work on")
    if not refine.take_lod_slot(wait_s):
        raise BlenderUnavailable("blender is busy with another model — try "
                                 "again in a moment")
    try:
        with tempfile.TemporaryDirectory(prefix="av-areas-") as tmp:
            res = runner.run("picture_areas", inputs={"model": src},
                             params=params, out_dir=Path(tmp), timeout_s=600)
            if not res.get("ok"):
                raise RuntimeError(res.get("error") or "picture_areas failed")
            data = res.get("data") or {}
            produced = (res.get("outputs") or {}).get("model")
            blob = Path(produced).read_bytes() if produced else None
    finally:
        refine.free_lod_slot()

    previous = file_areas(src)
    model_file = src
    if blob is not None:
        verdict = validate_static_glb(blob)
        if not verdict.get("ok"):
            raise RuntimeError("split model failed validation: "
                               + "; ".join(verdict.get("errors") or []))
        # A FRESH gallery for the landing. ``g`` was built before the Blender
        # run and memoizes the selection file it read then — minutes ago. A
        # distance-mesh thread that selected a ``low`` in the meantime would
        # have that entry written back away by the landing's own `select`,
        # leaving its file behind as an orphan nothing can reach. The gallery
        # contract says so itself: instances are SHORT-LIVED, one per call.
        model_file = _land_split(model_gallery(pid, index), src, blob,
                                 str(params.get("mode") or ""),
                                 str(params.get("area") or ""))

    script_areas = [a for a in (data.get("areas") or []) if isinstance(a, dict)]
    areas = _sidecar_areas_from_script(script_areas, previous[AREAS_KEY],
                                       default_source)
    leaf_bbox = sanitize_leaf_bbox(data.get("leaf_bbox"))
    _write_areas_sidecar(model_file, areas,
                         {a.get("id"): a.get("edges") for a in script_areas},
                         data.get("mesh_layout"), leaf_bbox)
    kinds = list(params.get("kinds") or [])
    try:
        residual = int(data.get("leaf_residual") or 0)
    except (TypeError, ValueError):
        residual = 0
    # A run that left a leaf with frame faces still inside its outline says
    # so (E2); a run that looked for the leaf and found none leaves its
    # note; any other run (a clean cut, a delete) clears both.
    if leaf_bbox and residual > 0:
        warning: Optional[str] = LEAF_RESIDUAL_NOTE.format(n=residual)
    elif LEAF_KIND in kinds and not leaf_bbox:
        warning = NO_LEAF_NOTE
    else:
        warning = None
    fields: Dict[str, Any] = {
        AREAS_KEY: areas,
        LEAF_BBOX_KEY: leaf_bbox,
        AREAS_RUN_AT_KEY: utc_now_iso(),
        AREAS_ERROR_KEY: None,
        AREAS_WARNING_KEY: warning,
    }
    if params.get("mode") == "auto":
        fields[KEY_AREAS_RUN_KEY] = kinds
    set_file_areas(model_file, **fields)
    # THIS variant's defaults and values follow its rewritten mesh (R15).
    if _prune_variant_entry(meta, index, {a["id"] for a in areas}):
        _write_sidecar(pid, meta)
    _autofill_slots(pid)
    logger.info("Prop %s: picture areas %s -> %s (%s, variant %s)", pid,
                params.get("mode"), ", ".join(a["id"] for a in areas) or "none",
                model_file.name, index)
    return areas


def _prune_variant_entry(meta: Dict[str, Any], index: int, ids: Set[str], *,
                         slot_values: bool = True) -> bool:
    """Drop what ONE variant says about areas its mesh no longer has — its
    ``area_defaults`` and, with ``slot_values``, its ``slot_values``.

    Both describe THAT VARIANT'S OWN mesh (v2 E1), so only the events that
    rewrite that mesh prune them: a split, a re-split, a rename, a deleted
    area, a re-copy. Ruling R15 keeps one asymmetry: a mere gallery click
    (:func:`_reconcile_areas`) lets the defaults follow the file that is
    active now but never touches the pictures somebody hung
    (``slot_values=False``). A failed run prunes nothing at all.

    The variant's ``label`` is NEVER touched — it is the name the admin gave
    that version, not a description of its values.

    Mutates ``meta`` in place and returns whether anything changed; the
    caller owns the sidecar write."""
    entries = _variant_list(meta)
    if not 0 <= index < len(entries):
        return False
    entry = entries[index]
    changed = False
    for key in ((AREA_DEFAULTS_KEY, SLOT_VALUES_KEY) if slot_values
                else (AREA_DEFAULTS_KEY,)):
        values = entry.get(key) or {}
        kept = {k: v for k, v in values.items() if k in ids}
        if kept == values:
            continue
        if kept:
            entry[key] = kept
        else:
            entry.pop(key, None)
        changed = True
    if changed:
        meta[VARIANTS_KEY] = entries
    return changed


def _origins(areas: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {a["id"]: a["origin"] for a in (areas or []) if a.get("origin")}


def detect_areas(prop_id: str, *, mode: str = "auto",
                 faces: Any = None, kind: str = "picture",
                 through: bool = False,
                 variant: Any = None, kinds: Any = None,
                 min_faces: int = MIN_AREA_FACES,
                 min_area_m2: float = MIN_AREA_M2,
                 wait_s: float = 10.0) -> List[Dict[str, Any]]:
    """Find, draw or adopt the picture areas of ONE VARIANT's mesh —
    returns that file's ``areas`` list after the run.

    ``mode="auto"`` dissolves every area it once detected ITSELF — an area
    the admin drew by hand (``source == "manual"``) is kept as it is, faces,
    material and number (ruling R14) — and detects the key-coloured
    panels of the kinds the prop asked for (``key_areas``) — plus the door
    LEAF (spec § 6) when the prop asked for ``leaf`` or is a door prop
    (:func:`is_door_prop`); a door that asked for nothing gets the leaf only,
    a prop that is neither gets every COLOUR kind, and the leaf heuristic
    never runs on such a prop — a picture frame must not lose its biggest
    plate to it. ``kinds`` overrides that rule with EXACTLY the given kinds
    (the tab's "Detect now", E3). A run that looked for the leaf and found
    none leaves :data:`NO_LEAF_NOTE` in the file's ``areas_warning`` (the
    areas it found stay). ``mode="manual"`` turns ``faces`` (flat triangle
    indices in the R1 order of the CURRENT mesh — the tab's polygon pick)
    into one new area of ``kind``; every other area stays; kind ``leaf``
    cuts those faces out as the leaf node (replacing a previous leaf) —
    with ``through`` (the tab's polygon pick, E2) as the PRISM through the
    listed faces' footprint, back skin and edges included, without it
    exactly as listed. The leaf is a prism in ``auto`` mode too; a run that
    leaves frame faces inside the leaf's outline stores
    :data:`LEAF_RESIDUAL_NOTE` as the file's ``areas_warning``.
    ``mode="adopt"`` (E6) turns every material the slot convention names
    (:func:`detect_slots`: ``slot_<name>``, bare picture/screen/sign/glass)
    that is not an area yet into one made of that material's faces — no UV
    rewrite, the material renamed to its canonical ``slot_<kind>_<k>`` when
    it is not that already (``glass*`` → glass, everything else → picture);
    ``ValueError`` when there is nothing left to adopt. ``min_faces`` /
    ``min_area_m2`` are the auto filter (production: 12 faces, 0.02 m²).

    ``variant`` is the STORE index (``None`` = the primary variant): the run
    changes THAT variant's GLB, its file sidecar and its ``.areas.json`` and
    nothing of any other variant (v2 E1 — every variant is its own mesh).
    Same for :func:`delete_area` and :func:`rename_area_kind`.

    Raises ``ValueError`` for bad input, :class:`BlenderUnavailable` when
    Blender is missing or busy, ``RuntimeError`` when the run fails.
    ``wait_s`` is how long to wait for a Blender slot — a request thread
    keeps it short, a landing thread may wait.
    """
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        raise ValueError("prop not found")
    index = _resolve_variant(pid, variant, meta)
    if index < 0:
        raise ValueError(f"this prop has no variant {variant}")
    current = file_areas(_variant_full_file(pid, index))[AREAS_KEY]
    mode = str(mode or "auto").strip().lower()
    params: Dict[str, Any] = {"mode": mode, "origins": _origins(current)}
    if mode == "auto":
        if kinds is not None:
            # The tab's "Detect now": exactly these kinds, nothing added.
            wanted = sanitize_key_areas(kinds)
            if not wanted:
                raise ValueError("kinds must name at least one kind "
                                 "(" + ", ".join(AREA_KINDS) + ")")
        else:
            # The kinds of an automatic run: what the prop ASKED for, plus
            # the leaf for a door prop; a prop that asked for nothing and is
            # no door gets every colour kind (the "Detect areas" button on a
            # plain frame) — a door that asked for nothing gets the leaf
            # ONLY, never an unrequested chroma detection.
            wanted = list(meta.get(KEY_AREAS_KEY) or [])
            if is_door_prop(meta) and LEAF_KIND not in wanted:
                wanted.append(LEAF_KIND)
            if not wanted:
                wanted = list(COLOUR_KINDS)
        params["kinds"] = wanted
        # R14: an automatic run dissolves what it detected itself and leaves
        # what the ADMIN drew — or the modeller NAMED (adopt, E6) — standing:
        # faces, material, number. The detector never sees those faces again
        # (their material is a slot material, and only the atlas materials
        # are read), so a hand-drawn panel survives every "Detect areas"
        # click, which is what the button's tooltip says.
        params["keep"] = [a["id"] for a in current if a.get("source") != "auto"]
        params["min_faces"] = max(1, int(min_faces))
        params["min_area_m2"] = max(0.0, float(min_area_m2))
    elif mode == "manual":
        kind = str(kind or "").strip().lower()
        if kind not in AREA_KINDS:
            raise ValueError(f"unknown area kind {kind!r} (known: "
                             + ", ".join(AREA_KINDS) + ")")
        try:
            idx = sorted({int(f) for f in (faces or [])})
        except (TypeError, ValueError):
            raise ValueError("faces must be a list of triangle indices") from None
        if not idx or idx[0] < 0:
            raise ValueError("faces must be a non-empty list of triangle indices")
        if len(idx) > MAX_MANUAL_FACES:
            raise ValueError(f"faces: {len(idx)} entries, at most "
                             f"{MAX_MANUAL_FACES} allowed")
        params["faces"] = idx
        params["kind"] = kind
        if kind == LEAF_KIND and through:
            params["through"] = True
    elif mode == "adopt":
        src = _variant_full_file(pid, index)
        if not src or src.suffix.lower() != ".glb":
            raise ValueError("this variant has no full-tier GLB to work on")
        try:
            names = glb_material_names_at(src)
        except (OSError, ValueError, KeyError, json.JSONDecodeError,
                UnicodeDecodeError, struct.error):
            raise ValueError("the mesh's material names cannot be read") from None
        mapping = adopt_mapping(names, current)
        if not mapping:
            raise ValueError("nothing to adopt: no material named slot_<name>, "
                             "picture, screen, sign or glass that is not an "
                             "area already")
        params["adopt"] = mapping
    else:
        raise ValueError(f"unknown mode {mode!r} (auto | manual | adopt)")
    return _areas_run(pid, index, params,
                      default_source=mode if mode in AREA_SOURCES else "manual",
                      wait_s=wait_s)


def adopt_mapping(material_names: Any,
                  current: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """``{material name: area id}`` for E6's ``adopt``: every material name
    :func:`detect_slots` recognises that is not an area of the file yet.

    The id is the canonical ``<kind>_<k>``: a name that already IS
    ``slot_<kind>_<k>`` keeps that id (and is skipped when the file lists
    it); any other slot name — ``slot_poster``, a bare ``glass``,
    ``slot_screen`` — gets the next free number of its kind, ``glass*``
    being glass and everything else a picture (ruling of 2026-08-28: the
    two colour kinds are what the renderers can fill). Names come back as
    the mesh spells them, so the script can find the material.
    """
    have = {a.get("id") for a in (current or [])}
    used: Dict[str, Set[int]] = {k: set() for k in COLOUR_KINDS}
    for aid in have:
        m = _AREA_ID_RE.match(str(aid or ""))
        if m:
            used[m.group(1)].add(int(m.group(2)))
    # TWO PASSES (fix round 1): every canonical name reserves its number
    # FIRST, whatever its position in the material list — in a single pass
    # a bare `glass` ahead of `slot_glass_1` would take glass_1 and the
    # real slot_glass_1 would be skipped and, in the script, renamed over.
    canonical: Dict[str, Tuple[str, int]] = {}
    others: List[Tuple[str, str]] = []
    for raw in (material_names or []):
        name = str(raw or "")
        if name in canonical or any(name == n for n, _s in others):
            continue
        slots = detect_slots([name])
        if not slots:
            continue
        slot = slots[0]["name"]
        m = _AREA_ID_RE.match(slot)
        if m:
            canonical[name] = (m.group(1), int(m.group(2)))
            used[m.group(1)].add(int(m.group(2)))
        else:
            others.append((name, slot))
    out: Dict[str, str] = {}
    for name, (kind, k) in canonical.items():
        if f"{kind}_{k}" not in have:
            out[name] = f"{kind}_{k}"
    for name, slot in others:
        kind = "glass" if slot.startswith("glass") else "picture"
        k = 1
        while k in used[kind]:
            k += 1
        used[kind].add(k)
        out[name] = f"{kind}_{k}"
    return out


def delete_area(prop_id: str, area_id: str, variant: Any = None,
                wait_s: float = 10.0) -> List[Dict[str, Any]]:
    """Dissolve one area of ONE variant's mesh: its faces go back to the
    material they came from (``origin``) with their atlas UVs restored, the
    material is gone from the mesh, the file's entry and any default or
    value of that variant on it with it. For ``leaf`` the node is joined
    back into ``frame`` and the file's ``leaf_bbox`` goes. Returns the
    remaining ``areas``. ``ValueError`` for an unknown area."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        raise ValueError("prop not found")
    index = _resolve_variant(pid, variant, meta)
    if index < 0:
        raise ValueError(f"this prop has no variant {variant}")
    current = file_areas(_variant_full_file(pid, index))[AREAS_KEY]
    aid = str(area_id or "").strip().lower()
    if aid not in {a["id"] for a in current}:
        raise ValueError(f"unknown area {aid!r}")
    return _areas_run(pid, index, {"mode": "delete", "area": aid,
                                   "origins": _origins(current)},
                      default_source="manual", wait_s=wait_s)


def _rewrite_glb_material_names(blob: bytes, mapping: Dict[str, str]) -> bytes:
    """The GLB with ``materials[].name`` renamed per ``mapping`` — the JSON
    chunk re-serialised, every other chunk byte for byte. The one mesh edit
    that needs no Blender: a name is data of the container, not geometry."""
    if len(blob) < 20 or blob[:4] != b"glTF":
        raise ValueError("not a GLB file")
    chunks: List[Tuple[int, bytes]] = []
    offset = 12
    while offset + 8 <= len(blob):
        length, ctype = struct.unpack("<II", blob[offset:offset + 8])
        chunks.append((ctype, blob[offset + 8:offset + 8 + length]))
        offset += 8 + length + ((4 - length % 4) % 4)
    out = b""
    for ctype, body in chunks:
        if ctype == 0x4E4F534A:
            gltf = json.loads(body.decode("utf-8"))
            for mat in gltf.get("materials") or []:
                if mat.get("name") in mapping:
                    mat["name"] = mapping[mat["name"]]
            body = json.dumps(gltf, separators=(",", ":"),
                              ensure_ascii=False).encode("utf-8")
            body += b" " * ((4 - len(body) % 4) % 4)
        else:
            body += b"\0" * ((4 - len(body) % 4) % 4)
        out += struct.pack("<II", len(body), ctype) + body
    return struct.pack("<III", 0x46546C67, 2, 12 + len(out)) + out


def rename_area_kind(prop_id: str, area_id: str, kind: str,
                     variant: Any = None) -> List[Dict[str, Any]]:
    """Change what an area of ONE variant's mesh IS (picture <-> glass): the
    material is renamed to the next free ``slot_<kind>_<k>`` of the target
    kind, in a NEW gallery file (the GLB's JSON chunk rewritten, no Blender
    needed), and the file's entry and its outline record follow the new id.
    Returns the ``areas`` list. Same kind = nothing to do.

    Everything THAT variant stored for the OLD id goes
    (:func:`_prune_variant_entry`, both halves): the old id names no area
    any more, so the dialog cannot show — let alone remove — a value keyed
    on it, and a save would keep failing on it. The preset is NOT carried
    over either: the area just became another kind, and a glass preset on a
    picture panel is exactly the value the sanitizers refuse. Another
    variant's copy still carries the old material and keeps its values.

    The door LEAF is refused in both directions (R9): a node is not a
    material, so there is no name to rewrite — dissolve it and draw the
    faces again as the other kind instead."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        raise ValueError("prop not found")
    kind = str(kind or "").strip().lower()
    if kind not in AREA_KINDS:
        raise ValueError(f"unknown area kind {kind!r} (known: "
                         + ", ".join(AREA_KINDS) + ")")
    index = _resolve_variant(pid, variant, meta)
    if index < 0:
        raise ValueError(f"this prop has no variant {variant}")
    g = model_gallery(pid, index)
    src = g.find(DEFAULT_TIER, fallback=False) if g else None
    if not src or src.suffix.lower() != ".glb":
        raise ValueError("this variant has no full-tier GLB to work on")
    current = file_areas(src)
    areas = [dict(a) for a in current[AREAS_KEY]]
    aid = str(area_id or "").strip().lower()
    entry = next((a for a in areas if a["id"] == aid), None)
    if entry is None:
        raise ValueError(f"unknown area {aid!r}")
    if entry["kind"] == kind:
        return areas
    if kind == LEAF_KIND or entry["kind"] == LEAF_KIND:
        raise ValueError("the door leaf is a node, not a material — dissolve "
                         "it and draw the faces as the other kind instead")
    used = {int(a["id"].rsplit("_", 1)[1]) for a in areas if a["kind"] == kind}
    k = 1
    while k in used:
        k += 1
    new_id = f"{kind}_{k}"
    blob = _rewrite_glb_material_names(
        src.read_bytes(), {f"{SLOT_PREFIX}{aid}": f"{SLOT_PREFIX}{new_id}"})
    outline = read_areas_sidecar(src)
    target = _land_split(g, src, blob, "rename", new_id)
    for rec in outline.get("areas") or []:
        if rec.get("id") == aid:
            rec["id"], rec["kind"] = new_id, kind
    if outline:
        sp = areas_sidecar_path(target)
        if sp:
            sp.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
    entry["id"], entry["kind"] = new_id, kind
    areas = sanitize_areas(areas)
    # The new file is the same mesh under new names: it keeps the leaf box
    # the input had and gets the renamed list; the run stamp moves.
    set_file_areas(target, areas=areas, leaf_bbox=current[LEAF_BBOX_KEY],
                   areas_run_at=utc_now_iso(),
                   areas_warning=current[AREAS_WARNING_KEY] or None)
    # A rename is ALWAYS a kind change, so nothing that was stored for the
    # old id can survive it: a glass preset on a panel that is now a
    # picture is invalid on its face, and re-keying it onto the new id
    # would only move the invalid value. Both halves lose the dead id.
    if _prune_variant_entry(meta, index, {a["id"] for a in areas}):
        _write_sidecar(pid, meta)
    _autofill_slots(pid)
    logger.info("Prop %s: area %s renamed to %s (%s, variant %s)", pid, aid,
                new_id, target.name, index)
    return areas


def areas_info(prop_id: str, variant: Any = None) -> Dict[str, Any]:
    """What ``GET /world/props/{id}/areas?variant=i`` answers for ONE
    variant: its active file's areas, each with the outline ``edges`` of
    that file's record, the R1 ``mesh_layout``, its ``leaf_bbox`` and
    ``rotation``, the variant's ``area_defaults``, the prop's ``key_areas``
    and what the file's last automatic run searched, whether Blender can
    run, the last run, and — as two fields — what the last run left to
    say: ``error`` is a run that broke (Blender missing, busy, a failing
    script), ``warning`` a run that worked and found nothing to cut. An
    unknown variant answers the empty shape with ``variant -1``."""
    from app.blender import refine
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    index = _resolve_variant(pid, variant, meta) if meta else -1
    mp = model_path(pid, DEFAULT_TIER, index) if index >= 0 else None
    fa = file_areas(mp)
    outline = read_areas_sidecar(mp) if mp else {}
    edges = {rec.get("id"): rec.get("edges") or []
             for rec in (outline.get("areas") or []) if isinstance(rec, dict)}
    reason = refine.unavailable_reason()
    return {
        "variant": index,
        "model_file": mp.name if mp else "",
        "areas": [{**a, "edges": edges.get(a["id"], [])} for a in fa[AREAS_KEY]],
        "mesh_layout": outline.get("mesh_layout") or [],
        "key_areas": list(meta.get(KEY_AREAS_KEY) or []),
        KEY_AREAS_RUN_KEY: fa[KEY_AREAS_RUN_KEY],
        AREA_DEFAULTS_KEY: variant_area_defaults(meta, index) if index >= 0 else {},
        LEAF_BBOX_KEY: fa[LEAF_BBOX_KEY],
        ROTATION_KEY: fa[ROTATION_KEY],
        "blender": {"available": not reason, "reason": reason},
        "last_run": fa[AREAS_RUN_AT_KEY] or None,
        "error": fa[AREAS_ERROR_KEY],
        "warning": fa[AREAS_WARNING_KEY],
    }


def _areas_after_landing(prop_id: str, variant: Any = None,
                         wait_s: float = 10.0) -> None:
    """The landing hook of the TWO paths a NEW mesh arrives on — the upload
    (``save_uploaded_glb`` → ``_store_bbox(landing=True)``) and the generation
    chain (``_generate``) — for EVERY variant (v2 E1: each is its own mesh):
    a prop that asked for key colours — or is a DOOR prop
    (:func:`is_door_prop`, spec § 6: its leaf is cut out on every landing) —
    gets the fresh mesh of THAT variant split automatically; one that is
    neither gets that file's area list reconciled (:func:`_reconcile_areas`).

    ONLY on a landing (review finding 2026-08-27): a gallery selection or a
    deleted file goes through ``_store_bbox`` too, and an auto-run there would
    override the admin's choice with a fresh split file and cost a Blender
    process per click — those paths only reconcile.

    NEVER fails the landing: a failure is logged and stored on the landed
    FILE as ``areas_error`` with ``areas: []``, and shown by the tab.
    ``wait_s`` is the Blender-slot wait: the upload request keeps the
    route's 10 s, the generation worker thread may wait longer."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return
    # E6 FIRST: a mesh whose modeller named its surfaces gets an area per
    # such material — on a file that has no reading yet, so a re-landed
    # split result is not adopted twice. The key-colour run that may follow
    # keeps them (R14: only `auto` areas are dissolved).
    if _names_slot_materials(_variant_full_file(pid, variant)):
        try:
            detect_areas(pid, mode="adopt", variant=variant, wait_s=wait_s)
        except Exception as e:                              # noqa: BLE001
            _landing_run_failed(pid, variant, e, "adoption of named materials")
    if not meta.get(KEY_AREAS_KEY) and not is_door_prop(meta):
        _reconcile_areas(pid, variant)
        return
    try:
        detect_areas(pid, mode="auto", variant=variant, wait_s=wait_s)
    except Exception as e:                                  # noqa: BLE001
        _landing_run_failed(pid, variant, e, "picture-area detection")


def _names_slot_materials(mp: Optional[Path]) -> bool:
    """Does this landed full file carry a material the slot convention
    names (:func:`detect_slots`) while it has NO area reading yet? Only a
    positive finding on a readable GLB answers True."""
    if not mp or mp.suffix.lower() != ".glb" or AREAS_KEY in read_model_sidecar(mp):
        return False
    try:
        return bool(detect_slots(glb_material_names_at(mp)))
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            UnicodeDecodeError, struct.error):
        return False


def _landing_run_failed(pid: str, variant: Any, e: BaseException,
                        what: str) -> None:
    """A landing run failed: log it and store it on the landed FILE.

    The fresh mesh is unsplit, so it names no area and carries no leaf node
    — that much is a reading of the file. What the ADMIN authored (the
    variant's ``area_defaults`` and ``slot_values``) is NOT: a missing or
    busy Blender is a load condition, and answering it by deleting the
    panes and pictures of a door would make a queue wipe a prop. Both
    halves stay until the next SUCCESSFUL run prunes them (R15)."""
    logger.warning("Prop %s: automatic %s failed (variant %s): %s", pid, what,
                   variant, e)
    mp = _variant_full_file(pid, variant)
    if not mp:
        return
    try:
        set_file_areas(mp, areas=[], leaf_bbox=None,
                       areas_error=str(e) or type(e).__name__)
    except (OSError, ValueError):
        pass


def _reconcile_areas(pid: str, variant: Any = None) -> None:
    """Give ONE variant's ACTIVE full mesh its area reading when it has none
    yet, and let that variant's defaults follow it — after the admin
    selected another gallery file, deleted one or uploaded a mesh without
    key colours.

    Since v2 E1 every split result carries its areas on its own sidecar, so
    a re-selected split file needs nothing here. What this settles is the
    file WITHOUT a reading: one that carries a ``.areas.json`` companion but
    no sidecar list (a split from before the move, a copy) takes the
    companion's list and ``leaf_bbox`` verbatim; a readable file without a
    companion is no split result and reads as "no areas" (the material-name
    heuristic of v1 is gone — E6's ``adopt`` is its successor). Only a
    POSITIVE reading is written — an unreadable mesh is not a statement.

    Then the VARIANT's ``area_defaults`` are pruned to the areas its active
    file names; its ``slot_values`` are NEVER touched here (ruling R15): a
    picture variant hangs its pictures on its own copy, and a gallery click
    is not the moment they are re-read."""
    pid = safe_prop_id(pid)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return
    index = _resolve_variant(pid, variant, meta)
    if index < 0:
        return
    mp = _variant_full_file(pid, index)
    if not mp or mp.suffix.lower() != ".glb":
        return
    if AREAS_KEY not in read_model_sidecar(mp):
        record = read_areas_sidecar(mp)
        if isinstance(record.get("areas"), list):
            try:
                kept = sanitize_areas([{k: v for k, v in a.items() if k != "edges"}
                                       for a in record["areas"] if isinstance(a, dict)])
                leaf_bbox = sanitize_leaf_bbox(record.get("leaf_bbox"))
            except ValueError:
                return
        else:
            try:
                glb_material_names_at(mp)
            except (OSError, ValueError, KeyError, json.JSONDecodeError,
                    UnicodeDecodeError, struct.error):
                # struct.error: a truncated container (same reader as
                # `shrink_capability`) — a selection must never fail on it.
                return
            kept, leaf_bbox = [], None
        try:
            set_file_areas(mp, areas=kept, leaf_bbox=leaf_bbox)
        except (OSError, ValueError):
            return
        logger.info("Prop %s: picture areas read for %s (%s)", pid, mp.name,
                    ", ".join(a["id"] for a in kept) or "none")
    ids = {a["id"] for a in file_areas(mp)[AREAS_KEY]}
    if _prune_variant_entry(meta, index, ids, slot_values=False):
        try:
            _write_sidecar(pid, meta)
        except (OSError, ValueError):
            return


# ── CRUD ────────────────────────────────────────────────────────────────

def create_prop(*, name: str, category: str = "", width_m: Any = None,
                depth_m: Any = None, height_m: Any = None,
                tags: Any = None, description: str = "", prompt: str = "",
                source: str = "manual", key_areas: Any = None) -> Dict[str, Any]:
    """Create a new prop record (sidecar only — the model/source files are
    added by upload or the generation chain). Returns ``{id, **sidecar}``.

    ``key_areas`` (``["picture", "glass"]``) records which chroma-key panels
    the generation is asked for — the prompt gets the fragments
    (:func:`compose_prompt`) and every landing mesh is split automatically
    (:func:`_areas_after_landing`). Stored only when non-empty; an unknown
    kind is ``ValueError``.

    Dims: whatever is given is taken, every missing one becomes the LARGEST
    given value (a rough cube); nothing given = 1 m per dim. They land on the
    prop's FIRST VARIANT together with the generation subject, because that is
    where both live (2026-08-25) — the create form still asks for one size and
    one sentence, and this is the variant they describe. The entry starts
    ``dims_estimated``: the mesh's proportions refine it when the model
    arrives."""
    name = (name or "").strip() or "Prop"
    prop_id = _new_prop_id(name)
    dims: Dict[str, float] = {}
    for key, raw in (("width_m", width_m), ("depth_m", depth_m),
                     ("height_m", height_m)):
        if raw is None or f"{raw}".strip() == "":
            continue
        v = _coerce_dim_m(raw, 0.0)
        if v > 0:
            dims[key] = v
    base = max(dims.values()) if dims else DEFAULT_DIM_M
    for key in DIM_KEYS:
        dims.setdefault(key, base)
    variant: Dict[str, Any] = {"stem": MODEL_STEM, "active": True,
                               **dims, DIMS_ESTIMATED_KEY: True}
    subject = _coerce_description(description)
    if subject:
        variant[DESCRIPTION_KEY] = subject
    keys = sanitize_key_areas(key_areas)
    meta = {
        "name": name,
        "category": (category or "").strip(),
        VARIANTS_KEY: [variant],
        # NEW props do not sway (user order 2026-08-20): the 1.0 default is
        # the VEGETATION-era reading of an ABSENT key, kept so existing
        # scatter plants keep waving — but furniture is the normal case now,
        # so creation writes an explicit, stored 0.0. Plants opt IN via the
        # dial; legacy sidecars without the key stay at the old default.
        "sway_factor": 0.0,
        "tags": _coerce_tags(tags),
        "created_at": utc_now_iso(),
        "source": (source or "manual").strip(),
        "prompt": (prompt or "").strip(),
    }
    if keys:
        meta[KEY_AREAS_KEY] = keys
    _write_sidecar(prop_id, meta)
    logger.info("Prop %s created (%s)", prop_id, name)
    return {"id": prop_id, **meta}


#: What the PROP record itself still carries — the fields the general section
#: of the admin form edits. Everything about how the object LOOKS moved onto
#: the variants (2026-08-25), and :data:`MOVED_TO_VARIANT` names those so a
#: stale client is REFUSED instead of silently writing a key nobody reads.
PROP_PATCH_KEYS = ("name", "category", "tags", "sway_factor", "slots",
                   "key_areas")
#: The fields that are variant-only now. A prop-level patch naming one of
#: them is a 400 with the route that owns it — never a no-op: an editor that
#: still sends ``height_m`` here would report "Saved" over a value that never
#: reached anything. ``area_defaults`` joined them with v2 E1 (2026-08-28):
#: a pane default describes ONE variant's mesh.
MOVED_TO_VARIANT = {
    "width_m": "POST /world/props/{id}/variants/{i}/dims",
    "depth_m": "POST /world/props/{id}/variants/{i}/dims",
    "height_m": "POST /world/props/{id}/variants/{i}/dims",
    "dims_estimated": "POST /world/props/{id}/variants/{i}/dims",
    "description": "POST /world/props/{id}/variants/{i}/description",
    "ground_offset_m": "POST /world/props/{id}/variants/{i}/ground-offset",
    "markers": "POST /world/props/{id}/variants/{i}/markers",
    AREA_DEFAULTS_KEY: "POST /world/props/{id}/variants/{i}/area-defaults",
}


def _check_prop_patch(patch: Dict[str, Any],
                      meta: Optional[Dict[str, Any]] = None) -> None:
    """Refuse a prop patch that names a field this record does not own.

    A key that MOVED onto the variants gets the route that owns it now
    (:data:`MOVED_TO_VARIANT`); anything else unknown is named with the list of
    fields that do exist. Both are ``ValueError`` and both are 400s, for the one
    reason: a silently ignored key would report "Saved" over a value that
    reached nothing.
    """
    moved = [k for k in patch if k in MOVED_TO_VARIANT]
    if moved:
        raise ValueError(
            "these fields belong to the model variant now: "
            + "; ".join(f"{k} -> {MOVED_TO_VARIANT[k]}" for k in sorted(moved)))
    unknown = [k for k in patch if k not in PROP_PATCH_KEYS]
    if unknown:
        raise ValueError("unknown prop field(s): " + ", ".join(sorted(unknown))
                         + " (the prop record has: "
                         + ", ".join(PROP_PATCH_KEYS) + ")")
    # The one field whose VALUE is checked here rather than in the applier: the
    # batch save's law is "everything is checked before anything is written",
    # and this is the only prop field a body can get structurally wrong.
    if SLOTS_KEY in patch:
        sanitize_slots(patch.get(SLOTS_KEY))
    if KEY_AREAS_KEY in patch:
        sanitize_key_areas(patch.get(KEY_AREAS_KEY))


def _apply_prop_fields(meta: Dict[str, Any], patch: Dict[str, Any]) -> None:
    """Write the PROP's own fields into ``meta`` — the sanitation of
    :func:`update_prop`, called verbatim by the batch save as well so a bulk
    body can never be a second, laxer way into the same record.

    The caller has already run :func:`_check_prop_patch`; this only stores.
    """
    if "name" in patch:
        nm = str(patch.get("name") or "").strip()
        if nm:
            meta["name"] = nm
    if "category" in patch:
        meta["category"] = str(patch.get("category") or "").strip()
    if "tags" in patch:
        meta["tags"] = _coerce_tags(patch.get("tags"))
    if "sway_factor" in patch:
        # The default is written as ABSENCE, so clearing the field in the admin
        # (and every junk value) removes the key instead of storing a 1.0 that
        # a later default change would silently outvote.
        factor = _coerce_sway_factor(patch.get("sway_factor"))
        if factor is None:
            meta.pop("sway_factor", None)
        else:
            meta["sway_factor"] = factor
    if SLOTS_KEY in patch:
        # Already validated in `_check_prop_patch` (nothing is written before
        # the whole body is checked); this stores the sanitized result and
        # signs the list as the ADMIN's — from here on the model import leaves
        # it alone, an emptied list included.
        meta[SLOTS_KEY] = sanitize_slots(patch.get(SLOTS_KEY))
        meta[SLOTS_AUTO_KEY] = False
    if KEY_AREAS_KEY in patch:
        # Ruling R7: an existing prop may request key colours later (the
        # detail page offers the checkboxes too; a re-generation reads them).
        # Empty = the key goes — absence is the "none requested" statement.
        keys = sanitize_key_areas(patch.get(KEY_AREAS_KEY))
        if keys:
            meta[KEY_AREAS_KEY] = keys
        else:
            meta.pop(KEY_AREAS_KEY, None)


def update_prop(prop_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update the PROP's own fields (name / category / tags / sway_factor /
    slots / key_areas). None when the prop does not exist.

    Raises ``ValueError`` when the patch names one of the fields that
    moved onto the variants (:data:`MOVED_TO_VARIANT`) — the route maps that to
    a 400. Ignoring them would be worse than refusing: the admin would get a
    green "Saved" for a size that was never stored anywhere.
    """
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    if not isinstance(patch, dict):
        patch = {}
    _check_prop_patch(patch, meta)
    _apply_prop_fields(meta, patch)
    _write_sidecar(pid, meta)
    return {"id": pid, **meta}


def set_rotation(prop_id: str, rotation: Any, variant: Any = None,
                 filename: str = "") -> Optional[Dict[str, Any]]:
    """Persist the orientation fix ``{x, y, z}`` (degrees, free values) on
    ONE model FILE of one variant — ``filename`` "" = the variant's active
    full file (pattern ``location_model3d.set_rotation``). None when the
    prop, the variant or the named FILE does not exist (the route's 404);
    ``ValueError`` for a variant without a full-tier mesh.

    A LOW file inherits its fix from the full file it was reduced from, so
    a dial on the active full file is copied onto the variant's active low
    file as well, and a dial aimed at an inheriting low file lands on its
    full file — the two tiers are one object and must never disagree.

    The STORED dims stay untouched: re-orienting a mesh does not silently
    rewrite numbers the admin can see — the editor recomputes its proportional
    suggestions live instead.

    Returns ``{variant, filename, rotation, prop}`` — the store index, the
    file the fix landed on, the fix as stored, and the full record."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    index = _resolve_variant(pid, variant, meta)
    if index < 0:
        return None
    g = model_gallery(pid, index)
    if not g:
        return None
    active_full = g.find(DEFAULT_TIER, fallback=False)
    if filename:
        target = g.file(filename)
        if not target:
            return None
        parent = str(read_model_sidecar(target).get(INHERITS_FROM_KEY) or "")
        if parent and g.file(parent):
            target = g.file(parent)
    else:
        target = active_full
        if not target:
            raise ValueError("this variant has no full-tier mesh to orient")
    cur = file_areas(target)[ROTATION_KEY]
    set_file_areas(target, rotation=rotation)
    rot = file_areas(target)[ROTATION_KEY]
    if active_full and target == active_full:
        low = g.find(LOW_TIER, fallback=False)
        if low and low != target:
            set_file_areas(low, rotation=rot)
        # The fix is part of a surface's identity (spec-surface-height § 4):
        # a turned mesh invalidates THIS variant's lattice. In the
        # background, so the dial answers at once.
        if rot != cur:
            bake_surfaces(pid, index, background=True)
    return {"variant": index, "filename": target.name, "rotation": rot,
            "prop": _prop_record(pid, read_sidecar(pid), full=True)}


def delete_prop(prop_id: str) -> bool:
    """Remove the whole prop directory (model + source + sidecar)."""
    d = _prop_dir(prop_id)
    if not d or not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    logger.info("Prop %s deleted", safe_prop_id(prop_id))
    return True


# ── Files ───────────────────────────────────────────────────────────────

def model_gallery(prop_id: str, variant: Any = None) -> Optional[ModelGallery]:
    """The mesh gallery of ONE variant (None for an invalid id or an index
    this prop has no variant for). ``variant=None`` is the primary one."""
    d = _prop_dir(prop_id)
    if not d:
        return None
    stem = _stem_of(prop_id, variant)
    return ModelGallery(d, stem, (".glb",)) if stem else None


def model_path(prop_id: str, tier: str = "",
               variant: Any = None) -> Optional[Path]:
    """The ACTIVE mesh of ``tier`` in one variant — a tier the variant does
    not have falls back to the best available one, so a prop without a low
    variant still renders."""
    g = model_gallery(prop_id, variant)
    return g.find(tier) if g else None


def surface_for(prop_id: str, variant: Any = None) -> Optional[Dict[str, Any]]:
    """The payload block of a variant's baked surface, or None
    (spec-surface-height § 6.1).

    ``variant`` is the STORE index, like everywhere else in this module. The
    orientation fix is the FILE's (v2 E1) — every variant is its own mesh
    with its own dial — and the bake is only valid under the fix it was made
    with."""
    from app.core.model_surface import payload_block, read_surface
    mp = model_path(prop_id, variant=variant)
    if not mp:
        return None
    surface = read_surface(mp, file_areas(mp)[ROTATION_KEY])
    return payload_block(surface) if surface else None


def surface_status_for(prop_id: str, variant: Any = None) -> Dict[str, Any]:
    """What the prop panel shows about one variant's surface: baked, stale or
    missing (:func:`model_surface.surface_status`)."""
    from app.core.model_surface import surface_status
    mp = model_path(prop_id, variant=variant)
    return surface_status(mp, file_areas(mp)[ROTATION_KEY])


def delete_surface_for(prop_id: str, variant: Any = None) -> bool:
    """Remove one variant's baked walking surface — ``variant=None`` every
    ACTIVE one. True when at least one lattice was there and is gone.

    The counterpart of :func:`bake_surfaces` and it reads the same file
    through the same lookup, so what is removed is exactly what that call
    would overwrite. An unknown prop, an index this prop has no variant for
    and a variant with no mesh all answer False — there is nothing to remove,
    which is not an error but the state the caller asked about.

    RAISES :class:`SurfaceBakeRunning` while a bake of THIS prop is in flight.
    A bake writes every variant file it was asked for when its Blender run
    returns, so a delete slipped in beside it would be undone seconds later
    without a word. The check takes ``_lock`` and the unlink happens under it:
    a bake that starts between the check and the file operation would be the
    same race in slow motion.

    The walk gate's per-location cache goes WHOLESALE afterwards, like the
    bake's: a prop does not know where it stands, and a stale metre is worse
    than one recomposition.
    """
    from app.core.model_surface import delete_surface, forget_surfaces
    pid = safe_prop_id(prop_id)
    if not pid:
        return False
    meta = read_sidecar(pid)
    if not meta:
        return False
    indices = ([variant] if variant is not None
               else list(_active_indices(_variant_list(meta))))
    removed = False
    with _lock:
        if pid in _surface_building:
            raise SurfaceBakeRunning(pid)
        for idx in indices:
            mp = model_path(pid, variant=idx)
            if mp and delete_surface(mp):
                removed = True
    if removed:
        forget_surfaces()
    return removed


def bake_surfaces(prop_id: str, variant: Any = None, *,
                  background: bool = False, force: bool = False) -> None:
    """Bring one variant's walking surface up to date — ``variant=None`` every
    ACTIVE one (spec-surface-height § 5).

    Baked is exactly the file :func:`surface_for` reads back, so what the
    lattice describes is what the payload ships. A surface that is already
    valid for its file and fix is left alone: re-baking it would cost a Blender
    run per variant for a result identical to the stored one, an all-``null``
    lattice included. ``force`` bypasses that skip — it is the admin's "Bake
    surface" button (§ 8), which must do something visible. Nothing is reported
    back: a missing surface is a legal state.

    ONE bake per PROP at a time, synchronous and background callers alike: the
    fix is the prop's, so two runs would write the same variant files, and the
    loser's rotation on disk means every reader rejects the lattice and the
    prop silently walks on terrain. A request arriving mid-bake is not dropped
    but REMEMBERED — the running job takes one more turn, over EVERY active
    variant (a superset of whatever that call asked for; the validity guard
    makes the untouched ones free).

    SYNCHRONOUS by default: the generation chain calls it from its own worker,
    which already runs Blender step by step (``attach_measurement``), so one
    more step there is no news. Everything that sits on a REQUEST — the upload,
    a selection, the orientation dial — passes ``background``, because a
    lattice may wait minutes for a Blender slot and the spec's rule is "never
    in the request thread".
    """
    from app.core.model_surface import bake_surface, forget_surfaces, read_surface
    pid = safe_prop_id(prop_id)
    if not pid:
        return
    with _lock:
        if pid in _surface_building:
            _surface_dirty[pid] = _surface_dirty.get(pid, False) or force
            return
        _surface_building.add(pid)
        _surface_dirty.pop(pid, None)

    # A KEY GIVEN BACK INSIDE THE LOOP IS NOT OURS ANY MORE. The loop releases
    # it and marks itself done in ONE critical section — but between that and
    # the ``finally`` below (and the refused-thread handler) another request
    # may already have taken the very same key and started its own job. A
    # second ``discard`` would then steal ITS key, and the request after that
    # would start a third job on a prop that is being baked. So the release is
    # recorded, and everything downstream keeps its hands off.
    released = threading.Event()

    def _work() -> None:
        run_force = force
        # None = every active variant; a re-run always widens to that.
        only: Optional[List[Any]] = [variant] if variant is not None else None
        try:
            while True:
                # The sidecar is read HERE, inside the job: the fix that is
                # current when Blender starts is the one the lattice records,
                # not the one that stood when this call was made.
                meta = read_sidecar(pid)
                # Manually active, NOT effectively active: a variant that is
                # out of season right now still renders in its season, and a
                # lattice is baked from the mesh, not from the calendar.
                indices = (only if only is not None
                           else list(_active_indices(_variant_list(meta))))
                baked = False
                for idx in (indices if meta else []):
                    try:
                        mp = model_path(pid, variant=idx)
                        if not mp:
                            continue
                        # The fix is the FILE's (v2 E1), read beside the mesh.
                        fix = file_areas(mp)[ROTATION_KEY]
                        if not run_force and read_surface(mp, fix):
                            continue
                        # The world size THIS variant renders at decides the
                        # lattice resolution: the step is 0.25 WORLD metres and
                        # the lattice is cast in model units, so the bake needs
                        # the very ``max_m``/``measure`` the placement spec
                        # carries (``_prop_models``: max of the variant's three
                        # dims, measured over all three axes).
                        if bake_surface(mp, fix, wait_s=300,
                                        target_m=max(variant_dims(meta, idx).values()),
                                        measure="xyz"):
                            baked = True
                    except Exception as e:                  # noqa: BLE001
                        # Per VARIANT: one mesh that cannot be baked must cost
                        # neither the other variants their surface nor — on the
                        # synchronous path — the prop its measurement.
                        logger.warning("Prop %s: surface bake failed for "
                                       "variant %s: %s", pid, idx, e)
                if baked:
                    # A prop stands in many locations, so the walk gate's
                    # per-location cache (5 s) is dropped WHOLESALE — the prop
                    # does not know where it is placed, and a stale metre is
                    # worse than one recomposition.
                    forget_surfaces()
                with _lock:
                    if pid not in _surface_dirty:
                        # Released and marked done in ONE critical section, so
                        # a request arriving now starts its own job instead of
                        # writing into a dirty flag nobody reads again.
                        _surface_building.discard(pid)
                        released.set()
                        return
                    run_force = _surface_dirty.pop(pid)
                    only = None
        finally:
            # Safety net for what the loop's own guard cannot catch; a no-op on
            # the ordinary way out — and never on a key the loop gave back.
            with _lock:
                if not released.is_set():
                    _surface_building.discard(pid)

    if background:
        try:
            threading.Thread(target=_work, daemon=True,
                             name=f"prop-surface-{pid}").start()
        except RuntimeError:
            # A refused thread start gives the key back — otherwise this prop
            # would never be baked again in this process. Same rule: only while
            # the key is still ours.
            with _lock:
                if not released.is_set():
                    _surface_building.discard(pid)
                    _surface_dirty.pop(pid, None)
    else:
        _work()


def model_tiers(prop_id: str, variant: Any = None) -> List[str]:
    """The resolution tiers the prop actually HAS, sorted ('' id or no mesh →
    empty list).

    The SELECTION decides, not the files on disk: a prop switched off with the
    ``__none__`` sentinel has no tier at all. This is the read behind every
    ``variants`` map that names a prop (scene placements, terrain scatter) —
    only an existing tier may be offered, a guessed one is a 404 dressed up as
    a model.

    Being that read, this is also where a MISSING distance mesh is asked for
    (:func:`_demand_low`)."""
    g = model_gallery(prop_id, variant)
    tiers = sorted(g.tiers()) if g else []
    _demand_low(prop_id, variant, tiers)
    return tiers


def _published_entry(meta: Dict[str, Any], index: int,
                     tiers: List[str], *, markers: bool,
                     file: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ONE entry of the published variant list: ``{variant, tiers, dims,
    ground_offset_m?, slot_values?, markers?}`` — plus, on the prop RECORD
    (``file`` given), what its active mesh carries: ``areas``, ``rotation``,
    ``area_defaults``, ``areas_warning`` and ``leaf_bbox`` (while it has a
    leaf node).

    Written once, because it is the ONE shape a consumer resolves a placement's
    variant POSITION in — the world-prop payload, the ground boxes, the room
    recipe and the terrain scatter all index into it, and the fields a
    variant owns have to travel together or a placement gets one version's size
    with another one's sink — or, since v2 E1, one version's mesh with another
    one's orientation fix.

    ``ground_offset_m`` follows the storage law (absent = on the ground) so the
    payload does not carry a 0.0 for every prop in every world. ``markers`` are
    ADMIN detail and ride only where the full record does: the lean client
    library gets ``marker_count`` and nothing else, exactly as before.
    ``file`` is the :func:`file_areas` reading of the variant's active full
    mesh; the scatter/world-prop payloads (:func:`active_variant_tiers`) pass
    none and stay what they were.
    """
    entry: Dict[str, Any] = {"variant": index, "tiers": tiers,
                             "dims": variant_dims(meta, index)}
    off = variant_ground_offset(meta, index)
    if off:
        entry[GROUND_OFFSET_KEY] = off
    # WHAT THIS VERSION SHOWS in the prop's picture areas
    # (spec-picture-props.md § 5). It rides with the entry for the same reason
    # the size does: the consumer resolves ONE position in this list into one
    # placement, and the recipe would otherwise have to ask the library a
    # second time per placement. Absent when the variant shows nothing of its
    # own — every prop that is not a frame keeps the payload it always had.
    values = variant_slot_values(meta, index)
    if values:
        entry[SLOT_VALUES_KEY] = values
    if file is not None:
        # The measured facts of THIS variant's mesh (v2 E1): the recipe reads
        # `fix_euler`, `slots` and `leaf_bbox` off the entry a placement
        # resolves to, the Areas tab reads the same entry.
        entry[AREAS_KEY] = list(file[AREAS_KEY])
        entry[ROTATION_KEY] = dict(file[ROTATION_KEY])
        entry[AREA_DEFAULTS_KEY] = variant_area_defaults(meta, index)
        entry[AREAS_WARNING_KEY] = file[AREAS_WARNING_KEY]
        # …and what this version should COST (v2 E5) — the re-mesh dialog
        # opens on the prop record, so it prefills from here rather than
        # asking the variant list a second time. `None` = no statement.
        for key in (TARGET_FACES_HIGH_KEY, TARGET_FACES_LOW_KEY):
            entry[key] = _variant_entry(meta, index).get(key)
        if file[LEAF_BBOX_KEY]:
            entry[LEAF_BBOX_KEY] = file[LEAF_BBOX_KEY]
    if markers:
        own = variant_markers(meta, index)
        if own:
            entry[MARKERS_KEY] = own
    return entry


def active_variant_tiers(prop_id: str) -> List[Dict[str, Any]]:
    """Every EFFECTIVELY ACTIVE variant that HAS a mesh, in payload order:
    ``[{"variant": <store index>, "tiers": [...], "dims": {…},
    "ground_offset_m"?}, …]``.

    ``dims`` are the three real metres THIS variant renders at and
    ``ground_offset_m`` how deep it stands (:func:`variant_dims`,
    :func:`variant_ground_offset`). They ride along because the consumers of this list
    (the world-prop payload, the ground boxes, the terrain scatter) resolve a
    POSITION in it into one placement, and asking the library a second time per
    position would be the same sidecar read once per variant.

    "Effectively" = manually active AND in season (E2c,
    :func:`_effective_indices`) — the season gate sits in that one function, so
    the scatter, the world props and the scene payload all inherit it here.

    This is what becomes ``model_variants`` in the scene payload, and the
    reason element 0 is the primary variant is the whole compatibility
    contract: ``variants`` (the single map every existing consumer reads) is
    element 0 of this list. Variants without a mesh are DROPPED — an entry
    with no tier would be a placement that renders nothing, and the copies
    picking it would simply be missing from the wood.

    The store index rides along because it is NOT the position: switching
    variant 1 off leaves the payload with variants 0 and 2, and the serving
    URL of the second entry must say ``?variant=2``. A list position as the
    URL index would silently serve the mesh the admin just switched off."""
    meta = read_sidecar(prop_id)
    entries = _variant_list(meta)
    out: List[Dict[str, Any]] = []
    for i in _effective_indices(entries):
        tiers = model_tiers(prop_id, i)
        if tiers:
            out.append(_published_entry(meta, i, tiers, markers=False))
    return out


def _variant_stale(prop_id: str, index: int, primary_file: str,
                   primary_signature: str = "") -> bool:
    """Was this variant's mesh COPIED from a file the prop no longer shows?
    (ruling R4)

    ``copied_from`` on the active mesh's sidecar names the file the copy was
    taken from AND that gallery's signature at the time; the primary's active
    full file and its signature now are what they should be. A mesh that was
    never copied (the primary itself, an uploaded variant) is never stale —
    it is nobody's copy — and neither is anything while the PRIMARY has no
    active full mesh at all: there is nothing to compare against, and the tab
    must not offer a re-copy that can only fail.

    The SIGNATURE is checked as well as the name, because a name can come
    back: ``ModelGallery.new_path`` keys on the whole second, and since E4 a
    landing frees the name of the file it replaces — a re-cut inside the same
    second can therefore land under the predecessor's exact name, and a
    name-only comparison would call the copy current over a frame that
    changed. The signature carries ``created_at`` and moves either way."""
    if not primary_file:
        return False
    g = model_gallery(prop_id, index)
    active = g.find(DEFAULT_TIER, fallback=False) if g else None
    if not active:
        return False
    ref = read_model_sidecar(active).get(COPIED_FROM_KEY)
    if not isinstance(ref, dict):
        return False
    name = str(ref.get("file") or "")
    if not name:
        return False
    if name != primary_file:
        return True
    # Same name: only a RECORDED signature can still say "another file".
    stored = str(ref.get("signature") or "")
    return bool(stored) and bool(primary_signature) and stored != primary_signature


def list_variants(prop_id: str) -> List[Dict[str, Any]]:
    """The prop's variants for the admin strip: ``[{index, stem, active,
    seasons, in_season, tiers, has_model, model_file, model_url, signature,
    has_source, source_url, image, images, dims, dims_estimated, description,
    ground_offset_m, markers, slot_values, label, target_faces_high,
    target_faces_low, stale, surface_status}]`` — every variant, active or
    not, in order.

    ``target_faces_high`` / ``target_faces_low`` are what this version should
    COST in triangles (v2 E5), ``None`` where it states nothing — and that
    ``None`` is the whole point: the strip shows the backend's own default as
    a PLACEHOLDER, so an untouched field keeps meaning "whatever the backend
    does" instead of freezing today's default into the record.

    ``slot_values`` is WHAT this variant shows in the prop's picture areas
    (``{}`` = nothing of its own), ``label`` the name it is listed under and
    ``stale`` whether its COPIED mesh predates the frame the prop shows now
    (:func:`_variant_stale`) — the tab's "Re-copy mesh" runs on that flag.

    Since 2026-08-25 there is ONE number per field and no pair of them: the
    variant owns its size, its subject, its sink and its markers, so ``dims``
    are the three metres it really renders at (always complete),
    ``description`` the sentence its product shot is rendered from (``""`` =
    none, and the render falls back to the prop's NAME), ``ground_offset_m``
    its sink (0 = on the ground) and ``markers`` its object-local spots. The
    old ``effective_*`` twins are gone with the inheritance they described.

    ``seasons`` are the season names this variant is tagged for (E2c; empty =
    no dependency, the default) and ``in_season`` says whether that tag matches
    the world's CURRENT season — the strip needs both: the chips show what is
    stored, the flag shows what renders. ``primary`` follows the EFFECTIVE
    order, because the bare URL does too.

    ``model_url`` / ``source_url`` are the canonical serving URLs WITH their
    ``variant`` parameter (the primary one keeps the bare URL, which is the
    very string stored on scatter entries). ``image`` is what THIS variant's
    source image was rendered with — the panel shows the provenance of the
    picture it is displaying, not of some other variant's. ``images`` is
    ``{view: provenance}`` for every view file that exists (front, back, left,
    right), so the panel knows which of the four tiles it can show."""
    meta = read_sidecar(prop_id)
    entries = _variant_list(meta)
    primary = _effective_indices(entries)[0]
    primary_gallery = model_gallery(prop_id, primary)
    primary_file = primary_gallery.find(DEFAULT_TIER, fallback=False) \
        if primary_gallery else None
    primary_name = primary_file.name if primary_file else ""
    primary_sig = primary_gallery.signature(DEFAULT_TIER) if primary_gallery else ""
    now = current_season_tokens()
    out: List[Dict[str, Any]] = []
    for i, entry in enumerate(entries):
        g = model_gallery(prop_id, i)
        tiers = sorted(g.tiers()) if g else []
        active_file = g.find() if g else None
        base = f"/assets/props/{prop_id}/model"
        src_base = f"/assets/props/{prop_id}/source"
        has_source = source_path(prop_id, i) is not None
        out.append({
            "index": i,
            "stem": entry["stem"],
            "active": bool(entry["active"]),
            "seasons": list(entry.get(SEASONS_KEY) or []),
            "in_season": season_tags_active(entry.get(SEASONS_KEY), now),
            "primary": i == primary,
            "tiers": tiers,
            "has_model": bool(tiers),
            "model_file": active_file.name if active_file else "",
            "model_url": (base if i == primary else f"{base}?variant={i}") if tiers else "",
            "signature": g.signature() if g else "",
            "has_source": has_source,
            "source_url": ((src_base if i == primary else f"{src_base}?variant={i}")
                           if has_source else ""),
            "image": _image_meta(meta, entry["stem"]),
            "images": variant_images(prop_id, i),
            "dims": {k: entry[k] for k in DIM_KEYS},
            "dims_estimated": bool(entry.get(DIMS_ESTIMATED_KEY)),
            "description": entry.get(DESCRIPTION_KEY, ""),
            "ground_offset_m": entry.get(GROUND_OFFSET_KEY, GROUND_OFFSET_DEFAULT),
            "markers": entry.get(MARKERS_KEY, []),
            # The picture assignment of THIS variant, its pane defaults (v2
            # E1), the name it is listed under, and whether its copied frame
            # is out of date (R4).
            SLOT_VALUES_KEY: dict(entry.get(SLOT_VALUES_KEY) or {}),
            AREA_DEFAULTS_KEY: dict(entry.get(AREA_DEFAULTS_KEY) or {}),
            VARIANT_LABEL_KEY: entry.get(VARIANT_LABEL_KEY, ""),
            # What this version should COST in triangles (v2 E5) — `None`
            # where it states nothing, which is what the strip shows as the
            # backend default in its placeholder rather than as a value.
            TARGET_FACES_HIGH_KEY: entry.get(TARGET_FACES_HIGH_KEY),
            TARGET_FACES_LOW_KEY: entry.get(TARGET_FACES_LOW_KEY),
            "stale": _variant_stale(prop_id, i, primary_name, primary_sig),
            # This variant's own baked walking surface, STATE only (the
            # lattice is what ``surface`` means, and it travels on the scene
            # spec) — every variant is a mesh of its own and is baked on its
            # own (spec-surface-height § 6.1).
            "surface_status": surface_status_for(prop_id, i),
        })
    return out


#: What a NEW variant copies from its source (2026-08-25) — everything the
#: variant owns except its own files. The stem, the mesh gallery, the source
#: image and its provenance are what makes the new slot a new VERSION; the
#: fields below are what makes it a version OF THIS OBJECT.
#: ``area_defaults`` joins them (v2 E1): a new version of a door has the same
#: panes until its own mesh says otherwise — the landing of that mesh prunes
#: whatever the new file does not name (:func:`_prune_variant_entry`).
#: The face budgets join them for the same reason (v2 E5): a new version of
#: the same object costs the same, so the field opens FILLED and is edited.
_COPIED_ON_ADD = (*DIM_KEYS, DIMS_ESTIMATED_KEY, DESCRIPTION_KEY,
                  GROUND_OFFSET_KEY, MARKERS_KEY, AREA_DEFAULTS_KEY,
                  TARGET_FACES_HIGH_KEY, TARGET_FACES_LOW_KEY)


def add_variant(prop_id: str, source: Any = None) -> int:
    """Append a variant slot and return its index; ``-1`` when the prop does
    not exist or the active cap is already reached.

    The slot carries no mesh yet — a generation targeted at it fills it. This
    is what "generating appends instead of replacing" runs on.

    THE COPY SOURCE is the variant the admin currently has open (``source``, a
    STORE index) and the PRIMARY variant when none is named — the same
    resolution every other unqualified read uses (:func:`_variant_entry`). Size,
    ``dims_estimated``, subject, ground offset and markers come over as a COPY,
    not a link: the admin authors a version of THIS object, so every field
    opens filled and is EDITED ("…as a sapling") instead of written from
    nothing, and a later edit of the source leaves the new slot alone.

    Deliberately NOT gated on a running generation: appending a slot is a
    sidecar edit at the END of the list, it renumbers nothing and touches no
    file a job holds. The cap is the only ceiling."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return -1
    entries = _variant_list(meta)
    if len(_active_indices(entries)) >= variant_max():
        return -1
    stem = _free_stem(entries)
    if not stem:
        return -1
    src = _variant_entry(meta, source)
    entry: Dict[str, Any] = {"stem": stem, "active": True}
    for key in _COPIED_ON_ADD:
        if key in src:
            entry[key] = json.loads(json.dumps(src[key]))
    entries.append(entry)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return len(entries) - 1


def set_variant_active(prop_id: str, variant: int, active: bool) -> bool:
    """Switch one variant on or off. Switching the LAST active one off is
    refused: a prop with no active variant would render nothing, and that
    state belongs to the ``__none__`` selection sentinel, not to a toggle.

    A variant that is GENERATING right now cannot be toggled either — the
    active set decides which variant is the primary one, and moving that under
    a running job would send its image or its mesh to another stem."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return False
    entries = _variant_list(meta)
    try:
        i = int(variant)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(entries):
        return False
    if variant_generating(pid, i):
        return False
    if not active and len([e for e in entries if e["active"]]) <= 1:
        return False
    entries[i]["active"] = bool(active)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def set_variant_seasons(prop_id: str, variant: int, seasons: Any) -> bool:
    """Tag one variant with the seasons it depicts, or clear the tag (E2c).

    The names come from the world's ``game_seasons`` and are stored VERBATIM;
    matching is case-insensitive, so a pack authored in another world keeps
    working as long as the season is spelled the same. An empty list clears the
    key — no dependency is ABSENCE, never an empty list beside a missing one.

    Deliberately NOT refused for a generating variant (unlike the on/off
    toggle): a tag moves no file and renames no stem. It CAN move the primary
    variant, which is a payload fact and not a job's business — the run writes
    into the store index it was started with, and that number does not change.
    """
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return False
    pid, meta, entries, i = ctx
    _apply_variant_seasons(entries[i], seasons)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def _edit_variant(prop_id: str, variant: int,
                  ) -> Optional[Tuple[str, Dict[str, Any],
                                      List[Dict[str, Any]], int]]:
    """``(pid, meta, entries, index)`` for a variant write, or ``None`` when
    the prop or the index does not exist. The four setters below share it so
    they validate the index in exactly one way."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    entries = _variant_list(meta)
    try:
        i = int(variant)
    except (TypeError, ValueError):
        return None
    if not 0 <= i < len(entries):
        return None
    return pid, meta, entries, i


# ── The five variant fields: sanitize + store, once ─────────────────────
# Each applier is the BODY of the setter below it, lifted out so the batch save
# (:func:`bulk_update`) runs the very same sanitation instead of a second,
# laxer one. They mutate ONE entry and write nothing — the caller owns the
# sidecar write, which is what lets a batch do five fields of three variants in
# a single one.

def _apply_variant_dims(entry: Dict[str, Any], dims: Any) -> None:
    """Store this variant's size — a PATCH, key by key (see
    :func:`set_variant_dims` for the rules)."""
    patch = dims if isinstance(dims, dict) else {}
    touched = False
    for key in DIM_KEYS:
        if key not in patch:
            continue
        value = _coerce_dim_m(patch.get(key), 0.0)
        if value > 0:
            entry[key] = value
            touched = True
    if touched:
        entry[DIMS_ESTIMATED_KEY] = False


def _apply_variant_ground_offset(entry: Dict[str, Any], offset: Any) -> None:
    """Store the sink, or clear it (0 and junk are ABSENCE)."""
    value = _coerce_ground_offset_m(offset)
    if value is None:
        entry.pop(GROUND_OFFSET_KEY, None)
    else:
        entry[GROUND_OFFSET_KEY] = value


def _apply_variant_markers(entry: Dict[str, Any], markers: Any) -> None:
    """Replace the object-local marker list (an empty one clears the key)."""
    clean = sanitize_markers(markers)
    if clean:
        entry[MARKERS_KEY] = clean
    else:
        entry.pop(MARKERS_KEY, None)


def _apply_variant_description(entry: Dict[str, Any], text: Any) -> None:
    """Store the generation subject, or clear it (blank and junk are ABSENCE)."""
    desc = _coerce_description(text)
    if desc:
        entry[DESCRIPTION_KEY] = desc
    else:
        entry.pop(DESCRIPTION_KEY, None)


def _apply_variant_seasons(entry: Dict[str, Any], seasons: Any) -> None:
    """Store the season tags, or clear them (an empty list is ABSENCE)."""
    clean = sanitize_season_tags(seasons)
    if clean:
        entry[SEASONS_KEY] = clean
    else:
        entry.pop(SEASONS_KEY, None)


def _apply_variant_slot_values(entry: Dict[str, Any],
                               clean: Dict[str, Dict[str, str]],
                               label: Any) -> None:
    """Store an ALREADY CHECKED assignment and the name it is listed under.

    ``clean`` comes out of :func:`sanitize_variant_slot_values` — this only
    writes. An empty assignment removes the values (absence is how "this
    variant shows nothing of its own" is stored).

    THE LABEL IS THREE-VALUED (ruling R10), because "the body said nothing"
    and "the admin cleared the field" are different statements:

    * ``None`` — not mentioned: the stored name STANDS. Re-hanging a picture
      must not silently rename the variant the admin christened.
    * ``""`` — cleared: the name is DERIVED from the new values again
      (:func:`default_variant_label`), which is also what a brand-new variant
      with no stored name gets.
    * any text — stored verbatim (stripped, capped).
    """
    if clean:
        entry[SLOT_VALUES_KEY] = clean
    else:
        entry.pop(SLOT_VALUES_KEY, None)
    if label is None:
        text = (_coerce_variant_label(entry.get(VARIANT_LABEL_KEY))
                or default_variant_label(clean))
    else:
        text = _coerce_variant_label(label) or default_variant_label(clean)
    if text:
        entry[VARIANT_LABEL_KEY] = text
    else:
        entry.pop(VARIANT_LABEL_KEY, None)


def _apply_variant_face_targets(entry: Dict[str, Any], targets: Any) -> None:
    """Store this variant's face budgets — a PATCH, key by key, and
    THREE-VALUED per key (v2 E5), because "the body said nothing" and "the
    admin emptied the field" are different statements:

    * the key is ABSENT — the stored budget stands (clearing the high target
      must not silently drop the low one);
    * the key is ``null`` / ``""`` — the budget is cleared and the
      backend/config default takes over again;
    * a number — stored, or ``ValueError`` when it is outside the window
      (:func:`sanitize_face_target`; nothing is written then).
    """
    patch = targets if isinstance(targets, dict) else {}
    for key in (TARGET_FACES_HIGH_KEY, TARGET_FACES_LOW_KEY):
        if key not in patch:
            continue
        value = sanitize_face_target(patch.get(key))
        if value:
            entry[key] = value
        else:
            entry.pop(key, None)


#: The six fields a variant owns, by the name a batch body calls them — the
#: dims travel as ONE `dims` object because the trio is one statement (a prop
#: is scaled uniformly, so the three numbers say how big AND what shape), and
#: the two face budgets as ONE `face_targets` object for the same reason: high
#: and low describe one object at two distances.
VARIANT_PATCH_APPLIERS = {
    "dims": _apply_variant_dims,
    "description": _apply_variant_description,
    "ground_offset_m": _apply_variant_ground_offset,
    "markers": _apply_variant_markers,
    "seasons": _apply_variant_seasons,
    "face_targets": _apply_variant_face_targets,
}
#: The same names as a tuple, for the refusal message.
VARIANT_PATCH_KEYS = tuple(VARIANT_PATCH_APPLIERS)


def set_variant_dims(prop_id: str, variant: int, dims: Any) -> bool:
    """Set this variant's real size (2026-08-24, variant-only since
    2026-08-25).

    ``dims`` is a patch: only the keys it names are touched, so the height can
    be committed on its own. A usable number is stored (clamped to (0, 100]);
    EVERYTHING else — ``None``, an empty string, zero, junk — LEAVES THE
    CURRENT VALUE STANDING, because there is nothing to inherit any more and a
    variant with no size is not a state a payload may carry. A typing slip
    costs the edit, never the record.

    Storing a size CLEARS ``dims_estimated`` on that entry: a number the admin
    typed is never redistributed from the mesh proportions again.

    Deliberately NOT refused for a generating variant, exactly like the season
    tag: a size moves no file and renames no stem.
    """
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return False
    pid, meta, entries, i = ctx
    _apply_variant_dims(entries[i], dims)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def set_variant_ground_offset(prop_id: str, variant: int, offset: Any) -> bool:
    """How deep THIS variant stands in the ground, ± 5 m in centimetre steps
    (2026-08-25).

    The default 0.0 — and every junk value — REMOVES the key: "stands on the
    ground" is stored as absence and in no other shape, so a payload never
    carries a zero for it. Not refused for a generating variant: a sink moves
    no file and renames no stem.
    """
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return False
    pid, meta, entries, i = ctx
    _apply_variant_ground_offset(entries[i], offset)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def set_variant_markers(prop_id: str, variant: int, markers: Any) -> bool:
    """Replace THIS variant's object-local marker list (2026-08-25).

    The markers are fractions of THIS mesh's bounding box, so they belong to
    the variant and to no other: a seat that sits right on the grown chair sits
    somewhere else on the broken one. An empty list removes the key.
    """
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return False
    pid, meta, entries, i = ctx
    _apply_variant_markers(entries[i], markers)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def set_variant_description(prop_id: str, variant: int, text: Any) -> bool:
    """Give ONE variant its own generation subject, or clear it (2026-08-24).

    Blank, ``None`` and junk all CLEAR the key: "this variant has no subject of
    its own" is stored as absence and nothing else, and a render then composes
    from the prop's NAME — the same law the season tags follow.

    Deliberately NOT refused for a generating variant: the text is read when a
    render STARTS, so changing it mid-run changes nothing that is in flight,
    moves no file and renames no stem."""
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return False
    pid, meta, entries, i = ctx
    _apply_variant_description(entries[i], text)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def set_variant_slot_values(prop_id: str, variant: int, slot_values: Any,
                            label: Any = None) -> bool:
    """WHAT this variant shows in the prop's picture areas — the picture
    assignment itself (spec-picture-props.md § 1, D2). ``False`` when the prop
    or the index does not exist, ``ValueError`` for an unusable value.

    The areas belong to the VARIANT'S FILE (they are materials of its mesh,
    v2 E1) and so do the values: hanging another picture is a new version of
    the frame, not a new prop and not a property of the placement.
    Everything is checked against THAT variant's real areas
    (:func:`sanitize_variant_slot_values`) BEFORE anything is written, so a
    refused save leaves the sidecar exactly as it was — and the recipe can
    read the stored values verbatim.

    ``label`` is what the strip lists this variant under, three-valued
    (R10): ``None`` — the body did not mention it — KEEPS the stored name,
    ``""`` re-derives it from the picture file names, any text is stored. An
    EMPTY assignment clears the values, which is how a variant stops being a
    picture variant.

    Deliberately NOT refused for a generating variant, like the other value
    setters: a picture moves no file and renames no stem. It does move the
    prop's mesh signature (a swapped picture has to reach a running client),
    which is a payload fact and not a job's business."""
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return False
    pid, meta, entries, i = ctx
    clean = sanitize_variant_slot_values(
        slot_values, file_areas(_variant_full_file(pid, i))[AREAS_KEY])
    _apply_variant_slot_values(entries[i], clean, label)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return True


def set_variant_area_defaults(prop_id: str, variant: int,
                              area_defaults: Any) -> Optional[Dict[str, Any]]:
    """What this variant shows in its PANES when nobody hung anything —
    ``{"<area id>": {"preset": "glass"}}``, checked against THAT variant's
    file areas (:func:`sanitize_area_defaults`: the area must exist on its
    active full mesh and be a ``glass`` one). ``None`` when the prop or the
    index does not exist, ``ValueError`` for an unusable value — and nothing
    is written then. An EMPTY object clears the defaults.

    Returns the variant's published record (:func:`list_variants`)."""
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return None
    pid, meta, entries, i = ctx
    clean = sanitize_area_defaults(
        area_defaults, file_areas(_variant_full_file(pid, i))[AREAS_KEY])
    if clean:
        entries[i][AREA_DEFAULTS_KEY] = clean
    else:
        entries[i].pop(AREA_DEFAULTS_KEY, None)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return list_variants(pid)[i]


#: The sentinel that separates "the caller did not mention this budget" from
#: an explicit ``None``, which CLEARS it. A default of ``None`` could not tell
#: the two apart, and clearing the high target would then wipe the low one.
_KEEP = object()


def set_variant_face_targets(prop_id: str, variant: int,
                             high: Any = _KEEP,
                             low: Any = _KEEP) -> Optional[Dict[str, Any]]:
    """What this variant should COST in triangles (v2 E5) — the full mesh's
    budget and the distance mesh's. ``None`` when the prop or the index does
    not exist, ``ValueError`` for a number outside the window (and nothing is
    written then).

    Each argument is three-valued: OMITTED keeps the stored budget, ``None``
    clears it (the backend/config default takes over again), a number stores
    it. The pair is deliberately not one value: a variant may state what its
    close-up mesh costs and leave the distance mesh to the configured ratio.

    Returns the variant's published record (:func:`list_variants`)."""
    ctx = _edit_variant(prop_id, variant)
    if not ctx:
        return None
    pid, meta, entries, i = ctx
    patch: Dict[str, Any] = {}
    if high is not _KEEP:
        patch[TARGET_FACES_HIGH_KEY] = high
    if low is not _KEEP:
        patch[TARGET_FACES_LOW_KEY] = low
    _apply_variant_face_targets(entries[i], patch)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return list_variants(pid)[i]


def variant_face_targets(prop_id: str,
                         variant: Any = None) -> Dict[str, Optional[int]]:
    """``{target_faces_high, target_faces_low}`` of ONE variant, ``None`` per
    field where the variant states nothing — THE read every consumer of the
    budgets shares (generation, the improvement engine through it, the
    distance mesh, the mesh→mesh reduction).

    An unknown prop or index answers with two ``None``s: "no statement" is
    exactly what a caller can do something with, and there is no run in which
    a missing prop should mean a different face count."""
    entry = _variant_entry(read_sidecar(prop_id), variant)
    return {TARGET_FACES_HIGH_KEY: entry.get(TARGET_FACES_HIGH_KEY),
            TARGET_FACES_LOW_KEY: entry.get(TARGET_FACES_LOW_KEY)}


def _copy_variant_mesh(prop_id: str, target: int, source: Any = None) -> Path:
    """Copy the SOURCE variant's active full mesh into the TARGET variant's
    stem and select it — the mechanic a picture variant runs on (ruling R4).

    A picture variant is a version of the same object, so it carries the
    frame's mesh rather than referencing it: LOD, selection, signature and
    recipe stay exactly what they are, at the price of one GLB per picture.
    Everything that describes THAT mesh travels with it — the area fields of
    its sidecar (``areas``, ``leaf_bbox``, ``rotation``, the run stamps; v2
    E1: the copy is the same mesh, so it carries the same reading), the
    ``.areas.json`` companion (the outline edges the Areas tab draws) and the
    variant's source image WITH ITS EXTRA VIEWS, which the source-image law
    makes the variant's own — all of the source's views, and never a stale
    view the target happened to keep.

    The copy lands as a NEW gallery file, so a re-copy keeps the old one as
    history, and its model sidecar records :data:`COPIED_FROM_KEY`: the file
    it was taken from and that gallery's signature. THAT is what makes
    staleness a fact instead of a guess — the copy is stale as soon as the
    source's active full file is no longer that name.

    ``ValueError`` when there is nothing to copy or no such variant."""
    pid = safe_prop_id(prop_id)
    src_gal = model_gallery(pid, source) if pid else None
    src = src_gal.find(DEFAULT_TIER, fallback=False) if src_gal else None
    if not src:
        raise ValueError("this prop has no full-tier mesh to copy")
    dst_gal = model_gallery(pid, target)
    if not dst_gal:
        raise ValueError(f"this prop has no variant {target}")
    dst = dst_gal.new_path(src.suffix)
    shutil.copyfile(src, dst)
    prev = read_model_sidecar(src)
    write_model_sidecar(dst, {
        "created_at": utc_now_iso(),
        "source": "variant-copy",
        "format": prev.get("format") or "glb",
        "rig": prev.get("rig") or "none",
        "tier": DEFAULT_TIER,
        "source_file": src.name,
        COPIED_FROM_KEY: {"file": src.name,
                          "signature": src_gal.signature(DEFAULT_TIER)},
        **{k: prev[k] for k in _COPIED_RUN_KEYS if prev.get(k)},
        **{k: prev[k] for k in FILE_AREAS_KEYS if k in prev},
    })
    dst_gal.select(dst.name, DEFAULT_TIER)
    # A distance mesh this store built from the PREVIOUS copy shows the
    # previous frame — the same reason a split drops it.
    _drop_stale_low(dst_gal)
    companion = areas_sidecar_path(src)
    target_companion = areas_sidecar_path(dst)
    if companion and target_companion and companion.exists():
        shutil.copyfile(companion, target_companion)
    meta = read_sidecar(pid)
    src_stem = _stem_of(pid, source, meta=meta)
    dst_stem = _stem_of(pid, target, meta=meta)
    dirty = False
    src_img = source_path(pid, source)
    dst_img = _source_file(pid, target, create=True)
    if src_img and dst_img and src_img != dst_img:
        shutil.copyfile(src_img, dst_img)
        # …and what that picture was made with, so the panel shows the
        # provenance of the image it is displaying.
        rec = _image_meta(meta, src_stem)
        if any(rec.values()) and dst_stem and dst_stem != MODEL_STEM:
            entries = _variant_list(meta)
            for entry in entries:
                if entry["stem"] == dst_stem:
                    entry["image"] = rec
            meta[VARIANTS_KEY] = entries
            dirty = True
    # THE EXTRA VIEWS GO WITH IT: a copy is ONE version of the object, so it
    # takes all of the source's views — and where the source has none, the
    # target's own is REMOVED. A mixed set (front from this subject, a back
    # left over from what the target used to be) carries no marker saying so,
    # and the multi-view mesher would bake the two into one object.
    if src_stem and dst_stem and src_stem != dst_stem:
        for view in EXTRA_VIEWS:
            src_view = source_path(pid, source, view=view)
            dst_view = _source_file(pid, target, view=view, create=True)
            if not dst_view:
                continue
            if src_view:
                shutil.copyfile(src_view, dst_view)
                rec = _image_meta(meta, src_stem, view)
                if any(rec.values()):
                    _set_image_meta(meta, dst_stem, view=view, **rec)
                else:
                    _drop_image_meta(meta, dst_stem, view)
                dirty = True
            elif dst_view.exists():
                dst_view.unlink()
                _drop_image_meta(meta, dst_stem, view)
                dirty = True
    if dirty:
        _write_sidecar(pid, meta)
    return dst


def add_picture_variant(prop_id: str, slot_values: Any,
                        label: Any = None) -> int:
    """Hang a picture: a NEW variant of the frame prop that carries a COPY of
    the primary variant's mesh and shows ``slot_values`` on it (D2, § 1).

    Returns the store index of the new variant. ``ValueError`` for an unknown
    prop, an unusable or EMPTY assignment (a variant that shows nothing of its
    own is a plain :func:`add_variant`), a reached cap (R5) or a prop without a
    full-tier mesh to copy — and all of them are answered BEFORE anything is
    created, so a refusal leaves no half-built variant behind.

    The mesh is the PRIMARY variant's, because that is the frame everything
    else on this prop is a version of; the distance mesh is asked for exactly
    as it is for any other variant (:func:`request_low_tier`)."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        raise ValueError("unknown prop")
    entries = _variant_list(meta)
    src_index = _effective_indices(entries)[0]
    src_gal = model_gallery(pid, src_index)
    src_file = src_gal.find(DEFAULT_TIER, fallback=False) if src_gal else None
    # Checked against the areas of the mesh that is COPIED — the primary's
    # active full file (v2 E1: the areas are that file's).
    clean = sanitize_variant_slot_values(slot_values,
                                         file_areas(src_file)[AREAS_KEY])
    if not clean:
        # A variant that shows nothing of its own is a plain model variant —
        # `add_variant` is the verb for that, and it does not copy a mesh.
        raise ValueError("a picture variant needs at least one slot value")
    if len(_active_indices(entries)) >= variant_max():
        raise ValueError(f"At most {variant_max()} active variants per prop")
    if not src_file:
        raise ValueError("this prop has no full-tier mesh to copy")
    index = add_variant(pid, src_index)
    if index < 0:
        raise ValueError("no free variant slot")
    _copy_variant_mesh(pid, index, src_index)
    set_variant_slot_values(pid, index, clean, label)
    request_low_tier(pid, index)
    logger.info("Prop %s: picture variant %d added (%s)", pid, index,
                ", ".join(sorted(clean)) or "nothing")
    return index


def recopy_variant_mesh(prop_id: str, variant: int) -> bool:
    """Take the primary variant's mesh again for ONE picture variant (R4) —
    the answer to "variants outdated" after the frame was re-split.

    ``False`` when the prop or the index does not exist — and while THIS
    variant is GENERATING: the run is about to write the very file the copy
    lands in, the same reason a delete and the on/off toggle refuse it.
    ``ValueError`` for the primary variant itself (it IS the source). The
    assignment is kept: the admin re-copies the frame, not the picture — but
    it is CHECKED here (R15): this variant's mesh becomes the primary's, so
    a value naming an area the primary no longer has describes nothing any
    more and goes. This is the one moment a variant's values are re-read
    against the prop's current areas; a mere gallery click is not."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return False
    entries = _variant_list(meta)
    try:
        i = int(variant)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(entries):
        return False
    if variant_generating(pid, i):
        return False
    primary = _effective_indices(entries)[0]
    if i == primary:
        raise ValueError("the primary variant IS the mesh every picture "
                         "variant is copied from")
    _copy_variant_mesh(pid, i, primary)
    _prune_variant_values(pid, i)
    request_low_tier(pid, i)
    return True


def _prune_variant_values(pid: str, index: int) -> None:
    """Drop what ONE variant's ``slot_values`` and ``area_defaults`` say
    about areas its FRESH COPY does not carry (R15, the re-copy event: the
    copy brought the primary file's areas with it). Only that variant is
    touched — every other one still hangs on its own older copy."""
    meta = read_sidecar(pid)
    if not meta:
        return
    ids = {a["id"] for a in file_areas(_variant_full_file(pid, index))[AREAS_KEY]}
    if not _prune_variant_entry(meta, index, ids):
        return
    try:
        _write_sidecar(pid, meta)
    except (OSError, ValueError):
        return


def bulk_update(prop_id: str, general: Any = None,
                variants: Any = None) -> Optional[Dict[str, Any]]:
    """THE BATCH SAVE of the prop detail: the prop's own fields and any number
    of variant field patches, in ONE sidecar write. ``None`` when the prop does
    not exist.

    The detail panel keeps a LOCAL DRAFT and writes it with one explicit Save
    (the map editor's law, ``core/bulk_edit.py`` / ``tabs/props/pendingFields``).
    Every field used to go out on its own route the moment it lost focus, so
    authoring one variant — three metres, a subject, a sink, a season, a marker
    — was seven requests and seven sidecar writes for one thought.

    ``general`` is the prop patch :func:`update_prop` takes; ``variants`` maps a
    STORE INDEX (as a string or an int, the way JSON object keys arrive) to a
    patch of the five fields the variant owns
    (:data:`VARIANT_PATCH_APPLIERS`)::

        {"general": {"name": "Bench"},
         "variants": {"0": {"dims": {"width_m": 2.0}, "markers": []},
                      "2": {"seasons": ["Winter"]}}}

    EVERYTHING IS CHECKED BEFORE ANYTHING IS WRITTEN (``plan_batch``'s law): an
    unknown field, a moved field or an index this prop has no variant for raises
    ``ValueError`` and the sidecar is left exactly as it was. A body that is
    half junk must not leave a half-saved prop behind — the admin would have no
    way of telling which half arrived.

    Unknown keys are REFUSED rather than ignored, for the same reason the prop
    patch refuses the moved ones: a green "Saved" over a value that reached
    nothing is the worst of the three possible answers.

    NO VERSION STAMP, unlike the map's batch (``bulk_edit.plan_batch``), and
    that is a decision rather than an omission:

    * The map's stamps are a column of a SQLite row and its other writers are
      other EDITORS. A prop sidecar has no stamp, and its other writers are
      BACKGROUND JOBS — a finished render stores the image provenance, a
      finished mesh stores the bbox, a gallery selection writes too. A stamp
      would be bumped by all of them, so the honest single-editor case ("type a
      size while your own mesh bakes") would come back "changed on the server".
    * This batch merges FIELD BY FIELD into the sidecar as it is right now
      (read → apply the named fields → write), never a whole-record replace, so
      whatever a job wrote into OTHER keys survives it.
    * What is left is the write that lands between this read and this write —
      a race the single-value routes have had since they existed, which a
      stamp would report rather than prevent, and which needs one editor per
      prop to even occur.

    Nothing to do writes nothing — an empty body is a read.
    """
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    prop_patch = general if isinstance(general, dict) else {}
    _check_prop_patch(prop_patch, meta)

    raw = variants if isinstance(variants, dict) else {}
    entries = _variant_list(meta)
    plan: List[Tuple[int, Dict[str, Any]]] = []
    for key, patch in raw.items():
        try:
            i = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"variant key must be a store index: {key!r}")
        if not 0 <= i < len(entries):
            raise ValueError(f"this prop has no variant {i}")
        if not isinstance(patch, dict):
            raise ValueError(f"variant {i}: patch must be an object")
        unknown = [k for k in patch if k not in VARIANT_PATCH_APPLIERS]
        if unknown:
            raise ValueError(
                f"variant {i}: unknown field(s) "
                + ", ".join(sorted(unknown))
                + " (a variant owns: " + ", ".join(VARIANT_PATCH_KEYS) + ")")
        plan.append((i, patch))

    if not prop_patch and not plan:
        return _prop_record(pid, meta, full=True)
    _apply_prop_fields(meta, prop_patch)
    for i, patch in plan:
        for field, value in patch.items():
            VARIANT_PATCH_APPLIERS[field](entries[i], value)
    if plan:
        meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    return _prop_record(pid, meta, full=True)


def delete_variant(prop_id: str, variant: int) -> bool:
    """Remove one variant WITH its stored meshes, its selection entry and its
    SOURCE IMAGE. Refused for the last remaining variant — a prop always has
    one.

    The image goes because it belongs to this variant and to no other (the
    source-image law); a freed stem is handed out again, and an inherited
    picture would silently become the next variant's re-mesh input.

    Refused as well while THIS variant is generating: the run is about to write
    the very files the delete removes, and a deletion renumbers every variant
    behind it — the job would land in a stranger's slot."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return False
    entries = _variant_list(meta)
    try:
        i = int(variant)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(entries) or len(entries) <= 1:
        return False
    if variant_generating(pid, i):
        return False
    g = model_gallery(pid, i)
    if g:
        doomed = g.files()
        g.delete()
        _drop_areas_sidecars(doomed)
        # The stem's selection entry survives its files (``delete`` only
        # re-points what is left), and a freed stem may be handed out again —
        # so it goes with the variant.
        g.forget()
    for view in VIEWS:
        img = _source_file(pid, i, view=view)
        if img and img.exists():
            img.unlink()
    entries.pop(i)
    meta[VARIANTS_KEY] = entries
    _write_sidecar(pid, meta)
    _store_bbox(pid)
    return True


def prop_scatter_facts(prop_id: str) -> Dict[str, float]:
    """What a SCATTERED prop contributes to the terrain payload (§ A9), out of
    ONE sidecar read — ``{}`` for an id this world has no record for.

    Three facts, one read, because a scatter entry needs them all at once and a
    second walk of the prop directory per entry would undo exactly what
    ``with_scatter_props``' cache is there for:

    * ``height_m`` — the prop's REAL height in metres, the very number the
      Props tab shows. The mesh file cannot say it: its normalisation destroyed
      the scale, so it is the library record or nothing. Of the PRIMARY variant
      (2026-08-24), deliberately: which variant a painted-scatter instance
      shows is the one placement decision this server does NOT make — the
      instances are sampled client-side in a camera window and pick their
      variant there — so there is no variant to resolve here, and the entry
      carries the primary one's height like it carries its URL.
    * ``sway_factor`` — how much of its ground's wind this prop takes part in
      (see :data:`SWAY_FACTOR_DEFAULT`).
    * ``ground_offset_m`` — how deep this prop stands in the ground, wherever
      it stands (see :data:`GROUND_OFFSET_DEFAULT`). Of the PRIMARY variant for
      the same reason the height is (2026-08-25, when the sink moved onto the
      variants): the instances are sampled client-side, so there is no variant
      to resolve here. A scattered copy is seated by the CLIENT on its own
      height sampler, so the number has to travel with the entry the same way
      the wind factor does.

    The lean read: the master sidecar and the same :func:`variant_dims` every
    listing goes through, without the gallery, bbox-backfill and per-run detail
    :func:`get_prop` collects.

    A record always answers with a usable height — a variant that authors no
    size reads back the ``DEFAULT_DIM_M`` cube. So an EMPTY dict means "no such
    prop", never "nothing authored"."""
    meta = read_sidecar(prop_id)
    if not meta:
        return {}
    return {"height_m": variant_dims(meta)["height_m"],
            "sway_factor": sway_factor_of(meta),
            "ground_offset_m": variant_ground_offset(meta)}


def prop_ground_extent(prop_id: str, variant: Any = None) -> Dict[str, float]:
    """How much GROUND one prop covers — ``{"width_m", "depth_m"}`` in metres,
    ``{}`` for an id this world has no record for.

    The horizontal half of :func:`prop_scatter_facts`' answer, out of the same
    single sidecar read and the same :func:`variant_dims`, because it is
    asked for a different reason: the scatter has to stay OUT of the box a
    deliberately placed prop occupies (``world_props.prop_boxes``, § A9b).

    ``variant`` is the STORE index of the variant this box is asked for; a
    caller that knows which mesh stands there passes it, and ``None`` answers
    for the primary variant (:func:`variant_dims`). A sapling variant of a pine
    keeps less ground clear than the grown one, and the box is the ground the
    mesh really covers.

    The two dims are the REAL ones stored after the orientation fix — x and z
    of the object as it stands — never anything measured on the mesh, whose
    normalisation destroyed the scale. ``height_m`` is deliberately not
    returned: a box on the ground plane has no use for it.
    """
    meta = read_sidecar(prop_id)
    if not meta:
        return {}
    dims = variant_dims(meta, variant)
    return {"width_m": dims["width_m"], "depth_m": dims["depth_m"]}


def prop_stack_facts(prop_id: str, variant: Any = None) -> Dict[str, float]:
    """Everything the stacking rule needs about ONE prop, out of ONE sidecar
    read — ``{}`` for an id this world has no record for.

    The union of :func:`prop_ground_extent` (the footprint a prop covers) and
    the two vertical facts of :func:`prop_scatter_facts` (how tall it is, how
    deep it stands): "put the teapot on the table" asks all four at once, and a
    second directory walk per placement would be the same read twice.

    ``variant`` is the STORE index of the variant standing there (``None`` =
    the primary one). Both ends of the stacking rule need it: a teapot on the
    TALL variant of a table lands higher than on the low one, and the height it
    lands at is the support's own. Since 2026-08-25 the SINK is resolved per
    variant too — a support that sits 10 cm deeper carries its top 10 cm lower,
    and that is the very number the rule subtracts.
    """
    meta = read_sidecar(prop_id)
    if not meta:
        return {}
    dims = variant_dims(meta, variant)
    return {"width_m": dims["width_m"], "depth_m": dims["depth_m"],
            "height_m": dims["height_m"],
            "ground_offset_m": variant_ground_offset(meta, variant)}


def placement_variant(prop_id: str, position: Any) -> Optional[int]:
    """The STORE index behind a placement's ``variant``, or ``None`` when the
    prop publishes no variant at all (no record, or no mesh anywhere).

    Two index spaces meet here, and confusing them is the classic defect of
    this feature (§ B2 addendum): a PLACEMENT stores a POSITION in the
    published list (``active_variant_tiers`` / ``model_variants``), while every
    sidecar-level function — :func:`variant_dims`, the serving URL, the
    variant-scoped routes — speaks the STORE index. Switching variant 1 off
    leaves the payload with the store indices 0 and 2, so position 1 IS store
    index 2.

    The position wraps modulo the published count, exactly like the payload
    resolves it: a stored index must never make a placement disappear because
    an admin deleted a mesh.
    """
    entries = active_variant_tiers(prop_id)
    if not entries:
        return None
    try:
        pos = int(position or 0)
    except (TypeError, ValueError):
        pos = 0
    return int(entries[pos % len(entries)].get("variant") or 0)


def _footprint_contains(box: Dict[str, Any], px: float, pz: float) -> bool:
    """Is the point inside the prop's TURNED footprint box?

    The point and the box centre are in the SAME stored frame — room-local
    metres in a room, location-local metres on the yard (§ A13a) — so nothing
    converts; the frame only has to be one and the same for both.

    The turn is the world's (§ A1.1 / § B2 step 3): a prop is drawn with
    ``rotation.y = +rad(yaw)``, which maps a local point to
    ``x = lx·cos θ + lz·sin θ``, ``z = −lx·sin θ + lz·cos θ``. Testing a world
    point therefore applies the INVERSE turn and compares against the half
    extents. That is the same arithmetic the floor plan's own hit test runs
    (``RoomLayoutEditor.propsAtPoint``), where the plan's y axis IS z — keep
    the two in lockstep or a prop can only be stacked where it is not.
    """
    th = math.radians(float(box.get("yaw") or 0.0))
    dx = px - float(box["at"][0])
    dz = pz - float(box["at"][1])
    cos, sin = math.cos(th), math.sin(th)
    lx = dx * cos - dz * sin
    lz = dx * sin + dz * cos
    return (abs(lx) <= float(box.get("width_m") or 0.0) / 2.0
            and abs(lz) <= float(box.get("depth_m") or 0.0) / 2.0)


def stack_offset_y(boxes: Sequence[Dict[str, Any]], index: int) -> Optional[float]:
    """THE STACKING RULE — the ``offset_y`` that sets one placement down on the
    prop it stands over ("put the teapot on the table"). ``None`` when no other
    placement's footprint covers this one's spot.

    PURE arithmetic over already-resolved boxes, so the numbers are checkable
    by hand (``scripts/smoke_scene_recipe.py`` [7f]). One box is a placement
    joined with its library facts::

        {at: [u, v], yaw?, offset_y?, width_m, depth_m, height_m,
         ground_offset_m?}

    ``at``/``yaw`` are the stored placement, the dims and ``ground_offset_m``
    belong to the PROP (:func:`prop_stack_facts`).

    The rule is one sentence: **the placed prop's base lands exactly on the top
    surface of the TOPMOST prop underneath it.** Written out over the base
    ladder the scene spec composes (§ B2 addendum 2026-08-20, automatic floor +
    the prop's own ``ground_offset_m`` + the placement's ``offset_y``)::

        top(support) = ground_offset_m(support) + offset_y(support) + height_m(support)
        offset_y(target) = top(support) − ground_offset_m(target)

    Both ground offsets are in there because both are real: a support that sinks
    10 cm into the floor has its top 10 cm lower, and a target authored to sink
    would otherwise sink into the table top instead of onto it. The automatic
    floor cancels — support and target stand in the same room, on the same
    plate, and only the difference is stored.

    "Underneath" is a FOOTPRINT test, not a distance: any other placement whose
    turned box covers this placement's anchor qualifies, and of those the one
    with the highest top surface wins (a mug on a tray on a table). Ties fall to
    the LATER placement — the one drawn on top in the plan.
    """
    if index < 0 or index >= len(boxes):
        return None
    target = boxes[index]
    px, pz = float(target["at"][0]), float(target["at"][1])
    best: Optional[float] = None
    for i, box in enumerate(boxes):
        if i == index or not box:
            continue
        if not _footprint_contains(box, px, pz):
            continue
        top = (float(box.get("ground_offset_m") or 0.0)
               + float(box.get("offset_y") or 0.0)
               + float(box.get("height_m") or 0.0))
        if best is None or top >= best:
            best = top
    if best is None:
        return None
    return round(best - float(target.get("ground_offset_m") or 0.0), 3)


def placement_stack_offset_y(placements: Sequence[Dict[str, Any]],
                             index: int) -> Optional[float]:
    """:func:`stack_offset_y` for a STORED placement list — the library read in
    front of the pure rule.

    ``placements`` is ``layout.props`` as the floor-plan editor holds it
    (``prop_id``, ``at``, ``yaw?``, ``offset_y?``, ``variant?``); a placement
    whose prop the library does not know drops out of the candidate list — a
    dangling id has no measurable surface to stand on. Scattered copies never
    take part: they are computed at compose time and stored nowhere, so no
    author can point at one.

    EVERY box is resolved for ITS OWN variant (2026-08-24), target and support
    alike: the placement's ``variant`` is a POSITION in the published list, so
    it goes through :func:`placement_variant` before the facts are read. A
    table placed as its tall variant carries the teapot at the tall variant's
    height, and the same teapot placed as its own small variant sinks by its
    own ground offset — the rule below is untouched, it is only fed the right
    numbers.
    """
    # Cached per prop AND position: two placements of the same prop may show
    # two different variants, and those are two different sizes.
    facts: Dict[Tuple[str, int], Dict[str, float]] = {}
    boxes: List[Optional[Dict[str, Any]]] = []
    for placement in placements:
        if not isinstance(placement, dict):
            boxes.append(None)
            continue
        pid = safe_prop_id(str(placement.get("prop_id") or ""))
        try:
            pos = max(0, int(placement.get("variant") or 0))
        except (TypeError, ValueError):
            pos = 0
        key = (pid, pos)
        if pid and key not in facts:
            # `placement_variant` answers None for a prop that publishes no
            # variant at all, and that is exactly the primary-variant read.
            facts[key] = prop_stack_facts(pid, placement_variant(pid, pos))
        f = facts.get(key) or {}
        at = placement.get("at")
        if not f or not isinstance(at, (list, tuple)) or len(at) != 2:
            boxes.append(None)
            continue
        boxes.append({"at": [at[0], at[1]], "yaw": placement.get("yaw"),
                      "offset_y": placement.get("offset_y"), **f})
    if index < 0 or index >= len(boxes) or not boxes[index]:
        return None
    return stack_offset_y([b or {} for b in boxes], index)


def prop_id_from_model_url(url: Any) -> str:
    """The prop id behind the canonical model URL (``/assets/props/<id>/model``
    — the very string :func:`list_props` hands out as ``model_url`` and the map
    editor stores on a scatter entry); ``''`` for anything else.

    Deliberately strict: no host, no query, no trailing path. A foreign or
    absolute URL names a mesh this world knows nothing about, and guessing an
    id out of it would invent tiers that do not exist."""
    m = _MODEL_URL_RE.match(str(url or "").strip())
    return safe_prop_id(m.group(1)) if m else ""


def model_file_path(prop_id: str, filename: str,
                    variant: Any = None) -> Optional[Path]:
    """Path of ONE stored mesh by filename (the admin previews non-active
    files with it). Validated against the variant's stem; None when
    missing/foreign."""
    g = model_gallery(prop_id, variant)
    return g.file(filename) if g else None


def _variant_of_file(meta: Dict[str, Any], filename: str) -> int:
    """Which variant a stored mesh NAME belongs to — ``-1`` when the name
    names no variant of this prop. Same name law as
    ``ModelGallery._name_re``: ``<stem>`` or ``<stem>_<ts>`` plus the
    extension, so ``model-v2_17.glb`` is never read as the primary."""
    for i, entry in enumerate(_variant_list(meta)):
        if re.match(rf"^{re.escape(entry['stem'])}(_\d+)?\.[A-Za-z0-9]+$",
                    filename or ""):
            return i
    return -1


def _copied_from_label(meta: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    """``{file, variant}`` of a mesh that was COPIED from another variant —
    ``{}`` for every other file. The stored record names the file only
    (:data:`COPIED_FROM_KEY`); the index is resolved here because only this
    module knows the prop's variant list."""
    if not isinstance(raw, dict):
        return {}
    name = str(raw.get("file") or "")
    if not name:
        return {}
    return {"file": name, "variant": _variant_of_file(meta, name)}


def list_models(prop_id: str, variant: Any = None) -> List[Dict[str, Any]]:
    """All stored meshes of the prop for the admin gallery, newest first:
    ``[{filename, tier, selected_for, face_num, face_target_note,
    texture_size, format, created_at, backend, source, source_file, tris,
    lod_ratio, shrinkable, shrink_reason, active}]``. ``tier`` is what the file was made for,
    ``selected_for`` the tiers it currently serves, ``source_file`` the stored
    mesh a low variant was reduced FROM, ``tris``/``lod_ratio`` what the CPU
    reduction left of it (0 = not a reduced mesh), ``active`` the one a client
    without a tier request gets.

    ``label_parts`` is the GROUPED VIEW the gallery row's second line is built
    from (v2 E4): ``{source, areas_mode, areas_area, area_ids, source_file,
    copied_from, inherits_from}``. It repeats facts the flat row already
    publishes on purpose — the row is read by three panels and every one of
    them wants a different subset, while the label wants exactly these seven
    and nothing else. ``copied_from`` is resolved here into ``{file,
    variant}``: only this module can say WHICH variant a file name belongs
    to, and "Copy of variant 0" is the sentence the admin needs.

    ``shrinkable`` / ``shrink_reason`` come from the cheap capability probe
    (header + JSON chunk): a vertex-coloured mesh without UVs can never be
    reduced, and the admin must see that on the row instead of starting a job
    that fails permanently."""
    g = model_gallery(prop_id, variant)
    if not g:
        return []
    prop_meta = read_sidecar(prop_id)
    active = g.find()
    out: List[Dict[str, Any]] = []
    for p in g.files():
        meta = read_model_sidecar(p)
        cap = shrink_capability(p)
        fa = file_areas(p)
        area_ids = [a["id"] for a in fa[AREAS_KEY]]
        out.append({
            "filename": p.name,
            "tier": g.tier_of(p),
            "selected_for": g.selected_for(p.name),
            "face_num": int(meta.get("face_num") or 0),
            # Why the file has fewer faces than its variant asked for
            # ('' = it got what was asked; v2 E5).
            FACE_TARGET_NOTE_KEY: str(meta.get(FACE_TARGET_NOTE_KEY) or ""),
            "texture_size": int(meta.get("texture_size") or 0),
            "format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "created_at": meta.get("created_at", ""),
            "backend": meta.get("backend", ""),
            "source": meta.get("source", ""),
            "source_file": meta.get("source_file", ""),
            # What THIS file carries (v2 E1): its orientation fix, the ids of
            # its areas, and — for a distance mesh — the full file it
            # inherits them from (pattern `location_model3d.list_models`).
            ROTATION_KEY: fa[ROTATION_KEY],
            "area_ids": area_ids,
            INHERITS_FROM_KEY: str(meta.get(INHERITS_FROM_KEY) or ""),
            # Everything the row's second line says about WHERE this file
            # came from, in one place (v2 E4) — without it the list was a
            # column of identical minutes.
            "label_parts": {
                "source": str(meta.get("source") or ""),
                "areas_mode": str(meta.get("areas_mode") or ""),
                AREAS_AREA_KEY: str(meta.get(AREAS_AREA_KEY) or ""),
                "area_ids": area_ids,
                "source_file": str(meta.get("source_file") or ""),
                "copied_from": _copied_from_label(prop_meta,
                                                  meta.get(COPIED_FROM_KEY)),
                INHERITS_FROM_KEY: str(meta.get(INHERITS_FROM_KEY) or ""),
            },
            # What the reduction actually cost this file (0 = not a reduced
            # mesh, or one from before these numbers were recorded).
            "tris": int(meta.get("tris") or 0),
            "lod_ratio": float(meta.get("lod_ratio") or 0.0),
            "shrinkable": bool(cap["shrinkable"]),
            "shrink_reason": cap["reason"],
            "active": bool(active and p.name == active.name),
        })
    return out


def get_model_info(prop_id: str, variant: Any = None) -> Dict[str, Any]:
    """Gallery status of ONE variant for the admin panel: ``{models, tiers,
    none_selected, shrink_backends, blender}`` — the prop counterpart of
    ``location_model3d.get_building_info`` minus the img2mesh backend list
    (the props tab already carries that one). ``tiers`` are the resolution
    tiers the prop actually HAS; a missing one is what the admin sees as "low
    missing". ``shrink_backends`` are the mesh→mesh aliases behind "Create low
    variant" — a different list from the img2mesh backends, and empty when
    none is configured. ``blender`` is the refinement runner's state: without
    a usable Blender the CPU distance-mesh action cannot run, and the panel
    hides it instead of offering a button that always fails."""
    from app.blender import runner
    from app.core.model3d import list_shrink_backends
    g = model_gallery(prop_id, variant)
    return {
        "models": list_models(prop_id, variant),
        "tiers": sorted(g.tiers()) if g else [],
        "none_selected": bool(g and g.none_selected()),
        "shrink_backends": list_shrink_backends()["backends"],
        "blender": runner.status(),
    }


def select_model(prop_id: str, filename: str,
                 tier: str = DEFAULT_TIER, variant: Any = None) -> bool:
    """Make a stored mesh the active one of ``tier`` in one variant. An EMPTY
    filename deselects — on the default tier that persists the "render
    nothing" sentinel, on any other tier the tier ceases to exist. False when
    the prop, the variant or the file does not exist."""
    g = model_gallery(prop_id, variant) if read_sidecar(prop_id) else None
    if not g or not g.select(filename, tier):
        return False
    if (normalize_tier(tier) or DEFAULT_TIER) == DEFAULT_TIER:
        # The mesh the dims are derived from changed — re-measure it.
        _store_bbox(prop_id, variant)
    return True


def delete_model(prop_id: str, filename: str = "",
                 variant: Any = None) -> bool:
    """Remove ONE stored mesh (+ its sidecar) or ALL of a variant's. A
    selection pointing at a removed file moves to the newest remaining one
    (default tier) or is dropped (any other tier)."""
    g = model_gallery(prop_id, variant) if read_sidecar(prop_id) else None
    if not g:
        return False
    doomed = [g.file(filename)] if filename else g.files()
    if not g.delete(filename):
        return False
    _drop_areas_sidecars(doomed)
    _store_bbox(prop_id, variant)
    return True


def _drop_areas_sidecars(files: Sequence[Optional[Path]]) -> None:
    """The ``.areas.json`` companions of removed mesh files go with them —
    the gallery only knows a file's own ``.json`` sidecar."""
    for f in files:
        sp = areas_sidecar_path(f) if f else None
        if sp and sp.exists():
            try:
                sp.unlink()
            except OSError:
                pass


# ── The source image, one per variant ───────────────────────────────────
# A variant is a whole object version, so the product shot it was meshed from
# belongs to it and not to the prop (module docstring, "THE SOURCE IMAGE
# FOLLOWS THE MESH"). Same law as the meshes, same suffix, same
# no-migration path: base stem → source.png, model-v<n> → source-v<n>.png.

def source_name(stem: str) -> str:
    """File name of the source image belonging to ONE mesh stem — ``''`` for
    a stem this store would not hand out."""
    if not _VARIANT_STEM_RE.match(stem or ""):
        return ""
    if stem == MODEL_STEM:
        return SOURCE_NAME
    return f"source-{stem.split('-', 1)[1]}.png"


def view_source_name(stem: str, view: str) -> str:
    """File name of ONE view of a variant's source image: the front keeps
    :func:`source_name`, every extra view hangs ``_<view>`` off that stem
    (``source_back.png``, ``source-v2_left.png``). ``''`` for a stem this
    store would not hand out or an unknown view."""
    base = source_name(stem)
    if not base or not is_view(view):
        return ""
    if view == "front":
        return base
    return f"{base[:-len('.png')]}_{view}.png"


def _source_file(prop_id: str, variant: Any = None, *, view: str = "front",
                 create: bool = False) -> Optional[Path]:
    """Where ONE view of a variant's source image LIVES, whether or not it
    exists yet. ``None`` for an unknown prop, an index this prop has no
    variant for, or an unknown view."""
    d = _prop_dir(prop_id, create=create)
    if not d:
        return None
    name = view_source_name(_stem_of(prop_id, variant), view)
    return (d / name) if name else None


def source_path(prop_id: str, variant: Any = None,
                view: str = "front") -> Optional[Path]:
    """The EXISTING source image of one variant and view — ``None`` (or a
    negative index) means the PRIMARY variant, i.e. the same file every
    unqualified read has always served. ``None`` when this variant has no
    such image yet."""
    p = _source_file(prop_id, variant, view=view)
    return p if p and p.exists() else None


def _image_meta(meta: Dict[str, Any], stem: str,
                view: str = "front") -> Dict[str, str]:
    """What is recorded about ONE view of a variant's source image: backend,
    prompt, negative, generated_at (empty strings when nothing is recorded)."""
    keys = IMAGE_META_KEYS
    if view != "front":
        if stem == MODEL_STEM:
            rec = (meta.get(IMAGE_VIEWS_KEY) or {}).get(view) or {}
        else:
            rec = {}
            for entry in _variant_list(meta):
                if entry["stem"] == stem:
                    rec = (entry.get(IMAGE_VIEWS_KEY) or {}).get(view) or {}
        return {k: str(rec.get(k) or "") for k in keys}
    if stem == MODEL_STEM:
        return {k: str(meta.get(_IMAGE_META_MASTER[k]) or "") for k in keys}
    for entry in _variant_list(meta):
        if entry["stem"] == stem:
            img = entry.get("image") or {}
            return {k: str(img.get(k) or "") for k in keys}
    return {k: "" for k in keys}


def _set_image_meta(meta: Dict[str, Any], stem: str, *, view: str = "front",
                    backend: str = "", prompt: str = "", negative: str = "",
                    generated_at: str = "") -> None:
    """Record what a freshly written source image (of one view) was made
    with, IN PLACE. The caller writes the sidecar.

    ``generated_at`` defaults to NOW, which is what a fresh write means; a
    COPY passes the original stamp through, because the copy displays the
    very same picture and inventing a new date for it would be a lie."""
    rec = {"backend": backend, "prompt": prompt, "negative": negative,
           "generated_at": generated_at or utc_now_iso()}
    if view != "front":
        if stem == MODEL_STEM:
            meta.setdefault(IMAGE_VIEWS_KEY, {})[view] = rec
            return
        entries = _variant_list(meta)
        for entry in entries:
            if entry["stem"] == stem:
                entry.setdefault(IMAGE_VIEWS_KEY, {})[view] = rec
        meta[VARIANTS_KEY] = entries
        return
    if stem == MODEL_STEM:
        for k, m in _IMAGE_META_MASTER.items():
            meta[m] = rec[k]
        return
    entries = _variant_list(meta)
    for entry in entries:
        if entry["stem"] == stem:
            entry["image"] = rec
    meta[VARIANTS_KEY] = entries


def _drop_image_meta(meta: Dict[str, Any], stem: str, view: str) -> None:
    """Forget the provenance of a deleted EXTRA view, in place."""
    if stem == MODEL_STEM:
        (meta.get(IMAGE_VIEWS_KEY) or {}).pop(view, None)
        return
    entries = _variant_list(meta)
    for entry in entries:
        if entry["stem"] == stem:
            (entry.get(IMAGE_VIEWS_KEY) or {}).pop(view, None)
    meta[VARIANTS_KEY] = entries


def save_source_image(prop_id: str, contents: bytes, variant: Any = None, *,
                      view: str = "front", backend: str = "", prompt: str = "",
                      negative: str = "") -> bool:
    """Store image bytes as ONE view of a variant's source image (default
    front). False when the prop/variant/view is unknown or the bytes are not
    a readable image.

    The picture is normalised exactly like a rendered one — at most 1024 px on
    the long edge, PNG — but an ALPHA channel survives: a cut-out upload is
    transparent outside the object, and flattening it would hand the next
    re-mesh a background the mesher has to guess away again."""
    import io

    from PIL import Image, UnidentifiedImageError

    # A prop that does not exist gets no directory: a write path may create
    # the folder of a KNOWN prop, never conjure a ghost one from a typo'd id.
    if not read_sidecar(prop_id):
        return False
    target = _source_file(prop_id, variant, view=view, create=True)
    if not target:
        return False
    try:
        img = Image.open(io.BytesIO(contents))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return False
    img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    img.save(target, "PNG")
    meta = read_sidecar(prop_id)
    _set_image_meta(meta, _stem_of(prop_id, variant), view=view,
                    backend=backend, prompt=prompt, negative=negative)
    _write_sidecar(prop_id, meta)
    logger.info("Prop %s: %s source image stored for variant %s (%s, %d bytes)",
                safe_prop_id(prop_id), view, variant, target.name,
                len(contents))
    return True


def delete_source_image(prop_id: str, variant: Any, view: str) -> bool:
    """Remove ONE extra view image of a variant (never the front — that is
    the variant's identity picture). False when nothing was there."""
    if view not in EXTRA_VIEWS:
        return False
    p = source_path(prop_id, variant, view=view)
    if not p:
        return False
    p.unlink()
    meta = read_sidecar(prop_id)
    _drop_image_meta(meta, _stem_of(prop_id, variant), view)
    _write_sidecar(prop_id, meta)
    return True


def variant_images(prop_id: str, variant: Any = None) -> Dict[str, Dict[str, str]]:
    """``{view: provenance}`` for every view whose file exists on this
    variant — what the detail's source panel renders its four tiles from."""
    meta = read_sidecar(prop_id)
    stem = _stem_of(prop_id, variant)
    return {v: _image_meta(meta, stem, v) for v in VIEWS
            if source_path(prop_id, variant, view=v)}


def save_uploaded_glb(prop_id: str, contents: bytes,
                      tier: str = DEFAULT_TIER, variant: Any = None) -> bool:
    """Store an uploaded GLB as a NEW mesh of one variant and make it the
    active one of its tier. The prop record must already exist (created
    first); validation is the caller's job."""
    g = model_gallery(prop_id, variant) if read_sidecar(prop_id) else None
    if not g:
        return False
    # The dial the admin set on the file this one replaces is the default
    # for the variant's next mesh (v2 E1: the fix is the file's; a mesh with
    # other axes is re-dialled). A low upload inherits nothing here — the
    # tier it lands in follows its full file.
    previous = (g.find(DEFAULT_TIER, fallback=False)
                if (normalize_tier(tier) or DEFAULT_TIER) == DEFAULT_TIER else None)
    inherited = file_areas(previous)[ROTATION_KEY] if previous else None
    target = g.new_path()
    target.write_bytes(contents)
    write_model_sidecar(target, {
        "created_at": utc_now_iso(),
        "source": "upload",
        "format": "glb",
        "rig": "none",
        "tier": tier or DEFAULT_TIER,
        **({ROTATION_KEY: inherited}
           if inherited and any(inherited.values()) else {}),
    })
    g.select(target.name, tier)
    logger.info("Prop %s: model uploaded (%d bytes) -> %s",
                safe_prop_id(prop_id), len(contents), target.name)
    _store_bbox(prop_id, variant, landing=True)
    return True


# ── Model bounding box ──────────────────────────────────────────────────

def _extract_bbox(prop_id: str) -> Optional[List[float]]:
    """Edge lengths ``[bx, by, bz]`` of the PRIMARY variant's AABB in MESH
    units on the RAW mesh axes (no orientation fix applied), round 5 — None
    when the model is missing, unreadable or degenerate (a zero-volume box
    carries no proportions).

    Only the primary variant is measured: the dims describe the OBJECT, and
    four meshes of the same chair must not each redistribute them."""
    mp = model_path(prop_id)
    if not mp:
        return None
    try:
        bounds = glb_bounds(mp.read_bytes())
    except OSError:
        return None
    if not bounds:
        return None
    lo, hi = bounds
    sizes = [round(hi[i] - lo[i], 5) for i in range(3)]
    return sizes if max(sizes) > 0 else None


def _retexture_file(path: Optional[Path], label: str) -> None:
    """Re-encodes ONE stored GLB's textures to JPEG, if switched on.

    A prop is placed many times over, so its byte size is the one that
    multiplies. Geometry is untouched; the result is only kept if it is
    smaller and still validates as a static model."""
    from app.blender import refine
    from app.core.model_validate import validate_static_glb
    if not refine.auto_retexture_enabled():
        return
    if not path or Path(path).suffix.lower() != ".glb":
        return
    res = refine.retexture(Path(path), validator=validate_static_glb)
    if res.get("applied"):
        logger.info("%s: Texturen neu kodiert (%d bytes gespart)", label,
                    (res.get("data") or {}).get("bytes_saved", 0))


def _auto_retexture(prop_id: str, variant: Any = None) -> None:
    """Re-encodes one variant's ACTIVE model (see ``_retexture_file``)."""
    _retexture_file(model_path(prop_id, variant=variant), f"Prop {prop_id}")


def _auto_bake_vc(prop_id: str, variant: Any = None) -> None:
    """Converts a vertex-colour (Triposplat) model to a textured one, if
    switched on. Runs BEFORE the re-encode on purpose: the baked texture is a
    fresh PNG, and the retexture step turns it into JPEG in the same ingest.
    Without this step the model can neither be re-encoded nor reduced
    (``MeshNotShrinkable``) — the whole alias family was a dead end."""
    from app.blender import refine
    from app.core.model_validate import validate_static_glb
    path = model_path(prop_id, variant=variant)
    if (not refine.auto_bake_vc_enabled() or not path
            or not refine.needs_vc_bake(path)):
        return
    res = refine.bake_vertex_colors(path, validator=validate_static_glb)
    if res.get("applied"):
        d = res.get("data") or {}
        logger.info("Prop %s: vertex colours baked to a %d px texture "
                    "(%s -> %s boundary edges)", safe_prop_id(prop_id),
                    d.get("texture_size", 0), d.get("boundary_before"),
                    d.get("boundary_after"))
    elif res.get("error"):
        logger.info("Prop %s: vertex-colour bake not applied (%s)",
                    safe_prop_id(prop_id), res.get("error"))


def _lod_key(prop_id: str, variant: Any = None) -> str:
    """In-flight / failure key of ONE variant's distance mesh. Every variant
    reduces on its own, so a broken second mesh must not silence the first."""
    return f"{safe_prop_id(prop_id)}#{_stem_of(prop_id, variant) or '?'}"


def _glb_triangles(data: bytes) -> int:
    """Triangle count of a GLB, read from its glTF JSON alone.

    The number is in the accessors: a ``mode`` 4 primitive has one triangle
    per three indices (or per three positions when it is not indexed), and the
    scene uses a mesh once per node that references it. No BIN chunk is
    decoded and no geometry is touched — this runs on the polled distance-mesh
    path, where a full parse of every prop would be the cost of the feature.

    0 when the file says nothing usable; the caller then falls back to the
    configured ratio instead of dividing by an invented number.
    """
    try:
        gltf = parse_glb(data).get("gltf") or {}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, struct.error):
        return 0
    accessors = gltf.get("accessors") or []

    def _count(index: Any) -> int:
        if not isinstance(index, int) or not 0 <= index < len(accessors):
            return 0
        try:
            return int((accessors[index] or {}).get("count") or 0)
        except (TypeError, ValueError):
            return 0

    per_mesh: List[int] = []
    for mesh in (gltf.get("meshes") or []):
        total = 0
        for prim in ((mesh or {}).get("primitives") or []):
            if not isinstance(prim, dict) or int(prim.get("mode", 4) or 4) != 4:
                continue
            n = _count(prim.get("indices"))
            if not n:
                n = _count((prim.get("attributes") or {}).get("POSITION"))
            total += n // 3
        per_mesh.append(total)
    if not per_mesh:
        return 0
    # A mesh referenced by two nodes IS in the scene twice — that is what
    # Blender counts, and the ratio has to agree with what it will reduce.
    used = [n.get("mesh") for n in (gltf.get("nodes") or [])
            if isinstance(n, dict) and isinstance(n.get("mesh"), int)]
    if used:
        return sum(per_mesh[i] for i in used if 0 <= i < len(per_mesh))
    return sum(per_mesh)


def _source_triangles(model_path: Optional[Path]) -> int:
    """How many triangles ONE stored mesh has — 0 when nothing can say.

    The sidecar first (a Blender measurement, or the count a reduction left),
    the file itself second: measuring is what the sidecar is for, and a file
    that was never measured must still answer or the low target could not
    become a ratio."""
    if not model_path or not model_path.is_file():
        return 0
    meta = read_model_sidecar(model_path)
    measured = meta.get("measured")
    for value in ((measured or {}).get("tris") if isinstance(measured, dict)
                  else None, meta.get("tris")):
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return n
    try:
        return _glb_triangles(model_path.read_bytes())
    except OSError:
        return 0


def _lod_ratio_for(prop_id: str, variant: Any, src: Path) -> float:
    """The Decimate fraction ONE variant's distance mesh is built at.

    The variant's ``target_faces_low`` is an ABSOLUTE triangle count, Blender
    reduces by FRACTION — so the target only means anything against the
    source's own count: ``target / source_tris``, clamped to
    ``[LOD_RATIO_MIN, LOD_RATIO_MAX]``. Without a target (or without a
    readable source count) the configured per-kind ratio stands, which is what
    every prop did before the field existed.
    """
    from app.blender import refine
    target = variant_face_targets(prop_id, variant)[TARGET_FACES_LOW_KEY]
    if target:
        tris = _source_triangles(src)
        if tris > 0:
            return max(LOD_RATIO_MIN, min(target / tris, LOD_RATIO_MAX))
    return float(refine.lod_ratio("prop"))


def _backend_face_cap(backend: str) -> int:
    """The ``face_num_max`` of ONE mesh backend, 0 = no ceiling (or unknown).

    Read off the live backend objects rather than the config, because that is
    where the clamp itself lives (``openai_mesh._effective_faces``) — the note
    on a file must say the same number the job was actually cut to. Never
    raises: a note is worth nothing next to a lost generation result."""
    if not backend:
        return 0
    try:
        from app.imagegen.service import get_image_service
        svc = get_image_service()
        listers = (getattr(svc, "list_mesh_backends", None),
                   getattr(svc, "list_shrink_backends", None))
        for lister in listers:
            for b in (lister() if lister else []):
                if getattr(b, "name", "") == backend:
                    return int(getattr(b, "face_num_max", 0) or 0)
    except Exception:                                       # noqa: BLE001
        return 0
    return 0


def _face_target_note(backend: str, faces: Any) -> str:
    """What a file has to SAY when its backend cut the requested budget —
    '' when it got what was asked for (v2 E5).

    A silently halved budget is the kind of thing nobody finds again: the
    admin dials 60,000 on the variant, the alias hangs above 40,000 and caps
    it, and the gallery row would show a face count that agrees with neither.
    """
    cap = _backend_face_cap(backend)
    try:
        want = int(faces or 0)
    except (TypeError, ValueError):
        return ""
    if cap and want > cap:
        return f"clamped to backend maximum {cap}"
    return ""


def _reduce_to_low(pid: str, src: Path, ratio: float,
                   variant: Any = None) -> Dict[str, Any]:
    """The reduction itself: Blender Decimate, then a NEW gallery file that
    becomes the variant's ``low`` model. The caller holds the in-flight key.

    A failure is REMEMBERED (``_lod_failed``) and a success forgets it — that
    memory is what keeps the automatic path from grinding through the same
    broken mesh on every payload build."""
    from app.blender import refine
    key = _lod_key(pid, variant)
    out: Dict[str, Any] = {"ok": False, "tier": LOW_TIER, "ratio": ratio,
                           "tris": None, "tris_before": None, "size": 0,
                           "size_before": 0, "error": ""}
    res = refine.build_static_lod(src, ratio)
    if not res.get("ok"):
        _lod_failed.add(key)
        out["error"] = res.get("error") or "distance mesh not built"
        return out
    gallery = model_gallery(pid, variant)
    if not gallery:
        out["error"] = "no_model"
        return out
    if gallery.find(DEFAULT_TIER, fallback=False) != src:
        # The full mesh moved on while this ran (a picture-area split landed
        # a new file and dropped the old low tier): a distance mesh of the
        # superseded file must not become the low tier of the new one — the
        # next payload asks again and reduces the current file.
        out["error"] = "full mesh changed during the build"
        return out
    target = gallery.new_path()
    target.write_bytes(res["blob"])
    # The distance mesh is the SAME object: Decimate keeps node names and
    # materials (measured on real props), so it inherits the full file's
    # areas, leaf box and orientation instead of re-measuring them (v2 E1;
    # `file_areas` follows `inherits_from`, the copies are for a reader
    # whose full file is gone).
    prev = read_model_sidecar(src)
    write_model_sidecar(target, {
        "created_at": utc_now_iso(),
        "source": "lod",
        "format": "glb",
        "rig": "none",
        "tier": LOW_TIER,
        "source_file": src.name,
        "lod_ratio": ratio,
        "tris": res.get("tris"),
        "tris_before": res.get("tris_before"),
        INHERITS_FROM_KEY: src.name,
        **{k: prev[k] for k in _INHERITED_AREAS_KEYS if k in prev},
    })
    # THE SAME QUESTION AGAIN, NOW THAT THE FILE EXISTS. The check above is a
    # look BEFORE the write, and a picture-area split can land in the gap:
    # `_land_split` drops a stale low tier, but at that moment there is none to
    # drop, and the distance mesh of the file that was just replaced would then
    # become the low tier of its successor — the atlas where the picture is.
    # So the selection is written and read back under `_lock`, and a low mesh
    # that turns out to belong to the superseded file removes itself again
    # (`delete` takes the sidecar with it). The gallery is built FRESH here:
    # the instance above memoized the selection file before the reduction, and
    # writing that memo back would restore the superseded full tier.
    with _lock:
        fresh = model_gallery(pid, variant) or gallery
        fresh.select(target.name, LOW_TIER)
        if fresh.find(DEFAULT_TIER, fallback=False) != src:
            fresh.delete(target.name)
            out["error"] = "full mesh changed during the build"
            return out
    _lod_failed.discard(key)
    logger.info("Prop %s: distance mesh %s (%s -> %s tris)", pid,
                target.name, res.get("tris_before"), res.get("tris"))
    out.update(ok=True, tris=res.get("tris"),
               tris_before=res.get("tris_before"),
               size=target.stat().st_size, size_before=src.stat().st_size)
    return out


def build_low_tier(prop_id: str, ratio: float = 0.0, force: bool = False,
                   variant: Any = None) -> Dict[str, Any]:
    """Reduces one variant's full mesh to its distance mesh, BLOCKING (CPU).

    The result is a NEW gallery file selected as ``low`` — never an overwrite:
    a gallery keeps its history and the admin can go back to the previous low
    mesh or delete it. ``force`` is the admin's explicit rebuild; without it a
    gallery that already HAS a low tier is left alone (the automatic path,
    where an existing choice always wins). ``force`` also ignores the failure
    memory — the admin may have fixed the very thing that failed.

    ``ratio`` 0 takes the variant's own target (v2 E5:
    ``target_faces_low / source triangles``, clamped) and the configured
    per-kind fraction where it states none. One build per prop at a time, and
    the reduced mesh must pass the same static validation as a freshly
    delivered model. Returns ``{ok, tier, ratio, tris, tris_before, size,
    size_before, error}``.
    """
    out: Dict[str, Any] = {"ok": False, "tier": LOW_TIER,
                           "ratio": float(ratio or 0.0),
                           "tris": None, "tris_before": None, "size": 0,
                           "size_before": 0, "error": ""}
    pid = safe_prop_id(prop_id)
    g = model_gallery(pid, variant)
    src = g.find(DEFAULT_TIER, fallback=False) if g else None
    if not src or src.suffix.lower() != ".glb":
        out["error"] = "no_model"
        return out
    # AFTER the source is known: the variant's absolute low target only
    # becomes a fraction against THAT file's triangle count.
    ratio = float(ratio or _lod_ratio_for(pid, variant, src))
    out["ratio"] = ratio
    if LOW_TIER in g.tiers() and not force:
        out["error"] = "low tier already exists"
        return out
    key = _lod_key(pid, variant)
    with _lock:
        if key in _lod_building:
            out["error"] = "a distance mesh of this prop is already being built"
            return out
        _lod_building.add(key)
    try:
        return _reduce_to_low(pid, src, ratio, variant)
    finally:
        with _lock:
            _lod_building.discard(key)


def request_low_tier(prop_id: str, variant: Any = None) -> None:
    """Builds one variant's missing distance mesh in the BACKGROUND, if
    switched on ("Build distance meshes on demand").

    Called wherever a payload lists this prop's tiers (see
    :func:`_demand_low`), so it runs on POLLED paths and every gate is ordered
    by COST: the config flag, the in-process sets and the global slot come
    first, the gallery read and the GLB probe only for a candidate that could
    start right now. With every slot busy a sweep over a hundred props is
    therefore a hundred set lookups, not a hundred GLB parses.

    The in-flight key is taken BEFORE the thread starts
    (``model3d.request_lod``'s pattern): two simultaneous payload builds must
    not start two reductions. Key and slot are both released again on EVERY
    way out — a rejected candidate, a failed thread start, or the build
    itself.

    Serving never waits and nothing is reported back — a distance mesh is an
    optimisation, and its absence is a fallback, not an error."""
    from app.blender import refine
    from app.core.model_validate import shrink_capability
    if not refine.auto_lod_enabled():
        return
    pid = safe_prop_id(prop_id)
    if not pid:
        return
    key = _lod_key(pid, variant)
    if key in _lod_failed:
        return
    # An explicitly DESELECTED low tier is a decision, not a gap (user
    # finding 2026-08-20) — same rule as the location galleries.
    g = model_gallery(pid, variant)
    if g is not None and g.tier_declined(LOW_TIER):
        return
    with _lock:
        if key in _lod_building:
            return
        _lod_building.add(key)
    if not refine.take_lod_slot():
        with _lock:
            _lod_building.discard(key)
        return
    started = False
    try:
        g = model_gallery(pid, variant)
        src = g.find(DEFAULT_TIER, fallback=False) if g else None
        if not src or src.suffix.lower() != ".glb" or LOW_TIER in g.tiers():
            return
        # A mesh the store itself calls unreducible never becomes a low
        # variant; remembering it is what keeps the probe off the polled path.
        if not shrink_capability(src)["shrinkable"]:
            _lod_failed.add(key)
            return
        ratio = _lod_ratio_for(pid, variant, src)

        def _run() -> None:
            try:
                res = _reduce_to_low(pid, src, ratio, variant)
                if not res.get("ok"):
                    logger.debug("Prop %s: distance mesh not built (%s)", pid,
                                 res.get("error"))
            except Exception as e:                          # noqa: BLE001
                _lod_failed.add(key)
                logger.warning("Prop %s: distance-mesh build failed: %s",
                               pid, e)
            finally:
                refine.free_lod_slot()
                with _lock:
                    _lod_building.discard(key)

        threading.Thread(target=_run, daemon=True,
                         name=f"prop-lod-{key}").start()
        started = True
    finally:
        # Whatever ends this call without a running thread — a rejected
        # candidate or a refused thread start — gives both back. A leaked slot
        # would shrink the global limit for the rest of the process.
        if not started:
            refine.free_lod_slot()
            with _lock:
                _lod_building.discard(key)


def _demand_low(prop_id: str, variant: Any, tiers: List[str]) -> None:
    """A payload just listed one variant's resolution tiers — if ``low`` is
    missing while a full mesh exists, ask for it in the BACKGROUND.

    This is where the demand belongs, not on the serving route: every payload
    lists only the tiers a subject HAS, and every renderer picks from that
    list (``pickVariant``), so nobody ever requests a ``low`` that does not
    exist. The moment a client is TOLD there is no distance mesh is the
    moment to build one."""
    if tiers and LOW_TIER not in tiers:
        request_low_tier(prop_id, variant)


def _store_bbox(prop_id: str, variant: Any = None, *,
                landing: bool = False) -> None:
    """Everything that happens once a model has landed: re-encode its
    textures, measure it, persist ``bbox`` on the sidecar (one
    read-modify-write) and redistribute still-estimated dims over the fresh
    proportions. A failed measurement leaves the sidecar untouched.

    Called from the paths that store or re-point a mesh WITHOUT running the
    generation chain: ``save_uploaded_glb``, ``select_model``, ``delete_model``
    and ``delete_variant``. The chain itself (:func:`_generate`) selects and
    measures inline and does NOT come through here — a post-ingest step has to
    be added in BOTH places, which is why each of them says so (finding
    2026-08-27: the slot detection sat here alone and never fired for a
    generated prop).

    The per-file work (bake, re-encode, distance mesh) belongs to the variant
    that just received the mesh; the MEASUREMENT belongs to the object and is
    therefore only redone when the primary variant was the one that changed.

    ``landing`` is True for a mesh that just ARRIVED (the upload) and False
    for a re-pointed selection or a deleted file: only a landing may split
    the mesh into picture areas — the other paths reconcile the area list
    with the mesh that is active now."""
    _auto_bake_vc(prop_id, variant)
    # The picture-area split right after the bake (it renames every material)
    # and BEFORE the distance mesh is asked for, so the low tier is reduced
    # from the split file and not from the one it replaces. Never fails the
    # landing. The generation chain has the same call of its own (`_generate`).
    if landing:
        _areas_after_landing(prop_id, variant, wait_s=10.0)
    else:
        _reconcile_areas(prop_id, variant)
    _auto_retexture(prop_id, variant)
    request_low_tier(prop_id, variant)
    # The walking surface (spec-surface-height § 5 Nr. 1) — AFTER every step
    # that rewrites the mesh (bake, area split, re-encode), because the lattice
    # is only valid for the file it was measured on, and BEFORE the early
    # return below: a non-primary variant carries its own mesh and therefore
    # its own surface. In the BACKGROUND: unlike the generation chain, every
    # caller of this function (upload, selection, deletion) sits on the request
    # path, and a lattice may wait minutes for a Blender slot — "never in the
    # request thread" is the spec's own wording.
    bake_surfaces(prop_id, variant, background=True)
    if variant is not None and _stem_of(prop_id, variant) != _stem_of(prop_id):
        return
    # The texture slots are read AFTER the Blender steps above — the
    # vertex-colour bake renames every material — and before the measurement,
    # so an unmeasurable mesh still contributes the slots it names. Its own
    # read-modify-write, and it writes only when the result really changed.
    # The generation chain has the same call of its own (`_generate`).
    _autofill_slots(prop_id)
    bbox = _extract_bbox(prop_id)
    if not bbox:
        return
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return
    meta["bbox"] = bbox
    _redistribute_dims(meta, file_areas(model_path(prop_id))[ROTATION_KEY])
    # Same write, one more source: the header parser above yields the box, but
    # not the triangle count, the UV sets or whether the colour sits in the
    # vertices — and those are what decides whether a prop is cheap enough to
    # place many times. Purely informational; nothing here derives dims from it.
    mp = model_path(prop_id)
    if mp:
        from app.blender.refine import attach_measurement
        attach_measurement(meta, mp)
    try:
        _write_sidecar(pid, meta)
    except (OSError, ValueError):
        pass


def _ensure_bbox(prop_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy backfill for props whose model predates the ``bbox`` field: measure
    once on the first read, persist it, and remember failures per model mtime
    so an unmeasurable GLB is not re-parsed on every listing. Returns the
    (possibly updated) meta."""
    if meta.get("bbox") or not meta:
        return meta
    mp = model_path(prop_id)
    if not mp:
        return meta
    try:
        key = (safe_prop_id(prop_id), mp.stat().st_mtime_ns)
    except OSError:
        return meta
    if key in _bbox_failed:
        return meta
    bbox = _extract_bbox(prop_id)
    if not bbox:
        _bbox_failed.add(key)
        return meta
    meta["bbox"] = bbox
    try:
        _write_sidecar(prop_id, meta)
    except (OSError, ValueError):
        pass
    return meta


# ── Dims redistribution ─────────────────────────────────────────────────

def _redistribute_dims(meta: Dict[str, Any], rotation: Any = None) -> None:
    """Re-derive the PRIMARY variant's dims from the model's proportions,
    keeping the largest edge — ONLY while they are a still-estimated
    placeholder cube. A size the admin typed (``dims_estimated`` False) is
    never touched. ``rotation`` is the orientation fix of the mesh the box
    was measured on (the primary's active full file, v2 E1).

    The primary variant and no other: ``bbox`` is measured on ITS mesh
    (``_extract_bbox``), so it is the only entry whose proportions this box
    describes. A second variant's own bake refines nothing here — its size is
    authored in the strip.
    """
    entries = _variant_list(meta)
    i = _effective_indices(entries)[0]
    if not entries[i].get(DIMS_ESTIMATED_KEY) or not meta.get("bbox"):
        return
    dims = {key: _coerce_dim_m(entries[i].get(key)) for key in DIM_KEYS}
    entries[i].update(_dims_from_size(max(dims.values()), meta["bbox"],
                                      rotation))
    entries[i][DIMS_ESTIMATED_KEY] = False
    meta[VARIANTS_KEY] = entries


# ── Listing ─────────────────────────────────────────────────────────────

def _all_prop_ids() -> List[str]:
    d = _props_dir()
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        if p.is_dir() and safe_prop_id(p.name) and (p / SIDECAR_NAME).exists():
            out.append(p.name)
    return sorted(out)


def _picture_signature_part(entries: List[Dict[str, Any]],
                            rotations: Dict[int, Dict[str, Any]]) -> str:
    """What the PICTURES and the ORIENTATION contribute to a prop's mesh
    signature (spec-picture-props.md § 5, v2 E1): EVERY variant's
    ``area_defaults`` and ``slot_values``, keyed by store index, and the
    non-zero orientation fix of every ACTIVE variant's file (``rotations``).

    Every variant, not just the active ones: switching a picture variant on is
    a change of the cast the scene shows, and the mesh half of the signature
    already covers that — this half has to move when the picture ON one of
    them changes, whichever it is. A turned file keeps its name, so the fix
    has to be in the key or a running client would keep the old lean.
    ``""`` when the prop says nothing about pictures and stands untouched,
    so no other prop's key moves for this feature."""
    defaults = {str(i): e.get(AREA_DEFAULTS_KEY) or {}
                for i, e in enumerate(entries) if e.get(AREA_DEFAULTS_KEY)}
    values = {str(i): e.get(SLOT_VALUES_KEY) or {}
              for i, e in enumerate(entries) if e.get(SLOT_VALUES_KEY)}
    fixes = {str(i): r for i, r in rotations.items() if any(r.values())}
    if not defaults and not values and not fixes:
        return ""
    return "|" + json.dumps({"defaults": defaults, "variants": values,
                             "rotation": fixes}, sort_keys=True)


def _prop_record(prop_id: str, meta: Dict[str, Any], *, full: bool) -> Dict[str, Any]:
    meta = _ensure_bbox(prop_id, meta)
    entries = _variant_list(meta)
    # EFFECTIVELY active (E2c): manually active AND in season. The record is a
    # RENDER payload — the client prop library and every room recipe read
    # `variant_tiers` off it — so it has to answer with the cast a scene shows
    # now, exactly like `active_variant_tiers` does for the scatter next door.
    # The authoring views (`list_variants`, the cap, the generation target)
    # keep reading the manual set.
    active_idx = _effective_indices(entries)
    # Which resolution tiers each ACTIVE variant HAS — the selection decides,
    # not the presence of files (an admin may have switched a variant off with
    # the __none__ sentinel). Element 0 is the PRIMARY variant, so
    # `variant_tiers[0] == model_tiers` whenever the prop has a mesh at all —
    # that identity IS the "primary variant" contract every unchanged consumer
    # rides on (§ B2 addendum).
    galleries = [model_gallery(prop_id, i) for i in active_idx]
    tier_lists = [sorted(g.tiers()) if g else [] for g in galleries]
    # The record IS a client payload (the prop library the 3D client reads),
    # so this is one of the two places a missing distance mesh is noticed —
    # for every variant, not just the primary one.
    for i, vt in zip(active_idx, tier_lists):
        _demand_low(prop_id, i, vt)
    gallery = galleries[0]
    tiers = tier_lists[0]
    # …plus everything the VARIANT owns (2026-08-25): the three real metres it
    # renders at, how deep it stands and — on a full record — its markers,
    # and (v2 E1) what its ACTIVE FULL MESH carries: areas, leaf box,
    # orientation fix, pane defaults. A placement reads all of them off the
    # entry it draws (`room_recipe._placement_dims` and friends,
    # `scene_recipe._prop_models`) instead of off the record, which answers
    # for the PRIMARY variant.
    files = {i: file_areas(g.find(DEFAULT_TIER, fallback=False) if g else None)
             for i, g in zip(active_idx, galleries)}
    variant_tiers = [_published_entry(meta, i, vt, markers=full, file=files[i])
                     for i, vt in zip(active_idx, tier_lists) if vt]
    has_model = bool(tiers)
    # The PRIMARY variant's values — the answer to every question asked without
    # a variant in hand (the lean client library, the floor plan's schematic
    # footprint, the admin list row).
    primary = active_idx[0]
    dims = variant_dims(meta, primary)
    rec: Dict[str, Any] = {
        "id": prop_id,
        "name": meta.get("name") or prop_id,
        "category": meta.get("category") or "",
        "width_m": dims["width_m"],
        "depth_m": dims["depth_m"],
        "height_m": dims["height_m"],
        "tags": meta.get("tags") or [],
        # The fillable surfaces of this prop's mesh, `[{name, kind}, …]` —
        # ALWAYS present, so no consumer has to know the difference between
        # "none" and "not detected yet". On the lean record too: it is what a
        # scene's `slots` are matched against.
        "slots": meta.get(SLOTS_KEY) or [],
        # Which key colours the NEXT generation is asked for (ruling V2: the
        # one area fact that is the prop's wish, not a file's measurement).
        # Areas, leaf box, orientation fix and pane defaults are on
        # `variant_tiers[i]` — nothing of the kind on the record (v2 E1).
        KEY_AREAS_KEY: list(meta.get(KEY_AREAS_KEY) or []),
        "marker_count": len(variant_markers(meta, primary)),
        "has_model": has_model,
        "model_tiers": tiers,
        # Every active variant that has a mesh, in payload order:
        # `[{variant: <store index>, tiers: [...], dims: {…},
        # ground_offset_m?, markers?}, …]`, element 0 being the primary one
        # (its `tiers` IS `model_tiers`, its `dims` the record's own). The
        # store index is not the position — a switched-off variant leaves a
        # gap — and it is what the serving URL names. Turns into
        # `model_variants` on a spec.
        "variant_tiers": variant_tiers,
    }
    if full:
        # Image + provenance of the PRIMARY variant — the same file the bare
        # `/source` URL serves, so the list thumbnail and the record agree.
        # The per-variant records are in `list_variants`.
        has_source = source_path(prop_id) is not None
        image = _image_meta(meta, entries[active_idx[0]]["stem"])
        # What the library LIST needs to flag an incomplete prop: how many of
        # the ACTIVE variants (the ones a scene renders) still lack their mesh
        # resp. their source image. Three counts, never the variant records —
        # a row only has to say THAT something is missing; which one it is, is
        # what the variant strip in the detail shows.
        # Over the MANUALLY active variants, not the in-season ones (E2c): a
        # summer variant without its mesh is still a prop to finish while the
        # world is in winter, and a badge that hides it for three seasons hides
        # a defect, not a season.
        manual_idx = _active_indices(entries)
        manual_tiers = [sorted(g.tiers()) if g else []
                        for g in (model_gallery(prop_id, i) for i in manual_idx)]
        missing_mesh = sum(1 for vt in manual_tiers if not vt)
        missing_image = sum(1 for i in manual_idx
                            if source_path(prop_id, i) is None)
        # Per-run facts of the ACTIVE mesh (they live on its own sidecar since
        # the gallery rebuild) — the admin panel shows what the current model
        # was made with.
        active_file = gallery.find() if gallery else None
        run = read_model_sidecar(active_file) if active_file else {}
        rec.update({
            # The PRIMARY variant's subject and markers — the record has no
            # variant in hand, and this is the same answer every other
            # unqualified read gives (2026-08-25).
            "description": variant_description(meta, primary),
            "markers": variant_markers(meta, primary),
            "has_source": has_source,
            "created_at": meta.get("created_at") or "",
            "source": meta.get("source") or "",
            "backend": run.get("backend") or "",
            "face_num": int(run.get("face_num") or 0),
            "texture_size": int(run.get("texture_size") or 0),
            # Over ALL active variants: adding, removing or re-generating one
            # of them must move the scene signature, or a client that already
            # holds the room keeps showing the old cast of meshes.
            # …and over the PICTURES (spec-picture-props.md § 5) and the
            # per-file ORIENTATION (v2 E1): a swapped image or a turned dial
            # changes no mesh, no tier and no URL, so without them in the
            # key a running client would keep the old poster on the wall or
            # the old lean. Appended only when the prop says something about
            # pictures or stands turned, so every other prop's key stays
            # character for character what it was.
            "model_signature": hashlib.md5(
                ("|".join(f"{i}:{g.signature() if g else ''}"
                          for i, g in zip(active_idx, galleries))
                 + _picture_signature_part(
                     entries, {i: files[i][ROTATION_KEY] for i in active_idx})
                 ).encode()).hexdigest()[:12],
            "variant_count": len(variant_tiers),
            "variant_max": variant_max(),
            # Active variants in total, and how many of them are incomplete.
            # `variants_total - variants_missing_mesh == variant_count`
            # whenever no variant is out of season (E2c) — off-season ones
            # count here, because the badge is an authoring to-do list.
            "variants_total": len(manual_idx),
            "variants_missing_mesh": missing_mesh,
            "variants_missing_image": missing_image,
            "backend_image": image["backend"],
            "prompt": image["prompt"],
            "negative": image["negative"],
            "source_generated_at": image["generated_at"],
            "model_url": f"/assets/props/{prop_id}/model" if has_model else "",
            "model_file": active_file.name if active_file else "",
            "source_url": f"/assets/props/{prop_id}/source" if has_source else "",
            # Always the EFFECTIVE factor, never the raw key: the admin field
            # shows what applies, and "absent" is not a state a form can edit.
            "sway_factor": sway_factor_of(meta),
            # …and the same for the ground offset, of the PRIMARY variant:
            # 0.0 is what a prop that stands ON the ground reads back, whether
            # the key exists or not.
            "ground_offset_m": variant_ground_offset(meta, primary),
            # Where the slot list above came FROM: True = read off the model's
            # material names, False = authored in the editor. An authoring
            # detail, hence the full record only — the badge in the prop editor
            # is its one consumer.
            "slots_auto": bool(meta.get(SLOTS_AUTO_KEY)),
            # The PRIMARY variant's baked walking surface — STATE only, never
            # the lattice: the panel says baked/stale/missing and offers the
            # bake button, the numbers travel on the scene spec alone
            # (spec-surface-height § 6.1). Hence the name: ``surface`` is the
            # lattice, everywhere, and this is not it.
            "surface_status": surface_status_for(prop_id),
        })
        if meta.get("bbox"):
            rec["bbox"] = meta["bbox"]
        rec["dims_estimated"] = variant_dims_estimated(meta, primary)
    return rec


def list_props(*, full: bool = False) -> List[Dict[str, Any]]:
    """All props. ``full`` adds the sidecar detail + file urls (admin);
    otherwise the lean client shape (id, name, category, width_m, depth_m,
    height_m, tags, marker_count, has_model).

    The marker LISTS ride only on the full record — the lean client library
    gets the count, exactly as before the markers became per-variant."""
    out = []
    for pid in _all_prop_ids():
        meta = read_sidecar(pid)
        if meta:
            out.append(_prop_record(pid, meta, full=full))
    return out


def migrate_marker_surface_once() -> Dict[str, int]:
    """Marker heights now name the SURFACE, not the figure's root (2026-07-28).

    Until now a prop marker said where the figure's ROOT goes, and since the
    seat drop existed only in the 3D client's room-marker path, every author
    baked it in by hand — all 15 markers in the field carry a negative height,
    each a different guess (a bench at -0.63, a bar stool at -0.23). The scene
    recipe now ships ``root_offset`` with the marker and both renderers apply
    it, so the marker itself may finally mean "here is the seat".

    This lifts the stored fractions by exactly the drop the renderers will now
    subtract, so **nothing moves on screen**: a marker that sat right stays
    right, and one that sat wrong stays as wrong as it was — with a value that
    can now be corrected against the preview figure instead of by feel.

    Idempotent via a world_kv flag. Returns stats for the boot log.

    RUNS BEFORE ``prop_field_migration`` and reads the PRE-MOVE shape on
    purpose (prop-level ``markers`` + prop-level dims): both are one-time
    repairs, and a world that still needs this one still has its props in that
    shape. Once the field migration has run there is nothing here left to find.
    """
    from app.core.places_migration import group_for_kind
    from app.core.pose_catalog import get_groups
    from app.core.scene_recipe import FIGURE_HEIGHT_M
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(_MARKER_SURFACE_FLAG):
        return {}
    # The pre-move marker still names a clip KIND; the drop it implies is the
    # one of the place type that kind became (places_migration), read from
    # the catalog groups — the deleted FIGURE_ROOT_DROP table said the same.
    groups = get_groups()
    props = touched = 0
    for pid in _all_prop_ids():
        meta = read_sidecar(pid)
        markers = meta.get("markers") if isinstance(meta, dict) else None
        if not markers:
            continue
        props += 1
        bbox = meta.get("bbox") or []
        dims = [float(meta.get(f"{a}_m") or 0) for a in ("width", "depth", "height")]
        size_y = abs(float(bbox[1])) if len(bbox) > 2 else 0.0
        span = max(abs(float(b)) for b in bbox) if len(bbox) > 2 else 0.0
        # Real metres per marker-fraction of the Y axis — the same chain
        # compose_prop_marker walks: uniform real-size scale x raw box height.
        scale = (max(dims) / span) if (span > 0 and max(dims) > 0) else 0.0
        per_frac = size_y * scale
        if per_frac <= 0:
            continue
        changed = False
        for m in markers:
            drop = float((groups.get(group_for_kind(str(m.get("animation")
                                                             or "")))
                          or {}).get("root_drop") or 0.0)
            if not drop:
                continue
            at = m.get("at")
            if not isinstance(at, list) or len(at) != 3:
                continue
            # Cap at the same bound `sanitize_markers` enforces, so the
            # migration can never write a value the next UI edit would reject.
            # A prop so small that the drop overshoots it is unfixable by
            # arithmetic anyway — it needs a fresh marker.
            at[1] = round(min(float(at[1]) + (drop * FIGURE_HEIGHT_M) / per_frac,
                              MARKER_AT_MAX), 4)
            changed = True
            touched += 1
        if changed:
            meta["markers"] = markers
            _write_sidecar(pid, meta)
    set_world_setting(_MARKER_SURFACE_FLAG, "1")
    return {"props": props, "markers_lifted": touched}


def get_prop(prop_id: str) -> Optional[Dict[str, Any]]:
    """Full detail of ONE prop, or None."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    return _prop_record(pid, meta, full=True)


# ── Generation state (populated by the generation chain, A2) ─────────────

def _gen_key(prop_id: str, variant: Any, backend_glob: str,
             view: str = "") -> str:
    """Double-start key: prop, STORE VARIANT INDEX and backend. Two variants of
    the same prop may generate side by side — they are two objects to the GPU —
    while the same variant on the same backend stays one job.

    A view render carries its VIEW so a back and a left render of one variant
    run side by side while the same view stays one job.

    ``None`` is not a key of its own: an unqualified run works on the PRIMARY
    variant, so it resolves to that variant's index here. Otherwise the same
    picture could be rendered twice at once — once through the plain route and
    once through the primary variant's own — and the pair would race for one
    file. Resolving also makes the middle field always an integer, which is
    what :func:`pending_variants` reports back to the admin."""
    idx = primary_variant(prop_id) if variant is None else int(variant)
    return f"{prop_id}|{idx}|{(backend_glob or '').strip().lower()}|{view}"


def _split_gen_key(key: str) -> Tuple[str, int]:
    """``(prop id, store variant index)`` of an in-flight key. ``-1`` for a key
    whose middle field is not an index — nothing writes such a key today, and a
    malformed one must not take a whole listing down."""
    pid, _, rest = key.partition("|")
    idx, _, _ = rest.partition("|")
    try:
        return pid, int(idx)
    except ValueError:
        return pid, -1


def is_pending(prop_id: str = "") -> List[str]:
    """Prop ids with at least one running generation (any variant, any
    backend) — the boolean aggregate the library list row shows."""
    with _lock:
        ids = sorted({_split_gen_key(k)[0] for k in _generating})
    if not prop_id:
        return ids
    return [prop_id] if prop_id in ids else []


def pending_variants(prop_id: str = "") -> Dict[str, List[int]]:
    """Which VARIANTS are generating right now: ``{prop id: [store index, …]}``.

    The indices are STORE indices — the position in the prop's own variant
    list, the same number every variant-scoped route takes — never a position
    in some filtered view. A switched-off variant keeps its index, so the strip
    can put the spinner on the chip the job actually writes into.

    Props with nothing running do not appear at all; a ``prop_id`` narrows the
    answer to that prop (still as a map, so the caller reads it the same way)."""
    with _lock:
        keys = list(_generating)
    out: Dict[str, set] = {}
    for key in keys:
        pid, idx = _split_gen_key(key)
        if idx < 0 or (prop_id and pid != prop_id):
            continue
        out.setdefault(pid, set()).add(idx)
    return {pid: sorted(idx) for pid, idx in out.items()}


def variant_generating(prop_id: str, variant: Any) -> bool:
    """Is THIS variant of this prop generating right now? The gate on the two
    verbs that would pull the ground from under a running job — deleting the
    variant it writes into, or switching it off mid-run."""
    pid = safe_prop_id(prop_id)
    try:
        idx = primary_variant(pid) if variant is None else int(variant)
    except (TypeError, ValueError):
        return False
    return idx in pending_variants(pid).get(pid, [])


# ── Generation chain: prompt → txt2img source image → img2mesh GLB ───────
# The interior counterpart of location_model3d for single objects. Two GPU
# steps, both on the backend queue channel like every render: a txt2img
# product-shot render (use case ``prop``) becomes the VARIANT's source image
# (source.png for the base stem, source-v<n>.png beyond it), then
# ``service.generate_mesh(rig="none")`` turns it into model.glb (NEVER a
# mesh-backend fallback — the existing rule). Runs on a worker thread with the
# per-job double-start guard (prop_id|mesh backend).

def apply_key_areas(prompt: str, negative: str,
                    key_areas: Any) -> Tuple[str, str]:
    """Appends the chroma-key fragments for ``key_areas`` to a FINAL prompt
    and merges their negatives (spec-picture-props.md § 3; the text is
    ``config.KEY_AREA_PROMPTS`` / ``KEY_AREA_NEGATIVES``).

    Idempotent: a fragment the prompt already carries (the dialog showed the
    composed text and sent it back) is not appended twice. Kind order is the
    fixed one of ``AREA_KINDS``; a kind without a fragment (``leaf`` — the
    door image already shows frame and leaf) adds nothing."""
    from app.core.config import KEY_AREA_NEGATIVES, KEY_AREA_PROMPTS
    from app.core.prompt_compose import merge_tags
    prompt = (prompt or "").rstrip()
    negative = negative or ""
    for kind in sanitize_key_areas(key_areas):
        fragment = KEY_AREA_PROMPTS.get(kind, "")
        core = fragment.strip(" ,")
        if core and core not in prompt:
            prompt = prompt.rstrip(" ,") + fragment if prompt else core
        neg = KEY_AREA_NEGATIVES.get(kind, "")
        if neg and neg not in negative:
            negative = merge_tags(negative, neg)
    return prompt, negative


def compose_prompt(subject: str, backend, key_areas: Any = None,
                   use_case: str = "prop") -> Dict[str, str]:
    """Final source-render prompt + negative for a prop on a backend — the
    ``prop`` use-case style (per image family) with the object subject woven
    into its ``{subject}`` slot. The dialog shows exactly this and may edit it
    (final-prompt rule); ``style`` is returned RAW (slot included) so the UI
    can recompose it per object with the same weaving rule.

    The 3D-ASSET FRAMING ("A high-quality 3D model of …, designed for 3D asset
    generation, 8k resolution") is part of that style and of nothing else —
    see ``_DEFAULT_IMAGE_USE_CASES["prop"]`` in ``app.core.config``. Nothing
    here adds a phrase of its own, so the framing cannot land in a prompt
    twice.

    ``key_areas`` (``["picture", "glass"]``) appends the chroma-key fragment
    per kind to the composed prompt and its negative addition to the negative
    (:func:`apply_key_areas`) — the one thing this prompt gets beyond the
    style, and only on request. ``style`` stays raw either way.

    ``use_case`` picks the style of an extra VIEW (``prop_back`` /
    ``prop_side``); the front is ``prop``."""
    from app.core import config as _cfg
    from app.core.prompt_compose import compose as _compose
    ucp = _cfg.resolve_use_case_style(
        use_case,
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    subject = (subject or "").strip() or "a single object"
    # The composition itself (slot/append, negation guard, negative merge)
    # belongs to prompt_compose; only the return SHAPE is this module's, the
    # dialog recomposes per object from `style` + its own subject field.
    composed = _compose(use_case=use_case, subject=subject, backend=backend)
    prompt, negative = apply_key_areas(composed.prompt, composed.negative,
                                       key_areas)
    return {
        "style": (ucp.get("prompt_style") or "").strip(),
        "prompt": prompt,
        "negative": negative,
    }


def _render_source(prop_id: str, backend_glob: str,
                   prompt: str, negative: str, variant: Any = None, *,
                   view: str = "front",
                   front_reference: bool = False) -> bool:
    """txt2img render of the product shot → THIS VARIANT's source image. Runs
    the GPU job on the backend queue channel (like every render). Records the
    image backend + final prompt with the variant. Returns True on success.

    ``variant`` None is the primary one, whose image keeps the historic
    ``source.png``; every further variant renders into its own
    ``source-v<n>.png``, so a second version of the object cannot overwrite
    the picture the first one was meshed from.

    ``view`` names which of the four views is rendered — the front composes
    from the ``prop`` use case, an extra view from its own (``prop_back`` /
    ``prop_side``) and says the direction in the subject. ``front_reference``
    additionally slots THIS variant's front image as the appearance reference
    of an extra view."""
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    backend = None
    if backend_glob.strip():
        backend = svc.resolve_imagegen_target(backend_glob)
    if not backend:
        # Admin default for prop product shots (/admin/settings → Media
        # Generation → "Prop Default") — the ✨ Furnish job passes no glob.
        default_glob = os.environ.get("PROP_IMAGEGEN_DEFAULT", "").strip()
        if default_glob:
            backend = svc.resolve_imagegen_target(default_glob)
    if not backend:
        backend = svc._select_backend()
    if not backend:
        logger.warning("Prop %s: no image backend available", prop_id)
        return False

    from app.core.view_prompts import view_subject, view_use_case
    use_case = view_use_case("prop", view)
    meta0 = read_sidecar(prop_id)
    key_areas = meta0.get(KEY_AREAS_KEY) or []
    if not prompt.strip():
        # The stored description is the generation subject; the name is only
        # the display fallback when no description was written. It is THIS
        # VARIANT's description (2026-08-24) — a version of the object is
        # rendered from its own sentence where it has one, and only a variant
        # without one falls back to the prop's.
        composed = compose_prompt(
            view_subject(view, variant_description(meta0, variant)
                         or meta0.get("name", "")),
            backend, key_areas=key_areas, use_case=use_case)
        prompt = composed["prompt"]
        if not negative.strip():
            negative = composed["negative"]
    elif key_areas:
        # A prompt the dialog sent back already carries the chroma-key
        # fragments (the client mirrors them); one from an older client does
        # not. The request for key colours is on the record either way, and
        # the append is idempotent — so it is honoured either way.
        prompt, negative = apply_key_areas(prompt, negative, key_areas)

    params: Dict[str, Any] = {
        "width": 1024, "height": 1024,
        "seed": random.randint(1, 2**31 - 1),
    }
    # A back/side view may take the variant's FRONT image as its appearance
    # reference (design 2026-09-02) — only where a front exists and the
    # backend has a slot; otherwise the view renders from text alone.
    if view != "front" and front_reference:
        front = source_path(prop_id, variant)
        if not front:
            logger.info("Prop %s: no front image, %s view renders without "
                        "reference", prop_id, view)
        elif int(getattr(backend, "ref_slot_count", 0) or 0) < 1:
            logger.info("Prop %s: backend %s has no reference slot, %s view "
                        "renders without reference", prop_id, backend.name, view)
        else:
            params["reference_images"] = {"input_reference_image_1": str(front)}
    # The prompt arrives already composed (compose_prompt above, or edited in
    # the dialog) — the metablock records the use case, not a fresh compose.
    _log_meta = {"agent_name": f"Prop {prop_id}", "original_prompt": prompt,
                 "auto_enhance": False,
                 "compose": {"use_case": use_case, "settings_applied": True}}
    from app.core.llm_queue import get_llm_queue, Priority
    images = get_llm_queue().submit_gpu_task(
        provider_name=backend.name,
        task_type="prop_source" if view == "front" else f"prop_source_{view}",
        priority=Priority.IMAGE_GEN,
        callable_fn=lambda: backend.generate(prompt, negative, params,
                                             log_meta=_log_meta),
        agent_name="system",
        label=(f"Prop source: {prop_id}" if view == "front"
               else f"Prop source ({view}): {prop_id}"),
        gpu_type=backend.api_type)
    if not images:
        logger.warning("Prop %s: empty source render", prop_id)
        return False

    # One writer for every source image (upload, cutout, render): it norms the
    # picture and records the provenance the panel shows for THIS variant
    # (backend + when; prompt/negative in the tooltip).
    return save_source_image(prop_id, images[0], variant, view=view,
                             backend=backend.name, prompt=prompt,
                             negative=negative)


def _store_lod_stages(gallery: ModelGallery, stages: List[Dict[str, Any]],
                      main_file: str, backend: str,
                      texture_size: Any = None) -> str:
    """Store the LOD stages of ONE generation as their own gallery files and
    select the SMALLEST for tier ``low``. Returns the selected file name.

    A stage is a self-contained GLB baked from the same views as the main
    result (mesh-client-spec § 3.2), so it is a normal gallery file — not a
    companion of the main one. ``face_num`` is the REQUESTED count from the
    file name (the real one is only inside the GLB), ``source_file`` names the
    run's main mesh so the pair is visible in the admin list. Extra stages stay
    in the gallery unselected — the admin can promote any of them."""
    selected = ""
    for stage in stages:
        blob = stage.get("blob") or b""
        if not blob:
            continue
        path = gallery.new_path(f".{stage.get('format') or 'glb'}")
        path.write_bytes(blob)
        # LOD stages carry their own embedded textures and are, per the
        # gateway spec, often LARGER than the main result because of it —
        # they are exactly the files that must not stay uncompressed.
        _retexture_file(path, f"LOD {path.name}")
        write_model_sidecar(path, {
            "created_at": utc_now_iso(),
            "source": "lod",
            "format": stage.get("format") or "glb",
            "rig": "none",
            "tier": LOW_TIER,
            "backend": backend,
            "source_file": main_file,
            **({"face_num": int(stage.get("faces") or 0)}
               if stage.get("faces") else {}),
            **({"texture_size": int(texture_size)} if texture_size else {}),
        })
        # Smallest requested stage wins the low slot; the stages arrive sorted
        # ascending, so the FIRST stored one is it.
        if not selected:
            gallery.select(path.name, LOW_TIER)
            selected = path.name
    return selected


def _generate(prop_id: str, prompt: str, negative: str,
              image_backend_glob: str, mesh_backend_glob: str,
              face_num: Any = None, texture_size: Any = None,
              mesh_only: bool = False,
              image_only: bool = False,
              tier: str = DEFAULT_TIER,
              lod_faces: Any = None,
              variant: Any = None,
              view: str = "front",
              front_reference: bool = False,
              views: Optional[List[str]] = None) -> Dict[str, Any]:
    """Blocking chain on a worker thread — source render then img2mesh. ONE
    tracked header task wraps the whole chain (the actual GPU jobs show in the
    queue panel via their channel entries).

    ``view``/``front_reference`` steer the source render (which view, and
    whether the front is slotted as its reference); ``views`` names the extra
    views the MESH step should send along beside the front image."""
    from app.core.task_queue import get_task_queue
    name = read_sidecar(prop_id).get("name") or prop_id
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation", f"Prop: {name}", start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        # mesh_only re-meshes the EXISTING source image (new backend / face
        # count / texture size) without burning an image render; image_only
        # renders a NEW source image and stops — re-meshing is its own,
        # separately triggered step ("3D from this image").
        if not mesh_only and not _render_source(
                prop_id, image_backend_glob, prompt, negative, variant,
                view=view, front_reference=front_reference):
            error = "source render failed"
            return {"ok": False, "error": error}
        if image_only:
            return {"ok": True}
        # The variant's OWN image — a re-mesh reproduces the picture the
        # variant it refines was made from, never another variant's.
        src = source_path(prop_id, variant)
        if not src:
            error = ("this variant has no source image to mesh from"
                     if mesh_only else "source image missing")
            return {"ok": False, "error": error}

        from app.imagegen.service import get_image_service
        if not mesh_backend_glob.strip():
            # Same admin default the character 3D tab uses — without it the
            # pool picks the cheapest mesh backend, which is arbitrary when
            # several share cost 0. list_mesh_backends blanks the default when
            # it is not a rig-'none' MESH backend: the setting also holds
            # image-backend names, and one of those as a mesh glob matches
            # nothing (or the wrong thing).
            from app.core.model3d import list_mesh_backends
            mesh_backend_glob = str(
                list_mesh_backends("none").get("default") or "").strip()
        g = model_gallery(prop_id, variant)
        if not g:
            error = "bad prop id"
            return {"ok": False, "error": error}
        # WHAT THIS VERSION COSTS (v2 E5): the variant states its budgets, the
        # caller's explicit numbers win. That one order is why the automatic
        # improvement inherits them too — it comes through here without any
        # face argument of its own, and used to run on whatever the backend
        # default happened to be.
        targets = variant_face_targets(prop_id, variant)
        if not face_num:
            face_num = targets[TARGET_FACES_HIGH_KEY]
        if lod_faces is None and targets[TARGET_FACES_LOW_KEY]:
            # `None` and an EMPTY LIST are different statements (ruling V9):
            # None = "nobody said", so the variant's budget applies; `[]` = the
            # dialog's stage toggle is OFF, and switching it off has to switch
            # something off. Sent to every alias; the ones whose schema
            # declares no LOD param log it and drop it (openai_mesh), and the
            # CPU distance mesh then reads the same target for its own ratio.
            lod_faces = [targets[TARGET_FACES_LOW_KEY]]
        # The dial of the file this run replaces is the new file's default
        # (v2 E1; same rule as the upload) — read BEFORE the new file lands.
        previous = g.find(DEFAULT_TIER, fallback=False)
        inherited = file_areas(previous)[ROTATION_KEY] if previous else None
        # Extra views for a multi-view alias — the files this variant holds
        # among the requested ones; a requested view without a file is
        # skipped, never fatal.
        view_paths: Dict[str, str] = {}
        for v in (views or []):
            if v not in EXTRA_VIEWS:
                continue
            vp = source_path(prop_id, variant, view=v)
            if vp:
                view_paths[v] = str(vp)
            else:
                logger.info("Prop %s: requested %s view has no image, skipped",
                            prop_id, v)
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(g.new_path()),
            backend_glob=mesh_backend_glob,
            mesh_name=prop_id,
            rig="none",
            face_num=face_num,
            texture_size=texture_size,
            view_images=view_paths or None,
            lod_faces=lod_faces)
        if not res.get("ok"):
            error = str(res.get("error") or "mesh generation failed")
            logger.error("Prop %s mesh failed: %s", prop_id, error)
            return {"ok": False, "error": error}

        # A NEW file in the gallery, active for its tier — the previous meshes
        # stay (pick one of them in the admin panel). Everything about THIS
        # run goes on the file's own sidecar, not on the prop record.
        path = Path(res["path"])
        write_model_sidecar(path, {
            "created_at": utc_now_iso(),
            "source": "generated",
            "format": res.get("format", path.suffix.lstrip(".").lower() or "glb"),
            "rig": res.get("rig", "none"),
            "tier": tier or DEFAULT_TIER,
            "backend": res.get("backend", ""),
            **({"face_num": int(face_num)} if face_num else {}),
            **({"texture_size": int(texture_size)} if texture_size else {}),
            # Over the alias' ceiling the job runs CLAMPED, and the file says
            # so — the gallery row shows it (v2 E5).
            **({FACE_TARGET_NOTE_KEY: note}
               if (note := _face_target_note(res.get("backend", ""), face_num))
               else {}),
            **({ROTATION_KEY: inherited}
               if inherited and any(inherited.values()) else {}),
            **({"view_images": {v: Path(p).name
                                for v, p in view_paths.items()}}
               if view_paths else {}),
        })
        g.select(path.name, tier)
        # LOD stages of the SAME job (§ 3.2): each becomes its own gallery
        # file, the smallest fills the `low` slot — one generation leaves a
        # complete full+low pair.
        low = _store_lod_stages(g, res.get("stages") or [], path.name,
                                res.get("backend", ""), texture_size)
        if low:
            logger.info("Prop %s: LOD stage %s selected as low variant",
                        prop_id, low)

        meta = read_sidecar(prop_id)
        meta["source"] = "generated"
        # Only the PRIMARY variant informs the object's proportions — a second
        # chair mesh must not redistribute the dims the admin sees.
        primary = _stem_of(prop_id, variant) == _stem_of(prop_id)
        if primary:
            bbox = _extract_bbox(prop_id)
            if bbox:
                meta["bbox"] = bbox
                _redistribute_dims(meta, file_areas(path)[ROTATION_KEY])
        _write_sidecar(prop_id, meta)
        # The picture-area split of the mesh that just landed (when the prop
        # asked for key colours) — for EVERY variant (v2 E1: each is its own
        # mesh), same law as the slots below: this chain does not go through
        # `_store_bbox`, so the landing hook has to stand here as well. Its
        # own read-modify-write, never raises; a worker thread may wait
        # longer for a Blender slot.
        _areas_after_landing(prop_id, variant, wait_s=30.0)
        if primary:
            # …and the object's texture slots, off the mesh that just landed.
            # AFTER the write above, never before: `_autofill_slots` does its
            # own read-modify-write and the `meta` in hand here predates it.
            # This chain does not go through `_store_bbox` (it selects and
            # measures inline), so the call has to stand here as well or a
            # GENERATED prop would never get its slots.
            _autofill_slots(prop_id)
        # The walking surface of the mesh that just landed — AFTER the area
        # split above, which rewrites the file. Same law as the slots: this
        # chain does not go through `_store_bbox`, so the hook has to stand
        # here as well, and it stands OUTSIDE the primary gate because every
        # variant carries its own mesh (spec-surface-height § 5 Nr. 1).
        bake_surfaces(prop_id, variant)
        logger.info("Prop %s: model generated into variant %s (%s, backend %s)",
                    prop_id, _stem_of(prop_id, variant), path.name,
                    res.get("backend", ""))
        return {"ok": True}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def _shrink(prop_id: str, source_file: str, backend_glob: str,
            face_num: Any = None, texture_size: Any = None,
            variant: Any = None) -> Dict[str, Any]:
    """Blocking mesh→mesh reduction of ONE stored mesh (worker thread, see
    trigger_shrink). Adds a NEW file to the prop's gallery and makes it the
    ``low`` variant; the source file and the prop's dims stay untouched — the
    dims are measured from the FULL mesh and a coarser copy of the same object
    must not move them.

    Without a ``face_num`` the variant's ``target_faces_low`` applies (v2 E5):
    this IS the variant's distance mesh, so it is the same budget the CPU
    reduction aims at — only reached by a backend instead of by Decimate."""
    from app.core.task_queue import get_task_queue
    from app.imagegen.service import get_image_service
    g = model_gallery(prop_id, variant)
    src = g.file(source_file) if g else None
    if not g or not src:
        return {"ok": False, "error": "source model missing"}
    if not face_num:
        face_num = variant_face_targets(prop_id, variant)[TARGET_FACES_LOW_KEY]
    name = read_sidecar(prop_id).get("name") or prop_id
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation", f"Low variant: {name}", start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        res = get_image_service().generate_mesh_variant(
            source_model_path=str(src),
            output_path=str(g.new_path()),
            backend_glob=backend_glob,
            mesh_name=prop_id,
            face_num=face_num,
            texture_size=texture_size)
        if not res.get("ok"):
            error = str(res.get("error") or "shrink failed")
            logger.error("Prop %s shrink failed: %s", prop_id, error)
            return {"ok": False, "error": error}
        path = Path(res["path"])
        src_fix = file_areas(src)[ROTATION_KEY]
        write_model_sidecar(path, {
            "created_at": utc_now_iso(),
            "source": "shrink",
            "format": res.get("format", "glb"),
            "rig": "none",
            "tier": LOW_TIER,
            "backend": res.get("backend", ""),
            "source_file": source_file,
            **({"face_num": int(face_num)} if face_num else {}),
            **({"texture_size": int(texture_size)} if texture_size else {}),
            **({FACE_TARGET_NOTE_KEY: note}
               if (note := _face_target_note(res.get("backend", ""), face_num))
               else {}),
            # A backend re-mesh keeps the axes of its source, not its nodes
            # or materials — the fix travels, the areas do not (v2 E1).
            **({ROTATION_KEY: src_fix} if any(src_fix.values()) else {}),
        })
        g.select(path.name, LOW_TIER)
        logger.info("Prop %s: low variant %s (backend %s, from %s)",
                    prop_id, path.name, res.get("backend", ""), source_file)
        return {"ok": True, "path": str(path)}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def trigger_shrink(prop_id: str, *, source_file: str, backend_glob: str = "",
                   face_num: Any = None, texture_size: Any = None,
                   variant: Any = None) -> bool:
    """Start a low-variant reduction of a STORED mesh in the background.
    False when the prop/file is unknown or this very file is already being
    reduced (double-click guard). The result always lands in tier ``low``.

    Raises ``MeshNotShrinkable`` when the source mesh brings no UVs/texture —
    the gateway job would fail permanently on such an input, so it is refused
    here as well (the UI already hides the action; this is the second line)."""
    pid = safe_prop_id(prop_id)
    if not pid or not read_sidecar(pid):
        return False
    g = model_gallery(pid, variant)
    src = g.file(source_file) if g else None
    if not g or not src:
        return False
    cap = shrink_capability(src)
    if not cap["shrinkable"]:
        raise MeshNotShrinkable(cap["reason"])
    key = _gen_key(pid, variant, f"shrink:{source_file}")
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _run() -> None:
        try:
            _shrink(pid, source_file, backend_glob, face_num=face_num,
                    texture_size=texture_size, variant=variant)
        except Exception as e:
            logger.error("Prop shrink for %s failed: %s", pid, e)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return True


def target_variant(prop_id: str) -> int:
    """Which variant a NEWLY generated mesh belongs in — the rule behind
    "generating APPENDS a variant instead of replacing one" (E2.3).

    In order:

    1. the first ACTIVE variant that carries no mesh yet — a freshly created
       prop has exactly one such slot, so its first generation still fills
       variant 0 and nothing about a one-mesh prop changed;
    2. a freshly appended slot, while the active cap allows one;
    3. at the cap, the LAST active variant — the new mesh joins its gallery as
       another stored file and becomes its active one. Nothing is lost (a
       gallery keeps its history), and the cap is not quietly exceeded.

    A re-mesh does NOT go through here: it names its variant explicitly, so
    "make a better version of THIS one" replaces inside that gallery."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return 0
    entries = _variant_list(meta)
    active = _active_indices(entries)
    for i in active:
        g = model_gallery(pid, i)
        if not (g and g.tiers()):
            return i
    if len(active) < variant_max():
        fresh = add_variant(pid)
        if fresh >= 0:
            return fresh
    return active[-1]


def trigger_generation(prop_id: str, *, prompt: str = "", negative: str = "",
                       image_backend_glob: str = "",
                       mesh_backend_glob: str = "",
                       face_num: Any = None,
                       texture_size: Any = None,
                       mesh_only: bool = False,
                       image_only: bool = False,
                       tier: str = DEFAULT_TIER,
                       lod_faces: Any = None,
                       variant: Any = None,
                       view: str = "front",
                       front_reference: bool = False,
                       views: Optional[List[str]] = None) -> bool:
    """Start the source→mesh chain in the background. Different mesh backends
    for the same prop run concurrently (each queues on its own GPU channel);
    False only while THIS prop+variant+backend combination is already
    generating (double-click guard), or when the prop does not exist.

    ``variant`` names the model variant the run belongs to — BOTH its source
    image and its mesh, they are one version of the object. ``None`` lets
    :func:`target_variant` decide, which APPENDS a variant while the cap
    allows — that is the plain "generate" button. A re-mesh passes the index
    it is refining, and so does ``image_only``, which re-renders exactly that
    variant's picture and leaves every other one alone; with no index it is
    the PRIMARY variant's image, like every other unqualified read.

    ``lod_faces`` additionally asks the mesh alias for reduced stages of the
    same bake; the smallest one lands as that variant's ``low`` tier. It is
    THREE-VALUED (ruling V9): ``None`` lets the variant's ``target_faces_low``
    decide, an EMPTY LIST switches the stage off explicitly, a number asks for
    that stage.

    ``view``/``front_reference`` belong to an ``image_only`` run (which view is
    rendered, and whether the front is slotted as reference); ``views`` names
    the extra views a MESH run should send along."""
    pid = safe_prop_id(prop_id)
    if not pid or not read_sidecar(pid):
        return False
    if variant is None and not image_only:
        variant = target_variant(pid)
    key = _gen_key(pid, variant, mesh_backend_glob, view if image_only else "")
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _run() -> None:
        try:
            _generate(pid, prompt, negative, image_backend_glob,
                      mesh_backend_glob, face_num=face_num,
                      texture_size=texture_size, mesh_only=mesh_only,
                      image_only=image_only, tier=tier, lod_faces=lod_faces,
                      variant=variant, view=view,
                      front_reference=front_reference, views=views)
        except Exception as e:
            logger.error("Prop generation for %s failed: %s", pid, e)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return True
