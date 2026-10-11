"""Shared catalog editing rules for HTTP routes and background jobs."""
import json
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from app.core import expression_pose_maps as epm
from app.core import pose_catalog
from app.core.log import get_logger

logger = get_logger(__name__)


class CatalogEditError(Exception):
    """Catalog edit refusal independent of the HTTP transport."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@contextmanager
def catalog_txn(axis: str) -> Iterator[None]:
    """Serializes ONE catalog file against every other writer of it.

    The editor's write paths are all ``read_store`` → change → ``write_store`` over the
    WHOLE document. They used to be kept apart by the event loop; since the
    route bodies run in the threadpool (2026-08-24) two admins (or two tabs)
    can be inside one at the same time, both read the same document and the
    later write drops the earlier entry. The alias checks
    (``require_free_aliases``) have the same problem: they read the catalog
    cache, and without the lock two new entries can each pass the check for an
    alias only one of them may own.

    Keyed by the AXIS, so the ``pose`` and the ``expression`` axis do not
    wait for each other. Blocking — these are rare admin clicks, and a
    dropped edit would have to be retyped.
    """
    from app.core.keyed_lock import keyed_lock
    # Keyed on the AXIS, not on one store: an entry can move between the
    # tracked catalog and the world layer, and that touches both. The file
    # lock serializes against writers OUTSIDE this process (the animation
    # studio's publish) — same read -> alias check -> write section.
    with keyed_lock("pose_catalog", axis):
        with pose_catalog.catalog_file_lock(axis):
            yield


def read_store(axis: str, store: str = "shared") -> Dict[str, Any]:
    """Raw catalog document of ONE store: the shared FILE (keeps ``_comment``
    and any field this router does not know about, so a write never eats
    them), or the world layer's entries as a document of the same shape.

    Call it inside :func:`catalog_txn` whenever the result is written back.
    """
    if store == "world":
        return {"entries": dict(pose_catalog.world_entries(axis))}
    try:
        data = json.loads(
            pose_catalog.catalog_path(axis).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    entries = data.get("entries")
    data["entries"] = entries if isinstance(entries, dict) else {}
    return data


def store_of(axis: str, key: str) -> str:
    """Which store an existing entry lives in — the merged catalog knows."""
    entry = pose_catalog.get_catalog(axis).get(key) or {}
    return str(entry.get("_store") or "shared")


def after_write() -> None:
    """What every catalog write of either layer has to drop afterwards."""
    # Drops the catalog cache, the alias embeddings and the expression memo.
    epm.reload_presets()
    # The place types (groups) live in this catalog — the seat inventory
    # composed from the old ones is stale.
    from app.core import places; places.invalidate()


def write_store(axis: str, data: Dict[str, Any], store: str = "shared") -> None:
    """Write ONE store back as a whole: the world layer's entries in one
    transaction, or the shared file atomically
    (``pose_catalog.write_shared_document``)."""
    if store == "world":
        pose_catalog.replace_world_entries(axis, data.get("entries") or {})
        after_write()
        return
    pose_catalog.write_shared_document(axis, data)
    after_write()


def validate_key(raw: Any) -> str:
    """Validated entry key. A key with a slash in it would be unreachable
    through /poses/{key} afterwards — reject it at creation time."""
    key = str(raw or "").strip().lower()
    if not key:
        raise CatalogEditError(status=400, detail="key missing")
    if "/" in key:
        raise CatalogEditError(status=400, detail="key must not contain '/'")
    return key


def validate_synonyms(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        raise CatalogEditError(status=400, detail="synonyms must be a list")
    return [str(s).strip().lower() for s in raw if str(s).strip()]


def validate_group(raw: Any) -> str:
    """Validated place type — the finite vocabulary of the ``groups`` block.

    A pose without a known place type is unplaceable: the marker speaks group
    ids, so an unknown one would silently make the pose unreachable.
    """
    group = str(raw or "").strip().lower()
    if group not in pose_catalog.get_groups():
        raise CatalogEditError(status=400, detail="place type missing or unknown")
    return group


def alias_owner(axis: str, alias: str, exclude_key: str = "") -> str:
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


def require_free_aliases(axis: str, aliases: List[str], exclude_key: str = "") -> None:
    """409 (naming the owning entry) as soon as one alias is already claimed.

    Every write path goes through this — an alias must point at exactly one
    entry, otherwise the resolver's alias index silently drops one of them.
    """
    for alias in aliases:
        owner = alias_owner(axis, alias, exclude_key=exclude_key)
        if owner:
            raise CatalogEditError(status=409,
                                detail=f"'{alias}' already belongs to '{owner}'")


def apply_generated_entry(*, mode: str, animation: str, key: str,
                          entry: Optional[Dict[str, Any]] = None,
                          raw_text: str = "") -> Dict[str, Any]:
    """Apply a generated solo animation using the catalog editor rules."""
    axis = "pose"
    with catalog_txn(axis):
        key = validate_key(key)
        animation = str(animation or "").strip().lower()
        if not animation:
            raise CatalogEditError(400, "animation missing")
        shared = read_store(axis)
        if mode == "entry":
            existing = pose_catalog.get_catalog(axis).get(key)
            if existing is None:
                raise CatalogEditError(404, "Entry not found")
            store = store_of(axis, key)
            # An override hides its shared seed in the merged catalog. Both
            # existing rows must follow the generated animation.
            stores = ["shared"] if key in shared["entries"] else [store]
            world = read_store(axis, "world")
            if key in shared["entries"] and key in world["entries"]:
                stores.append("world")
            for target in stores:
                data = shared if target == "shared" else world
                if not data["entries"][key].get("solo", True):
                    raise CatalogEditError(400, "pair poses cannot get a generated animation")
            for target in stores:
                data = shared if target == "shared" else world
                data["entries"][key]["animation"] = animation
                write_store(axis, data, target)
        elif mode in ("candidate", "free"):
            if key in pose_catalog.get_catalog(axis):
                raise CatalogEditError(409, "Entry already exists")
            require_free_aliases(axis, [key])
            spec = entry or {}
            prompt = str(spec.get("prompt") or "").strip()
            if not prompt:
                raise CatalogEditError(400, "prompt missing")
            group = validate_group(spec.get("group"))
            # Generated entries are shared, so a world-only place type cannot
            # supply their persistent group block or its default.
            if group not in (shared.get("groups") or {}):
                raise CatalogEditError(400, "place type missing or unknown")
            raw_text = str(raw_text or "").strip().lower()
            if mode == "candidate" and not raw_text:
                raise CatalogEditError(400, "raw_text missing")
            aliases = validate_synonyms(spec.get("synonyms") or [])
            if mode == "candidate":
                aliases.append(raw_text)
            synonyms: List[str] = []
            for alias in aliases:
                if alias == key or alias in synonyms:
                    continue
                owner = alias_owner(axis, alias)
                if owner:
                    logger.info("generated pose synonym dropped: %r belongs to %r", alias, owner)
                    continue
                synonyms.append(alias)
            if pose_catalog.poses_in_group(group) == []:
                shared["groups"][group]["default"] = key
            shared["entries"][key] = {
                "prompt": prompt, "synonyms": synonyms, "animation": animation,
                "solo": True, "group": group}
            write_store(axis, shared)
            stores = ["shared"]
            if mode == "candidate":
                pose_catalog.delete_candidate(axis, raw_text)
        else:
            raise CatalogEditError(400, "unknown mode")
    return {"key": key, "stores": stores}
