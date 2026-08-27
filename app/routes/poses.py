"""Catalog editor routes — the two finite render-key axes.

`pose` and `expression` are the ONLY keys under which image variants are
cached and animation clips are resolved (plan-pose-katalog.md). Both axes live
in one curated JSON file each (``shared/templates/<axis>/<axis>_catalog.json``,
``pose_catalog.catalog_path``); this router is the write surface behind the
Poses admin tab: edit entries, approve/dismiss the candidates the resolver
recorded for free text it could not absorb, and clear the rendered expression
images after a prompt edit (the image cache is keyed by the catalog KEY, so an
edited prompt does not invalidate anything by itself).

The pose axis carries a second, much smaller vocabulary in the same file: the
PLACE TYPES (``groups``) a marker speaks, edited through ``GET``/``PUT
/poses/groups``. Every pose names exactly one of them.

Free text never creates an entry any more — the catalog grows only through the
approval flow here. The animation vocabulary is NOT hardcoded either: it is
whatever clips the world currently ships.
"""
import json
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core import expression_pose_maps as epm
from app.core import pose_catalog
from app.core.auth_dependency import require_admin
from app.core.log import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/poses", tags=["poses"])


def _axis(axis: str) -> str:
    """Validated axis. An unknown value is a client error, never a 500 — the
    catalog helpers raise KeyError on anything but the two known axes."""
    value = (axis or "").strip().lower()
    if value not in pose_catalog.AXES:
        raise HTTPException(status_code=400, detail="unknown axis")
    return value


@contextmanager
def _catalog_txn(axis: str) -> Iterator[None]:
    """Serializes ONE catalog file against every other writer of it.

    The editor's write paths are all ``_read`` → change → ``_write`` over the
    WHOLE document. They used to be kept apart by the event loop; since the
    route bodies run in the threadpool (2026-08-24) two admins (or two tabs)
    can be inside one at the same time, both read the same document and the
    later write drops the earlier entry. The alias checks
    (``_require_free_aliases``) have the same problem: they read the catalog
    cache, and without the lock two new entries can each pass the check for an
    alias only one of them may own.

    Keyed by the catalog FILE PATH, so the ``pose`` and the ``expression``
    axis do not wait for each other. Blocking — these are rare admin clicks,
    and a dropped edit would have to be retyped.
    """
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("pose_catalog", str(pose_catalog.catalog_path(axis))):
        yield


def _read(axis: str) -> Dict[str, Any]:
    """Raw catalog document of an axis (keeps ``_comment`` and any field this
    router does not know about, so a write never eats them).

    Call it inside :func:`_catalog_txn` whenever the result is written back.
    """
    try:
        data = json.loads(pose_catalog.catalog_path(axis).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    entries = data.get("entries")
    data["entries"] = entries if isinstance(entries, dict) else {}
    return data


def _write(axis: str, data: Dict[str, Any]) -> None:
    """ATOMIC catalog write — temp file in the same directory, then rename.

    The old in-place ``open(path, "w")`` truncated the catalog before writing
    it: a crash, a full disk or a reader arriving mid-write saw a truncated or
    empty document — and this file is the render key of every pose and
    expression, so an empty one takes the whole world's poses with it.
    ``os.replace`` is atomic within one filesystem, which is why the temp file
    is created in the catalog's OWN directory. Its permissions are carried
    over from the file being replaced — ``mkstemp`` creates 0600, and the
    catalog is a tracked repo file whose mode must not change under an edit.
    """
    path = pose_catalog.catalog_path(axis)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # Drops the catalog cache, the alias embeddings and the expression memo.
    epm.reload_presets()


def _key(raw: Any) -> str:
    """Validated entry key. A key with a slash in it would be unreachable
    through /poses/{key} afterwards — reject it at creation time."""
    key = str(raw or "").strip().lower()
    if not key:
        raise HTTPException(status_code=400, detail="key missing")
    if "/" in key:
        raise HTTPException(status_code=400, detail="key must not contain '/'")
    return key


def _synonyms(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="synonyms must be a list")
    return [str(s).strip().lower() for s in raw if str(s).strip()]


def _group(raw: Any) -> str:
    """Validated place type — the finite vocabulary of the ``groups`` block.

    A pose without a known place type is unplaceable: the marker speaks group
    ids, so an unknown one would silently make the pose unreachable.
    """
    group = str(raw or "").strip().lower()
    if group not in pose_catalog.get_groups():
        raise HTTPException(status_code=400, detail="place type missing or unknown")
    return group


def _places(raw: Any) -> int:
    """Marker slots a PAIR pose consumes — 1 or 2, nothing else."""
    try:
        return 2 if int(raw or 2) >= 2 else 1
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="places must be 1 or 2")


def _yaw_offset(raw: Any) -> float:
    """Degrees the pair clip's frame turns against the marker facing."""
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="yaw_offset must be a number")


def _alias_owner(axis: str, alias: str, exclude_key: str = "") -> str:
    """Entry key that already claims this alias ("" = free).

    ``exclude_key`` skips exactly one entry — an update re-saving an entry with
    the synonyms it already owns is not a collision with itself.
    """
    alias = (alias or "").strip().lower()
    for key, entry in pose_catalog.get_catalog(axis).items():
        if exclude_key and key == exclude_key:
            continue
        if alias == key or alias in entry.get("synonyms", []):
            return key
    return ""


def _require_free_aliases(axis: str, aliases: List[str], exclude_key: str = "") -> None:
    """409 (naming the owning entry) as soon as one alias is already claimed.

    Every write path goes through this — an alias must point at exactly one
    entry, otherwise the resolver's alias index silently drops one of them.
    """
    for alias in aliases:
        owner = _alias_owner(axis, alias, exclude_key=exclude_key)
        if owner:
            raise HTTPException(status_code=409,
                                detail=f"'{alias}' already belongs to '{owner}'")


# ── Place types: the vocabulary a marker speaks ──────────────────────────
# Registered BEFORE the /{key} routes on purpose — FastAPI matches in
# declaration order, so a later `/groups` would be swallowed by `PUT /{key}`.

def _normalize_group(raw: Any) -> Dict[str, Any]:
    """One place type as it is stored: a label, the root drop as a fraction of
    the figure height (clamped to 0..1) and the pose a click on such a marker
    sets."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        drop = round(max(0.0, min(1.0, float(raw.get("root_drop") or 0.0))), 3)
    except (TypeError, ValueError):
        drop = 0.0
    return {"label": str(raw.get("label") or "").strip(),
            "root_drop": drop,
            "default": str(raw.get("default") or "").strip().lower()}


def _groups_problems(groups: Dict[str, Any], entries: Dict[str, Any]) -> List[str]:
    """Why a groups block may NOT be written: a group still named by a pose
    is missing, or a default is not a pose of its own group."""
    problems: List[str] = []
    for key, entry in entries.items():
        g = str(entry.get("group") or "")
        if g and g not in groups:
            problems.append(f"place type '{g}' is still used by '{key}'")
    for g, spec in groups.items():
        d = spec.get("default", "")
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

    The block is replaced as a WHOLE, so it is checked as a whole: dropping a
    type some pose still names, or pointing a default at a pose of another
    group, would leave the catalog invalid the moment it is written.
    """
    raw = (body or {}).get("groups")
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(status_code=400, detail="groups missing")
    groups: Dict[str, Any] = {}
    for key, spec in raw.items():
        k = _key(key)
        groups[k] = _normalize_group(spec)
        if not groups[k]["label"]:
            groups[k]["label"] = k
    with _catalog_txn("pose"):
        data = _read("pose")
        problems = _groups_problems(groups, data.get("entries") or {})
        if problems:
            raise HTTPException(status_code=400, detail="; ".join(problems))
        data["groups"] = groups
        _write("pose", data)
    return {"status": "success", "groups": pose_catalog.get_groups()}


@router.get("")
def list_entries(axis: str = Query("pose"),
                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """All catalog entries of an axis + the animation kinds that have clips
    (pose only) + the integrity problems of the catalog."""
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
        }
        if axis == "pose":
            # Place fields are POSE vocabulary — an expression has no place.
            row["group"] = entry.get("group", "")
            row["places"] = entry.get("places", 2)
            row["yaw_offset"] = entry.get("yaw_offset", 0.0)
        out.append(row)
    out.sort(key=lambda p: p["key"])
    from app.core.animation_clips import pair_kinds
    return {
        "entries": out,
        "kinds": epm.available_animation_kinds() if axis == "pose" else [],
        # Kinds that exist as a PAIR clip (two halves, § A8a): such a pose is
        # a two-person one and has to carry solo: false.
        "pair_kinds": pair_kinds() if axis == "pose" else [],
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
    axis = _axis(body.get("axis") or "pose")
    key = _key(body.get("key"))
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt missing")
    animation = str(body.get("animation") or "").strip().lower()
    if axis == "pose" and not animation:
        raise HTTPException(status_code=400, detail="animation missing")
    group = _group(body.get("group")) if axis == "pose" else ""
    with _catalog_txn(axis):
        data = _read(axis)
        if key in data["entries"]:
            raise HTTPException(status_code=409, detail="Entry already exists")
        synonyms = _synonyms(body.get("synonyms") or [])
        _require_free_aliases(axis, [key] + synonyms)

        entry: Dict[str, Any] = {"prompt": prompt, "synonyms": synonyms}
        if axis == "pose":
            entry["animation"] = animation
            entry["solo"] = bool(body.get("solo", True))
            entry["group"] = group
            if not entry["solo"]:
                entry["places"] = _places(body.get("places"))
                entry["yaw_offset"] = _yaw_offset(body.get("yaw_offset"))
        data["entries"][key] = entry
        _write(axis, data)
    return {"status": "success", "key": key, "axis": axis}


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
    axis = _axis(axis)
    key = key.strip().lower()
    with _catalog_txn(axis):
        data = _read(axis)
        entry = data["entries"].get(key)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        if "prompt" in body:
            entry["prompt"] = str(body["prompt"] or "").strip()
        if "synonyms" in body:
            synonyms = _synonyms(body["synonyms"] or [])
            # The entry's OWN key is excluded: re-saving it with the synonyms
            # it already holds must stay legal.
            _require_free_aliases(axis, synonyms, exclude_key=key)
            entry["synonyms"] = synonyms
        if "animation" in body and axis == "pose":
            anim = str(body["animation"] or "").strip().lower()
            if not anim:
                raise HTTPException(status_code=400, detail="animation missing")
            entry["animation"] = anim
        if "solo" in body and axis == "pose":
            entry["solo"] = bool(body["solo"])
        if "group" in body and axis == "pose":
            entry["group"] = _group(body["group"])
        if "places" in body and axis == "pose":
            entry["places"] = _places(body["places"])
        if "yaw_offset" in body and axis == "pose":
            entry["yaw_offset"] = _yaw_offset(body["yaw_offset"])
        if axis == "pose" and entry.get("solo", True):
            # A solo pose occupies exactly one place and never turns — leaving
            # the pair fields behind would be a stray the catalog reports.
            entry.pop("places", None)
            entry.pop("yaw_offset", None)
        data["entries"][key] = entry
        _write(axis, data)
    return {"status": "success", "key": key, "axis": axis}


@router.delete("/{key}")
def delete_entry(key: str, axis: str = Query("pose"),
                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Deletes a catalog entry. The ``_default`` entry is not deletable — it
    is the target every unresolvable free text falls back to."""
    axis = _axis(axis)
    key = key.strip().lower()
    with _catalog_txn(axis):
        data = _read(axis)
        entry = data["entries"].get(key)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        if entry.get("_default"):
            raise HTTPException(status_code=400,
                                detail="the default entry cannot be deleted")
        data["entries"].pop(key, None)
        _write(axis, data)
    return {"status": "success", "key": key, "axis": axis}


# ── Candidates: free text the catalog could not absorb ───────────────────

@router.get("/candidates")
def list_candidates(axis: str = Query("pose"), status: str = Query("open"),
                    _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Open candidates of an axis, most recently seen first.

    ``count`` counts the FIRST sighting per server process on the expression
    axis (the resolver memoizes), so it reads as "seen", not as a hit count —
    recency is the better sort key.
    """
    axis = _axis(axis)
    rows = pose_catalog.list_candidates(axis, status=status)
    rows.sort(key=lambda r: (r.get("last_seen") or ""), reverse=True)
    return {"candidates": rows, "axis": axis}


@router.post("/candidates/approve")
async def approve_candidate(request: Request,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Absorbs a candidate into the catalog — either as a new entry
    (``key`` + ``prompt``, ``animation`` mandatory on the pose axis) or as a
    synonym of an existing entry (``as_synonym_of``). The candidate row is
    deleted afterwards: it resolves now, and if it still does not, the miss
    has to show up again instead of hiding behind a terminal status.
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_approve_candidate_sync, _, body)


def _approve_candidate_sync(_: Dict[str, Any], body: Any) -> Dict[str, Any]:
    """The blocking body of ``approve_candidate`` — runs in the threadpool."""
    axis = _axis(body.get("axis") or "pose")
    raw_text = str(body.get("raw_text") or "").strip().lower()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text missing")
    with _catalog_txn(axis):
        data = _read(axis)
        target = str(body.get("as_synonym_of") or "").strip().lower()

        if target:
            entry = data["entries"].get(target)
            if entry is None:
                raise HTTPException(status_code=404, detail="Entry not found")
            owner = _alias_owner(axis, raw_text)
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
            key = _key(body.get("key"))
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                raise HTTPException(status_code=400, detail="prompt missing")
            animation = str(body.get("animation") or "").strip().lower()
            # Only non-emptiness is checked: the kind vocabulary is
            # world-dependent (whatever clips exist), so an unknown kind is a
            # warning, not a wall.
            if axis == "pose" and not animation:
                raise HTTPException(status_code=400, detail="animation missing")
            if key in data["entries"]:
                raise HTTPException(status_code=409, detail="Entry already exists")
            # The candidate text itself becomes a synonym unless it IS the key
            # — on top of whatever the admin typed into the form.
            synonyms: List[str] = []
            for alias in _synonyms(body.get("synonyms") or []) + [raw_text]:
                if alias != key and alias not in synonyms:
                    synonyms.append(alias)
            _require_free_aliases(axis, [key] + synonyms)
            entry = {"prompt": prompt, "synonyms": synonyms}
            if axis == "pose":
                entry["animation"] = animation
                entry["solo"] = bool(body.get("solo", True))
            data["entries"][key] = entry

        _write(axis, data)
    pose_catalog.delete_candidate(axis, raw_text)
    logger.info("candidate approved: %s/%r -> %r", axis, raw_text, key)
    return {"status": "success", "axis": axis, "key": key}


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
