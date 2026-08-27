"""Prop library — single 3D objects (chair, table, plant, …) for room furnishing.

Plan: ``development_instructions/plan-room-props.md``. Unlike the room-diorama
models (``location_model3d.py``), a prop is ONE isolated object generated from a
dedicated product-shot render (use case ``prop``) → img2mesh (rig "none"). Each
prop carries OBJECT-LOCAL animation markers — a figure with a matching activity
snaps to the marker in the object's own space, so markers live on the OBJECT
instead of being set per room.

Storage: ``worlds/<world>/props/<prop_id>/``:

    model_<ts>.glb   — the meshes (unrigged GLB, embedded texture)
    model_<ts>.json  — one sidecar per mesh: {created_at, source, format,
                       tier, backend, face_num, texture_size}
    selection.json   — {"model": {"<tier>": "<filename>"}}
    source.png       — the product-shot render THIS variant's meshes were made
                       from (one per variant, see the source-image law below)
    sidecar.json     — the prop MASTER record: {name, category, tags[],
                       rotation{x,y,z}, bbox[3], sway_factor, slots[],
                       slots_auto, created_at, source, prompt,
                       model_variants[…]}

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
``markers``          the OBJECT-LOCAL animation markers of THIS mesh
===================  ========================================================

so one entry reads::

    "model_variants": [{"stem": "model", "active": true,
                        "width_m": 0.6, "depth_m": 0.6, "height_m": 4.0,
                        "dims_estimated": false,
                        "description": "a tall pine tree",
                        "ground_offset_m": -0.1,
                        "markers": [{"animation": "sit", "at": [.5, .4, .5]}]},
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
identical to ``layout.markers`` (animation + facing), only the frame is the
object instead of the room rectangle.

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
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.game_time import (current_season_tokens, sanitize_season_tags,
                                season_tags_active)
from app.core.log import get_logger
from app.core.model_store import (DEFAULT_TIER, ModelGallery, normalize_tier,
                                  read_sidecar as read_model_sidecar,
                                  write_sidecar as write_model_sidecar)
from app.core.model_validate import (MeshNotShrinkable, glb_bounds,
                                     glb_material_names_at, shrink_capability)
from app.core.timeutils import utc_now_iso

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

#: How much of a placed prop's DEPTH survives its cut (§ B2 addendum
#: 2026-08-23) — a fraction, 1.0 = the whole prop. The floor never reaches 0:
#: an infinitely thin slab is a prop nobody can see and an authoring slip that
#: looks like a lost placement, so the dial stops at 5 %.
CUT_KEEP_MIN = 0.05

# Marker fractions may leave the raw bounding box by half a box per axis —
# the HEIGHT axis reaches a full box below (deep seats in tall machines);
# see ``sanitize_markers``.
# Flag for the one-time "marker names the surface" lift (see
# migrate_marker_surface_once).
_MARKER_SURFACE_FLAG = "world.migration.prop_marker_surface"
MARKER_AT_MIN = -0.5
MARKER_AT_MAX = 1.5
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
    :func:`variant_description`, :func:`variant_ground_offset` and
    :func:`variant_markers`, so "which variant is this" cannot drift between
    the four fields the variant owns.
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
    """The OBJECT-LOCAL animation markers of ONE variant (``[]`` when it has
    none). The fractions are of THAT mesh's bounding box, which is why they
    are the variant's and never the prop's (2026-08-25)."""
    return sanitize_markers(_variant_entry(meta, variant).get(MARKERS_KEY))


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
    """Object-local animation markers (A4). Same vocabulary as
    ``layout.markers`` — ``animation`` = a clip kind from the OPEN clip
    vocabulary, ``facing`` = degrees (0 south / 90 east / 180 north / 270 west,
    absent = client default) — but ``at`` is an OBJECT-LOCAL ``[u, v, w]``
    (three fractions of the model bounding box) instead of a room ``[x, y]``.

    The fractions may exceed 0..1 by half a box in each direction
    (``[-0.5, 1.5]``): a seat or lying surface often sits ON the hull edge or
    slightly outside it, and the old hard 0..1 clamp made those markers
    impossible to place (the Seated Row Machine finding). ``compose_prop_marker``
    multiplies the fractions linearly, so out-of-range values compose
    correctly without any change there.

    Invalid entries are dropped individually; capped at 50."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        anim = str(m.get("animation") or "").strip()
        at = m.get("at")
        if not anim or not isinstance(at, (list, tuple)) or len(at) != 3:
            continue
        try:
            at3 = [round(min(max(float(at[i]),
                                 MARKER_AT_Y_MIN if i == 1 else MARKER_AT_MIN),
                             MARKER_AT_MAX), 4)
                   for i in range(3)]
        except (TypeError, ValueError):
            continue
        entry: Dict[str, Any] = {"animation": anim, "at": at3}
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
    spellings, so ``slot_glass`` and ``glass`` never disagree."""
    return "material" if name in MATERIAL_SLOT_NAMES else "image"


def detect_slots(material_names: Any) -> List[Dict[str, str]]:
    """THE detection rule (Entscheid 4): which of a model's MATERIAL NAMES are
    texture slots. This function is the only place it is stated.

    For every name, lower-cased and stripped:

    * ``slot_<name>`` → a slot called ``<name>``; its kind is ``material`` for
      the names in :data:`MATERIAL_SLOT_NAMES`, ``image`` otherwise. The prefix
      is the OPEN half of the convention — anything can be a slot if the
      modeller says so.
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


# ── CRUD ────────────────────────────────────────────────────────────────

def create_prop(*, name: str, category: str = "", width_m: Any = None,
                depth_m: Any = None, height_m: Any = None,
                tags: Any = None, description: str = "", prompt: str = "",
                source: str = "manual") -> Dict[str, Any]:
    """Create a new prop record (sidecar only — the model/source files are
    added by upload or the generation chain). Returns ``{id, **sidecar}``.

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
    meta = {
        "name": name,
        "category": (category or "").strip(),
        VARIANTS_KEY: [variant],
        "rotation": {"x": 0, "y": 0, "z": 0},
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
    _write_sidecar(prop_id, meta)
    logger.info("Prop %s created (%s)", prop_id, name)
    return {"id": prop_id, **meta}


#: What the PROP record itself still carries — the fields the general section
#: of the admin form edits. Everything about how the object LOOKS moved onto
#: the variants (2026-08-25), and :data:`MOVED_TO_VARIANT` names those so a
#: stale client is REFUSED instead of silently writing a key nobody reads.
PROP_PATCH_KEYS = ("name", "category", "tags", "sway_factor", "slots")
#: The five fields that are variant-only now. A prop-level patch naming one of
#: them is a 400 with the route that owns it — never a no-op: an editor that
#: still sends ``height_m`` here would report "Saved" over a value that never
#: reached anything.
MOVED_TO_VARIANT = {
    "width_m": "POST /world/props/{id}/variants/{i}/dims",
    "depth_m": "POST /world/props/{id}/variants/{i}/dims",
    "height_m": "POST /world/props/{id}/variants/{i}/dims",
    "dims_estimated": "POST /world/props/{id}/variants/{i}/dims",
    "description": "POST /world/props/{id}/variants/{i}/description",
    "ground_offset_m": "POST /world/props/{id}/variants/{i}/ground-offset",
    "markers": "POST /world/props/{id}/variants/{i}/markers",
}


def _check_prop_patch(patch: Dict[str, Any]) -> None:
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


def update_prop(prop_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update the PROP's own fields (name / category / tags / sway_factor /
    slots). None when the prop does not exist.

    Raises ``ValueError`` when the patch names one of the five fields that
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
    _check_prop_patch(patch)
    _apply_prop_fields(meta, patch)
    _write_sidecar(pid, meta)
    return {"id": pid, **meta}


def set_rotation(prop_id: str, rotation: Any) -> Optional[Dict[str, Any]]:
    """Persist the orientation fix. None when the prop does not exist.

    The STORED dims stay untouched: re-orienting a prop does not silently
    rewrite numbers the admin can see — the editor recomputes its proportional
    suggestions live instead."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    meta["rotation"] = _sanitize_rotation(rotation, meta.get("rotation"))
    _write_sidecar(pid, meta)
    return {"id": pid, **meta}


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
                     tiers: List[str], *, markers: bool) -> Dict[str, Any]:
    """ONE entry of the published variant list: ``{variant, tiers, dims,
    ground_offset_m?, markers?}``.

    Written once, because it is the ONE shape a consumer resolves a placement's
    variant POSITION in — the world-prop payload, the ground boxes, the room
    recipe and the terrain scatter all index into it, and the four fields a
    variant owns have to travel together or a placement gets one version's size
    with another one's sink.

    ``ground_offset_m`` follows the storage law (absent = on the ground) so the
    payload does not carry a 0.0 for every prop in every world. ``markers`` are
    ADMIN detail and ride only where the full record does: the lean client
    library gets ``marker_count`` and nothing else, exactly as before.
    """
    entry: Dict[str, Any] = {"variant": index, "tiers": tiers,
                             "dims": variant_dims(meta, index)}
    off = variant_ground_offset(meta, index)
    if off:
        entry[GROUND_OFFSET_KEY] = off
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


def list_variants(prop_id: str) -> List[Dict[str, Any]]:
    """The prop's variants for the admin strip: ``[{index, stem, active,
    seasons, in_season, tiers, has_model, model_file, model_url, signature,
    has_source, source_url, image, dims, dims_estimated, description,
    ground_offset_m, markers}]`` — every variant, active or not, in order.

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
    picture it is displaying, not of some other variant's."""
    meta = read_sidecar(prop_id)
    entries = _variant_list(meta)
    primary = _effective_indices(entries)[0]
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
            "dims": {k: entry[k] for k in DIM_KEYS},
            "dims_estimated": bool(entry.get(DIMS_ESTIMATED_KEY)),
            "description": entry.get(DESCRIPTION_KEY, ""),
            "ground_offset_m": entry.get(GROUND_OFFSET_KEY, GROUND_OFFSET_DEFAULT),
            "markers": entry.get(MARKERS_KEY, []),
        })
    return out


#: What a NEW variant copies from its source (2026-08-25) — everything the
#: variant owns except its own files. The stem, the mesh gallery, the source
#: image and its provenance are what makes the new slot a new VERSION; the
#: fields below are what makes it a version OF THIS OBJECT.
_COPIED_ON_ADD = (*DIM_KEYS, DIMS_ESTIMATED_KEY, DESCRIPTION_KEY,
                  GROUND_OFFSET_KEY, MARKERS_KEY)


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


#: The five fields a variant owns, by the name a batch body calls them — the
#: dims travel as ONE `dims` object because the trio is one statement (a prop
#: is scaled uniformly, so the three numbers say how big AND what shape).
VARIANT_PATCH_APPLIERS = {
    "dims": _apply_variant_dims,
    "description": _apply_variant_description,
    "ground_offset_m": _apply_variant_ground_offset,
    "markers": _apply_variant_markers,
    "seasons": _apply_variant_seasons,
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
    _check_prop_patch(prop_patch)

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
        g.delete()
        # The stem's selection entry survives its files (``delete`` only
        # re-points what is left), and a freed stem may be handed out again —
        # so it goes with the variant.
        g.forget()
    img = _source_file(pid, i)
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


def list_models(prop_id: str, variant: Any = None) -> List[Dict[str, Any]]:
    """All stored meshes of the prop for the admin gallery, newest first:
    ``[{filename, tier, selected_for, face_num, texture_size, format,
    created_at, backend, source, source_file, tris, lod_ratio, shrinkable,
    shrink_reason, active}]``. ``tier`` is what the file was made for,
    ``selected_for`` the tiers it currently serves, ``source_file`` the stored
    mesh a low variant was reduced FROM, ``tris``/``lod_ratio`` what the CPU
    reduction left of it (0 = not a reduced mesh), ``active`` the one a client
    without a tier request gets.

    ``shrinkable`` / ``shrink_reason`` come from the cheap capability probe
    (header + JSON chunk): a vertex-coloured mesh without UVs can never be
    reduced, and the admin must see that on the row instead of starting a job
    that fails permanently."""
    g = model_gallery(prop_id, variant)
    if not g:
        return []
    active = g.find()
    out: List[Dict[str, Any]] = []
    for p in g.files():
        meta = read_model_sidecar(p)
        cap = shrink_capability(p)
        out.append({
            "filename": p.name,
            "tier": g.tier_of(p),
            "selected_for": g.selected_for(p.name),
            "face_num": int(meta.get("face_num") or 0),
            "texture_size": int(meta.get("texture_size") or 0),
            "format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "created_at": meta.get("created_at", ""),
            "backend": meta.get("backend", ""),
            "source": meta.get("source", ""),
            "source_file": meta.get("source_file", ""),
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
    if not g or not g.delete(filename):
        return False
    _store_bbox(prop_id, variant)
    return True


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


def _source_file(prop_id: str, variant: Any = None, *,
                 create: bool = False) -> Optional[Path]:
    """Where ONE variant's source image LIVES, whether or not it exists yet.
    ``None`` for an unknown prop or an index this prop has no variant for."""
    d = _prop_dir(prop_id, create=create)
    if not d:
        return None
    name = source_name(_stem_of(prop_id, variant))
    return (d / name) if name else None


def source_path(prop_id: str, variant: Any = None) -> Optional[Path]:
    """The EXISTING source image of one variant — ``None`` (or a negative
    index) means the PRIMARY variant, i.e. the same file every unqualified
    read has always served. ``None`` when this variant has no image yet."""
    p = _source_file(prop_id, variant)
    return p if p and p.exists() else None


def _image_meta(meta: Dict[str, Any], stem: str) -> Dict[str, str]:
    """What is recorded about ONE variant's source image: backend, prompt,
    negative, generated_at (empty strings when nothing is recorded)."""
    keys = IMAGE_META_KEYS
    if stem == MODEL_STEM:
        return {k: str(meta.get(_IMAGE_META_MASTER[k]) or "") for k in keys}
    for entry in _variant_list(meta):
        if entry["stem"] == stem:
            img = entry.get("image") or {}
            return {k: str(img.get(k) or "") for k in keys}
    return {k: "" for k in keys}


def _set_image_meta(meta: Dict[str, Any], stem: str, *, backend: str = "",
                    prompt: str = "", negative: str = "") -> None:
    """Record what a freshly written source image was made with, IN PLACE.
    The caller writes the sidecar."""
    rec = {"backend": backend, "prompt": prompt, "negative": negative,
           "generated_at": utc_now_iso()}
    if stem == MODEL_STEM:
        for k, m in _IMAGE_META_MASTER.items():
            meta[m] = rec[k]
        return
    entries = _variant_list(meta)
    for entry in entries:
        if entry["stem"] == stem:
            entry["image"] = rec
    meta[VARIANTS_KEY] = entries


def save_source_image(prop_id: str, contents: bytes, variant: Any = None, *,
                      backend: str = "", prompt: str = "",
                      negative: str = "") -> bool:
    """Store image bytes as ONE variant's source image. False when the
    prop/variant is unknown or the bytes are not a readable image.

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
    target = _source_file(prop_id, variant, create=True)
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
    _set_image_meta(meta, _stem_of(prop_id, variant), backend=backend,
                    prompt=prompt, negative=negative)
    _write_sidecar(prop_id, meta)
    logger.info("Prop %s: source image stored for variant %s (%s, %d bytes)",
                safe_prop_id(prop_id), variant, target.name, len(contents))
    return True


def save_uploaded_glb(prop_id: str, contents: bytes,
                      tier: str = DEFAULT_TIER, variant: Any = None) -> bool:
    """Store an uploaded GLB as a NEW mesh of one variant and make it the
    active one of its tier. The prop record must already exist (created
    first); validation is the caller's job."""
    g = model_gallery(prop_id, variant) if read_sidecar(prop_id) else None
    if not g:
        return False
    target = g.new_path()
    target.write_bytes(contents)
    write_model_sidecar(target, {
        "created_at": utc_now_iso(),
        "source": "upload",
        "format": "glb",
        "rig": "none",
        "tier": tier or DEFAULT_TIER,
    })
    g.select(target.name, tier)
    logger.info("Prop %s: model uploaded (%d bytes) -> %s",
                safe_prop_id(prop_id), len(contents), target.name)
    _store_bbox(prop_id, variant)
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
    target = gallery.new_path()
    target.write_bytes(res["blob"])
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
    })
    gallery.select(target.name, LOW_TIER)
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

    ``ratio`` 0 takes the configured target for props. One build per prop at a
    time, and the reduced mesh must pass the same static validation as a
    freshly delivered model. Returns ``{ok, tier, ratio, tris, tris_before,
    size, size_before, error}``.
    """
    from app.blender import refine
    ratio = float(ratio or refine.lod_ratio("prop"))
    out: Dict[str, Any] = {"ok": False, "tier": LOW_TIER, "ratio": ratio,
                           "tris": None, "tris_before": None, "size": 0,
                           "size_before": 0, "error": ""}
    pid = safe_prop_id(prop_id)
    g = model_gallery(pid, variant)
    src = g.find(DEFAULT_TIER, fallback=False) if g else None
    if not src or src.suffix.lower() != ".glb":
        out["error"] = "no_model"
        return out
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
        ratio = refine.lod_ratio("prop")

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


def _store_bbox(prop_id: str, variant: Any = None) -> None:
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
    therefore only redone when the primary variant was the one that changed."""
    _auto_bake_vc(prop_id, variant)
    _auto_retexture(prop_id, variant)
    request_low_tier(prop_id, variant)
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
    _redistribute_dims(meta)
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

def _redistribute_dims(meta: Dict[str, Any]) -> None:
    """Re-derive the PRIMARY variant's dims from the model's proportions,
    keeping the largest edge — ONLY while they are a still-estimated
    placeholder cube. A size the admin typed (``dims_estimated`` False) is
    never touched.

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
                                      meta.get("rotation")))
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
    # renders at, how deep it stands and — on a full record — its markers. A
    # placement reads all three off the entry it draws
    # (`room_recipe._placement_dims` and friends) instead of off the record,
    # which answers for the PRIMARY variant.
    variant_tiers = [_published_entry(meta, i, vt, markers=full)
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
        # The client applies the fix before measuring/scaling the mesh —
        # same role as the room-model meta rotation.
        "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
        "tags": meta.get("tags") or [],
        # The fillable surfaces of this prop's mesh, `[{name, kind}, …]` —
        # ALWAYS present, so no consumer has to know the difference between
        # "none" and "not detected yet". On the lean record too: it is what a
        # scene's `slots` are matched against.
        "slots": meta.get(SLOTS_KEY) or [],
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
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
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
            "model_signature": hashlib.md5(
                "|".join(f"{i}:{g.signature() if g else ''}"
                         for i, g in zip(active_idx, galleries)
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
    from app.core.scene_recipe import FIGURE_HEIGHT_M, FIGURE_ROOT_DROP
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(_MARKER_SURFACE_FLAG):
        return {}
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
            drop = FIGURE_ROOT_DROP.get(
                str(m.get("animation") or "").strip().lower(), 0.0)
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

def _gen_key(prop_id: str, variant: Any, backend_glob: str) -> str:
    """Double-start key: prop, STORE VARIANT INDEX and backend. Two variants of
    the same prop may generate side by side — they are two objects to the GPU —
    while the same variant on the same backend stays one job.

    ``None`` is not a key of its own: an unqualified run works on the PRIMARY
    variant, so it resolves to that variant's index here. Otherwise the same
    picture could be rendered twice at once — once through the plain route and
    once through the primary variant's own — and the pair would race for one
    file. Resolving also makes the middle field always an integer, which is
    what :func:`pending_variants` reports back to the admin."""
    idx = primary_variant(prop_id) if variant is None else int(variant)
    return f"{prop_id}|{idx}|{(backend_glob or '').strip().lower()}"


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

def compose_prompt(subject: str, backend) -> Dict[str, str]:
    """Final source-render prompt + negative for a prop on a backend — the
    ``prop`` use-case style (per image family) with the object subject woven
    into its ``{subject}`` slot. The dialog shows exactly this and may edit it
    (final-prompt rule); ``style`` is returned RAW (slot included) so the UI
    can recompose it per object with the same weaving rule.

    The 3D-ASSET FRAMING ("A high-quality 3D model of …, designed for 3D asset
    generation, 8k resolution") is part of that style and of nothing else —
    see ``_DEFAULT_IMAGE_USE_CASES["prop"]`` in ``app.core.config``. Nothing
    here adds a phrase of its own, so the framing cannot land in a prompt
    twice."""
    from app.core import config as _cfg
    from app.core.prompt_compose import compose as _compose
    ucp = _cfg.resolve_use_case_style(
        "prop",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    subject = (subject or "").strip() or "a single object"
    # The composition itself (slot/append, negation guard, negative merge)
    # belongs to prompt_compose; only the return SHAPE is this module's, the
    # dialog recomposes per object from `style` + its own subject field.
    composed = _compose(use_case="prop", subject=subject, backend=backend)
    return {
        "style": (ucp.get("prompt_style") or "").strip(),
        "prompt": composed.prompt,
        "negative": composed.negative,
    }


def _render_source(prop_id: str, backend_glob: str,
                   prompt: str, negative: str, variant: Any = None) -> bool:
    """txt2img render of the product shot → THIS VARIANT's source image. Runs
    the GPU job on the backend queue channel (like every render). Records the
    image backend + final prompt with the variant. Returns True on success.

    ``variant`` None is the primary one, whose image keeps the historic
    ``source.png``; every further variant renders into its own
    ``source-v<n>.png``, so a second version of the object cannot overwrite
    the picture the first one was meshed from."""
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

    if not prompt.strip():
        # The stored description is the generation subject; the name is only
        # the display fallback when no description was written. It is THIS
        # VARIANT's description (2026-08-24) — a version of the object is
        # rendered from its own sentence where it has one, and only a variant
        # without one falls back to the prop's.
        meta0 = read_sidecar(prop_id)
        composed = compose_prompt(
            variant_description(meta0, variant) or meta0.get("name", ""),
            backend)
        prompt = composed["prompt"]
        if not negative.strip():
            negative = composed["negative"]

    params: Dict[str, Any] = {
        "width": 1024, "height": 1024,
        "seed": random.randint(1, 2**31 - 1),
    }
    # The prompt arrives already composed (compose_prompt above, or edited in
    # the dialog) — the metablock records the use case, not a fresh compose.
    _log_meta = {"agent_name": f"Prop {prop_id}", "original_prompt": prompt,
                 "auto_enhance": False,
                 "compose": {"use_case": "prop", "settings_applied": True}}
    from app.core.llm_queue import get_llm_queue, Priority
    images = get_llm_queue().submit_gpu_task(
        provider_name=backend.name,
        task_type="prop_source",
        priority=Priority.IMAGE_GEN,
        callable_fn=lambda: backend.generate(prompt, negative, params,
                                             log_meta=_log_meta),
        agent_name="system",
        label=f"Prop source: {prop_id}",
        gpu_type=backend.api_type)
    if not images:
        logger.warning("Prop %s: empty source render", prop_id)
        return False

    # One writer for every source image (upload, cutout, render): it norms the
    # picture and records the provenance the panel shows for THIS variant
    # (backend + when; prompt/negative in the tooltip).
    return save_source_image(prop_id, images[0], variant,
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
              variant: Any = None) -> Dict[str, Any]:
    """Blocking chain on a worker thread — source render then img2mesh. ONE
    tracked header task wraps the whole chain (the actual GPU jobs show in the
    queue panel via their channel entries)."""
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
        if not mesh_only and not _render_source(prop_id, image_backend_glob,
                                                prompt, negative, variant):
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
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(g.new_path()),
            backend_glob=mesh_backend_glob,
            mesh_name=prop_id,
            rig="none",
            face_num=face_num,
            texture_size=texture_size,
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
                _redistribute_dims(meta)
        _write_sidecar(prop_id, meta)
        if primary:
            # …and the object's texture slots, off the mesh that just landed.
            # AFTER the write above, never before: `_autofill_slots` does its
            # own read-modify-write and the `meta` in hand here predates it.
            # This chain does not go through `_store_bbox` (it selects and
            # measures inline), so the call has to stand here as well or a
            # GENERATED prop would never get its slots.
            _autofill_slots(prop_id)
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
    must not move them."""
    from app.core.task_queue import get_task_queue
    from app.imagegen.service import get_image_service
    g = model_gallery(prop_id, variant)
    src = g.file(source_file) if g else None
    if not g or not src:
        return {"ok": False, "error": "source model missing"}
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
                       variant: Any = None) -> bool:
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
    same bake; the smallest one lands as that variant's ``low`` tier."""
    pid = safe_prop_id(prop_id)
    if not pid or not read_sidecar(pid):
        return False
    if variant is None and not image_only:
        variant = target_variant(pid)
    key = _gen_key(pid, variant, mesh_backend_glob)
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
                      variant=variant)
        except Exception as e:
            logger.error("Prop generation for %s failed: %s", pid, e)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return True
