"""Party prompt section — the package's thought-context contribution.

Until this existed, no prompt said a party was there at all: the verbs were
offered, the engine dragged followers along, but neither the thought turn nor
the chat turn ever told a character that it leads a group or follows someone.
A leader then waited for its followers to "come along" instead of setting out,
which is the one thing only it can do.

Text lives here rather than in a Jinja file to match the neighbouring movement
package (``plugins/movement/blocks.py``), which renders its travel sections the
same way.
"""
from typing import List, Optional

from app.core.log import get_logger

logger = get_logger("party_blocks")


def _and_list(names: List[str]) -> str:
    """"A", "A and B", "A, B and C" — the way a person would say it."""
    clean = [n for n in names if n]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    return f"{', '.join(clean[:-1])} and {clean[-1]}"


def party_section(character_name: str) -> str:
    """What this character has to know about its party — or "" without one.

    Two roles, two different truths: the leader is the only one who can move
    the group, the follower cannot move at all while it follows (the movement
    verbs are hidden from it, see ``SetLocationSkill.visible_for``). Both are
    told how to end it, because leaving is always allowed.
    """
    try:
        from app.core.party_engine import get_party_of
        party: Optional[dict] = get_party_of(character_name)
    except Exception as e:
        logger.debug("party block failed for %s: %s", character_name, e)
        return ""
    if not party:
        return ""

    if party.get("role") == "leader":
        members = [m for m in party.get("members", [])
                   if m and m != character_name]
        if not members:
            return ""
        followers = _and_list(members)
        verb = "travels" if len(members) == 1 else "travel"
        return (
            "=== Your party ===\n"
            f"{followers} {verb} with you, and you lead. Only you choose where "
            "the group goes: set out for a place and they come along — do not "
            "wait for them to move. If you no longer want the company, leave "
            "the party."
        )

    leader = (party.get("leader") or "").strip()
    if not leader:
        return ""
    return (
        "=== Your party ===\n"
        f"You travel with {leader}'s party. {leader} chooses where the group "
        "goes and you come along — you cannot set out on your own while you "
        "follow. If you want to go your own way, leave the party."
    )
