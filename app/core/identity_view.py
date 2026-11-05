"""How observer O sees character C — the observer-relative identity view.

A character may currently wear a PERSONA: an alias with its own description
that every observer who is not in on the secret perceives as a separate
person. The core names no package for this. Three singleton providers answer
it (``hooks.register_provider(..., owner="<package id>")``):

``identity.active_persona``  ``fn(subject) -> dict | None``
    The persona C wears right now: ``{"persona_id", "alias", "description",
    "portrait_url"}``, or ``None`` when C is not transformed.
``identity.knows``           ``fn(observer, subject) -> bool``
    Whether the observer is in on C's current persona.
``identity.persona_names``   ``fn() -> Iterable[str]``
    Every configured alias, transformed or not (reserved character names).

With no provider registered every function here answers with the real name —
removing the package removes the feature and nothing else (deletion test).
A provider that raises is logged once per capability at debug level and
treated as absent for that answer, so one broken package degrades to real
names instead of breaking a prompt. Nothing is cached here; the provider owns
its cache.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("identity_view")

PROVIDER_ACTIVE = "identity.active_persona"
PROVIDER_KNOWS = "identity.knows"
PROVIDER_NAMES = "identity.persona_names"

_MISSING = object()   # no provider registered
_FAILED = object()    # the provider raised
_logged_failures: Set[str] = set()


@dataclass(frozen=True)
class Persona:
    """The persona ``subject`` wears right now."""
    subject: str
    persona_id: str
    alias: str
    description: str
    portrait_url: str


def _call(capability: str, *args: Any) -> Any:
    """Ask a singleton provider; ``_MISSING`` without one, ``_FAILED`` on a raise."""
    from app.core.hooks import get_provider
    fn: Optional[Callable] = get_provider(capability)
    if fn is None:
        return _MISSING
    try:
        return fn(*args)
    except Exception as e:
        if capability not in _logged_failures:
            _logged_failures.add(capability)
            logger.debug("identity provider %s failed (real names used): %s", capability, e)
        return _FAILED


def _same(a: str, b: str) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def active_persona(subject: str) -> Optional[Persona]:
    """The persona ``subject`` wears now, or ``None`` (no provider, not
    transformed, a raising provider or an answer without an alias)."""
    if not subject:
        return None
    got = _call(PROVIDER_ACTIVE, subject)
    if not isinstance(got, dict):
        return None
    alias = got.get("alias")
    if not isinstance(alias, str) or not alias.strip():
        return None

    def _s(key: str) -> str:
        v = got.get(key)
        return v if isinstance(v, str) else ""

    return Persona(subject=subject, persona_id=_s("persona_id"), alias=alias.strip(),
                   description=_s("description"), portrait_url=_s("portrait_url"))


def _knows_state(observer: str, subject: str, persona: Optional[Persona]) -> Any:
    """True / False, or ``_FAILED`` when the knows provider raised."""
    if persona is None or _same(observer, subject):
        return True
    got = _call(PROVIDER_KNOWS, observer, subject)
    if got is _MISSING:
        return False
    if got is _FAILED:
        return _FAILED
    return bool(got)


def knows(observer: str, subject: str) -> bool:
    """Whether ``observer`` sees through ``subject``'s current persona.

    True for the subject herself (casefold), for a subject without a persona,
    and when the provider says so. A raising provider counts as True — the
    view the observer would have without the package.
    """
    state = _knows_state(observer, subject, active_persona(subject))
    return True if state is _FAILED else bool(state)


def _label(observer: str, subject: str, persona: Optional[Persona]) -> str:
    if persona is None or _same(observer, subject):
        return subject
    state = _knows_state(observer, subject, persona)
    if state is _FAILED:
        return subject
    if state:
        return f"{persona.alias} ({subject})"
    return persona.alias


def shown_name(observer: str, subject: str) -> str:
    """The name ``observer`` perceives for ``subject``.

    The real name when C wears no persona or O is C; ``"<alias> (<name>)"``
    for a knower; the alias for everyone else.
    """
    return _label(observer, subject, active_persona(subject))


def shown_names(observer: str, subjects: Iterable[str]) -> List[str]:
    """:func:`shown_name` for each subject, in order."""
    return [shown_name(observer, s) for s in subjects]


def identity_key(subject: str) -> str:
    """The observer-independent key of who ``subject`` is right now: the alias
    while transformed, else the real name. Used for relationship rows and
    memory ``related_character``."""
    persona = active_persona(subject)
    return persona.alias if persona else subject


def public_label(subject: str) -> str:
    """The public view of ``subject`` for shared texts (scene summaries): the
    alias while transformed, else the real name."""
    persona = active_persona(subject)
    return persona.alias if persona else subject


def masked_description(observer: str, subject: str) -> Optional[str]:
    """The persona description that replaces ``subject``'s real appearance for
    ``observer`` — only when O is a non-knower of C's active persona; else
    ``None`` (use the real appearance). May be ``""`` when the persona has no
    description: the real appearance must still not be shown."""
    persona = active_persona(subject)
    if persona is None or _same(observer, subject):
        return None
    state = _knows_state(observer, subject, persona)
    if state is _FAILED or state:
        return None
    return persona.description


def resolve_name(observer: str, token: str) -> Optional[str]:
    """The real character a name token refers to, from ``observer``'s mouth.

    A roster name (exact, then case-insensitive) answers itself as stored; the
    alias of an ACTIVE persona (case-insensitive) answers its subject; anything
    else — including the alias of a persona nobody wears right now — ``None``.
    A label of the form ``"<alias> (<name>)"`` is the caller's to split.
    """
    tok = (token or "").strip()
    if not tok:
        return None
    from app.models.character import list_available_characters
    roster = list_available_characters()
    if tok in roster:
        return tok
    folded = tok.casefold()
    for name in roster:
        if name.casefold() == folded:
            return name
    from app.core.hooks import get_provider
    if get_provider(PROVIDER_ACTIVE) is None:
        return None
    for name in roster:
        persona = active_persona(name)
        if persona is not None and persona.alias.casefold() == folded:
            return name
    return None


#: ``"<head> (<inner>)"`` — a knower's label ``"<alias> (<name>)"``, or a
#: name with a suffix a prompt line carried (``"<name> (avatar)"``).
_LABEL_RE = re.compile(r"^(?P<head>.*?\S)\s*\((?P<inner>[^()]*)\)\s*$")


def _split_label(token: str) -> Optional[Tuple[str, str]]:
    """``(head, inner)`` of a ``"<head> (<inner>)"`` token, else ``None``."""
    m = _LABEL_RE.match(token or "")
    if not m:
        return None
    return m.group("head").strip(), m.group("inner").strip()


def _match(observer: str, token: str) -> Tuple[Optional[str], bool]:
    """``(subject, by_alias)`` for one token: :func:`resolve_name`, plus
    whether the token named the subject by an alias rather than by name."""
    subject = resolve_name(observer, token)
    if subject is None:
        return None, False
    return subject, not _same(subject, token)


def resolve_present(observer: str, token: str) -> Optional[str]:
    """The real character ``observer`` means with ``token`` — for a resolver
    that reaches someone IN PERSON (talk, walk over, invite, interact).

    The token may be a roster name, the alias of an active persona, or a
    label ``"<alias> (<name>)"`` / ``"<name> (<suffix>)"`` (resolved by the
    part before the parenthesis). The real name of a character who wears a
    persona right now resolves only for an observer who :func:`knows` her:
    for everyone else the real person is not here — ``None``, the
    resolver's ordinary unknown/not-present path. Presence itself is still
    the caller's check. With no provider this is :func:`resolve_name`.
    """
    tok = (token or "").strip()
    if not tok:
        return None
    subject, by_alias = _match(observer, tok)
    if subject is None:
        parts = _split_label(tok)
        if parts is not None:
            subject, by_alias = _match(observer, parts[0])
    if subject is None:
        return None
    if not by_alias and not knows(observer, subject):
        return None
    return subject


def resolve_remote(observer: str, token: str) -> Tuple[Optional[str], str]:
    """``(real name, "")`` for a resolver that reaches someone REMOTELY
    (messages): the real name works for every observer — the message reaches
    her as herself — and so does a label ``"<alias> (<name>)"`` through its
    name part. A persona has no contact: a token that names the subject only
    by an active alias answers ``(None, "Error: <alias> cannot be reached
    that way.")``. Anything else ``(None, "")`` — the caller's unknown path.
    """
    tok = (token or "").strip()
    if not tok:
        return None, ""
    candidates = [tok]
    parts = _split_label(tok)
    if parts is not None:
        candidates += [parts[1], parts[0]]
    alias = ""
    for cand in candidates:
        subject, by_alias = _match(observer, cand)
        if subject is None:
            continue
        if not by_alias:
            return subject, ""
        if not alias:
            persona = active_persona(subject)
            alias = persona.alias if persona else cand
    if alias:
        return None, f"Error: {alias} cannot be reached that way."
    return None, ""


def is_persona_name(name: str) -> bool:
    """Whether ``name`` is a configured alias (transformed or not), casefolded."""
    folded = (name or "").strip().casefold()
    if not folded:
        return False
    got = _call(PROVIDER_NAMES)
    if got is _MISSING or got is _FAILED or got is None or isinstance(got, (str, bytes)):
        return False
    try:
        return any(isinstance(n, str) and n.strip().casefold() == folded for n in got)
    except TypeError:
        return False


def identity_snapshot(names: Iterable[str]) -> Dict[str, str]:
    """``{subject: alias}`` for the names that wear a persona right now."""
    out: Dict[str, str] = {}
    for name in names:
        persona = active_persona(name)
        if persona is not None:
            out[name] = persona.alias
    return out


def pair_stamp(a: str, b: str) -> Dict[str, Any]:
    """The identity stamp for one message between ``a`` and ``b``, saved now.

    ``{"identity": {subject: alias}, "identity_shown": {subject: label}}`` for
    the side(s) that wear a persona right now, where ``label`` is
    :func:`shown_name` of that subject as the OTHER side sees it — a pairwise
    message has exactly these two readers. ``{}`` when neither is transformed
    (or no provider is registered)."""
    sides = [n for n in (a, b) if n]
    snap = identity_snapshot(sides)
    if not snap:
        return {}
    shown: Dict[str, str] = {}
    for subject in snap:
        other = b if subject == a else a
        shown[subject] = shown_name(other, subject)
    return {"identity": snap, "identity_shown": shown}


def stamped_name(observer: str, subject: str, stamp: Any) -> str:
    """The name ``observer`` reads for ``subject`` on a message that carries
    ``stamp`` (a :func:`pair_stamp` result inside the message metadata).

    No alias stamped for the subject (an older message, or one spoken
    undisguised) → the real name, as before. Stamped and the subject still
    wears that alias → the live :func:`shown_name` (a later reveal counts).
    Stamped and the persona is no longer worn → the label stamped at saving
    time: what was said as the persona stays the persona's, also after the
    revert. The subject herself always reads her real name; with no provider
    registered every stamp is ignored (deletion test: real names)."""
    if not subject or _same(observer, subject) or not isinstance(stamp, dict):
        return subject
    identity = stamp.get("identity")
    alias = identity.get(subject) if isinstance(identity, dict) else None
    if not isinstance(alias, str) or not alias.strip():
        return subject
    from app.core.hooks import get_provider
    if get_provider(PROVIDER_ACTIVE) is None:
        return subject
    persona = active_persona(subject)
    if persona is not None and _same(persona.alias, alias):
        return _label(observer, subject, persona)
    shown = stamp.get("identity_shown")
    label = shown.get(subject) if isinstance(shown, dict) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return alias.strip()


def rewrite_names(observer: str, text: str, subjects: Iterable[str]) -> str:
    """Replace each transformed subject's real name in ``text`` by
    :func:`shown_name` for ``observer`` — whole words, case-sensitive, in one
    pass (an inserted label is never rewritten again). For text the system or
    the storyteller builds, never for a character's own speech."""
    if not text:
        return text
    mapping: Dict[str, str] = {}
    for subject in subjects:
        if not subject or subject in mapping:
            continue
        label = _label(observer, subject, active_persona(subject))
        if label != subject:
            mapping[subject] = label
    if not mapping:
        return text
    alternation = "|".join(re.escape(s) for s in sorted(mapping, key=len, reverse=True))
    pattern = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")
    return pattern.sub(lambda m: mapping[m.group(0)], text)
