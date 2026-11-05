"""Who knows that a linked body is its leader — an ordinary record secret.

Knowledge is per (body, observer): "<body> is secretly <leader>." — ONE record
secret per body, created through ``app.models.secrets.add_secret(body, ...)``,
so it is stored at the MIND (the leader) and carries ``body`` = the body: a
knower's prompt reads "About <body>: <body> is secretly <leader>.".
``source_ref = "transformation:<body>"``; its ``known_by`` list holds the
knowers, stored as minds by the secrets API. It is edited in the leader's
Transformation panel (tab "Knowers", ``set_knowers``) and through the reveal
verb (``add``), and stays an ordinary secret, so Characters → Secrets shows it
too. The knowers belong to the BODY, not to a definition: two definitions
turning the leader into the same body share them, and deleting a definition
keeps them (the body is still secretly the leader).

Every family member always knows (``mind_of(observer) == leader``); every
other lookup goes through ``secrets.knows`` (mind-aware). Every read-modify-
write of the secret runs under ``keyed_lock("secrets", leader)`` (an RLock —
the secrets model takes the same key inside).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.core.keyed_lock import keyed_lock
from app.core.linked_characters import leader_of, mind_of
from app.models import secrets


def _ref(body: str) -> str:
    return f"transformation:{body}"


def _fold(name: str) -> str:
    return (name or "").strip().casefold()


def _find(leader: str, body: str) -> Optional[Dict[str, Any]]:
    ref = _ref(body)
    return next((s for s in secrets.list_secrets(leader) if s.get("source_ref") == ref), None)


def content(body: str, leader: str) -> str:
    """The secret's text."""
    return f"{body} is secretly {leader}."


def ensure_secret(body: str) -> str:
    """The id of the body's knower secret, created if missing; ``""`` when
    ``body`` is not a linked character."""
    leader = leader_of(body)
    if not leader:
        return ""
    with keyed_lock("secrets", leader):
        found = _find(leader, body)
        if found is not None:
            return found["id"]
        return secrets.add_secret(body, content=content(body, leader),
                                  source="record", source_ref=_ref(body))["id"]


def _in_family(observer: str, leader: str) -> bool:
    return bool(observer) and mind_of(observer.strip()) == leader


def knows(observer: str, body: str) -> bool:
    """Whether ``observer`` knows that ``body`` is its leader. The family
    (the leader and every body) always does."""
    leader = leader_of(body)
    if not leader or not _fold(observer):
        return False
    if _in_family(observer, leader):
        return True
    found = _find(leader, body)
    return found is not None and secrets.knows(found, observer.strip())


def knower_names(body: str) -> List[str]:
    """The knowers on the body's secret, as stored (minds, the family left out)."""
    leader = leader_of(body)
    if not leader:
        return []
    found = _find(leader, body)
    out: List[str] = []
    for name in (found or {}).get("known_by") or []:
        if isinstance(name, str) and name.strip() and not _in_family(name, leader) \
                and name.strip() not in out:
            out.append(name.strip())
    return out


def add(observer: str, body: str) -> bool:
    """Make ``observer`` a knower. False when ``body`` is not linked."""
    leader = leader_of(body)
    if not leader or not _fold(observer):
        return False
    with keyed_lock("secrets", leader):
        if knows(observer, body):
            return True
        sid = ensure_secret(body)
        return bool(sid) and secrets.add_known_by(body, sid, observer.strip())


def remove(observer: str, body: str) -> bool:
    """Take ``observer`` off the knowers. False when they were not on it."""
    leader = leader_of(body)
    if not leader or not _fold(observer):
        return False
    mind = mind_of(observer.strip())
    with keyed_lock("secrets", leader):
        found = _find(leader, body)
        if found is None:
            return False
        before = [k for k in found.get("known_by") or [] if isinstance(k, str)]
        after = [k for k in before if k != mind]
        if len(after) == len(before):
            return False
        return secrets.update_secret(leader, found["id"], {"known_by": after}) is not None


def set_knowers(body: str, names: Iterable[str]) -> List[str]:
    """Make exactly ``names`` (as minds; the family and blanks left out,
    duplicates folded) the knowers of ``body`` and return the stored list
    (``knower_names``). The secret is created when a knower is to be stored and
    none exists yet. Added knowers go through ``add_known_by`` so they get
    their first-learned stamp."""
    leader = leader_of(body)
    if not leader:
        return []
    wanted: List[str] = []
    for name in names or []:
        if not isinstance(name, str) or not name.strip() or _in_family(name, leader):
            continue
        mind = mind_of(name.strip())
        if mind not in wanted:
            wanted.append(mind)
    with keyed_lock("secrets", leader):
        found = _find(leader, body)
        if found is None:
            if not wanted:
                return []
            sid = ensure_secret(body)
            found = _find(leader, body) if sid else None
            if found is None:
                return []
        current = [k for k in found.get("known_by") or [] if isinstance(k, str)]
        remaining = [k for k in current if k in wanted]
        if len(remaining) != len(current):
            secrets.update_secret(leader, found["id"], {"known_by": remaining})
        for name in wanted:
            if name not in remaining:
                secrets.add_known_by(leader, found["id"], name)
    return knower_names(body)
