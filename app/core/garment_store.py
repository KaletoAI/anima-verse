"""The garment store — where a character's own-mesh garments live on disk
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R10,
R11, R13; spec ``2026-11-08-base-body-outfits-design.md`` § C.4).

Per owner, under ``characters/<name>/garments/``::

    images/{item}_{fsig}_{step}_{view}.png  + .json   the image steps of the kind
                                                      (hair: haired/ghost/cutout,
                                                      clothing: worn/ghost/cutout);
    images/{item}_{fsig}_{step}_{view}.try{n}.png     the attempts of a step
    raw/{item}_{fsig}.glb                             generator output
    prepared/{item}_{fsig}.glb                        decimated
    {item}_{fsig}.glb + .json                         the fit: rigged base with the
                                                      garment grafted on; its record
                                                      holds gates + base_model_sha256
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
above unchanged. An OUTFIT BODY of the mesh mode (``base_body.outfit_body_id``,
``ob`` + 8 hex) has the per-body parts in a folder of its own, same names::

    bodies/<body id>/{item}_{fsig}.glb + .json        the fit on that body
    bodies/<body id>/low/{item}_{fsig}.glb            its distance tier
    bodies/<body id>/layers/{item}_{fsig}_{lsig}.glb  a layered fit on that body
    bodies/<body id>/layers/low/…                     its distance tier
    bodies/<body id>/failed/{item}_{fsig}.json        the last refused fit there

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
mesh and only re-fits; the fit record's ``base_model_sha256`` decides that.

Hair has two methods (``garment_hair.hair_method``; plan
``docs/superpowers/plans/2026-11-09-hairdeck-hair.md``, Task 4): the edit chain
above, and HairDeck — steps ``("hairdeck", "fit")`` (``steps_for``). HairDeck
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
edit-chain payload plus ``method``, ``hsig``, the colour override (profile ``hair_colour``) and the
placement (profile ``hair_forward_m`` / ``hair_tilt_deg``); the
edit-chain fsig carries no ``method`` key, so it stays what it always was.
The fit is the same ``{item}_{fsig}.glb`` + record (its record says
``method: "hairdeck"``; a record without ``method`` is an edit-chain fit);
``prepared/`` is not used by HairDeck.

Hair by SUBTRACT (plan ``docs/superpowers/plans/2026-11-10-hair-subtract-method.md``) — steps
``("haired", "mesh_source", "cut", "fit")``: the haired views are the edit chain's own (stored under the
edit-chain fsig, ``image_fsig``), one mesh of the HAIRED character is generated from them
(occasion ``hair_source_mesh``) and the hair is cut off it on the CPU (``garment_cut``)::

    source/{item}_{ssig}/haired.glb                   the haired character's mesh
    source/{item}_{ssig}/haired_{view}_cut.png        its inputs (the haired views' cut-outs)
    source/{item}_{ssig}/record.json                  {accepted, ssig, image_fsig, haired, backend, ...}
    prepared/{item}_{fsig}.glb + .json                the cut (B's unrigged frame) + its gates

``ssig`` = md5[:12] over the haired views' sha256 and ``SOURCE_VERSION``: the mesh job is redone only for
new haired views. The subtract fsig is the edit-chain payload plus ``method``, the haired views' sha256,
the base MODEL's sha256 (a new base model re-cuts on the CPU, never a mesh job), the shape (``cut`` /
``shell``), the shell thickness and ``garment_cut.CUT_VERSION``.

Run status is in memory (like ``base_body``): a restart reruns only the step
that was in flight, every finished step is cached on disk under ``fsig``.
"""
import hashlib
import json
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
GARMENT_VERSION: Dict[str, int] = {"hair": 1, "clothing": 2}
GARMENT_STEPS: Dict[str, Tuple[str, ...]] = {"hair": ("haired", "ghost", "cutout", "mesh", "fit"),
                                             "clothing": ("worn", "ghost", "cutout", "mesh", "fit")}
#: The steps of hair made by HairDeck (``steps_for``).
HAIRDECK_STEPS: Tuple[str, ...] = ("hairdeck", "fit")
#: Bumped when the HairDeck job's inputs change meaning (part of ``hsig``).
HAIRDECK_VERSION = 1
#: The record of a HairDeck job folder (``hairdeck_dir``).
HAIRDECK_RECORD = "record.json"
EDIT_CHAIN = "edit_chain"
HAIRDECK = "hairdeck"
SUBTRACT = "subtract"
#: The steps of hair made by subtraction (``steps_for``; ``haired`` is the edit chain's image step).
SUBTRACT_STEPS: Tuple[str, ...] = ("haired", "mesh_source", "cut", "fit")
#: Bumped when the hair source mesh job's inputs change meaning (part of ``ssig``).
SOURCE_VERSION = 1
#: Folder of the hair source meshes (one sub-folder per ``(item, ssig)``) and the record in it.
SOURCE_DIR = "source"
SOURCE_RECORD = "record.json"
GARMENT_VIEWS: Tuple[str, ...] = ("front", "back")
#: Every step of any kind that stores images (the rest store meshes); the
#: order of one kind is ``image_steps``.
IMAGE_STEPS: Tuple[str, ...] = ("haired", "worn", "ghost", "cutout")
#: part -> sub-folder of ``garments/`` ("" = the folder itself).
PART_DIRS: Dict[str, str] = {"image": "images", "raw": "raw", "prepared": "prepared",
                             "fit": "", "low": "low", "failed": "failed",
                             "layer": "layers", "layer_low": "layers/low"}
#: The parts keyed by an inner-layer signature ``lsig`` besides the fsig.
LAYER_PARTS: Tuple[str, ...] = ("layer", "layer_low")
#: The parts kept per body (``garment_path(body=…)``); the rest is shared.
BODY_PARTS: Tuple[str, ...] = ("fit", "low", "failed", "layer", "layer_low")
#: Folder of the outfit bodies' fits under ``garments/``.
BODIES_DIR = "bodies"
#: An outfit body id (``base_body.OUTFIT_BODY_RE``).
_BODY_RE = re.compile(r"ob[0-9a-f]{8}")
#: A base signature (``base_body.BASE_SIG_RE``): the base body's fits live in ``garments/`` itself.
_BASE_RE = re.compile(r"base[0-9a-f]{8}")

_FSIG_RE = re.compile(r"[0-9a-f]{12}")
_ITEM = r"(?P<item>[A-Za-z0-9][A-Za-z0-9_-]*)"
_FSIG = r"(?P<fsig>[0-9a-f]{12})"
#: images/: {item}_{fsig}_{step}_{view}[.try{n}].{png,json}
_IMAGE_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"_[a-z]+_[a-z]+(?:\.try[0-9]+)?\.(?:png|json)")
#: the mesh folders and the fit: {item}_{fsig}.{glb,json}
_MESH_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"\.(?:glb|json)")
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
    > 0 names that attempt's file), ``raw``, ``prepared``, ``fit``, ``low``,
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
    elif part in LAYER_PARTS:
        if not isinstance(lsig, str) or not _FSIG_RE.fullmatch(lsig):
            raise ValueError(f"invalid layer fingerprint {str(lsig)[:40]!r}")
        path = base / PART_DIRS[part] / f"{iid}_{fsig}_{lsig}.glb"
    else:
        folder = base / PART_DIRS[part] if PART_DIRS[part] else base
        path = folder / f"{iid}_{fsig}.{'json' if part == 'failed' else 'glb'}"
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


def source_dir(character_name: str, item_id: str, ssig: str) -> Path:
    """``garments/source/{item}_{ssig}/`` — the hair source mesh of the
    subtract method (``haired.glb``, the cut-outs it was made from and
    ``record.json``). ValueError like ``garment_path``. Creates nothing."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid garment item id {str(item_id)[:80]!r}")
    if not isinstance(ssig, str) or not _FSIG_RE.fullmatch(ssig):
        raise ValueError(f"invalid source fingerprint {str(ssig)[:40]!r}")
    root = _root(character_name)
    path = root / SOURCE_DIR / f"{iid}_{ssig}"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"garment path escapes {root}")
    return path


def parse_name(path: Path) -> Optional[Tuple[str, str]]:
    """``(item_id, fsig)`` of a stored garment file, None for any other name
    (a layered fit belongs to the group of the body fit it was made from)."""
    layers = PART_DIRS["layer"]
    if path.parent.name == layers or (path.parent.name == "low" and path.parent.parent.name == layers):
        pattern = _LAYER_NAME_RE
    else:
        pattern = _IMAGE_NAME_RE if path.parent.name == PART_DIRS["image"] else _MESH_NAME_RE
    match = pattern.fullmatch(path.name)
    return (match.group("item"), match.group("fsig")) if match else None


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


# --- Fingerprint --------------------------------------------------------------

def image_steps(kind: str) -> Tuple[str, ...]:
    """The image steps of ``kind`` in chain order (hair: haired, ghost,
    cutout; clothing: worn, ghost, cutout). ValueError for an unknown kind."""
    if kind not in GARMENT_STEPS:
        raise ValueError(f"unknown garment kind {kind!r}")
    return tuple(step for step in GARMENT_STEPS[kind] if step in IMAGE_STEPS)


def _kind_inputs(kind: str, character_name: str, profile: Dict[str, Any],
                 item_id: Optional[str] = None) -> Dict[str, Any]:
    """The kind's own fingerprint inputs; clothing needs ``item_id`` (its
    inputs are the item's)."""
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair.fsig_inputs(character_name, profile=profile)
    if kind == "clothing":
        from app.core import garment_clothing
        from app.models.inventory import get_item
        item = get_item(item_id) if item_id else None
        if not item:
            raise ValueError(f"{str(item_id)[:80]!r} is no item")
        return garment_clothing.fsig_inputs(character_name, item, profile=profile)
    raise ValueError(f"unknown garment kind {kind!r}")


def kind_method(kind: str, character_name: str, profile: Dict[str, Any]) -> str:
    """The method a garment of ``kind`` is made with: hair follows
    ``garment_hair.hair_method``, every other kind the edit chain."""
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair.hair_method(character_name, profile=profile)
    return EDIT_CHAIN


def steps_for(kind: str, method: str) -> Tuple[str, ...]:
    """The step order of ``kind`` made with ``method``: hair by HairDeck is
    ``HAIRDECK_STEPS``, anything else ``GARMENT_STEPS[kind]``. ValueError for
    an unknown kind or method."""
    if kind not in GARMENT_STEPS:
        raise ValueError(f"unknown garment kind {kind!r}")
    if method == HAIRDECK and kind == "hair":
        return HAIRDECK_STEPS
    if method == SUBTRACT and kind == "hair":
        return SUBTRACT_STEPS
    if method != EDIT_CHAIN:
        raise ValueError(f"unknown {kind} method {method!r}")
    return GARMENT_STEPS[kind]


def _garment_kind(item_id: str) -> str:
    """The garment kind of an item: ``garment.kind`` of a garment item, or
    ``clothing`` for an own-mesh outfit piece (``garment_set``). Ownership is
    checked by the caller (``garments._item``)."""
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    if garment_set.garment_kind_of(item) == garment_set.CLOTHING:
        return garment_set.CLOTHING
    kind = str((item.get("garment") or {}).get("kind") or "")
    if item.get("category") != "garment" or kind not in GARMENT_VERSION:
        raise ValueError(f"{item_id!r} is no garment item of a known kind")
    return kind


def garment_method(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> str:
    """``kind_method`` of a garment item. ValueError when ``item_id`` is no
    garment of a known kind."""
    kind = _garment_kind(item_id)
    return kind_method(kind, character_name, _profile_of(character_name, profile))


def hairdeck_backend_params(character_name: str) -> Dict[str, Any]:
    """The ``extra_params`` of the backend the ``hair_mesh`` occasion is meant
    to run on for the character (``routing.intended_backend``: configuration
    only, so a cooldown never changes it); {} when there is none."""
    from app.imagegen import routing, service
    pool = getattr(service.get_image_service(), "pool", None)
    if pool is None:
        return {}
    try:
        backend = routing.intended_backend("hair_mesh", character_name, pool=pool)
    except Exception:  # noqa: BLE001 — a fingerprint never fails on the routing config
        logger.exception("HairDeck backend of %s unresolvable", character_name)
        return {}
    params = getattr(backend, "extra_params", None) if backend is not None else None
    return dict(params) if isinstance(params, dict) else {}


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


def _edit_payload(character_name: str, item_id: str, kind: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The edit-chain fingerprint payload (R10)."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    bsig = base_body.base_signature(character_name, profile=profile)
    images = {view: base_body.file_sha256(find_ref_image(character_name, base_body._kind(view), bsig))
              for view in GARMENT_VIEWS}
    return {"kind": kind, **_kind_inputs(kind, character_name, profile, item_id),
            "version": GARMENT_VERSION[kind], "bsig": bsig, "base_images": images}


def _md5(payload: Dict[str, Any]) -> str:
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return digest.hexdigest()[:12]


def image_fsig(character_name: str, item_id: str, *,
               profile: Optional[Dict[str, Any]] = None) -> str:
    """The fsig the item's IMAGE steps are stored under: the edit-chain fsig
    for the subtract method (its haired views are the edit chain's own),
    ``garment_fsig`` otherwise. ValueError like ``garment_fsig``."""
    kind = _garment_kind(item_id)
    profile = _profile_of(character_name, profile)
    if kind_method(kind, character_name, profile) == SUBTRACT:
        return _md5(_edit_payload(character_name, item_id, kind, profile))
    return garment_fsig(character_name, item_id, profile=profile)


def haired_shas(character_name: str, item_id: str, ifsig: str) -> Dict[str, str]:
    """view -> sha256 of the ACCEPTED haired view under ``ifsig`` ("" when
    there is none)."""
    from app.core import base_body
    out: Dict[str, str] = {}
    for view in GARMENT_VIEWS:
        path = garment_path(character_name, item_id, ifsig, "image", step="haired", view=view)
        accepted = path.is_file() and read_record(path.with_suffix(".json")).get("accepted") is True
        out[view] = base_body.file_sha256(path) if accepted else ""
    return out


def subtract_ssig(character_name: str, item_id: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over the accepted haired views' sha256 (always those of the
    edit-chain fsig — whatever method is selected now) and ``SOURCE_VERSION``
    — names the hair source mesh folder (``source_dir``)."""
    kind = _garment_kind(item_id)
    profile = _profile_of(character_name, profile)
    ifsig = _md5(_edit_payload(character_name, item_id, kind, profile))
    return _md5({"haired": haired_shas(character_name, item_id, ifsig), "version": SOURCE_VERSION})


def garment_fsig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over ``{kind, <kind inputs>, version, bsig, base_images}``
    (R10); hair made by HairDeck adds ``{method, hsig, colour, placement}``
    (the colour override, "" = automatic; the manual placement
    ``garment_hair.hair_placement``, None = automatic); hair made by
    subtraction adds ``{method, haired, base_model, shape, shell_mm,
    cut_version}`` (module docstring). ValueError when ``item_id`` is no
    garment of a known kind."""
    kind = _garment_kind(item_id)
    profile = _profile_of(character_name, profile)
    payload = _edit_payload(character_name, item_id, kind, profile)
    method = kind_method(kind, character_name, profile)
    if method == HAIRDECK:
        from app.core import garment_hair
        payload.update(method=HAIRDECK, hsig=garment_hsig(character_name, item_id, profile=profile),
                       colour=garment_hair.hair_colour_override(profile),
                       placement=garment_hair.hair_placement(profile))
    elif method == SUBTRACT:
        from app.core import base_body, garment_cut, garment_hair
        base = base_body.current_base(character_name, profile=profile)
        payload.update(method=SUBTRACT, haired=haired_shas(character_name, item_id, _md5(payload)),
                       base_model=base[1] if base else "",
                       shape=garment_hair.subtract_shape(character_name, profile=profile),
                       shell_mm=garment_hair.shell_mm(profile), cut_version=garment_cut.CUT_VERSION)
    return _md5(payload)


def fit_method(record: Dict[str, Any]) -> str:
    """The method a fit record was made with; a record without ``method``
    (every fit from before HairDeck) is an edit-chain fit."""
    return str(record.get("method") or EDIT_CHAIN)


# --- Records ------------------------------------------------------------------

def read_record(path: Path) -> Dict[str, Any]:
    """A sidecar's JSON object, {} when missing, unreadable or not an object."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_record(path: Path, record: Dict[str, Any]) -> None:
    """Write a sidecar atomically (temp file in the same folder + replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _accepted_on(record: Dict[str, Any], base_model_sha: str) -> bool:
    return record.get("accepted") is True and record.get("base_model_sha256") == base_model_sha


def accepted_fit(character_name: str, item_id: str, *, base_model_sha: str,
                 profile: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """The fit to serve for a garment item on the base model ``base_model_sha``
    (R11): the current-fsig fit when its record is accepted on that model,
    else the newest (GLB mtime) accepted fit of the item on that model made
    with the CURRENT method (``fit_method``; a switched method never serves
    the other method's hair), else None. An empty ``base_model_sha`` (no base
    model) has no fit."""
    if not base_model_sha:
        return None
    profile = _profile_of(character_name, profile)
    try:
        current: Optional[str] = garment_fsig(character_name, item_id, profile=profile)
        method = garment_method(character_name, item_id, profile=profile)
    except ValueError:
        current, method = None, EDIT_CHAIN
    if current is not None:
        path = garment_path(character_name, item_id, current, "fit")
        record = read_record(path.with_suffix(".json"))
        if path.is_file() and _accepted_on(record, base_model_sha):
            return path, record
    return newest_accepted_fits(character_name, item_id, base_model_sha=base_model_sha).get(method)


def newest_accepted_fits(character_name: str, item_id: str, *,
                         base_model_sha: str = "") -> Dict[str, Tuple[Path, Dict[str, Any]]]:
    """method -> ``(fit GLB, record)`` of the item's newest (GLB mtime)
    accepted fit made with that method (``fit_method``); with
    ``base_model_sha`` only fits accepted on that base model. Read-only:
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
            if record.get("accepted") is not True:
                continue
            if base_model_sha and not _accepted_on(record, base_model_sha):
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
                   base_model_sha: str = "") -> None:
    """Persist the failure of a chain run of ``(item_id, fsig)``."""
    from app.core.timeutils import utc_now
    path = garment_path(character_name, item_id, fsig, "failed")
    if not path.parent.parent.parent.is_dir():
        return  # never mint the folders of a vanished character
    record = {"item_id": item_id, "fsig": fsig, "step": step, "error": error,
              "base_model_sha256": base_model_sha, "failed_at": _iso(utc_now())}
    if step == "fit":
        # Refused by a fit that already widens a too-small piece (``garment_refit`` retries one without).
        from app.core.garment_fit import SCALE_RETRY_VERSION
        record["scale_retry"] = SCALE_RETRY_VERSION
    write_record(path, record)


def record_body_failure(character_name: str, item_id: str, fsig: str, body: str, *, error: str,
                        body_sha: str, base_fit_sha: str, fit_version: Any) -> None:
    """Persist a refused (or failed) fit of ``(item_id, fsig)`` on the outfit
    body ``body``: automatic fits on that body skip it while the body, the
    base fit it was derived from and the fit algorithm are the same
    (``body_failure``)."""
    from app.core.garment_fit import SCALE_RETRY_VERSION
    from app.core.timeutils import utc_now
    from app.models.character import get_character_dir
    if not get_character_dir(character_name).is_dir():
        return  # never mint the folders of a vanished character
    write_record(garment_path(character_name, item_id, fsig, "failed", body=body),
                 {"item_id": item_id, "fsig": fsig, "step": "fit", "error": error, "body_id": body,
                  "body_sha256": body_sha, "base_fit_sha256": base_fit_sha, "fit_version": fit_version,
                  "scale_retry": SCALE_RETRY_VERSION, "failed_at": _iso(utc_now())})


def body_failure(character_name: str, item_id: str, fsig: str, body: str, *, body_sha: str,
                 base_fit_sha: str, fit_version: Any) -> Optional[Dict[str, Any]]:
    """The persisted failure of a fit of ``(item_id, fsig)`` on the outfit
    body ``body`` that still holds: recorded on the same body
    (``body_sha``), from the same base fit (``base_fit_sha``) by the same fit
    algorithm (``fit_version``). None otherwise."""
    try:
        record = read_record(garment_path(character_name, item_id, fsig, "failed", body=body))
    except ValueError:
        return None
    if (not record.get("error") or record.get("body_sha256") != body_sha
            or record.get("base_fit_sha256") != base_fit_sha or record.get("fit_version") != fit_version):
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
    if record.get("step") == "fit" and record.get("base_model_sha256") != base_model_sha:
        return None
    return record


# --- Run status (in memory) ---------------------------------------------------

_status_lock = threading.Lock()
_running: Dict[Tuple[str, str], Tuple[str, datetime]] = {}
_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}
# One garment run per character at a time: the steps of one garment build on
# each other, and two items of one character share its base files.
_char_locks: Dict[str, threading.Lock] = {}


def char_lock(character_name: str) -> threading.Lock:
    """The lock a garment run of this character holds."""
    with _status_lock:
        return _char_locks.setdefault(character_name, threading.Lock())


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
