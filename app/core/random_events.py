"""Random event generator: create automatic events at locations.

Called hourly from ThoughtLoop (every 60 ticks at a 60-second interval,
once per hour per user). LLM-generated events are stored through
app/models/events.py and injected into the system prompt.

Configuration:
    EVENT_GENERATION_ENABLED=true (default: true)
    EVENT_BASE_PROBABILITY=0.10 (default: 10% per hour per location)

Per-location event_settings in world.json:
    event_probability: probability per hourly check (0.0–1.0)
    allowed_categories: allowed category list
    event_blacklist: forbidden event terms
    max_concurrent_events: maximum simultaneous events per location
    event_cooldown_hours: minimum hours between events
"""
import os
import random
import re
from datetime import datetime, timedelta

from app.core.game_time import GameDuration, GameTime
from app.core.timeutils import parse_iso, utc_now, game_time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config_schema import field_default
from app.core.log import get_logger

logger = get_logger("random_events")

# Live getters — os.environ is re-read on every call, so admin UI changes take
# effect without a server restart.
def is_enabled() -> bool:
    return os.environ.get("EVENT_GENERATION_ENABLED", "true").lower() in ("true", "1", "yes")


def base_probability() -> float:
    # The env value is the percent field / 100 (config._flatten_to_env).
    return float(os.environ.get(
        "EVENT_BASE_PROBABILITY",
        field_default("random_events", "base_probability") / 100))


def resolution_cooldown_min() -> int:
    return int(os.environ.get("EVENT_RESOLUTION_COOLDOWN_MINUTES", "15"))


def resolution_proactive_enabled() -> bool:
    return os.environ.get("EVENT_RESOLUTION_PROACTIVE", "true").lower() in ("true", "1", "yes")

# Category definitions with base weights and TTL.
CATEGORIES = {
    "ambient": {
        "weight": 40,
        "ttl_hours": 2,
        "description": "Atmosphere, harmless — weather, sounds, smells, small observations",
    },
    "social": {
        "weight": 30,
        "ttl_hours": 4,
        "description": "Social interaction — a visitor, a message, a rumor, someone arriving",
    },
    "disruption": {
        "weight": 20,
        "ttl_hours": 6,
        "description": "Something that demands attention — a power outage, an accident, a discovery",
    },
    "danger": {
        "weight": 10,
        "ttl_hours": 8,
        "description": "Urgent, time pressure — a break-in, a fire, a storm, someone in danger",
    },
}

def default_event_settings() -> Dict[str, Any]:
    """Default settings for locations without overrides; probability reflects the live base value."""
    return {
        "event_probability": base_probability(),
        "allowed_categories": list(CATEGORIES.keys()),
        "event_blacklist": [],
        "max_concurrent_events": 1,
        "event_cooldown_hours": 2,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Last generator roll as a GAME stamp — the base probability is "per hour",
# which means per GAME hour since the game clock exists: with factor 60 an
# in-game hour passes per real minute and the roll must keep pace. The 60s
# periodic tick is the natural upper bound on roll frequency.
# RAM only (reset on restart), so it holds a GameTime, not a serialized form.
_LAST_GENERATE_GAME: List[Optional[GameTime]] = [None]


def check_and_generate():
    """Check every occupied location and generate events where due.

    Called from the periodic tick (60s); internally gated to one roll per
    GAME hour (see _LAST_GENERATE_GAME).
    """
    if not is_enabled():
        return

    _now_g = game_time()
    _last = _LAST_GENERATE_GAME[0]
    if _last is not None:
        _delta = (_now_g - _last).seconds
        if 0 <= _delta < 3600:
            return  # not a full game hour yet
        # negative delta = game clock was set backwards -> re-anchor
    _LAST_GENERATE_GAME[0] = _now_g

    try:
        from app.models.character import list_available_characters, get_character_current_location
        from app.models.world import list_locations

        chars = list_available_characters()
        if not chars:
            return

        # Feature gate: exclude characters that disable random events.
        from app.models.character_template import is_feature_enabled as _feat
        chars = [c for c in chars if _feat(c, "random_events_enabled")]
        if not chars:
            return

        # Find occupied locations.
        occupied: Dict[str, List[str]] = {}
        for char in chars:
            loc = get_character_current_location(char)
            if loc:
                occupied.setdefault(loc, []).append(char)

        if not occupied:
            return

        # Check each occupied location.
        locations = {loc.get("id"): loc for loc in list_locations()}
        for loc_id, char_names in occupied.items():
            loc_data = locations.get(loc_id)
            if not loc_data:
                continue
            _try_generate_for_location(loc_id, loc_data, char_names)

    except Exception as e:
        logger.debug("check_and_generate error: %s", e)


def check_escalation():
    """Check whether unanswered disruption/danger events need escalation. Called every five minutes from ThoughtLoop._tick()."""
    if not is_enabled():
        return

    try:
        from app.models.events import list_events, get_all_events
        from app.models.chat import get_chat_history

        all_events = get_all_events()
        for event in all_events:
            cat = event.get("category", "")
            if cat not in ("disruption", "danger"):
                continue

            # Already escalated into a follow-up event?
            event_id = event.get("id", "")
            already_escalated = any(
                e.get("escalation_of") == event_id for e in all_events
            )
            if already_escalated:
                continue

            # Age of the event (half the TTL elapsed?). ``ttl_hours`` are GAME
            # hours (app/models/events.py) and ``expires_at`` is a canonical
            # game stamp, so the escalation window has to be measured on the
            # GAME clock too. Measured in real hours it could never fire in an
            # accelerated world: with factor 6 a danger event (ttl 8) is
            # deleted after 80 real minutes while the escalation waited 4 real
            # hours. ``created_at`` stays the SYSTEM stamp below, because
            # _had_chat_since compares it against chat line timestamps.
            try:
                created = parse_iso(event.get("created_at", ""))
                ttl_hours = event.get("ttl_hours", 6)
                half_ttl = GameDuration.of(hours=ttl_hours / 2)
                started_g = GameTime.parse(event.get("game_ts", ""))
                if game_time() - started_g < half_ttl:
                    continue  # Not old enough yet.
            except (ValueError, TypeError):
                continue

            # Check location chat activity since the event.
            location_id = event.get("location_id", "")
            if not location_id:
                continue

            had_interaction = _had_chat_since(location_id, created)
            if had_interaction:
                continue  # Someone reacted in chat.

            # A resolution attempt, whether successful or failed,
            # also counts as a reaction and prevents escalation.
            resolution = event.get("resolution") or {}
            if resolution.get("attempts"):
                continue  # Already attempted at least once.

            # Escalate.
            _escalate_event(event)

    except Exception as e:
        logger.debug("check_escalation error: %s", e)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _get_event_settings(location: Dict[str, Any]) -> Dict[str, Any]:
    """Read location event_settings with defaults."""
    settings = location.get("event_settings", {})
    result = default_event_settings()
    result.update({k: v for k, v in settings.items() if v is not None})
    return result


def _get_category_weights(location: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, int]:
    """Calculate category weights based on danger_level."""
    from app.core.danger_system import get_danger_level

    weights = {k: v["weight"] for k, v in CATEGORIES.items()}
    danger = get_danger_level(location)

    # Higher danger levels shift weights toward disruption/danger.
    if danger >= 2:
        weights["danger"] += danger * 5
        weights["disruption"] += danger * 3
        weights["ambient"] = max(5, weights["ambient"] - danger * 3)

    # Keep only allowed categories.
    allowed = settings.get("allowed_categories", list(CATEGORIES.keys()))
    weights = {k: v for k, v in weights.items() if k in allowed}

    return weights


def _pick_category(weights: Dict[str, int]) -> str:
    """Choose a category by weight."""
    cats = list(weights.keys())
    w = [weights[c] for c in cats]
    return random.choices(cats, weights=w, k=1)[0]


_ENTRY_ROLL_LAST: Dict[Tuple[str, str], datetime] = {}


def _apply_event_stat_effects(event: dict, name: str, location: dict) -> None:
    """Apply the effective category map once per persisted event and character."""
    from app.core.stat_rules import get_setting
    from app.models.character import adjust_status_effects
    from app.models.events import add_stat_hit
    category = event.get("category", "")
    overrides = (location.get("event_settings") or {}).get("stat_effects") or {}
    effects = (overrides[category] if category in overrides
               else (get_setting("event_effects") or {}).get(category, {}))
    if effects and any(effects.values()) and add_stat_hit(event["id"], name):
        adjust_status_effects(name, effects, source=f"event:{category}")


def _apply_event_to_occupants(event: dict, location: dict) -> None:
    """Use the current roster, independently of the prompt's character limit."""
    from app.models.character import list_available_characters, get_character_current_location
    for name in list_available_characters():
        if get_character_current_location(name) == event.get("location_id"):
            _apply_event_stat_effects(event, name, location)


def apply_active_event_effects(character: str, location_id: str, location: dict) -> None:
    """Apply existing unresolved location events independently of random rolls."""
    from app.models.events import list_events
    for event in list_events(location_id=location_id):
        if event.get("location_id") == location_id and not event.get("resolved"):
            _apply_event_stat_effects(event, character, location)


def on_character_entered_room(*, character: str, location_id: str, room_id: str) -> None:
    """Cover NPC moves and party followers through the durable entry hook."""
    from app.models.world import get_location_by_id
    location = get_location_by_id(location_id)
    if location:
        apply_active_event_effects(character, location_id, location)


def try_roll_on_entry(character_name: str, loc_id: str, location: Dict[str, Any]) -> None:
    """Roll immediately when a character enters a location.

    EVENT_ENTRY_ROLL_ENABLED controls the feature globally.
    EVENT_ENTRY_ROLL_COOLDOWN_MINUTES limits repeated entry rolls per
    character and location. Existing unresolved danger events suppress rolls.
    A successful roll starts _generate_event in a background thread after
    0..N seconds of jitter so the move handler does not block.
    Avatar entry rolls are enabled; NPC walking-step triggers are disabled.
    """
    if not loc_id or not location:
        return
    apply_active_event_effects(character_name, loc_id, location)
    if os.environ.get("EVENT_ENTRY_ROLL_ENABLED", "1") not in ("1", "true", "True"):
        return
    if os.environ.get("EVENT_GENERATION_ENABLED", "1") not in ("1", "true", "True"):
        return

    # Cooldown
    try:
        cooldown_min = int(os.environ.get("EVENT_ENTRY_ROLL_COOLDOWN_MINUTES", "10"))
    except (ValueError, TypeError):
        cooldown_min = 10
    key = (character_name or "", loc_id)
    last = _ENTRY_ROLL_LAST.get(key)
    if last and (utc_now() - last).total_seconds() < cooldown_min * 60:
        return
    _ENTRY_ROLL_LAST[key] = utc_now()

    # Skip when an unresolved disruption/danger event is active locally.
    # Only one blocking event is allowed per location.
    # Ambient/social events do not block further rolls.
    # list_events also returns global events (location_id=None);
    # filter explicitly by this location so a global danger event
    # does not block entry rolls everywhere.
    try:
        from app.models.events import list_events
        for e in list_events(location_id=loc_id) or []:
            if e.get("location_id") != loc_id:
                continue
            if e.get("category") in ("disruption", "danger") and not e.get("resolved"):
                return
    except Exception as _e:
        logger.debug("entry-roll skip-check fehlgeschlagen: %s", _e)

    settings = _get_event_settings(location)
    prob = settings.get("event_probability", base_probability())
    if random.random() > prob:
        return

    weights = _get_category_weights(location, settings)
    if not weights:
        return
    category = _pick_category(weights)

    try:
        jitter_max = int(os.environ.get("EVENT_ENTRY_ROLL_JITTER_SECONDS", "3"))
    except (ValueError, TypeError):
        jitter_max = 3
    delay = random.uniform(0, max(0, jitter_max))

    def _spawn():
        try:
            from app.models.events import list_events as _le
            active = _le(location_id=loc_id)
            _generate_event(loc_id, location, category, [character_name], active, settings)
        except Exception as _e:
            logger.debug("entry-roll _spawn fehlgeschlagen: %s", _e)

    import threading
    threading.Timer(delay, _spawn).start()
    logger.info("Entry-Roll Treffer: %s @ %s — Event spawnt in %.1fs (cat=%s)",
                character_name, loc_id, delay, category)


def _try_generate_for_location(loc_id: str, location: Dict[str, Any], char_names: List[str]):
    """Try to generate an event for a location."""
    settings = _get_event_settings(location)

    # 1. Check probability.
    prob = settings.get("event_probability", base_probability())
    if random.random() > prob:
        return

    # 2. Allow at most one active unresolved disruption/danger event
    # per location. Ambient/social events may coexist because they
    # provide atmosphere without blocking. list_events includes global
    # events (location_id=None), which must not count here:
    # a single global danger event must not block generation
    # at every location.
    from app.models.events import list_events
    active_all = list_events(location_id=loc_id)
    active_local = [e for e in active_all if e.get("location_id") == loc_id]
    if any(e.get("category") in ("disruption", "danger") and not e.get("resolved")
           for e in active_local):
        return

    # 3. Check the local concurrent-event limit, especially to prevent
    # ambient/social event spam.
    max_concurrent = settings.get("max_concurrent_events", 1)
    if len(active_local) >= max_concurrent:
        return
    active = active_local

    # 4. Check minimum hours since the latest event.
    # Legacy event_cooldown_minutes remains supported.
    cooldown_hours = settings.get("event_cooldown_hours")
    if cooldown_hours is None:
        legacy_min = settings.get("event_cooldown_minutes")
        cooldown_hours = (legacy_min / 60.0) if legacy_min is not None else 2
    if active:
        latest = max(active, key=lambda e: e.get("created_at", ""))
        try:
            # GAME hours, like the per-hour dice gate above: in real hours a
            # 2 h cooldown would mean 12 game hours at factor 6 (5 game days at
            # factor 60), while the dice itself rolls once per GAME hour.
            last_time = GameTime.parse(latest.get("game_ts", ""))
            if game_time() - last_time < GameDuration.of(hours=cooldown_hours):
                return
        except (ValueError, TypeError):
            pass

    # 5. Roll the category.
    weights = _get_category_weights(location, settings)
    if not weights:
        return
    category = _pick_category(weights)

    # 6. Generate through the LLM, occasionally producing a secret hint.
    reveal_chance = float(settings.get("secret_reveal_chance", 0.08))
    if reveal_chance > 0 and random.random() < reveal_chance:
        if _try_generate_secret_hint_event(loc_id, location, char_names, settings):
            return  # Hint event generated.
    _generate_event(loc_id, location, category, char_names, active, settings)


def _try_generate_secret_hint_event(loc_id: str,
    location: Dict[str, Any],
    char_names: List[str],
    settings: Dict[str, Any]) -> bool:
    """Generate a subtle hint about a secret of a character present here.

    Choose a character whose secret is not already widely known, generate
    a hint without revealing it fully, and mark the other occupants as hinted-to.
    Return True when a hint event was created.
    """
    if len(char_names) < 2:
        return False  # Requires a target and at least one observer.

    from app.models.secrets import list_secrets, is_record
    from app.models.events import add_event

    # Collect characters with secrets.
    candidates = []
    for c in char_names:
        try:
            secs = [s for s in list_secrets(c)
                    if not is_record(s) and s.get("content") and len(s.get("known_by", [])) < 3]
            if secs:
                candidates.append((c, secs))
        except Exception:
            continue
    if not candidates:
        return False

    # Choose a random character, then weight secrets by severity.
    target_char, target_secrets = random.choice(candidates)
    # Higher severity gives a secret more weight.
    weights = [max(1, int(s.get("severity", 2))) for s in target_secrets]
    secret = random.choices(target_secrets, weights=weights, k=1)[0]

    # Prompt a subtle hint in the target character language
    # for world narration rather than the user interface.
    from app.core.llm_router import llm_call
    from app.core.i18n import language_name
    from app.models.character import get_character_language
    _lang = (get_character_language(target_char) or "de")
    lang_name = language_name(_lang)

    observers = [c for c in char_names if c != target_char]
    from app.core.prompt_templates import render_task
    sys_prompt, user_prompt = render_task(
        "random_event_secret_hint",
        location_name=location.get("name", loc_id),
        target_character=target_char,
        secret_content=secret.get("content", ""),
        observers_list=", ".join(observers),
        language_name=lang_name)

    try:
        response = llm_call(
            task="random_event",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name="system")
        text = (response.content or "").strip()
        text = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', text).strip().strip('"').strip("'").strip()
        if not text or len(text) < 10:
            return False

        # Store secret metadata for the hint, without a full reveal.
        event = add_event(text, location_id=loc_id,
            ttl_hours=4, category="social",
            metadata={
                "hints_at_secret_id": secret.get("id", ""),
                "secret_owner": target_char,
                "observers": observers,
            })
        _apply_event_to_occupants(event, location)
        # Observers are not added to known_by: they only see the hint
        # and must infer the connection themselves.
        logger.info("Secret-Hint-Event @ %s: %s fuer %s (Ziel: %s)",
                    location.get("name", loc_id), text[:60], target_char, observers)
        return True
    except Exception as e:
        logger.debug("Secret-Hint-Event fehlgeschlagen: %s", e)
        return False


def _generate_event(loc_id: str,
    location: Dict[str, Any],
    category: str,
    char_names: List[str],
    active_events: List[Dict[str, Any]],
    settings: Dict[str, Any]):
    """Generate an event through the LLM and store it."""
    from app.core.llm_router import llm_call
    from app.models.events import add_event
    from app.models.character import get_character_current_feeling
    from app.core.danger_system import get_hazards

    # Gather context.
    loc_name = location.get("name", loc_id)
    loc_desc = location.get("description", "")
    rooms = [r.get("name", "") for r in location.get("rooms", []) if r.get("name")]
    hazards = get_hazards(location)
    hazard_texts = [h.get("name", h.get("description", "")) for h in hazards if isinstance(h, dict)]

    # Characters and moods.
    char_infos = []
    for c in char_names[:5]:
        mood = get_character_current_feeling(c) or ""
        char_infos.append(f"{c} (mood: {mood})" if mood else c)

    # Clock, date and day bucket from the game clock + world calendar. The
    # bucket follows the season's sunrise/sunset and the calendar's noon/
    # evening hours instead of hardcoded 6/12/18/22 boundaries.
    _now = game_time()
    current_time = _now.time_hhmm()
    time_desc = _now.day_bucket()

    # Previous event, to avoid repetition.
    last_event = ""
    if active_events:
        last_event = active_events[-1].get("text", "")

    # Blacklist
    blacklist = settings.get("event_blacklist", [])

    cat_info = CATEGORIES.get(category, {})
    cat_desc = cat_info.get("description", category)

    # Account language
    from app.core.i18n import language_name
    from app.models.account import get_language_settings
    _lang = get_language_settings()["system_language"]
    lang_name = language_name(_lang)
    # In-world calendar date — the season name is a localized data field, so
    # it follows the same language as the rest of this prompt.
    game_date = _now.date_label(_lang)
    # The season's atmosphere as one line — an event that fits the weather
    # ("the wind tears at the awning") beats a generic one.
    game_weather = _now.atmosphere(_lang)["label"]

    # Indoor/outdoor setting of the location as a prompt hint (empty if unset).
    indoor_flag = (location.get("indoor") or "").strip().lower()
    if indoor_flag == "indoor":
        setting_block = ("Setting: Indoor (enclosed location — fit interior themes: "
                          "drafts, flickering light, knocking sounds, broken objects, "
                          "intruders, scents)")
    elif indoor_flag == "outdoor":
        setting_block = ("Setting: Outdoor (open-air location — fit weather, wildlife, "
                          "terrain, or arriving people)")
    else:
        setting_block = ""

    from app.core.prompt_templates import render_task
    sys_prompt, user_prompt = render_task(
        "random_event_general",
        location_name=loc_name,
        category=category,
        category_description=cat_desc,
        current_time=current_time,
        time_of_day=time_desc,
        game_date=game_date,
        game_weather=game_weather,
        location_description=loc_desc,
        setting_block=setting_block,
        rooms_block=f"Rooms: {', '.join(rooms[:6])}" if rooms else "",
        characters_block=f"Characters present: {', '.join(char_infos)}" if char_infos else "",
        hazards_block=f"Known hazards: {', '.join(hazard_texts)}" if hazard_texts else "",
        last_event_block=f'Last event here (avoid repetition): "{last_event}"' if last_event else "",
        blacklist_block=f"Do NOT mention: {', '.join(blacklist)}" if blacklist else "",
        language_name=lang_name)

    # Call the LLM.
    try:
        response = llm_call(
            task="random_event",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name="system")

        raw = (response.content or "").strip()
        # Clean LLM artifacts.
        raw = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', raw).strip()

        text, image_prompt = _parse_event_payload(raw)

        if not text or len(text) < 5:
            logger.debug("LLM-Event-Text zu kurz oder leer")
            return

        # Check the blacklist.
        text_lower = text.lower()
        for bl in blacklist:
            if bl.lower() in text_lower:
                logger.info("Event geblockt (Blacklist '%s'): %s", bl, text[:60])
                return

        # Store the event; image_prompt belongs in metadata, so the free-form
        # JSON payload needs no schema migration.
        ttl = cat_info.get("ttl_hours", 6)
        metadata: Dict[str, Any] = {}
        if image_prompt:
            metadata["image_prompt"] = image_prompt
        event = add_event(text, location_id=loc_id,
                         ttl_hours=ttl, category=category,
                         metadata=metadata or None)
        _apply_event_to_occupants(event, location)
        logger.info("Random Event [%s] @ %s: %s", category, loc_name, text[:80])

        # Danger events block leaving until resolved. The avatar remains
        # there while NPCs attempt resolution through random_events.resolve;
        # pathfinding routes around the blocked location.
        if category == "danger" and event and event.get("id") and loc_id:
            try:
                from app.models.rules import add_event_rule
                add_event_rule(
                    event_id=event["id"],
                    location_id=loc_id,
                    message=text,
                    action="leave",
                    name=f"Event @ {loc_name}")
            except Exception as _e:
                logger.debug("add_event_rule fehlgeschlagen: %s", _e)

        # Generate images only for disruption/danger at locations with a
        # background_image. Without a background the event still exists,
        # but no image overlay is generated.
        if event and category in ("disruption", "danger") and image_prompt:
            try:
                from app.core.event_images import trigger_event_image
                trigger_event_image(event["id"], loc_id, image_prompt, resolved=False)
            except Exception as _e:
                logger.debug("trigger_event_image fehlgeschlagen: %s", _e)

    except Exception as e:
        logger.error("Event-Generierung fehlgeschlagen: %s", e)


def _parse_event_payload(raw: str) -> Tuple[str, str]:
    """Parse JSON output from the event generator LLM.

    On a parse failure or non-JSON fallback, use the entire output as event
    text and return no image_prompt.
    """
    import json as _json

    # Fast path: valid JSON object.
    text = raw
    # Strip Markdown fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    if text.startswith("{"):
        try:
            payload = _json.loads(text)
            evt_text = str(payload.get("text", "")).strip().strip('"').strip("'").strip()
            image_prompt = str(payload.get("image_prompt", "")).strip()
            if evt_text:
                return evt_text, image_prompt
        except Exception:
            pass

    # Recover a single JSON object from surrounding output.
    m = re.search(r'\{[^{}]*"text"\s*:\s*"[^"]*"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            payload = _json.loads(m.group(0))
            evt_text = str(payload.get("text", "")).strip().strip('"').strip("'").strip()
            image_prompt = str(payload.get("image_prompt", "")).strip()
            if evt_text:
                return evt_text, image_prompt
        except Exception:
            pass

    # Fallback: use the whole non-JSON output as event text, without an image.
    fallback_text = raw.strip().strip('"').strip("'").strip()
    return fallback_text, ""


def _escalate_event(event: Dict[str, Any]):
    """Escalate an unanswered disruption/danger event."""
    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task
    from app.models.events import add_event

    old_cat = event.get("category", "disruption")
    new_cat = "danger" if old_cat == "disruption" else "danger"
    old_text = event.get("text", "")
    location_id = event.get("location_id", "")

    # Account language.
    from app.core.i18n import language_name
    from app.models.account import get_language_settings
    _lang = get_language_settings()["system_language"]
    lang_name = language_name(_lang)

    sys_prompt, user_prompt = render_task(
        "random_event_escalation",
        old_text=old_text,
        new_category=new_cat,
        language_name=lang_name)

    try:
        response = llm_call(
            task="random_event",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name="system")

        text = (response.content or "").strip()
        text = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', text).strip()
        text = text.strip('"').strip("'").strip()

        if text and len(text) >= 5:
            ttl = CATEGORIES.get(new_cat, {}).get("ttl_hours", 8)
            escalated = add_event(text, location_id=location_id,
                     ttl_hours=ttl, category=new_cat,
                     escalation_of=event.get("id"))
            from app.models.world import get_location_by_id
            location = get_location_by_id(location_id) if location_id else None
            if location:
                _apply_event_to_occupants(escalated, location)
            logger.info("Event eskaliert [%s→%s]: %s → %s",
                        old_cat, new_cat, old_text[:40], text[:40])

    except Exception as e:
        logger.error("Event-Eskalation fehlgeschlagen: %s", e)


def _had_chat_since(location_id: str, since: datetime) -> bool:
    """Check whether chat activity occurred at a location after a timestamp."""
    try:
        from app.models.character import list_available_characters, get_character_current_location
        from app.models.chat import get_chat_history

        chars = list_available_characters()
        for char in chars:
            if get_character_current_location(char) != location_id:
                continue
            history = get_chat_history(char)
            if not history:
                continue
            # Check the most recent message.
            last = history[-1] if history else None
            if last:
                try:
                    ts = parse_iso(last.get("timestamp", ""))
                    if ts > since:
                        return True
                except (ValueError, TypeError):
                    pass
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Event Resolution (validation, proactive solving, attempts)
# ---------------------------------------------------------------------------

def _on_resolution_cooldown(event: Dict[str, Any], cooldown_min: Optional[int] = None) -> bool:
    """Whether the most recent resolution attempt is still within the cooldown."""
    if cooldown_min is None:
        cooldown_min = resolution_cooldown_min()
    try:
        last = (event.get("resolution") or {}).get("last_attempt_at")
        if not last:
            return False
        last_dt = parse_iso(last)
        return utc_now() - last_dt < timedelta(minutes=cooldown_min)
    except (ValueError, TypeError):
        return False


def validate_solution(event: Dict[str, Any],
    solution_text: str,
    actor_name: str,
    actors_joint: Optional[List[str]] = None) -> Dict[str, Any]:
    """Ask the tool LLM whether the proposed solution plausibly resolves the event.

    Character traits from template stat hint_thresholds provide context:
    attentive or brave characters fare better in borderline cases.
    Return {"resolved": bool, "reason": str}.
    """
    import json as _json
    from app.core.llm_router import llm_call
    from app.core.stat_hints import format_character_with_hints

    actor_with_caps = format_character_with_hints(actor_name)
    joint_with_caps = [format_character_with_hints(j) for j in (actors_joint or [])]
    joint_txt = f" (together with {', '.join(joint_with_caps)})" if joint_with_caps else ""

    from app.core.prompt_templates import render_task
    sys_prompt, user_prompt = render_task(
        "random_event_validate_solution",
        event_text=event.get("text", ""),
        event_category=event.get("category", ""),
        actor_with_caps=actor_with_caps,
        joint_block=joint_txt,
        solution_text=solution_text.strip())

    try:
        response = llm_call(
            task="random_event",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name=actor_name)
        raw = (response.content or "").strip()
        raw = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', raw).strip()
        # Extract JSON because the LLM may wrap it in prose.
        m = re.search(r'\{[^{}]*"resolved"[^{}]*\}', raw, re.DOTALL)
        payload = _json.loads(m.group(0)) if m else _json.loads(raw)
        return {
            "resolved": bool(payload.get("resolved", False)),
            "reason": str(payload.get("reason", ""))[:200],
        }
    except Exception as e:
        logger.warning("validate_solution Fehler: %s", e)
        return {"resolved": False, "reason": f"validator-error: {e}"}


def try_resolve_events():
    """Proactive resolution: characters attempt to solve open events.

    Called every five minutes from ThoughtLoop._tick(). Select at most one
    event per call as a global rate limit.
    """
    if not resolution_proactive_enabled():
        return

    try:
        from app.models.events import get_all_events, resolve_event, record_attempt
        from app.models.character import (
            list_available_characters, get_character_current_location,
            is_character_sleeping)
        from app.models.account import is_player_controlled

        # Unresolved disruption/danger events without an active cooldown.
        candidates = []
        for evt in get_all_events():
            if evt.get("category") not in ("disruption", "danger"):
                continue
            if evt.get("resolved"):
                continue
            if not evt.get("location_id"):
                continue
            if _on_resolution_cooldown(evt):
                continue
            candidates.append(evt)
        if not candidates:
            return

        # Danger before disruption, otherwise newest first.
        candidates.sort(key=lambda e: (0 if e.get("category") == "danger" else 1,
                                        e.get("created_at", "")), reverse=False)
        event = candidates[0]
        location_id = event["location_id"]

        # Characters at this location, excluding player-controlled ones
        # so the proactive solver does not preempt the user chat reply.
        from app.models.character_template import is_feature_enabled as _feat
        actors = []
        for c in list_available_characters():
            if get_character_current_location(c) != location_id:
                continue
            if is_character_sleeping(c):
                continue
            # Same feature gate as the generation path: a character that does
            # not take part in random events does not solve them either.
            if not _feat(c, "random_events_enabled"):
                continue
            try:
                if is_player_controlled(c):
                    continue
            except Exception:
                pass
            actors.append(c)
        if not actors:
            return

        # Primary actor plus an optional helper for joint resolution.
        primary = actors[0]
        joint = actors[1:2] if len(actors) > 1 else []

        solution_text = _generate_solution_rp(primary, event, joint)
        if not solution_text:
            return

        result = validate_solution(event, solution_text, primary, joint)
        outcome = "success" if result["resolved"] else "fail"
        record_attempt(event["id"], primary, solution_text,
                       outcome=outcome, reason=result.get("reason", ""),
                       joint_with=joint)

        if result["resolved"]:
            resolve_event(event["id"], resolved_by=primary,
                          resolved_text=solution_text[:200])
            _diary_log_resolution(primary, event, solution_text, True, joint)
            _notify_resolution(primary, event, solution_text, joint)
        else:
            _diary_log_resolution(primary, event, solution_text, False,
                                   joint, reason=result.get("reason", ""))

    except Exception as e:
        logger.debug("try_resolve_events error: %s", e)


def _generate_solution_rp(actor: str, event: Dict[str, Any],
    joint: Optional[List[str]] = None) -> str:
    """Ask the character roleplay LLM for a short account of how it resolves the event."""
    from app.models.character import get_character_personality, get_character_language
    from app.core.llm_router import llm_call

    personality = get_character_personality(actor) or ""
    joint_txt = f" You are with {', '.join(joint)}." if joint else ""
    from app.core.i18n import language_name
    _lang = (get_character_language(actor) or "de")
    lang_name = language_name(_lang)

    from app.core.prompt_templates import render_task
    sys_prompt, user_prompt = render_task(
        "random_event_solution_rp",
        actor=actor,
        personality=personality,
        event_text=event.get("text", ""),
        joint_block=joint_txt,
        language_name=lang_name)

    try:
        response = llm_call(
            task="thought",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name=actor)
        text = (response.content or "").strip()
        text = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', text).strip()
        # Remove markers appended by the roleplay LLM.
        text = re.sub(r'\n?\s*\*\*I\s+(feel|do|am\s+at)\s+[^*]+\*\*', '', text, flags=re.IGNORECASE).strip()
        return text
    except Exception as e:
        logger.warning("solution RP-Generierung Fehler: %s", e)
        return ""


def _diary_log_resolution(actor: str, event: Dict[str, Any],
    solution_text: str, success: bool,
    joint: Optional[List[str]] = None,
    reason: str = ""):
    """Record the resolution attempt as episodic memory.

    Daily diary summaries aggregate memories automatically, so one memory
    entry per participating character is sufficient.
    """
    try:
        from app.models.memory import add_memory
        event_text = event.get("text", "")
        joint_txt = f" (mit {', '.join(joint)})" if joint else ""
        if success:
            content = f"Event geloest{joint_txt}: {event_text[:120]} — Aktion: {solution_text[:180]}"
            importance = 4
        else:
            content = f"Versuch fuer {event_text[:120]}{joint_txt}: {solution_text[:150]}. Erfolglos ({reason[:100]})."
            importance = 2
        all_actors = [actor] + list(joint or [])
        for p in all_actors:
            add_memory(p, content, memory_type="episodic",
                       importance=importance, tags=["event_resolution"])
    except Exception as e:
        logger.debug("Memory-Log Fehler: %s", e)


def _notify_resolution(actor: str, event: Dict[str, Any],
    solution_text: str, joint: Optional[List[str]] = None):
    """Send a proactive notification that the event was resolved."""
    try:
        from app.models.notifications import create_notification
        joint_txt = f" (mit {', '.join(joint)})" if joint else ""
        content = f"Event geloest{joint_txt}: {event.get('text', '')[:200]} — {solution_text[:500]}"
        create_notification(
            character=actor,
            content=content,
            notification_type="event_resolved",
            metadata={"event_id": event.get("id", ""), "joint_with": joint or []})
    except Exception as e:
        logger.debug("Notification Fehler: %s", e)
