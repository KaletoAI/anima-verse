"""Pre-decision data loader for the AgentLoop's slim thought prompt.

Gathers inbox / events / assignments / commitments / arc / outfit-trigger
data and formats each as a ready-to-render block string. The slim template
``shared/templates/llm/chat/agent_thought.md`` only emits a section when
its block is non-empty — so what we don't load here, the agent doesn't see.

Public API:
    build_thought_context(character_name, tools_hint='') -> dict

Returns a kwargs dict that can be passed straight into
``render('chat/agent_thought.md', **ctx)``.
"""
import re
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now, game_local_now
from typing import Any, Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger("thought_context")


# Window during which "you just moved" justifies an outfit-decision hint.
_OUTFIT_AFTER_LOCATION_MINUTES = 10
# Hours since last retrospect that count as "boost — time to reflect".
_RETROSPECT_BOOST_HOURS = 24
# Thought journal (plan-thought-journal.md): how many of the character's own
# last thoughts go back into the next thought prompt, and how much of EACH of
# them. Module constants on purpose — config sprawl only once there is a real
# tuning need.
#
# Two decisions, both measured (task A1.1 + the A1.2b follow-up):
#
# HOW MUCH — a journal entry is the character's whole narrated turn (hundreds of
# characters of finished prose). Handed back verbatim it invites the model to
# copy it instead of continuing it: 20 of 25 verbatim prompt→answer blocks of
# >=100 characters sat in exactly this section, up to 1199 characters long, and
# the copied blocks were long (P90 125 words). A ~45-word fragment is too short
# to pass as a finished answer worth reusing.
#
# WHICH END — the TAIL. A narrated turn opens with scene setting and ends with
# the intention ("… and I decide to come back tomorrow"). The block exists to
# answer "what was I in the middle of", so it must carry the intention. Measured
# over 308 long journal entries, of the 169 that contain an intention marker at
# all, a 300-character CLOSING excerpt carries it in 99 (59 %) — against 42
# (25 %) for a 198-character opening excerpt and 38 (22 %) for head+tail split.
THOUGHT_RECENT_N = 3
THOUGHT_RECENT_TAIL_CHARS = 300
# Derived: the whole block can never exceed N excerpts plus their "- " prefix
# and joining newline. Kept as a constant because callers and checks assert
# against the rendered block as a whole.
THOUGHT_RECENT_CHARS = THOUGHT_RECENT_N * (THOUGHT_RECENT_TAIL_CHARS + 3)


def build_thought_context(character_name: str, tools_hint: str = "") -> Dict[str, Any]:
    """Build the kwargs dict for ``chat/agent_thought.md``.

    Loads only what's needed: each block is computed lazily and only set
    when it has content. The template renders nothing for empty blocks.
    """
    from app.models.character import (
        get_character_profile, get_character_current_location,
        get_character_language_instruction)
    from app.models.world import get_location_name

    profile = get_character_profile(character_name)
    location_id = profile.get("current_location", "") or ""
    room_id = profile.get("current_room", "") or ""
    location_name = get_location_name(location_id) if location_id else "Unknown"
    # Presence is three pieces of information: who is in the ROOM, who is
    # elsewhere at this location, AND whether "nobody in the room" is a fact
    # or just unknown. The template needs all of them.
    present_people_block, elsewhere_block, alone_here = _build_presence(
        character_name, location_id, room_id)

    ctx: Dict[str, Any] = {
        "character_name": character_name,
        # Sprach-Instruktion des Characters (z.B. "Always respond in German.")
        # — sonst erzeugt der Thought-Turn englische Spontan-Aeusserungen.
        "lang_instruction": get_character_language_instruction(character_name),
        "personality": (profile.get("character_personality", "") or "").strip(),
        "location_name": location_name,
        "activity": ("Sleeping" if profile.get("is_sleeping")
                     else (profile.get("pose_intent") or "")) or "None",
        "feeling": (profile.get("current_feeling", "") or "Neutral"),
        "time_of_day": game_local_now().strftime("%H:%M"),  # in-game clock (world TZ)
        # Defaults for optional blocks — keep them present so StrictUndefined
        # doesn't raise on missing keys.
        "inbox_block": _build_inbox_block(character_name),
        "events_block": _build_events_block(location_id),
        "assignments_block": _build_assignments_block(character_name),
        "general_task": _build_general_task(profile),
        "commitments_block": _build_commitments_block(character_name),
        "state_flags_block": _build_state_flags_block(character_name),
        "outfit_decision_block": _build_outfit_decision_block(character_name),
        "arc_block": _build_arc_block(character_name),
        "retrospective_block": _build_retrospective_block(character_name),
        "skill_context_blocks": "",  # set below from _skill_block_parts (fine-grained drops)
        # Additional context — currently rendered in agent_thought_in_chat.md.
        # Agent_thought.md ignores them silently (no template reference).
        "effects_block": _build_effects_block(character_name),
        "recent_chat_block": _build_recent_chat_block(character_name),
        # The character's OWN last thoughts — continuity of inner life. Private
        # to this character: it never reaches anyone else's prompt.
        "recent_thoughts": recent_thoughts_block(character_name),
        "outfit_self_block": _build_outfit_block(character_name, "Your outfit"),
        "outfit_avatar_block": _build_avatar_outfit_block(),
        "room_items_block": _build_room_items_block(location_id, room_id),
        "inventory_block": _build_inventory_block(character_name),
        "present_people_block": present_people_block,
        "elsewhere_block": elsewhere_block,
        "alone_here": alone_here,
        "tracker_block": _build_tracker_block(character_name, location_id),
        "activity_hint_block": _build_activity_hint_block(character_name, location_id, room_id),
        "daily_schedule_block": _build_daily_schedule_block(character_name),
        "tools_hint": tools_hint,
        "has_assignments": False,  # set below if assignments_block non-empty
    }
    ctx["has_assignments"] = bool(ctx["assignments_block"])

    # Closing action instruction — MODE-AWARE (this is why an rp_first RP
    # model was emitting tool JSON: the old hardcoded line told it to
    # "execute the corresponding tool"). In rp_first the RP pass must write
    # pure in-character prose; the separate Tool-LLM translates it into
    # tool calls afterwards. Single/no_tools keep the tool instruction.
    try:
        from app.models.character import get_character_config
        _chat_mode = (get_character_config(character_name) or {}).get("chat_mode", "")
    except Exception:
        _chat_mode = ""
    if _chat_mode == "rp_first":
        ctx["action_instruction"] = (
            "Decide what you want to do next. Pick ONE meaningful action and "
            "play it out fully IN CHARACTER — narrate what you do and say as "
            "prose, first person. Do NOT write tool calls, JSON, function "
            "syntax or field lists; just act it out. If nothing relevant "
            "right now, reply only with: SKIP.")
    else:
        ctx["action_instruction"] = (
            "Decide what you want to do next. Pick ONE meaningful action and "
            "execute the corresponding tool. If nothing relevant, reply only "
            "with: SKIP.")

    # Skill prompt contributions as (package_id, text) parts → the joined string
    # (skill_context_blocks) plus an internal parts list for fine-grained
    # skill:<pkg> drop-block filtering in prompt_filters. The underscore key is
    # internal — the agent_thought.md template never references it (StrictUndefined).
    _skill_parts = _build_skill_context_blocks(character_name)
    ctx["_skill_block_parts"] = _skill_parts
    ctx["skill_context_blocks"] = "\n\n".join(t for _, t in _skill_parts)

    # State-driven filters: drop blocks + inject modifier text based on
    # active conditions/stats (drunk, exhausted, …). Replaces the old
    # rules-based effects_block path.
    try:
        from app.core.prompt_filters import apply_filters
        apply_filters(character_name, ctx, location_id=location_id)
    except Exception as e:
        logger.debug("prompt_filters apply failed for %s: %s", character_name, e)

    # has_assignments may have changed if the filter dropped assignments_block
    ctx["has_assignments"] = bool(ctx["assignments_block"])
    return ctx


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

def _build_inbox_block(character_name: str) -> str:
    """Pre-formatted inbox block: per-sender unread messages with context."""
    try:
        from app.core.agent_inbox import load_unread_messages
        unread = load_unread_messages(character_name,
            max_per_sender=3, context_messages=2)
        if not unread:
            return ""
        lines: List[str] = []
        for sender, msgs in unread.items():
            lines.append(f"From {sender}:")
            for m in msgs:
                marker = "[NEW]" if m.get("unread") else "[seen]"
                role = m.get("role", "")
                # Speaker label: 'user' role = the sender; 'assistant' = self
                speaker = sender if role == "user" else character_name
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                # Truncate very long messages so the prompt stays slim.
                if len(content) > 400:
                    content = content[:400].rstrip() + " […]"
                lines.append(f"  {marker} {speaker}: {content}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("inbox block failed for %s: %s", character_name, e)
        return ""


def _build_state_flags_block(character_name: str) -> str:
    """Situation lines for package-declared state flags (flag lifecycle) —
    e.g. "You are still wet — use DryOff …". Generic: the texts come from
    the packages' state_flags declarations, this code knows no flag."""
    try:
        from app.core.flag_lifecycle import situation_lines
        lines = situation_lines(character_name)
        return "\n".join(f"- {line}" for line in lines) if lines else ""
    except Exception as e:
        logger.debug("state flags block failed for %s: %s", character_name, e)
        return ""


def _build_skill_context_blocks(character_name: str) -> List[Tuple[str, str]]:
    """Prompt contributions of the character's active skills as
    ``(package_id, block_text)`` parts (generic).

    Each skill may return a self-contained section via
    thought_context_block() — e.g. the instagram package's pending block.
    The package_id lets prompt_filters drop a single package's block via a
    ``skill:<pkg>`` drop-block entry (fine-grained), while the joined string
    stays ``skill_context_blocks`` (coarse, drops all). Knows no skill content (R1)."""
    try:
        from app.core.dependencies import get_skill_manager
        skills = get_skill_manager()._get_agent_skills(
            character_name, check_limits=False)
    except Exception:
        return []
    try:
        from app.plugins.registry import package_of_skill
    except Exception:
        package_of_skill = None
    parts: List[Tuple[str, str]] = []
    for skill in skills:
        sid = getattr(skill, "SKILL_ID", "") or ""
        try:
            block = (skill.thought_context_block(character_name) or "").strip()
        except Exception as e:
            logger.debug("thought context block failed (%s): %s", sid or "?", e)
            continue
        if not block:
            continue
        pkg_id = sid
        if package_of_skill:
            try:
                pkg = package_of_skill(sid)
                if pkg:
                    pkg_id = pkg.id
            except Exception:
                pass
        parts.append((pkg_id, block))
    return parts


def _build_events_block(location_id: str) -> str:
    """Active events at the character's location."""
    if not location_id:
        return ""
    try:
        from app.models.events import build_events_prompt_section
        return (build_events_prompt_section(location_id=location_id) or "").strip()
    except Exception as e:
        logger.debug("events block failed: %s", e)
        return ""


def _build_assignments_block(character_name: str) -> str:
    """Active intents (plans & tasks) for this character — unified store
    (plan-intents-unified.md)."""
    try:
        from app.models.intents import build_intents_prompt_section
        return (build_intents_prompt_section(character_name) or "").strip()
    except Exception as e:
        logger.debug("intents block failed for %s: %s", character_name, e)
        return ""


def _build_general_task(profile: Dict[str, Any]) -> str:
    """Static general task from the character profile (long-running purpose)."""
    return (profile.get("character_task", "") or "").strip()


def _build_commitments_block(character_name: str) -> str:
    """Open commitments — promises this character made and hasn't fulfilled."""
    try:
        from app.models.memory import load_memories
        from app.models.character import character_exists
        memories = load_memories(character_name)
        # Dangling-Filter: Commitments gegenueber einem nicht (mehr) existierenden
        # Character ausblenden (related_character gesetzt aber nicht in der Welt).
        open_ones = [
            m for m in memories
            if m.get("memory_type") == "commitment"
            and "completed" not in (m.get("tags") or [])
            and not (m.get("related_character") and not character_exists(m.get("related_character")))
        ]
        if not open_ones:
            return ""
        # Newest first, cap at 5 to keep prompt slim.
        open_ones.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        lines = []
        for m in open_ones[:5]:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            delay = (m.get("delay") or "").strip()
            suffix = f" (when: {delay})" if delay else ""
            lines.append(f"- {content}{suffix}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("commitments block failed for %s: %s", character_name, e)
        return ""


def _bare_slots_summary(character_name: str) -> str:
    """Short summary of essential UNCOVERED slot groups ('' = fully dressed).

    Groups: upper body (top/underwear_top/outer), lower body
    (bottom/underwear_bottom/legs), feet. Multi-slot pieces count via
    collect_covered_slots. Used by the outfit line (the agent must KNOW it
    is naked — "Your outfit: boots" reads like a full outfit otherwise)
    and by the recurring outfit-decision hint.
    """
    try:
        from app.models.inventory import get_equipped_pieces
        from app.core.outfit_renderer import collect_covered_slots
        pieces = get_equipped_pieces(character_name) or {}
        covered = collect_covered_slots(pieces)
    except Exception as e:
        logger.debug("bare-slots summary failed for %s: %s", character_name, e)
        return ""

    def worn(slot: str) -> bool:
        return bool(pieces.get(slot)) or slot in covered

    upper = worn("top") or worn("underwear_top") or worn("outer")
    lower = worn("bottom") or worn("underwear_bottom") or worn("legs")
    feet = worn("feet")
    if not upper and not lower and not feet:
        return "completely naked"
    parts: List[str] = []
    if not upper:
        parts.append("topless")
    elif worn("outer") and not worn("top") and not worn("underwear_top"):
        parts.append("nothing underneath the outer layer")
    if not lower:
        parts.append("naked below the waist")
    if not feet:
        parts.append("barefoot")
    return ", ".join(parts)


def _build_outfit_decision_block(character_name: str) -> str:
    """Outfit-decision hint when:
      a) location changed within the last N minutes, OR
      b) the agent just woke up (activity changed away from 'Sleeping'
         within the last N minutes), OR
      c) recurring: essential slots are bare while the character is up and
         about (not sleeping/intimate/in water, no decency exemption) —
         the one-shot hints (a)/(b) are easily ignored and never return,
         which left characters naked or barefoot for days.

    The agent is free to ignore the hint via SKIP.
    """
    try:
        from app.core.db import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT location_changed_at, activity_changed_at, current_activity, "
            "is_sleeping, is_wet, is_intimate, decency_exempt "
            "FROM character_state WHERE character_name=?",
            (character_name,),
        ).fetchone()
        if not row:
            return ""
        (loc_changed_at, activity_changed_at, current_activity,
         is_sleeping, is_wet, is_intimate, decency_exempt) = row
        now = utc_now()
        cur_activity_lc = (current_activity or "").strip().lower()

        # (a) Recent location change
        if loc_changed_at:
            try:
                changed = parse_iso(loc_changed_at)
                if now - changed <= timedelta(minutes=_OUTFIT_AFTER_LOCATION_MINUTES):
                    return (
                        "You recently changed location. Consider whether your "
                        "current outfit still fits the new context — if not, "
                        "use OutfitChange.")
            except (ValueError, TypeError):
                pass

        # (b) Recent wake-up: activity transitioned AWAY from Sleeping. We
        # detect by checking the most recent state_history activity entries
        # — if the previous activity was Sleeping and the change was within
        # the wake-up window, signal an outfit decision.
        if cur_activity_lc != "sleeping" and activity_changed_at:
            try:
                changed = parse_iso(activity_changed_at)
            except (ValueError, TypeError):
                changed = None
            if changed and now - changed <= timedelta(minutes=_OUTFIT_AFTER_LOCATION_MINUTES * 2):
                # Look at the previous activity in state_history.
                try:
                    prev = conn.execute(
                        "SELECT state_json FROM state_history "
                        "WHERE character_name=? AND ts < ? "
                        "ORDER BY ts DESC LIMIT 5",
                        (character_name, activity_changed_at),
                    ).fetchall()
                    import json as _json
                    for (sj,) in prev:
                        try:
                            d = _json.loads(sj or "{}")
                        except Exception:
                            continue
                        if d.get("type") == "activity":
                            prev_val = (d.get("value") or "").strip().lower()
                            if prev_val == "sleeping":
                                return (
                                    "You just woke up. Consider whether your "
                                    "sleepwear still fits the day ahead — if "
                                    "not, use OutfitChange.")
                            break  # only check the most recent activity
                except Exception:
                    pass

        # (c) Recurring bare-slot hint. Suppressed while sleeping, intimate,
        # in water, or under a decency exemption (nudity is fine there).
        if not (is_sleeping or is_wet or is_intimate or decency_exempt) \
                and cur_activity_lc != "sleeping":
            bare = _bare_slots_summary(character_name)
            if bare:
                return (
                    f"You are currently {bare}. If that is not intentional "
                    "for the situation you are in, get dressed via "
                    "OutfitChange (your inventory has clothes).")

        return ""
    except Exception as e:
        logger.debug("outfit-decision block failed for %s: %s", character_name, e)
        return ""


def _build_arc_block(character_name: str) -> str:
    """Active story arc context (low priority)."""
    try:
        from app.core.story_engine import get_story_engine
        return (get_story_engine().inject_arc_context(character_name) or "").strip()
    except Exception as e:
        logger.debug("arc block failed for %s: %s", character_name, e)
        return ""


def _build_retrospective_block(character_name: str) -> str:
    """Recent beliefs/lessons/goals + a hint to reflect when overdue.

    Returns empty when ``retrospect_enabled`` is false for this character
    (per-char config or template feature) — the agent_thought.md template
    skips the block via ``{% if retrospective_block %}``.

    Otherwise: shows most recent entries from the soul files (so they
    influence decisions) and adds a "time to reflect" hint when the last
    Retrospect was >24h ago. Soul files are the same ones the user can
    edit in the Soul-Editor UI; Retrospect appends to them in place.
    """
    try:
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "retrospect_enabled"):
            return ""
        from app.core.soul_writer import load_all_body_lines, get_last_retrospect_at

        beliefs = load_all_body_lines(character_name, "beliefs", limit=6)
        lessons = load_all_body_lines(character_name, "lessons", limit=6)
        goals = load_all_body_lines(character_name, "goals", limit=6)
        last_at = get_last_retrospect_at(character_name)

        overdue = True
        if last_at:
            try:
                last_dt = parse_iso(last_at)
                overdue = utc_now() - last_dt > timedelta(hours=_RETROSPECT_BOOST_HOURS)
            except (ValueError, TypeError):
                pass

        lines: List[str] = []
        if beliefs:
            lines.append("Your beliefs so far:")
            lines.extend(f"  {b}" for b in beliefs)
        if lessons:
            lines.append("Lessons you've learned:")
            lines.extend(f"  {l}" for l in lessons)
        if goals:
            lines.append("Goals on record:")
            lines.extend(f"  {g}" for g in goals)
        if overdue:
            lines.append("(It's been a while since you last reflected — consider using Reflect.)")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("retrospective block failed for %s: %s", character_name, e)
        return ""


# ---------------------------------------------------------------------------
# In-Chat extras (also useful for the regular template)
# ---------------------------------------------------------------------------

def _build_effects_block(character_name: str) -> str:
    """Active status modifiers + danger conditions (drunk, exhausted, etc.).

    Reuses ``danger_system.build_status_prompt_section`` which already
    knows how to combine stat-based modifiers, danger levels and active
    conditions into a single prompt section.
    """
    try:
        from app.core.danger_system import build_status_prompt_section
        return (build_status_prompt_section(character_name) or "").strip()
    except Exception as e:
        logger.debug("effects block failed for %s: %s", character_name, e)
        return ""


# A sentence end: closing punctuation, optionally followed by closing quotes or
# brackets, at a word boundary. The quote tail matters here — narrated turns are
# full of `sagte ich."` and `"Komm her."` and a boundary missed there costs a
# whole sentence.
_SENTENCE_END = re.compile(r"[.!?…][\"»”'’)\]]*(?=\s|$)")


def _closing_excerpt(text: str, limit: int) -> str:
    """The END of one journal entry, at most ``limit`` characters.

    The tail is what the block is for: a narrated turn opens with scene setting
    and closes with the intention the character was left holding. So the excerpt
    grows backwards from the end — as many WHOLE sentences as fit, and a hard
    cut at a word boundary only when not even the last sentence fits.

    The leading "… " marks where text was dropped (the beginning) and is the
    visible signal that this is a fragment of an earlier turn, not a finished
    piece of prose to be reused. Short entries are returned untouched.
    """
    if len(text) <= limit:
        return text
    budget = limit - 2  # room for the leading "… " marker
    # Every position a sentence STARTS at (right behind a sentence end).
    starts = []
    for m in _SENTENCE_END.finditer(text):
        s = m.end()
        while s < len(text) and text[s].isspace():
            s += 1
        if s < len(text):
            starts.append(s)
    # The earliest of those whose tail still fits = the most whole sentences.
    fitting = [s for s in starts if len(text) - s <= budget]
    if fitting:
        return "… " + text[min(fitting):]
    # Not even the last sentence fits — cut hard. Move to the next word start so
    # the fragment doesn't begin inside a word, unless that would cost more than
    # half the budget (one very long word): the "… " already says it's a cut.
    cut = len(text) - budget
    space = text.find(" ", cut)
    if space != -1 and len(text) - (space + 1) >= budget // 2:
        cut = space + 1
    return "… " + text[cut:].lstrip()


def recent_thoughts_block(character_name: str) -> str:
    """The character's own last thoughts, OLDEST FIRST — one closing excerpt each.

    Newest last so the prompt reads chronologically into the present moment.
    Of each entry only its END is handed over, at most
    ``THOUGHT_RECENT_TAIL_CHARS`` characters (see ``_closing_excerpt``) — that
    is where the intention of a narrated turn sits. At most ``THOUGHT_RECENT_N``
    entries are rendered, so the whole block stays within the derived
    ``THOUGHT_RECENT_CHARS``. A long thought is shortened, never dropped.
    Empty journal → empty string, and the template then renders no block at
    all.

    The journal itself keeps the full text — only this prompt-facing handover
    is condensed.

    Public because the smoke checks it directly; it is otherwise only called
    from ``build_thought_context``.
    """
    try:
        from app.models.thought_store import list_thoughts
        rows = list_thoughts(character_name, limit=THOUGHT_RECENT_N)
    except Exception as e:
        logger.debug("recent_thoughts_block(%s): %s", character_name, e)
        return ""
    if not rows:
        return ""
    lines: List[str] = []
    # rows are newest first — flip at the end so the block reads oldest first.
    for row in rows:
        text = " ".join((row.get("content") or "").split())
        if not text:
            continue
        lines.append(f"- {_closing_excerpt(text, THOUGHT_RECENT_TAIL_CHARS)}")
    return "\n".join(reversed(lines))


def _build_recent_chat_block(character_name: str, limit: int = 3) -> str:
    """Last N chat messages between this character and their most recent
    chat partner (avatar OR another NPC via TalkTo).

    The thought turn doesn't carry chat history by default — when the
    character is mid-conversation we want them to see the latest exchanges
    so a follow-up thought can refer to actual content. Newest first.

    Partner-Aufloesung: wir verlassen uns NICHT auf ``get_active_character``
    (im AgentLoop-Background-Kontext oft leer und greift bei NPC↔NPC-
    TalkTo-Konversationen ohnehin nicht). Stattdessen lesen wir das
    Gegenueber direkt aus dem letzten ``chat_messages``-Eintrag dieses
    Characters — egal in welcher Storage-Richtung.

    Anschliessend ``UnifiedChatManager.get_chat_history`` mergen beide
    Storage-Richtungen (A,B)/(B,A) und dedupen Doppel-Eintraege.
    """
    try:
        from app.core.db import get_connection
        from app.models.unified_chat import UnifiedChatManager
        conn = get_connection()
        # Letzten Partner aus beiden Speicher-Richtungen finden
        row = conn.execute(
            "SELECT ts, partner, character_name FROM chat_messages "
            "WHERE character_name=? OR partner=? "
            "ORDER BY ts DESC LIMIT 1",
            (character_name, character_name),
        ).fetchone()
        if not row:
            return ""
        # Partner = die Seite die NICHT character_name ist
        ts, p_partner, p_char = row
        partner = p_partner if p_char == character_name else p_char
        if not partner:
            return ""
        history = UnifiedChatManager.get_chat_history(
            character_name=character_name, partner_name=partner)
        if not history:
            return ""
        recent = history[-limit:] if limit else history
        lines: List[str] = []
        for msg in recent:
            role = getattr(msg, "role", "") or ""
            content = (getattr(msg, "content", "") or "").strip()
            if not content:
                continue
            speaker = partner if role == "user" else character_name
            if len(content) > 400:
                content = content[:400].rstrip() + " […]"
            lines.append(f"  {speaker}: {content}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("recent_chat block failed for %s: %s", character_name, e)
        return ""


def _build_outfit_block(character_name: str, label: str) -> str:
    """Equipped outfit fragment for any character. Returns ``label: ...`` or ''.

    Includes a bare-slot suffix ("— otherwise topless, barefoot"): without
    it, "Your outfit: boots" reads like a full outfit and the agent never
    learns it is naked (root cause of the days-long-naked NPCs)."""
    try:
        from app.core.outfit_renderer import render_outfit
        out = render_outfit(character_name=character_name)
        raw = (out.get("pieces") or "").strip()
        bare = _bare_slots_summary(character_name)
        if not raw:
            return f"{label}: nothing — you are completely naked" if bare else ""
        if bare:
            return f"{label}: {raw} — otherwise {bare}"
        return f"{label}: {raw}"
    except Exception as e:
        logger.debug("outfit block failed for %s: %s", character_name, e)
        return ""


def _build_avatar_outfit_block() -> str:
    """Avatar outfit. Returns 'Avatar outfit (<name>): ...' or ''."""
    try:
        from app.models.account import get_active_character
        avatar = (get_active_character() or "").strip()
        if not avatar:
            return ""
        return _build_outfit_block(avatar, f"Avatar outfit ({avatar})")
    except Exception as e:
        logger.debug("avatar outfit block failed: %s", e)
        return ""


def _build_room_items_block(location_id: str, room_id: str) -> str:
    """Items present in the current room (visible only — hidden ones skipped).

    Format: bullet list of "name (xN) — short description". Cap at 8.
    """
    if not location_id or not room_id:
        return ""
    try:
        from app.models.inventory import get_room_items, get_item
        items = get_room_items(location_id, room_id) or []
        if not items:
            return ""
        lines: List[str] = []
        for ri in items:
            if ri.get("hidden"):
                continue
            iid = ri.get("item_id") or ""
            qty = ri.get("quantity", 1) or 1
            item = get_item(iid) or {}
            name = (item.get("name") or iid or "?").strip()
            desc = (item.get("description") or "").strip()
            if len(desc) > 80:
                desc = desc[:80].rstrip() + "…"
            qty_str = f" (x{qty})" if qty > 1 else ""
            line = f"- {name}{qty_str}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
            if len(lines) >= 8:
                break
        return "\n".join(lines)
    except Exception as e:
        logger.debug("room_items block failed (%s/%s): %s", location_id, room_id, e)
        return ""


def _build_inventory_block(character_name: str) -> str:
    """Character's carried inventory (excludes equipped pieces). Cap at 8.

    ``get_character_inventory`` enriches each entry with ``item_name`` /
    ``item_description`` (resolved from the items table). Falls back to
    item_id only if the lookup failed.
    """
    try:
        from app.models.inventory import get_character_inventory
        inv = get_character_inventory(character_name, include_equipped=False) or {}
        items = inv.get("inventory") if isinstance(inv, dict) else inv
        if not items:
            return ""
        lines: List[str] = []
        for entry in items[:8]:
            iid = entry.get("item_id") or ""
            qty = entry.get("quantity", 1) or 1
            name = (entry.get("item_name") or iid or "?").strip()
            qty_str = f" (x{qty})" if qty > 1 else ""
            lines.append(f"- {name}{qty_str}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("inventory block failed for %s: %s", character_name, e)
        return ""


def _build_tracker_block(character_name: str, current_location_id: str) -> str:
    """Lines for each carried item with a `tracks_character` field.

    Reveals the tracked character's current location to the carrier — the
    in-world fiction is a magical amulet/ring/sigil that pinpoints another
    being. Skips items whose target is missing, equals self, or has no
    location yet. The agent decides what to do with the info; movement still
    requires SetLocation.
    """
    try:
        from app.models.inventory import get_character_inventory, get_item
        from app.models.character import get_character_current_location
        from app.models.world import get_location_name
        inv = get_character_inventory(character_name, include_equipped=True) or {}
        items = inv.get("inventory") if isinstance(inv, dict) else inv
        if not items:
            return ""
        lines: List[str] = []
        seen_targets: set = set()
        for entry in items:
            iid = entry.get("item_id") or ""
            if not iid:
                continue
            item = get_item(iid)
            if not item:
                continue
            target = (item.get("tracks_character") or "").strip()
            if not target or target == character_name:
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            target_loc = get_character_current_location(target) or ""
            item_name = (item.get("name") or iid).strip()
            if not target_loc:
                lines.append(f"- Your {item_name} reaches for {target}, but cannot find them right now.")
                continue
            if target_loc == current_location_id:
                lines.append(f"- Your {item_name} hums softly: {target} is here with you.")
                continue
            loc_name = get_location_name(target_loc) or target_loc
            lines.append(f"- Your {item_name} reveals: {target} is at {loc_name}.")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("tracker block failed for %s: %s", character_name, e)
        return ""


def present_people_details(entries, location_id: str = "") -> str:
    """Visible-detail lines for present characters — worn outfit (short)
    plus visibly triggered states. ``entries`` = [(name, display_label)].
    Shared by the thought context AND the chat system prompt (R5): what a
    character can SEE of the people around them."""
    lines = []
    for n, label in entries[:8]:
        details = []
        try:
            # The REAL person description (appearance + body-slot fragments +
            # worn outfit + state modifiers) — same function the scene
            # renderer uses for text persons; capped per person.
            from app.core.scene_render import _appearance_text
            desc = (_appearance_text(n) or "").strip()
            if desc:
                if len(desc) > 180:
                    desc = desc[:180].rstrip(", ") + "…"
                details.append(desc)
        except Exception:
            pass
        try:
            from app.core.prompt_filters import triggered_state_labels
            states = triggered_state_labels(n, location_id)
            if states:
                details.append("visibly " + ", ".join(states[:4]))
        except Exception:
            pass
        lines.append(f"- {label}" + (f": {'; '.join(details)}" if details else ""))
    return "\n".join(lines)


def _build_presence(character_name: str, location_id: str,
                    room_id: str) -> Tuple[str, str, bool]:
    """Presence split by ROOM, excluding self. Avatar marked.

    Returns ``(room_block, elsewhere_block, alone_known)``:
    - ``room_block`` — people in the SAME room, with full visible details.
    - ``elsewhere_block`` — people in OTHER rooms of this location, name +
      room only (they are out of sight and out of earshot — no visual
      details, or the LLM stages scenes with people it cannot see).
    - ``alone_known`` is True ONLY when the lookup succeeded and really
      nobody else is in the room — an unknown location or a failed lookup
      yields ``("", "", False)``, because "we don't know" must never be
      rendered as "you are alone".

    Why the room split (2026-07-30): both presence blocks used to be
    location-wide, so an NPC was told a person two rooms away was visibly
    present — and kept staging a physical scene (TalkTo) with someone who
    could never hear it (speech reach is the room, plan-room-conversation).
    The prompt now matches the perception model.

    Why alone_known exists: an empty block used to drop the whole section
    from the prompt, so the prompt said NOTHING about who is around. A
    missing section is no evidence of absence for an LLM — with a stale
    pose like "standing in front of Kai" it happily kept playing a scene
    with a person who was at the other end of the map. Silence is not
    "alone"; the prompt has to say it.

    Each same-room person carries what the character can SEE: a short
    outfit line (worn pieces) and visibly triggered states ('drunk',
    'aroused', ...) — without this, an NPC never knows what the people
    around it look like right now."""
    if not location_id:
        return "", "", False
    try:
        from app.models.account import get_active_character
        avatar = (get_active_character() or "").strip()
        here_names, elsewhere_pairs = location_presence_split(
            character_name, location_id, room_id)
        here = [(n, f"{n} (avatar)" if n == avatar else n) for n in here_names]
        elsewhere = [
            f"- {n} (avatar) — in: {room}" if n == avatar else f"- {n} — in: {room}"
            for n, room in elsewhere_pairs]
        room_block = present_people_details(here[:8], location_id) if here else ""
        return room_block, "\n".join(elsewhere[:8]), not here
    except Exception as e:
        logger.debug("present_people block failed for %s: %s", character_name, e)
        return "", "", False


def location_presence_split(character_name: str, location_id: str,
                            room_id: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Split the location's characters by room, excluding self.

    Returns ``(here_names, elsewhere_pairs)``: names in the SAME room
    (exact ``current_room`` equality, matching the perception model) and
    ``(name, room_label)`` pairs for other rooms of this location. The ONE
    computation behind the prompt presence blocks and the thought
    journal's ``nearby`` snapshot — no second SQL path.

    Raises on lookup failure (callers decide what "unknown" means —
    _build_presence must not render a failed lookup as "you are alone").
    """
    from app.models.group_chat import get_characters_at_location
    from app.models.character import get_character_current_room
    from app.models.world import get_room_name
    here: List[str] = []
    elsewhere: List[Tuple[str, str]] = []
    for p in (get_characters_at_location(location_id) or [])[:16]:
        n = (p.get("name") or "").strip()
        if not n or n == character_name:
            continue
        other_room = get_character_current_room(n) or ""
        if other_room == (room_id or ""):
            here.append(n)
        else:
            elsewhere.append(
                (n, get_room_name(location_id, other_room) or "another room"))
    return here, elsewhere


def _build_activity_hint_block(character_name: str,
                               location_id: str,
                               room_id: str) -> str:
    """Free-text activity direction of the current room (fallback:
    location) — "what one typically does here". The LLM decides freely;
    there is no activity library anymore (renamed from the library-era
    available_activities_block)."""
    if not location_id:
        return ""
    try:
        from app.models.world import get_room_activity_hint
        return get_room_activity_hint(location_id, room_id)
    except Exception as e:
        logger.debug("activity hint block failed for %s: %s", character_name, e)
        return ""

def _build_daily_schedule_block(character_name: str) -> str:
    """Soft hint about the character's typical rhythm at the current hour.

    Each slot now carries ``location`` and ``role`` (or ``sleep: true``).
    Hours without a slot are intentionally left blank — the agent is free
    to choose. Sleep stays a hint; the energy-based rule decides whether
    it actually triggers. Returns '' if there is no usable hint.
    """
    try:
        from app.models.character import get_character_daily_schedule
        schedule = get_character_daily_schedule(character_name) or {}
        if not schedule.get("enabled"):
            return ""
        slots = schedule.get("slots") or []
        if not slots:
            return ""

        loc_id_to_name: Dict[str, str] = {}
        try:
            from app.models.world import list_locations
            for loc in list_locations() or []:
                lid = (loc.get("id") or loc.get("name") or "").strip()
                lname = (loc.get("name") or lid).strip()
                if lid:
                    loc_id_to_name[lid] = lname
        except Exception:
            pass

        slot_by_hour: Dict[int, Dict[str, Any]] = {}
        for s in slots:
            try:
                h = int(s.get("hour"))
            except (TypeError, ValueError):
                continue
            slot_by_hour[h] = s

        now = utc_now()
        cur_h = now.hour
        next_h = (cur_h + 1) % 24

        def _fmt(slot: Dict[str, Any], hour: int) -> str:
            if slot.get("sleep"):
                return f"  {hour:02d}:00 — you usually sleep around now"
            loc = (slot.get("location") or "").strip()
            role = (slot.get("role") or "").strip()
            parts = []
            if loc:
                parts.append(f"location: {loc_id_to_name.get(loc, loc)}")
            if role:
                parts.append(f"role: {role}")
            if not parts:
                return ""
            return f"  {hour:02d}:00 — " + ", ".join(parts)

        lines: List[str] = []
        cur = slot_by_hour.get(cur_h)
        if cur:
            line = _fmt(cur, cur_h)
            if line:
                lines.append(line)
        nxt = slot_by_hour.get(next_h)
        if nxt and nxt is not cur:
            line = _fmt(nxt, next_h)
            if line:
                lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        logger.debug("daily_schedule block failed for %s: %s", character_name, e)
        return ""
