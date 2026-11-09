"""Base body — the bald, unclothed A-pose figure of a humanoid character.

A humanoid character on the ``base_body`` model pipeline (profile field
``model_pipeline: "base_body"``) gets ONE base body: four A-pose views
(front/back/left/right) of a bald, anatomically neutral figure, rendered from
the character's profile image, and one model built from them. Outfits are
painted onto that body later (spec
``docs/superpowers/specs/2026-11-08-base-body-outfits-design.md`` § A).

This module holds the description, the view prompts with their negative, the
base signature that keys every stored base image and model, the rendering of
the four views (``generate_base_images``, the front through the hand-pose
gate of ``base_body_gates``), the rigged base model built from
them (``generate_base_model``), the per-character pipeline switch
(``set_pipeline``) and the UI info (``base_info``).

Outfits (spec § B, phase 3): every outfit combination of a character on the
pipeline gets two DRESSED images (``DRESSED_VIEWS``) — the front an edit of
the base front, the back a draft from the dressed front fitted onto the base
back (``generate_dressed_images``, ``dress_prompt`` / ``back_draft_prompt`` /
``FIT_PROMPT``) stored as the usual ``tpose[_back]_<sig>`` refs — and an
outfit model that is the rigged base
with the outfit painted on by the local GLBBodyRetexture worker
(``build_outfit_model``, base colour swapped by ``replace_base_color``).

What describes the body:

* gender and age through the template's ``character_appearance`` replacement
  tokens, in the ``"{gender}, {age} years old"`` phrasing World-Dev asks for;
* the ``always`` fragments of the body slots a species package flags
  ``base_body: true`` (human: eyes, skin, build — the build fragment carries
  the height phrase). Never the free-text ``character_appearance`` (it names
  clothes and hair), never hair, never a slot without the flag — anatomy
  packs stay out unless they opt in.

The pose texts are the mesh-input A-pose texts of ``app/core/model_refs.py``
(admin overrides included) with their hair clauses taken out: a bald figure
has no hair to keep off the chest or to match to the reference.
"""
import hashlib
import json
import re
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("base_body")

BASE_VIEWS = ("front", "back", "left", "right")
# Part of the signature: bump when the composition below changes in a way
# that must re-render every base body.
BASE_BODY_VERSION = 2

# Framing, head and body layers (wording verified in the S1 spike,
# claude-out/s1-base-body/src/bald_tpose.py).
FULL_FRAMING = ("full body shot from the top of the head to the soles of the feet, the entire figure inside the "
                "frame with empty margin above the head and below the feet")
BALD_HEAD = ("completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of "
             "the head fully visible, the ears fully visible, natural eyebrows")
BODY_TEXT = "a smooth, featureless mannequin-like body without anatomical detail, sfw, no clothing"

HAIR_NEGATIVE = ("hair, long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, "
                 "stubble on the scalp, hair on the shoulders, hair on the back")
BODY_NEGATIVE = "clothing, underwear, jewellery, detailed anatomy"
POSE_NEGATIVE = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, "
                 "feet cut off, cropped legs, close-up, portrait crop")
BASE_NEGATIVE = ", ".join((HAIR_NEGATIVE, BODY_NEGATIVE, POSE_NEGATIVE))

_HAIR_RE = re.compile(r"\bhair", re.IGNORECASE)
# The shape of ``base_signature`` — never an outfit signature (pure hex).
BASE_SIG_RE = re.compile(r"base[0-9a-f]{8}")


def is_base_signature(signature: Optional[str]) -> bool:
    """Whether a model/ref signature is a base-body one (by its shape)."""
    return bool(signature) and BASE_SIG_RE.fullmatch(signature) is not None


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _without_hair(text: str) -> str:
    """The pose text without its hair clauses. The shipped clauses go by exact
    text; an admin override that words hair differently loses every comma
    clause that mentions hair, and one without any keeps everything."""
    from app.core.model_refs import TPOSE_HAIR_CLAUSES
    for clause in TPOSE_HAIR_CLAUSES:
        text = text.replace(clause, "")
    segments = [seg.strip() for seg in (text or "").split(",")]
    return ", ".join(seg for seg in segments if seg and not _HAIR_RE.search(seg))


def _identity_words(profile: Dict[str, Any]) -> str:
    """Gender and age as the character's template renders them into the
    appearance tokens ({gender} -> "female", {age} -> "30")."""
    from app.models.character_template import build_replacement_map, get_template
    template = get_template(profile.get("template", "")) if profile.get("template") else None
    if not template:
        return ""
    tokens = build_replacement_map(template, profile, "character_appearance")
    parts = []
    if tokens.get("gender"):
        parts.append(tokens["gender"])
    if tokens.get("age"):
        parts.append(f"{tokens['age']} years old")
    return ", ".join(parts)


def base_appearance(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                    base_fragments: bool = True) -> str:
    """Gender/age words + height phrase + the ``always`` fragments of the
    character's body slots flagged ``base_body: true``, in slot order, then
    the ``base_body_prompt`` texts of every slot that applies to the
    character (``body_slots.base_body_fragments``, flag irrelevant) — left
    out with ``base_fragments=False`` (they describe the undressed body)."""
    profile = _profile_of(character_name, profile)
    from app.core.body_slots import base_body_fragments, prompt_fragments
    from app.core.height import height_phrase
    fragments = (prompt_fragments(character_name, profile=profile, base_body=True)["general"]
                 + (base_body_fragments(character_name, profile=profile) if base_fragments else []))
    parts = []
    identity = _identity_words(profile)
    if identity:
        parts.append(identity)
    # The human build slot carries the height ("{height}, {type} build"); only
    # when no flagged fragment rendered it does the phrase stand on its own.
    height = height_phrase(profile, character_name)
    if height and not any(height in fragment for fragment in fragments):
        parts.append(height)
    parts.extend(fragments)
    return ", ".join(parts)


def _pose_text(view: str) -> str:
    from app.core.model_refs import get_tpose_prompt, get_tpose_view_prompt
    return _without_hair(get_tpose_prompt() if view == "front" else get_tpose_view_prompt(view))


def base_negative(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                  head: str = BASE_NEGATIVE) -> str:
    """``BASE_NEGATIVE`` (or ``head``) plus the ``base_body_negative`` text of
    every body slot that applies to the character
    (``body_slots.slots_for_character``, in slot order; the ``base_body`` flag
    does not matter) — a package keeps what its slots describe out of the
    base views."""
    profile = _profile_of(character_name, profile)
    from app.core.body_slots import slots_for_character
    extra = [text for text in (str(getattr(spec, "base_body_negative", "") or "").strip()
                               for spec in slots_for_character(character_name, profile=profile)) if text]
    return ", ".join([head, *extra])


def base_prompt(character_name: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of one base-body view. Front and the extra
    views share the framing and body layers; a back view drops every facial
    segment of them (``prompt_builder.strip_face_terms``), like the outfit
    back view does — a facial word pulls the head around to the camera. The
    negative is ``base_negative`` (``BASE_NEGATIVE`` + the slots' texts)."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    return (_view_prompt(character_name, view, BODY_TEXT, profile=profile, base_fragments=True),
            base_negative(character_name, profile=profile))


def _view_prompt(character_name: str, view: str, body_text: str, *,
                 profile: Dict[str, Any], base_fragments: bool) -> str:
    """Pose text + framing + bald head + ``body_text`` + the appearance; a
    back view without its facial segments."""
    body = ", ".join(p for p in (BALD_HEAD, body_text,
                                 base_appearance(character_name, profile=profile,
                                                 base_fragments=base_fragments)) if p)
    if view == "back":
        from app.core.prompt_builder import strip_face_terms
        body = strip_face_terms(body)
    return ", ".join(p for p in (_pose_text(view), FULL_FRAMING, body) if p)


def base_signature(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """``"base" + 8 hex`` over everything that shapes the base body: the four
    view prompts and negatives, the current profile image (file name and
    size) and ``BASE_BODY_VERSION``."""
    profile = _profile_of(character_name, profile)
    from app.core.model_refs import current_profile_image
    image = current_profile_image(character_name, profile=profile)
    try:
        image_id = [image.name, image.stat().st_size] if image else ["", 0]
    except OSError:
        image_id = ["", 0]
    payload = {
        "version": BASE_BODY_VERSION,
        "views": {view: list(base_prompt(character_name, view, profile=profile)) for view in BASE_VIEWS},
        "profile_image": image_id,
    }
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return "base" + digest[:8]


def is_base_pipeline(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character is on the base-body pipeline: the profile switch
    is set AND the character is humanoid (an animal never is)."""
    profile = _profile_of(character_name, profile)
    if profile.get("model_pipeline") != "base_body":
        return False
    from app.core.model_refs import is_humanoid
    return bool(is_humanoid(character_name, profile=profile))


# --- Rendering the four views ---------------------------------------------

# Status per (character, view), in memory like the model-refs status: the
# count of reservations still holding the view (a route thread waiting on the
# character lock counts — it WILL render), since when, and the last failure.
_status_lock = threading.Lock()
_running: Dict[Tuple[str, str], Tuple[datetime, int]] = {}
_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}
# One base render per character at a time: the views edit the front, and a
# second run would race the same files.
_char_locks: Dict[str, threading.Lock] = {}


def _char_lock(character_name: str) -> threading.Lock:
    with _status_lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def reserve_views(character_name: str, views: Iterable[str]) -> None:
    """Mark views running (counted, so nested and queued runs stack)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        for view in views:
            key = (character_name, view)
            started, count = _running.get(key, (utc_now(), 0))
            _running[key] = (started, count + 1)


def release_views(character_name: str, views: Iterable[str]) -> None:
    with _status_lock:
        for view in views:
            key = (character_name, view)
            started, count = _running.get(key, (None, 0))
            if count <= 1:
                _running.pop(key, None)
            else:
                _running[key] = (started, count - 1)


def _record(character_name: str, view: str, error: Optional[str], *, warning: bool = False) -> None:
    """The outcome of one view: ``error`` None = fine; with ``warning`` the
    text is a caveat on a view that WAS stored (``base_status`` reports it
    as ``warning``, not as ``failed``)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        if error is None:
            _failed.pop((character_name, view), None)
        else:
            _failed[(character_name, view)] = {"error": error, "warning": warning, "failed_at": utc_now()}


def base_status(character_name: str) -> Dict[str, Dict[str, Any]]:
    """Per view: ``{running, started_at, failed, error, failed_at, warning}``
    — SYSTEM stamps (``utc_now``), shaped like
    ``model_refs.get_render_status``; ``warning`` is the caveat of a view
    that was stored anyway (the hand gate), None otherwise."""
    out: Dict[str, Dict[str, Any]] = {}
    with _status_lock:
        for view in BASE_VIEWS:
            started, _count = _running.get((character_name, view), (None, 0))
            failure = _failed.get((character_name, view)) or {}
            warned = bool(failure.get("warning"))
            out[view] = {"running": started is not None, "started_at": _iso(started),
                         "failed": bool(failure) and not warned,
                         "error": None if warned else failure.get("error"),
                         "failed_at": None if warned else _iso(failure.get("failed_at")),
                         "warning": failure.get("error") if warned else None}
    return out


class MissingInput(ValueError):
    """A precondition the user can fix (a profile picture, the front image)
    — a route answers 409, unlike a request that can never work (400)."""


class MissingFront(MissingInput):
    """A single side/back view was asked for before its front exists."""


def _kind(view: str) -> str:
    return "tpose" if view == "front" else f"tpose_{view}"


def check_renderable(character_name: str, *, view: Optional[str] = None,
                     profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The profile, or ValueError when no base body can be rendered: an
    unknown view, a non-humanoid character (animals keep the whole-body
    path), or no profile image (the identity of the base body comes from
    it — ``MissingInput``), or a single view without its front
    (``MissingFront``)."""
    if view is not None and view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    from app.core.model_refs import current_profile_image, find_ref_image, is_humanoid
    if not is_humanoid(character_name, profile=profile):
        raise ValueError("The base body is for humanoid characters only")
    if current_profile_image(character_name, profile=profile) is None:
        raise MissingInput("No profile picture. Set a profile picture, then render the base body")
    if view not in (None, "front") and find_ref_image(
            character_name, "tpose", base_signature(character_name, profile=profile)) is None:
        raise MissingFront("A base-body view requires the front image")
    return profile


#: Front renders per run at most: the first one plus two re-renders when the
#: hand gate (``base_body_gates.hand_pose_gate``) fails. Each is a fresh
#: render — the backend picks a new seed.
HAND_GATE_ATTEMPTS = 3


def hand_gate_warning(attempts: int) -> str:
    """The status warning of a front kept although no attempt passed."""
    return (f"Palms may face the camera (hand check failed after {attempts} "
            f"attempt{'' if attempts == 1 else 's'})")


def _publish_staged(staged: Path, final_stem: Path, record: Dict[str, Any],
                    key: str = "hand_gate") -> Optional[Path]:
    """Move a staged attempt (image + sidecar, the gate ``record`` written
    into the sidecar under ``key``) onto the view's stem in ``model_refs``. A stored image
    of the stem with another extension goes, like ``render_character_image``
    drops it. None when ``model_refs`` is gone (the character was deleted
    during the render)."""
    import shutil
    if not final_stem.parent.is_dir():
        return None
    sidecar = staged.with_suffix(".json")
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    except (OSError, ValueError):
        meta = {}
    meta[key] = record
    sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    target = final_stem.parent / f"{final_stem.name}{staged.suffix}"
    for old in final_stem.parent.glob(f"{final_stem.name}.*"):
        if old.suffix.lower() != ".json" and old != target:
            old.unlink()
    shutil.move(str(staged), str(target))
    shutil.move(str(sidecar), str(target.with_suffix(".json")))
    return target


def generate_base_images(character_name: str, *, view: Optional[str] = None,
                         force: bool = False) -> Dict[str, Optional[str]]:
    """Render the base-body views. Blocking — call from a worker thread.

    Front first (the ``tpose`` render path: use case ``tpose``, occasion
    ``base_front``, the profile image as identity reference), then
    back/left/right as edits of the front on grey (occasion ``base_view``,
    use cases ``model_refs.TPOSE_VIEW_USE_CASES``). Stored as ``tpose_<bsig>`` and
    ``tpose_<view>_<bsig>`` in ``model_refs/``; every sidecar records
    ``base_signature``. The mesh-input matte applies because the occasion
    is a mesh-input one (``render_character_image``).

    Hand gate on the front: the palms should face the thighs, and whether
    they do depends on the seed. Each front attempt renders into a private
    staging dir inside ``model_refs`` (``.handgate_*``, one subdir per
    attempt) and is measured by ``base_body_gates.hand_pose_gate``; the
    first passing attempt — else, after ``HAND_GATE_ATTEMPTS``, the one with
    the lowest score — is moved onto the front's stem with the gate numbers
    of every attempt in its sidecar (``hand_gate``). Attempt files never sit
    beside the stored refs: ``find_ref_image``, the cache GC and the outfit
    scans parse every file name there as a signature of its own. A front
    kept without a pass records ``hand_gate_warning`` as a status warning;
    the run goes on. A later attempt that fails to render ends the attempts
    with what was rendered. Back/left/right edit the chosen front.

    Cached per base signature: a view that exists is skipped unless
    ``force``. ``view`` renders that one view only (a non-front view needs
    the front). The prompts carry no use-case style — the image service
    adds the style and the use case's negative; ``base_prompt``'s negative
    is APPENDED to it (``extra_negative``), never a replacement.

    Returns ``{view: path | None}`` for every view it rendered (None =
    failed); a front that fails stops the run — the views need it."""
    import tempfile
    from app.core import base_body_gates, expression_regen
    from app.core.model_refs import (TPOSE_VIEW_USE_CASES, _tpose_size, find_ref_image,
                                     get_model_refs_dir, neutral_view_reference)
    with _char_lock(character_name):
        # Read at run time: a run queued behind another one renders the
        # profile (image, body slots) current when it starts.
        profile = check_renderable(character_name, view=view)
        bsig = base_signature(character_name, profile=profile)
        refs_dir = get_model_refs_dir(character_name)
        wanted = BASE_VIEWS if view is None else (view,)
        todo = [v for v in wanted
                if force or find_ref_image(character_name, _kind(v), bsig) is None]
        if not todo:
            logger.info("Base body %s (%s): already rendered", character_name, bsig)
            return {}
        width, height = _tpose_size()
        mesh_profile = deepcopy(profile)
        mesh_profile["equipped_pieces"] = {}
        mesh_profile["equipped_items"] = []
        results: Dict[str, Optional[str]] = {}

        def draw(v: str, stem: Path, reference: Optional[Path]) -> Optional[Path]:
            prompt, negative = base_prompt(character_name, v, profile=profile)
            return expression_regen.render_character_image(
                character_name,
                output_stem=stem,
                equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="",
                bare_prompt=prompt, extra_negative=negative,
                image_use_case="tpose" if v == "front" else TPOSE_VIEW_USE_CASES[v],
                occasion="base_front" if v == "front" else "base_view",
                override_width=width, override_height=height,
                apply_state_modifiers=False,
                mesh_input_profile=mesh_profile,
                back_view=v == "back",
                reference_image=reference,
                sidecar_extra={"base_signature": bsig},
                # The character's identity/pose LoRAs as on its tpose
                # render (tpose_loras, else loras); no slot LoRAs.
                character_loras=True)

        def draw_front(final: Path) -> Tuple[Optional[Path], Optional[str]]:
            """``(stored path, warning)`` of the gated front attempts."""
            attempts: List[Tuple[Path, Dict[str, Any]]] = []
            with tempfile.TemporaryDirectory(prefix=".handgate_", dir=refs_dir,
                                             ignore_cleanup_errors=True) as staging:
                for n in range(1, HAND_GATE_ATTEMPTS + 1):
                    stem = Path(staging) / f"attempt{n}" / final.name
                    stem.parent.mkdir()
                    try:
                        path = draw("front", stem, None)
                    except Exception as e:  # noqa: BLE001 — keep what was rendered
                        if not attempts:
                            raise
                        logger.warning("Base body %s (%s): front attempt %d failed: %s",
                                       character_name, bsig, n, e)
                        break
                    if not path:
                        if not attempts:
                            return None, None
                        logger.warning("Base body %s (%s): front attempt %d rendered nothing",
                                       character_name, bsig, n)
                        break
                    gate = base_body_gates.hand_pose_gate(path)
                    attempts.append((path, gate))
                    logger.info("Base body %s (%s): front attempt %d hand gate %s (score %s, limit %s)",
                                character_name, bsig, n, "passed" if gate["ok"] else "failed",
                                gate.get("score"), gate.get("limit"))
                    if gate["ok"]:
                        break
                chosen, passed = base_body_gates.best_attempt([g for _p, g in attempts])
                record = {"ok": passed, "chosen": chosen + 1, "limit": base_body_gates.HAND_LIMIT,
                          "attempts": [g for _p, g in attempts]}
                stored = _publish_staged(attempts[chosen][0], final, record)
            if stored is None:
                return None, None
            return stored, None if passed else hand_gate_warning(len(attempts))

        def render(v: str, reference: Optional[Path]) -> Optional[Path]:
            final = refs_dir / f"{_kind(v)}_{bsig}"
            warning = None
            reserve_views(character_name, (v,))
            try:
                if v == "front":
                    path, warning = draw_front(final)
                else:
                    path = draw(v, final, reference)
                error = None if path else "render failed"
            except Exception as e:  # noqa: BLE001 — one view never kills the run
                path, error = None, str(e) or type(e).__name__
                logger.warning("Base body %s %s (%s) failed: %s", character_name, v, bsig, e)
            finally:
                release_views(character_name, (v,))
            _record(character_name, v, error or warning, warning=error is None and warning is not None)
            results[v] = str(path) if path else None
            return path

        front = find_ref_image(character_name, "tpose", bsig)
        if "front" in todo:
            front = render("front", None)
            if front is None:
                logger.warning("Base body %s (%s): front failed, views skipped", character_name, bsig)
                for v in todo:
                    if v != "front":
                        _record(character_name, v, "front render failed")
                return results
        views = [v for v in todo if v != "front"]
        if views and front is None:
            raise MissingFront("A base-body view requires the front image")
        if views:
            # Every view edits the front, on neutral grey (an RGBA cut-out
            # turns black at the backend).
            with neutral_view_reference(front, refs_dir) as reference:
                for v in views:
                    render(v, reference)
        logger.info("Base body %s (%s): %s", character_name, bsig,
                    {k: bool(p) for k, p in results.items()})
        return results


def start_base_images(character_name: str, *, view: Optional[str] = None,
                      force: bool = False) -> None:
    """Run ``generate_base_images`` in a worker thread. The requested views
    count as running from THIS moment (the UI polls ``base_info``), and an
    error that ends the whole run is recorded on them."""
    views = BASE_VIEWS if view is None else (view,)
    reserve_views(character_name, views)

    def run() -> None:
        try:
            generate_base_images(character_name, view=view, force=force)
        except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
            logger.error("Base body render for %s failed: %s", character_name, e)
            for v in views:
                _record(character_name, v, str(e) or type(e).__name__)
        finally:
            release_views(character_name, views)

    threading.Thread(target=run, daemon=True, name=f"base-body-{character_name}").start()


def base_info(character_name: str) -> Dict[str, Any]:
    """UI info: ``{pipeline, humanoid, signature, images: {view: url|None},
    image_meta: {view: {model?, created_at?}|None}, status: {view: ...},
    model, outfit, hair}`` (``image_meta``: ``model_refs.image_tile_meta``
    of each stored view; ``model``: see
    ``base_model_info``; ``outfit``: the CURRENT outfit's model on the
    pipeline, see ``outfit_info`` — None off the pipeline; ``hair``:
    ``garments.hair_summary`` ``{item_id, status}`` — None without a worn
    hair item or off the pipeline); the image URLs
    carry the file's mtime so a re-render is fetched anew."""
    from app.core.model_refs import find_ref_image, image_tile_meta, is_humanoid
    profile = _profile_of(character_name, None)
    humanoid = bool(is_humanoid(character_name, profile=profile))
    signature = base_signature(character_name, profile=profile) if humanoid else ""
    images: Dict[str, Optional[str]] = {}
    image_meta: Dict[str, Optional[Dict[str, Any]]] = {}
    for view in BASE_VIEWS:
        path = find_ref_image(character_name, _kind(view), signature) if signature else None
        try:
            stamp = path.stat().st_mtime_ns if path else None
        except OSError:
            stamp = None
        images[view] = (f"/characters/{quote(character_name, safe='')}/base-body/images/{view}?v={stamp}"
                        if stamp is not None else None)
        image_meta[view] = image_tile_meta(path) if stamp is not None else None
    from app.core.timeutils import utc_now
    pipeline = is_base_pipeline(character_name, profile=profile)
    hair = None
    if pipeline and humanoid:
        try:
            from app.core import garments
            hair = garments.hair_summary(character_name, profile=profile)
        except Exception:  # noqa: BLE001 — the summary never breaks the poll
            logger.exception("Hair summary of %s failed", character_name)
    return {"pipeline": pipeline, "humanoid": humanoid,
            "signature": signature, "images": images, "image_meta": image_meta,
            "status": base_status(character_name),
            "model": base_model_info(character_name, signature),
            "outfit": outfit_info(character_name, base_sig=signature) if pipeline else None,
            "hair": hair,
            "now": _iso(utc_now())}


def base_image_path(character_name: str, view: str) -> Optional[Path]:
    """The stored image of one view for the CURRENT base signature."""
    if view not in BASE_VIEWS:
        return None
    from app.core.model_refs import find_ref_image
    return find_ref_image(character_name, _kind(view), base_signature(character_name))


# --- The base model ---------------------------------------------------------

# Base model runs in memory, like the image status: character -> base
# signature of the run in progress, and the last failed run per character.
# Runs of one character are serial (model3d's generation guard).
_model_running: Dict[str, str] = {}
_model_failed: Dict[str, Dict[str, Any]] = {}


def check_model_ready(character_name: str, *,
                      profile: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], str]:
    """``(profile, base signature)`` when a base model can be built: the
    preconditions of the images (``check_renderable``) plus the stored front
    image of the CURRENT base signature (``MissingInput`` without it)."""
    profile = check_renderable(character_name, profile=profile)
    bsig = base_signature(character_name, profile=profile)
    from app.core.model_refs import find_ref_image
    if find_ref_image(character_name, "tpose", bsig) is None:
        raise MissingInput("No base-body images. Render the base-body images first")
    return profile, bsig


def generate_base_model(character_name: str, *, force: bool = False) -> Dict[str, Any]:
    """Build the rigged base model from the base images. Blocking (minutes)
    — call from a worker thread.

    The staged mesh run of ``model3d.generate_for_current_outfit`` with
    ``signature=<bsig>`` and ``base=True`` (frozen into the hub-op inputs):
    source ``tpose_<bsig>``, every stored base view, the character's mesh
    occasion; after the rig no anatomy parts and no distance tier, the
    sidecar records ``"base": true`` and the unrigged checkpoint
    ``model3d/unrigged/<bsig>.glb`` stays. Cached per base signature unless
    ``force``."""
    from app.core import model3d
    from app.core.timeutils import utc_now
    bsig = ""
    error: Optional[str] = None
    try:
        _profile, bsig = check_model_ready(character_name)
        with _status_lock:
            _model_running[character_name] = bsig
            _model_failed.pop(character_name, None)
        result = model3d.generate_for_current_outfit(character_name, force=force,
                                                     signature=bsig, base=True)
        if not result.get("ok"):
            error = str(result.get("error") or "Base model generation failed")
        else:
            # R14: a worn garment whose fit is not on this base model starts
            # its chain (fit only when just the model bytes changed).
            from app.core import garments
            garments.after_base_model(character_name)
        return result
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        with _status_lock:
            _model_running.pop(character_name, None)
            if error is not None:
                _model_failed[character_name] = {"signature": bsig, "error": error,
                                                 "failed_at": utc_now()}


def start_base_model(character_name: str, *, force: bool = False) -> bool:
    """Run ``generate_base_model`` in a worker thread under model3d's
    per-character generation guard and lock. False when a 3D model
    generation already runs for the character. The run counts as running
    from THIS moment (the UI polls ``base_info``)."""
    from app.core import model3d
    bsig = base_signature(character_name)
    with _status_lock:
        reserved = character_name not in _model_running
        if reserved:
            _model_running[character_name] = bsig
    started = model3d.trigger_generation(character_name, force=force, base=True)
    if not started and reserved:
        with _status_lock:
            _model_running.pop(character_name, None)
    return started


def base_model_info(character_name: str, signature: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """``{signature, url, created_at, status, error}`` of the base model of
    the CURRENT base signature, or None when none is stored, running or
    failed. ``status``: ``running``; ``failed`` (the last run ended with an
    error, or the stored model is the static checkpoint whose rig failed —
    its sidecar ``rig_error``); ``unrigged`` (a static checkpoint without a
    run, e.g. one interrupted by a restart); ``ready``. ``url`` serves the
    stored model (``/characters/<name>/model3d/file?signature=<bsig>``)."""
    from app.core import model3d
    if signature is None:
        from app.core.model_refs import is_humanoid
        signature = base_signature(character_name) if is_humanoid(character_name) else ""
    if not signature:
        return None
    with _status_lock:
        running = _model_running.get(character_name)
        failure = dict(_model_failed.get(character_name) or {})
    path = model3d.find_model3d(character_name, signature)
    meta = model3d._read_sidecar(path) if path else {}
    if running == signature:
        status, error = "running", ""
    elif failure.get("signature") == signature:
        status, error = "failed", failure.get("error") or ""
    elif path is None:
        return None
    elif meta.get("rig_error"):
        status, error = "failed", str(meta["rig_error"])
    elif meta.get("rig") in (None, "", "none"):
        status, error = "unrigged", ""
    else:
        status, error = "ready", ""
    return {"signature": signature,
            "url": model3d.signature_model_url(character_name, signature) if path else None,
            "created_at": meta.get("created_at") or None,
            "status": status, "error": error}


def set_pipeline(character_name: str, enabled: bool) -> bool:
    """Switch the character onto (``model_pipeline: "base_body"``) or off the
    base-body pipeline. ValueError for a non-humanoid on switching on — the
    profile stays untouched. Returns the save result."""
    from app.core.keyed_lock import keyed_lock
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        if enabled:
            if not is_humanoid(character_name, profile=profile):
                raise ValueError("The base-body pipeline is for humanoid characters only")
            if profile.get("model_pipeline") == "base_body":
                return True
            profile["model_pipeline"] = "base_body"
        else:
            if "model_pipeline" not in profile:
                return True
            profile.pop("model_pipeline")
        return bool(save_character_profile(character_name, profile))


# --- Outfits on the base body (spec § B) -----------------------------------

# The edit form of the S1 spike (claude-out/s1-base-body/kleidung_real/
# front.json): keep everything, change only the clothing.
DRESS_KEEP = ("Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand "
              "position, same framing and background.")
DRESS_STYLE_NEGATIVE = ("illustration, anime, cgi, 3d render, painting, airbrushed skin, plastic skin, smooth "
                        "flawless skin, overexposed, glossy, fantasy, studio lighting, cartoon, drawing, sketch, "
                        "watermark, signature, text, logo, deformed, blurry, low quality")
# The spike's garment words, each with the words that mean the outfit itself
# names it — such a term leaves the negative (a skirt must not be forbidden
# from an outfit that IS a skirt). "hair": the base body is bald until the
# hair mesh (phase 4); the edit must not grow any.
DRESS_GARMENT_NEGATIVE = (
    ("loose clothing", r"loose"),
    ("baggy", r"baggy"),
    ("skirt", r"skirts?"),
    ("dress", r"dress(?:es)?"),
    ("jacket", r"jackets?|coats?|blazers?"),
    ("shoes", r"shoes?|boots?|sandals?|sneakers?|heels|slippers?|loafers?|footwear"),
    ("socks", r"socks?|stockings?|tights"),
    ("hair", r"hair"),
)

# The view sentence that opens a dressed edit of a non-front view: without
# it, back and side edits came out turned toward the camera (end-to-end run
# 2026-11-09; the left wording verified there). The front needs none.
DRESS_VIEW = {
    "back": ("This is a back view seen directly from behind, the figure faces away from the camera; keep it a "
             "back view, do not turn the figure toward the camera."),
    "left": ("This is a strict left side profile view, the whole body in profile facing the left edge of the "
             "frame; keep it a side profile view, do not turn the figure toward the camera."),
    "right": ("This is a strict right side profile view, the whole body in profile facing the right edge of the "
              "frame; keep it a side profile view, do not turn the figure toward the camera."),
}

#: The views an outfit dresses and hands to the body-retexture worker. Side
#: views put cloth on the arm in profile (measured 2026-11-09); the base
#: body's left/right views stay mesh inputs of the base model only.
DRESSED_VIEWS = ("front", "back")
SIDE_VIEW_NOT_DRESSED = ("On the base-body pipeline only the front and the back are dressed — "
                         "the side views belong to the base body (Base body tab)")
DRESSED_FRONT_FIRST = "Render the dressed front first — the back draft is made from it"

# The back is two steps (user decision 2026-11-09, measured on the end-to-end
# run): a DRAFT rendered fresh from the dressed front with the base back
# prompt, the body text replaced by the outfit of the reference — then the FIT,
# an edit of the base back with the draft as second reference.
DRAFT_OUTFIT_TEXT = ("wearing exactly the same outfit as the person in the reference image, the same "
                     "garments, lengths, cut, colours and shoes")
#: The draft keeps the base negative minus its no-clothing words.
DRAFT_NEGATIVE = ", ".join((HAIR_NEGATIVE, "detailed anatomy", POSE_NEGATIVE))
#: The whole fit prompt — no style, view sentence, outfit text or negative
#: (measured 2026-11-09: silhouette IoU vs the base back 0.92-0.93 against
#: 0.905 with the long edit prompt).
FIT_PROMPT = "edit the first image with the clothes from the second image"
#: Use case of the fit: empty style and negative (config).
FIT_USE_CASE = "outfit_fit"
#: Alpha from which a pixel belongs to the figure of a fit reference.
FIT_FIGURE_ALPHA = 16
#: Fit renders per back at most; each attempt is a fresh render (new seed).
FIT_ATTEMPTS = 2
#: Where the back drafts live: a subdirectory of model_refs, so no reader of
#: the stored refs (find_ref_image, mesh inputs, the outfit scans) parses
#: them as refs of their own; the reference gate still accepts them.
DRAFT_DIR = "drafts"

BASE_IMAGES_MISSING = "Base body images missing — render them in the Base body tab"
BASE_MODEL_MISSING = "Base body model missing — generate it in the 3D tab"
DRESSED_IMAGES_MISSING = "Dressed images missing — render the outfit's pose images"
OLDER_BASE = "Built on an older base body"
BEFORE_PIPELINE = "Built before the base body pipeline"


def dress_text(character_name: str, view: str, *, pieces: Optional[Dict[str, str]],
               items: Optional[list], profile: Optional[Dict[str, Any]] = None) -> str:
    """What the dressed edit says the figure now wears — "" for an undressed
    combination (nothing worn, or an undressed free-text wardrobe).

    The outfit text of the mesh-input render (``render_outfit(mesh_input=
    True, back_view=view == "back")``), composed as
    ``expression_regen.render_character_image`` composes its "is wearing"
    layer: the pieces, else (nothing structured worn) a dressed free-text
    wardrobe's text; the items follow with their own verb ("holding …")."""
    from app.core.outfit_renderer import render_outfit
    profile = dict(_profile_of(character_name, profile))
    profile["equipped_pieces"] = dict(pieces or {})
    profile["equipped_items"] = list(items or [])
    rendered = render_outfit(profile=profile, equipped_pieces=dict(pieces or {}),
                             equipped_items=list(items or []), back_view=view == "back",
                             mesh_input=True)
    wear = (rendered.get("pieces") or "").strip()
    if not wear and not (pieces or items):
        free = rendered.get("full") or ""
        if free.startswith("wearing: "):
            wear = free[len("wearing: "):].strip()
    held = (rendered.get("items") or "").strip()
    if wear and held:
        return f"they now wear {wear}, {held}"
    if wear:
        return f"they now wear {wear}"
    if held:
        return f"they are now {held}"
    return ""


def dress_negative(text: str) -> str:
    """The spike's negative minus the garment terms ``text`` names."""
    kept = [term for term, pattern in DRESS_GARMENT_NEGATIVE
            if not re.search(rf"\b(?:{pattern})\b", text or "", re.IGNORECASE)]
    return ", ".join([DRESS_STYLE_NEGATIVE, *kept])


def dress_prompt(character_name: str, view: str, *, pieces: Optional[Dict[str, str]],
                 items: Optional[list], profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of the dressed edit of one base view: the
    spike's edit form "Keep the image exactly as it is: … Only change their
    clothing: they now wear {outfit}." — opened by the view sentence
    ``DRESS_VIEW[view]`` for back/left/right — and its negative without the
    garment words the outfit names. ValueError for an undressed combination
    (that one copies the base images, there is nothing to edit)."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    text = dress_text(character_name, view, pieces=pieces, items=items, profile=profile)
    if not text:
        raise ValueError("An undressed combination has no dressed edit")
    edit = f"{DRESS_KEEP} Only change their clothing: {text}."
    view_sentence = DRESS_VIEW.get(view)
    return (f"{view_sentence} {edit}" if view_sentence else edit), dress_negative(text)


# Outfit status, in memory like the base status: (character, stage) ->
# signature of the run in progress (stage "images" or "model"), and the last
# failure per (character, signature).
_outfit_running: Dict[Tuple[str, str], str] = {}
_outfit_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _outfit_start(character_name: str, signature: str, stage: str) -> None:
    with _status_lock:
        _outfit_running[(character_name, stage)] = signature


def _outfit_end(character_name: str, signature: str, stage: str, error: Optional[str]) -> None:
    """End a stage: a failure is stored for the signature; a success clears
    a failure of the same stage (a model success clears every failure)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        if _outfit_running.get((character_name, stage)) == signature:
            _outfit_running.pop((character_name, stage), None)
        key = (character_name, signature)
        if error is not None:
            _outfit_failed[key] = {"stage": stage, "error": error, "failed_at": utc_now()}
        elif stage == "model" or (_outfit_failed.get(key) or {}).get("stage") == stage:
            _outfit_failed.pop(key, None)


def _ref_sidecar(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


# path -> ((size, mtime_ns, inode), sha256): content identity of base files,
# hashed again only when the file's stat changes (a copied world rehashes
# once and keeps its outfits current).
_hash_cache: Dict[str, Tuple[Tuple[int, int, int], str]] = {}


def file_sha256(path: Optional[Path]) -> str:
    """sha256 of a file's content, "" when it does not exist."""
    if path is None:
        return ""
    try:
        stat = path.stat()
    except OSError:
        return ""
    key = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
    with _status_lock:
        cached = _hash_cache.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
    with _status_lock:
        _hash_cache[str(path)] = (key, digest)
    return digest


def base_model_sha256(character_name: str, bsig: str) -> str:
    """Content identity of the stored rigged base model of ``bsig`` (the
    REAL model directory, also from inside a staged run), "" without one.
    An outfit model records it: a regenerated base under the same signature
    makes every outfit model built on the old one stale."""
    from app.models.character import get_character_dir
    return file_sha256(get_character_dir(character_name) / "model3d" / f"{bsig}.glb")


def current_base(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """``(base signature, base model sha256)`` of a character on the
    pipeline — what an outfit model must have been built on to be current —
    or None off the pipeline."""
    profile = _profile_of(character_name, profile)
    if not is_base_pipeline(character_name, profile=profile):
        return None
    bsig = base_signature(character_name, profile=profile)
    return bsig, base_model_sha256(character_name, bsig)


def built_on_current_base(meta: Dict[str, Any], base: Tuple[str, str]) -> bool:
    """Whether an outfit model's sidecar names the current base body."""
    return (meta.get("base_signature") == base[0]
            and meta.get("base_model_sha256") == base[1])


def back_draft_prompt(character_name: str, *,
                      profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of the back DRAFT: the base back prompt with the
    body text — ``BODY_TEXT`` and the slots' ``base_body_prompt`` texts, the
    undressed part — replaced by ``DRAFT_OUTFIT_TEXT``; the bald head stays
    (hair is its own mesh). Negative: ``DRAFT_NEGATIVE`` + the slots'
    ``base_body_negative`` texts."""
    profile = _profile_of(character_name, profile)
    return (_view_prompt(character_name, "back", DRAFT_OUTFIT_TEXT, profile=profile, base_fragments=False),
            base_negative(character_name, profile=profile, head=DRAFT_NEGATIVE))


def cut_out(path: Path):
    """The RGBA cut-out of an image: as stored when it already carries a
    matte (some alpha below ``FIT_FIGURE_ALPHA``), else the mesh-input matte
    (BiRefNet-DIS, ``character.MESH_INPUT_REMBG_MODEL``)."""
    import io
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    if image.getchannel("A").getextrema()[0] < FIT_FIGURE_ALPHA:
        return image
    with Image.open(io.BytesIO(run_rembg(path.read_bytes(), MESH_INPUT_REMBG_MODEL))) as matted:
        return matted.convert("RGBA")


def fit_canvas(base, draft, size: Tuple[int, int]):
    """``(base canvas, draft canvas)`` of the fit: two transparent RGBA
    images of one size — height = the base cut-out's, width = the wider of
    the base cut-out and that height at the render's aspect ``size`` — the
    base pasted centred, the draft's figure (alpha >= ``FIT_FIGURE_ALPHA``)
    cropped, scaled to the base figure's height and pasted with its centre on
    the base figure's centre. A cut-out without a figure: ValueError."""
    from PIL import Image
    base_box = base.getchannel("A").point(lambda a: 255 if a >= FIT_FIGURE_ALPHA else 0).getbbox()
    draft_box = draft.getchannel("A").point(lambda a: 255 if a >= FIT_FIGURE_ALPHA else 0).getbbox()
    if base_box is None or draft_box is None:
        raise ValueError("fit reference without a figure")
    height = base.height
    figure = draft.crop(draft_box)
    scale = (base_box[3] - base_box[1]) / figure.height
    figure = figure.resize((max(1, round(figure.width * scale)), base_box[3] - base_box[1]), Image.LANCZOS)
    width = max(base.width, round(height * size[0] / size[1]), figure.width)
    left = (width - base.width) // 2
    base_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    base_canvas.paste(base, (left, 0), base)
    centre_x = left + (base_box[0] + base_box[2]) / 2
    draft_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draft_canvas.paste(figure, (round(centre_x - figure.width / 2), base_box[1]), figure)
    return base_canvas, draft_canvas


@contextmanager
def fit_references(base_back: Path, draft: Path, refs_dir: Path, size: Tuple[int, int]):
    """``(base reference, draft reference)``: the ``fit_canvas`` pair of the
    cut-outs, saved under their own names in a private ``.fitref_*`` dir
    inside ``refs_dir`` (the reference containment gate accepts it; the fit's
    sidecar records the references by name)."""
    import tempfile
    base_canvas, draft_canvas = fit_canvas(cut_out(base_back), cut_out(draft), size)
    with tempfile.TemporaryDirectory(prefix=".fitref_", dir=refs_dir, ignore_cleanup_errors=True) as tmp:
        base_out = Path(tmp) / "base" / f"{base_back.stem}.png"
        draft_out = Path(tmp) / "draft" / f"{draft.stem}.png"
        for out, image in ((base_out, base_canvas), (draft_out, draft_canvas)):
            out.parent.mkdir()
            image.save(out)
        yield base_out, draft_out


def back_draft_path(character_name: str, signature: str) -> Optional[Path]:
    """The stored back draft of an outfit (``model_refs/drafts/
    tpose_back_<signature>.*``), or None."""
    from app.core.model_refs import _IMAGE_EXTS
    from app.models.character import get_character_dir
    directory = get_character_dir(character_name) / "model_refs" / DRAFT_DIR
    for ext in _IMAGE_EXTS:
        path = directory / f"tpose_back_{signature}{ext}"
        if path.is_file():
            return path
    return None


def dressed_image(character_name: str, view: str, signature: str, bsig: str) -> Optional[Path]:
    """The stored dressed image of one view of an outfit, or None — only one
    edited from the CURRENT base view counts (base signature ``bsig`` and
    the base view file's content; an edit of an older base body, or of a
    re-rendered one, does not line up with it). Only ``DRESSED_VIEWS`` are
    dressed; a side view is always None."""
    from app.core.model_refs import find_ref_image
    if view not in DRESSED_VIEWS:
        return None
    path = find_ref_image(character_name, _kind(view), signature)
    if path is None:
        return None
    meta = _ref_sidecar(path)
    if (meta.get("base_signature") != bsig or meta.get("base_image_sha256")
            != file_sha256(find_ref_image(character_name, _kind(view), bsig))):
        return None
    return path


def fit_gate_warning(attempts: int, record: Dict[str, Any]) -> str:
    """The status warning of a dressed back kept although no attempt passed;
    ``record`` is the kept attempt's ``{"guard", "noise"}``."""
    reasons = []
    if not (record.get("guard") or {}).get("ok", True):
        reasons.append("turned toward the camera")
    if not (record.get("noise") or {}).get("ok", True):
        reasons.append("grainy")
    what = " and ".join(reasons) or "off"
    return (f"Dressed back may be {what} (back check failed after {attempts} "
            f"attempt{'' if attempts == 1 else 's'})")


def best_fit_attempt(results: List[Dict[str, Any]]) -> Tuple[int, bool]:
    """``(index, passed)``: the first attempt passing both checks, else the
    one that keeps its view (guard) with the lowest noise score."""
    for i, result in enumerate(results):
        if result["ok"]:
            return i, True

    def rank(i: int):
        result = results[i]
        noise = (result.get("noise") or {}).get("score")
        return (not (result.get("guard") or {}).get("ok", True),
                noise if noise is not None else float("inf"), i)
    return min(range(len(results)), key=rank), False


def _dress_back(character_name: str, *, signature: str, bsig: str, pieces: Optional[Dict[str, str]],
                items: Optional[list], profile: Dict[str, Any], front: Path,
                base_views: Dict[str, Optional[Path]], refs_dir: Path,
                size: Tuple[int, int]) -> Tuple[Optional[Path], Optional[str]]:
    """The dressed back in two steps. ``(stored path, warning)``; raises
    ``OutfitError`` with the step that failed.

    1. DRAFT (occasion ``outfit_back_draft``): a fresh render with the
       dressed ``front`` (on grey) as the only reference and
       ``back_draft_prompt``; stored as ``model_refs/drafts/tpose_back_<sig>``.
    2. FIT (occasion ``outfit_back``, use case ``FIT_USE_CASE``): an edit of
       the cut-out base back (image 1) with the cut-out draft scaled onto it
       (image 2, ``fit_references``), prompt ``FIT_PROMPT`` and nothing else
       (user decision 2026-11-09). The render comes back on black and gets
       the mesh-input matte. Up to ``FIT_ATTEMPTS`` renders, each staged in a
       private ``.fitgate_*`` dir inside ``model_refs`` and checked by the
       head ``view_guard`` (a fit that turned into a front view) and
       ``base_body_gates.noise_gate`` against the base back (a grainy seed);
       the first passing attempt — else ``best_fit_attempt`` — is moved onto
       ``tpose_back_<sig>`` with every attempt's numbers in its sidecar
       (``fit_gate``, with ``warning`` when none passed)."""
    import tempfile
    from app.core import base_body_gates, expression_regen
    from app.core.model_refs import TPOSE_VIEW_USE_CASES, neutral_view_reference
    width, height = size
    use_case = TPOSE_VIEW_USE_CASES["back"]
    drafts = refs_dir / DRAFT_DIR
    drafts.mkdir(exist_ok=True)
    draft_text, draft_negative = back_draft_prompt(character_name, profile=profile)
    common = dict(equipped_pieces=dict(pieces or {}), equipped_items=list(items or []),
                  pose_prompt="", expression_prompt="", image_use_case=use_case,
                  override_width=width, override_height=height, apply_state_modifiers=False,
                  mesh_input_profile=profile, back_view=True, character_loras=True)
    with neutral_view_reference(front, refs_dir) as reference:
        draft = expression_regen.render_character_image(
            character_name, output_stem=drafts / f"tpose_back_{signature}",
            bare_prompt=draft_text, extra_negative=draft_negative,
            occasion="outfit_back_draft", reference_image=reference,
            sidecar_extra={"base_signature": bsig, "dressed": True, "back_draft": True,
                           "front_sha256": file_sha256(front)},
            **common)
    if draft is None:
        raise OutfitError("Dressed back draft failed")
    base_back = base_views["back"]
    extra = {"base_signature": bsig, "dressed": True, "base_image_sha256": file_sha256(base_back),
             "back_draft": draft.name, "back_draft_sha256": file_sha256(draft)}
    final = refs_dir / f"tpose_back_{signature}"
    attempts: List[Tuple[Path, Dict[str, Any]]] = []
    with tempfile.TemporaryDirectory(prefix=".fitgate_", dir=refs_dir, ignore_cleanup_errors=True) as staging, \
            fit_references(base_back, draft, refs_dir, size) as (base_reference, draft_reference):
        for n in range(1, FIT_ATTEMPTS + 1):
            stem = Path(staging) / f"attempt{n}" / final.name
            stem.parent.mkdir()
            try:
                path = expression_regen.render_character_image(
                    character_name, output_stem=stem, bare_prompt=FIT_PROMPT,
                    occasion="outfit_back", reference_image=base_reference,
                    extra_reference_images=[draft_reference], sidecar_extra=extra,
                    **{**common, "image_use_case": FIT_USE_CASE})
            except Exception as e:  # noqa: BLE001 — keep what was rendered
                if not attempts:
                    raise
                logger.warning("Dressed back %s (%s): fit attempt %d failed: %s", character_name, signature, n, e)
                break
            if path is None:
                if not attempts:
                    raise OutfitError("Dressed back edit failed")
                break
            guard = view_guard("back", path, base_views)
            noise = base_body_gates.noise_gate(path, base_back)
            result = {"ok": bool(guard["ok"] and noise["ok"]), "guard": guard, "noise": noise}
            attempts.append((path, result))
            logger.info("Dressed back %s (%s): fit attempt %d %s (guard %s, noise %s/%s)", character_name,
                        signature, n, "passed" if result["ok"] else "failed", guard.get("best"),
                        noise.get("score"), noise.get("limit"))
            if result["ok"]:
                break
        chosen, passed = best_fit_attempt([r for _p, r in attempts])
        warning = None if passed else fit_gate_warning(len(attempts), attempts[chosen][1])
        record = {"ok": passed, "chosen": chosen + 1, "noise_limit": base_body_gates.NOISE_LIMIT,
                  "attempts": [r for _p, r in attempts], "warning": warning}
        stored = _publish_staged(attempts[chosen][0], final, record, key="fit_gate")
    return stored, warning


def generate_dressed_images(character_name: str, *, pieces: Optional[Dict[str, str]],
                            items: Optional[list], signature: str, force: bool = False,
                            view: Optional[str] = None) -> Dict[str, Optional[str]]:
    """The outfit's mesh-input images on the base-body pipeline. Blocking —
    called from ``model_refs.generate_model_ref_images`` (kind ``tpose``),
    serial per character on its tpose lane.

    Only ``DRESSED_VIEWS`` (or ``view`` alone — a side view is a ValueError
    with ``SIDE_VIEW_NOT_DRESSED``):

    * front: an EDIT of the base front of the current base signature
      (``reference_image`` = the base front on grey, ``bare_prompt`` =
      ``dress_prompt``, occasion ``outfit_front``, use case ``tpose``);
    * back: ``_dress_back`` — a draft from the dressed front, then a gated
      fit onto the base back (occasions ``outfit_back_draft`` /
      ``outfit_back``, use cases ``tpose_back`` / ``FIT_USE_CASE``); it needs the dressed front
      (rendered in the same pass, or the stored one — else the status error
      ``DRESSED_FRONT_FIRST``).

    The character's own LoRAs, the dressed negative APPENDED to the use
    case's. Stored as ``tpose_<sig>`` / ``tpose_back_<sig>``, sidecar
    ``base_signature``, ``dressed: true`` and ``base_image_sha256`` (the
    edited base view's content, ``dressed_image``). An undressed combination
    copies the base front/back instead (no GPU run; ``dressed: false``). A
    view that exists for the current base signature is skipped unless
    ``force``. A kept fit warning (``fit_gate_warning``) is in the back's
    sidecar and in ``outfit_info``'s warnings.

    Missing base images: the status error ``BASE_IMAGES_MISSING``, nothing
    rendered. Returns ``{kind: path | None}`` for every view it produced."""
    import shutil
    from app.core import expression_regen
    from app.core.model_refs import (_tpose_size, find_ref_image, get_model_refs_dir, mesh_variant,
                                     neutral_view_reference)
    if view is not None and view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    if view is not None and view not in DRESSED_VIEWS:
        raise ValueError(SIDE_VIEW_NOT_DRESSED)
    profile = _profile_of(character_name, None)
    bsig = base_signature(character_name, profile=profile)
    wanted = DRESSED_VIEWS if view is None else (view,)
    # Every base view: the wanted ones are edited, all four score the back's
    # view guard.
    base_views = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
    if any(base_views[v] is None for v in wanted):
        logger.warning("Dressed images %s (%s): base images of %s missing", character_name, signature, bsig)
        _outfit_end(character_name, signature, "images", BASE_IMAGES_MISSING)
        return {}
    todo = [v for v in wanted if force or dressed_image(character_name, v, signature, bsig) is None]
    if not todo:
        _outfit_end(character_name, signature, "images", None)
        return {}
    refs_dir = get_model_refs_dir(character_name)
    mesh_profile = deepcopy(profile)
    mesh_profile["equipped_pieces"] = dict(pieces or {})
    mesh_profile["equipped_items"] = list(items or [])
    dressed = bool(dress_text(character_name, "front", pieces=pieces, items=items, profile=mesh_profile))
    results: Dict[str, Optional[str]] = {}
    errors = []
    _outfit_start(character_name, signature, "images")
    try:
        if not dressed:
            from app.core.timeutils import utc_now_iso
            variant = mesh_variant(character_name, dict(pieces or {}), mesh_profile)
            for v in todo:
                source = base_views[v]
                target = refs_dir / f"{_kind(v)}_{signature}{source.suffix}"
                shutil.copyfile(source, target)
                meta = {**_ref_sidecar(source), "created_at": utc_now_iso(),
                        "equipped_pieces": dict(pieces or {}), "equipped_items": list(items or []),
                        "mesh_variant": variant, "base_signature": bsig,
                        "base_image_sha256": file_sha256(source), "dressed": False}
                target.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
                results[_kind(v)] = str(target)
        else:
            width, height = _tpose_size()
            if "front" in todo:
                prompt, negative = dress_prompt(character_name, "front", pieces=pieces, items=items,
                                                profile=mesh_profile)
                try:
                    with neutral_view_reference(base_views["front"], refs_dir) as reference:
                        path = expression_regen.render_character_image(
                            character_name,
                            output_stem=refs_dir / f"tpose_{signature}",
                            equipped_pieces=dict(pieces or {}), equipped_items=list(items or []),
                            pose_prompt="", expression_prompt="",
                            bare_prompt=prompt, extra_negative=negative,
                            image_use_case="tpose",
                            occasion="outfit_front",
                            override_width=width, override_height=height,
                            apply_state_modifiers=False,
                            mesh_input_profile=mesh_profile,
                            reference_image=reference,
                            sidecar_extra={"base_signature": bsig, "dressed": True,
                                           "base_image_sha256": file_sha256(base_views["front"])},
                            character_loras=True)
                    if path is None:
                        errors.append("Dressed front edit failed")
                except Exception as e:  # noqa: BLE001 — one view never kills the pass
                    path = None
                    errors.append(f"Dressed front edit failed: {e}")
                    logger.warning("Dressed %s front (%s) failed: %s", character_name, signature, e)
                results["tpose"] = str(path) if path else None
            if "back" in todo:
                front = dressed_image(character_name, "front", signature, bsig)
                path = None
                if front is None:
                    errors.append(DRESSED_FRONT_FIRST)
                else:
                    try:
                        path, warning = _dress_back(
                            character_name, signature=signature, bsig=bsig, pieces=pieces, items=items,
                            profile=mesh_profile, front=front, base_views=base_views, refs_dir=refs_dir,
                            size=(width, height))
                        if warning:
                            logger.warning("Dressed back %s (%s): %s", character_name, signature, warning)
                    except Exception as e:  # noqa: BLE001 — the front stays
                        errors.append(str(e) if isinstance(e, OutfitError) else f"Dressed back edit failed: {e}")
                        logger.warning("Dressed %s back (%s) failed: %s", character_name, signature, e)
                results["tpose_back"] = str(path) if path else None
    finally:
        _outfit_end(character_name, signature, "images", errors[0] if errors else None)
    logger.info("Dressed images %s (%s on %s): %s", character_name, signature, bsig,
                {k: bool(p) for k, p in results.items()})
    return results


# --- View guard -------------------------------------------------------------

# An edit can turn the figure toward the camera while keeping its outline —
# the worker's framing check then lets it through. The guard compares the
# HEAD region of a dressed view with the four base views: it must be most
# similar to its own. Tuned on the end-to-end run of 2026-11-09 (head = top
# 12 % of the figure, 64x64 grey, zero-mean normalized cross-correlation):
# good front 0.982 (next 0.657), good left 0.888 (next 0.654); the turned
# left/right edits 0.567/0.412 against 0.750/0.495 for the front.
VIEW_GUARD_HEAD_SHARE = 0.12
VIEW_GUARD_SIZE = 64


def _head_vector(path: Path):
    """The head region of a matted figure as a unit, zero-mean vector, or
    None when it cannot be measured (no transparent pixel = no matte, no
    figure, a flat head region). The figure is cropped to its alpha box,
    the top ``VIEW_GUARD_HEAD_SHARE`` of it cropped again to its own alpha
    box (the head, not the arm span), put on neutral grey, greyscaled and
    resized to ``VIEW_GUARD_SIZE`` squared."""
    import numpy as np
    from PIL import Image
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except (OSError, ValueError):
        return None
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] == 255:
        return None
    box = alpha.getbbox()
    if box is None:
        return None
    figure = image.crop(box)
    head = figure.crop((0, 0, figure.width, max(1, round(figure.height * VIEW_GUARD_HEAD_SHARE))))
    box = head.getchannel("A").getbbox()
    if box is None:
        return None
    head = head.crop(box)
    flat = Image.new("RGBA", head.size, (128, 128, 128, 255))
    flat.alpha_composite(head)
    grey = flat.convert("L").resize((VIEW_GUARD_SIZE, VIEW_GUARD_SIZE), Image.BILINEAR)
    vector = np.asarray(grey, dtype=np.float64).ravel()
    vector = vector - vector.mean()
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else None


def view_guard(view: str, dressed: Path, base_views: Dict[str, Optional[Path]]) -> Dict[str, Any]:
    """Whether a dressed view kept its view: ``{"ok", "scores": {base view:
    correlation}, "best"}`` — ``ok`` when the dressed head region correlates
    best with the base view of the same name. ``{"ok": True, "skipped":
    <reason>}`` when it cannot be measured (an image without a matte, the
    own base view missing): the guard never blocks what it cannot judge."""
    vector = _head_vector(dressed)
    if vector is None:
        return {"ok": True, "skipped": "dressed image without a measurable head region"}
    scores: Dict[str, float] = {}
    for name, path in base_views.items():
        reference = _head_vector(path) if path is not None else None
        if reference is not None:
            scores[name] = round(float(vector @ reference), 4)
    if view not in scores:
        return {"ok": True, "skipped": "base view without a measurable head region"}
    best = max(scores, key=lambda name: scores[name])
    return {"ok": best == view, "scores": scores, "best": best}


def _guard_message(view: str, result: Dict[str, Any]) -> str:
    if not result.get("best"):
        return f"{view} view: the dressed image does not keep its view ({result.get('skipped') or 'unchecked'})"
    return (f"{view} view: the dressed image does not keep its view (its head looks most like the "
            f"{result['best']} base view)")


# --- GLB base colour --------------------------------------------------------

_MIME_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def _base_color_targets(gltf: Dict[str, Any]) -> Tuple[int, Dict[int, str]]:
    """``(primary, {image index: role})`` of a document's base colour: every
    image a material's ``baseColorTexture`` resolves to — the preferred one
    (``model_validate.texture_image_index``: an EXT_texture_webp source, else
    the core source) is ``primary`` and must be the same for every material;
    a WebP texture's core fallback is replaced too (role ``core``)."""
    from app.core.model_validate import texture_image_index
    textures = gltf.get("textures") or []
    primaries, targets = set(), {}
    for material in gltf.get("materials") or []:
        info = ((material or {}).get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        if not isinstance(info, dict):
            continue
        texture = textures[info["index"]]
        primary = texture_image_index(gltf, texture)
        primaries.add(primary)
        targets[primary] = "webp" if "EXT_texture_webp" in (texture.get("extensions") or {}) else "core"
        if targets[primary] == "webp" and isinstance(texture.get("source"), int):
            targets[texture["source"]] = "core"
    if len(primaries) != 1:
        raise ValueError(f"Expected exactly one base-colour image, found {len(primaries)}")
    return next(iter(primaries)), targets


def base_color_image(glb: bytes) -> Tuple[bytes, str]:
    """``(bytes, mime)`` of a GLB's one base-colour image."""
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf, binary = parsed["gltf"], parsed["bin"]
    primary, _targets = _base_color_targets(gltf)
    image = gltf["images"][primary]
    view = (gltf.get("bufferViews") or [])[image["bufferView"]] if "bufferView" in image else None
    if view is None or view.get("buffer", 0) != 0:
        raise ValueError("The base-colour image is not embedded in the GLB")
    start = int(view.get("byteOffset", 0))
    return bytes(binary[start:start + int(view["byteLength"])]), image.get("mimeType", "")


def _encode(image: bytes, mime: str, target: str) -> bytes:
    if mime == target:
        return image
    import io
    from PIL import Image
    with Image.open(io.BytesIO(image)) as decoded:
        decoded.load()
        out = io.BytesIO()
        if target == "image/jpeg":
            decoded.convert("RGB").save(out, format="JPEG", quality=95)
        elif target == "image/webp":
            decoded.save(out, format="WEBP", lossless=True, exact=True, quality=100)
        else:
            decoded.save(out, format="PNG")
    return out.getvalue()


def replace_base_color(glb: bytes, image: bytes, mime: str) -> bytes:
    """The GLB with ``image`` as its base colour; nodes, skins, meshes,
    accessors, materials and textures stay as they are.

    The image entries the base colour resolves to get the new bytes: a
    core (PNG/JPEG) source takes ``image`` as given when it is PNG or JPEG
    (its ``mimeType`` follows), a WebP source of EXT_texture_webp gets it
    re-encoded as lossless WebP. The BIN chunk is repacked in bufferView
    order (4-byte aligned) — only the bufferViews' offsets/lengths and the
    buffer length change. ValueError for anything this cannot rewrite
    safely: not exactly one base-colour image, an image outside the BIN
    chunk or sharing its bufferView, a second buffer, a bufferView with
    extensions (meshopt names raw buffer offsets)."""
    import struct
    from app.core.model_validate import parse_glb
    if mime not in _MIME_FORMATS:
        raise ValueError(f"Unsupported base-colour image type: {mime!r}")
    parsed = parse_glb(glb)
    gltf, binary = parsed["gltf"], parsed["bin"]
    _primary, targets = _base_color_targets(gltf)
    images, views = gltf.get("images") or [], gltf.get("bufferViews") or []
    if len(gltf.get("buffers") or []) != 1:
        raise ValueError("Base-colour replacement needs a single-buffer GLB")
    used = {}
    for i, img in enumerate(images):
        if "bufferView" in img:
            used.setdefault(img["bufferView"], []).append(("image", i))
    for i, accessor in enumerate(gltf.get("accessors") or []):
        if "bufferView" in accessor:
            used.setdefault(accessor["bufferView"], []).append(("accessor", i))
    replaced: Dict[int, bytes] = {}
    for index, role in targets.items():
        img = images[index]
        if "bufferView" not in img or "uri" in img:
            raise ValueError("The base-colour image is not embedded in the GLB")
        if used.get(img["bufferView"]) != [("image", index)]:
            raise ValueError("The base-colour image shares its bufferView")
        target = "image/webp" if role == "webp" else (mime if mime != "image/webp" else "image/png")
        replaced[img["bufferView"]] = _encode(image, mime, target)
        img["mimeType"] = target
    packed = bytearray()
    for i, view in enumerate(views):
        if view.get("buffer", 0) != 0 or view.get("extensions"):
            raise ValueError("Base-colour replacement cannot repack this bufferView")
        start, length = int(view.get("byteOffset", 0)), int(view["byteLength"])
        if start < 0 or length < 0 or start + length > len(binary):
            raise ValueError("Invalid bufferView in the GLB")
        raw = replaced.get(i, binary[start:start + length])
        packed.extend(b"\0" * (-len(packed) % 4))
        view["byteOffset"] = len(packed)
        view["byteLength"] = len(raw)
        packed.extend(raw)
    packed.extend(b"\0" * (-len(packed) % 4))
    gltf["buffers"][0]["byteLength"] = len(packed)
    document = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    document += b" " * (-len(document) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(document) + len(packed))
            + struct.pack("<I4s", len(document), b"JSON") + document
            + struct.pack("<I4s", len(packed), b"BIN\0") + bytes(packed))


# --- The outfit model -------------------------------------------------------

class OutfitError(RuntimeError):
    """A precondition of the outfit model is missing (base model, images)."""


# Base sidecar keys that describe the base run itself, never the outfit
# model copied from it.
_BASE_ONLY_META = ("base", "created_at", "signature", "source", "lod_error", "diagnosis", "measured",
                   "rig_error", "source_image", "source_image_sha256", "view_images",
                   "view_images_sha256", "job_id", "source_filename", "pieces", "items",
                   "mesh_variant", "refined", "retexture_proof", "base_signature",
                   "base_model_sha256", "dressed")


def _snapshot_base_model(character_name: str, bsig: str) -> Dict[str, Any]:
    """The current base model's files, read under the publication lock of
    the REAL model directory (the outfit run is staged on its own
    signature): rigged GLB + sidecar, the unrigged checkpoint, the clean
    prerig source + sidecar when it exists."""
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import _read_sidecar
    from app.models.character import get_character_dir
    directory = get_character_dir(character_name) / "model3d"
    with keyed_lock("model3d_publication", str(directory)):
        rigged = directory / f"{bsig}.glb"
        meta = _read_sidecar(rigged)
        if not rigged.is_file() or not meta.get("base") or meta.get("rig") != "mixamo" or meta.get("rig_error"):
            raise OutfitError(BASE_MODEL_MISSING)
        unrigged = directory / "unrigged" / f"{bsig}.glb"
        if not unrigged.is_file():
            raise OutfitError("Base body model has no unrigged source — regenerate the base model")
        prerig = directory / "prerig" / f"{bsig}.glb"
        return {"rigged": rigged.read_bytes(), "meta": meta, "unrigged": unrigged.read_bytes(),
                "prerig": prerig.read_bytes() if prerig.is_file() else None,
                "prerig_meta": _read_sidecar(prerig) if prerig.is_file() else {}}


def _guard_dressed_views(character_name: str, signature: str, bsig: str,
                         dressed_views: Dict[str, Optional[Path]],
                         registrations: Dict[str, Optional[Path]]) -> Tuple[Dict[str, Any], list]:
    """Run ``view_guard`` on every dressed view of a DRESSED combination
    (an undressed one is the base images themselves). A failing view is
    re-rendered ONCE (``generate_dressed_images(view=…, force=True)`` with
    the pieces/items of its sidecar) and checked again; still failing, it
    is dropped from ``dressed_views`` (set None) with a warning naming the
    view — except the front, which fails the build (``OutfitError``).
    Returns ``(guard record per view, warnings)``; the record keeps the
    scores of both attempts (``first`` = the replaced image's)."""
    from app.core.model3d import _ref_manifest
    if _ref_sidecar(dressed_views["front"]).get("dressed") is False:
        return {}, []
    record: Dict[str, Any] = {}
    warnings = []
    for v in DRESSED_VIEWS:
        path = dressed_views.get(v)
        if path is None or registrations.get(v) is None:
            continue
        result = view_guard(v, path, registrations)
        if not result["ok"]:
            logger.warning("Outfit model %s (%s): %s — rendering it once more", character_name, signature,
                           _guard_message(v, result))
            manifest = _ref_manifest(path) or _ref_manifest(dressed_views["front"])
            retry: Dict[str, Any] = {"ok": False, "skipped": "no outfit manifest to re-render from"}
            if manifest:
                try:
                    generate_dressed_images(character_name, pieces=manifest.get("pieces"),
                                            items=manifest.get("items"), signature=signature,
                                            force=True, view=v)
                except Exception as e:  # noqa: BLE001 — the old verdict stands
                    logger.warning("Dressed %s %s re-render failed: %s", character_name, v, e)
                path = dressed_image(character_name, v, signature, bsig)
                retry = (view_guard(v, path, registrations) if path is not None
                         else {"ok": False, "skipped": "re-render failed"})
            result = {**retry, "rerendered": True, "first": result}
            if not result["ok"] and "best" not in result:
                result["best"] = result["first"].get("best")
        record[v] = result
        if result["ok"]:
            dressed_views[v] = path
            continue
        if v == "front":
            raise OutfitError(_guard_message(v, result))
        warnings.append(_guard_message(v, result) + "; left out of the outfit model")
        dressed_views[v] = None
    return record, warnings


def _assemble_garments(character_name: str, signature: str, path: Path, meta: Dict[str, Any]) -> None:
    """The eager assembly of a freshly built outfit model (R11): built INSIDE
    the model's stage, so its publication carries bare file and assembly
    together. A failure never blocks the bare model — it is published with
    the reason in ``garment_warnings`` (and served bare)."""
    from app.core import garment_assembly, model3d
    try:
        result = garment_assembly.assemble(character_name, signature, tiers=(garment_assembly.FULL,))
        warning = "" if result.get("ok") else str(result.get("error") or "Garment assembly failed")
    except Exception as e:  # noqa: BLE001 — the bare model stays published
        warning = f"Garment assembly failed: {e}"
    if warning:
        logger.warning("Outfit model %s (%s): %s", character_name, signature, warning)
        meta["garment_warnings"] = [warning]
        model3d._publish_sidecar(path, meta)


def build_outfit_model(character_name: str, signature: str) -> Dict[str, Any]:
    """Build the outfit model ``model3d/<signature>.glb`` of a character on
    the pipeline: the rigged base model with the outfit painted on. Called by
    ``model3d._generate_for_current_outfit`` INSTEAD of the img2mesh stages,
    inside its staging (writes go to the stage of ``signature``; the base is
    read from the real directory). Blocking; CPU only.

    Inputs, frozen when the run starts: the current base model (rigged GLB,
    unrigged checkpoint ``model3d/unrigged/<bsig>.glb``, clean prerig
    source), the dressed front/back ``tpose[_back]_<signature>`` made from
    the current base and their registration images ``tpose[_back]_<bsig>``
    — only ``DRESSED_VIEWS`` reach the worker.
    Before the worker runs, every dressed view passes the view guard
    (``_guard_dressed_views``: a turned view is re-rendered once, then left
    out with a warning; a turned front fails the build); the per-view
    record and the warnings go into the sidecar (``view_guard``,
    ``view_warnings``). The worker gets the unrigged geometry carrying the rigged base's CURRENT
    base-colour image (same UV layout) and writes the dressed GLB; its base
    colour goes into a copy of the rigged base GLB (and of its prerig
    source). An undressed combination is the base copy without a worker
    run. Then the usual post-steps: texture re-encode, the extension rig
    (``model3d._auto_extension_rig`` — the copied base state makes it a
    no-op unless this outfit's ``mesh_variant`` declares other groups, e.g.
    anatomy parts; then every group is rebuilt once from the clean prerig
    copy, never on top of the base's extension bones), measurement,
    sidecar (``base_signature``, ``base_model_sha256``, ``retexture_proof``,
    ``source: "base_body"``), distance tier, and the eager garment assembly
    ``model3d/assembled/<signature>.glb`` (``_assemble_garments``; a failure
    only adds ``garment_warnings`` to the sidecar).

    Errors (worker unavailable/refused, missing base model or images, an
    output that cannot be read) → ``{"ok": False, "error": <message>}``,
    recorded for the outfit status; nothing is written, so the previous
    model of the signature stays."""
    import tempfile
    from app.core import body_retexture, model3d
    from app.core.extension_rig import extension_metadata
    from app.core.model_refs import find_ref_image
    from app.core.task_queue import get_task_queue
    from app.core.timeutils import utc_now_iso
    _outfit_start(character_name, signature, "model")
    error: Optional[str] = None
    task_id = ""
    try:
        try:
            task_id = get_task_queue().track_start(
                "model3d_generation", f"Outfit retexture: {character_name}",
                agent_name=character_name, start_running=True)
        except Exception:  # noqa: BLE001 — tracking is display only
            task_id = ""
        profile = _profile_of(character_name, None)
        if not is_base_pipeline(character_name, profile=profile):
            raise OutfitError("The character is not on the base-body pipeline")
        bsig = base_signature(character_name, profile=profile)
        base = _snapshot_base_model(character_name, bsig)
        registrations = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
        if registrations["front"] is None:
            raise OutfitError(BASE_IMAGES_MISSING)
        dressed_views = {v: dressed_image(character_name, v, signature, bsig) for v in DRESSED_VIEWS}
        if dressed_views["front"] is None:
            raise OutfitError(DRESSED_IMAGES_MISSING)
        guard, warnings = _guard_dressed_views(character_name, signature, bsig, dressed_views, registrations)
        with tempfile.TemporaryDirectory(prefix="body-retexture-") as tmp:
            work = Path(tmp)
            views: Dict[str, Tuple[Path, Path]] = {}
            front_meta: Dict[str, Any] = {}
            manifest: Dict[str, Any] = {}
            names: Dict[str, str] = {}
            # Only the dressed views go to the worker (DRESSED_VIEWS); the
            # side registrations scored the view guard above.
            for v in DRESSED_VIEWS:
                dressed = dressed_views[v]
                registration = registrations[v]
                if v == "front" and dressed is None:
                    raise OutfitError(DRESSED_IMAGES_MISSING)
                if dressed is None or registration is None:
                    continue
                # Frozen copies: a re-render while the worker runs must not
                # change its input.
                frozen = (work / f"dressed_{v}{dressed.suffix}", work / f"registration_{v}{registration.suffix}")
                frozen[0].write_bytes(dressed.read_bytes())
                frozen[1].write_bytes(registration.read_bytes())
                views[v] = frozen
                names[v] = dressed.name
                if v == "front":
                    front_meta = _ref_sidecar(dressed)
                    manifest = model3d._ref_manifest(dressed)
            proof: Optional[Dict[str, Any]] = None
            outfit = base["rigged"]
            if front_meta.get("dressed") is not False:
                image, mime = base_color_image(base["rigged"])
                worker_in = work / "base_in.glb"
                worker_in.write_bytes(replace_base_color(base["unrigged"], image, mime))
                out_glb = work / "dressed.glb"
                proof = body_retexture.retexture(worker_in, views, out_glb,
                                                 proof=work / "proof.json", atlas=work / "atlas.png")
                if not out_glb.is_file():
                    raise OutfitError("Body retexture worker wrote no GLB")
                atlas, atlas_mime = base_color_image(out_glb.read_bytes())
                outfit = replace_base_color(base["rigged"], atlas, atlas_mime)
            verdict = model3d._validator_for("mixamo", character_name)(outfit)
            if not verdict.get("ok"):
                raise OutfitError("Retextured model is invalid: " + "; ".join(verdict.get("errors") or []))
        out_dir = model3d.get_model3d_dir(character_name)
        path = out_dir / f"{signature}.glb"
        model3d._purge_combination(out_dir, signature, keep_model=path)
        model3d._publish_model_bytes(path, outfit)
        meta = {k: v for k, v in deepcopy(base["meta"]).items() if k not in _BASE_ONLY_META}
        meta.update({"created_at": utc_now_iso(), "source": "base_body", "signature": signature,
                     "character": character_name, "format": "glb", "rig": "mixamo",
                     "base_signature": bsig,
                     "base_model_sha256": hashlib.sha256(base["rigged"]).hexdigest(),
                     "retexture_proof": proof,
                     "dressed": front_meta.get("dressed") is not False,
                     "source_image": names["front"],
                     "view_images": {v: n for v, n in names.items() if v != "front"},
                     "view_guard": guard, "view_warnings": warnings})
        meta.update(manifest)
        model3d._auto_retexture(character_name, path, meta)
        if base["prerig"] is not None:
            # The clean source of the extension rig carries the same texture
            # as the model, so a rebuild from it keeps the outfit.
            prerig = out_dir / "prerig" / path.name
            prerig.parent.mkdir(parents=True, exist_ok=True)
            source = base["prerig"]
            if proof is not None or path.read_bytes() != base["rigged"]:
                source = replace_base_color(source, *base_color_image(path.read_bytes()))
            model3d._publish_model_bytes(prerig, source)
            model3d._publish_sidecar(prerig, base["prerig_meta"])
        model3d._auto_extension_rig(character_name, path, meta)
        model3d._attach_measurement(meta, path)
        meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
        model3d._publish_sidecar(path, meta)
        model3d.request_lod(character_name, path)
        _assemble_garments(character_name, signature, path, meta)
        logger.info("Outfit model %s (%s on %s): %s", character_name, signature, bsig,
                    "retextured" if proof is not None else "undressed base copy")
        return {"ok": True, "cached": False, "path": str(path), "filename": path.name, "proof": proof}
    except (OutfitError, body_retexture.RetextureUnavailable, body_retexture.RetextureFailed,
            ValueError) as e:
        error = str(e) or type(e).__name__
        logger.warning("Outfit model %s (%s) failed: %s", character_name, signature, error)
        return {"ok": False, "error": error}
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        _outfit_end(character_name, signature, "model", error)
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error or "")
            except Exception:  # noqa: BLE001
                pass


def dressed_warnings(character_name: str, signature: str, bsig: str) -> List[str]:
    """The caveats of the stored dressed images of an outfit made from the
    current base: the back's ``fit_gate`` warning (kept although no fit
    attempt passed)."""
    back = dressed_image(character_name, "back", signature, bsig) if bsig else None
    warning = (_ref_sidecar(back).get("fit_gate") or {}).get("warning") if back else None
    return [warning] if warning else []


def outfit_info(character_name: str, *, base_sig: Optional[str] = None,
                signature: Optional[str] = None) -> Dict[str, Any]:
    """``{signature, status, error, proof, url}`` of an outfit model on the
    pipeline (default: the CURRENT outfit). ``status``: ``running`` (dressed
    images or model in progress), ``failed`` (the last run's error),
    ``stale`` (the stored model was built on an older base body — or before
    the pipeline — and is rebuilt on the next trigger; ``error`` says so,
    ``stale_reason`` ``older_base`` / ``before_pipeline``), ``ready``,
    ``missing``. ``warnings``: the stored model's view-guard warnings
    (dressed views left out because they turned around), then the dressed
    images' own (``dressed_warnings``). ``proof``: the
    worker's proof of the stored model (None for an undressed base copy)."""
    from app.core import model3d
    from app.core.model_refs import current_outfit_state
    if signature is None:
        signature = current_outfit_state(character_name)[2]
    if base_sig is None:
        base_sig = base_signature(character_name)
    current = (base_sig, base_model_sha256(character_name, base_sig))
    with _status_lock:
        running = any(sig == signature for (name, _stage), sig in _outfit_running.items()
                      if name == character_name)
        failure = dict(_outfit_failed.get((character_name, signature)) or {})
    path = model3d.find_model3d(character_name, signature, include_stale=True)
    meta = model3d._read_sidecar(path) if path else {}
    if running:
        status, error = "running", ""
    elif failure:
        status, error = "failed", failure.get("error") or ""
    elif path is None:
        status, error = "missing", ""
    elif not built_on_current_base(meta, current):
        status, error = "stale", (OLDER_BASE if meta.get("base_signature") else BEFORE_PIPELINE)
    else:
        status, error = "ready", ""
    return {"signature": signature, "status": status, "error": error,
            "stale_reason": (("older_base" if meta.get("base_signature") else "before_pipeline")
                             if status == "stale" else None),
            "warnings": (list(meta.get("view_warnings") or []) if path else []) + dressed_warnings(
                character_name, signature, base_sig),
            "proof": meta.get("retexture_proof") if path else None,
            "url": model3d.signature_model_url(character_name, signature) if status == "ready" else None}
