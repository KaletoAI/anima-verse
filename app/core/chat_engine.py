"""
Chat Engine — shared logic for the chat paths.

Provides:
- build_chat_context(): prepares system prompt, history, tools
- post_process_response(): mood, location, memory, relationship extraction
"""
import asyncio
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.core.timeutils import utc_now_iso

from app.core.log import get_logger
from app.core.perception import STORYTELLER_SPEAKER

logger = get_logger("chat_engine")


def dedupe_assistant_repeats(messages: List[Dict[str, str]],
                             drop_preceding_user: bool = True,
                             log_label: str = "History") -> List[Dict[str, str]]:
    """Drops assistant messages whose fuzzy signature was already seen.

    Breaks the self-reinforcement loop: a model that sees its own phrase twice
    in the context writes it a third time. Only the FIRST occurrence stays (see
    ``history_manager.fuzzy_signature`` — marker/whitespace variants match).

    ``drop_preceding_user`` decides what happens to the line before a dropped
    duplicate:

    - 1:1 history (True): the "user" line is the partner's message this reply
      answered. It goes with it, so no question stays behind without an answer.
    - Room transcript (False): a "user" line is a DIFFERENT speaker's utterance,
      prefixed with their name. Deleting it because my own reply was a duplicate
      would erase a third party's words from the scene — the responder would
      answer a conversation it never heard.

    Public because the standalone check calls it directly; otherwise only used
    by ``build_chat_context``.
    """
    from app.utils.history_manager import fuzzy_signature

    seen: set = set()
    deduped: List[Dict[str, str]] = []
    for msg in messages:
        if msg.get("role") == "assistant":
            key = fuzzy_signature(msg.get("content", ""))
            if key and key in seen:
                if drop_preceding_user and deduped and deduped[-1]["role"] == "user":
                    deduped.pop()
                continue
            if key:
                seen.add(key)
        deduped.append(msg)
    if len(deduped) < len(messages):
        logger.info("%s: %d fuzzy duplicates removed (%d → %d)",
                    log_label, len(messages) - len(deduped),
                    len(messages), len(deduped))
    return deduped


def _messages_from_room_stream(responder: str,
                               stream: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Builds the conversation from the responder's room perception stream
    (multi-party transcript) instead of the 1:1 chat history.

    Core of the room conversation: what the character HEARD in the room is its
    conversational context — not an old pairwise history. Foreign lines are
    prefixed with the speaker name (`Thalion: …`) so the LLM knows who said what
    in a multi-person scene.

    The prefix also carries WHOM a line was aimed at, taken from the row's
    ``meta.addressees`` (absent/empty = said to the room):

    - no addressees      → ``Thalion: …``
    - one addressee      → ``Thalion (to Liesa): …``
    - several            → ``Thalion (to Liesa, Karl): …``
    - the responder among them → its own name becomes ``you``, the original
      order stays: ``Thalion (to you): …``, ``Thalion (to you, Karl): …``

    Without it a character cannot tell a line meant for it from one it merely
    overheard. The responder's own lines stay role "assistant" with no prefix.
    Whisper meta (no content) is dropped.
    """
    out: List[Dict[str, str]] = []
    for row in stream or []:
        meta = row.get("meta") or {}
        sp = (row.get("speaker") or meta.get("speaker") or "").strip()
        content = (row.get("content") or "").strip()
        kind = row.get("kind") or ""
        if not content or kind == "whisper_meta":
            continue
        if sp and sp == responder:
            out.append({"role": "assistant", "content": content})
        else:
            addressees = [str(a).strip() for a in (meta.get("addressees") or [])
                          if str(a).strip()]
            if addressees:
                shown = ", ".join("you" if a == responder else a
                                  for a in addressees)
                prefix = f"{sp or '?'} (to {shown})"
            else:
                prefix = sp or "?"
            out.append({"role": "user", "content": f"{prefix}: {content}"})
    return out


def _build_rp_tool_system(character_name: str, agent_tools: list,
                          tool_format: str, tool_model_name: str,
                          partner_name: str) -> str:
    """Baut den System-Prompt für die rp_first-Tool-Phase (non-streaming Variante
    des Blocks aus routes/chat.py). Der Tool-LLM erkennt damit narrative Aktionen
    (ChangeOutfit, SetLocation, SetActivity, …) und ruft die passenden Tools.
    """
    from app.core.tool_formats import build_tool_instruction
    from app.core.dependencies import get_skill_manager
    from app.core.outfit_renderer import render_outfit
    from app.models.character import (get_character_appearance,
                                       get_character_current_location,
                                       get_character_language_instruction)
    from app.models.character_template import is_roleplay_character
    from app.models.world import list_locations_for_character
    from app.models.account import get_active_character

    sm = get_skill_manager()
    appearance = get_character_appearance(character_name) or ""
    usage = sm.get_agent_usage_instructions(character_name, tool_format, check_limits=False)
    instr = build_tool_instruction(tool_format, agent_tools, appearance, usage,
                                   model_name=tool_model_name,
                                   is_roleplay=is_roleplay_character(character_name))
    names = [t.name for t in agent_tools]

    loc_id = get_character_current_location(character_name) or ""
    loc_list = ", ".join(l.get("name", "")
                         for l in list_locations_for_character(character_name)
                         if l.get("name"))
    act_list = ""
    if loc_id:
        try:
            from app.core import places
            from app.models.character import get_character_current_room
            act_list = places.room_offer(character_name, loc_id,
                                         get_character_current_room(character_name) or "")
        except Exception:
            act_list = ""
    self_outfit = render_outfit(character_name=character_name).get("full", "") or "(nothing equipped)"
    outfit_block = f"\n{character_name} currently wears: {self_outfit}"
    avatar = get_active_character() or ""
    if avatar and avatar != character_name:
        av_outfit = render_outfit(character_name=avatar).get("full", "") or "(nothing equipped)"
        outfit_block += f"\n{avatar} currently wears: {av_outfit}"

    real_partner = (partner_name or "").strip()
    if real_partner.lower() in {"user", "player", "spieler", "admin", ""}:
        real_partner = ""
    if real_partner:
        header = f"Character: {character_name}. Conversation partner: {real_partner}.\n"
        warn = (f"IMPORTANT: Do NOT use TalkTo for {real_partner} — "
                f"they are already in the conversation.\n")
    else:
        header = f"Character: {character_name}.\n"
        warn = ""
    lang = get_character_language_instruction(character_name)
    lang_block = (f"\n{lang} Every message, caption or free-text tool argument "
                  f"you write MUST be in that language.\n") if lang else ""
    return (f"{header}{instr}\n\nAvailable tools: {', '.join(names)}\n"
            f"Decide which tools to call based on the conversation. "
            f"If no tools are needed, respond with: NONE\n{warn}{lang_block}"
            f"\nKnown locations: {loc_list}\n"
            + (f"{act_list}\n" if act_list else "")   # the offer brings its own headings
            + outfit_block)


def _rp_tool_decision_input(user_input: str, rp_response: str,
                            tools_dict: Dict[str, Any],
                            in_person: bool = False,
                            agent_name: str = "") -> str:
    """Tool decision prompt for the character-to-character chat turn.

    The action→tool mapping, the speech note and the anti-hallucination rules
    come from the SAME source as the streaming path (app.core.streaming), so
    both prompts always offer exactly the tools this character actually has —
    minus the movement verbs an in-person turn would discard anyway.

    ``agent_name`` decides how this character may move at all — the same rule
    the server applies when it reads the answer
    (``routes.chat._marker_travel_refusal``): whoever owns the movement verb
    is sent to the verb, a character with no other way keeps the place marker,
    and a party follower or an avatar is told nothing about moving, because
    neither way is open to it. Without a name the marker is left out: naming a
    way that turns out to be closed is how a model writes one anyway.
    """
    from app.core.streaming import (action_mapping_lines, decision_tools,
                                    speech_turn_note, tool_decision_guardrails)
    tools_dict = decision_tools(tools_dict, suppress_in_person=in_person)
    try:
        from app.routes.chat import _marker_travel_refusal
        _move_refusal = _marker_travel_refusal(agent_name) if agent_name else "no_name"
    except Exception:
        _move_refusal = "no_name"
    if not _move_refusal:
        _place_rule = (
            ", and **I am at <room or place>** ONLY when the RP explicitly describes "
            "physically setting off — a room of this place is reached at once, a place "
            "from the list starts a walk")
    elif "SetLocation" in tools_dict:
        _place_rule = (
            ". When the RP describes setting off for another place, call SetLocation "
            "from the list above — never write **I am at ...**, it is refused for this "
            "character")
    else:
        _place_rule = ""
    return (
        f"The user said: {user_input}\n\n"
        f"The character responded:\n{rp_response}\n\n"
        f"Analyze the response and call any tool the character's narrative action "
        f"triggers. The character NEVER writes tool calls themselves; you do that. "
        f"Fire the tool whenever the narrative shows the action, even if phrased "
        f"indirectly (\"she goes to change\", \"puts on a dress\", \"heads to the kitchen\", "
        f"\"let's go to the forest edge\"). This list is the character's COMPLETE tool "
        f"inventory — never call a tool that is not on it:\n"
        f"{action_mapping_lines(tools_dict)}\n"
        f"{speech_turn_note(tools_dict, False)}"
        f"Call every tool that applies; multiple are fine. Do NOT skip a tool because "
        f"the action was \"only described\" narratively — that IS the signal.\n"
        f"{tool_decision_guardrails(tools_dict, with_markers=not _move_refusal)}"
        f"Also emit fallback markers the character forgot (only if NOT already wrapped "
        f"in **...** in the RP): **I feel <emotion>**, "
        f"**I do <pose key>: <what you do, 2-6 words>**"
        f"{_place_rule}. The pose key is one of the keys listed after a place (or under "
        f"'Anywhere here'), copied exactly; the part after the colon is the detail (what a "
        f"bystander would see), and may be left out. Use the character's language; match "
        f"exact names from the lists in your system prompt.\n"
        f"If nothing applies, respond with: NONE")


def chat_llm_task(character_name: str) -> str:
    """The routing task a character's CHAT replies resolve their model through.

    Temporary NPCs answer through ``npc_talk`` so an admin can put them on a
    fast model (spec-npc-conversation § 2); everyone else stays on
    ``chat_stream``. ONE place, because every reply path — the respond lane,
    a chime, the exit beat, TalkTo, group chat — builds its context here.
    Unrouted, ``npc_talk`` falls back to ``chat_stream`` through the
    ``npc_*`` rule in ``llm_router.resolve_llm``, so a world that never
    opened the routing tab keeps working. Fails open to ``chat_stream``: an
    unreadable sheet is an ordinary character, not a broken chat.
    """
    if not character_name:
        return "chat_stream"
    try:
        from app.models.character import is_temporary_npc
        if is_temporary_npc(character_name):
            return "npc_talk"
    except Exception as e:  # noqa: BLE001 — a reply must never fail on this
        logger.debug("chat_llm_task(%s): %s", character_name, e)
    return "chat_stream"


def attach_moment(messages: List[Dict[str, Any]], moment: str) -> List[Dict[str, Any]]:
    """Hangs the scene state on the last user turn — after the history.

    Returns a NEW list; the history dicts are never mutated (they are reused
    for the next turn, where they must reach the backend byte-identical, or
    its prompt cache breaks right there). The last message is replaced by a
    copy with the scene state appended, separated by a blank line — the same
    join ``streaming.compose_messages`` uses. When the list does not end with
    a user turn (or is empty) the scene state becomes a user turn of its own,
    so a model always gets it last. An empty scene state changes nothing.
    """
    if not moment:
        return list(messages)
    out = list(messages)
    if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), str):
        last = dict(out[-1])
        last["content"] = (f"{last['content']}\n\n{moment}"
                           if last["content"] else moment)
        out[-1] = last
    else:
        out.append({"role": "user", "content": moment})
    return out


def build_chat_context(
    owner_id: str,
    character_name: str,
    user_input: str,
    selected_skills: Optional[list] = None,
    speaker: str = "user",
    medium: Optional[str] = None,
    partner_name: str = "",
    room_stream: Optional[List[Dict[str, Any]]] = None,
    respond_opportunity: bool = False,
    winding_down: bool = False,
    addressed_to: Optional[List[str]] = None,
    moment_notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Build everything needed to run a chat: system prompt, scene state,
    message history, LLM instances, and tool setup.

    Args:
        owner_id: User who owns the character (storage path)
        character_name: Character name (the responder)
        user_input: Current incoming message
        selected_skills: Optional skill filter
        speaker: "user" (default) or the name of the speaking character.
            For character-to-character, speaker is the sender's name.
        medium: Communication medium as the characters see it:
            "in_person", "messaging", "instagram".
            None = auto-derived from the speaker context.
        partner_name: For character-to-character: the speaking character
            (= speaker when speaker != "user"). Used for history file names.
        addressed_to: Names the incoming line was addressed to. None = not
            known / plain 1:1 chat — the prompt then treats the line as
            addressed to the responder. An empty list means "said to the
            room", i.e. addressed to nobody in particular.
        moment_notes: One-off context of this turn (e.g. a caller's hint);
            it lands in the scene state next to the character's active state
            modifiers.

    Returns:
        Dict with keys: system_content, moment_content (the scene state —
        hang it on the last user turn, see attach_moment), messages, llm,
        agent_config,
        tools_dict, tool_format, tool_llm, max_iterations,
        full_chat_history, user_display_name, lang_instruction,
        speaker, medium
    """
    from app.core.dependencies import get_skill_manager
    from app.core.llm_router import resolve_llm
    from app.models.character import (
        get_character_config,
        get_character_language_instruction)
    from app.models.account import get_player_identity
    from app.models.chat import get_chat_history
    from app.utils.history_manager import (
        get_time_based_history, get_cached_summary, refresh_summary_if_uncovered,
        strip_history_artifacts, anti_repetition_overrides)
    from app.routes.chat import _build_chat_prompt, _strip_tool_hallucinations

    agent_config = get_character_config(character_name)
    _chat_instance = resolve_llm(chat_llm_task(character_name),
                                 agent_name=character_name)
    lang_instruction = get_character_language_instruction(character_name)
    # The player IS the avatar. ``get_player_identity`` is the one place that
    # says so and keeps a login name out of character contexts; "user" is its
    # sentinel for "no avatar", which the extraction below filters again.
    # (The old ``get_chat_partner()`` fallback named the AGENT as the player's
    # display name and has had no writer since the store routes were removed.)
    user_display_name = get_player_identity("user")

    # Auto-derive the medium when it is not set
    if medium is None:
        if speaker != "user":
            # Character-to-character: in_person when at the same place, else messaging
            try:
                from app.models.character import get_character_current_location
                speaker_loc = get_character_current_location(speaker)
                self_loc = get_character_current_location(character_name)
                medium = "in_person" if (speaker_loc and speaker_loc == self_loc) else "messaging"
            except Exception:
                medium = "messaging"
        else:
            medium = "in_person"

    # Partner name for the history file names: explicit for C2C, else the active character
    _history_partner = partner_name if partner_name else (speaker if speaker != "user" else "")
    # In room mode the 1:1 history below is replaced entirely by the
    # perception stream AND the history_summary is suppressed in the prompt —
    # loading and preparing it would be pure waste. So skip it here
    # (anti-repetition uses the room_stream in room mode anyway).
    full_chat_history = [] if room_stream else get_chat_history(
        character_name, partner_name=_history_partner)

    # Build the LLM — anti-repetition from the chat section of the admin config:
    # frequency_penalty (token penalty) + a graduated temperature bump per
    # detected phrase repetition.
    # Repetition source: in room mode the responder's own most recent room
    # utterances (perception stream) instead of the chat_messages history — that
    # way it works across the whole scene AND survives the chat_messages
    # phase-out (plan-history-consolidation-cleanup.md).
    if room_stream:
        _rep_source = [{"role": "assistant", "content": (r.get("content") or "")}
                       for r in room_stream
                       if (r.get("speaker") or (r.get("meta") or {}).get("speaker") or "").strip()
                       == character_name and (r.get("content") or "").strip()]
    else:
        _rep_source = full_chat_history
    _llm_overrides: Dict[str, Any] = anti_repetition_overrides(
        _rep_source,
        float(getattr(_chat_instance, "temperature", 0.7)),
        agent_name=character_name)
    llm = _chat_instance.create_llm(**_llm_overrides) if _chat_instance else None

    # History window (time-based)
    recent_history, old_history = get_time_based_history(full_chat_history)
    history_summary = (
        refresh_summary_if_uncovered(character_name, old_history)
        if old_history else "")

    messages = []
    # Hallucinated template prefix from the send-message hint:
    # "[Name, ]deine Antwort: '...'" used to be stored as the reply format
    # because the LLM copied the format hint literally. Strip it so the
    # pattern is not echoed into new replies.
    _meta_prefix_re = re.compile(
        r'^(?:[A-Z][\wÄÖÜäöüß \-]{0,30},\s*)?(?:deine|meine|seine|ihre)\s+Antwort:\s*[\'\"]?',
        re.IGNORECASE)
    for msg in recent_history:
        content = msg["content"]
        if msg["role"] == "assistant":
            content = re.sub(r'^\[Gedanken-Nachricht[^\]]*\]\s*', '', content)
            cleaned = _meta_prefix_re.sub('', content).rstrip("'\"").strip()
            if cleaned and cleaned != content:
                content = cleaned
            if content != msg["content"]:
                content = content.strip()
                if not content:
                    continue
            content = _strip_tool_hallucinations(content)
            content = strip_history_artifacts(content)
            if not content:
                continue
            messages.append({"role": "assistant", "content": content})
        else:
            content = strip_history_artifacts(content)
            if not content:
                continue
            messages.append({"role": "user", "content": content})

    # Room mode: the conversation comes from the perception stream (what the
    # character heard in the room), not from the 1:1 history. Fixes that a third
    # person present (e.g. a bystander) answers an address without knowing what
    # was just said and hallucinates from an old pairwise history instead.
    room_mode = bool(room_stream)
    present_characters: List[str] = []
    if room_mode:
        messages = _messages_from_room_stream(character_name, room_stream)
        # Present = the speakers in the room stream (except me + the storyteller) — from
        # that the system prompt builds the group-scene framing (anti-impersonation).
        _seen = set()
        for _row in room_stream:
            _sp = (_row.get("speaker") or (_row.get("meta") or {}).get("speaker") or "").strip()
            if _sp and _sp != character_name and _sp != STORYTELLER_SPEAKER and _sp not in _seen:
                _seen.add(_sp)
                present_characters.append(_sp)

    # Break the self-reinforcement loop — AFTER the room-mode replacement, so it
    # acts on the list that is actually sent. In room mode a "user" line is a
    # foreign speaker, so the preceding line is kept (see
    # dedupe_assistant_repeats).
    messages = dedupe_assistant_repeats(
        messages, drop_preceding_user=not room_mode,
        log_label="Room transcript" if room_mode else "C2C history")

    # Derive the tools from the enabled skills
    sm = get_skill_manager()
    agent_tools = sm.get_agent_tools(character_name, check_limits=False)
    if selected_skills is not None:
        agent_tools = [t for t in agent_tools if t.name in selected_skills]

    # Mode detection: load the tool_llm early for determine_mode + system prompt
    from app.core.dependencies import determine_mode
    _tool_instance = resolve_llm("intent", agent_name=character_name) if agent_tools else None
    tool_llm = _tool_instance.create_llm() if _tool_instance else None
    mode = determine_mode(agent_tools, tool_llm, agent_config)
    tools_enabled = mode != "no_tools"

    # State filters (drunk/exhausted/…): their prompt_modifier is only applied
    # on the thought path. Add it here (chat reply) as well so the character
    # shows its state when answering too — in the scene state, because a
    # state comes and goes; condition_reminder already comes from
    # _build_chat_prompt.
    _notes: List[str] = []
    try:
        from app.core.prompt_filters import active_modifiers
        from app.models.character import get_character_current_location
        _mods = active_modifiers(character_name,
                                 get_character_current_location(character_name) or "")
        if _mods:
            _notes.append("[Current state — let this shape how you respond:]\n"
                          + "\n".join(_mods))
    except Exception as _e:
        logger.debug("chat-context active_modifiers failed: %s", _e)
    _notes.extend(n for n in (moment_notes or []) if n)

    # System prompt + scene state
    _prompt = _build_chat_prompt(character_name, lang_instruction, history_summary,
        tools_enabled=tools_enabled, agent_config=agent_config,
        selected_skills=selected_skills,
        has_tool_llm=(mode == "rp_first"),
        partner_override=(speaker if speaker != "user" else ""),
        medium=medium,
        respond_opportunity=respond_opportunity,
        winding_down=winding_down,
        present_characters=present_characters,
        incoming_text=user_input,
        addressed_to=addressed_to,
        moment_notes=_notes)
    system_content = _prompt.system

    # Tool setup
    tools_dict = {}
    tool_format = "tag"
    max_iterations = 1

    if agent_tools:
        # Initiator: who triggered this chat turn. "user" for a user chat,
        # the speaking character for C2C. Passed through to the skills so
        # talk_to/send_message can create pending_reports.
        _tool_initiator = speaker if speaker else "user"
        for t in agent_tools:
            _orig_func = t.func
            def _make_ctx_wrapper(fn, _agent=character_name, _uid=owner_id, _init=_tool_initiator):
                def wrapper(raw_input):
                    ctx = {"input": raw_input, "agent_name": _agent, "user_id": _uid,
                           "initiator": _init, "skip_daily_limit": True}
                    if isinstance(raw_input, str) and raw_input.strip().startswith("{"):
                        try:
                            parsed = json.loads(raw_input)
                            if isinstance(parsed, dict):
                                for k, v in parsed.items():
                                    if k not in ("agent_name", "user_id", "initiator"):
                                        ctx[k] = v
                        except Exception:
                            pass
                    return fn(json.dumps(ctx))
                return wrapper
            tools_dict[t.name] = _make_ctx_wrapper(_orig_func)
        max_iterations = 3

        from app.core.tool_formats import get_format_for_model
        tool_model_name = _tool_instance.model if _tool_instance else (
            _chat_instance.model if _chat_instance else ""
        )
        tool_format = get_format_for_model(tool_model_name)

    # rp_first-Tool-Phase: System-Prompt + Tool-Klassen vorbereiten, damit
    # run_chat_turn nach der RP-Antwort narrative Aktionen ausführen kann.
    tool_system_content = ""
    deferred_tools: set = set()
    content_tools: set = set()
    if mode == "rp_first" and agent_tools and tool_llm is not None:
        try:
            tool_system_content = _build_rp_tool_system(
                character_name, agent_tools, tool_format, tool_model_name,
                partner_name=(speaker if speaker != "user" else ""))
        except Exception as _e:
            logger.debug("tool_system_content build failed: %s", _e)
        for _t in agent_tools:
            _sk = sm.get_skill_by_name(_t.name)
            if _sk and getattr(_sk, "DEFERRED", False):
                deferred_tools.add(_t.name)
            if _sk and getattr(_sk, "CONTENT_TOOL", False):
                content_tools.add(_t.name)

    return {
        "system_content": system_content,
        "moment_content": _prompt.moment,
        "messages": messages,
        "llm": llm,
        "agent_config": agent_config,
        "tools_dict": tools_dict,
        "tool_format": tool_format,
        "tool_llm": tool_llm,
        "max_iterations": max_iterations,
        "mode": mode,
        "full_chat_history": full_chat_history,
        "old_history": old_history,
        "user_display_name": user_display_name,
        "lang_instruction": lang_instruction,
        "speaker": speaker,
        "medium": medium,
        "partner_name": _history_partner,
        "room_mode": room_mode,
        "agent_tools": agent_tools,
        "tool_system_content": tool_system_content,
        "deferred_tools": deferred_tools,
        "content_tools": content_tools,
        "tool_model_name": tool_model_name if agent_tools else "",
    }


def execute_tool_matches(ctx: Dict[str, Any], responder: str,
                         matches: List[tuple], *, rp_text: str,
                         incoming_message: str) -> None:
    """Run the tool calls of ONE reply under the respond lane's rules.

    Shared by the rp_first tool phase (matches from the tool LLM's decision)
    and the single chat mode (matches written INLINE by the chat model, see
    ``run_chat_turn``). The rules: an unknown tool name is logged and
    skipped; a CONTENT_TOOL is skipped (this path has no chat retry to feed
    its result back); a SUPPRESS_IN_PERSON verb is skipped while the medium
    is in_person (one does not walk away in the turn one answers in); a
    DEFERRED tool runs in a daemon thread with the RP text injected;
    everything else runs right here. Nothing raises out of this function.
    """
    from app.core.streaming import _inject_rp_context
    _deferred_set = ctx.get("deferred_tools") or set()
    _content_set = ctx.get("content_tools") or set()
    _deferred_matches: List[tuple] = []
    for _name, _inp in matches:
        _fn = ctx["tools_dict"].get(_name)
        if not _fn:
            # The model called a tool this character does not have (name
            # mismatch or not enabled). Silently dropping it used to show up
            # as "tool call in the log, never executed" — logged so the
            # reason is visible.
            logger.warning("run_chat_turn[%s]: Tool-Call '%s' ohne Executor "
                           "(nicht verfügbar/Name-Mismatch) — übersprungen "
                           "(verfügbar: %s)", responder, _name,
                           ", ".join(sorted(ctx["tools_dict"].keys())))
            continue
        if _name in _content_set:
            logger.info("run_chat_turn[%s]: Content-Tool %s übersprungen "
                        "(kein Retry-Pfad in run_chat_turn)", responder, _name)
            continue
        if _name in _deferred_set:
            _deferred_matches.append((_name, _inp))
            continue
        # A (plan-follow-room-conversation-bug): whoever ANSWERS in an
        # in-person conversation does not walk away in the same turn.
        # The tool LLM otherwise derives a movement verb from RP prose
        # ("stands up, Move east") while the character was just
        # speaking. Which verbs count is declared by the skills
        # (SUPPRESS_IN_PERSON flag); teleport (spell) is a deliberate
        # act and NOT affected.
        from app.core.streaming import _suppress_in_person_tool_names
        if _name in _suppress_in_person_tool_names() and ctx.get("medium") == "in_person":
            logger.info("run_chat_turn[%s]: %s unterdrückt — Antwort im selben "
                        "in-person-Turn (man geht nicht weg, während man spricht)",
                        responder, _name)
            continue
        try:
            _fn(_inp)
            logger.info("run_chat_turn[%s]: Tool ausgeführt → %s", responder, _name)
        except Exception as _te:
            logger.warning("run_chat_turn[%s]: Tool %s fehlgeschlagen: %s",
                           responder, _name, _te)
    if _deferred_matches:
        # Post-RP execution in a daemon thread: does not block the chat
        # answer (a skill's execute may contain LLM calls for the prompt
        # build); the skills enqueue into the task queue themselves.
        _tools_dict = ctx["tools_dict"]

        def _run_deferred(matches=_deferred_matches, rp=rp_text,
                          ui=incoming_message, who=responder):
            for _dname, _dinp in matches:
                try:
                    _tools_dict[_dname](_inject_rp_context(_dinp, rp, ui))
                    logger.info("run_chat_turn[%s]: Deferred Tool ausgeführt → %s",
                                who, _dname)
                except Exception as _de:
                    logger.error("run_chat_turn[%s]: Deferred Tool %s fehlgeschlagen: %s",
                                 who, _dname, _de)

        import threading
        # bind_trace instead of copying the whole context: the
        # deferred tools deliberately run WITHOUT the caller's
        # perception shadow, they only need the turn's trace id.
        from app.core.turn_trace import bind_trace
        threading.Thread(target=bind_trace(_run_deferred),
                         daemon=True).start()


def run_chat_turn(
    owner_id: str,
    responder: str,
    speaker: str,
    incoming_message: str,
    medium: str = "in_person",
    task_type: str = "character_talk",
    post_process: bool = False,
    room_stream: Optional[List[Dict[str, Any]]] = None,
    respond_opportunity: bool = False,
    hint: str = "",
    winding_down: bool = False,
    addressed_to: Optional[List[str]] = None,
    usage_out: Optional[Dict[str, Any]] = None) -> str:
    """Lets responder generate ONE reply to incoming_message from speaker.

    Synchronous. Used by the talk_to / send_message skills. Uses the existing
    chat engine (system prompt, history, medium context) but WITHOUT
    streaming — a single llm_queue.submit() call.

    Writes both sides of the conversation into the chat history:
      - responder's file: "user" (speaker) → "assistant" (responder)
      - speaker's file: "assistant" (speaker) → "user" (responder)

    ``addressed_to`` names who the incoming line was aimed at. If the caller
    does not know it, it is derived from the room transcript (below), so the
    prompt can tell a line meant for the responder from one it overheard.

    ``usage_out``, when given, receives the chat call's token usage as
    ``{"model"[, "prompt_tokens", "completion_tokens"[, "cached_tokens"]]}``.
    ``model`` is set whenever the call returned; the counts only when the
    backend reported usage, ``cached_tokens`` only when it reported a cache
    figure (see ``llm_client.usage_from_openai``). It stays empty when no call
    returned. The caller hangs it on the utterance so the chat can show how
    much of the prompt the backend served from its cache — or that it says
    nothing about it.

    Returns:
        The responder's cleaned-up response text.
    """
    from app.core.llm_queue import get_llm_queue, Priority
    from app.models.chat import save_message
    from datetime import datetime

    # When the addressed responder is player-controlled (an avatar), NO LLM
    # call may run — the user answers themselves. The incoming message is
    # still stored in both chat histories so it shows up on the next refresh.
    # IMPORTANT: is_player_controlled lives in app.models.account, NOT in
    # app.models.character. A wrong import here used to raise ImportError,
    # the try/except swallowed it and the avatar answered anyway.
    try:
        from app.models.account import is_player_controlled
        if is_player_controlled(responder):
            ts = utc_now_iso()
            _stored = [
                save_message({
                    "role": "user", "content": incoming_message, "timestamp": ts,
                    "speaker": speaker, "medium": medium,
                }, character_name=responder, partner_name=speaker),
                save_message({
                    "role": "assistant", "content": incoming_message, "timestamp": ts,
                    "speaker": speaker, "medium": medium,
                }, character_name=speaker, partner_name=responder),
            ]
            # A lost write here is what the avatar will NOT find in their
            # inbox on the next refresh — there is no turn left to abort, so
            # it is logged loudly and the (empty) answer stays the same.
            if not all(_stored):
                logger.error("run_chat_turn: avatar delivery %s -> %s NOT stored "
                             "(%d of 2 writes failed) — the message is lost",
                             speaker, responder, _stored.count(False))
            logger.info("run_chat_turn: Avatar %s — kein Auto-Reply, "
                        "Message von %s gespeichert (User antwortet selbst)",
                        responder, speaker)
            return ""
    except Exception as _pe:
        logger.warning("run_chat_turn: player_controlled-Check fehlgeschlagen "
                       "(Avatar-Schutz unwirksam): %s", _pe)

    if addressed_to is None and room_stream:
        # The caller did not say whom the line was for — read it off the
        # transcript: the speaker's most recent row carries the addressees.
        _derived: List[str] = []
        for _row in reversed(room_stream):
            _meta = _row.get("meta") or {}
            _sp = (_row.get("speaker") or _meta.get("speaker") or "").strip()
            if _sp and _sp == speaker:
                _derived = [str(a).strip()
                            for a in (_meta.get("addressees") or [])
                            if str(a).strip()]
                break
        if _derived:
            addressed_to = _derived
        elif respond_opportunity:
            # An overheard turn with nothing addressed: said to the room.
            addressed_to = []
        else:
            # Obligatory turn — being called on IS being addressed, even when
            # the row itself carries no addressee list.
            addressed_to = [responder]

    ctx = build_chat_context(owner_id, responder, incoming_message,
        speaker=speaker, medium=medium,
        partner_name=speaker, room_stream=room_stream,
        respond_opportunity=respond_opportunity, winding_down=winding_down,
        addressed_to=addressed_to,
        # One-off immediate context (e.g. a spell effect) — the character
        # reacts to it narratively without it staying in the prompt.
        moment_notes=([f"[{hint}]"] if hint else None))

    if ctx["llm"] is None:
        logger.error("run_chat_turn: Kein LLM fuer %s verfuegbar", responder)
        return ""

    messages = [{"role": "system", "content": ctx["system_content"]}]
    messages.extend(ctx["messages"])
    # In room mode the transcript already carries the triggering utterance as
    # its last line → do not append it again. Only as a fallback (empty
    # transcript) set the trigger explicitly, else the LLM has no last user turn.
    if not ctx.get("room_mode") or not ctx["messages"]:
        messages.append({"role": "user", "content": incoming_message})
    messages = attach_moment(messages, ctx["moment_content"])

    # Label for the task panel — shows who-to-whom via which trigger
    if task_type == "talk_to":
        _label = f"TalkTo: {speaker} → {responder}"
    elif task_type == "send_message":
        _label = f"Message: {speaker} → {responder}"
    else:
        _label = f"{task_type}: {speaker} → {responder}"

    try:
        response = get_llm_queue().submit(
            task_type=task_type,
            priority=Priority.CHAT,
            llm=ctx["llm"],
            messages_or_prompt=messages,
            agent_name=responder,
            label=_label)
        raw = getattr(response, "content", "") or ""
        if usage_out is not None:
            from app.utils.llm_logger import get_model_name
            _usage = getattr(response, "usage", None)
            if isinstance(_usage, dict):
                usage_out.update(_usage)
            usage_out["model"] = get_model_name(ctx["llm"])
    except Exception as e:
        logger.error("run_chat_turn LLM error for %s: %s", responder, e)
        return ""

    # SINGLE chat mode: the chat model writes its tool calls INLINE
    # (``<tool name="…">…</tool>``), exactly as the streaming path's
    # ``_stream_single`` expects. They are read from the RAW text before the
    # cleanup strips them, and executed after the return like the rp_first
    # phase (2026-09-09: without this a temporary NPC's whole answer was the
    # tag, recorded verbatim as its utterance, and the room imitated it).
    _inline_matches: List[tuple] = []
    if ctx.get("mode") == "single" and ctx.get("tools_dict"):
        try:
            from app.core.tool_formats import find_tool_calls
            from app.core.streaming import _dedupe_singleton_tools
            _inline_matches = _dedupe_singleton_tools(find_tool_calls(
                ctx.get("tool_format", "tag"), raw, ctx["tools_dict"]))
        except Exception as _me:  # noqa: BLE001 — the answer still goes out
            logger.warning("run_chat_turn[%s]: inline tool scan failed: %s",
                           responder, _me)
            _inline_matches = []

    clean = clean_response(raw)
    if not clean:
        if _inline_matches:
            # The character DID something, it just said nothing: the tool
            # call was the whole reply. Run it now — there is no reply to
            # hand back first, so nothing waits on this.
            logger.info("run_chat_turn[%s]: reply is tool calls only (%s)",
                        responder, ", ".join(n for n, _ in _inline_matches))
            execute_tool_matches(ctx, responder, _inline_matches, rp_text="",
                                 incoming_message=incoming_message)
            return ""
        logger.warning("run_chat_turn: leere Antwort von %s", responder)
        return ""

    # Chime-in SKIP gate: on an opportunity utterance (not addressed) the
    # character may stay silent. "SKIP" → no reply, no saving, no
    # post-processing, no utterance. Tolerates punctuation/quotes.
    if respond_opportunity or winding_down:
        _probe = clean.strip().strip('"\'`*().!').strip().upper()
        if _probe == "SKIP" or (_probe.startswith("SKIP") and len(_probe) <= 12):
            logger.info("run_chat_turn: %s klinkt sich nicht ein (SKIP)", responder)
            return ""

    # rp_first tool phase (feature parity): a second tool-LLM call spots the
    # narrative actions in the RP text ("puts on shorts", "off to the forest
    # edge") and runs the matching tools, plus the fallback markers (mood,
    # location, activity) that feed post-processing.
    # Classification as in streaming._stream_rp_first: side-effect tools run
    # immediately, DEFERRED tools run after the reply in the background with
    # RP context injected. CONTENT_TOOLs would need a chat retry (the result
    # flows back into the RP) — this path does not have one (yet), so they are
    # logged and skipped.
    # It no longer runs BEFORE the return: the caller gets the answer right
    # away (see _bg_after_reply below) — otherwise the tool-LLM call added
    # ~8 s of visible latency before the utterance was recorded.
    _needs_tool_phase = bool(
        ctx.get("mode") == "rp_first" and ctx.get("tool_system_content")
        and ctx.get("tool_llm") is not None and ctx.get("tools_dict"))

    def _run_tool_phase() -> str:
        """rp_first tool phase — returns the extracted fallback markers."""
        try:
            from app.core.tool_formats import find_tool_calls
            from app.core.streaming import _extract_markers, _inject_rp_context
            _tool_msgs = [
                {"role": "system", "content": ctx["tool_system_content"]},
                {"role": "user", "content": _rp_tool_decision_input(
                    incoming_message, clean, ctx["tools_dict"],
                    in_person=(ctx.get("medium") == "in_person"),
                    agent_name=responder)},
            ]
            _tresp = get_llm_queue().submit(
                task_type="intent", priority=Priority.CHAT, llm=ctx["tool_llm"],
                messages_or_prompt=_tool_msgs, agent_name=responder,
                label=f"Tool: {speaker} → {responder}")
            _ttext = getattr(_tresp, "content", "") or ""
            _matches = find_tool_calls(ctx.get("tool_format", "tag"), _ttext, ctx["tools_dict"])
            execute_tool_matches(ctx, responder, _matches, rp_text=clean,
                                 incoming_message=incoming_message)
            return _extract_markers(_ttext, clean) or ""
        except Exception as _e:
            logger.warning("run_chat_turn rp_first tool-phase failed: %s", _e)
            return ""

    ts = utc_now_iso()

    # chat_messages ONLY for directed messaging (talk_to/send_message) —
    # there it feeds the agent inbox (load_unread_messages).
    # In ROOM mode the perception stream is the canonical source (shown in
    # /play + scenes); chat_messages would only duplicate the old pairwise
    # history and is part of the cutover
    # (plan-history-consolidation-cleanup.md, phase 3).
    if not ctx.get("room_mode"):
        _stored = [
            save_message({
                "role": "user", "content": incoming_message, "timestamp": ts,
                "speaker": speaker, "medium": medium,
            }, character_name=responder, partner_name=speaker),
            save_message({
                "role": "assistant", "content": clean, "timestamp": ts,
                "speaker": responder, "medium": medium,
            }, character_name=responder, partner_name=speaker),
            save_message({
                "role": "assistant", "content": incoming_message, "timestamp": ts,
                "speaker": speaker, "medium": medium,
            }, character_name=speaker, partner_name=responder),
            save_message({
                "role": "user", "content": clean, "timestamp": ts,
                "speaker": responder, "medium": medium,
            }, character_name=speaker, partner_name=responder),
        ]
        # The answer has already been produced and is returned either way —
        # aborting the turn over a lost history row would throw away work AND
        # the reply. What must not happen is that it passes silently: the
        # reply then lives in this thread's context only and is gone on the
        # next reload (DATA-13).
        if not all(_stored):
            logger.error("run_chat_turn: chat history %s <-> %s NOT stored "
                         "(%d of 4 writes failed) — the turn is not in the DB",
                         speaker, responder, _stored.count(False))

    # Pending-Report Sofort-Trigger: if the speaker owes someone a report
    # back, bump them in the AgentLoop so they think on the next slot.
    # The pending_reports block in their thought context shows the open
    # obligation directly.
    try:
        from app.core.pending_reports import trigger_sofort_thought_if_applicable
        if trigger_sofort_thought_if_applicable(speaker, responder):
            try:
                from app.core.agent_loop import get_agent_loop
                get_agent_loop().bump(speaker)
            except Exception as _be:
                logger.debug("AgentLoop bump failed for %s: %s", speaker, _be)
    except Exception as e:
        logger.debug("pending_report Sofort-Trigger Fehler: %s", e)

    # Tool phase + post-processing in a daemon thread, AFTER the return: the
    # answer is final and goes to the caller immediately (the respond turn
    # records it as an utterance). The order is preserved: first the tool
    # phase (delivers the fallback markers), then the post-processing (memory,
    # relationship, intent, mood/location/activity adoption, expression
    # regeneration, history summary — opt-in, player chat via the loop only).
    # plan-room-conversation-feature-parity §D.
    _needs_inline_tools = bool(_inline_matches)
    if _needs_tool_phase or _needs_inline_tools or post_process:
        try:
            import contextvars
            import threading
            from app.core.turn_trace import bind_trace

            # The tool phase used to run synchronously IN the caller's context
            # — including a possibly active perception_shadow.suppressed()
            # (respond turn). A thread does not copy ContextVars, so the
            # context is captured here and the tool phase runs inside it; the
            # post-processing always ran in the fresh thread context.
            # The turn trace is handed over BY VALUE (bind_trace) instead of
            # widening _caller_ctx over the whole thread: the post-processing
            # must not inherit the suppressed perception shadow, it only needs
            # the trace id so its follow-up LLM calls group with the answer.
            _caller_ctx = contextvars.copy_context()

            def _bg_after_reply():
                _markers = (_caller_ctx.run(_run_tool_phase)
                            if _needs_tool_phase else "")
                if _needs_inline_tools:
                    # Single mode: the fallback markers (**I do …**) sit
                    # in the chat text itself, so they are read from the
                    # raw answer for the post-processing below.
                    _caller_ctx.run(execute_tool_matches, ctx, responder,
                                    _inline_matches, rp_text=clean,
                                    incoming_message=incoming_message)
                    try:
                        from app.core.streaming import _extract_markers
                        _markers = _extract_markers(raw, clean) or ""
                    except Exception as _xe:  # noqa: BLE001
                        logger.debug("marker extraction failed: %s", _xe)
                if not post_process:
                    return
                try:
                    # Partner = the SPEAKER of the trigger utterance, not
                    # ctx["user_display_name"]: that one resolves the active
                    # avatar via get_active_character(), which returns '' in
                    # loop/background threads (avatar selection lives in USER
                    # settings) → sentinel "user" → relationship + memory
                    # attribution silently skipped on every room reply (no
                    # 'chat' interaction was recorded since April).
                    post_process_response(
                        owner_id=owner_id, character_name=responder,
                        user_input=incoming_message,
                        full_response=(clean + ("\n" + _markers if _markers else "")),
                        agent_config=ctx["agent_config"], llm=ctx["llm"],
                        user_display_name=(speaker or ctx["user_display_name"]),
                        full_chat_history=ctx["full_chat_history"],
                        old_history=ctx.get("old_history"),
                        extraction_context={"source": "user_chat"})
                except Exception as _pe:
                    logger.error("run_chat_turn post_process(%s) failed: %s",
                                 responder, _pe)
            threading.Thread(target=bind_trace(_bg_after_reply),
                             daemon=True).start()
        except Exception as _e:
            logger.debug("Follow-up spawn (tool phase / post-processing) failed: %s", _e)

    return clean


def clean_response(full_response: str) -> str:
    """Strip meta-tags from response for saving to history."""
    clean = full_response
    clean = re.sub(r'!\[([^\]]*)\]\(data:image/[^)]+\)', '', clean)
    # Mood-Marker (Zustand, kein Gesprächsinhalt) — sprach-robust: EN „I feel"
    # UND lokalisiert „Ich fühle …" (RP-Modell schreibt deutsch). Sonst leakte
    # „**Ich fühle aggressiv**" in Utterance + History.
    clean = re.sub(r'\n?\s*\*\*\s*(?:I\s+feel|Ich\s+f[üu]hle)\s+[^*]+\*\*\s*', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\n?\s*\*\*I\s+am\s+at\s+[^*]+\*\*\s*', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\n?\s*\*\*I\s+do\s+[^*]+\*\*\s*', '', clean, flags=re.IGNORECASE)
    from app.core.intent_engine import strip_intent_tags
    clean = strip_intent_tags(clean)
    from app.models.assignments import strip_assignment_tags
    clean = strip_assignment_tags(clean)
    # Vereinheitlichte [INTENT:]-Marker (plan-intents-unified.md) — im Room-/
    # C2C-Pfad laeuft die Bereinigung ueber clean_response, nicht ueber
    # _strip_tool_hallucinations; ohne dies leakten Marker in Utterance/History.
    from app.models.intents import strip_intent_markers
    clean = strip_intent_markers(clean)
    # Strip tool hallucinations — and INLINE tool calls of the single chat
    # mode, which run_chat_turn has already read from the raw text: the
    # same two patterns routes/chat._strip_tool_hallucinations uses, so
    # a tag never reaches an utterance or a history whichever path wrote it.
    if "<tool" in clean:
        clean = re.sub(r'<tool\s+name="[^"]*">[\s\S]*?</tool>', '', clean)
        clean = re.sub(r'<tool\s+name="[^"]*">[^<]*', '', clean)
    clean = re.sub(r'<tool_call>.*?</tool_call>', '', clean, flags=re.DOTALL)
    clean = re.sub(r'</?tool_(?:call|result)>', '', clean)
    # LLM-Tokenizer-Artefakte entfernen — JEDES <|...|> (auch lowercase wie
    # <|python_tag|>, <|reserved_special_token_72|>) + <SPECIAL_28>. Frueher nur
    # GROSSBUCHSTABEN-<|...|> → lowercase-Tokens leakten in den Room-Stream und
    # wurden beim naechsten Turn als Kontext zurueckgefuettert (Kaskade).
    clean = re.sub(r'<\|[^|>]{0,60}\|>', '', clean)
    clean = re.sub(r'<SPECIAL_\d+>', '', clean)
    return clean.strip()


def post_process_response(
    owner_id: str,
    character_name: str,
    user_input: str,
    full_response: str,
    agent_config: Dict[str, Any],
    llm: Any,
    user_display_name: str,
    full_chat_history: list,
    history_window: int = 0,
    old_history: list = None,
    extraction_context: Dict[str, Any] = None,
    executed_tools: list = None) -> Dict[str, Any]:
    """
    Run all post-processing after a chat response: mood, location, activity,
    memory extraction, relationship updates, intent extraction.

    Called from the web chat path (in the background).

    Args:
        owner_id: User who owns the character
        character_name: Character name
        user_input: Original user message
        full_response: Complete LLM response (before cleaning)
        agent_config: Character config dict
        llm: LLM instance used for chat
        user_display_name: Display name of the user
        full_chat_history: Full chat history (before this exchange)
        history_window: DEPRECATED — ignored, kept for backward compat
        old_history: Messages older than short-term window (for summary)

    Returns:
        Dict with extracted data: mood, location, activity (may be None)
    """
    from app.routes.chat import _extract_mood, _extract_location, _extract_activity
    from app.routes.chat import _extract_context_from_last_chat

    result = {"mood": None, "location": None, "activity": None}

    cleaned = clean_response(full_response)

    # Mood extraction
    try:
        mood = _extract_mood(character_name, full_response)
        if mood:
            result["mood"] = mood
    except Exception as e:
        logger.error("Mood extraction error: %s", e)

    # Location extraction (Location- oder Raum-Wechsel)
    try:
        loc_change = _extract_location(character_name, full_response)
        if loc_change:
            if loc_change.get("id"):
                # Echter Location-Wechsel — Frontend aktualisiert Hintergrund + Sidebar
                result["location"] = loc_change.get("name")
            elif loc_change.get("room") and loc_change.get("location_id"):
                # Reiner Raum-Wechsel — Location-ID mitsenden fuer Hintergrund-Update
                result["location"] = loc_change["location_id"]
            if loc_change.get("room"):
                result["room"] = loc_change["room"]
    except Exception as e:
        logger.error("Location extraction error: %s", e)

    # Activity extraction
    try:
        act_change = _extract_activity(character_name, full_response)
        if act_change:
            result["activity"] = act_change
    except Exception as e:
        logger.error("Activity extraction error: %s", e)

    # Intent-Marker (Vorhaben & Aufgaben): [INTENT:…] (neu) / [INTENT_DONE:…] /
    # [INTENT_PROGRESS:…]. Ersetzt die alten Assignment-Marker UND den toten
    # intent_engine-Pfad — eine vereinheitlichte Quelle (plan-intents-unified.md).
    try:
        from app.models.character_template import feature_disabled as _off
        if not _off(character_name, "intents_enabled"):
            from app.models.intents import parse_and_apply_intent_markers
            _ni = parse_and_apply_intent_markers(character_name, full_response)
            if _ni:
                result["intent_markers"] = _ni
    except Exception as e:
        logger.error("Intent marker extraction error: %s", e)

    # Background extraction: memory + categories + relationships
    # Nur bei substantiellen Antworten (kurze/leere Antworten ueberspringen)
    if len(cleaned) < 20:
        logger.debug("[%s] Antwort zu kurz (%d Zeichen) — Background-Extraktion uebersprungen",
                      character_name, len(cleaned))
        return result

    # Im Thought-Modus ist user_input synthetisch — fuer Memory-Extraction
    # leeren, damit die Template-Zeile "Player (User): ..." nicht mit einer
    # System-Instruktion gefuellt wird (sonst extrahiert der LLM Bogus-
    # Memories ueber den vermeintlichen User-Befehl).
    _is_thought = bool(extraction_context and extraction_context.get("source") == "thought")
    _mem_user_input = "" if _is_thought else user_input

    # Partner-Name fuer Extraction: nie generische Sentinel ("user"/"Player")
    # weiterreichen — die Extraction skippt dann sauber statt sie als Adressat
    # in Memory-Texten zu materialisieren.
    _extract_partner = (user_display_name or "").strip()
    if _extract_partner.lower() in {"user", "player", "spieler"}:
        _extract_partner = ""

    def _background_extraction():
        # Memory extraction — NUR aus Gedanken (thought). Gespräch-Memories
        # kommen ausschließlich aus der Szenen-Konsolidierung (consolidate_scene
        # legt pro Szene ein Episodic-Memory je Teilnehmer an). Die alte
        # Per-Turn-Extraktion war redundant zu den Szenen UND die Müll-Quelle
        # (z.B. „X will use Y to steal…") — sie ist für Gespräche raus.
        # (plan-history-consolidation-cleanup.md, Phase 2)
        from app.models.character_template import feature_disabled as _off
        # Feature gates. They sit BEFORE the LLM calls, not just before the
        # writes: a character that remembers nothing must not pay for an
        # extraction turn, and one without relationships must not pay for the
        # sentiment turn. `feature_disabled`, not `is_feature_enabled` — a
        # profile without a template must keep working, not fall silent.
        if _is_thought and not _off(character_name, "memory_enabled"):
            try:
                from app.core.memory_service import extract_memories_from_exchange, apply_extracted_memories
                extracted = extract_memories_from_exchange(
                    character_name, _extract_partner, _mem_user_input, cleaned, llm
                )
                if extracted:
                    count = apply_extracted_memories(character_name, extracted,
                                                     extraction_context=extraction_context)
                    logger.debug("[%s] Memory extraction (thought): %d new", character_name, count)
            except Exception as e:
                logger.error("[%s] Memory extraction error: %s", character_name, e)

        # Relationship update — im Thought-Modus skippen, da Gedanken keine
        # Interaktion mit dem User sind (sonst falsche Closeness-Increments
        # und ein zweiter LLM-Call mit synthetischem User-Input).
        if _is_thought:
            return
        if _off(character_name, "relationships_enabled"):
            return
        # Relationship-Update braucht echte Charakternamen — Sentinel
        # ("user"/"Player") sind keine validen Speaker-Namen.
        if not _extract_partner:
            logger.debug("[%s] relationship update skipped: no partner",
                          character_name)
        else:
            try:
                from app.models.relationship import record_interaction, get_romantic_interests

                _speaker_a = _extract_partner
                _speaker_b = character_name

                summary = f"{_speaker_a}: {user_input[:100]}"
                if cleaned:
                    summary += f" — {_speaker_b}: {cleaned[:80]}"

                analysis = {"sentiment_a": 0.05, "sentiment_b": 0.05, "romantic_delta": 0.0}
                try:
                    ri_a = get_romantic_interests(_speaker_a)
                    ri_b = get_romantic_interests(_speaker_b)
                    romantic_context = ""
                    if ri_a or ri_b:
                        romantic_context = "\nRomantic interest context:\n"
                        if ri_a:
                            romantic_context += f"- {_speaker_a}'s romantic interests: {ri_a}\n"
                        if ri_b:
                            romantic_context += f"- {_speaker_b}'s romantic interests: {ri_b}\n"
                        romantic_context += "Only set romantic_delta > 0 if the conversation matches these interests."

                    from app.core.llm_router import llm_call as _llm_call
                    from app.core.prompt_templates import render_task
                    rel_system_prompt, conversation_text = render_task(
                        "relationship_summary",
                        speaker_a=_speaker_a,
                        speaker_b=_speaker_b,
                        text_a=user_input[:300],
                        text_b=cleaned[:300] if cleaned else "",
                        romantic_context=romantic_context)
                    try:
                        resp = _llm_call(
                            task="relationship_summary",
                            system_prompt=rel_system_prompt,
                            user_prompt=conversation_text,
                            agent_name=character_name)
                        raw = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', resp.content).strip()
                    except RuntimeError:
                        raw = ""
                    match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
                    if match:
                        data = json.loads(match.group(0))
                        analysis = {
                            "sentiment_a": max(-0.3, min(0.3, float(data.get("sentiment_a", 0.05)))),
                            "sentiment_b": max(-0.3, min(0.3, float(data.get("sentiment_b", 0.05)))),
                            "romantic_delta": max(-0.1, min(0.15, float(data.get("romantic_delta", 0.0)))),
                        }
                except Exception as rel_err:
                    logger.debug("[%s] Relationship analysis failed (defaults): %s", character_name, rel_err)

                # Old type BEFORE the update — a TYPE change (neutral →
                # acquaintance → friend/romantic) is surfaced as a
                # display-only narrator line in the scene view.
                _old_type = ""
                try:
                    from app.models.relationship import get_relationship
                    _old_type = (get_relationship(_speaker_a, _speaker_b)
                                 or {}).get("type") or ""
                except Exception:
                    pass
                _rel_after = record_interaction(
                    char_a=_speaker_a,
                    char_b=_speaker_b,
                    interaction_type="chat",
                    summary=summary,
                    strength_delta=2,
                    sentiment_delta_a=analysis.get("sentiment_a", 0.05),
                    sentiment_delta_b=analysis.get("sentiment_b", 0.05),
                    romantic_delta=analysis.get("romantic_delta", 0.0))
                _new_type = (_rel_after or {}).get("type") or ""
                if _new_type and _new_type != _old_type:
                    # Display-only line (meta.display_only): rendered by the
                    # player scene view, filtered from all LLM transcripts
                    # (perception_store default).
                    try:
                        from app.core.perception import (record_utterance,
                                                         VOLUME_NORMAL)
                        from app.models.character import (
                            get_character_current_location,
                            get_character_current_room)
                        _r_loc = get_character_current_location(character_name) or ""
                        _r_room = get_character_current_room(character_name) or ""
                        _txt = (f"💞 {_speaker_a} ⇄ {_speaker_b}: "
                                + (f"{_old_type} → {_new_type}"
                                   if _old_type else _new_type))
                        # No location gate: an empty location is the
                        # WILDERNESS, not a missing value (E6). The anchor
                        # gives the storyteller the character's point, so out
                        # there the line reaches the same people the character's
                        # own words would.
                        record_utterance(
                            speaker=STORYTELLER_SPEAKER, content=_txt,
                            volume=VOLUME_NORMAL, location_id=_r_loc,
                            room_id=_r_room, source="relationship",
                            anchor=character_name,
                            perception_meta={"display_only": True,
                                             "relationship": True})
                    except Exception as _re:
                        logger.debug("relationship display line failed: %s", _re)
            except Exception as rel_err:
                logger.error("[%s] Relationship update error: %s", character_name, rel_err)

    # Run background extraction in thread pool. bind_trace carries the turn's
    # trace id into the pool thread (run_in_executor does not propagate the
    # context, and a pooled thread would otherwise keep whatever a previous
    # job left there) — this is where relationship_summary is called.
    from app.core.turn_trace import bind_trace
    try:
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, bind_trace(_background_extraction))
    except RuntimeError:
        # No event loop — run synchronously
        _background_extraction()

    # (Old intent_engine path removed — intents now run through the unified
    # [INTENT:] markers above, plan-intents-unified.md. That also removes the
    # A4 event-loop bug of this dead path.)

    # Instagram interaction extraction
    try:
        from app.models.instagram import extract_instagram_interactions, apply_interactions_to_latest_post
        from app.models.assignments import strip_assignment_tags
        cleaned_for_instagram = strip_assignment_tags(full_response)
        interactions = extract_instagram_interactions(cleaned_for_instagram)
        if interactions:
            apply_interactions_to_latest_post(character_name, interactions)
    except Exception as e:
        logger.error("[%s] Instagram extraction error: %s", character_name, e)

    # Chat context extraction (activity + outfit from response).
    # Im Thought-Modus ist user_input eine synthetische System-Instruktion
    # ("Think about your task…") und stammt NICHT vom Avatar — daher
    # wird sie aus updated_history weggelassen, damit die Avatar-Outfit-
    # Extraktion nicht mit Unsinn gefuettert wird. Agent-Side-Extraction aus
    # dem Thought-Response bleibt aktiv.
    try:
        is_thought = bool(extraction_context and extraction_context.get("source") == "thought")
        updated_history = list(full_chat_history)
        if not is_thought:
            updated_history.append({"role": "user", "content": user_input})
        updated_history.append({"role": "assistant", "content": full_response})
        _extract_context_from_last_chat(character_name, updated_history, agent_config)
    except Exception as e:
        logger.error("[%s] Context extraction error: %s", character_name, e)

    # History summary update (only if there are old messages)
    try:
        from app.utils.history_manager import update_summary_background
        # old_history comes from the time-based window; fallback for old callers
        old_messages = old_history
        if old_messages is None and history_window and len(full_chat_history) > history_window:
            old_messages = full_chat_history[:-history_window]
        if old_messages:
            try:
                loop = asyncio.get_event_loop()
                loop.run_in_executor(
                    None, bind_trace(update_summary_background),
                    character_name, old_messages, _extract_partner
                )
            except RuntimeError:
                # No event loop (daemon/worker thread) — run synchronously
                update_summary_background(character_name, old_messages,
                                          _extract_partner)
    except Exception as e:
        logger.error("[%s] History summary error: %s", character_name, e)

    return result
