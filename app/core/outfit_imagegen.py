"""The character's image settings as a render reads them — with a worn
persona folded in.

A character's own image settings live in ``profile["outfit_imagegen"]``
(written by ``character_ops.apply_outfit_imagegen``: backend globs per
occasion, ``loras``, ``tpose_loras``, legacy ``model``). While she wears a
persona (``identity_view``), every image of HER — outfit/expression images,
photo/instagram occasions, T-pose references and therefore the 3D model —
renders with the persona's settings and the persona's look instead. The
stored value is never changed: the override is read-time only.

``PersonaLook`` is the persona state a render needs, captured once:
``token`` (the cache-key part, :func:`identity_view.look_token`),
``appearance`` (the persona description, or ``None`` = the real look) and
``imagegen`` (the persona's image settings, ``None`` = not transformed).

A job that is queued in one state and runs later keeps the state it was
queued in: the caller captures a :class:`PersonaLook` at queue time and runs
the render inside :func:`pinned_look`. Every reader below (and the image
routing's character match) asks :func:`current_look`, which answers the
pinned state inside such a scope and the live one outside it. The pin is a
``ContextVar``: it covers the calling thread (where the routing resolves),
never another thread.

With no identity provider registered every function answers exactly as
before the persona feature (deletion test).
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Iterator, List, Mapping, Optional

#: The backend globs a persona may replace; an empty persona value keeps the
#: character's own.
PERSONA_BACKEND_KEYS = ("workflow", "tpose_workflow")

_EMPTY: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class PersonaLook:
    """What a render of a character needs to know about her persona.

    ``token`` ``""`` / ``"persona:<id>"``; ``appearance`` the persona
    description (``None`` = the real appearance); ``imagegen`` the persona's
    image settings (``None`` = not transformed — the character's own
    settings apply unchanged)."""
    token: str = ""
    appearance: Optional[str] = None
    imagegen: Optional[Mapping[str, Any]] = field(default=None, hash=False)

    @property
    def transformed(self) -> bool:
        return self.imagegen is not None


#: The real look: not transformed.
REAL_LOOK = PersonaLook()

_PINNED: ContextVar[Mapping[str, PersonaLook]] = ContextVar("persona_look_pinned", default=_EMPTY)


def capture_look(character: str) -> PersonaLook:
    """The LIVE persona state of ``character`` (ignores any pin)."""
    from app.core import identity_view
    imagegen = identity_view.persona_imagegen(character)
    if imagegen is None:
        return REAL_LOOK
    return PersonaLook(token=identity_view.look_token(character),
                       appearance=identity_view.self_field(character, "character_appearance"),
                       imagegen=MappingProxyType(copy.deepcopy(imagegen)))


def current_look(character: str) -> PersonaLook:
    """The pinned state of ``character`` inside :func:`pinned_look`, else the
    live one."""
    pinned = _PINNED.get().get(character)
    return pinned if pinned is not None else capture_look(character)


@contextmanager
def pinned_look(character: str, look: Optional[PersonaLook] = None) -> Iterator[PersonaLook]:
    """Pin ``character``'s persona state for the calling thread: ``look``,
    or the current state (``current_look``) captured now. Nested pins of
    other characters stay; the previous state is restored on exit."""
    state = look if look is not None else current_look(character)
    merged = dict(_PINNED.get())
    merged[character] = state
    token = _PINNED.set(MappingProxyType(merged))
    try:
        yield state
    finally:
        _PINNED.reset(token)


def _lora_list(value: Any) -> List[Dict[str, Any]]:
    """The persona's LoRA list as stored (``[{name, strength}]``); anything
    that is not a list of dicts counts as empty."""
    if not isinstance(value, (list, tuple)):
        return []
    return [copy.deepcopy(dict(v)) for v in value if isinstance(v, Mapping)]


def merge_outfit_imagegen(stored: Any, look: PersonaLook) -> Dict[str, Any]:
    """``stored`` (the character's ``outfit_imagegen``) with ``look`` folded
    in — see :func:`effective_outfit_imagegen`."""
    out: Dict[str, Any] = copy.deepcopy(dict(stored)) if isinstance(stored, Mapping) else {}
    if look.imagegen is None:
        return out
    persona = look.imagegen
    for key in PERSONA_BACKEND_KEYS:
        value = persona.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    # A persona REPLACES the character's LoRAs: an empty list means no
    # character LoRA at all (a face LoRA would give her away).
    out["loras"] = _lora_list(persona.get("loras"))
    out["tpose_loras"] = _lora_list(persona.get("tpose_loras"))
    out.pop("model", None)
    return out


def effective_outfit_imagegen(character: str, stored: Any) -> Dict[str, Any]:
    """The image settings a render of ``character`` uses, from her stored
    ``outfit_imagegen`` (never modified).

    Not transformed → a copy of ``stored``. Transformed → a copy where
    ``workflow`` / ``tpose_workflow`` are the persona's when non-empty,
    ``loras`` := the persona's ``loras`` (possibly ``[]``), ``tpose_loras``
    := the persona's ``tpose_loras`` (possibly ``[]`` — the render's rule
    "empty = the normal LoRAs" then means the persona's), ``model`` removed.
    Other keys (``profile_workflow``, ``mesh_workflow``,
    ``tpose_view_workflow``) unchanged. Honours :func:`pinned_look`."""
    return merge_outfit_imagegen(stored, current_look(character))
