"""Temporary NPCs — generate / validate / repair / apply, plus the TTL sweep.

A temporary NPC is an ordinary character with the ``npc-temporary`` template.
Everything that makes it "temporary" is template content, not code:

* the ``temporary_npc`` feature flag marks the kind (fails CLOSED, see
  ``character_template.template_feature``) — a SECOND kind of NPC is another
  template JSON with the same flag, not another code path here;
* every expensive subsystem (memory, relationships, thoughts, intents, moods,
  random events, wardrobe) is switched off in that template's ``features``, and
  the gates that read them live at the central write/call points, so nothing in
  the core has to know what an NPC is;
* the NPC's one standing task and its one free-text outfit are template FIELDS,
  which is why the chat prompt and the image prompt pick them up without a line
  of code here.

The generation pipeline reuses the World-Dev machinery unchanged: the same
schema-markdown loader, the same ```json:<type>``` fence extractor, the same
``_apply_character_internal``. What this module adds is the sequencing —
generate → validate → repair → apply — with no human in the loop.
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

logger = get_logger("npc_ops")

#: The template that defines a temporary NPC. Fixed here, never chosen by the
#: LLM — the schema tells the model not to emit a `template` field at all.
NPC_TEMPLATE = "npc-temporary"

#: Schema markdown under shared/world_dev_schemas/.
NPC_SCHEMA = "npc_character"

#: The fence marker the generator must produce.
NPC_FENCE = "npc"

#: Cap for the repair turn's gap list — the validator is told to stay under 30.
MAX_GAP_LINES = 30


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def npc_template_name(template: str = "") -> str:
    """Resolve a requested NPC template to a usable one.

    A location slot may name its OWN template (plan-npc-auto-spawn.md § 1) —
    that is how a second NPC kind stays a JSON file instead of a code path.
    The only condition is that the template actually marks its characters as
    temporary NPCs; anything else would put a full character with memories,
    relationships and thoughts on a disposable slot, so it falls back to the
    canonical one and says so.
    """
    from app.models.character_template import get_template

    wanted = (template or "").strip()
    if not wanted or wanted == NPC_TEMPLATE:
        return NPC_TEMPLATE
    tmpl = get_template(wanted)
    if tmpl and (tmpl.get("features") or {}).get("temporary_npc") is True:
        return wanted
    logger.warning("NPC template %r is not a temporary-NPC template — using %s",
                   wanted, NPC_TEMPLATE)
    return NPC_TEMPLATE


def npc_generable_fields(template: str = "") -> str:
    """Markdown field list for the schema's ``{generable_fields}`` slot.

    Derived from the NPC template, so adding a field to the template JSON adds
    it to the generation prompt — no code change, which is the point of making
    a second NPC kind a template variant.
    """
    from app.models.character_template import get_template

    tmpl = get_template(npc_template_name(template)) or {}
    lines: List[str] = []
    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            if not field.get("llm_generable"):
                continue
            key = field.get("key", "")
            if not key:
                continue
            label = field.get("label", key)
            ftype = field.get("type", "text")
            if ftype == "select" and field.get("options"):
                type_info = "one of: " + " | ".join(
                    str(o.get("value")) for o in field["options"])
            elif ftype == "number":
                type_info = "number"
            else:
                type_info = "text"
            required = " (REQUIRED)" if field.get("required") else ""
            store = " [config]" if field.get("store") == "config" else ""
            hint = (field.get("hint") or "").strip()
            lines.append(f"- `{key}` — {label}{required}{store}: {type_info}."
                         + (f" {hint}" if hint else ""))
    if not lines:
        # A template without generable fields cannot produce an NPC; say so
        # loudly in the prompt rather than sending an empty section.
        return "(no generable fields — the NPC template is broken)"
    return "\n".join(lines)


#: `render_task` renders FIRST and splits on `## system` / `## user` AFTERWARDS,
#: so a markdown heading of exactly that name inside the INJECTED schema tears
#: the prompt in half — the real user turn would replace the schema's tail and
#: everything before the stray heading would be dropped. The schema is a file an
#: author edits, so the guard belongs at the injection point, not in the file's
#: review checklist.
_MARKER_RE = re.compile(r"^(##\s+)(system|user)(\s*)$",
                        re.IGNORECASE | re.MULTILINE)


def sanitize_injected_markdown(text: str) -> str:
    """Demote `## system` / `## user` headings so they cannot split a prompt."""
    return _MARKER_RE.sub(r"#\1\2\3", text or "")


def _location_labels(location_id: str, room_id: str = "") -> Tuple[str, str]:
    """Human names for the schema header. Unknown ids fall back to the id."""
    from app.models.world import get_location_by_id
    loc = get_location_by_id(location_id) or {}
    loc_name = loc.get("name") or location_id or "(unspecified)"
    room_name = ""
    for room in loc.get("rooms") or []:
        if (room.get("id") or "") == room_id:
            room_name = room.get("name") or ""
            break
    return loc_name, (room_name or room_id or "(any room)")


def build_npc_schema_text(location_id: str, room_id: str = "",
                          template: str = "") -> str:
    """The NPC schema markdown with every placeholder filled."""
    from app.models.character import list_available_characters
    from app.models.world_setup import get_world_setup_text
    from app.routes.world_dev import _load_schema

    setup = (get_world_setup_text() or "").strip()
    setup_block = f"## World setup\n\n{setup}\n\n" if setup else ""
    # Pooled NPCs count as existing names here: their profile is still there
    # and a generated twin would collide with it on apply.
    existing = ", ".join(list_available_characters(include_pooled=True)) or "(none yet)"
    loc_name, room_name = _location_labels(location_id, room_id)

    return sanitize_injected_markdown(_load_schema(
        NPC_SCHEMA,
        world_setup_block=setup_block,
        generable_fields=npc_generable_fields(template),
        existing_characters=existing,
        location_name=loc_name,
        room_name=room_name,
    ))


# ---------------------------------------------------------------------------
# Local validation (no LLM) — the cheap half of the validate stage
# ---------------------------------------------------------------------------

def validate_npc_fields(data: Dict[str, Any], template: str = "") -> List[str]:
    """Missing/empty required fields, as `key — reason` lines.

    Required = the template's own ``required`` flags plus the name. Unlike the
    world-dev character check this does NOT demand outfits: a temporary NPC has
    none by design, its wardrobe is the ``outfit_description`` prompt text.
    """
    from app.models.character_template import get_template

    gaps: List[str] = []
    name = str(data.get("character_name") or "").strip()
    if not name:
        gaps.append("character_name — missing, every NPC needs an in-world name")

    tmpl = get_template(npc_template_name(template)) or {}
    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            key = field.get("key", "")
            if not key or key == "character_name":
                continue
            if not field.get("llm_generable") or not field.get("required"):
                continue
            if not str(data.get(key) or "").strip():
                label = field.get("label", key)
                gaps.append(f"{key} — missing, {label} is required")

    # Things the schema explicitly forbids: they cost tokens downstream and
    # would drag the NPC back into the systems it is supposed to stay out of.
    if data.get("outfits"):
        gaps.append("outfits — must not be set, a temporary NPC has no wardrobe "
                    "pieces; put the clothing into outfit_description instead")
    for soul_key in ("character_soul", "character_beliefs", "character_lessons",
                     "character_goals", "character_presence", "character_task",
                     "roleplay_instructions"):
        if data.get(soul_key):
            gaps.append(f"{soul_key} — must not be set, a temporary NPC has no "
                        "soul documents")
    personality = str(data.get("character_personality") or "")
    if personality.lstrip().startswith("#"):
        gaps.append("character_personality — must be plain prose, not a markdown "
                    "document with headings")
    return gaps


def name_is_taken(name: str) -> bool:
    """True when a character of that name already exists (case-insensitive).

    Pooled NPCs count: their profile, their storage directory and their row
    are all still there, so the name is not free even though nobody in the
    world carries it right now.
    """
    from app.models.character import list_available_characters
    wanted = (name or "").strip().lower()
    if not wanted:
        return True
    return any(wanted == (c or "").strip().lower()
               for c in list_available_characters(include_pooled=True))


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def expiry_stamp(ttl_hours: Optional[float]) -> str:
    """Canonical GAME stamp ``ttl_hours`` of game time from now, or "".

    Empty means "no TTL" — the NPC lives until an admin deletes it. Game time,
    not system time: a frozen world must freeze the NPC's lifetime with it.
    """
    try:
        hours = float(ttl_hours) if ttl_hours is not None else 0.0
    except (TypeError, ValueError):
        return ""
    if hours <= 0:
        return ""
    return (game_time() + GameDuration.of(hours=hours)).canonical()


def apply_npc(data: Dict[str, Any], location_id: str, room_id: str = "",
              briefing: str = "", ttl_hours: Optional[float] = None,
              created_by: str = "", template: str = "",
              slot_role: str = "", wanderer: bool = False,
              wander_target: str = "") -> Dict[str, Any]:
    """Create the character, then stamp the NPC-only bookkeeping onto it.

    The heavy lifting is ``_apply_character_internal`` — the very same call the
    World-Dev apply uses, with the template pinned. Everything after it is the
    handful of fields the LLM must NOT write: where the NPC stands, what it was
    generated from, and when it dies.
    """
    from app.models.character import (get_character_profile,
                                      save_character_current_location,
                                      save_character_current_room,
                                      save_character_profile)
    from app.routes.world_dev import _apply_character_internal

    tmpl_name = npc_template_name(template)
    payload = dict(data)
    payload.pop("outfits", None)          # never a wardrobe (see validate)
    payload["template"] = tmpl_name       # fixed, never LLM-chosen
    name = str(payload.get("character_name") or "").strip()
    if not name:
        raise ValueError("character_name missing")

    result = _apply_character_internal(payload, selected_template=tmpl_name,
                                       created_by=created_by or "npc_generator")

    # Bookkeeping the generator is not allowed to set.
    profile = get_character_profile(name) or {}
    profile["npc_briefing"] = (briefing or "").strip()
    profile["expires_at"] = expiry_stamp(ttl_hours)
    profile["outfit_worn"] = True
    # THE SLOT TAG. What makes an NPC count towards a location's slot is this
    # pair on its profile — never its name, never its role text in prose
    # (feedback_no_name_resolution). An NPC without a slot (manual, wanderer)
    # simply carries empty ones.
    profile["npc_slot_role"] = (slot_role or "").strip()
    profile["npc_slot_location"] = (location_id or "").strip() if slot_role else ""
    profile["npc_wanderer"] = bool(wanderer)
    # THE ROAD IS STAMPED BEFORE THE PLACEMENT. The finish gate may hold this
    # NPC back, and the job it queues is what sends the wanderer off later —
    # so where it is going has to be on the profile (and in that payload)
    # before anybody asks for a placement, not one line afterwards.
    if wanderer and wander_target:
        profile["wander_origin"] = location_id
        profile["wander_target"] = wander_target
    # The standing task IS the activity baseline — one field, two consumers:
    # the chat prompt renders it (in_prompt), the world shows it as what the
    # NPC is doing.
    task = str(profile.get("standing_task") or "").strip()
    if task:
        profile["current_activity"] = task
    save_character_profile(name, profile)

    # THE FINISH GATE (plan-npc-leben § 0 A). An NPC with no portrait, no mesh
    # and no outfit text is not put on the map at all: it stays pooled and one
    # `npc_assets` job renders what is missing and places it afterwards. The
    # character SHEET is written either way — the gate decides where the NPC
    # stands, not whether it exists.
    from app.core.npc_assets import gate_placement
    held = gate_placement(name, location_id, room_id, wanderer=wanderer,
                          wander_target=wander_target)

    # Placement, not movement: the NPC is CREATED standing there. This is the
    # same structured setter the admin placement uses (it syncs the metre
    # position), never a narrative "walks in".
    if location_id and not held:
        try:
            save_character_current_location(name, location_id)
            if room_id:
                save_character_current_room(name, room_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("NPC %s could not be placed at %s: %s",
                           name, location_id, e)

    result["expires_at"] = profile["expires_at"]
    result["held_for_assets"] = held
    result["location_id"] = location_id
    result["room_id"] = room_id
    logger.info("Temporary NPC '%s' created at %s (expires %s)%s",
                name, location_id or "(nowhere)",
                profile["expires_at"] or "never",
                " — held back until its assets exist" if held else "")
    return result


# ---------------------------------------------------------------------------
# Listing + sweep
# ---------------------------------------------------------------------------

def npc_summary(name: str) -> Dict[str, Any]:
    """One row for the Game-Admin NPC list."""
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_profile)
    from app.models.world import get_location_name

    profile = get_character_profile(name) or {}
    expires_at = str(profile.get("expires_at") or "")
    location_id = get_character_current_location(name) or ""
    return {
        "name": name,
        "template": profile.get("template") or NPC_TEMPLATE,
        "standing_task": profile.get("standing_task") or "",
        "dialogue_style": profile.get("dialogue_style") or "",
        "arrival_reason": profile.get("arrival_reason") or "",
        "goals": profile.get("npc_goals") or "",
        "briefing": profile.get("npc_briefing") or "",
        "outfit_description": profile.get("outfit_description") or "",
        "slot_role": profile.get("npc_slot_role") or "",
        "slot_location": profile.get("npc_slot_location") or "",
        "wanderer": bool(profile.get("npc_wanderer")),
        "location_id": location_id,
        "location_name": get_location_name(location_id) if location_id else "",
        "room_id": get_character_current_room(name) or "",
        "expires_at": expires_at,
        "expires_label": (GameTime.parse(expires_at).label()
                          if _is_stamp(expires_at) else ""),
        "expired": is_expired(expires_at),
    }


def _is_stamp(value: str) -> bool:
    try:
        GameTime.parse(value)
        return True
    except (ValueError, TypeError):
        return False


def is_expired(expires_at: str) -> bool:
    """True when the stamp is set AND the game clock has passed it."""
    if not _is_stamp(expires_at):
        return False
    return game_time() >= GameTime.parse(expires_at)


def list_npcs() -> List[Dict[str, Any]]:
    from app.models.character import list_temporary_npcs
    return [npc_summary(n) for n in list_temporary_npcs()]


def sweep_expired_npcs() -> int:
    """POOL every temporary NPC whose game-time TTL has run out.

    Since plan-npc-auto-spawn.md § 3 the sweep no longer deletes: the profile
    is kept and the row is marked pooled, so the next spawn of that role can
    re-use a finished character sheet instead of paying for three LLM turns.
    What the other characters remembered about the NPC still goes — pooling
    changes the NPC's fate, not the memory decision (§ 10.4 of the temp-NPC
    plan). An NPC without ``expires_at`` is never swept; it lives until an
    admin deletes it.
    """
    from app.core.npc_pool import pool_npc
    from app.models.character import get_character_profile, list_temporary_npcs

    removed = 0
    for name in list_temporary_npcs():
        try:
            profile = get_character_profile(name) or {}
            if not is_expired(str(profile.get("expires_at") or "")):
                continue
            if pool_npc(name, reason="ttl"):
                removed += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("npc sweep(%s) error: %s", name, e)
    return removed


# ---------------------------------------------------------------------------
# The blocking pipeline — the one the automatic spawns use
# ---------------------------------------------------------------------------

#: The routed LLM task of an automatic NPC generation. The manual dialog picks
#: a model by hand (there is a human at the browser); an automatic spawn has
#: nobody to ask, so it goes through the ordinary routing table like every
#: other background LLM job (/admin/settings → LLM Routing).
NPC_TASK = "npc_generate"

#: Completion cap for one generation turn. An NPC sheet is a small flat JSON
#: object; a model that runs past this is looping, not writing.
NPC_MAX_TOKENS = 2500


def generate_npc_blocking(briefing: str, location_id: str, room_id: str = "",
                          ttl_hours: Optional[float] = None,
                          template: str = "", slot_role: str = "",
                          wanderer: bool = False, wander_target: str = "",
                          created_by: str = "npc_auto") -> Dict[str, Any]:
    """generate → validate → repair → apply, synchronously. For queue workers.

    Same four stages and the same helpers as the SSE pipeline, with two
    deliberate differences, both of which come from there being no human at
    the other end:

    * the LLM goes through ``llm_call`` (routing table + provider queue)
      instead of a model picked in a dialog — an automatic spawn cannot ask
      anyone which model to use;
    * the LLM VALIDATOR stage is skipped. Its value is a second opinion for a
      person watching the stream; here it would double the cost of every
      spawn, and the local field check is what the apply stage enforces
      anyway. So: one generate turn, and one repair turn only when the local
      check found gaps.

    Returns ``{"ok": bool, "character": str, "error": str, "gaps": [...],
    "held_for_assets": bool}`` — the last one says the NPC was created but is
    NOT in the world yet (the finish gate, see ``npc_assets``).
    """
    import json as _json

    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task
    from app.routes.world_dev import _extract_json_block

    if not briefing.strip():
        return {"ok": False, "error": "briefing required"}

    tmpl = npc_template_name(template)
    schema_text = build_npc_schema_text(location_id, room_id, tmpl)

    def _turn(task_template: str, **vars_: Any) -> Optional[Dict[str, Any]]:
        system_prompt, user_prompt = render_task(task_template, **vars_)
        response = llm_call(NPC_TASK, system_prompt, user_prompt,
                            agent_name="NpcGenerator",
                            label=f"NPC spawn ({slot_role or 'wanderer'})",
                            max_tokens=NPC_MAX_TOKENS)
        return _extract_json_block(getattr(response, "content", "") or "",
                                   NPC_FENCE)

    try:
        data = _turn("npc_generate", schema_text=schema_text,
                     briefing=briefing.strip())
    except Exception as e:  # noqa: BLE001
        logger.warning("NPC auto-generate failed: %s", e)
        return {"ok": False, "error": str(e)}
    if not data:
        return {"ok": False, "error": "no ```json:npc block in the answer"}

    gaps = validate_npc_fields(data, tmpl)
    name = str(data.get("character_name") or "").strip()
    if name and name_is_taken(name):
        gaps.append(f"character_name — '{name}' already exists in this world, "
                    "pick a different in-world name")
    if gaps:
        try:
            repaired = _turn("npc_repair", schema_text=schema_text,
                             draft_json=_json.dumps(data, ensure_ascii=False,
                                                    indent=2),
                             gaps="\n".join(f"- {g}" for g in gaps[:MAX_GAP_LINES]))
            if repaired:
                data = repaired
        except Exception as e:  # noqa: BLE001
            logger.warning("NPC auto-repair failed, keeping the draft: %s", e)

    blocking = validate_npc_fields(data, tmpl)
    if blocking:
        return {"ok": False, "error": "still incomplete after repair",
                "gaps": blocking}
    name = str(data.get("character_name") or "").strip()
    if name_is_taken(name):
        return {"ok": False, "error": f"a character named '{name}' already exists"}
    try:
        applied = apply_npc(data, location_id, room_id, briefing, ttl_hours,
                            created_by, template=tmpl, slot_role=slot_role,
                            wanderer=wanderer, wander_target=wander_target)
    except Exception as e:  # noqa: BLE001
        logger.error("NPC auto-apply failed: %s", e)
        return {"ok": False, "error": f"apply failed: {e}"}
    return {"ok": True, "character": applied.get("character") or name,
            "expires_at": applied.get("expires_at", ""),
            "held_for_assets": bool(applied.get("held_for_assets"))}


# ---------------------------------------------------------------------------
# The three-stage pipeline
# ---------------------------------------------------------------------------

def _make_llm(model: str, provider: str, max_tokens: Optional[int]):
    """One LLM handle for one stage. Same routing as the World-Dev chat."""
    from app.core.llm_router import create_llm_instance
    instance = create_llm_instance(task="chat", model=model,
                                   provider_name=provider,
                                   max_tokens=max_tokens)
    if not instance:
        return None, None
    llm = instance.create_llm() if hasattr(instance, "create_llm") else instance
    return llm, instance


async def _collect(llm, system_prompt: str, user_prompt: str,
                   max_lines: int = 400) -> str:
    """Stream one completion into a string, with a runaway guard.

    Same guard as the world-dev validator: a looping model repeats one line
    forever, which would otherwise hold the SSE stream open indefinitely.
    """
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    full = ""
    async for chunk in llm.astream(messages):
        content = getattr(chunk, "content", None)
        if not content:
            continue
        full += content
        if full.count("\n") > max_lines:
            logger.info("npc pipeline: cancelling stream — output too long")
            break
    return full


async def generate_npc(briefing: str, location_id: str, room_id: str = "",
                       ttl_hours: Optional[float] = None,
                       model: str = "", provider: str = "",
                       validator_model: str = "", validator_provider: str = "",
                       max_tokens: Optional[int] = None,
                       created_by: str = "") -> AsyncGenerator[Dict[str, Any], None]:
    """Run generate → validate → repair → apply, yielding one dict per step.

    Yielded frames (the route turns each into one SSE ``data:`` line):
      ``{"stage": "generate"|"validate"|"repair"|"apply", "status": ...}``
      plus stage-specific keys (``gaps``, ``character_data``, ``applied``).
    A frame with ``"error"`` ends the run.
    """
    from app.core.prompt_templates import render_task
    from app.routes.world_dev import _extract_json_block

    if not briefing.strip():
        yield {"stage": "generate", "error": "briefing required"}
        return
    if not model:
        yield {"stage": "generate", "error": "model required"}
        return

    schema_text = build_npc_schema_text(location_id, room_id)

    # --- 1) generate -------------------------------------------------------
    yield {"stage": "generate", "status": "running"}
    llm, instance = _make_llm(model, provider, max_tokens)
    if not llm:
        yield {"stage": "generate",
               "error": f"no LLM for {provider or '?'}/{model}"}
        return
    # Queue bookkeeping happens HERE and not in the route, because this is
    # where the provider instance exists: registering without it would pause
    # whichever channel happens to come first instead of the one this run
    # actually occupies.
    # Bookkeeping only, so a failure here must not abort the run: a world with
    # no provider channel configured raises out of the registration, and the
    # honest error for that is whatever the LLM call itself reports, not an
    # opaque "No channel available for chat registration".
    from app.core.llm_queue import get_llm_queue
    queue = get_llm_queue()
    task_id = ""
    try:
        task_id = await queue.register_chat_active_async(
            "NpcGenerator", llm_instance=instance, task_type="npc_generate",
            label="Temporary NPC")
    except Exception as e:  # noqa: BLE001
        logger.warning("NPC run not registered with the LLM queue: %s", e)
    try:
        async for frame in _run_pipeline(
                llm, schema_text, briefing, location_id, room_id, ttl_hours,
                validator_model or model, validator_provider or provider,
                created_by, render_task, _extract_json_block):
            yield frame
    finally:
        if task_id:
            queue.register_chat_done(task_id)


async def _run_pipeline(llm, schema_text, briefing, location_id, room_id,
                        ttl_hours, v_model, v_provider, created_by,
                        render_task, _extract_json_block
                        ) -> AsyncGenerator[Dict[str, Any], None]:
    """The four stages themselves — split out so the queue registration in
    ``generate_npc`` gets a single try/finally around all of them."""
    system_prompt, user_prompt = render_task(
        "npc_generate", schema_text=schema_text, briefing=briefing.strip())
    try:
        raw = await _collect(llm, system_prompt, user_prompt)
    except Exception as e:  # noqa: BLE001
        yield {"stage": "generate", "error": f"LLM error: {e}"}
        return
    data = _extract_json_block(raw, NPC_FENCE)
    if not data:
        yield {"stage": "generate",
               "error": "no ```json:npc block in the answer"}
        return
    yield {"stage": "generate", "status": "done", "character_data": data}

    # --- 2) validate -------------------------------------------------------
    # Local field check first (free), then the LLM validator against the very
    # schema the generator saw. Both feed ONE gap list into the repair turn.
    yield {"stage": "validate", "status": "running"}
    gaps = validate_npc_fields(data)
    name = str(data.get("character_name") or "").strip()
    if name and name_is_taken(name):
        gaps.append(f"character_name — '{name}' already exists in this world, "
                    "pick a different in-world name")
    if v_model:
        v_llm, _ = _make_llm(v_model, v_provider, 1024)
        if v_llm:
            try:
                v_system, v_user = render_task(
                    "world_dev_validate", schema_text=schema_text,
                    draft_json=json.dumps(data, ensure_ascii=False, indent=2))
                verdict = await _collect(v_llm, v_system, v_user, max_lines=80)
                for line in verdict.splitlines():
                    line = line.strip()
                    if not line or line.upper() == "OK" or not line.startswith("-"):
                        continue
                    if line not in gaps:
                        gaps.append(line.lstrip("- ").strip())
            except Exception as e:  # noqa: BLE001
                logger.warning("NPC validator failed, continuing: %s", e)
    gaps = gaps[:MAX_GAP_LINES]
    yield {"stage": "validate", "status": "done", "gaps": gaps}

    # --- 3) repair ---------------------------------------------------------
    if gaps:
        yield {"stage": "repair", "status": "running"}
        r_system, r_user = render_task(
            "npc_repair", schema_text=schema_text,
            draft_json=json.dumps(data, ensure_ascii=False, indent=2),
            gaps="\n".join(f"- {g}" for g in gaps))
        try:
            raw2 = await _collect(llm, r_system, r_user)
            repaired = _extract_json_block(raw2, NPC_FENCE)
        except Exception as e:  # noqa: BLE001
            logger.warning("NPC repair turn failed, keeping the draft: %s", e)
            repaired = None
        if repaired:
            data = repaired
            yield {"stage": "repair", "status": "done", "character_data": data}
        else:
            # A failed repair is not fatal — the draft may still be usable.
            yield {"stage": "repair", "status": "skipped"}
    else:
        yield {"stage": "repair", "status": "skipped"}

    # --- 4) apply ----------------------------------------------------------
    yield {"stage": "apply", "status": "running"}
    blocking = validate_npc_fields(data)
    if blocking:
        yield {"stage": "apply", "error": "still incomplete after repair",
               "gaps": blocking}
        return
    name = str(data.get("character_name") or "").strip()
    if name_is_taken(name):
        yield {"stage": "apply",
               "error": f"a character named '{name}' already exists"}
        return
    try:
        import asyncio
        applied = await asyncio.to_thread(
            apply_npc, data, location_id, room_id, briefing, ttl_hours,
            created_by)
    except Exception as e:  # noqa: BLE001
        logger.error("NPC apply failed: %s", e)
        yield {"stage": "apply", "error": f"apply failed: {e}"}
        return
    yield {"stage": "apply", "status": "done", "applied": applied}
