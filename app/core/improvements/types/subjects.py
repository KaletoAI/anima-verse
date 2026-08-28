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


def generate_character_model(name: str, backend: str) -> None:
    """Blocking mesh generation for the worn outfit, on ``backend``.

    Takes over ``model3d``'s own double-start guard: the producer is called
    directly (not through ``trigger_generation``, which is the thread
    wrapper), so the guard has to be held here or a parallel admin action
    would generate into the same file.
    """
    from app.core import model3d
    with model3d._lock:
        if name in model3d._generating:
            raise CandidateBusy(f"{name}: model generation already running")
        model3d._generating.add(name)
    try:
        result = model3d.generate_for_current_outfit(
            name, force=True, backend_glob=backend)
    finally:
        with model3d._lock:
            model3d._generating.discard(name)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


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
    file is gone) the newest gallery image typed ``"building"`` takes over;
    that type is the marker ``location_model3d`` itself reads.
    """
    from app.models.world import get_gallery_dir, get_gallery_image_types
    gallery = get_gallery_dir(location_id)
    stored = str((building_model(location_id) or {}).get("source_image")
                 or "").strip()
    if stored and (gallery / stored).exists():
        return stored
    newest, newest_mtime = "", -1.0
    for name, image_type in (get_gallery_image_types(location_id) or {}).items():
        if image_type != "building":
            continue
        path = gallery / name
        if not path.exists():
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest, newest_mtime = name, mtime
    return newest


#: Job kind this module claims a building's in-flight slot under.  ``_generate``
#: does not take the slot itself — only the ``trigger_*`` wrappers do — so a
#: direct caller has to hold it, or a parallel admin run would mesh the same
#: subject a second time.
_BUILDING_JOB_KIND = "improvement"


def generate_building_model(location_id: str, backend: str) -> None:
    """Blocking mesh generation for a location's building, on ``backend``."""
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


def prop_model(prop_id: str) -> Optional[Dict[str, Any]]:
    """The prop's ACTIVE mesh entry (carrying ``backend``), or None."""
    from app.core.props import list_models
    for entry in list_models(prop_id):
        if entry.get("active"):
            return entry
    return None


def prop_has_source(prop_id: str) -> bool:
    """Whether the prop's primary variant has the product shot a re-mesh needs.
    Without it there is nothing to generate FROM — such a prop is not a
    candidate for anything here."""
    from app.core.props import source_path
    return source_path(prop_id) is not None


def generate_prop_model(prop_id: str, backend: str) -> None:
    """Blocking re-mesh of the prop's existing source image, on ``backend``.

    ``mesh_only``: the picture stays, only the mesh is made again — an idle
    improvement must not spend an image render on a product shot that is
    already there.

    Holds the same job slot ``props.trigger_generation`` holds — ``_generate``
    does not take it itself.  The variant is the PRIMARY one (``None``), which
    is the variant every reader here looks at.
    """
    from app.core import props as props_module
    if props_module.is_pending(prop_id):
        raise CandidateBusy(f"{prop_id}: model generation already running")
    key = props_module._gen_key(prop_id, None, backend)
    with props_module._lock:
        if key in props_module._generating:
            raise CandidateBusy(f"{prop_id}: model generation already running")
        props_module._generating.add(key)
    try:
        result = props_module._generate(prop_id, "", "", "", backend,
                                        mesh_only=True)
    finally:
        with props_module._lock:
            props_module._generating.discard(key)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


# ---------------------------------------------------------------------------
# Character expressions
# ---------------------------------------------------------------------------

def expression_missing(name: str) -> bool:
    """Whether the DEFAULT expression variant (mood "", pose "", worn outfit)
    is missing — the same question the NPC finish gate asks, and a PEEK: a
    check must not forge the variant's LRU bookkeeping."""
    from app.core.expression_regen import peek_cached_expression
    from app.core.model_refs import current_outfit_state
    try:
        pieces, items, _sig = current_outfit_state(name)
        return peek_cached_expression(name, "", "", equipped_pieces=pieces,
                                      equipped_items=items) is None
    except Exception:  # noqa: BLE001 — an unreadable cache is "not done"
        return True


def generate_expression(name: str) -> None:
    """Blocking render of that default variant — the generator directly, so the
    per-character ``expression_variants_enabled`` gate stays out of it (the
    same call ``npc_assets`` makes).  It swallows every failure and answers
    None, so the complaint is worded here.

    ``generate_expression_image`` does not register in the module's own
    in-flight set — only the trigger path does — so the busy question is asked
    with ``is_generating`` on the exact variant coordinates.
    """
    from app.core import expression_regen
    from app.core.model_refs import current_outfit_state
    pieces, items, _sig = current_outfit_state(name)
    if expression_regen.is_generating(name, "", "", equipped_pieces=pieces,
                                      equipped_items=items):
        raise CandidateBusy(f"{name}: expression render already running")
    if expression_regen.generate_expression_image(
            name, "", "", equipped_pieces=pieces, equipped_items=items) is None:
        raise RuntimeError("expression render failed")


# ---------------------------------------------------------------------------
# Character images
# ---------------------------------------------------------------------------

def character_profile(name: str) -> Optional[Dict[str, Any]]:
    """The character's CURRENT profile image as
    ``{filename, path, backend, prompt}``, or None when there is none.

    "Current" is what the profile field says — the same resolution
    ``GET /characters/{name}/images/profile`` does
    (``get_character_profile_image`` + the images dir).  ``backend`` is what
    the image's own meta records as its maker, ``prompt`` the prompt it was
    generated from; either may be empty for a hand-uploaded picture, and a
    caller that wants to RENDER needs the prompt.
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

    There is no double-start guard on this path (neither ``character_ops`` nor
    ``image_regenerate`` keeps an in-flight set for a character's portrait), so
    nothing can be reported as :class:`CandidateBusy` here.
    """
    from app.core.expression_regen import clear_expression_cache
    from app.models.character import set_character_profile_image
    from app.skills.image_regenerate import regenerate_image
    current = character_profile(name)
    if not current:
        raise RuntimeError("no profile image")
    if not current["prompt"]:
        raise RuntimeError("profile image has no stored prompt")
    ok, _final_prompt, new_path = regenerate_image(
        name, current["path"], current["prompt"], backend_name=backend,
        create_new=True, use_room=False)
    if not ok or not new_path:
        raise RuntimeError("profile regenerate failed")
    set_character_profile_image(name, Path(new_path).name)
    clear_expression_cache(name)


# ---------------------------------------------------------------------------
# Location gallery images
# ---------------------------------------------------------------------------

def gallery_images(location_id: str) -> List[Dict[str, Any]]:
    """Every gallery image of a location that CAN be rendered again, as
    ``{filename, backend, prompt, room_id, prompt_type, source_file}``.

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
                    "source_file": str((meta or {}).get("source_file") or "")})
    return out


def regenerate_gallery_image(location_id: str, filename: str,
                             backend: str) -> None:
    """Blocking re-render of one gallery image on ``backend``.

    The render lands as a NEW gallery file — the generator only overwrites in
    place when the caller asks for a replacement, and an improvement must not
    destroy the picture it was asked to improve upon.  Afterwards the new image
    carries ``source_file`` (which picture it replaces), and the background
    flag follows it: the core already flagged the new file, so the old one is
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
    from app.models.world import (get_background_images,
                                  get_gallery_image_metas,
                                  remove_background_image,
                                  set_gallery_image_meta)
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
    # Merge: the core has just written this image's meta (backend, model,
    # LoRAs) and `set_gallery_image_meta` REPLACES the entry.
    meta = dict((get_gallery_image_metas(location_id) or {}).get(new_name) or {})
    meta["source_file"] = filename
    set_gallery_image_meta(location_id, new_name, meta)
    if new_name in get_background_images(location_id):
        remove_background_image(location_id, filename)


# ---------------------------------------------------------------------------
# Walkable surfaces
# ---------------------------------------------------------------------------
#
# Both helpers answer in the same shape — ``(a, b, label, model file,
# orientation fix, target_m, measure)`` — because a surface subject is always
# "one model file under one fix, placed at one world size", whatever identifies
# it.  The fix travels with the file: a baked lattice is only valid under the
# rotation it was made with (spec-surface-height § 4).  The world size travels
# with it too: the lattice step is 0,25 WORLD metres but is cast in the model's
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
                        surface_target_m(loc_id, room_id, path), "xz"))
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
    the prop, because one orientation dial turns every variant of it.
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
        rotation = meta.get("rotation") or {}
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
            out.append((prop_id, idx, label, path, rotation,
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
            if o.get("category") != "inpaint"]


# ---------------------------------------------------------------------------
# Mesh backends
# ---------------------------------------------------------------------------

def mesh_backend_options() -> List[Dict[str, str]]:
    """The mesh backends the admin form offers, in ``ParamField.options``
    shape."""
    from app.core import model3d
    return [{"value": b["name"], "label": b["name"]}
            for b in model3d.list_mesh_backends()["backends"]]


def default_mesh_backend() -> str:
    """The admin's default mesh backend, ``""`` when none is configured."""
    from app.core import model3d
    return str(model3d.list_mesh_backends().get("default") or "").strip()
