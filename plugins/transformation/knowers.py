"""Who is in on a bearer's persona — kept as an ordinary character secret.

Knowledge is "<bearer> is <alias>": one record secret per (bearer, persona),
owned by the bearer, ``source_ref = "transformation:<persona id>"``; its
``known_by`` list holds the knowers and is edited by hand in Characters →
Secrets. Names there are compared casefolded and stripped. Every
read-modify-write of the secret runs under ``keyed_lock("secrets", bearer)``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.keyed_lock import keyed_lock
from app.models import secrets

from plugins.transformation.definitions import Definition, load


def _ref(persona_id: str) -> str:
    return f"transformation:{persona_id}"


def _fold(name: str) -> str:
    return (name or "").strip().casefold()


def _find(bearer: str, persona_id: str) -> Optional[Dict[str, Any]]:
    ref = _ref(persona_id)
    return next((s for s in secrets.list_secrets(bearer) if s.get("source_ref") == ref), None)


def ensure_secret(bearer: str, d: Definition) -> str:
    """The id of the bearer's secret for persona ``d``, created if missing."""
    with keyed_lock("secrets", bearer):
        found = _find(bearer, d.id)
        if found is not None:
            return found["id"]
        return secrets.add_secret(bearer, content=f"I am secretly {d.alias}.",
                                  source="record", source_ref=_ref(d.id))["id"]


def knows(observer: str, bearer: str, persona_id: str) -> bool:
    """Whether ``observer`` knows that ``bearer`` is the persona."""
    folded = _fold(observer)
    if not folded:
        return False
    if folded == _fold(bearer):
        return True
    found = _find(bearer, persona_id)
    if found is None:
        return False
    return any(isinstance(k, str) and _fold(k) == folded for k in found.get("known_by") or [])


def add(observer: str, bearer: str, persona_id: str) -> bool:
    """Make ``observer`` a knower. False when the persona is not configured."""
    with keyed_lock("secrets", bearer):
        if knows(observer, bearer, persona_id):
            return True
        found = _find(bearer, persona_id)
        if found is None:
            d = load().get(persona_id)
            if d is None:
                return False
            sid = ensure_secret(bearer, d)
        else:
            sid = found["id"]
        return secrets.add_known_by(bearer, sid, observer.strip())
