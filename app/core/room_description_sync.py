"""Sync a room's DESCRIPTION with what really stands in it (plan-furnish-v2.md
§ 2b B14b, decision E8).

The description is the author's brief for a room ("a copper kettle over the
hearth, herbs under the ceiling, a heavy wooden table") and the furnishing job
reads it as one. After the job has run, the two drift apart in both directions:
pieces the description promised were never built, and pieces the solver placed
are named nowhere. Chat and image prompts read the DESCRIPTION, so a room can
be full of furniture nobody in the world knows about.

E8 settles it as a BUTTON WITH A PREVIEW, never an automatic rewrite: this
module builds the inventory, asks one LLM for a new text and hands it back.
Nothing here writes — :func:`apply` is a separate call the admin triggers after
reading the proposal, and it goes through the ordinary room-description update
(``world.update_room_description``), the same path the room editor and the
describe-room skill use.

THE INVENTORY IS ONE LINE PER PIECE THAT STANDS THERE. A placement counts
once, whether it stands on the floor or on a table (a child placement carrying
``on`` is a piece of furniture like any other — the parent link is geometry,
not quantity), and a scattered anchor counts as the one piece the author
placed. Temporary ``need:<key>`` ids cannot appear: the layout sanitizer
refuses a prop id with a colon, so only ACCEPTED, real props ever reach a
stored layout.
"""

from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger(__name__)

#: How much of the model's answer is kept. The prompt asks for 60–160 words;
#: the cap is the anti-runaway bound, not the wish.
MAX_DESCRIPTION_CHARS = 4000


def _language_name(code: str) -> str:
    """Resolve a UI language code ("de") to its English name ("German") for
    the prompt. An unknown value passes through unchanged, so a free-text
    language name keeps working; an empty one means English."""
    if not code:
        return "English"
    from app.core.i18n import list_languages
    for entry in list_languages():
        if entry.get("value") == code:
            return str(entry.get("label") or code)
    return code


def inventory(job_id: str) -> List[Dict[str, Any]]:
    """What the room's stored layout really holds — ``{name, count, mount}``
    per prop, sorted by name.

    ``job_id`` is the furnish job's target id, so the yard's composite
    ``__ground__@<location>`` works exactly like a room id. A placement whose
    prop the library does not know is skipped: it renders as a placeholder box
    and has no name to put in a sentence.
    """
    from app.core.props import list_props
    from app.core.room_furnish import _load_room, _mount_of

    _loc, room = _load_room(job_id)
    library = {p["id"]: p for p in list_props()}
    counts: Dict[str, int] = {}
    layout = room.get("layout") if isinstance(room.get("layout"), dict) else {}
    for entry in (layout.get("props") or []):
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("prop_id") or "")
        if pid in library:
            counts[pid] = counts.get(pid, 0) + 1
    out = [{"name": str(library[pid].get("name") or pid),
            "count": count,
            "mount": _mount_of(library[pid])}
           for pid, count in counts.items()]
    return sorted(out, key=lambda e: str(e["name"]).lower())


def _llm_text(task: str, system_prompt: str, user_prompt: str,
              label: str) -> str:
    """The one PLAIN-TEXT LLM hop of this module — the seam a smoke replaces.

    Not ``llm_json``: this task answers a paragraph of prose, so the answer is
    the response content, trimmed. Everything else (routing, queue, logging)
    is the shared path.
    """
    from app.core import llm_router
    response = llm_router.llm_call(task, system_prompt, user_prompt,
                                   label=label)
    return str(getattr(response, "content", "") or "")


def propose(job_id: str, lang: str = "") -> Dict[str, Any]:
    """One rewritten description for this room — PREVIEW ONLY.

    Answers ``{"proposal": <text>, "inventory": [...]}``; the caller shows
    both and decides. A room whose layout holds nothing is not refused: an
    empty inventory is a legitimate answer ("the room is bare"), and refusing
    it would make the button lie about rooms the admin has just cleared.
    """
    from app.core.prompt_templates import render_task
    from app.core.room_furnish import FurnishError, _load_room, _room_label

    _loc, room = _load_room(job_id)
    room_name = _room_label(room)
    items = inventory(job_id)
    sys_p, user_p = render_task(
        "room_description_sync",
        room_name=room_name,
        description=str(room.get("description") or "").strip(),
        inventory=items,
        language=_language_name(lang))
    text = _llm_text("room_description_sync", sys_p, user_p,
                     f"Description sync: {room_name}").strip()
    if not text:
        raise FurnishError("The model answered with nothing.", 502)
    logger.info("room_description_sync %s: proposal over %d kind(s), %d chars",
                job_id, len(items), len(text))
    return {"proposal": text[:MAX_DESCRIPTION_CHARS], "inventory": items}


def apply(job_id: str, description: str) -> Dict[str, Any]:
    """Write the (possibly hand-edited) text as the room's description.

    Goes through ``world.update_room_description``, which validates the text
    the same way every other writer's does — a refused text answers 400 rather
    than silently doing nothing.
    """
    from app.models.world import update_room_description
    from app.core.room_furnish import FurnishError, _load_room, _target

    loc, _room = _load_room(job_id)
    text = str(description or "").strip()[:MAX_DESCRIPTION_CHARS]
    if not text:
        raise FurnishError("The description is empty.", 400)
    room_id, _loc_id = _target(job_id)
    if not update_room_description(str(loc.get("id") or ""), room_id, text):
        raise FurnishError("The description could not be stored.", 400)
    logger.info("room_description_sync %s: description updated (%d chars)",
                job_id, len(text))
    return {"status": "saved", "description": text}
