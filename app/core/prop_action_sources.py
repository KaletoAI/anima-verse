"""Prop actions a PACKAGE contributes to every matching piece of furniture.

An author action lives in the prop (``sidecar.json → actions``) and travels
with every export. A package action does not: the package registers a SOURCE
at load, and :func:`prop_actions.effective_document` adds its definitions to
each prop at RUNTIME only. Authoring, validation on save and every export read
the raw document, so the prop file never names a package action — remove the
package and the action is gone, nothing else changes (plan-pack-prop-actions.md).

A definition has exactly the author schema of one action (``validate_document``)
plus an optional ``match`` = ``{"categories": [...], "tags": [...]}`` against
the prop's ``category``/``tags`` (empty = every prop with a matching place).
Its ``id`` comes from :func:`pack_action_id`: the reserved ``pack-`` prefix lets
a prop exclude it (``exclude_actions``) even while the package is off.
"""
import hashlib
import json
import threading
from copy import deepcopy
from typing import Callable, Dict, List, Tuple
from uuid import NAMESPACE_URL, uuid5

from app.core.log import get_logger

logger = get_logger("prop_action_sources")

#: The id prefix only package actions carry; an author action may not use it.
PACK_PREFIX = "pack-"

_lock = threading.Lock()
_sources: Dict[str, Callable[[], List[dict]]] = {}
# raw-definitions hash -> (validated actions, signature); one entry is enough,
# the sources answer the same until a setting changes.
_validated: Tuple[str, List[dict], str] = ("", [], "")
_warned: set = set()


def pack_action_id(owner: str, key: str) -> str:
    """The stable id of a package action: the same package and key give the
    same id on every start, so exclusions and running actions survive one."""
    return PACK_PREFIX + str(uuid5(NAMESPACE_URL, f"anima:pack-action:{owner}:{key}"))


def register_source(owner: str, fn: Callable[[], List[dict]]) -> None:
    """Register (or replace) the action source of package ``owner``. ``fn``
    returns the package's definitions; it runs on every runtime read, so it
    must be cheap (read the loaded config, never a file or the DB)."""
    with _lock:
        _sources[owner] = fn


def unregister_source(owner: str) -> None:
    with _lock:
        _sources.pop(owner, None)


def _active_owners() -> List[str]:
    from app.plugins import registry
    with _lock:
        owners = sorted(_sources)
    # A source lives exactly as long as its package is loaded: an unloaded or
    # disabled package contributes nothing, without an unregister call.
    return [owner for owner in owners if registry.get_package(owner) is not None]


def _raw() -> List[Tuple[str, dict]]:
    rows = []
    for owner in _active_owners():
        with _lock:
            fn = _sources.get(owner)
        if fn is None:
            continue
        try:
            definitions = fn() or []
        except Exception as e:   # noqa: BLE001 — a package may not break furniture
            logger.error("prop action source of %s failed: %s", owner, e)
            continue
        if not isinstance(definitions, list):
            logger.error("prop action source of %s returned %s, not a list", owner, type(definitions).__name__)
            continue
        rows.extend((owner, definition) for definition in definitions)
    return rows


def _match_valid(match) -> bool:
    return match is None or (isinstance(match, dict) and not set(match) - {"categories", "tags"}
                             and all(isinstance(match.get(k, []), list)
                                     and all(isinstance(v, str) for v in match.get(k, []))
                                     for k in ("categories", "tags")))


def _validate(rows: List[Tuple[str, dict]]) -> List[dict]:
    from app.core.prop_actions import validate_document
    result, seen = [], set()
    for owner, definition in rows:
        if not isinstance(definition, dict):
            problem = "not an object"
        else:
            action = {k: v for k, v in definition.items() if k != "match"}
            aid = action.get("id")
            errors = [i for i in validate_document({"actions": [action]}, pack=True)
                      if i["severity"] == "error"]
            problem = ("id must come from pack_action_id" if not (isinstance(aid, str) and aid.startswith(PACK_PREFIX))
                       else "duplicate id" if aid in seen
                       else "invalid match" if not _match_valid(definition.get("match"))
                       else "; ".join(f"{i['path']}: {i['message']}" for i in errors))
        if problem:
            key = (owner, json.dumps(definition, sort_keys=True, default=str))
            if key not in _warned:
                _warned.add(key)
                logger.warning("prop action of package %s skipped (%s)", owner, problem)
            continue
        seen.add(aid)
        result.append(dict(owner=owner, action=action, match=definition.get("match") or {}))
    return result


def _current() -> Tuple[List[dict], str]:
    global _validated
    rows = _raw()
    raw_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    with _lock:
        if _validated[0] == raw_hash:
            return _validated[1], _validated[2]
    validated = _validate(rows)
    signature = hashlib.sha256(json.dumps(validated, sort_keys=True).encode()).hexdigest()[:16] if validated else ""
    with _lock:
        _validated = (raw_hash, validated, signature)
    return validated, signature


def pack_actions() -> List[dict]:
    """Every valid definition of every loaded source, as
    ``{"owner", "action", "match"}`` — private copies."""
    return deepcopy(_current()[0])


def signature() -> str:
    """Changes whenever the set of package actions changes; empty without any.
    Every cache that holds bindings carries it in its key."""
    return _current()[1]


def matches(match: dict, document: dict) -> bool:
    """Whether a definition's ``match`` admits this prop (case-insensitive)."""
    categories = {c.strip().lower() for c in match.get("categories", [])}
    tags = {t.strip().lower() for t in match.get("tags", [])}
    if categories and str(document.get("category") or "").strip().lower() not in categories:
        return False
    own_tags = {str(t).strip().lower() for t in document.get("tags") or []}
    return not tags or bool(tags & own_tags)
