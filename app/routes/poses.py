"""Catalog editor routes — the two finite render-key axes.

`pose` and `expression` are the ONLY keys under which image variants are
cached and animation clips are resolved (plan-pose-katalog.md). Both axes live
in one curated JSON file each (``shared/templates/<axis>/<axis>_catalog.json``,
``pose_catalog.catalog_path``); this router is the write surface behind the
Poses admin tab: edit entries, approve/dismiss the candidates the resolver
recorded for free text it could not absorb, and clear the rendered expression
images after a prompt edit (the image cache is keyed by the catalog KEY, so an
edited prompt does not invalidate anything by itself).

Free text never creates an entry any more — the catalog grows only through the
approval flow here. The animation vocabulary is NOT hardcoded either: it is
whatever clips the world currently ships.
"""
import json
from typing import Any, Dict, List

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


def _read(axis: str) -> Dict[str, Any]:
    """Raw catalog document of an axis (keeps ``_comment`` and any field this
    router does not know about, so a write never eats them)."""
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
    path = pose_catalog.catalog_path(axis)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
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


@router.get("")
def list_entries(axis: str = Query("pose"),
                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """All catalog entries of an axis + the animation kinds that have clips
    (pose only) + the integrity problems of the catalog."""
    axis = _axis(axis)
    out: List[Dict[str, Any]] = []
    for key, entry in pose_catalog.get_catalog(axis).items():
        out.append({
            "key": key,
            "prompt": entry.get("prompt", ""),
            "synonyms": entry.get("synonyms", []) or [],
            "animation": entry.get("animation", "") or "",
            "solo": bool(entry.get("solo", True)),
            "is_default": bool(entry.get("_default")),
            "axis": axis,
        })
    out.sort(key=lambda p: p["key"])
    from app.core.animation_clips import pair_kinds
    return {
        "entries": out,
        "kinds": epm.available_animation_kinds() if axis == "pose" else [],
        # Kinds that exist as a PAIR clip (two halves, § A8a): such a pose is
        # a two-person one and has to carry solo: false.
        "pair_kinds": pair_kinds() if axis == "pose" else [],
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
    data = _read(axis)
    if key in data["entries"]:
        raise HTTPException(status_code=409, detail="Entry already exists")
    synonyms = _synonyms(body.get("synonyms") or [])
    _require_free_aliases(axis, [key] + synonyms)

    entry: Dict[str, Any] = {"prompt": prompt, "synonyms": synonyms}
    if axis == "pose":
        entry["animation"] = animation
        entry["solo"] = bool(body.get("solo", True))
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
    data = _read(axis)
    entry = data["entries"].get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if "prompt" in body:
        entry["prompt"] = str(body["prompt"] or "").strip()
    if "synonyms" in body:
        synonyms = _synonyms(body["synonyms"] or [])
        # The entry's OWN key is excluded: re-saving it with the synonyms it
        # already holds must stay legal.
        _require_free_aliases(axis, synonyms, exclude_key=key)
        entry["synonyms"] = synonyms
    if "animation" in body and axis == "pose":
        anim = str(body["animation"] or "").strip().lower()
        if not anim:
            raise HTTPException(status_code=400, detail="animation missing")
        entry["animation"] = anim
    if "solo" in body and axis == "pose":
        entry["solo"] = bool(body["solo"])
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
        # Only non-emptiness is checked: the kind vocabulary is world-dependent
        # (whatever clips exist), so an unknown kind is a warning, not a wall.
        if axis == "pose" and not animation:
            raise HTTPException(status_code=400, detail="animation missing")
        if key in data["entries"]:
            raise HTTPException(status_code=409, detail="Entry already exists")
        # The candidate text itself becomes a synonym unless it IS the key —
        # on top of whatever the admin typed into the form.
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
