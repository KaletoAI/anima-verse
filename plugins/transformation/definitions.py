"""Persona definitions — the world config list ``skills.transformation_personas``.

Each record binds a persona (alias + description) to a power item. ``load()``
parses the list into frozen :class:`Definition` objects keyed by ``id`` and
skips, with one warning per record and reason per process, every record that
is disabled, lacks ``id``/``item_id``/``alias``, repeats an earlier ``id`` or
alias (casefold, the first one wins) or whose alias is the name of an existing
character. Defaults come from the package's own schema (``field_default``),
never from a second copy here.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

from app.core import config
from app.core.config_schema import field_default
from app.core.log import get_logger

logger = get_logger("transformation")

CONFIG_PATH = "skills.transformation_personas"
#: How long a parsed list is reused (SYSTEM seconds). The config fingerprint
#: is part of the cache key, so an edit is seen at once; the TTL only bounds
#: how long a roster change (a character created or deleted under an alias)
#: goes unnoticed.
_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class Definition:
    id: str
    enabled: bool
    item_id: str
    alias: str
    description: str
    activation_phrase: str
    revert_phrase: str
    suit_items: Tuple[str, ...]
    condition_id: str
    max_duration_minutes: int
    cooldown_minutes: int
    transform_activity: str


_warned: Set[Tuple[str, str]] = set()
_lock = threading.Lock()
_cache: Tuple[Any, float, Optional[Dict[str, Definition]]] = (None, 0.0, None)


def _default(name: str) -> Any:
    return field_default("skills", "transformation_personas", name)


def _warn_once(key: str, reason: str, message: str, *args: Any) -> None:
    with _lock:
        if (key, reason) in _warned:
            return
        _warned.add((key, reason))
    logger.warning(message, *args)


def _text(record: Dict[str, Any], name: str) -> str:
    value = record.get(name)
    if value is None:
        value = _default(name) if name == "transform_activity" else ""
    return str(value).strip()


def _minutes(record: Dict[str, Any], name: str) -> int:
    value = record.get(name)
    try:
        minutes = int(value) if value is not None and value != "" else int(_default(name))
    except (TypeError, ValueError):
        minutes = int(_default(name))
    return max(0, minutes)


def _parse(raw: Any) -> Dict[str, Definition]:
    if not isinstance(raw, list):
        if raw is not None:
            _warn_once("*", "not_a_list", "%s is not a list — no personas", CONFIG_PATH)
        return {}
    from app.models.character import list_available_characters
    roster = {n.casefold() for n in list_available_characters(include_pooled=True)}
    out: Dict[str, Definition] = {}
    aliases: Set[str] = set()
    for index, record in enumerate(raw):
        if not isinstance(record, dict):
            _warn_once(f"#{index}", "not_a_record", "Persona #%d is not a record — skipped", index)
            continue
        pid = _text(record, "id")
        key = pid or f"#{index}"
        enabled = record.get("enabled", _default("enabled"))
        if enabled is False or (isinstance(enabled, str) and enabled.lower() == "false"):
            _warn_once(key, "disabled", "Persona %s is disabled — skipped", key)
            continue
        item_id, alias = _text(record, "item_id"), _text(record, "alias")
        if not pid or not item_id or not alias:
            _warn_once(key, "incomplete", "Persona %s lacks id, item_id or alias — skipped", key)
            continue
        if pid in out:
            _warn_once(key, f"dup_id:{index}", "Persona id %s appears twice — later entry skipped", pid)
            continue
        folded = alias.casefold()
        if folded in aliases:
            _warn_once(key, "dup_alias", "Persona %s: alias %r is already used — skipped", pid, alias)
            continue
        if folded in roster:
            _warn_once(key, "alias_is_character",
                       "Persona %s: alias %r is the name of a character — skipped", pid, alias)
            continue
        suit = tuple(s.strip() for s in _text(record, "suit_items").split(",") if s.strip())
        out[pid] = Definition(
            id=pid, enabled=True, item_id=item_id, alias=alias,
            description=_text(record, "description"),
            activation_phrase=_text(record, "activation_phrase"),
            revert_phrase=_text(record, "revert_phrase"),
            suit_items=suit,
            condition_id=_text(record, "condition_id"),
            max_duration_minutes=_minutes(record, "max_duration_minutes"),
            cooldown_minutes=_minutes(record, "cooldown_minutes"),
            transform_activity=_text(record, "transform_activity") or str(_default("transform_activity")),
        )
        aliases.add(folded)
    return out


def load() -> Dict[str, Definition]:
    """The usable personas, keyed by id (a fresh dict; the values are frozen).

    Cached per config fingerprint for at most ``_TTL_SECONDS``.
    """
    global _cache
    raw = config.get(CONFIG_PATH)
    fingerprint = json.dumps(raw, sort_keys=True, default=str)
    now = time.monotonic()
    with _lock:
        key, stamp, defs = _cache
    if defs is not None and key == fingerprint and now - stamp < _TTL_SECONDS:
        return dict(defs)
    defs = _parse(raw)
    with _lock:
        _cache = (fingerprint, now, defs)
    return dict(defs)


def invalidate() -> None:
    """Drop the parsed list; the next ``load()`` parses the config again."""
    global _cache
    with _lock:
        _cache = (None, 0.0, None)


def for_item(item_id: str) -> Optional[Definition]:
    """The persona the item grants, or ``None``."""
    if not item_id:
        return None
    for definition in load().values():
        if definition.item_id == item_id:
            return definition
    return None
