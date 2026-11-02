"""Who may take part in an action, and in front of whom
(plan-intim-privatsphaere.md, part B).

The core names no rule here: packages answer through the capability
``participation.check`` (``hooks.register_provider(..., multiple=True)``),
called as ``fn(kind, key, members, location_id, room_id, *, offer=False)``.

* ``kind`` — ``"prop_action"`` (a furniture action whose ``presence`` is
  ``"policy"``) or ``"pose"`` (a free pair pose: invitation and start).
* ``key`` — the pose key the action holds.
* ``members`` — every character taking part, the initiator first.
* ``offer`` — True when a menu asks whether to offer, False for a start.

A provider answers ``""`` (none of its business, or allowed) or
``{"reason": <code>, "message": <English sentence for the LLM>}``. The first
refusal wins, in registration order; a provider that raises is skipped.

One code has a meaning of its own: ``NOT_OFFERED`` ("no_capability") says a
participant cannot do this at all — menus leave such an entry out instead of
showing it blocked (``offered``). Every other refusal is shown with its reason.
"""
from typing import Dict, Iterable, List

from app.core.log import get_logger

logger = get_logger("participation")

CAPABILITY = "participation.check"
#: the refusal that hides an entry from menus instead of greying it out
NOT_OFFERED = "no_capability"


def check(kind: str, key: str, members: Iterable[str], location_id: str, room_id: str,
          *, offer: bool = False) -> Dict[str, str]:
    """``{}`` when every provider allows it, else the first refusal as
    ``{"reason", "message"}``."""
    from app.core.hooks import get_providers
    members = [m for m in members if m]
    for fn in get_providers(CAPABILITY):
        try:
            got = fn(kind, key, members, location_id, room_id, offer=offer)
        except Exception as e:
            logger.warning("participation provider %s failed: %s",
                           getattr(fn, "__qualname__", fn), e)
            continue
        if isinstance(got, dict) and isinstance(got.get("reason"), str) and got["reason"]:
            message = got.get("message")
            return {"reason": got["reason"],
                    "message": message if isinstance(message, str) and message else got["reason"]}
    return {}


def offered(kind: str, key: str, members: Iterable[str], location_id: str = "",
            room_id: str = "") -> bool:
    """Whether a menu lists the entry at all: every refusal but
    ``NOT_OFFERED`` still lists it (blocked, with its reason)."""
    return check(kind, key, members, location_id, room_id, offer=True).get("reason") != NOT_OFFERED


def onlookers(members: Iterable[str], location_id: str, room_id: str) -> List[str]:
    """The PEOPLE besides ``members`` who are there: everyone in the room
    inside a location; out in the open everyone within earshot of a member
    (``perception.addressable_for``). Animals are nobody (``is_humanoid``),
    the same rule the furniture presence check applies. Sorted."""
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile
    members = {m for m in members if m}
    if location_id:
        from app.core import places
        names = {n for n, _ in places._present(location_id, room_id)}
    else:
        from app.core.perception import addressable_for
        names = {n for m in members for n in addressable_for(m)}
    out = []
    for name in sorted(names - members):
        if is_humanoid(name, profile=get_character_profile(name) or {}):
            out.append(name)
    return out

