"""Catalog editor routes — the two finite render-key axes.

`pose` and `expression` are the ONLY keys under which image variants are
cached and animation clips are resolved (plan-pose-katalog.md). Each axis has
TWO layers (``pose_catalog.STORES``): the curated, tracked JSON file
(``shared/templates/<axis>/<axis>_catalog.json``, ``pose_catalog.catalog_path``)
and the world's own layer in its ``world.db``, which overrides the file per
key and holds what must never be committed. This router is the write surface
behind the Poses admin tab: edit entries in either layer, approve/dismiss the
candidates the resolver recorded for free text it could not absorb, and clear
the rendered expression images after a prompt edit (the image cache is keyed
by the catalog KEY, so an edited prompt does not invalidate anything by
itself).

The pose axis carries a second, much smaller vocabulary in the same two
layers: the PLACE TYPES (``groups``) a marker speaks, edited through
``GET``/``PUT /poses/groups``. Every pose names exactly one of them.

Free text never creates an entry any more — the catalog grows only through the
approval flow here. The animation vocabulary is NOT hardcoded either: it is
whatever clips the world currently ships.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import Path as PathParam

from app.core import expression_pose_maps as epm
from app.core import pose_catalog
from app.core.auth_dependency import require_admin
from app.core.pose_catalog_edit import (
    CatalogEditError, after_write, alias_owner, catalog_txn, read_store,
    require_free_aliases, store_of, validate_group, validate_key,
    validate_synonyms, write_store,
)
from app.core.log import get_logger

# Compatibility for existing smoke imports; implementation lives in core.
_alias_owner = alias_owner

logger = get_logger(__name__)

router = APIRouter(prefix="/poses", tags=["poses"])
DEFAULT_ANIMATION_VARIANTS = 3
_TASK_ID_PATTERN = r"^task_[0-9a-f]+$"


def _axis(axis: str) -> str:
    """Validated axis. An unknown value is a client error, never a 500 — the
    catalog helpers raise KeyError on anything but the two known axes."""
    value = (axis or "").strip().lower()
    if value not in pose_catalog.AXES:
        raise HTTPException(status_code=400, detail="unknown axis")
    return value


def _validated_store(raw: Any, fallback: str) -> str:
    """The store a write should target."""
    value = str(raw or "").strip().lower() or fallback
    if value not in pose_catalog.STORES:
        raise HTTPException(
            status_code=400,
            detail=f"store must be one of {', '.join(pose_catalog.STORES)}")
    return value


def _places(raw: Any) -> int:
    """Marker slots a PAIR pose consumes — 1 or 2, and it must be SAID.

    There is no sensible default: two bodies 6 cm apart fit on one slot, two
    dancers sweeping the floor need two, and the difference is not something
    the server can guess. A silent fallback to 2 is how every pair pose in the
    catalog came to claim two slots, which made a bed marker of capacity 1
    refuse a pose whose figures lie 19 cm apart. The editor shows the clip's
    measured distance beside the field so the choice is informed.
    """
    if raw is None or raw == "":
        raise HTTPException(
            status_code=400,
            detail="places is required for a pair pose (1 or 2)")
    try:
        return 2 if int(raw) >= 2 else 1
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="places must be 1 or 2")


def _yaw_offset(raw: Any) -> float:
    """Degrees the pair clip's frame turns against the marker facing."""
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="yaw_offset must be a number")


# ── Place types: the vocabulary a marker speaks ──────────────────────────
# Registered BEFORE the /{key} routes on purpose — FastAPI matches in
# declaration order, so a later `/groups` would be swallowed by `PUT /{key}`.

def _normalize_group(raw: Any) -> Dict[str, Any]:
    """One place type as it is stored: a label, the root drop as a fraction of
    the figure height (clamped to 0..1), the pose a click on such a marker
    sets, and whether the group's poses need a marker at all. The layer it
    goes to (``store``) is read by the caller, never stored in the document.

    ``needs_place`` defaults to True — a place type normally demands a
    marker; only a body shape one can strike anywhere (standing, kneeling)
    says otherwise.
    """
    raw = raw if isinstance(raw, dict) else {}
    try:
        drop = round(max(0.0, min(1.0, float(raw.get("root_drop") or 0.0))), 3)
    except (TypeError, ValueError):
        drop = 0.0
    return {"label": str(raw.get("label") or "").strip(),
            "root_drop": drop,
            "default": str(raw.get("default") or "").strip().lower(),
            "needs_place": bool(raw.get("needs_place", True))}


def _groups_problems(groups: Dict[str, Any], entries: Dict[str, Any]) -> List[str]:
    """Why a groups block may NOT be written: a group still named by a pose
    is missing, or a default is not a pose of its own group.

    A group with NO poses may carry an empty default — a place type has to
    exist before any pose can name it (``validate_group`` rejects an unknown one), so
    demanding a default from the start would make the block unable to grow.

    A group with ``needs_place: false`` is checked the same way: its poses
    still need a default, they just never get a marker.
    """
    problems: List[str] = []
    for key, entry in entries.items():
        g = str(entry.get("group") or "")
        if g and g not in groups:
            problems.append(f"place type '{g}' is still used by '{key}'")
    for g, spec in groups.items():
        d = spec.get("default", "")
        if not d and not any(str(e.get("group") or "") == g for e in entries.values()):
            continue
        if d not in entries or str(entries[d].get("group") or "") != g:
            problems.append(f"place type '{g}': default '{d}' is not a pose of this group")
    return problems


@router.get("/groups")
def list_groups(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """All place types, keyed by group id."""
    return {"groups": pose_catalog.get_groups()}


@router.put("/groups")
async def put_groups(request: Request,
                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Replaces the whole place-type block."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_put_groups_sync, body)


def _put_groups_sync(body: Any) -> Dict[str, Any]:
    """The blocking body of ``put_groups`` — runs in the threadpool.

    The EFFECTIVE block is replaced as a whole, so it is checked as a whole:
    dropping a type some pose still names, or pointing a default at a pose of
    another group, would leave the catalog invalid the moment it is written.
    Every group says which layer it goes to (``store``, default ``shared``):
    the world groups become the world layer as a whole; the shared file gets
    the shared groups — and keeps, untouched, its own version of a group the
    body moved to the world, because that version is the seed the world row
    overrides and comes back once the row is dropped.
    """
    try:
        raw = (body or {}).get("groups")
        if not isinstance(raw, dict) or not raw:
            raise HTTPException(status_code=400, detail="groups missing")
        by_store: Dict[str, Dict[str, Any]] = {s: {} for s in pose_catalog.STORES}
        for key, spec in raw.items():
            k = validate_key(key)
            store = _validated_store((spec or {}).get("store") if isinstance(spec, dict)
                                     else None, "shared")
            group = _normalize_group(spec)
            if not group["label"]:
                group["label"] = k
            by_store[store][k] = group
        with catalog_txn("pose"):
            data = read_store("pose")
            old_shared = data.get("groups") if isinstance(data.get("groups"), dict) else {}
            shared_block: Dict[str, Any] = dict(by_store["shared"])
            for k in by_store["world"]:
                if k in old_shared:
                    shared_block[k] = old_shared[k]
            effective = dict(shared_block)
            effective.update(by_store["world"])
            # Checked against the EFFECTIVE entries: a world pose may name a
            # world group, and a shared pose must still find its group.
            entries = {k: e for k, e in pose_catalog.get_catalog("pose").items()}
            problems = _groups_problems(effective, entries)
            if problems:
                raise HTTPException(status_code=400, detail="; ".join(problems))
            pose_catalog.replace_world_groups(by_store["world"])
            if shared_block != old_shared:
                data["groups"] = shared_block
                write_store("pose", data)
            else:
                after_write()
        return {"status": "success", "groups": pose_catalog.get_groups()}
    except CatalogEditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


@router.get("")
def list_entries(axis: str = Query("pose"),
                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """All catalog entries of an axis + the animation kinds that have clips
    (pose only) + the integrity problems of the catalog."""
    from app.core.pose_rename import CODE_NAMED_POSE_KEYS
    axis = _axis(axis)
    out: List[Dict[str, Any]] = []
    for key, entry in pose_catalog.get_catalog(axis).items():
        row = {
            "key": key,
            "prompt": entry.get("prompt", ""),
            "synonyms": entry.get("synonyms", []) or [],
            "animation": entry.get("animation", "") or "",
            "solo": bool(entry.get("solo", True)),
            "is_default": bool(entry.get("_default")),
            "axis": axis,
            # Which file this entry lives in. The editor writes it back where
            # it came from, and the list can show what would be committed.
            "store": entry.get("_store", "shared"),
        }
        if axis == "pose":
            # Place fields are POSE vocabulary — an expression has no place.
            # Read through the ACCESSORS, never off the entry: a solo pose has
            # no stored places/yaw_offset, and a raw `.get(..., 2)` would tell
            # the client 2 where the loader says 1.
            row["group"] = entry.get("group", "")
            row["places"] = pose_catalog.pose_places(key)
            row["yaw_offset"] = pose_catalog.pose_yaw_offset(key)
            # Whether POST /poses/{key}/rename accepts this key — the editor
            # hides the button for the keys the server code names literally.
            row["renamable"] = key not in CODE_NAMED_POSE_KEYS
        out.append(row)
    out.sort(key=lambda p: p["key"])
    from app.core.animation_clips import clip_meta, pair_kinds
    _pairs = pair_kinds() if axis == "pose" else []
    # How far apart the two figures stand at the anchor moment, per pair kind
    # — the clip's own measurement (`geometry.root_distance_m`). The editor
    # shows it beside the slot count so nobody has to guess how much room a
    # pair takes: 0.06 m is one body on top of another, 0.63 m is arm's
    # length. It is a MEASUREMENT, not the answer — a dance sweeps far more
    # floor than the distance between its dancers.
    _spans: Dict[str, float] = {}
    for _k in _pairs:
        _g = (clip_meta(_k) or {}).get("geometry") or {}
        _d = _g.get("root_distance_m")
        if isinstance(_d, (int, float)):
            _spans[_k] = round(float(_d), 3)
    return {
        "entries": out,
        "kinds": epm.available_animation_kinds() if axis == "pose" else [],
        # Kinds that exist as a PAIR clip (two halves, § A8a): such a pose is
        # a two-person one and has to carry solo: false.
        "pair_kinds": _pairs,
        "pair_spans": _spans,
        "groups": pose_catalog.get_groups() if axis == "pose" else {},
        "problems": pose_catalog.validate_catalog(axis),
    }


@router.post("")
async def create_entry(request: Request,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Creates a catalog entry on the given axis."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_create_entry_sync, _, body)


def _create_entry_sync(_: Dict[str, Any], body: Any) -> Dict[str, Any]:
    """The blocking body of ``create_entry`` — runs in the threadpool."""
    try:
        axis = _axis(body.get("axis") or "pose")
        key = validate_key(body.get("key"))
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt missing")
        animation = str(body.get("animation") or "").strip().lower()
        if axis == "pose" and not animation:
            raise HTTPException(status_code=400, detail="animation missing")
        group = validate_group(body.get("group")) if axis == "pose" else ""
        # A new entry defaults to the TRACKED catalog; the importer of a licensed
        # clip asks for "world" so its name never reaches a committed file.
        store = _validated_store(body.get("store"), "shared")
        with catalog_txn(axis):
            data = read_store(axis, store)
            if key in pose_catalog.get_catalog(axis):
                raise HTTPException(status_code=409, detail="Entry already exists")
            synonyms = validate_synonyms(body.get("synonyms") or [])
            require_free_aliases(axis, [key] + synonyms)

            entry: Dict[str, Any] = {"prompt": prompt, "synonyms": synonyms}
            if axis == "pose":
                entry["animation"] = animation
                entry["solo"] = bool(body.get("solo", True))
                entry["group"] = group
                if not entry["solo"]:
                    entry["places"] = _places(body.get("places"))
                    entry["yaw_offset"] = _yaw_offset(body.get("yaw_offset"))
            data["entries"][key] = entry
            write_store(axis, data, store)
        return {"status": "success", "key": key, "axis": axis, "store": store}
    except CatalogEditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# Fixed animation paths must precede the /{key} routes.
@router.post("/animations/generate", status_code=202)
async def generate_animation(request: Request,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Validate and enqueue a pose animation for the admin editor."""
    import asyncio
    from app.core import pose_animation

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    seed = body.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise HTTPException(status_code=400, detail="seed must be an integer")
    backend = body.get("backend", "")
    if not isinstance(backend, str):
        raise HTTPException(status_code=400, detail="backend must be a string")
    variants = body.get("variants", DEFAULT_ANIMATION_VARIANTS)
    if isinstance(variants, bool) or not isinstance(variants, int):
        raise HTTPException(status_code=400, detail="variants must be an integer")
    try:
        task_id = await asyncio.to_thread(
            pose_animation.submit, body.get("mode", ""),
            key=body.get("key", ""), raw_text=body.get("raw_text", ""),
            text=body.get("text", ""), hint=body.get("hint", ""),
            seed=seed, backend=backend, variants=variants)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id}


@router.get("/animations/jobs")
async def animation_jobs(request: Request,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Recent pose animation jobs for the admin editor."""
    import asyncio
    from app.core import pose_animation

    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit must be a positive integer") from exc
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be a positive integer")
    return {"jobs": await asyncio.to_thread(pose_animation.recent_jobs, min(limit, 100))}


@router.get("/animations/backends")
async def animation_backends(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The models the generate dialog offers (the pose_animation chain)."""
    import asyncio
    from app.imagegen.service import get_image_service

    # The service singleton may build itself (availability probes): off the loop.
    backends = await asyncio.to_thread(lambda: get_image_service().animation_backends())
    return {"backends": backends, "default_variants": DEFAULT_ANIMATION_VARIANTS}


@router.get("/animations/{task_id}/candidates/{index}/clip.fbx")
def animation_candidate_clip(request: Request,
                             task_id: str = PathParam(..., pattern=_TASK_ID_PATTERN),
                             index: int = PathParam(..., ge=0, le=15),
                             _: Dict[str, Any] = Depends(require_admin)):
    """One candidate's FBX for the preview player."""
    from app.core import pose_animation
    from app.core.http_files import etag_file_response

    try:
        path = pose_animation.candidate_clip(task_id, index)
    except pose_animation.ChoiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return etag_file_response(path, request, "application/octet-stream")


@router.post("/animations/{task_id}/choose")
async def choose_animation(request: Request,
                           task_id: str = PathParam(..., pattern=_TASK_ID_PATTERN),
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Publish one candidate as the pose's clip and catalog entry."""
    import asyncio
    from app.core import pose_animation

    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="body must be a JSON object") from exc
    index = body.get("index") if isinstance(body, dict) else None
    if isinstance(index, bool) or not isinstance(index, int):
        raise HTTPException(status_code=400, detail="index must be an integer")
    try:
        return await asyncio.to_thread(pose_animation.choose, task_id, index)
    except pose_animation.ChoiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/animations/{task_id}/discard")
async def discard_animation(task_id: str = PathParam(..., pattern=_TASK_ID_PATTERN),
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Drop every candidate of a job waiting for a choice."""
    import asyncio
    from app.core import pose_animation

    try:
        return await asyncio.to_thread(pose_animation.discard, task_id)
    except pose_animation.ChoiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.put("/{key}")
async def update_entry(key: str, request: Request, axis: str = Query("pose"),
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Updates prompt / synonyms / animation / solo of a catalog entry."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_update_entry_sync, key, axis, _, body)


def _update_entry_sync(key: str, axis: str, _: Dict[str, Any],
                       body: Any) -> Dict[str, Any]:
    """The blocking body of ``update_entry`` — runs in the threadpool."""
    try:
        axis = _axis(axis)
        key = key.strip().lower()
        with catalog_txn(axis):
            was = store_of(axis, key)
            # An entry may MOVE between the tracked catalog and the world layer
            # — that is how an entry which must not be committed gets out of the
            # tracked file again.
            store = _validated_store(body.get("store"), was)
            data = read_store(axis, was)
            entry = data["entries"].get(key)
            if entry is None:
                raise HTTPException(status_code=404, detail="Entry not found")
            if "prompt" in body:
                entry["prompt"] = str(body["prompt"] or "").strip()
            if "synonyms" in body:
                synonyms = validate_synonyms(body["synonyms"] or [])
                # The entry's OWN key is excluded: re-saving it with the synonyms
                # it already holds must stay legal.
                require_free_aliases(axis, synonyms, exclude_key=key)
                entry["synonyms"] = synonyms
            if "animation" in body and axis == "pose":
                anim = str(body["animation"] or "").strip().lower()
                if not anim:
                    raise HTTPException(status_code=400, detail="animation missing")
                entry["animation"] = anim
            if "solo" in body and axis == "pose":
                entry["solo"] = bool(body["solo"])
            if "group" in body and axis == "pose":
                entry["group"] = validate_group(body["group"])
            if "places" in body and axis == "pose":
                entry["places"] = _places(body["places"])
            if "yaw_offset" in body and axis == "pose":
                entry["yaw_offset"] = _yaw_offset(body["yaw_offset"])
            if axis == "pose" and entry.get("solo", True):
                # A solo pose occupies exactly one place and never turns — leaving
                # the pair fields behind would be a stray the catalog reports.
                entry.pop("places", None)
                entry.pop("yaw_offset", None)
            if store == was:
                data["entries"][key] = entry
                write_store(axis, data, store)
            else:
                # Write the new home FIRST: a crash between the two writes then
                # leaves the entry in both layers (the world layer wins, so the
                # game still sees the edited one), never in neither.
                target = read_store(axis, store)
                target["entries"][key] = entry
                write_store(axis, target, store)
                data["entries"].pop(key, None)
                write_store(axis, data, was)
        return {"status": "success", "key": key, "axis": axis, "store": store}
    except CatalogEditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


@router.delete("/{key}")
def delete_entry(key: str, axis: str = Query("pose"),
                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Deletes a catalog entry. The ``_default`` entry is not deletable — it
    is the target every unresolvable free text falls back to."""
    try:
        axis = _axis(axis)
        key = key.strip().lower()
        with catalog_txn(axis):
            store = store_of(axis, key)
            data = read_store(axis, store)
            entry = data["entries"].get(key)
            if entry is None:
                raise HTTPException(status_code=404, detail="Entry not found")
            if entry.get("_default"):
                raise HTTPException(status_code=400,
                                    detail="the default entry cannot be deleted")
            data["entries"].pop(key, None)
            write_store(axis, data, store)
        return {"status": "success", "key": key, "axis": axis, "store": store}
    except CatalogEditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


@router.post("/{key}/rename")
async def rename_entry(key: str, request: Request, axis: str = Query("pose"),
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Renames the KEY of a pose entry; every stored reference follows."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_rename_entry_sync, key, axis, body)


def _renamed(entries: Dict[str, Any], old: str, new: str) -> Dict[str, Any]:
    """``entries`` with ``old`` renamed to ``new`` IN PLACE of the order (the
    tracked file keeps its layout), and ``new`` dropped from the entry's own
    synonyms — a key is never its own synonym."""
    out: Dict[str, Any] = {}
    for k, entry in entries.items():
        if k == old:
            entry = dict(entry)
            if new in (entry.get("synonyms") or []):
                entry["synonyms"] = [s for s in entry["synonyms"] if s != new]
            k = new
        out[k] = entry
    return out


def _rename_entry_sync(key: str, axis: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``rename_entry`` — runs in the threadpool.

    Pose axis only. The catalog is rewritten first, inside the catalog lock:
    the entry in EVERY layer that holds it (a world row may override a shared
    entry of the same key) and every place-type default naming it, in the raw
    layer documents. The world's references follow afterwards
    (``pose_rename.rewrite_references``) — pointing them at the new key before
    it exists would be the worse order. The ``_default`` flag travels with
    the entry. The old key is NOT kept as a synonym.
    """
    try:
        from app.core import pose_rename
        axis = _axis(axis)
        if axis != "pose":
            raise HTTPException(status_code=400, detail="only pose keys can be renamed")
        old = key.strip().lower()
        new = validate_key((body or {}).get("new_key"))
        if new == old:
            raise HTTPException(status_code=400, detail="the new key is the old key")
        if old in pose_rename.CODE_NAMED_POSE_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"'{old}' is named by the server code and cannot be renamed")
        with catalog_txn(axis):
            catalog = pose_catalog.get_catalog(axis)
            if old not in catalog:
                raise HTTPException(status_code=404, detail="Entry not found")
            if new in catalog:
                raise HTTPException(status_code=409, detail="Entry already exists")
            # The entry's OWN synonyms are free for it — renaming onto one of them
            # is how a synonym becomes the key.
            require_free_aliases(axis, [new], exclude_key=old)
            stores: List[str] = []
            shared = read_store(axis, "shared")
            groups = shared.get("groups") if isinstance(shared.get("groups"), dict) else {}
            shared_changed = old in shared["entries"]
            if shared_changed:
                shared["entries"] = _renamed(shared["entries"], old, new)
                stores.append("shared")
            for spec in groups.values():
                if isinstance(spec, dict) and spec.get("default") == old:
                    spec["default"] = new
                    shared_changed = True
            world = pose_catalog.world_entries(axis)
            if old in world:
                pose_catalog.replace_world_entries(axis, _renamed(world, old, new))
                stores.append("world")
            world_groups = pose_catalog.world_groups()
            if any(g.get("default") == old for g in world_groups.values()):
                for g in world_groups.values():
                    if g.get("default") == old:
                        g["default"] = new
                pose_catalog.replace_world_groups(world_groups)
            if shared_changed:
                write_store(axis, shared, "shared")
            else:
                after_write()
        references = pose_rename.rewrite_references(old, new)
        return {"status": "success", "old_key": old, "key": new, "axis": axis,
                "stores": stores, "references": references}
    except CatalogEditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── Candidates: free text the catalog could not absorb ───────────────────

@router.get("/candidates")
def list_candidates(axis: str = Query("pose"), status: str = Query("open"),
                    _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Open candidates of an axis, MOST OFTEN SEEN FIRST, most recent as the
    tie-break (user ruling 2026-09-08 — the order ``list_candidates`` already
    returns).

    On the expression axis ``count`` counts the FIRST sighting per server
    process (the resolver memoizes there), so it reads as "seen" rather than
    as a hit count; on the pose axis every miss counts.
    """
    axis = _axis(axis)
    rows = pose_catalog.list_candidates(axis, status=status)
    return {"candidates": rows, "axis": axis}


@router.post("/candidates/approve")
async def approve_candidate(request: Request,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Absorbs a candidate into the catalog — either as a new entry
    (``key`` + ``prompt``, ``animation`` and ``group`` mandatory on the pose
    axis) or as a synonym of an existing entry (``as_synonym_of``, which
    inherits the target's place type and needs none of its own). The candidate row is
    deleted afterwards: it resolves now, and if it still does not, the miss
    has to show up again instead of hiding behind a terminal status.
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_approve_candidate_sync, _, body)


def _approve_candidate_sync(_: Dict[str, Any], body: Any) -> Dict[str, Any]:
    """The blocking body of ``approve_candidate`` — runs in the threadpool."""
    try:
        axis = _axis(body.get("axis") or "pose")
        raw_text = str(body.get("raw_text") or "").strip().lower()
        if not raw_text:
            raise HTTPException(status_code=400, detail="raw_text missing")
        with catalog_txn(axis):
            target = str(body.get("as_synonym_of") or "").strip().lower()
            # Attaching to an existing entry writes where THAT entry lives; a new
            # entry goes where the caller asks, tracked catalog by default.
            store = (store_of(axis, target) if target
                     else _validated_store(body.get("store"), "shared"))
            data = read_store(axis, store)

            if target:
                entry = data["entries"].get(target)
                if entry is None:
                    raise HTTPException(status_code=404, detail="Entry not found")
                owner = alias_owner(axis, raw_text)
                if owner and owner != target:
                    raise HTTPException(status_code=409,
                                        detail=f"'{raw_text}' already belongs to '{owner}'")
                synonyms = [str(s).strip().lower() for s in (entry.get("synonyms") or [])
                            if str(s).strip()]
                if raw_text != target and raw_text not in synonyms:
                    synonyms.append(raw_text)
                entry["synonyms"] = synonyms
                data["entries"][target] = entry
                key = target
            else:
                key = validate_key(body.get("key"))
                prompt = str(body.get("prompt") or "").strip()
                if not prompt:
                    raise HTTPException(status_code=400, detail="prompt missing")
                animation = str(body.get("animation") or "").strip().lower()
                # Only non-emptiness is checked: the kind vocabulary is
                # world-dependent (whatever clips exist), so an unknown kind is a
                # warning, not a wall.
                if axis == "pose" and not animation:
                    raise HTTPException(status_code=400, detail="animation missing")
                # A new pose entry is a new pose: same place-type rule as create,
                # or the catalog is invalid the moment the candidate is absorbed.
                group = validate_group(body.get("group")) if axis == "pose" else ""
                if key in pose_catalog.get_catalog(axis):
                    raise HTTPException(status_code=409, detail="Entry already exists")
                # The candidate text itself becomes a synonym unless it IS the key
                # — on top of whatever the admin typed into the form.
                synonyms: List[str] = []
                for alias in validate_synonyms(body.get("synonyms") or []) + [raw_text]:
                    if alias != key and alias not in synonyms:
                        synonyms.append(alias)
                require_free_aliases(axis, [key] + synonyms)
                entry = {"prompt": prompt, "synonyms": synonyms}
                if axis == "pose":
                    entry["animation"] = animation
                    entry["solo"] = bool(body.get("solo", True))
                    entry["group"] = group
                    if not entry["solo"]:
                        # Same as create: a pair pose carries its own slot count
                        # and clip rotation — dropping them here would silently
                        # approve every pair candidate as "2 places, 0°".
                        entry["places"] = _places(body.get("places"))
                        entry["yaw_offset"] = _yaw_offset(body.get("yaw_offset"))
                data["entries"][key] = entry

            write_store(axis, data, store)
        pose_catalog.delete_candidate(axis, raw_text)
        logger.info("candidate approved: %s/%r -> %r (%s)", axis, raw_text, key, store)
        return {"status": "success", "axis": axis, "key": key, "store": store}
    except CatalogEditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


@router.post("/candidates/dismiss")
async def dismiss_candidate(request: Request,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Marks a candidate as ``dismissed`` — it stays recorded but never shows
    up in the open list again."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_dismiss_candidate_sync, _, body)


def _dismiss_candidate_sync(_: Dict[str, Any], body: Any) -> Dict[str, Any]:
    """The blocking body of ``dismiss_candidate`` — runs in the threadpool."""
    axis = _axis(body.get("axis") or "pose")
    raw_text = str(body.get("raw_text") or "").strip().lower()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text missing")
    found = pose_catalog.set_candidate_status(axis, raw_text, "dismissed")
    if not found:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {"status": "success", "axis": axis}


@router.post("/candidates/dismiss_all")
async def dismiss_all_candidates(request: Request,
                                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Dismisses every open candidate of one axis at once — the reset after
    the producers changed what they record."""
    import asyncio
    body = await request.json()
    axis = _axis(body.get("axis") or "pose")
    n = await asyncio.to_thread(pose_catalog.dismiss_all_candidates, axis)
    return {"status": "success", "axis": axis, "dismissed": n}


# ── Rendered expression images ───────────────────────────────────────────

@router.post("/expression-images/clear")
def clear_expression_images(_: Dict[str, Any] = Depends(require_admin)
                            ) -> Dict[str, Any]:
    """Deletes every cached expression image of every character.

    Belongs next to the catalog editor because the image cache is keyed by the
    catalog KEY, never by the prompt text: editing an entry's prompt leaves
    every image already rendered under that key stale forever. This is the
    reset for exactly that. Images are re-rendered on demand; the per-character
    variant of this lives in ``characters.py``.
    """
    from app.core.expression_regen import clear_expression_cache
    from app.models.character import list_available_characters

    images = 0
    for name in list_available_characters():
        try:
            images += clear_expression_cache(name)
        except Exception as e:
            logger.warning("clear_expression_cache(%s) failed: %s", name, e)
    logger.info("rendered expression images cleared: %d", images)
    return {"images_deleted": images}
