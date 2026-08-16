"""Pure decision: does the storyteller step in after an avatar utterance?

Background (plan-room-conversation-ergaenzungsplan, task R1 / A9-rest): the
immediate storyteller fallback in ``/play/say`` only covers "nobody is here".
When characters ARE present but every one of them stays silent (a respond turn
answering ``SKIP`` records no utterance at all), the avatar's line used to fall
into the void. The delayed check in ``play.py`` waits until the room's respond
turns have settled and then asks this module whether the room really stayed
silent.

No DB, no network, no clock — the caller hands in the speech acts recorded
AFTER the avatar's utterance, this decides. That keeps the rule testable
(``scripts/smoke_storyteller_silence.py``).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

# Kept in sync with app.core.perception.STORYTELLER_SPEAKER by the caller,
# which passes the real name in — this default only spares test callers.
DEFAULT_STORYTELLER = "Storyteller"


def should_narrate_silence(utterances_since: Iterable[Dict[str, Any]],
                           avatar: str,
                           storyteller_name: Optional[str] = None) -> bool:
    """True when the storyteller should narrate into the room's silence.

    ``utterances_since`` are the room's speech acts recorded after the avatar
    utterance under test, oldest first (only ``speaker`` is read).

    The rules, in the order they are applied per line:

    * a line by the AVATAR itself → False. The player spoke again; that newer
      utterance carries its own silence check, and narrating for the older one
      would double up.
    * a STORYTELLER line → not an answer, keep looking. Narration (including
      the spell result line ``/play/say`` writes right after the avatar's own
      utterance) must not count as the room reacting, or the storyteller would
      silence itself.
    * anyone else → False, someone actually replied.

    Nothing left over → True: everybody present stayed silent.
    """
    av = (avatar or "").strip()
    st = (storyteller_name or DEFAULT_STORYTELLER).strip()
    for u in utterances_since or []:
        speaker = (u.get("speaker") or "").strip()
        if not speaker:
            continue
        if av and speaker == av:
            return False
        if st and speaker == st:
            continue
        return False
    return True
