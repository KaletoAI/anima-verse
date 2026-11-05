"""Who is in on a bearer's persona — kept as an ordinary character secret.

Knowledge is "<bearer> is <alias>": one record secret per (bearer, persona),
owned by the bearer, ``source_ref = "transformation:<persona id>"``; its
``known_by`` list holds the knowers. It is edited in the Transformation
panel ("In on the secret", ``set_knowers``) and stays an ordinary secret, so
Characters → Secrets shows it too. Names are compared casefolded and stripped.
Every read-modify-write of the secret runs under ``keyed_lock("secrets",
bearer)`` (an RLock — the secrets model takes the same key inside).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.core.keyed_lock import keyed_lock
from app.models import secrets
from app.models.character import list_available_characters

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


def knower_names(bearer: str, persona_id: str) -> List[str]:
    """The knowers listed on the bearer's secret, as stored (stripped,
    deduplicated casefold, the bearer herself left out)."""
    found = _find(bearer, persona_id)
    out: List[str] = []
    seen = {_fold(bearer)}
    for name in (found or {}).get("known_by") or []:
        if not isinstance(name, str) or _fold(name) in seen:
            continue
        seen.add(_fold(name))
        out.append(name.strip())
    return out


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


def remove(observer: str, bearer: str, persona_id: str) -> bool:
    """Take ``observer`` off the knowers. False when they were not on it."""
    folded = _fold(observer)
    with keyed_lock("secrets", bearer):
        found = _find(bearer, persona_id)
        if found is None or not folded:
            return False
        before = [k for k in found.get("known_by") or [] if isinstance(k, str)]
        after = [k for k in before if _fold(k) != folded]
        if len(after) == len(before):
            return False
        return secrets.update_secret(bearer, found["id"], {"known_by": after}) is not None


def set_knowers(bearer: str, persona_id: str, names: Iterable[str]) -> List[str]:
    """Make exactly ``names`` the knowers of ``bearer``'s persona and return
    the stored list (``knower_names``).

    The bearer herself and blank names are left out, duplicates fold. The
    secret is created when a knower is to be stored and none exists yet
    (an unknown persona then stores nothing). Added knowers go through
    ``add_known_by`` so they get their first-learned stamp."""
    wanted: List[str] = []
    seen = {_fold(bearer)}
    for name in names or []:
        if isinstance(name, str) and _fold(name) and _fold(name) not in seen:
            seen.add(_fold(name))
            wanted.append(name.strip())
    with keyed_lock("secrets", bearer):
        found = _find(bearer, persona_id)
        if found is None:
            if not wanted:
                return []
            d = load().get(persona_id)
            if d is None:
                return []
            ensure_secret(bearer, d)
            found = _find(bearer, persona_id)
            if found is None:
                return []
        keep = {_fold(n) for n in wanted}
        current = [k for k in found.get("known_by") or [] if isinstance(k, str)]
        remaining = [k for k in current if _fold(k) in keep]
        if len(remaining) != len(current):
            secrets.update_secret(bearer, found["id"], {"known_by": remaining})
        have = {_fold(k) for k in remaining}
        for name in wanted:
            if _fold(name) not in have:
                secrets.add_known_by(bearer, found["id"], name)
    return knower_names(bearer, persona_id)


def _sweep(persona_id: str, fn) -> int:
    """Run ``fn(name, secret)`` for every character's secret of the persona
    (every past holder may have one); the number of secrets touched."""
    ref, count = _ref(persona_id), 0
    for name in list_available_characters(include_pooled=True):
        with keyed_lock("secrets", name):
            for found in [s for s in secrets.list_secrets(name) if s.get("source_ref") == ref]:
                fn(name, found)
                count += 1
    return count


def rename_alias(persona_id: str, alias: str) -> int:
    """Rewrite the content of every secret of the persona for a new alias."""
    return _sweep(persona_id, lambda name, found: secrets.update_secret(
        name, found["id"], {"content": f"I am secretly {alias}."}))


def forget_persona(persona_id: str) -> int:
    """Delete every character's secret of a deleted persona."""
    ref = _ref(persona_id)
    return _sweep(persona_id, lambda name, found: secrets.delete_secrets_by_ref(name, ref))
