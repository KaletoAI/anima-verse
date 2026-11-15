"""Full-body reference images — the picture the A-pose front is an edit of
(Ruling A87; corrects A74b, where the plain body's front was an edit of the
profile portrait itself).

The user, 2026-11-15: "Aus dem Profilbild wird ein Ganzkörperbild (mit allen
Attributen) erzeugt. Dieses ist die Referenz." — a dedicated FULL-BODY picture
of the character, made from the profile image and carrying all of the
character's attributes, is the basis of the A-pose:

* the PLAIN BODY's full-body reference (one per character): the base front is
  an edit of it while it is set (``base_body.front_source_image``), else of the
  profile image as before, else the text render;
* an OUTFIT's full-body reference (one per outfit — the worn combination,
  ``outfit_references.outfit_key``): stored in A74b's per-outfit records; the
  dressed front is an edit of it while something is painted on the figure.

Each is an optional step: GENERATE (the primary path), pick a gallery picture or
upload one, clear. Nothing else ever generates one — Run all and the Build only
show that there is none.

GENERATION follows the user's validated hub job 5086b496 (profile image →
full-body reference; its output was then the input of the A-pose edit c265fd78):
an img2img EDIT of the appearance picture whose prompt is the character's
attribute block between a framing clause and one light/finish sentence (use
cases ``base_reference`` / ``outfit_reference``, Ruling A95, the shape the user
validated on 2026-11-15: ``"Full body shot from head to feet inside the frame,
{character}, neutral studio lighting, plain clean background, photorealistic,
high detail"``) — no edit prefix, no pose words.

* The attribute block is THE person description of every image prompt
  (``prompt_builder.person_description``: the appearance tokens resolved and the
  body slots), in the neutral state (no state modifier), plus the height phrase
  when the appearance does not carry it (the rule of ``base_body.base_appearance``).
  It is the ORDINARY image description, never the mesh-input one (Ruling A93): the
  reference is an appearance picture — no mesh-input line is added (the front's
  pose text places the hair itself, ``TPOSE_FRONT_HAIR_CLAUSE``). But a slot that
  declares a ``mesh_part`` names nothing here and its LoRAs are dropped, whether
  its switch is on or off (Ruling A93b — a clean mesh cannot be made from a
  reference that shows it; ``person_description(appearance_reference=True)``,
  ``body_slots.filter_appearance_reference_loras``). While it is uncovered the
  slot's ``mesh_part.reference_prompt`` says what the region shows instead, and
  its ``reference_negative`` joins the negative (Ruling A95,
  ``body_slots.appearance_reference_negative``) — the package words both. The occasions stay mesh-input
  occasions for the tpose LoRAs and the unfolded negative
  (``imagegen.occasions.APPEARANCE_REFERENCE_OCCASIONS``).
* Plain body (``base_block``): the description of the UNDRESSED figure (nothing
  worn), hair included — the attribute block alone, as in the chain the user
  validated (Ruling A87b). The plain body's head and body state belong to the
  A-pose edit (step 2, ``base_body.edit_character``), which carries them.
  Negative: the use case's (``_NEG_REFERENCE``: picture quality and framing
  only, no pose terms) plus ``BASE_NEGATIVE`` (nothing worn) and the mesh-part
  slots' reference negatives (Ruling A95).
* Outfit (``outfit_block``): the description of the figure as dressed in the
  outfit, then "wearing" and the outfit's pieces (``outfit_renderer.render_outfit``:
  their prompt fragments). Appearance picture: the plain body's full-body
  reference when set, else the profile image.
* Occasions ``base_reference`` / ``outfit_reference`` (``imagegen.occasions``):
  a backend that cannot slot the reference is not applicable
  (``require_reference``), an empty chain is no route (``requires_chain``) —
  never the cheapest or a cloud backend. One render = one image job; no retry
  loop of its own.
* The result is stored in the character's GALLERY (as an upload is) with its
  prompt (``add_character_image_prompt``) and recorded by name + content sha:
  the plain body's in the profile key ``full_body_reference``, an outfit's in
  ``outfit_references`` under the outfit worn when the click happened. Never a
  file in ``model_refs`` (every name there is parsed as a signature).

RECORD: ``{image, sha256, set_at, origin ("generated" | "gallery" | "upload"),
prompt (the prompt it was generated with, "" otherwise), made_from ({image,
sha256, kind ("profile" | "full_body")} of the picture it was generated from)}``.

FRESHNESS: a new, changed or cleared plain-body reference makes the base front
OUTDATED (``base_body.front_reference_state``, its own reasons) — re-rendered
only by a click (the front's Regenerate, Run all, a Build you start), as A74b's
reference axis. Without a full-body reference the front record stays A74b's,
byte for byte: nothing turns due because this exists.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("full_body_reference")

#: The profile key of the plain body's record.
PROFILE_KEY = "full_body_reference"
#: Occasions and use cases (``imagegen.occasions`` / ``config``).
BASE_OCCASION = "base_reference"
OUTFIT_OCCASION = "outfit_reference"
BASE_USE_CASE = "base_reference"
OUTFIT_USE_CASE = "outfit_reference"
#: Image jobs of one Generate (one render, no retry loop).
GENERATE_JOBS = 1
#: The record's ``origin``.
ORIGIN_GENERATED = "generated"
ORIGIN_GALLERY = "gallery"
ORIGIN_UPLOAD = "upload"
#: ``made_from["kind"]``.
FROM_PROFILE = "profile"
FROM_FULL_BODY = "full_body"
#: Slot of the plain body's run state (an outfit's slot is its outfit key).
BASE_SLOT = "base"

#: Why Generate cannot run (409 of the routes; the tile shows it beside the disabled button).
NO_PROFILE_IMAGE = "No profile image — set one: the full-body reference is generated from it"
NO_APPEARANCE_PICTURE = ("No profile image and no full-body reference of the plain body — set one: the outfit's "
                         "full-body reference is generated from it")
ALREADY_RUNNING = "A full-body reference is being generated for this character"
NOT_HUMANOID = "The full-body reference is for humanoid characters only"
#: The tile's notes on what a generation is made from.
FROM_PROFILE_NOTE = "Generated from the profile image"
FROM_FULL_BODY_NOTE = "Generated from the plain body's full-body reference"
#: A plain-body reference generated from another profile image than the current one.
OTHER_PROFILE_NOTE = "Generated from another profile image — Generate makes it from the current one"


# --- Records -----------------------------------------------------------------------------------------------------

def _valid(record: Any) -> bool:
    return (isinstance(record, dict) and isinstance(record.get("image"), str) and bool(record["image"])
            and Path(record["image"]).name == record["image"] and isinstance(record.get("sha256"), str)
            and bool(record["sha256"]))


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def base_record(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The plain body's record, None without one."""
    record = _profile_of(character_name, profile).get(PROFILE_KEY)
    return dict(record) if _valid(record) else None


def gallery_path(character_name: str, image: str) -> Optional[Path]:
    """The gallery file ``image`` of the character, None when it is gone or outside the gallery."""
    from app.core import outfit_references
    return outfit_references.image_path(character_name, {"image": image, "sha256": "-"})


def base_image(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """The plain body's full-body reference file — None without a record or when its picture is gone from the
    gallery (the front then falls back to the profile image; the tile says the picture is gone)."""
    record = base_record(character_name, profile=profile)
    return gallery_path(character_name, record["image"]) if record else None


def _gallery_checked(character_name: str, image: str) -> Tuple[Path, bytes]:
    """``(path, bytes)`` of a gallery picture to record; ValueError for a name outside the gallery, a missing
    file or bytes that are no image."""
    from app.core.upload_limits import ensure_image
    name = str(image or "").strip()
    if not name or Path(name).name != name:
        raise ValueError("Pick a picture of the character's gallery")
    path = gallery_path(character_name, name)
    if path is None:
        raise ValueError(f"Not in the gallery: {name}")
    data = path.read_bytes()
    try:
        ensure_image(data, filename=name, what="Reference image")
    except Exception as e:  # HTTPException of the upload helpers
        raise ValueError(f"Not an image: {name}") from e
    return path, data


def _record(image: str, data: bytes, origin: str, prompt: str = "",
            made_from: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.core.timeutils import utc_now_iso
    record = {"image": image, "sha256": hashlib.sha256(data).hexdigest(), "set_at": utc_now_iso(),
              "origin": origin, "prompt": prompt}
    if made_from:
        record["made_from"] = dict(made_from)
    return record


def _invalidate() -> None:
    """A reference changes what the fronts are made from: drop the memoised figures."""
    from app.core import figure
    figure.invalidate()


def set_base(character_name: str, image: str, *, origin: str = ORIGIN_GALLERY, prompt: str = "",
             made_from: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record the gallery picture ``image`` as the plain body's full-body reference. Saves only — the front then
    shows as outdated with its cost; nothing renders. ValueError for a picture that is not in the gallery or no
    image; RuntimeError when the profile was not saved. Returns the record."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    _path, data = _gallery_checked(character_name, image)
    record = _record(image, data, origin, prompt, made_from)
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        profile[PROFILE_KEY] = record
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The full-body reference was not saved")
    _invalidate()
    logger.info("Full-body reference of %s (plain body, %s): %s", character_name, origin, image)
    return record


def clear_base(character_name: str) -> bool:
    """Drop the plain body's full-body reference (the picture stays in the gallery). Saves only. False when there
    was none; RuntimeError when the profile was not saved."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        if PROFILE_KEY not in profile:
            return False
        profile.pop(PROFILE_KEY, None)
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The full-body reference was not cleared")
    _invalidate()
    logger.info("Full-body reference of %s (plain body) cleared", character_name)
    return True


def set_outfit(character_name: str, image: str, *, key: Optional[str] = None,
               pieces: Optional[Dict[str, str]] = None, origin: str = ORIGIN_GALLERY, prompt: str = "",
               made_from: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record ``image`` as the full-body reference of an outfit — the one worn now, or ``key`` (with its
    ``pieces`` for the label) when a generation started for an outfit that may not be worn any more. A74b's
    storage (``outfit_references``). Saves only. Returns ``{key, record}``."""
    from app.core import outfit_references
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    _path, data = _gallery_checked(character_name, image)
    record = _record(image, data, origin, prompt, made_from)
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        if key is None:
            pieces, open_ids = outfit_references._worn(character_name, profile)
            key = outfit_references.outfit_key(pieces, open_ids)
        record["label"] = outfit_references._label(character_name, dict(pieces or {}))
        records = outfit_references.references_of(character_name, profile=profile)
        records[key] = record
        profile[outfit_references.PROFILE_KEY] = records
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The reference was not saved")
    _invalidate()
    logger.info("Full-body reference of %s (outfit %s, %s): %s", character_name, key, origin, image)
    return {"key": key, "record": record}


def store_in_gallery(character_name: str, data: bytes, suffix: str, tag: str = "fullbody") -> str:
    """Bytes (an upload already capped and checked by its route, or a generated picture) into the character's
    gallery as ``<name>_<stamp>_<tag><suffix>``. Returns the file name."""
    import time
    from app.models.character import add_character_image, get_character_images_dir
    suffix = (suffix or "").lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("Format not supported — PNG, JPEG or WebP")
    images = get_character_images_dir(character_name)
    images.mkdir(parents=True, exist_ok=True)
    stem = f"{character_name}_{int(time.time())}_{tag}"
    target = images / f"{stem}{suffix}"
    n = 1
    while target.exists():
        n += 1
        target = images / f"{stem}{n}{suffix}"
    target.write_bytes(data)
    add_character_image(character_name, target.name)
    return target.name


# --- The prompts -------------------------------------------------------------------------------------------------

def _attributes(character_name: str, profile: Dict[str, Any]) -> str:
    """THE person description of the image prompts (``person_description``) of ``profile`` as it is (its worn
    pieces decide which body-slot texts show), neutral (no state modifier), plus the height phrase when the
    description does not carry it (``base_body.base_appearance``'s rule). The ordinary description, not the
    mesh-input one (Ruling A93), without the mesh-part slots (A93b, module docstring)."""
    from app.core.height import height_phrase
    from app.core.prompt_builder import person_description
    text = person_description(character_name, apply_state_modifiers=False, mesh_input=False, body_profile=profile,
                              neutral_state=True, appearance_reference=True)
    height = height_phrase(profile, character_name)
    if height and height not in text:
        text = ", ".join(p for p in (text, height) if p)
    return text


def _undressed(profile: Dict[str, Any]) -> Dict[str, Any]:
    bare = deepcopy(profile)
    bare["equipped_pieces"] = {}
    bare["equipped_items"] = []
    return bare


def base_block(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The plain body's attribute block (module docstring): the undressed figure's description, hair included —
    no body-state words (the A-pose edit carries those)."""
    profile = _profile_of(character_name, profile)
    return _attributes(character_name, _undressed(profile))


def outfit_block(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The outfit's attribute block: the description of the figure dressed as now, then "wearing" and the worn
    pieces' prompt fragments (``render_outfit``, as the T-pose reference names them); held items are no part of
    an outfit (``outfit_references``)."""
    from app.core.outfit_renderer import render_outfit
    profile = _profile_of(character_name, profile)
    pieces = dict(profile.get("equipped_pieces") or {})
    dressed = deepcopy(profile)
    dressed["equipped_items"] = []
    attributes = _attributes(character_name, dressed)
    worn = (render_outfit(profile=dressed, character_name=character_name, equipped_pieces=pieces,
                          equipped_items=[], mesh_input=False).get("pieces") or "").strip()
    return ", ".join(p for p in (attributes, f"wearing {worn}" if worn else "") if p)


#: What the plain body's reference adds to the use case's negative: it wears nothing (Ruling A95).
BASE_NEGATIVE = "clothing, underwear, jewellery"


def reference_negative(character_name: str, render_profile: Dict[str, Any], *, base: bool) -> str:
    """The extra negative of a full-body reference (Ruling A95): ``BASE_NEGATIVE`` for the plain body, then the
    mesh-part slots' reference negatives of the figure as rendered."""
    from app.core.body_slots import appearance_reference_negative
    parts = [BASE_NEGATIVE if base else "", appearance_reference_negative(character_name, profile=render_profile)]
    return ", ".join(p for p in parts if p)


def backend_variants(character_name: str, render_profile: Dict[str, Any], block_of, negative_of
                     ) -> Optional[Dict[str, Any]]:
    """The payload ``backend_variants`` of a full-body reference (Ruling A103): when a mesh-part slot of the
    figure declares per-backend reference texts, ``{keys, variants}`` with one variant per combination of the
    texts' entries (the base included) — ``block_of()`` / ``negative_of()`` built under that choice
    (``body_slots.reference_backend_choice``) as ``style_character`` / ``negative_prompt_extra``. The image
    service picks the variant of the backend that renders (``service.apply_backend_variant``). None without
    any."""
    from itertools import product
    from app.core.body_slots import reference_backend_choice, reference_backend_keys
    keys = reference_backend_keys(character_name, profile=render_profile)
    if not keys:
        return None
    variants = []
    for choice in product(*[range(-1, len(key["match"])) for key in keys]):
        picked = {(key["slot"], key["field"]): index for key, index in zip(keys, choice) if index >= 0}
        with reference_backend_choice(picked):
            variants.append({"choice": list(choice), "style_character": block_of(),
                             "negative_prompt_extra": negative_of()})
    return {"keys": [{"slot": k["slot"], "field": k["field"], "match": k["match"]} for k in keys],
            "variants": variants}


def compose(use_case: str, block: str) -> str:
    """The prompt a Generate sends (before LoRA triggers): the use case's style with ``block`` in its
    ``{character}`` slot — what the tile shows before the click."""
    from app.core import config
    style = config.get_use_case_prompts(use_case, "natural", clothed=False, character=block)["prompt_style"]
    return config.join_style_prompt(style, "", block)


# --- Generating --------------------------------------------------------------------------------------------------

_lock = threading.Lock()
_running: Dict[Tuple[str, str], str] = {}          # (character, slot) -> SYSTEM stamp of the start
_failed: Dict[Tuple[str, str], Dict[str, str]] = {}  # (character, slot) -> {error, failed_at}


def run_state(character_name: str, slot: str) -> Dict[str, Any]:
    """``{running, started_at, error, failed_at}`` of the plain body's (``BASE_SLOT``) or an outfit's (its key)
    generation — in memory."""
    with _lock:
        started = _running.get((character_name, slot))
        failure = dict(_failed.get((character_name, slot)) or {})
    return {"running": started is not None, "started_at": started or None,
            "error": failure.get("error") or None, "failed_at": failure.get("failed_at") or None}


def _reserve(character_name: str, slot: str) -> None:
    from app.core.timeutils import utc_now_iso
    with _lock:
        if any(c == character_name for c, _s in _running):
            raise RuntimeError(ALREADY_RUNNING)
        _running[(character_name, slot)] = utc_now_iso()
        _failed.pop((character_name, slot), None)


def _release(character_name: str, slot: str, error: Optional[str]) -> None:
    from app.core.timeutils import utc_now_iso
    with _lock:
        _running.pop((character_name, slot), None)
        if error:
            _failed[(character_name, slot)] = {"error": error, "failed_at": utc_now_iso()}


def _render(character_name: str, *, occasion: str, use_case: str, block: str, source: Path,
            render_profile: Dict[str, Any], extra_negative: str,
            variants: Optional[Dict[str, Any]] = None) -> Tuple[bytes, str, str, str]:
    """One edit of ``source`` (frozen for the run inside ``model_refs``, as the base front's) with ``block`` in the
    use case's slot. Returns ``(image bytes, suffix, prompt sent, sha256 of the source)``; RuntimeError when the
    render delivered nothing."""
    from app.core import base_body, expression_regen
    from app.core.model_refs import _tpose_size, get_model_refs_dir
    refs_dir = get_model_refs_dir(character_name)
    refs_dir.mkdir(parents=True, exist_ok=True)
    width, height = _tpose_size()
    with base_body._frozen_reference(source, refs_dir) as (frozen, source_sha), \
            tempfile.TemporaryDirectory(prefix=".fullbody_", dir=refs_dir, ignore_cleanup_errors=True) as staging:
        stem = Path(staging) / "reference"
        path = expression_regen.render_character_image(
            character_name,
            output_stem=stem,
            equipped_pieces=dict(render_profile.get("equipped_pieces") or {}), equipped_items=[],
            pose_prompt="", expression_prompt="",
            bare_prompt="", extra_negative=extra_negative,
            image_use_case=use_case, style_character=block, occasion=occasion,
            override_width=width, override_height=height,
            apply_state_modifiers=False, mesh_input_profile=render_profile,
            reference_image=frozen, require_reference=True,
            # The character's identity/pose LoRAs as on the fronts (tpose_loras), no slot LoRA.
            character_loras=True,
            # A reference picture as the backend delivered it: no matte, no trim.
            postprocess=False,
            # Per-backend block/negative (Ruling A103); the sidecar's prompt is the one really sent.
            backend_variants=variants)
        if not path or not Path(path).is_file():
            raise RuntimeError("The render delivered no picture")
        path = Path(path)
        try:
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        prompt = str(meta.get("final_prompt") or meta.get("prompt") or compose(use_case, block))
        return path.read_bytes(), path.suffix, prompt, source_sha


def _publish(character_name: str, data: bytes, suffix: str, prompt: str) -> str:
    """The generated picture into the gallery with its prompt; returns its file name."""
    from app.models.character import add_character_image_prompt
    name = store_in_gallery(character_name, data, suffix if suffix else ".png")
    try:
        add_character_image_prompt(character_name, name, prompt)
    except Exception:  # noqa: BLE001 — the prompt line is a convenience, the record keeps the prompt too
        logger.debug("Prompt of %s not recorded in the gallery meta", name, exc_info=True)
    return name


def check_base(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Path]:
    """``(profile, profile image)`` when the plain body's reference can be generated; ValueError for a
    non-humanoid, ``base_body.MissingInput`` without a profile image."""
    from app.core import base_body
    from app.core.model_refs import current_profile_image, is_humanoid
    profile = _profile_of(character_name, profile)
    if not is_humanoid(character_name, profile=profile):
        raise ValueError(NOT_HUMANOID)
    image = current_profile_image(character_name, profile=profile)
    if image is None:
        raise base_body.MissingInput(NO_PROFILE_IMAGE)
    return profile, image


def generate_base(character_name: str, *, reserved: bool = False) -> Dict[str, Any]:
    """Generate the plain body's full-body reference from the profile image (module docstring) and record it.
    Blocking — call from a worker thread. Returns the record."""
    if not reserved:
        _reserve(character_name, BASE_SLOT)
    error: Optional[str] = None
    try:
        profile, image = check_base(character_name)
        block = base_block(character_name, profile=profile)
        negative = reference_negative(character_name, _undressed(profile), base=True)
        variants = backend_variants(
            character_name, _undressed(profile), lambda: base_block(character_name, profile=profile),
            lambda: reference_negative(character_name, _undressed(profile), base=True))
        data, suffix, prompt, source_sha = _render(
            character_name, occasion=BASE_OCCASION, use_case=BASE_USE_CASE, block=block, source=image,
            render_profile=_undressed(profile), extra_negative=negative, variants=variants)
        name = _publish(character_name, data, suffix, prompt)
        return set_base(character_name, name, origin=ORIGIN_GENERATED, prompt=prompt,
                        made_from={"image": image.name, "sha256": source_sha, "kind": FROM_PROFILE})
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        _release(character_name, BASE_SLOT, error)


def outfit_source(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                  ) -> Tuple[Optional[Path], str]:
    """``(picture, kind)`` an outfit's reference is generated from: the plain body's full-body reference, else the
    profile image; ``(None, "")`` without either."""
    from app.core.model_refs import current_profile_image
    profile = _profile_of(character_name, profile)
    full_body = base_image(character_name, profile=profile)
    if full_body is not None:
        return full_body, FROM_FULL_BODY
    image = current_profile_image(character_name, profile=profile)
    return (image, FROM_PROFILE) if image is not None else (None, "")


def generate_outfit(character_name: str, *, key: Optional[str] = None, reserved: bool = False) -> Dict[str, Any]:
    """Generate the full-body reference of the outfit worn now (module docstring) and record it under that
    outfit's key — the one worn when this started, even when another is worn by the time it is done. Blocking.
    Returns ``{key, record}``."""
    from app.core import outfit_references
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    pieces, open_ids = outfit_references._worn(character_name, profile)
    key = key or outfit_references.outfit_key(pieces, open_ids)
    if not reserved:
        _reserve(character_name, key)
    error: Optional[str] = None
    try:
        if not is_humanoid(character_name, profile=profile):
            raise ValueError(NOT_HUMANOID)
        source, kind = outfit_source(character_name, profile=profile)
        if source is None:
            from app.core import base_body
            raise base_body.MissingInput(NO_APPEARANCE_PICTURE)
        block = outfit_block(character_name, profile=profile)
        worn = {**profile, "equipped_items": []}
        variants = backend_variants(
            character_name, worn, lambda: outfit_block(character_name, profile=profile),
            lambda: reference_negative(character_name, worn, base=False))
        data, suffix, prompt, source_sha = _render(
            character_name, occasion=OUTFIT_OCCASION, use_case=OUTFIT_USE_CASE, block=block, source=source,
            render_profile=worn, extra_negative=reference_negative(character_name, worn, base=False),
            variants=variants)
        name = _publish(character_name, data, suffix, prompt)
        return set_outfit(character_name, name, key=key, pieces=pieces, origin=ORIGIN_GENERATED, prompt=prompt,
                          made_from={"image": source.name, "sha256": source_sha, "kind": kind})
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        _release(character_name, key, error)


def _start(character_name: str, slot: str, run) -> None:
    """Reserve ``slot`` now (the tile polls the run state from the click on) and run in a worker thread."""
    _reserve(character_name, slot)

    def work() -> None:
        try:
            run()
        except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
            logger.warning("Full-body reference of %s (%s) failed: %s", character_name, slot, e)

    threading.Thread(target=work, daemon=True, name=f"full-body-ref-{character_name}").start()


def start_base(character_name: str) -> None:
    """Check, then generate the plain body's reference in a worker thread. ValueError / MissingInput /
    RuntimeError (``ALREADY_RUNNING``) before anything starts."""
    check_base(character_name)
    _start(character_name, BASE_SLOT, lambda: generate_base(character_name, reserved=True))


def start_outfit(character_name: str) -> str:
    """Check, then generate the worn outfit's reference in a worker thread; returns its outfit key."""
    from app.core import base_body, outfit_references
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    if not is_humanoid(character_name, profile=profile):
        raise ValueError(NOT_HUMANOID)
    if outfit_source(character_name, profile=profile)[0] is None:
        raise base_body.MissingInput(NO_APPEARANCE_PICTURE)
    pieces, open_ids = outfit_references._worn(character_name, profile)
    key = outfit_references.outfit_key(pieces, open_ids)
    _start(character_name, key, lambda: generate_outfit(character_name, key=key, reserved=True))
    return key


# --- The tiles ---------------------------------------------------------------------------------------------------

def _url(character_name: str, path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return ""
    return f"/characters/{quote(character_name, safe='')}/images/{quote(path.name, safe='')}?v={stamp}"


def _public(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not record:
        return None
    keys = ("image", "sha256", "set_at", "origin", "prompt", "made_from", "label")
    return {k: record.get(k) for k in keys if k in record}


def base_tile(character_name: str) -> Dict[str, Any]:
    """The Base body tab's "Full-body reference" tile (``GET …/base-body/full-body-reference``):
    ``{kind "base", record, url, gone, run {running, started_at, error, failed_at}, generate {jobs, ready,
    blocked, source, source_url, prompt}, made_from_current, note, front {current, reason, source}}`` —
    ``generate.prompt`` is what a Generate sends now (before LoRA triggers); ``front``: whether the stored front
    is made from what it is made from now (``base_body.front_reference_state``)."""
    from app.core import base_body
    from app.core.model_refs import current_profile_image
    profile = _profile_of(character_name, None)
    record = base_record(character_name, profile=profile)
    path = gallery_path(character_name, record["image"]) if record else None
    image = current_profile_image(character_name, profile=profile)
    blocked = "" if image is not None else NO_PROFILE_IMAGE
    try:
        prompt = compose(BASE_USE_CASE, base_block(character_name, profile=profile))
    except Exception:  # noqa: BLE001 — the tile never breaks the poll
        logger.exception("Full-body reference prompt of %s failed", character_name)
        prompt = ""
    made_from = (record or {}).get("made_from") or {}
    made_from_current = True
    if record and made_from.get("kind") == FROM_PROFILE:
        made_from_current = (image is not None and image.name == made_from.get("image")
                             and base_body.file_sha256(image) == made_from.get("sha256"))
    front: Dict[str, Any] = {}
    try:
        state = base_body.front_reference_state(character_name, profile=profile)
        front = {"current": state["current"], "reason": state["reason"],
                 "stored": state["stored"] is not None,
                 "source": str(state["wanted"].get("source") or "")}
    except Exception:  # noqa: BLE001
        logger.exception("Front reference state of %s failed", character_name)
    note = ""
    if record and made_from.get("kind") == FROM_PROFILE:
        note = FROM_PROFILE_NOTE if made_from_current else OTHER_PROFILE_NOTE
    return {"kind": "base", "record": _public(record), "url": _url(character_name, path),
            "gone": bool(record) and path is None, "run": run_state(character_name, BASE_SLOT),
            "generate": {"jobs": GENERATE_JOBS, "ready": not blocked, "blocked": blocked,
                         "source": FROM_PROFILE if image is not None else "",
                         "source_url": _url(character_name, image), "prompt": prompt},
            "made_from_current": made_from_current, "note": note, "front": front}


def outfit_tile(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """``outfit_references.info`` with the Generate part of the tile: ``run``, ``generate {jobs, ready, blocked,
    source ("full_body" | "profile" | ""), source_url, prompt}``, ``followup_jobs`` (the image jobs of the dressed
    views a new reference makes due at the next Build — ``base_body.dressed_view_jobs`` while something is
    painted, 0 when the picture would not be used now), and the record's ``origin`` / ``prompt`` /
    ``made_from``."""
    from app.core import base_body
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    source, kind = outfit_source(character_name, profile=profile)
    try:
        prompt = compose(OUTFIT_USE_CASE, outfit_block(character_name, profile=profile))
    except Exception:  # noqa: BLE001 — the tile never breaks the poll
        logger.exception("Outfit full-body reference prompt of %s failed", character_name)
        prompt = ""
    info = dict(info)
    info["record"] = _public(info.get("record"))
    info["run"] = run_state(character_name, str(info.get("key") or ""))
    info["generate"] = {"jobs": GENERATE_JOBS, "ready": source is not None,
                        "blocked": "" if source is not None else NO_APPEARANCE_PICTURE,
                        "source": kind, "source_url": _url(character_name, source), "prompt": prompt}
    info["followup_jobs"] = base_body.dressed_view_jobs() if info.get("applies") else 0
    info["kind"] = "outfit"
    return info


def build_note(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What Run all and the Build show beside their plan (never a due step — they never generate one):
    ``{base: bool (the plain body has a full-body reference in its gallery), outfit: bool (the worn outfit has
    a record)}``."""
    from app.core import outfit_references
    profile = _profile_of(character_name, profile)
    base = base_image(character_name, profile=profile) is not None
    try:
        pieces, open_ids = outfit_references._worn(character_name, profile)
        outfit = outfit_references.record_for(character_name, pieces, open_ids, profile=profile) is not None
    except Exception:  # noqa: BLE001 — an information line, never a failure
        outfit = False
    return {"base": base, "outfit": outfit}
