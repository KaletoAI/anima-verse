"""What an improvement type may ask about a SUBJECT, and how it regenerates it.

One place for the subject kinds the built-in types work on — characters,
location buildings, props, character expressions and the rendered images of
characters and locations — so a type stays a declaration of *which* subjects it
wants and never learns where a mesh sidecar lives or which producer function is
the blocking one.

Two rules hold for every ``generate_*``/``regenerate_*`` here, because the
engine calls them synchronously in a queue worker:

* the BLOCKING producer is called directly, never a ``trigger_*`` wrapper —
  a wrapper starts a daemon thread and would report success while nothing had
  been generated;
* a failure has to leave here as an exception.  The mesh/prop producers swallow
  theirs and answer ``{"ok": False, "error": …}``, so the error is raised here;
  the gallery core is the exception — it raises ``HTTPException`` itself, and
  the busy case has to be translated back (see ``regenerate_gallery_image``).
  A subject that is already being generated elsewhere — or a backend that is
  simply saturated — raises :class:`CandidateBusy` instead: that is load, not a
  defect, and the engine leaves the step pending without counting an attempt.
"""
from app.imagegen.routing import ROUTE_META_KEYS
from app.imagegen.selection import is_generator_backend

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.improvements.base import CandidateBusy


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

def characters() -> List[str]:
    """The roster an improvement may work on: every living character except the
    temporary NPCs (their assets are the spawn gate's job, and they are gone
    again before an idle pass would finish).  ``list_available_characters``
    already leaves the pooled ones out."""
    from app.models.character import is_temporary_npc, list_available_characters
    return sorted(n for n in list_available_characters() if not is_temporary_npc(n))


def character_model(name: str) -> Optional[Dict[str, Any]]:
    """The mesh entry served for this character's CURRENT outfit (carrying
    ``backend`` and ``rig``), or None when there is none."""
    from app.core.model3d import get_model3d_info
    info = get_model3d_info(name)
    return info.get("model") or None


def character_model_pending(name: str) -> bool:
    """True while a mesh generation for this character is already running."""
    from app.core import model3d
    with model3d._lock:
        return name in model3d._generating


def generate_character_model(name: str, backend: str,
                             signature: str = "") -> None:
    """Blocking mesh generation for one outfit combination, on ``backend``.

    ``signature`` empty = the combination the character is WEARING, and the
    existing mesh of that combination is replaced (``force``).  A given
    signature addresses one stored combination instead — the T-pose render of
    exactly that signature is the input, and the mesh is only made when it is
    missing, because a signature candidate exists precisely because it has no
    model yet.

    ``backend`` empty = routed: the mesh occasion chain of the character's
    rig (image routing).  A named ``backend`` is an explicit pick:
    ``generate_for_current_outfit`` hands it to ``service.generate_mesh``
    for an unrigged source, followed by the configured rig occasion. The rig
    delivery must match the character's required rig.

    Takes over ``model3d``'s own double-start guard: the producer is called
    directly (not through ``trigger_generation``, which is the thread
    wrapper), so the guard has to be held here or a parallel admin action
    would generate into the same file.  The guard keys on the CHARACTER, not
    on the combination — that is what ``model3d`` itself locks on, and two
    meshes of one character must not be generated at once anyway.
    """
    from app.core.model_refs import is_state_fork
    if is_state_fork(signature):
        raise RuntimeError("State fork mesh candidates are retired")
    from app.core import model3d
    with model3d._lock:
        if name in model3d._generating:
            raise CandidateBusy(f"{name}: model generation already running")
        model3d._generating.add(name)
    try:
        result = model3d.generate_for_current_outfit(
            name, force=not signature, backend_glob=backend,
            signature=signature or None)
    finally:
        with model3d._lock:
            model3d._generating.discard(name)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


def character_tpose_signatures(name: str) -> set:
    """Outfit signatures this character has a T-POSE RENDER for.

    That render is the one input ``model3d.generate_for_current_outfit``
    resolves (``find_ref_image(name, "tpose", signature)``) — for humanoids and
    animals alike: "tpose_animal" is a use-case STYLE, not a file kind, so both
    land under ``model_refs/tpose_<signature>``.
    """
    from app.core.outfit_batch import ref_signatures
    return ref_signatures(name, "tpose")


def character_model_signatures(name: str) -> set:
    """Outfit signatures this character already has a MESH for."""
    from app.core.outfit_batch import mesh_signatures
    return mesh_signatures(name)


def character_model_exists(name: str, signature: str) -> bool:
    """Whether the mesh of exactly this combination is on disk — the exact
    match, never the serving fallbacks (neutral/nearest): a candidate is about
    one signature, and another combination's model does not finish it."""
    from app.core.model3d import find_model3d
    return find_model3d(name, signature) is not None


# ---------------------------------------------------------------------------
# Location buildings
# ---------------------------------------------------------------------------

def locations() -> List[Dict[str, Any]]:
    from app.models.world import list_locations
    return list_locations()


def building_model(location_id: str) -> Optional[Dict[str, Any]]:
    """Sidecar of the ACTIVE building model (``backend`` …), or None when the
    location has no model.  An existing model whose sidecar is unreadable
    answers ``{}`` — present, but nothing is known about it.

    Deliberately NOT ``get_building_info``: that one assembles the whole admin
    panel and probes the mesh backends, the shrink backends and Blender on
    every call.  A scan asks this per location, so it stays a disk walk.
    """
    from app.core.location_model3d import find_building_model
    from app.core.model_store import read_sidecar
    path = find_building_model(location_id)
    if not path:
        return None
    return dict(read_sidecar(path) or {})


def building_source_image(location_id: str) -> str:
    """Gallery file name the building mesh is generated FROM, ``""`` when the
    location has none.

    The active model's own source image first — regenerating a building means
    re-meshing the very picture it was made from.  Without one (or when that
    file is gone) a gallery image typed ``"building-<view>"`` takes over;
    those types are the marker ``location_model3d`` itself reads.

    Among those the FRONT wins: this feeds a single-image mesher, which
    reconstructs the hidden sides from the one picture it gets, and a rear or
    flank shot makes it guess the face.  Only when no front exists does the
    newest of the other views stand in — newest within each group, so a
    re-rendered front still beats an older one.
    """
    from app.core.view_prompts import building_view
    from app.models.world import get_gallery_dir, get_gallery_image_types
    gallery = get_gallery_dir(location_id)
    stored = str((building_model(location_id) or {}).get("source_image")
                 or "").strip()
    if stored and (gallery / stored).exists():
        return stored
    front, front_mtime = "", -1.0
    other, other_mtime = "", -1.0
    for name, image_type in (get_gallery_image_types(location_id) or {}).items():
        view = building_view(image_type)
        if not view:
            continue
        path = gallery / name
        if not path.exists():
            continue
        mtime = path.stat().st_mtime
        if view == "front":
            if mtime > front_mtime:
                front, front_mtime = name, mtime
        elif mtime > other_mtime:
            other, other_mtime = name, mtime
    return front or other


#: Job kind this module claims a building's in-flight slot under.  ``_generate``
#: does not take the slot itself — only the ``trigger_*`` wrappers do — so a
#: direct caller has to hold it, or a parallel admin run would mesh the same
#: subject a second time.
_BUILDING_JOB_KIND = "improvement"


def generate_building_model(location_id: str, backend: str) -> None:
    """Blocking mesh generation for a location's building, on ``backend``
    (empty = routed on the "mesh_building" chain)."""
    from app.core import location_model3d
    # Someone else's job on this subject (the admin's, a shrink run) — the
    # claim below cannot see it, because the mesh jobs key by image+backend+tier.
    if location_model3d.is_pending(location_id):
        raise CandidateBusy(f"{location_id}: model generation already running")
    source_image = building_source_image(location_id)
    if not source_image:
        raise RuntimeError("no building image")
    if not location_model3d.claim_job(location_id, kind=_BUILDING_JOB_KIND):
        raise CandidateBusy(f"{location_id}: model generation already running")
    try:
        result = location_model3d._generate(location_id, source_image, backend)
    finally:
        location_model3d.release_job(location_id, kind=_BUILDING_JOB_KIND)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


# ---------------------------------------------------------------------------
# Props
# ---------------------------------------------------------------------------

def props() -> List[Dict[str, Any]]:
    from app.core.props import list_props
    return list_props()


#: What separates a prop id from the model VARIANT a candidate addresses.
#: A prop carries several meshes of the same object (E2.3) and the improvement
#: engine may re-generate any of them (spec-bild-props-v2.md E5), so every
#: ident WRITTEN here names its variant by index — variant 0 included (ruling
#: V8). A bare id is the LEGACY shape only: it is still READ, as "whichever
#: variant this prop serves unqualified", so candidate keys stored before
#: variants were addressable keep naming what they named.
PROP_VARIANT_SEP = "#"


def split_prop_ident(ident: str) -> Tuple[str, Optional[int]]:
    """``"<prop id>#<index>"`` → ``(prop id, index)``; a BARE id →
    ``(prop id, None)``, which every reader resolves to the PRIMARY variant.

    A bare id is the LEGACY shape (ruling V8): candidate keys written before
    variants were addressable, and they must keep naming what they named —
    "whichever variant this prop serves unqualified". Nothing writes one any
    more, :func:`prop_ident` always states the index.

    Junk behind the separator is NOT an error: an ident is a stored candidate
    key, and a hand-edited one must fall back to the primary variant rather
    than take an improvement run down."""
    pid, sep, index = str(ident or "").partition(PROP_VARIANT_SEP)
    if not sep:
        return pid, None
    try:
        return pid, int(index)
    except (TypeError, ValueError):
        return pid, None


def prop_ident(prop_id: str, variant: Optional[int] = None) -> str:
    """The subject ident of ONE variant — the inverse of
    :func:`split_prop_ident`.

    THE INDEX IS ALWAYS STATED, index 0 included (ruling V8). Index 0 is NOT
    the same subject as the bare id: the primary variant is the first
    EFFECTIVELY ACTIVE one, which moves with the season tags and the on/off
    toggles — so a bare ident for variant 0 would read the primary's mesh, be
    labelled "variant 1" and re-mesh whatever is primary today. ``None`` still
    answers with the bare id, because that IS "the primary one, whichever it
    is" — the shape legacy candidate keys carry."""
    if variant is None:
        return prop_id
    return f"{prop_id}{PROP_VARIANT_SEP}{int(variant)}"


def prop_variants(prop_id: str) -> List[Dict[str, Any]]:
    """Every model variant of one prop, active or not (the store's list)."""
    from app.core.props import list_variants
    return list_variants(prop_id)


def prop_model(ident: str) -> Optional[Dict[str, Any]]:
    """The ACTIVE mesh entry (carrying ``backend``) of the variant ``ident``
    addresses, or None."""
    from app.core.props import list_models
    pid, variant = split_prop_ident(ident)
    for entry in list_models(pid, variant):
        if entry.get("active"):
            return entry
    return None


def prop_has_source(ident: str) -> bool:
    """Whether the addressed variant has the product shot a re-mesh needs.
    Without it there is nothing to generate FROM — such a prop is not a
    candidate for anything here."""
    from app.core.props import source_path
    pid, variant = split_prop_ident(ident)
    return source_path(pid, variant) is not None


def generate_prop_model(ident: str, backend: str) -> None:
    """Blocking re-mesh of an existing source image, on ``backend`` (empty =
    routed on the "mesh_object" chain).

    ``ident`` names the VARIANT this run is about (``"<prop id>#<index>"``, a
    bare id = the primary one): a prop carries several meshes of the same
    object, and replacing the backend of one of them must re-generate THAT
    one — not the primary variant's mesh in its place (E5).

    ``mesh_only``: the picture stays, only the mesh is made again — an idle
    improvement must not spend an image render on a product shot that is
    already there. The face budgets come from the variant as well: ``_generate``
    reads them where the caller passes none, which is exactly this path.

    Holds the same job slot ``props.trigger_generation`` holds — ``_generate``
    does not take it itself.
    """
    from app.core import props as props_module
    prop_id, variant = split_prop_ident(ident)
    if props_module.is_pending(prop_id):
        raise CandidateBusy(f"{ident}: model generation already running")
    key = props_module._gen_key(prop_id, variant, backend)
    with props_module._lock:
        if key in props_module._generating:
            raise CandidateBusy(f"{ident}: model generation already running")
        props_module._generating.add(key)
    try:
        result = props_module._generate(prop_id, "", "", "", backend,
                                        mesh_only=True, variant=variant)
    finally:
        with props_module._lock:
            props_module._generating.discard(key)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


def generate_prop_image(ident: str, backend: str) -> None:
    """Fill one variant's front image under the manual producer's job guard."""
    from app.core import props as props_module
    from app.imagegen.routing import NoRouteError
    prop_id, variant = split_prop_ident(ident)
    if prop_has_source(ident):
        return
    # The producer turns an unresolvable "prop" chain into ok=False, which
    # would count as a failed attempt; nothing routable right now is load.
    if not backend and not default_mesh_backend("prop"):
        raise CandidateBusy("no backend available for prop right now")
    if props_module.is_pending(prop_id):
        raise CandidateBusy(f"{ident}: image generation already running")
    key = props_module._gen_key(prop_id, variant, backend)
    with props_module._lock:
        if key in props_module._generating:
            raise CandidateBusy(f"{ident}: image generation already running")
        props_module._generating.add(key)
    try:
        if prop_has_source(ident):
            return
        try:
            result = props_module._generate(prop_id, "", "", backend, "",
                                            image_only=True, variant=variant)
        except NoRouteError as exc:
            if exc.__cause__ is not None:
                raise
            raise CandidateBusy(str(exc)) from exc
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "image generation failed"))
    finally:
        with props_module._lock:
            props_module._generating.discard(key)


# ---------------------------------------------------------------------------
# Character expressions
# ---------------------------------------------------------------------------

def expression_missing(name: str) -> bool:
    """Whether the selected set's default image is missing for the worn outfit."""
    from app.core.expression_regen import expression_snapshot, get_cached_expression
    try:
        return get_cached_expression(expression_snapshot(name)) is None
    except Exception:  # noqa: BLE001 — an unreadable cache is "not done"
        return True


def generate_expression(name: str) -> None:
    """Render the default through the same dedup/publication path as NPC finishing."""
    from app.core import expression_regen
    request = expression_regen.expression_snapshot(name)
    if expression_regen.expression_status(request)["state"] in ("pending", "running"):
        raise CandidateBusy(f"{name}: expression render already running")
    if expression_regen.generate_expression_image(request) is None:
        raise RuntimeError("expression render failed")


# ---------------------------------------------------------------------------
# Character images
# ---------------------------------------------------------------------------

def character_profile(name: str) -> Optional[Dict[str, Any]]:
    """The character's CURRENT profile image as
    ``{filename, path, backend, prompt, routing meta (ROUTE_META_KEYS), source_file}``, or
    None when there is none.

    "Current" is what the profile field says — the same resolution
    ``GET /characters/{name}/images/profile`` does
    (``get_character_profile_image`` + the images dir).  ``backend`` is what
    the image's own meta records as its maker, ``prompt`` the prompt it was
    generated from; either may be empty for a hand-uploaded picture, and a
    caller that wants to RENDER needs the prompt.  ``fallback_from`` is the
    image-routing marker of a render that did not run on its intended backend
    (None otherwise); ``source_file`` the picture this portrait was
    re-rendered FROM (``""`` for an original).
    """
    from app.models.character import (get_character_image_metadata,
                                      get_character_image_prompts,
                                      get_character_images_dir,
                                      get_character_profile_image)
    filename = str(get_character_profile_image(name) or "").strip()
    if not filename:
        return None
    path = get_character_images_dir(name) / filename
    if not path.exists():
        return None
    meta = get_character_image_metadata(name).get(filename) or {}
    return {
        "filename": filename,
        "path": str(path),
        "backend": str(meta.get("backend") or ""),
        "prompt": str(get_character_image_prompts(name).get(filename) or ""),
        **{k: meta.get(k) or None for k in ROUTE_META_KEYS},
        "source_file": str(meta.get("source_file") or ""),
    }


def regenerate_profile(name: str, backend: str) -> None:
    """Blocking re-render of the character's PROFILE image on ``backend``.

    ``create_new=True``: the old portrait stays in the gallery (decision E5) —
    a re-render on another backend is an offer, not a replacement, and the
    previous one has to remain recoverable.  ``use_room=False``: a portrait is
    not a scene, so the room reference slot stays free for the face.

    Afterwards the new file becomes the profile and the expression cache is
    dropped: every cached variant was derived from the OLD portrait, and
    ``generate_expression_image`` has no backend selector — the only way the
    target backend reaches the expressions is by deriving them again from the
    new portrait.

    The new file names the old portrait as ``source_file`` (in the producer's
    own meta write): the old one stays in the gallery, and without it a
    re-render of the old one's fallback marker could not see that its
    replacement already exists.

    There is no double-start guard on this path (neither ``character_ops`` nor
    ``image_regenerate`` keeps an in-flight set for a character's portrait);
    the one :class:`CandidateBusy` here is a backend that is not available
    (any more) when the render starts.
    """
    from app.core.expression_regen import clear_expression_cache
    from app.models.character import set_character_profile_image
    from app.skills.image_regenerate import (ExplicitBackendUnavailable,
                                             regenerate_image)
    current = character_profile(name)
    if not current:
        raise RuntimeError("no profile image")
    if not current["prompt"]:
        raise RuntimeError("profile image has no stored prompt")
    try:
        ok, _final_prompt, new_path = regenerate_image(
            name, current["path"], current["prompt"], backend_name=backend,
            create_new=True, use_room=False, source_file=current["filename"])
    except ExplicitBackendUnavailable as gone:
        # The backend dropped out after the caller picked it — load, not a
        # defect of this portrait (the location path maps its 503 the same way).
        raise CandidateBusy(str(gone)) from gone
    if not ok or not new_path:
        raise RuntimeError("profile regenerate failed")
    set_character_profile_image(name, Path(new_path).name)
    clear_expression_cache(name)


def character_gallery_images(name: str) -> List[Dict[str, Any]]:
    """Every image of a character's gallery that can be re-rendered (it has a
    stored prompt) — the current PROFILE image excluded (the portrait is its
    own subject). Read from the image metas on every call."""
    from app.models.character import (get_character_image_metadata,
                                      get_character_image_prompts,
                                      get_character_images_dir,
                                      get_character_profile_image)
    images_dir = get_character_images_dir(name)
    profile = str(get_character_profile_image(name) or "").strip()
    prompts = get_character_image_prompts(name) or {}
    out: List[Dict[str, Any]] = []
    for filename, meta in (get_character_image_metadata(name) or {}).items():
        if filename == profile or not (images_dir / filename).exists():
            continue
        prompt = str(prompts.get(filename) or "").strip()
        if not prompt:
            continue
        out.append({"filename": filename, "path": str(images_dir / filename),
                    "backend": str(meta.get("backend") or ""), "prompt": prompt,
                    **{k: meta.get(k) or None for k in ROUTE_META_KEYS},
                    "source_file": str(meta.get("source_file") or ""),
                    "room_id": str(meta.get("room_id") or ""),
                    "location": str(meta.get("location") or ""),
                    # An explicit [] ("nobody") stays [] — only a missing
                    # entry becomes None (= detect the persons again).
                    "character_names": (list(meta["character_names"])
                                        if isinstance(meta.get("character_names"), list)
                                        else None)})
    return out


def regenerate_character_gallery_image(name: str, filename: str, backend: str) -> None:
    """Re-render ONE gallery image of a character EXPLICITLY on ``backend``
    (no routing, no fallback) as a NEW file whose meta names the original as
    ``source_file``. The original stays — the admin compares and deletes.

    ``source_file`` travels INTO the producer's own meta write, so a crash
    between render and bookkeeping can never leave a replacement without it
    (the candidate would be listed again and rendered twice). An empty
    ``backend`` is refused: the producer would route it and could land on a
    fallback again, with a new marker.

    The producer is reached through the module attribute so a smoke can swap
    it (the same seam ``regenerate_profile`` offers)."""
    from app.skills import image_regenerate
    if not str(backend or "").strip():
        raise RuntimeError("no backend given — a re-render runs explicitly")
    entry = next((g for g in character_gallery_images(name)
                  if g["filename"] == filename), None)
    if entry is None:
        raise RuntimeError(f"{filename}: nothing to render it from")
    try:
        ok, _final_prompt, new_path = image_regenerate.regenerate_image(
            name, entry["path"], entry["prompt"], backend_name=backend,
            create_new=True, use_room=True, room_id=entry["room_id"],
            location_id=entry["location"], character_names=entry["character_names"],
            source_file=filename)
    except image_regenerate.ExplicitBackendUnavailable as gone:
        # The backend dropped out after the caller picked it — load, not a
        # defect of this image (the location path maps its 503 the same way).
        raise CandidateBusy(str(gone)) from gone
    if not ok or not new_path:
        raise RuntimeError("gallery regenerate failed")


# ---------------------------------------------------------------------------
# Location gallery images
# ---------------------------------------------------------------------------

def gallery_images(location_id: str) -> List[Dict[str, Any]]:
    """Every gallery image of a location that CAN be rendered again, as
    ``{filename, backend, prompt, room_id, prompt_type, source_file,
    routing meta (ROUTE_META_KEYS)}``.

    Three conditions, all from the image's own bookkeeping: the file has to
    exist (``delete_gallery_image`` drops the room/type/background entries but
    keeps the meta and the stored prompt, so a deleted picture would otherwise
    stay a candidate forever), the meta has to name the backend that made it
    (otherwise there is nothing to match a source backend against), and a
    prompt has to be stored (otherwise there is nothing to render FROM — the
    same rule that keeps a prop without its product shot out of
    ``fill_missing``).

    ``source_file`` is the picture this one was re-rendered FROM, ``""`` for an
    original — that is how a re-render can be recognised again after the fact.
    ``fallback_from`` is the image-routing marker of a render that did not run
    on its intended backend (None otherwise).
    """
    from app.models.world import (get_all_gallery_prompts, get_gallery_dir,
                                  get_gallery_image_metas,
                                  get_gallery_image_rooms,
                                  get_gallery_image_types)
    gallery = get_gallery_dir(location_id)
    prompts = get_all_gallery_prompts(location_id) or {}
    rooms = get_gallery_image_rooms(location_id) or {}
    types = get_gallery_image_types(location_id) or {}
    out: List[Dict[str, Any]] = []
    for filename, meta in (get_gallery_image_metas(location_id) or {}).items():
        backend = str((meta or {}).get("backend") or "").strip()
        prompt = str(prompts.get(filename) or "").strip()
        if not backend or not prompt or not (gallery / filename).exists():
            continue
        out.append({"filename": filename, "backend": backend, "prompt": prompt,
                    "room_id": str(rooms.get(filename) or ""),
                    "prompt_type": str(types.get(filename) or ""),
                    "source_file": str((meta or {}).get("source_file") or ""),
                    **{k: (meta or {}).get(k) or None for k in ROUTE_META_KEYS}})
    return out


def regenerate_gallery_image(location_id: str, filename: str,
                             backend: str) -> None:
    """Blocking re-render of one gallery image on ``backend``.

    The render lands as a NEW gallery file — the generator only overwrites in
    place when the caller asks for a replacement, and an improvement must not
    destroy the picture it was asked to improve upon.  The new image carries
    ``source_file`` (which picture it replaces) — the core writes it in the
    same meta write as the backend — and the background flag follows it: the core already flagged the new file, so the old one is
    unflagged here, or the location would show the picture that was meant to be
    superseded.

    ``settings_applied``: the stored prompt IS the finished prompt — the core
    saves the fully composed one (``save_gallery_prompt(loc_id, image_name,
    full_prompt)``).  Without the flag the core would run it through the
    composer a second time, weaving the use-case style in again (plus an LLM
    compose call where the use case enables it) and storing the doubled prompt,
    which would grow with every pass.  The negative falls back to the use-case
    negative, exactly as for the dialog.

    ``prompt_type`` travels with the prompt: without it a re-rendered map tile
    or building render would come back untyped and be flagged as a room
    background, which is exactly the leak the core's own type handling
    prevents.

    ``asyncio.run`` is correct here and not a shortcut: ``apply`` runs in a
    TaskQueue WORKER thread, which has no event loop of its own; the core is a
    coroutine only because the HTTP routes await it, and everything blocking
    inside it goes through ``asyncio.to_thread`` on whatever loop is running.
    """
    import asyncio

    from fastapi import HTTPException

    from app.core.world_ops import generate_gallery_image_core
    from app.imagegen.base import BackendBusyError
    from app.models.world import get_background_images, remove_background_image
    entry = next((g for g in gallery_images(location_id)
                  if g["filename"] == filename), None)
    if entry is None:
        raise RuntimeError(f"{filename}: nothing to render it from")
    try:
        result = asyncio.run(generate_gallery_image_core(location_id, {
            "prompt": entry["prompt"],
            "settings_applied": True,
            "room_id": entry["room_id"],
            "prompt_type": entry["prompt_type"],
            "backend": backend,
            # Written by the core in the same meta write as the backend.
            "source_file": filename,
        })) or {}
    except BackendBusyError as busy:
        raise CandidateBusy(str(busy)) from busy
    except HTTPException as e:
        # The core turns every "come back later" into a 503: a saturated
        # backend (BackendBusyError), an unavailable one, no image service at
        # all. None of those is a defect of this candidate, and counting them
        # as attempts would skip the step permanently after two of them.
        if e.status_code == 503:
            raise CandidateBusy(str(e.detail)) from e
        raise
    # Every real failure inside the core raises — a result without a file name
    # would mean it returned something else entirely.
    new_name = str(result.get("image") or "").strip()
    if not new_name:
        raise RuntimeError("gallery render produced no image")
    if new_name in get_background_images(location_id):
        remove_background_image(location_id, filename)


# ---------------------------------------------------------------------------
# Clothing item images
# ---------------------------------------------------------------------------

def clothing_items() -> List[Dict[str, Any]]:
    """World-owned clothing definitions, not the cross-world shared library."""
    from app.models.inventory import list_items
    return [item for item in list_items()
            if item.get("id") and item.get("category") == "outfit_piece"]


def clothing_image_done(item_id: str) -> bool:
    """A selected image must exist on disk. Gone/non-clothing items need no work."""
    from app.models.inventory import get_item, get_item_image_path
    item = get_item(item_id)
    if not item or item.get("_shared") or item.get("category") != "outfit_piece":
        return True
    return bool(item.get("image") and get_item_image_path(item_id))


def generate_clothing_image(item_id: str, backend: str = "") -> None:
    """Use the blocking item producer and preserve typed load/failure errors."""
    from app.imagegen.routing import NoRouteError
    from app.routes.inventory import generate_item_image_sync
    # The queue may have waited while an admin filled the image or removed the
    # item. Never overwrite that image or resurrect a deleted definition.
    if clothing_image_done(item_id):
        return
    try:
        ok = generate_item_image_sync(item_id, overrides={"backend": backend}, raise_errors=True)
    except NoRouteError as exc:
        # Exhausting a chain after a render failed is a failed attempt, not
        # initial unavailability. Routing preserves that failure as the cause.
        if exc.__cause__ is not None:
            raise
        raise CandidateBusy(str(exc)) from exc
    if not ok:
        raise RuntimeError(f"{item_id}: clothing image generation failed")


# ---------------------------------------------------------------------------
# Walkable surfaces
# ---------------------------------------------------------------------------
#
# Both helpers answer in the same shape — ``(a, b, label, model file,
# orientation fix, target_m, measure)`` — because a surface subject is always
# "one model file under one fix, placed at one world size", whatever identifies
# it.  The fix travels with the file: a baked lattice is only valid under the
# rotation it was made with (spec-surface-height § 4).  The world size travels
# with it too: the lattice step is 0.25 WORLD metres but is cast in the model's
# own units, so the bake has to know the ``max_m``/``measure`` the placement
# spec will scale this model by — the same numbers the landing bakes pass.

def room_models() -> List[Tuple[str, str, str, Path, Dict[str, Any], float, str]]:
    """``(location_id, room_id, label, model file, fix, target_m, measure)`` of
    every LAID-OUT room that has a model.

    A room without a floor plan is placed in no scene, so a lattice baked for
    its diorama would never be read — it is not a subject at all, the same way
    a prop without its product shot is none for ``fill_missing``.

    The file is the one the PAYLOAD serves (``find_building_model`` — the
    gallery's active model with the tier fallback, exactly what
    ``model_meta``/the scene recipe read the surface from), not the full tier
    the landing bake picks: a room whose only model is a distance mesh still
    needs the lattice its clients will ask for.
    """
    from app.core.location_model3d import find_building_model, surface_target_m
    from app.core.model_store import read_sidecar
    out: List[Tuple[str, str, str, Path, Dict[str, Any], float, str]] = []
    for location in locations():
        loc_id = str(location.get("id") or "")
        if not loc_id:
            continue
        for room in location.get("rooms") or []:
            if not isinstance(room, dict) or not room.get("layout"):
                continue
            room_id = str(room.get("id") or "")
            if not room_id:
                continue
            path = find_building_model(loc_id, room_id)
            if not path:
                continue
            label = (f"{location.get('name') or loc_id} / "
                     f"{room.get('name') or room_id}")
            rotation = dict(read_sidecar(path) or {}).get("rotation") or {}
            # The diorama's own scale law (``scene_recipe.diorama_max_m``),
            # read off the file that will be served — never a second reading of
            # the layout here.
            out.append((loc_id, room_id, label, path, rotation,
                        surface_target_m(loc_id, room_id, path, room), "xz"))
    return out


def prop_model_variants() -> List[Tuple[str, int, str, Path, Dict[str, Any],
                                        float, str]]:
    """``(prop_id, variant index, label, model file, fix, target_m, measure)``
    of every ACTIVE prop variant that has a mesh.

    The index set is ``props``' own — manually active and capped at
    ``variant_max``, the very set the landing bake walks
    (``props.bake_surfaces``) — and deliberately NOT the season-filtered one:
    a variant that is out of season right now still renders in its own season,
    and a lattice is baked from the mesh, not from the calendar.

    Indices are STORE indices, like everywhere in ``props``; the fix belongs to
    the FILE (spec-bild-props-v2.md E1) — every variant is its own mesh with
    its own dial, read beside it through ``props.file_areas``.
    """
    from app.core import props as prop_store
    out: List[Tuple[str, int, str, Path, Dict[str, Any], float, str]] = []
    for prop in props():
        prop_id = str(prop.get("id") or "")
        if not prop_id:
            continue
        meta = prop_store.read_sidecar(prop_id)
        if not meta:
            continue
        entries = prop_store._variant_list(meta)
        for idx in prop_store._active_indices(entries):
            path = prop_store.model_path(prop_id, variant=idx)
            if not path:
                continue
            label = str(prop.get("name") or prop_id)
            if idx:
                label = f"{label} (variant {idx})"
            # The world size THIS variant renders at, and the prop's own
            # measure — exactly what ``_prop_models`` puts on the placement
            # spec (``max_m`` = the largest of the three dims, ``measure`` xyz).
            out.append((prop_id, idx, label, path,
                        prop_store.file_areas(path)["rotation"],
                        max(prop_store.variant_dims(meta, idx).values()), "xyz"))
    return out


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def image_backend_options() -> List[Dict[str, str]]:
    """The image backends the admin form offers, in ``ParamField.options``
    shape.  Inpaint backends are left out: they need a mask, so they can never
    be the source or the target of a plain re-render — the render dialogs
    filter them the same way."""
    from app.core.world_ops import build_imagegen_options
    return [{"value": o["name"], "label": o["label"]}
            for o in build_imagegen_options().get("options", [])
            if is_generator_backend(o)]


# ---------------------------------------------------------------------------
# Mesh backends
# ---------------------------------------------------------------------------

#: The rigs a CHARACTER mesh can be bound to (``model3d.required_rig``):
def mesh_backend_options() -> List[Dict[str, str]]:
    """Offer enabled img2mesh backends, including configured offline picks."""
    from app.imagegen.service import get_image_service
    return [{"value": b.name, "label": b.name}
            for b in get_image_service().backends
            if b.instance_enabled and getattr(b, "MEDIA_TYPE", "image") == "mesh"
            and b.category == "img2mesh"]


def is_img2mesh_backend(name: str) -> bool:
    """Whether the explicit target is a configured image-to-mesh backend.

    Configuration only: offline backends must not make candidates disappear.
    All img2mesh backends can supply any character, building or prop source.
    """
    from app.core import config
    from app.imagegen.routing import describe_config_backend
    name = str(name or "").strip()
    for entry in config.get("image_generation.backends", []) or []:
        if not isinstance(entry, dict) or str(entry.get("name") or "").strip() != name:
            continue
        kind = describe_config_backend(entry)
        return kind["media"] == "mesh" and kind["category"] == "img2mesh"
    return False


def default_mesh_backend(occasion: str, character: str = "") -> str:
    """What the OCCASION's chain resolves to right now (image routing — any
    occasion, the image ones included),
    ``""`` when nothing is available. ``character`` applies that character's
    render-target override, just as the mesh producer does."""
    from app.imagegen.routing import explain_occasion
    return str(explain_occasion(occasion, character).get("resolved") or "").strip()
