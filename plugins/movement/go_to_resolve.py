"""Pure decision logic behind the ``GoToCharacter`` verb.

Kept free of every ``app.*`` import on purpose: the decision is a small,
fully deterministic function of four position values plus the actor's known
locations, so it can be checked without a world, a server or a DB
(``scripts/smoke_go_to_character.py``).

The verb itself never invents a route — it only decides WHICH of the
existing movement paths applies, then hands the case to ``SetLocation``.
"""
from typing import Iterable, Tuple


def resolve_go_to(actor_loc: str, actor_room: str,
                  target_loc: str, target_room: str,
                  known_location_ids: Iterable[str]) -> Tuple[str, str]:
    """Decide how the actor reaches the target person's current spot.

    Args:
        actor_loc: location id the actor stands in ("" = nowhere on the map).
        actor_room: room id the actor stands in ("" = the location's ground).
        target_loc: location id the target person stands in RIGHT NOW. For a
            travelling character this is ``current_id`` — the nearest cell,
            which is the game truth — never the journey destination.
        target_room: room id of the target person.
        known_location_ids: the locations the actor may travel to (same
            source the "Places you can go" prompt block uses).

    Returns:
        ``(kind, payload)`` with kind one of:

        * ``"same_room"`` — already standing with the person; payload is the
          shared location id. No movement.
        * ``"room"`` — same location, other room; payload is the target ROOM
          id. Handled by the instant room-change branch of SetLocation.
        * ``"location"`` — other location the actor knows; payload is the
          target location id. Handled by the normal SetLocation/journey path.
        * ``"unknown"`` — the target's location is not among the actor's
          known ones (or the target is nowhere on the map); payload is the
          target location id (possibly ""). The verb refuses and says so —
          it must not hand out new world knowledge.
    """
    known = {str(i) for i in (known_location_ids or []) if i}
    actor_loc = (actor_loc or "").strip()
    actor_room = (actor_room or "").strip()
    target_loc = (target_loc or "").strip()
    target_room = (target_room or "").strip()

    if not target_loc:
        # The person is not on the map (off-map sleep, never placed): there
        # is no spot to walk to, and "unknown" is the honest answer.
        return "unknown", ""
    if actor_loc and actor_loc == target_loc:
        if actor_room == target_room:
            return "same_room", target_loc
        return "room", target_room
    if target_loc in known:
        return "location", target_loc
    return "unknown", target_loc
