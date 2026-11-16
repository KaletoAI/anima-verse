"""The garment store — where a character's own-mesh garments live on disk
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R10,
R11, R13; spec ``2026-11-08-base-body-outfits-design.md`` § C.4).

Per owner, under ``characters/<name>/garments/``::

    images/{item}_{fsig}_{step}_{view}.png  + .json   the image steps of the kind
                                                      (clothing: worn/ghost/cutout;
                                                      hair has none);
    images/{item}_{fsig}_{step}_{view}.try{n}.png     the attempts of a step
    images/{item}_{fsig}_{step}_{view}.try{n}.raw.png an attempt as rendered, while the
                                                      attempt file holds it registered
                                                      (``garment_images.raw_path``)
    images/{item}_{fsig}_{step}_{view}.try{n}.support.png the pixels a composite
                                                      attempt may have changed
                                                      (``garment_images.support_path``)
    raw/{item}_{fsig}.glb                             generator output
    prepared/{item}_{fsig}.glb                        decimated
    {item}_{fsig}.glb + .json                         the fit: rigged base with the
                                                      garment grafted on; its record
                                                      holds gates + base_model_sha256
    {item}_{fsig}.strands.json + .npz                 a hair fit's strand record
                                                      (``hair_strands``), in its group
    low/{item}_{fsig}.glb                             the distance tier
    layers/{item}_{fsig}_{lsig}.glb + .json           a LAYERED fit: the body fit pushed
                                                      over the fitted inner pieces
                                                      (``garment_layers``, plan 2026-11-10
                                                      Task 2); ``lsig`` names the inner
                                                      fits it was made over
    layers/low/{item}_{fsig}_{lsig}.glb               its distance tier
    failed/{item}_{fsig}.json                         the last failed chain run of
                                                      this fsig {step, error,
                                                      base_model_sha256, failed_at}
                                                      — automatic triggers skip it

Fits per BODY (plan ``2026-11-10-outfit-body-mesh-mode.md``, Task 2): a fit
is keyed by ``(item, fsig, body id)``. The body of the retexture mode is the
base model — body id = the base signature — and its fits keep the paths
above unchanged. An OUTFIT BODY of the mesh mode (``figure.shape_key``,
``ob`` + 8 hex) has the per-body parts in a folder of its own, same names::

    bodies/<body id>/{item}_{fsig}.glb + .json        the fit on that body
    bodies/<body id>/low/{item}_{fsig}.glb            its distance tier
    bodies/<body id>/layers/{item}_{fsig}_{lsig}.glb  a layered fit on that body
    bodies/<body id>/layers/low/…                     its distance tier
    bodies/<body id>/failed/{item}_{fsig}.json        the last refused fit there

Each body (the base model in ``garments/``, an outfit body in its folder) also keeps the LAST refused fit of an
item and the fit a user's acceptance of it displaced (Ruling A31, ``fit_attempts``)::

    attempts/{item}_{fsig}.glb + .json + .npz         the refused fit, its record, the marked region
    attempts/derived/{item}_{fsig}.glb + .json + .npz a body shape's refused DERIVED shoe, kept beside the fresh
                                                      fit that replaced it (Ruling A40, ``fit_attempts``)
    attempts/prev/{item}_{fsig}.glb + .json           the fit an acceptance displaced (for its undo)
    attempts/prev/low/{item}_{fsig}.glb               its distance tier

The mesh step keeps every REFUSED attempt of its last run beside the accepted mesh (Ruling A48a,
``garment_mesh``; shared, not per body)::

    attempts/mesh/{item}_{fsig}.try{n}.glb            the decimated mesh of refused attempt n
    attempts/mesh/{item}_{fsig}.try{n}.raw.glb        that attempt's generator output

Images, the raw/prepared mesh and the HairDeck job stay shared (per fsig /
hsig): a fit on a body is CPU work from them (``garments.fit_on_body``),
never a hub job. Every fit record names its parents: ``item_id``, ``fsig``,
``body_id``, ``body_sha256`` (the rigged body it was fitted to; on the base
also ``base_model_sha256``), ``base_signature`` and — on an outfit body —
``base_fit_sha256`` (the base fit it was derived from). ``stored_groups``
lists the per-body files in the group of their ``(item, fsig)``.

``fsig`` = md5[:12] over the garment kind's own inputs (hair: description,
behind-the-shoulders flag, pronouns; clothing — an own-mesh outfit piece,
plan ``2026-11-09-base-body-phase5-mesh-items.md``: prompt fragment, slots,
covers, partially covers, pronouns), ``GARMENT_VERSION[kind]``, the base
signature and the content of the base front + back view. The base MODEL is not
in it: a base model regenerated under the same base signature keeps images and
mesh and only re-fits; the fit record decides that — by GEOMETRY (Ruling A107): a fit holds on the base
file it names (``base_model_sha256``) and on every later base file of the same ``base_geometry_id``
(``model_geometry``: a face retexture or matte floor rewrites only pixels and keeps the id).

A hairstyle has its own mode (``garment_hair.hairstyle_mode``; spec
``2026-11-11-hair-from-body-design.md``, plan 2026-11-12-unified-worn-pieces
Task 13): ``body`` — the hair is part of the body mesh, no steps, no files —,
HairDeck — steps ``("hairdeck", "fit")`` (``steps_for``) — and HAAR — steps
``("haar", "fit")``. HairDeck
turns the profile picture into hair cards; its files live in ONE folder per
``hsig``::

    raw/{item}_{hsig}/                                every file of the job +
                                                      record.json {accepted,
                                                      attempt, seed, notes, error}

``hsig`` = md5[:12] over the profile picture's sha256, the ``extra_params`` of
the backend the ``hair_mesh`` occasion is meant to run on and
``HAIRDECK_VERSION`` — no base, no colour: a base change or a colour change
re-fits from the cached job. A character with facial hair adds
``garment_beard.hsig_inputs`` (HairDeck gets a beard-free copy of the picture,
cached in the job folder as ``beard_free.png``). The HairDeck fsig is the
edit-chain payload (``_edit_payload``) plus ``method``, ``hsig``, the colour override (the hairstyle's
``hair_colour``) and the placement (its ``hair_forward_m`` / ``hair_tilt_deg``; ``hair_width_scale`` and ``hair_up_m``
only when set, so a hairstyle without them keeps its fsig). The fit is the same ``{item}_{fsig}.glb`` +
record (its record says ``method: "hairdeck"``; a record without ``method`` is an edit-chain fit — of hair, one of
the removed method, never served); ``prepared/`` is not used by HairDeck.

HAAR (strand-hair spec 2026-11-13 § 6.3) turns the hairstyle's TEXT into strands, one hub job per seed; its
seeds live in ONE folder per ``ssig``::

    raw/{item}_{ssig}/s{seed}/                        one strand job (``<name>_strands.npy``,
                                                      ``<name>_head.obj``, ``info.json``)
    raw/{item}_{ssig}/record.json                     {seeds, results: {seed: {accepted,
                                                      reasons, metrics, tile, length_class,
                                                      base_model_sha256, fit_version,
                                                      strands_sha256}}, chosen, jobs}

``ssig`` = md5[:12] over the hairstyle's text (the prompt), the ``extra_params`` of the backend the
``hair_strands`` occasion is meant to run on and ``HAAR_VERSION`` (``garment_ssig``). A seed folder appears
whole (it is renamed into place). ``results`` are the per-seed fit verdicts on the base model they name; the
SERVED seed (``haar_served_seed``) is the hairstyle's ``haar_seed`` while that seed is stored, else the best
passing one (``haar_best_seed``, spec § 6.3.1). The HAAR fsig is the edit-chain payload plus ``method``,
``ssig``, the served ``seed`` and the colour override — Swing is not in it (HAAR has no chains).

The SOURCE of an image group (``garment_source``, refit before re-render)::

    images/{item}_{fsig}_base_{view}.png  + .json     the base views the group's images were made on
                                                      (front's record: {bsig, base_images,
                                                      origin_fsig[, materialized_from]})

A group refitted from an older base's source carries copies of that source's image finals, prepared
mesh and base views under its own fsig, each record marked ``copied_from`` (``garment_source.materialize``),
and ``limbs/{item}_{fsig}.npz`` — the source fit's vertices, limb weights and limb frames the refit aligns
its sleeves / trouser legs from (``garment_source.write_limb_source``).

Run status is in memory (like ``base_body``): a restart reruns only the step
that was in flight, every finished step is cached on disk under ``fsig``.
"""
import hashlib
import json
import math
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_store")

#: clothing 2: the worn back is drafted from the worn front and fitted onto
#: the base back (``garment_images``) instead of one edit of the base back.
#: footwear 1: the rigid shoe (``garment_footwear``; its fsig carries the footwear versions instead).
GARMENT_VERSION: Dict[str, int] = {"hair": 1, "clothing": 2, "footwear": 1}
#: The steps of footwear made as a shoe: the first five per item (``footwear_source``), ``fit`` per wearer.
FOOTWEAR_STEPS: Tuple[str, ...] = ("source", "empty", "cutout", "mesh", "insole", "fit")
#: The steps of hair made by HairDeck (``steps_for``) — hair has no image chain.
HAIRDECK_STEPS: Tuple[str, ...] = ("hairdeck", "fit")
GARMENT_STEPS: Dict[str, Tuple[str, ...]] = {"hair": HAIRDECK_STEPS,
                                             "clothing": ("worn", "ghost", "cutout", "mesh", "fit"),
                                             "footwear": FOOTWEAR_STEPS}
#: Bumped when the HairDeck job's inputs change meaning (part of ``hsig``).
HAIRDECK_VERSION = 1
#: The record of a HairDeck job folder (``hairdeck_dir``).
HAIRDECK_RECORD = "record.json"
EDIT_CHAIN = "edit_chain"
HAIRDECK = "hairdeck"
#: Hair inside the body mesh (``garment_hair.BODY_MODE``): no steps, no fit, nothing served.
BODY = "body"
#: Hair strands from the hairstyle's text (``garment_hair.HAAR_MODE``): steps ``HAAR_STEPS``.
HAAR = "haar"
#: The steps of hair made by HAAR (``steps_for``): the strand jobs (one per seed), then the CPU fit.
HAAR_STEPS: Tuple[str, ...] = ("haar", "fit")
#: Bumped when the HAAR job's inputs change meaning (part of ``ssig``).
HAAR_VERSION = 1
#: The record of a HAAR job folder (``haar_dir``).
HAAR_RECORD = "record.json"
_SEED_DIR_RE = re.compile(r"s([1-9][0-9]{0,8})")
#: The only method of footwear (no method choice for ``feet``).
SHOE = "shoe"
GARMENT_VIEWS: Tuple[str, ...] = ("front", "back")
#: Every step of any kind that stores images (the rest store meshes); the
#: order of one kind is ``image_steps``.
IMAGE_STEPS: Tuple[str, ...] = ("worn", "ghost", "cutout")
#: part -> sub-folder of ``garments/`` ("" = the folder itself).
PART_DIRS: Dict[str, str] = {"image": "images", "raw": "raw", "prepared": "prepared",
                             "fit": "", "low": "low", "failed": "failed",
                             "layer": "layers", "layer_low": "layers/low", "limbs": "limbs",
                             # Ruling A31 (``fit_attempts``): the last refused fit per (item, body), and the fit an
                             # acceptance of it displaced
                             "attempt": "attempts", "attempt_prev": "attempts/prev",
                             "attempt_prev_low": "attempts/prev/low",
                             # Ruling A40: a body shape's refused derived shoe beside the fresh fit's attempt
                             "attempt_derived": "attempts/derived",
                             # Ruling A48a (``garment_mesh``): the refused attempts of the mesh step's last run
                             "mesh_attempt": "attempts/mesh", "mesh_attempt_raw": "attempts/mesh",
                             # Ruling A48d (``garment_shell``): the shell from the body alone, beside its fit
                             "shell": "shell"}
#: File suffix of a part other than ``glb`` (``limbs``: the refit's limb source, ``garment_source``).
_PART_SUFFIX: Dict[str, str] = {"failed": "json", "limbs": "npz"}
#: The parts keyed by an inner-layer signature ``lsig`` besides the fsig.
LAYER_PARTS: Tuple[str, ...] = ("layer", "layer_low")
#: The parts kept per body (``garment_path(body=…)``); the rest is shared.
BODY_PARTS: Tuple[str, ...] = ("fit", "low", "failed", "layer", "layer_low", "attempt", "attempt_prev",
                                "attempt_prev_low", "attempt_derived", "shell")
#: Folder of the outfit bodies' fits under ``garments/``.
BODIES_DIR = "bodies"
#: An outfit body id (``base_body.OUTFIT_BODY_RE``).
_BODY_RE = re.compile(r"ob[0-9a-f]{8}")
#: A base signature (``base_body.BASE_SIG_RE``): the base body's fits live in ``garments/`` itself.
_BASE_RE = re.compile(r"base[0-9a-f]{8}")

_FSIG_RE = re.compile(r"[0-9a-f]{12}")
_ITEM = r"(?P<item>[A-Za-z0-9][A-Za-z0-9_-]*)"
_FSIG = r"(?P<fsig>[0-9a-f]{12})"
#: images/: {item}_{fsig}_{step}_{view}[.try{n}].{png,json}, the raw {…}.try{n}.raw.png and the
#: composite support {…}.try{n}.support.png
_IMAGE_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"_[a-z]+_[a-z]+(?:\.try[0-9]+(?:\.(?:raw|support)(?=\.png$))?)?\.(?:png|json)")
#: the mesh folders and the fit: {item}_{fsig}.{glb,json}, and a hair fit's strand sidecars
#: {item}_{fsig}.strands.{json,npz} (``hair_strands.sidecar_paths``) — in the group of their fit, so they go with it
#: (Ruling H-R3)
_MESH_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"(?:\.(?:glb|json|npz)|\.strands\.(?:json|npz))")
#: attempts/mesh/: {item}_{fsig}.try{n}.glb and its raw {…}.try{n}.raw.glb (Ruling A48a)
_MESH_ATTEMPT_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"\.try[0-9]+(?:\.raw)?\.glb")
#: The parts of a refused mesh attempt -> the tail of their file name after ``.try{n}``.
MESH_ATTEMPT_PARTS: Dict[str, str] = {"mesh_attempt": ".glb", "mesh_attempt_raw": ".raw.glb"}
#: layers/ and layers/low/: {item}_{fsig}_{lsig}.{glb,json}
_LAYER_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"_[0-9a-f]{12}\.(?:glb|json)")


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


# --- Paths ------------------------------------------------------------------

def _root(character_name: str) -> Path:
    """``characters/<name>/garments`` without creating anything."""
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "garments"


def garments_dir(character_name: str) -> Path:
    """``characters/<name>/garments`` — created only when the character's own
    directory exists (a read path must never mint a ghost character)."""
    path = _root(character_name)
    if path.parent.is_dir():
        path.mkdir(exist_ok=True)
    return path


def is_body_id(body: Optional[str]) -> bool:
    """Whether ``body`` names an OUTFIT body (its fits live in ``bodies/``)."""
    return isinstance(body, str) and _BODY_RE.fullmatch(body) is not None


def body_root(character_name: str, body: str = "") -> Path:
    """The folder of a body's fits: ``garments/`` for the base body (``body``
    "" or a base signature), ``garments/bodies/<body id>`` for an outfit
    body. ValueError for anything else. Creates nothing."""
    root = _root(character_name)
    if not body or (isinstance(body, str) and _BASE_RE.fullmatch(body)):
        return root
    if not is_body_id(body):
        raise ValueError(f"invalid body id {str(body)[:40]!r}")
    return root / BODIES_DIR / body


def body_of(path: Path) -> str:
    """The outfit body id a stored garment file belongs to, "" for a file of
    the base body (or any other)."""
    for parent in Path(path).parents:
        if parent.parent.name == BODIES_DIR and is_body_id(parent.name):
            return parent.name
    return ""


def garment_path(character_name: str, item_id: str, fsig: str, part: str, *,
                 step: str = "", view: str = "", attempt: int = 0, lsig: str = "", body: str = "") -> Path:
    """The file of one garment part (see the module docstring for the layout).

    ``part`` is ``image`` (needs an image ``step`` and a ``view``; ``attempt``
    > 0 names that attempt's file), ``raw``, ``prepared``, ``mesh_attempt`` /
    ``mesh_attempt_raw`` (a refused attempt of the mesh step, needs its
    ``attempt`` > 0), ``fit``, ``low``,
    ``failed`` (a JSON record, ``record_failure``), or ``layer`` /
    ``layer_low`` (a layered fit, needs its ``lsig``). ``body`` (the
    ``BODY_PARTS`` only; the others are shared and ignore it): "" or a base
    signature = the base body, an outfit body id = that body's folder
    (``body_root``).
    ValueError for an invalid item id, fsig, lsig, body, part, step or view,
    and for any path that would resolve outside ``garments/``. Creates
    nothing."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid garment item id {str(item_id)[:80]!r}")
    if not isinstance(fsig, str) or not _FSIG_RE.fullmatch(fsig):
        raise ValueError(f"invalid garment fingerprint {str(fsig)[:40]!r}")
    if part not in PART_DIRS:
        raise ValueError(f"unknown garment part {part!r}")
    root = _root(character_name)
    if part in BODY_PARTS:
        base = body_root(character_name, body)
    else:
        base = root
    if part == "image":
        if step not in IMAGE_STEPS:
            raise ValueError(f"no image step {step!r}")
        if view not in GARMENT_VIEWS:
            raise ValueError(f"no garment view {view!r}")
        tail = f".try{int(attempt)}.png" if attempt else ".png"
        path = root / PART_DIRS[part] / f"{iid}_{fsig}_{step}_{view}{tail}"
    elif part in MESH_ATTEMPT_PARTS:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ValueError(f"a mesh attempt needs its number, not {attempt!r}")
        path = root / PART_DIRS[part] / f"{iid}_{fsig}.try{attempt}{MESH_ATTEMPT_PARTS[part]}"
    elif part in LAYER_PARTS:
        if not isinstance(lsig, str) or not _FSIG_RE.fullmatch(lsig):
            raise ValueError(f"invalid layer fingerprint {str(lsig)[:40]!r}")
        path = base / PART_DIRS[part] / f"{iid}_{fsig}_{lsig}.glb"
    else:
        folder = base / PART_DIRS[part] if PART_DIRS[part] else base
        path = folder / f"{iid}_{fsig}.{_PART_SUFFIX.get(part, 'glb')}"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"garment path escapes {root}")
    return path


def hairdeck_dir(character_name: str, item_id: str, hsig: str) -> Path:
    """``garments/raw/{item}_{hsig}/`` — the folder of a HairDeck job (every
    result file + ``record.json``). ValueError like ``garment_path``.
    Creates nothing."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid garment item id {str(item_id)[:80]!r}")
    if not isinstance(hsig, str) or not _FSIG_RE.fullmatch(hsig):
        raise ValueError(f"invalid HairDeck fingerprint {str(hsig)[:40]!r}")
    root = _root(character_name)
    path = root / PART_DIRS["raw"] / f"{iid}_{hsig}"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"garment path escapes {root}")
    return path


def parse_name(path: Path) -> Optional[Tuple[str, str]]:
    """``(item_id, fsig)`` of a stored garment file, None for any other name
    (a layered fit belongs to the group of the body fit it was made from)."""
    layers = PART_DIRS["layer"]
    if path.parent.name == layers or (path.parent.name == "low" and path.parent.parent.name == layers):
        pattern = _LAYER_NAME_RE
    elif path.parent.name == "mesh" and path.parent.parent.name == PART_DIRS["attempt"]:
        pattern = _MESH_ATTEMPT_NAME_RE
    else:
        pattern = _IMAGE_NAME_RE if path.parent.name == PART_DIRS["image"] else _MESH_NAME_RE
    match = pattern.fullmatch(path.name)
    return (match.group("item"), match.group("fsig")) if match else None


def is_strands_sidecar(path: Path) -> bool:
    """Whether a stored garment file is a hair fit's strand sidecar (``{item}_{fsig}.strands.{json,npz}``), not
    a fit, a fit record or a mesh — the readers of a group's ``.json`` files skip it."""
    return Path(path).name.endswith((".strands.json", ".strands.npz"))


def stored_groups(character_name: str) -> Dict[Tuple[str, str], List[Path]]:
    """Every recognised garment file of the character, grouped by
    ``(item_id, fsig)`` — the fits of every outfit body (``bodies/<body
    id>/…``) in the group of their ``(item_id, fsig)`` too (``body_of``
    tells them apart). Files with any other name are not listed."""
    root = _root(character_name)
    out: Dict[Tuple[str, str], List[Path]] = {}
    if not root.is_dir():
        return out
    folders = [root] + [root / sub for sub in sorted(set(PART_DIRS.values())) if sub]
    bodies = root / BODIES_DIR
    if bodies.is_dir():
        body_subs = sorted({PART_DIRS[part] for part in BODY_PARTS})
        for body in sorted(bodies.iterdir()):
            if body.is_dir() and is_body_id(body.name):
                folders += [body] + [body / sub for sub in body_subs if sub]
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            key = parse_name(path)
            if key is not None:
                out.setdefault(key, []).append(path)
    return out


def earlier_mesh_fsigs(character_name: str, item_id: str, current_fsig: str) -> List[str]:
    """Ruling A131: the fingerprints of ``item_id`` other than ``current_fsig`` that still hold a generated mesh
    (``prepared`` / ``raw``) — a clothing fsig carries the base ``bsig``, so a new base body moves the piece onto a
    new, empty fsig while the meshes made for the earlier body stay stored. Newest first (by the mesh file's
    mtime). Read-only, never raises."""
    found: Dict[str, float] = {}
    try:
        for (iid, fsig), _paths in stored_groups(character_name).items():
            if iid != item_id or fsig == current_fsig:
                continue
            for part in ("prepared", "raw"):
                path = garment_path(character_name, item_id, fsig, part)
                if path.is_file():
                    found[fsig] = max(found.get(fsig, 0.0), path.stat().st_mtime)
    except Exception:  # noqa: BLE001 — a hint, never a failure of the reader
        logger.debug("Earlier meshes of %s/%s unreadable", character_name, item_id, exc_info=True)
    return sorted(found, key=lambda f: -found[f])


def fitted_on_earlier_body(character_name: str, item_id: str, bsig: str) -> bool:
    """Ruling A131: whether ``item_id`` has an accepted fit (any fsig) made on a base other than ``bsig`` — the
    piece was ready on an earlier body and waits to be fitted on the new one (the Build refits it from that
    source on the CPU, ``garment_source``). Read-only, never raises."""
    try:
        root = _root(character_name)
        for (iid, _fsig), paths in stored_groups(character_name).items():
            if iid != item_id:
                continue
            for path in paths:
                if path.suffix != ".glb" or path.parent != root:
                    continue
                record = read_record(path.with_suffix(".json"))
                if record.get("accepted") is True and str(record.get("base_signature") or "") not in ("", bsig):
                    return True
    except Exception:  # noqa: BLE001 — a reason, never a failure of the reader
        logger.debug("Earlier fits of %s/%s unreadable", character_name, item_id, exc_info=True)
    return False


# --- Fingerprint --------------------------------------------------------------

def image_steps(kind: str) -> Tuple[str, ...]:
    """The image steps of ``kind`` in chain order (clothing: worn, ghost,
    cutout; hair and footwear: none). ValueError for an unknown kind."""
    if kind not in GARMENT_STEPS:
        raise ValueError(f"unknown garment kind {kind!r}")
    return tuple(step for step in GARMENT_STEPS[kind] if step in IMAGE_STEPS)


def _kind_inputs(kind: str, character_name: str, profile: Dict[str, Any],
                 item_id: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
    """The kind's own fingerprint inputs; clothing and footwear need
    ``item_id`` (their inputs are the item's). ``state`` (clothing only, plan
    2026-11-12-unified-worn-pieces Task 11b): the open / closed state the
    inputs are for, None → the profile's worn state
    (``garment_clothing.fsig_inputs``)."""
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair.fsig_inputs(character_name, str(item_id or ""), profile=profile)
    if kind in ("clothing", "footwear"):
        from app.models.inventory import get_item
        item = get_item(item_id) if item_id else None
        if not item:
            raise ValueError(f"{str(item_id)[:80]!r} is no item")
        if kind == "footwear":
            from app.core import garment_footwear
            return garment_footwear.fsig_inputs(character_name, item, profile=profile)
        from app.core import garment_clothing
        return garment_clothing.fsig_inputs(character_name, item, profile=profile, state=state)
    raise ValueError(f"unknown garment kind {kind!r}")


def kind_method(kind: str, character_name: str, profile: Dict[str, Any], *, item_id: str = "") -> str:
    """The method a garment ``item_id`` of ``kind`` is made with: a hairstyle
    its own mode (``garment_hair.hairstyle_mode``), footwear always a
    ``shoe``, every other kind the edit chain."""
    if kind == "hair":
        from app.core import garment_hair
        from app.models.inventory import get_item
        return garment_hair.hairstyle_mode(get_item(str(item_id or "")))
    if kind == "footwear":
        return SHOE
    return EDIT_CHAIN


def steps_for(kind: str, method: str) -> Tuple[str, ...]:
    """The step order of ``kind`` made with ``method``: hair by HairDeck is
    ``HAIRDECK_STEPS``, by HAAR ``HAAR_STEPS``, hair in the body mesh (``BODY``) has none — ``()``,
    nothing ever runs —, footwear only by ``shoe`` (``FOOTWEAR_STEPS``; the
    edit chain is never run for a feet piece), clothing only by the edit
    chain (``GARMENT_STEPS[kind]``). ValueError for an unknown kind or method
    (hair by any other method too — only ``body``, HairDeck and HAAR remain)."""
    if kind not in GARMENT_STEPS:
        raise ValueError(f"unknown garment kind {kind!r}")
    if kind == "hair":
        if method == BODY:
            return ()
        if method == HAIRDECK:
            return HAIRDECK_STEPS
        if method == HAAR:
            return HAAR_STEPS
        raise ValueError(f"unknown hair method {method!r}")
    if kind == "footwear":
        if method != SHOE:
            raise ValueError(f"unknown footwear method {method!r}")
        return FOOTWEAR_STEPS
    if method != EDIT_CHAIN:
        raise ValueError(f"unknown {kind} method {method!r}")
    return GARMENT_STEPS[kind]


def _garment_kind(item_id: str) -> str:
    """The garment kind of an item: ``garment.kind`` of a garment item, or
    ``clothing`` / ``footwear`` for an own-mesh outfit piece
    (``garment_set``). Ownership is checked by the caller
    (``garments._item``)."""
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    kind = garment_set.garment_kind_of(item)
    if kind is None:
        raise ValueError(f"{item_id!r} is no garment item of a known kind")
    return kind


def garment_method(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> str:
    """``kind_method`` of a garment item. ValueError when ``item_id`` is no
    garment of a known kind."""
    kind = _garment_kind(item_id)
    return kind_method(kind, character_name, _profile_of(character_name, profile), item_id=item_id)


def _intended_params(occasion: str, character_name: str) -> Dict[str, Any]:
    """The ``extra_params`` of the backend ``occasion`` is meant to run on for the character
    (``routing.intended_backend``: configuration only, so a cooldown never changes it); {} when there is none."""
    from app.imagegen import routing, service
    pool = getattr(service.get_image_service(), "pool", None)
    if pool is None:
        return {}
    try:
        backend = routing.intended_backend(occasion, character_name, pool=pool)
    except Exception:  # noqa: BLE001 — a fingerprint never fails on the routing config
        logger.exception("%s backend of %s unresolvable", occasion, character_name)
        return {}
    params = getattr(backend, "extra_params", None) if backend is not None else None
    return dict(params) if isinstance(params, dict) else {}


def hairdeck_backend_params(character_name: str) -> Dict[str, Any]:
    """The ``extra_params`` of the backend the ``hair_mesh`` occasion is meant
    to run on for the character (``routing.intended_backend``: configuration
    only, so a cooldown never changes it); {} when there is none."""
    return _intended_params("hair_mesh", character_name)


def strands_backend_params(character_name: str) -> Dict[str, Any]:
    """The ``extra_params`` of the backend the ``hair_strands`` occasion (HAAR) is meant to run on for the
    character; {} when there is none."""
    return _intended_params("hair_strands", character_name)


def garment_hsig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over ``{profile_image, extra_params, version}``: the sha256
    of the character's current profile picture ("" without one), the
    ``extra_params`` of the intended ``hair_mesh`` backend
    (``hairdeck_backend_params``) and ``HAIRDECK_VERSION`` — plus
    ``beard_free`` for a character with facial hair
    (``garment_beard.hsig_inputs``: HairDeck gets the picture with the beard
    removed; absent otherwise, so such an hsig is unchanged). Names the
    HairDeck job folder (``hairdeck_dir``). Neither the base nor the colour
    override is in it: changing them re-fits, never re-runs HairDeck."""
    from app.core import base_body, garment_beard
    from app.core.model_refs import current_profile_image
    profile = _profile_of(character_name, profile)
    payload = {"profile_image": base_body.file_sha256(current_profile_image(character_name, profile=profile)),
               "extra_params": hairdeck_backend_params(character_name),
               "version": HAIRDECK_VERSION,
               **garment_beard.hsig_inputs(character_name, profile=profile)}
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return digest.hexdigest()[:12]


def haar_prompt(item_id: str) -> str:
    """The prompt of a HAAR hairstyle's strand jobs: its text as is (``garment_hair.hairstyle_description``)."""
    from app.core import garment_hair
    from app.models.inventory import get_item
    return garment_hair.hairstyle_description(get_item(str(item_id or "")))


def garment_ssig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over ``{prompt, extra_params, version}``: the hairstyle's text (``haar_prompt``), the
    ``extra_params`` of the intended ``hair_strands`` backend (``strands_backend_params``) and ``HAAR_VERSION``.
    Names the HAAR job folder (``haar_dir``). Neither the base nor the colour is in it: changing them re-fits the
    stored seeds, never asks HAAR again. ``profile`` is accepted for symmetry with ``garment_hsig``."""
    payload = {"prompt": haar_prompt(item_id), "extra_params": strands_backend_params(character_name),
               "version": HAAR_VERSION}
    return _md5(payload)


def haar_dir(character_name: str, item_id: str, ssig: str) -> Path:
    """``garments/raw/{item}_{ssig}/`` — the folder of a HAAR hairstyle's strand jobs (``s{seed}/`` per seed +
    ``record.json``). ValueError like ``hairdeck_dir``. Creates nothing."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid garment item id {str(item_id)[:80]!r}")
    if not isinstance(ssig, str) or not _FSIG_RE.fullmatch(ssig):
        raise ValueError(f"invalid HAAR fingerprint {str(ssig)[:40]!r}")
    root = _root(character_name)
    path = root / PART_DIRS["raw"] / f"{iid}_{ssig}"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"garment path escapes {root}")
    return path


def haar_seed_dir(folder: Path, seed: int) -> Path:
    """``<haar_dir>/s{seed}``."""
    return Path(folder) / f"s{int(seed)}"


def haar_seeds(character_name: str, item_id: str, ssig: str) -> List[int]:
    """Every seed stored in the HAAR folder of ``ssig`` (a ``s{seed}/`` folder holding a strand file and a head
    file), ascending. A seed folder is renamed into place whole, so a listed seed is complete."""
    from app.core import strand_file
    folder = haar_dir(character_name, item_id, ssig)
    if not folder.is_dir():
        return []
    out: List[int] = []
    for sub in folder.iterdir():
        match = _SEED_DIR_RE.fullmatch(sub.name)
        if not match or not sub.is_dir():
            continue
        names = [p.name for p in sub.iterdir() if p.is_file()]
        if any(n.endswith(strand_file.STRANDS_SUFFIXES) for n in names) \
                and any(n.endswith(strand_file.HEAD_SUFFIX) for n in names):
            out.append(int(match.group(1)))
    return sorted(out)


def haar_record(character_name: str, item_id: str, ssig: str) -> Dict[str, Any]:
    """The HAAR folder's ``record.json`` ({} without one)."""
    return read_record(haar_dir(character_name, item_id, ssig) / HAAR_RECORD)


def haar_rank(result: Dict[str, Any]) -> Tuple[float, float]:
    """The ranking key of one passing seed's result (spec § 6.3.1): ``(face_cards, |tip p50 - class target|)``
    — the class target ``garment_haar.CLASS_TARGET_CM`` of the result's ``length_class`` (0 without a class),
    a missing number ranks last."""
    from app.core.garment_haar import CLASS_TARGET_CM
    metrics = result.get("metrics") or {}

    def number(key: str) -> float:
        try:
            value = float(metrics.get(key))
        except (TypeError, ValueError):
            return math.inf
        return value if math.isfinite(value) else math.inf

    cls = " ".join(str(result.get("length_class") or "").lower().split())
    target = CLASS_TARGET_CM.get(cls)
    tip = number("tip_p50_rel_shoulder_cm")
    if not math.isfinite(tip):
        off = math.inf
    else:
        off = abs(tip - target) if target is not None else 0.0
    return number("face_cards"), off


def haar_best_seed(results: Dict[Any, Dict[str, Any]]) -> Optional[int]:
    """The best PASSING seed of ``results`` (seed -> result; keys may be the record's strings): fewest face cards,
    then the tip nearest the class target, then the lowest seed (spec § 6.3.1). None when none passes."""
    passing = []
    for key, result in results.items():
        try:
            seed = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict) and result.get("accepted") is True:
            passing.append((haar_rank(result), seed))
    return min(passing)[1] if passing else None


def haar_pick(item: Optional[Dict[str, Any]]) -> Optional[int]:
    """The hairstyle's ``haar_seed`` setting as an int, None = automatic."""
    from app.core import garment_hair
    value = garment_hair.hairstyle_settings(item).get("haar_seed")
    if isinstance(value, bool):
        return None
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return None
    return seed if seed > 0 else None


def haar_served_seed(character_name: str, item_id: str, ssig: str, *,
                     item: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """The seed a HAAR hairstyle serves under ``ssig``: its ``haar_seed`` while that seed is stored (a pick of a
    refused seed too — the user saw its reasons), else the best passing stored seed with a result
    (``haar_best_seed``), else None."""
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id)
    stored = haar_seeds(character_name, item_id, ssig)
    pick = haar_pick(item)
    if pick is not None and pick in stored:
        return pick
    results = haar_record(character_name, item_id, ssig).get("results") or {}
    return haar_best_seed({s: results[str(s)] for s in stored if isinstance(results.get(str(s)), dict)})


def _edit_payload(character_name: str, item_id: str, kind: str, profile: Dict[str, Any], *,
                  bsig: Optional[str] = None, base_images: Optional[Dict[str, str]] = None,
                  state: Optional[str] = None) -> Dict[str, Any]:
    """The edit-chain fingerprint payload (R10) — on the current base, or on
    the base ``bsig`` with the base view sha256 ``base_images`` (both given:
    the payload a group of images made on that base has with the item's
    CURRENT inputs, ``edit_fsig_on``). ``state``: ``_kind_inputs``."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    if bsig is None or base_images is None:
        bsig = base_body.base_signature(character_name, profile=profile)
        base_images = {view: base_body.file_sha256(find_ref_image(character_name, base_body._kind(view), bsig))
                       for view in GARMENT_VIEWS}
    return {"kind": kind, **_kind_inputs(kind, character_name, profile, item_id, state),
            "version": GARMENT_VERSION[kind], "bsig": bsig, "base_images": dict(base_images)}


def edit_fsig_on(character_name: str, item_id: str, kind: str, profile: Dict[str, Any], *, bsig: str,
                 base_images: Dict[str, str]) -> str:
    """The edit-chain fsig the item's CURRENT inputs (description, slots,
    ``GARMENT_VERSION``) would have on the base ``bsig`` / ``base_images``:
    equal to the fsig a group of images was rendered under exactly when
    only the base differs (``garment_source.find_source``)."""
    return _md5(_edit_payload(character_name, item_id, kind, profile, bsig=bsig, base_images=base_images))


def _md5(payload: Dict[str, Any]) -> str:
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return digest.hexdigest()[:12]


def garment_fsig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None, state: Optional[str] = None,
                 method: Optional[str] = None, swing: Optional[bool] = None) -> str:
    """md5[:12] over ``{kind, <kind inputs>, version, bsig, base_images}``
    (R10); hair made by HAAR adds ``{method, ssig, seed, colour}`` (the served
    seed, ``haar_served_seed``; the colour override), ``cut`` only when the hairstyle has one
    (``garment_hair.hair_cut``, Ruling A71: an uncut hairstyle keeps its fingerprint) and nothing of Swing;
    hair made by HairDeck adds ``{method, hsig, colour, placement}``
    (the colour override, "" = automatic; the manual placement
    ``garment_hair.hair_placement``, None = automatic) and ``swing: True``
    only when the hair swings on its spring chains (``hair_motion.swing_on``,
    Ruling H11: a Swing-off fit keeps the fingerprint it had before Swing
    was a fit input). Footwear is md5[:12] over ``{kind,
    ssig, insole_version, width_cap, fit_version}`` alone
    (``garment_footwear.fsig_inputs``) — no base signature, no base images.
    A clothing piece worn OPEN is another garment (plan
    2026-11-12-unified-worn-pieces Task 11b): ``state`` (``open`` /
    ``closed``; None → the profile's worn state) enters its inputs —
    ``"state": "open"`` and the ", worn open" fragment; a closed piece's fsig
    is the one it had before the option. ``method`` (hair only): the
    fingerprint the hairstyle would have in that mode — None = its own mode
    (the Wardrobe hair row's "Other method" preview asks for the mode it left).
    ``swing`` (HairDeck only): the fingerprint with that Swing — None = the
    hairstyle's own (the refit sweep asks for the Swing-off one a fit from
    before Ruling H-R1 was made under, ``garment_refit.swing_default_fits``).
    ValueError when ``item_id`` is no garment of a known kind (or for a bad
    ``state``)."""
    kind = _garment_kind(item_id)
    profile = _profile_of(character_name, profile)
    if kind == "footwear":
        # No base in it (spec § 5.6): a base change makes the fit stale, never the source.
        return _md5({"kind": kind, **_kind_inputs(kind, character_name, profile, item_id)})
    payload = _edit_payload(character_name, item_id, kind, profile, state=state)
    method = method or kind_method(kind, character_name, profile, item_id=item_id)
    if method == HAIRDECK:
        from app.core import garment_hair
        from app.models.inventory import get_item
        settings = garment_hair.hairstyle_settings(get_item(item_id))
        payload.update(method=HAIRDECK, hsig=garment_hsig(character_name, item_id, profile=profile),
                       colour=garment_hair.hair_colour_override(settings),
                       placement=garment_hair.hair_placement(settings))
        from app.core import hair_motion
        if hair_motion.swing_on(settings) if swing is None else swing:
            payload["swing"] = True
    elif method == HAAR:
        from app.core import garment_hair
        from app.models.inventory import get_item
        item = get_item(item_id)
        ssig = garment_ssig(character_name, item_id, profile=profile)
        settings = garment_hair.hairstyle_settings(item)
        payload.update(method=HAAR, ssig=ssig,
                       seed=haar_served_seed(character_name, item_id, ssig, item=item),
                       colour=garment_hair.hair_colour_override(settings))
        cut = garment_hair.hair_cut(settings)
        if cut:
            payload["cut"] = cut
    return _md5(payload)


def fit_method(record: Dict[str, Any]) -> str:
    """The method a fit record was made with; a record without ``method``
    (every fit from before HairDeck) is an edit-chain fit. Hair fits of a
    removed hair method keep their method name here and are never served
    (``accepted_fit`` follows the current method)."""
    return str(record.get("method") or EDIT_CHAIN)


# --- Records ------------------------------------------------------------------

def finite_json(value: Any) -> Any:
    """A copy of a JSON value with every non-finite float (NaN, +-inf) as None. A refused cut whose hairline
    could not be measured stored NaN (Python's json writes it), and the hair GET could not encode the
    record: every record is written and read through this."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(v) for v in value]
    return value


def read_record(path: Path) -> Dict[str, Any]:
    """A sidecar's JSON object, {} when missing, unreadable or not an object; non-finite numbers (a NaN already
    on disk) read as None (``finite_json``)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return finite_json(data) if isinstance(data, dict) else {}


def write_record(path: Path, record: Dict[str, Any]) -> None:
    """Write a sidecar atomically (temp file in the same folder + replace); non-finite numbers are written as
    null (``finite_json``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(finite_json(record), indent=2, ensure_ascii=False, sort_keys=True,
                                  allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
        from app.core import figure
        figure.invalidate()   # a fit or a refusal can change a delivered figure


def footwear_servable(record: Dict[str, Any]) -> bool:
    """An accepted FOOTWEAR fit record of any fit version that the assembly can graft: it carries the body cut
    (``cut`` with ``sides``, ``garment_assembly._cut_body``) and the ``foot_pose``. Every version since the cut
    (fit version 3) and the foot pose has them; an older record without them is never served."""
    cut = record.get("cut")
    return (record.get("accepted") is True and isinstance(cut, dict) and bool(cut.get("sides"))
            and isinstance(record.get("foot_pose"), dict))


def user_accept_holds(record: Dict[str, Any], character_name: str = "") -> bool:
    """False for a fit the USER accepted (``user_accepted``, Ruling A31 — ``fit_attempts``) that is no longer
    the fit accepted: made by another fit algorithm version, or (on the base model, given ``character_name``) of
    another prepared mesh (clothing) or shoe source (footwear) than the one stored now. True for every other record. A user's acceptance is bound to
    the fit it saw; such a record is never served."""
    if not isinstance(record.get("user_accepted"), dict):
        return True
    from app.core import garment_fit
    if record.get("fit_version") != garment_fit.expected_fit_version(record):
        return False
    kind = str(record.get("kind") or "")
    on_base = not is_body_id(str(record.get("body_id") or ""))
    if character_name and kind == "footwear" and on_base:
        from app.core import garment_footwear  # the shoe source it was fitted from must still be today's
        try:
            return garment_footwear.fit_state(character_name, str(record.get("item_id") or ""),
                                              str(record.get("fsig") or ""),
                                              str(record.get("base_model_sha256") or "")) == "accepted"
        except ValueError:
            return False
    prepared = (record.get("inputs") or {}).get("prepared_sha256")
    if character_name and prepared and kind == "clothing" and on_base:
        from app.core.base_body import file_sha256
        try:
            path = garment_path(character_name, str(record.get("item_id") or ""), str(record.get("fsig") or ""),
                                "prepared")
        except ValueError:
            return False
        return file_sha256(path) == prepared
    return True


def image_accept_holds(path: Path, record: Dict[str, Any]) -> bool:
    """False for a garment IMAGE the user took by hand although its gate refused it (Ruling A37, "Use this":
    ``user_accepted {at, attempt, attempt_sha256, inputs, reasons}``) once any of its inputs changed: the file
    is no longer the attempt the user saw (``attempt_sha256``), or an image it was made from (``inputs``:
    ``{file name in the same folder: sha256}`` — the source step's image, a drafted back's front) is no longer
    that file. True for every other record. Such an image never counts as accepted again; the chain renders the
    view anew."""
    block = record.get("user_accepted")
    if not isinstance(block, dict) or "attempt_sha256" not in block:
        return True
    from app.core.base_body import file_sha256
    if file_sha256(path) != block.get("attempt_sha256"):
        return False
    inputs = block.get("inputs") if isinstance(block.get("inputs"), dict) else {}
    return all(file_sha256(path.parent / str(name)) == sha for name, sha in inputs.items())


def accepted_image(path: Path) -> bool:
    """A garment image (or another chain file with a record) that is accepted: on disk, ``accepted`` True in its
    record, and — taken by the user against its gate — still made from the inputs the user saw
    (``image_accept_holds``)."""
    if not path.is_file():
        return False
    record = read_record(path.with_suffix(".json"))
    return record.get("accepted") is True and image_accept_holds(path, record)


def _accepted_on(record: Dict[str, Any], base_model_sha: str) -> bool:
    """Accepted on the base model ``base_model_sha``. A FOOTWEAR fit of an
    older ``footwear_fit.FOOTWEAR_FIT_VERSION`` (an older fsig: the version is
    part of the footwear fsig) is served meanwhile when it can be grafted
    (``footwear_servable``) — until a fit of the new version is accepted, and
    on after that fit is refused, like every other garment (plan 2026-11-12
    fit-sdf-speed-drape, Ruling R7b: a shoe never goes missing because of a
    version bump; the current fsig's fit stays ``missing`` in
    ``garment_footwear.fit_state``, so the chain and the refit sweep replace
    it). Was R11 (plan
    2026-11-10-footwear-rigid-shoes Task 10 carry): never served."""
    from app.core.model_geometry import record_matches
    if record.get("accepted") is not True or not record_matches(record, base_model_sha):
        return False  # Ruling A107: judged by geometry — a texture-only base rewrite keeps the fit
    if not user_accept_holds(record):
        return False
    if str(record.get("kind") or "") == "footwear":
        from app.core.footwear_fit import FOOTWEAR_FIT_VERSION
        return record.get("fit_version") == FOOTWEAR_FIT_VERSION or footwear_servable(record)
    return True


def newest_body_footwear_fit(character_name: str, item_id: str, body: str, body_sha: str
                             ) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """``(fit GLB, record)`` of the item's newest (GLB mtime) accepted footwear fit on the outfit body ``body``
    made of the body bytes ``body_sha``, any fsig / fit version, graftable (``footwear_servable``) — what an outfit
    model on that body keeps of a shoe whose fit of the current fsig is missing or refused (Ruling R7b). None
    when there is none. Read-only."""
    if not is_body_id(body) or not body_sha:
        return None
    folder = body_root(character_name, body)
    best: Optional[Tuple[int, Path, Dict[str, Any]]] = None
    for (iid, _fsig), files in stored_groups(character_name).items():
        if iid != item_id:
            continue
        for path in files:
            if path.suffix != ".glb" or path.parent != folder:
                continue
            record = read_record(path.with_suffix(".json"))
            if (str(record.get("kind") or "") != "footwear" or record.get("body_id") != body
                    or record.get("body_sha256") != body_sha or not footwear_servable(record)
                    or isinstance(record.get("user_accepted"), dict)):
                continue  # a user's acceptance (Ruling A31) never stands in for another fit
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, path, record)
    return (best[1], best[2]) if best else None


def fit_state(record: Dict[str, Any]) -> str:
    """The open / closed state a fit record was made for: ``"open"`` when it says so (plan Task 11b), else
    ``"closed"`` — every record from before the option, and every non-clothing fit."""
    return "open" if record.get("state") == "open" else "closed"


def item_state(character_name: str, item_id: str, profile: Dict[str, Any], state: Optional[str] = None) -> str:
    """The state a garment item is judged in: ``state`` when given, else the profile's worn state of a closable
    clothing piece (``garment_clothing.state_of``); ``closed`` for every other garment (hair, footwear, an
    unknown item)."""
    from app.core import garment_clothing
    from app.models.inventory import get_item
    item = get_item(item_id)
    if not item or _garment_kind_or_none(item_id) != "clothing":
        return "closed"
    return garment_clothing.state_of(item, profile, state)


def _garment_kind_or_none(item_id: str) -> Optional[str]:
    try:
        return _garment_kind(item_id)
    except ValueError:
        return None


def accepted_fit(character_name: str, item_id: str, *, base_model_sha: str,
                 profile: Optional[Dict[str, Any]] = None,
                 state: Optional[str] = None) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """The fit to serve for a garment item on the base model ``base_model_sha``
    (R11): the current-fsig fit when its record is accepted on that model,
    else the newest (GLB mtime) accepted fit of the item on that model made
    with the CURRENT method (``fit_method``; a switched method never serves
    the other method's hair), else None. An empty ``base_model_sha`` (no base
    model) has no fit. A footwear fit of an older fit version is served
    while it can be grafted (``_accepted_on``, Ruling R7b). A HAAR fit is served like a HairDeck one (its
    current fsig names the served seed). Hair whose method is ``BODY`` is never
    served: the hair is part of the body mesh. Per open / closed state (plan
    2026-11-12-unified-worn-pieces Task 11b, ruling A2): ``state`` names the
    fsig and filters the fallback — asked for one state, a piece is never
    served the other state's fit. ``state`` None = the profile's worn state
    (``item_state``), and then the SERVED fit (fix round T12-F1, ruling F13
    b): a piece worn open whose open fit is missing is served its closed fit
    meanwhile (``figure``: "Shown closed until its open mesh is built") —
    never nothing, never painted while a closed mesh exists."""
    if not base_model_sha:
        return None
    profile = _profile_of(character_name, profile)
    served = state is None
    try:
        state = item_state(character_name, item_id, profile, state)
        current: Optional[str] = garment_fsig(character_name, item_id, profile=profile, state=state)
        method = garment_method(character_name, item_id, profile=profile)
    except ValueError:
        current, method = None, EDIT_CHAIN
        state = state if state in ("open", "closed") else "closed"
    if method == BODY:
        return None
    if current is not None:
        path = garment_path(character_name, item_id, current, "fit")
        record = read_record(path.with_suffix(".json"))
        if (path.is_file() and _accepted_on(record, base_model_sha) and fit_state(record) == state
                and user_accept_holds(record, character_name)):
            return path, record
    hit = newest_accepted_fits(character_name, item_id, base_model_sha=base_model_sha, state=state).get(method)
    if hit is None and served and state == "open":
        # Ruling F13 b: worn open without its open mesh — the closed mesh stands in.
        return accepted_fit(character_name, item_id, base_model_sha=base_model_sha, profile=profile, state="closed")
    return hit


def newest_accepted_fits(character_name: str, item_id: str, *, base_model_sha: str = "",
                         state: Optional[str] = None) -> Dict[str, Tuple[Path, Dict[str, Any]]]:
    """method -> ``(fit GLB, record)`` of the item's newest (GLB mtime)
    accepted fit made with that method (``fit_method``); with
    ``base_model_sha`` only fits accepted on that base model; with ``state``
    (``open`` / ``closed``) only fits made for that state (``fit_state``: a
    record without ``state`` is closed), None = every state. Read-only:
    never creates ``garments/``."""
    best: Dict[str, Tuple[int, Path, Dict[str, Any]]] = {}
    root = _root(character_name)
    for (iid, _fsig), files in stored_groups(character_name).items():
        if iid != item_id:
            continue
        for path in files:
            if path.suffix != ".glb" or path.parent != root:
                continue
            record = read_record(path.with_suffix(".json"))
            if record.get("accepted") is not True or isinstance(record.get("user_accepted"), dict):
                continue  # a user's acceptance (Ruling A31) holds for its own fsig only, never as a fallback
            if base_model_sha and not _accepted_on(record, base_model_sha):
                continue
            if state is not None and fit_state(record) != state:
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            method = fit_method(record)
            if method not in best or mtime > best[method][0]:
                best[method] = (mtime, path, record)
    return {method: (path, record) for method, (_mtime, path, record) in best.items()}


# --- Failed chains (on disk) ---------------------------------------------------
#
# A chain run that failed for an fsig is NOT re-run by automatic triggers
# (outfit renders, a new base model): the piece stays painted on with the
# reason until an explicit run (Regenerate, POST .../garments/{item}/run)
# or a changed fsig (plan 2026-11-09-base-body-phase5-mesh-items, Task 4 fix
# round 1). On disk, so a restart does not reset it. A refused FIT also
# depends on the base model, which the fsig leaves out: it holds only on the
# base model it failed on.

def record_failure(character_name: str, item_id: str, fsig: str, *, step: str, error: str,
                   base_model_sha: str = "", stamp: Optional[Dict[str, Any]] = None,
                   refit_offer: Optional[Dict[str, Any]] = None) -> None:
    """Persist the failure of a chain run of ``(item_id, fsig)``. ``stamp`` (a refused refit of the sweep,
    ``garment_refit.refusal_stamp``): ``{fit_version, inputs_id}`` merged into the record — the sweep does not
    try the same refit again (``garment_refit.held_refusal``, Ruling R7c). ``refit_offer`` (Ruling A162): the
    refused CPU refit that stopped the run before any hub job — ``{reason, source_fsig, source_bsig, attempt}``."""
    from app.core import model_geometry
    from app.core.timeutils import utc_now
    path = garment_path(character_name, item_id, fsig, "failed")
    if not path.parent.parent.parent.is_dir():
        return  # never mint the folders of a vanished character
    record = {"item_id": item_id, "fsig": fsig, "step": step, "error": error,
              "base_model_sha256": base_model_sha, **model_geometry.stamp(base_model_sha),
              "failed_at": _iso(utc_now())}
    if step == "fit":
        # Refused by a fit that already widens a too-small piece (``garment_refit`` retries one without).
        from app.core.garment_fit import SCALE_RETRY_VERSION
        record["scale_retry"] = SCALE_RETRY_VERSION
        if stamp:
            record.update({key: stamp[key] for key in ("fit_version", "inputs_id") if key in stamp})
        if refit_offer:
            record["refit_offer"] = dict(refit_offer)
    write_record(path, record)


def record_body_failure(character_name: str, item_id: str, fsig: str, body: str, *, error: str,
                        body_sha: str, base_fit_sha: str, fit_version: Any) -> None:
    """Persist a refused (or failed) fit of ``(item_id, fsig)`` on the outfit
    body ``body``: automatic fits on that body skip it while the body, the
    base fit it was derived from, the fit algorithm and the body gates
    (``garment_source.BODY_GATES_VERSION``) are the same (``body_failure``)."""
    from app.core.garment_fit import SCALE_RETRY_VERSION
    from app.core.garment_source import BODY_GATES_VERSION
    from app.core.timeutils import utc_now
    from app.models.character import get_character_dir
    if not get_character_dir(character_name).is_dir():
        return  # never mint the folders of a vanished character
    write_record(garment_path(character_name, item_id, fsig, "failed", body=body),
                 {"item_id": item_id, "fsig": fsig, "step": "fit", "error": error, "body_id": body,
                  "body_sha256": body_sha, "base_fit_sha256": base_fit_sha, "fit_version": fit_version,
                  "scale_retry": SCALE_RETRY_VERSION, "gates": BODY_GATES_VERSION, "failed_at": _iso(utc_now())})


def body_failure(character_name: str, item_id: str, fsig: str, body: str, *, body_sha: str,
                 base_fit_sha: str, fit_version: Any) -> Optional[Dict[str, Any]]:
    """The persisted failure of a fit of ``(item_id, fsig)`` on the outfit
    body ``body`` that still holds: recorded on the same body
    (``body_sha``), from the same base fit (``base_fit_sha``) by the same fit
    algorithm (``fit_version``) and the same body gates (``garment_source.
    BODY_GATES_VERSION`` — a refusal of other gates is judged again, T15-F1).
    None otherwise."""
    from app.core.garment_source import BODY_GATES_VERSION
    try:
        record = read_record(garment_path(character_name, item_id, fsig, "failed", body=body))
    except ValueError:
        return None
    if (not record.get("error") or record.get("body_sha256") != body_sha
            or record.get("base_fit_sha256") != base_fit_sha or record.get("fit_version") != fit_version
            or record.get("gates") != BODY_GATES_VERSION):
        return None
    return record


def clear_failure_on_body(character_name: str, item_id: str, fsig: str, body: str) -> None:
    """An accepted fit of ``(item_id, fsig)`` on the outfit body ``body``
    drops its failure record there."""
    try:
        garment_path(character_name, item_id, fsig, "failed", body=body).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def clear_failure(character_name: str, item_id: str, fsig: str) -> None:
    """A successful run of ``(item_id, fsig)`` drops its failure record."""
    try:
        garment_path(character_name, item_id, fsig, "failed").unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def chain_failure(character_name: str, item_id: str, fsig: str, *,
                  base_model_sha: str = "") -> Optional[Dict[str, Any]]:
    """The persisted failure of ``(item_id, fsig)`` that automatic triggers
    honour — None when there is none, and for a failed ``fit`` recorded on
    another base model than ``base_model_sha``."""
    try:
        record = read_record(garment_path(character_name, item_id, fsig, "failed"))
    except ValueError:
        return None
    if not record.get("step"):
        return None
    from app.core.model_geometry import record_matches
    if record.get("step") == "fit" and not record_matches(record, base_model_sha):
        return None
    return record


# --- Run status (in memory) ---------------------------------------------------

_status_lock = threading.Lock()
_running: Dict[Tuple[str, str], Tuple[str, datetime]] = {}
_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}
# One garment run per character at a time: the steps of one garment build on
# each other, and two items of one character share its base files.
_char_locks: Dict[str, threading.Lock] = {}


# One run per ITEM of a character at a time (Ruling A30): a CPU refit beside the character's FIFO
# (``garments.start_garment``) holds only this lock, never ``char_lock``. Lock order: ``char_lock`` before
# ``run_item_lock`` — nothing holding an item lock ever waits for ``char_lock``.
_item_locks: Dict[Tuple[str, str], threading.Lock] = {}


def char_lock(character_name: str) -> threading.Lock:
    """The lock a garment run of this character holds."""
    with _status_lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def run_item_lock(character_name: str, item_id: str) -> threading.Lock:
    """The lock every garment run of ``item_id`` for this character holds (Ruling A30): a FIFO run takes it
    after ``char_lock``, a CPU refit beside the FIFO takes it alone — so two runs of one item never overlap."""
    with _status_lock:
        return _item_locks.setdefault((character_name, item_id), threading.Lock())


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def start(character_name: str, item_id: str, step: str) -> None:
    """Mark ``step`` of the item running (SYSTEM time). A running run
    replaces the previous run's failure: the status never shows a step
    running together with an older ``failed`` record."""
    from app.core.timeutils import utc_now
    with _status_lock:
        _running[(character_name, item_id)] = (step, utc_now())
        _failed.pop((character_name, item_id), None)


def end(character_name: str, item_id: str, step: str, error: Optional[str] = None,
        gates: Optional[Any] = None) -> None:
    """Step finished. With ``error`` the item's failure becomes
    ``{step, error, gates, failed_at}``; without, a failure of the same step
    is cleared."""
    from app.core.timeutils import utc_now
    key = (character_name, item_id)
    with _status_lock:
        if (_running.get(key) or ("",))[0] == step:
            _running.pop(key, None)
        if error is not None:
            _failed[key] = {"step": step, "error": error, "gates": gates, "failed_at": utc_now()}
        elif (_failed.get(key) or {}).get("step") == step:
            _failed.pop(key, None)


def forget_failed_step(character_name: str, item_id: str, step: str) -> None:
    """Drop the item's in-memory failure when it is one of ``step`` (an input of that step changed: the refusal
    no longer speaks for the next run — Ruling A47's fit settings)."""
    with _status_lock:
        if (_failed.get((character_name, item_id)) or {}).get("step") == step:
            _failed.pop((character_name, item_id), None)


def status(character_name: str, item_id: str) -> Dict[str, Any]:
    """``{running_step, started_at, failed: {step, error, gates, failed_at} | None}``."""
    key = (character_name, item_id)
    with _status_lock:
        step, started = _running.get(key, (None, None))
        failure = _failed.get(key)
        failed = None
        if failure:
            failed = {**failure, "failed_at": _iso(failure.get("failed_at"))}
    return {"running_step": step, "started_at": _iso(started), "failed": failed}
