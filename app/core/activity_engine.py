"""Activity Engine - condition evaluation, visibility, cooldowns, duration, triggers.

Central logic for the extended special activities.
Used by set_activity_skill.py and chat.py.

All time here is GAME time (:class:`GameTime`): conditions, daily schedule
slots and the hourly stat tick are things the world experiences, so they run
on the game clock, never on system time.
"""
import re
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.game_time import GameTime
from app.core.npc_windows import is_night
from app.core.timeutils import game_time
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("activity_engine")


# ============================================================
# 1. CONDITION PARSER & EVALUATOR
# ============================================================

def evaluate_condition(
    condition: str, character_name: str,
    location_id: str = "",
    room_id: str = "") -> Tuple[bool, str]:
    """Evaluate a condition expression.

    Returns:
        (passed: bool, reason: str) - reason is empty when passed=True
    """
    global _last_matched_partner
    _last_matched_partner = None

    if not condition or not condition.strip():
        return True, ""

    # Split OR groups first, then AND conditions within each group.
    or_groups = [g.strip() for g in re.split(r"\s+OR\s+", condition, flags=re.IGNORECASE)]

    last_reason = ""
    for group in or_groups:
        # AND conditions within one group
        and_parts = [p.strip() for p in re.split(r"\s+AND\s+", group, flags=re.IGNORECASE)]
        group_passed = True
        group_reason = ""
        for part in and_parts:
            if not part:
                continue
            passed, reason = _evaluate_single_condition(part, character_name, location_id, room_id)
            if not passed:
                group_passed = False
                group_reason = reason
                break
        if group_passed:
            return True, ""
        last_reason = group_reason

    # No OR group passed
    return False, last_reason


def _evaluate_single_condition(
    condition: str, character_name: str,
    location_id: str, room_id: str = "") -> Tuple[bool, str]:
    """Evaluate a single condition."""
    cond = condition.strip()

    # --- NOT prefix ---
    negated = False
    if cond.upper().startswith("NOT "):
        negated = True
        cond = cond[4:].strip()

    cond = cond.lower()

    passed, reason = _evaluate_single_condition_inner(cond, character_name, location_id, room_id)
    if negated:
        if passed:
            return False, f"Bedingung 'NOT {cond}' nicht erfuellt"
        return True, ""
    return passed, reason


def _evaluate_single_condition_inner(
    cond: str, character_name: str,
    location_id: str, room_id: str = "") -> Tuple[bool, str]:
    """Evaluate a single condition without NOT handling."""

    # Unconditional truth, for example for an unconditional access block.
    if cond in ("always", "true"):
        return True, ""

    # --- alone ---
    if cond == "alone":
        return _check_alone(character_name, location_id)

    # --- night / day with an optional minute offset on the START of the window ---
    # The window bounds are the SUNSET and SUNRISE of the current season
    # (world calendar, app/core/game_time.py) — with the default calendar those
    # are 18:00 / 06:00, so an unconfigured world behaves exactly as before.
    #
    # WITHOUT an offset this IS `npc_windows.is_night` — the app's one
    # night/day decision, which a slot's `when="night"` asks as well. Only the
    # offset arithmetic lives here, and it runs on the same basis: the very
    # `now.sunrise_min` / `now.sunset_min` that decision compares against.
    #
    # Examples (default calendar):
    #   night       — sunset (18:00) until sunrise (06:00)
    #   night-30    — starts 30 min EARLIER: 17:30 until sunrise
    #   night+30    — starts 30 min LATER:   18:30 until sunrise
    #   day         — sunrise (06:00) until sunset (18:00)
    #   day-30      — 05:30 until sunset
    #   day+30      — 06:30 until sunset
    # The offset shifts only the START — the end stays sunrise resp. sunset.
    # Negative (-) = preparation window, positive (+) = delay.
    td_match = re.match(r"^(night|day)(?:([+-])(\d+))?$", cond)
    if td_match:
        base = td_match.group(1)
        sign = td_match.group(2) or ""
        offset_min = int(td_match.group(3) or 0)
        if sign == "+":
            shift = offset_min        # start later
        else:
            shift = -offset_min       # start earlier (default for "-")
        now = game_time()  # night/day rules follow the game clock
        now_min = now.minutes_of_day
        sunrise_min = now.sunrise_min
        sunset_min = now.sunset_min
        lbl_offset = f"{sign}{offset_min}" if offset_min else ""
        if base == "night":
            if not shift:
                in_window = is_night(now)
            else:
                start_min = sunset_min + shift
                end_min = sunrise_min
                # Normalise into [0, 1440)
                start_min %= 24 * 60
                # Wrap-around: night usually spans midnight.
                if start_min < end_min:
                    # Start lies BEFORE end_min (e.g. a large negative shift
                    # that did not wrap) — unusual but possible.
                    in_window = start_min <= now_min < end_min
                else:
                    # Normal case: the window spans midnight
                    in_window = (now_min >= start_min) or (now_min < end_min)
            if in_window:
                return True, ""
            return False, f"Nur nachts verfuegbar (night{lbl_offset})"
        else:  # day
            if not shift:
                in_window = not is_night(now)
            else:
                start_min = sunrise_min + shift
                end_min = sunset_min
                start_min_norm = start_min % (24 * 60)
                if start_min < 0:
                    # A strongly negative offset pulls the start before
                    # midnight
                    in_window = (now_min >= start_min_norm) or (now_min < end_min)
                elif start_min_norm >= end_min:
                    # Strongly positive offset or overflow — empty window
                    in_window = False
                else:
                    in_window = start_min_norm <= now_min < end_min
            if in_window:
                return True, ""
            return False, f"Nur tagsueber verfuegbar (day{lbl_offset})"

    # --- present:Name --- (target character in the same room/location)
    present_match = re.match(r"present:(.+)", cond)
    if present_match:
        return _check_present(character_name, present_match.group(1).strip(),
                              location_id, room_id)

    # --- mood:X ---
    mood_match = re.match(r"mood:(.+)", cond)
    if mood_match:
        target_mood = mood_match.group(1).strip()
        return _check_mood(character_name, target_mood)

    # --- relationship:Name>N or relationship:any>N ---
    rel_match = re.match(r"relationship:(\w+)([><=])(\d+)", cond)
    if rel_match:
        target_char = rel_match.group(1)
        operator = rel_match.group(2)
        threshold = int(rel_match.group(3))
        return _check_relationship(character_name, location_id,
                                   target_char, operator, threshold, field="strength")

    # --- romantic:Name>N or romantic:any>N ---
    rom_match = re.match(r"romantic:(\w+)([><=])(\d+)", cond)
    if rom_match:
        target_char = rom_match.group(1)
        operator = rom_match.group(2)
        threshold = int(rom_match.group(3))
        return _check_relationship(character_name, location_id,
                                   target_char, operator, threshold, field="romantic")

    # These atoms always inspect the character, even in target-access checks.
    if cond in ("at_home", "offmap"):
        from app.models.character import (
            OFFMAP_SLEEP_SENTINEL, get_character_config,
            get_character_current_location, get_character_pos,
        )
        current = get_character_current_location(character_name)
        if cond == "offmap":
            passed = not current and get_character_pos(character_name) is None
        else:
            home = (get_character_config(character_name) or {}).get("home_location") or ""
            if home == OFFMAP_SLEEP_SENTINEL:
                passed = not current and get_character_pos(character_name) is None
            else:
                passed = bool(home) and home == current
        return bool(passed), "" if passed else f"Condition '{cond}' not met"

    if cond == "travelling":
        from app.core.travel_engine import get_journey
        passed = get_journey(character_name) is not None
        return passed, "" if passed else "No journey in progress"

    danger_match = re.fullmatch(r"location_danger([><=])(\d+)", cond)
    if danger_match:
        from app.models.character import get_character_current_location
        from app.models.world import get_location_by_id
        from app.core.danger_system import get_danger_level
        current = get_character_current_location(character_name)
        location = get_location_by_id(current) if current else None
        level = get_danger_level(location) if location else 0
        passed = _compare(level, danger_match[1], int(danger_match[2]))
        return passed, "" if passed else "Location danger condition not met"

    if cond.startswith("state:"):
        from app.core.prompt_filters import is_state_active
        passed = is_state_active(character_name, cond.split(":", 1)[1].strip())
        return passed, "" if passed else "State is not active"

    # Generic comparisons for template-defined status fields follow specific atoms.
    stat_match = re.match(r"([a-z_]+)([><=])(\d+)$", cond)
    if stat_match:
        stat_name = stat_match.group(1)
        # Exclude reserved names with dedicated handlers.
        if stat_name not in ("mood", "relationship", "romantic", "has_item", "condition",
                             "event_active", "has_secret", "alone", "night", "day", "npc_present",
                             "current_activity", "location_danger"):
            operator = stat_match.group(2)
            threshold = int(stat_match.group(3))
            return _check_status_effect(character_name, stat_name, operator, threshold)

    # Boolean state flags are authoritative, independently of activity text.
    # State flags: core is_sleeping plus every flag DECLARED by a skill
    # package (registry) — no flag names hardcoded here (R1).
    _declared_flags = {"is_sleeping"}
    try:
        from app.plugins.registry import flag_specs
        _declared_flags.update(s.flag for s in flag_specs())
    except Exception:
        pass
    if cond in _declared_flags:
        fname = cond
        try:
            from app.models.character import get_state_flags
            if bool(get_state_flags(character_name).get(fname)):
                return True, ""
            return False, f"{fname} ist nicht gesetzt"
        except Exception as e:
            logger.debug("state-flag-Check fehlgeschlagen: %s", e)
            return False, f"{fname}-Check fehlgeschlagen"

    # --- current_activity:X (the character's pose, substring match) ---
    # Activity library removed: match against get_effective_activity (pose
    # flavor/catalog key resp. "Sleeping" via the is_sleeping flag), by
    # substring in both directions.
    cact_match = re.match(r"current_activity:(.+)", cond)
    if cact_match:
        target = cact_match.group(1).strip().lower()
        try:
            from app.models.character import get_effective_activity
            current = (get_effective_activity(character_name) or "").lower()
            if not current:
                return False, f"Pose muss '{target}' sein (keine aktiv)"
            if target in current or current in target:
                return True, ""
            return False, f"Pose muss '{target}' sein (ist: '{current}')"
        except Exception as e:
            logger.debug("current_activity-Check fehlgeschlagen: %s", e)
            return False, f"Pose muss '{target}' sein"

    # schedule:X matches the current daily schedule slot.
    # sleeping matches sleep slots; awake matches their negation.
    sched_match = re.match(r"schedule:(.+)", cond)
    if sched_match:
        target = sched_match.group(1).strip().lower()
        try:
            from app.models.character import get_character_daily_schedule
            schedule = get_character_daily_schedule(character_name) or {}
            if not schedule.get("enabled", False):
                # Without a schedule, neither sleeping nor awake matches.
                return False, "Tagesablauf nicht aktiv"
            current_hour = game_time().hour  # daily schedule = in-game hours
            slot = next((s for s in schedule.get("slots", [])
                         if s.get("hour") == current_hour), None)
            if target in ("sleeping", "sleep"):
                is_sleep = bool(slot and (slot.get("sleep")
                                          or slot.get("activity") == "__sleep__"
                                          or slot.get("location") == "__sleep__"))
                if is_sleep:
                    return True, ""
                return False, "Schedule sagt nicht Schlafen"
            if target in ("awake", "wake"):
                is_sleep = bool(slot and (slot.get("sleep")
                                          or slot.get("activity") == "__sleep__"
                                          or slot.get("location") == "__sleep__"))
                if not is_sleep:
                    return True, ""
                return False, "Schedule sagt Schlafen"
            # Otherwise match the target against slot.activity.
            slot_act = (slot.get("activity") if slot else "") or ""
            if slot_act.lower() == target:
                return True, ""
            return False, f"Schedule sagt nicht '{target}' (ist: '{slot_act}')"
        except Exception as e:
            logger.debug("schedule-condition Fehler: %s", e)
            return False, f"Schedule-Bedingung nicht auswertbar: {target}"

    # --- condition:X (profile active_conditions) ---
    cond_match = re.match(r"condition:(.+)", cond)
    if cond_match:
        cond_name = cond_match.group(1).strip().lower()
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
            active = profile.get("active_conditions", []) or []
            if any((c.get("name") or "").lower() == cond_name for c in active):
                return True, ""
            return False, f"Zustand nicht aktiv: {cond_name}"
        except Exception:
            return False, f"Zustand nicht aktiv: {cond_name}"

    # --- has_item:<id|name> --- (character inventory)
    item_match = re.match(r"has_item:(.+)", cond)
    if item_match:
        token = item_match.group(1).strip()
        try:
            from app.models.inventory import (
                has_item as _has_item,
                resolve_item_id as _resolve_item_id,
                get_item as _get_item)
            resolved_id = _resolve_item_id(token) or token
            if _has_item(character_name, resolved_id):
                return True, ""
            item_name = token
            try:
                _it = _get_item(resolved_id)
                if _it:
                    item_name = _it.get("name", token)
            except Exception:
                pass
            return False, f"Benoetigt Item: {item_name}"
        except Exception:
            return True, ""

    # --- room_has_item:<id|name> --- (target room contains item)
    room_item_match = re.match(r"room_has_item:(.+)", cond)
    if room_item_match:
        token = room_item_match.group(1).strip()
        if not room_id:
            return False, "Kein Raum-Kontext"
        try:
            from app.models.inventory import (
                resolve_item_id as _resolve_item_id,
                get_item as _get_item,
                get_room_items as _get_room_items)
            resolved_id = _resolve_item_id(token) or token
            room_items = _get_room_items(location_id, room_id) or []
            for ri in room_items:
                if ri.get("item_id") == resolved_id:
                    return True, ""
                # Name-match fallback
                it = _get_item(ri.get("item_id", ""))
                if it and (it.get("name") or "").strip().lower() == token.lower():
                    return True, ""
            item_name = token
            try:
                _it = _get_item(resolved_id)
                if _it:
                    item_name = _it.get("name", token)
            except Exception:
                pass
            return False, f"Raum enthaelt kein Item: {item_name}"
        except Exception:
            return True, ""

    # --- has_secret ---
    if cond == "has_secret":
        return _check_has_secret(character_name)

    # --- npc_present ---
    if cond == "npc_present":
        # Placeholder for the NPC system
        return True, ""

    # --- event_active:category ---
    event_match = re.match(r"event_active:(.+)", cond)
    if event_match:
        # Placeholder for event categories
        return True, ""

    # --- is_male / is_female — shorthand for gender=male / gender=female ---
    if cond in ("is_male", "is_female"):
        try:
            from app.models.character import get_character_profile
            g = str((get_character_profile(character_name) or {}).get("gender", "") or "").strip().lower()
            want = cond[3:]
            if g == want:
                return True, ""
            return False, f"gender ist '{g or '—'}' (braucht '{want}')"
        except Exception:
            return False, f"Bedingung nicht auswertbar: {cond}"

    # --- state flags: is_sleeping / is_wet / is_intimate / decency_exempt
    # plus every plugin-registered flag (flag_specs). The help panel offers
    # exactly this set as bare conditions, so the evaluator must accept
    # them; they live as top-level booleans in the profile (set by activity
    # skills, the decency toggle and set_flags rules).
    known_flags = set()
    try:
        from app.models.character import get_state_flags
        known_flags = set(get_state_flags(character_name))
    except Exception:
        pass
    try:
        from app.plugins.registry import flag_specs
        known_flags |= {s.flag for s in flag_specs()}
    except Exception:
        pass
    if cond in known_flags:
        try:
            from app.models.character import get_character_profile
            active = bool((get_character_profile(character_name) or {}).get(cond))
        except Exception:
            return False, f"Bedingung nicht auswertbar: {cond}"
        if active:
            return True, ""
        return False, f"Flag '{cond}' not active"

    # --- {profile_field}=value / {profile_field}!=value — generic string
    # compare against a top-level profile field (e.g. gender=male,
    # template=human-roleplay). Evaluated LAST so it never shadows the
    # specific handlers above; numeric stat comparisons stay with the
    # status_effects matcher.
    field_match = re.match(r"([a-z_][a-z0-9_]*)\s*(!=|=)\s*(.+)$", cond)
    if field_match:
        fname = field_match.group(1)
        op = field_match.group(2)
        expected = field_match.group(3).strip().lower()
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
            actual = str(profile.get(fname, "") or "").strip().lower()
            matches = (actual == expected)
            if op == "=":
                if matches:
                    return True, ""
                return False, f"{fname} ist '{actual or '—'}' (braucht '{expected}')"
            if matches:
                return False, f"{fname} ist '{actual}' (darf nicht sein)"
            return True, ""
        except Exception as e:
            logger.debug("profile-field condition '%s' failed: %s", cond, e)
            return False, f"Bedingung nicht auswertbar: {cond}"

    # Unknown condition: pass with a warning
    logger.warning("Unbekannte Condition: '%s'", cond)
    return True, ""


def _check_alone(character_name: str, location_id: str) -> Tuple[bool, str]:
    """Check whether the character is alone at the location."""
    if not location_id:
        return True, ""
    try:
        from app.models.character import list_available_characters, get_character_current_location
        all_chars = list_available_characters()
        others_at_loc = [
            c for c in all_chars
            if c != character_name and get_character_current_location(c) == location_id
        ]
        if others_at_loc:
            return False, f"Nicht allein (auch hier: {', '.join(others_at_loc)})"
        return True, ""
    except Exception as e:
        logger.warning("alone-Check fehlgeschlagen: %s", e)
        return True, ""


def _check_present(character_name: str, target_name: str,
                   location_id: str, room_id: str = "") -> Tuple[bool, str]:
    """Check whether the target is in the same room, or at the same location
    when no room is known, for presence-dependent effects."""
    if not target_name:
        return False, "present: kein Zielname"
    try:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        loc = location_id or get_character_current_location(character_name)
        if not loc:
            return False, f"{target_name} nicht hier (kein Ort)"
        room = room_id or get_character_current_room(character_name)
        from app.core.room_entry import characters_in_room
        present = characters_in_room(loc, room)
        # Die Condition kommt kleingeschrieben an (_evaluate_single_condition),
        # Character-Namen sind es nicht — Vergleich ohne Gross-/Kleinschreibung.
        wanted = target_name.lower()
        if any((n or "").lower() == wanted for n in present):
            return True, ""
        return False, f"{target_name} nicht im selben Raum"
    except Exception as e:
        logger.warning("present-Check fehlgeschlagen: %s", e)
        return False, "present-Check Fehler"


def _check_mood(character_name: str, target_mood: str) -> Tuple[bool, str]:
    """Check whether the current mood matches the target."""
    try:
        from app.models.character import get_character_current_feeling
        current = (get_character_current_feeling(character_name) or "").lower()
        if target_mood.lower() in current or current in target_mood.lower():
            return True, ""
        return False, f"Mood-Voraussetzung: {target_mood} (aktuell: {current or 'unbekannt'})"
    except Exception:
        return True, ""


def _check_relationship(character_name: str, location_id: str,
    target_char: str, operator: str, threshold: int,
    field: str = "strength") -> Tuple[bool, str]:
    """Check a relationship condition against a named character or "any".

    Candidates must share the location. Strength uses 0-100; romantic
    tension is scaled from 0-1 to 0-100. A match sets _last_matched_partner.
    """
    global _last_matched_partner
    try:
        from app.models.character import list_available_characters, get_character_current_location
        from app.models.relationship import get_relationship

        label = "Romantik" if field == "romantic" else "Beziehung"

        # Select candidates
        if target_char.lower() == "any":
            all_chars = list_available_characters()
            candidates = [
                c for c in all_chars
                if c != character_name
                and get_character_current_location(c) == location_id
            ]
            if not candidates:
                return False, f"Kein anderer Character am gleichen Ort"
        else:
            # A named target must be at the same location.
            char_loc = get_character_current_location(target_char)
            if char_loc != location_id:
                return False, f"{target_char} ist nicht am gleichen Ort"
            candidates = [target_char]

        for cand in candidates:
            rel = get_relationship(character_name, cand)
            if not rel:
                continue
            if field == "romantic":
                value = int((rel.get("romantic_tension", 0)) * 100)
            else:
                value = int(rel.get("strength", 0))
            if _compare(value, operator, threshold):
                _last_matched_partner = cand
                return True, ""

        if target_char.lower() == "any":
            return False, f"Kein Character am Ort mit {label} {operator}{threshold}"
        return False, f"{label} zu {target_char}: Bedingung {operator}{threshold} nicht erfuellt"
    except Exception as e:
        logger.debug("Relationship check failed: %s", e)
        return True, ""


def _compare(value: int, operator: str, threshold: int) -> bool:
    if operator == ">":
        return value > threshold
    if operator == "<":
        return value < threshold
    if operator == "=":
        return value == threshold
    return False


# Last matched partner (for partner_activity)
_last_matched_partner: Optional[str] = None


# State conditions (prompt filters) must not fire on a stat the character
# does not have; rule conditions keep the historic "missing counts as 100".
_MISSING_STAT_FAILS: ContextVar[bool] = ContextVar("missing_stat_fails", default=False)


@contextmanager
def missing_stats_fail():
    """Within this block a comparison on a missing stat is not met."""
    token = _MISSING_STAT_FAILS.set(True)
    try:
        yield
    finally:
        _MISSING_STAT_FAILS.reset(token)


def _check_status_effect(character_name: str,
    stat_name: str, operator: str, threshold: int) -> Tuple[bool, str]:
    """Compare an effective stat; missing stats count as 100, or as not met
    inside ``missing_stats_fail()``."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name)
        from app.core.stat_boosts import effective_stat
        value = effective_stat(profile, stat_name)
        if value is None:
            if _MISSING_STAT_FAILS.get():
                return False, f"{stat_name}: not a value of this character"
            value = 100
        if operator == ">" and value > threshold:
            return True, ""
        if operator == "<" and value < threshold:
            return True, ""
        if operator == "=" and int(value) == threshold:
            return True, ""
        return False, f"{stat_name}: {int(value)} (requires {operator}{threshold})"
    except Exception:
        return True, ""


def _check_has_secret(character_name: str) -> Tuple[bool, str]:
    """Check whether the character has any non-record secrets."""
    try:
        from app.models.secrets import list_secrets, is_record
        secrets = list_secrets(character_name)
        if any(not is_record(s) for s in secrets):
            return True, ""
        return False, "Keine Geheimnisse vorhanden"
    except Exception:
        return True, ""


# ============================================================
# 7. HOURLY TIMER — decay/regeneration for all status values
# ============================================================

def validate_condition_references(condition: str) -> List[str]:
    """Validate filter/rule references using the same resolvers as runtime.

    Resolve item ids/names and character names without evaluating conditions.
    Return readable warnings for unresolved references.
    """
    warns: List[str] = []
    if not condition:
        return warns
    # Same splitting as evaluate_condition: OR -> AND -> optional NOT.
    for group in re.split(r"\s+OR\s+", condition, flags=re.IGNORECASE):
        for part in re.split(r"\s+AND\s+", group, flags=re.IGNORECASE):
            atom = part.strip()
            if atom.upper().startswith("NOT "):
                atom = atom[4:].strip()
            if not atom:
                continue
            m = re.match(r"has_item:(.+)", atom)
            if m:
                token = m.group(1).strip()
                try:
                    from app.models.inventory import resolve_item_id, get_item
                    if not get_item(resolve_item_id(token) or token):
                        warns.append(f"Item '{token}' existiert nicht")
                except Exception:
                    pass
                continue
            cm = re.match(r"(present|relationship|romantic):([A-Za-z0-9_]+)", atom)
            if cm:
                pred, name = cm.group(1), cm.group(2)
                if name.lower() == "any" and pred in ("relationship", "romantic"):
                    continue
                try:
                    from app.models.character import list_available_characters
                    if name not in (list_available_characters() or []):
                        warns.append(f"Character '{name}' existiert nicht ({pred}:)")
                except Exception:
                    pass
    return warns


# Conditions whose ``started_at`` could not be parsed — warned about once each.
_UNPARSABLE_CONDITION_STAMPS: set = set()


def cleanup_expired_conditions(character_name: str,
                               profile: Optional[Dict[str, Any]] = None) -> int:
    """Remove expired conditions (``duration_hours`` exceeded) from
    ``active_conditions``. Returns the number of removed conditions.

    Called both from ``apply_effects`` (item/danger) and periodically
    (periodic_jobs status_tick) — so effects with a cooldown reliably fade
    even without a new item/danger trigger.

    ``profile``: an already-loaded profile, used ONLY for the cheap "does this
    character carry any condition at all?" question. Almost every call lands on
    a character with an empty ``active_conditions`` list, and that answer needs
    neither a second read nor the profile lock (SIM-7). Once there IS something
    to look at, the profile is re-read UNDER the lock, because the save below
    rewrites the whole ``profile_json`` blob and a stale read would revert a
    concurrent writer's fields (place, journey, equip — DATA-3).
    """
    try:
        from app.core.keyed_lock import keyed_lock
        from app.models.character import get_character_profile, save_character_profile
        # Cheap, UNLOCKED pre-check: nothing to expire -> no lock, no write.
        _pre = profile if profile is not None else get_character_profile(character_name)
        if not ((_pre or {}).get("active_conditions") or []):
            return 0
        with keyed_lock("character_profile", character_name):
            _prof = get_character_profile(character_name)
            _conditions = (_prof or {}).get("active_conditions", []) or []
            if not _conditions:
                return 0
            _now = game_time()  # condition durations are in-world -> game clock
            _active = []
            for cond in _conditions:
                if not isinstance(cond, dict):
                    _active.append(cond)
                    continue
                duration_h = cond.get("duration_hours", 0)
                if duration_h:
                    try:
                        # ``started_at`` is a canonical GAME-time stamp.
                        started = GameTime.parse(cond["started_at"])
                        if (_now - started).hours > float(duration_h):
                            logger.info("Condition '%s' expired for %s",
                                        cond.get("name"), character_name)
                            continue  # expired — drop it
                    except (ValueError, KeyError, TypeError):
                        # Unusable stamp: KEEP the condition (unchanged behaviour —
                        # a broken stamp must not silently delete state). Logged
                        # once per condition so a bad stamp is findable without
                        # spamming the periodic tick.
                        _warn_key = (character_name, str(cond.get("name") or ""),
                                     str(cond.get("started_at") or ""))
                        if _warn_key not in _UNPARSABLE_CONDITION_STAMPS:
                            _UNPARSABLE_CONDITION_STAMPS.add(_warn_key)
                            logger.warning(
                                "Condition '%s' of %s has an unusable started_at "
                                "(%r) — kept, cannot expire",
                                cond.get("name"), character_name,
                                cond.get("started_at"))
                _active.append(cond)
            removed = len(_conditions) - len(_active)
            if removed:
                _prof["active_conditions"] = _active
                save_character_profile(character_name, _prof)
            return removed
    except Exception as e:
        logger.debug("Condition cleanup fehlgeschlagen fuer %s: %s", character_name, e)
        return 0


def apply_effects(character_name: str,
    effects: Dict[str, Any],
    source: str = "") -> Dict[str, Any]:
    """Apply immediate mood influence and generic ``*_change`` stat deltas.

    Stat values are clamped to 0-100 and stored through the character profile.
    The caller handles condition application and duration. Returns applied
    changes keyed by stat, each containing ``old`` and ``new`` values.
    """
    if not effects or not isinstance(effects, dict):
        return {}

    log_prefix = f"[{source}] " if source else ""

    # Apply mood influence immediately.
    mood = effects.get("mood_influence")
    if mood:
        try:
            from app.models.character import save_character_current_feeling
            save_character_current_feeling(character_name, mood)
            logger.info("%sMood gesetzt: %s -> %s", log_prefix, character_name, mood)
        except Exception as e:
            logger.warning("Mood setzen fehlgeschlagen: %s", e)

    # Apply generic status effects for each key ending in "_change".
    from app.models.character import get_character_profile, save_character_profile
    changes: Dict[str, Any] = {}
    try:
        from app.core.keyed_lock import keyed_lock
        # Read AND write under the per-character profile lock (DATA-3). The
        # deltas below are a read-modify-write of ``status_effects`` AND the
        # save rewrites the whole profile_json blob — two lost updates in one.
        # History and sync run only after releasing the profile lock.
        with keyed_lock("character_profile", character_name):
            profile = get_character_profile(character_name)
            status = profile.get("status_effects", {}) or {}
            changed = False

            for key, delta in effects.items():
                if not key.endswith("_change") or not delta:
                    continue
                stat_key = key[:-7]  # Strip the effect suffix.
                current = status.get(stat_key, 100)
                new_val = max(0, min(100, current + int(delta)))
                if new_val != current:
                    status[stat_key] = new_val
                    changes[stat_key] = {"old": current, "new": new_val}
                    changed = True
                    logger.info("%s%s: %s %d -> %d", log_prefix,
                                character_name, stat_key, current, new_val)

            if changed:
                profile["status_effects"] = status
                if not save_character_profile(character_name, profile):
                    return {}
        if changes:
            from app.models.character import record_state_change
            from app.core import sync_topics
            record_state_change(character_name, "effects", source,
                                metadata={"changes": changes, "source": source})
            sync_topics.changed_at(character_name, topics=("presence", "self"))
    except Exception as e:
        logger.warning("Applying effects failed: %s", e)

    return changes


# key: "character_name" -> GameTime of the last tick (RAM only, never persisted)
_LAST_HOURLY_TICK: Dict[str, GameTime] = {}
# Fractional pull remainder, RAM only, keyed by character and stat.
_HOURLY_PULL_CARRY: Dict[tuple[str, str], float] = {}

def apply_hourly_status_tick(character_name: str):
    """Apply rules once per game hour, anchoring the first sight to now.

    Fixed and matching conditional rates add to a rounded rest-value pull.
    Fractional pull remainders survive subsequent ticks in RAM only.
    """
    tick_key = character_name
    # Hourly = one GAME hour (factor >1 -> decay ticks faster in real time).
    now = game_time()

    # Check whether a game hour has passed since the last tick. The gate comes
    # FIRST: on 59 of 60 ticks it ends the call before any profile is read.
    last_tick = _LAST_HOURLY_TICK.get(tick_key)
    if last_tick is None:
        # First sight (fresh process): anchor, charge nothing.
        _LAST_HOURLY_TICK[tick_key] = now
        return
    delta = (now - last_tick).seconds
    if delta < 0:
        # Game clock was set backwards -> re-anchor to now instead of
        # standing still until the clock has caught up (same treatment as
        # random_events.check_and_generate and the scheduler's game anchor).
        _LAST_HOURLY_TICK[tick_key] = now
        return
    if delta < 3600:
        return  # less than an hour ago

    # Feature gate: status_effects off -> no hourly tick
    try:
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "status_effects_enabled"):
            # Re-anchor anyway: a character that switches the feature on must
            # not be charged for the hours it spent switched off.
            _LAST_HOURLY_TICK[tick_key] = now
            return
    except Exception:
        pass

    _LAST_HOURLY_TICK[tick_key] = now

    try:
        from app.core.keyed_lock import keyed_lock
        from app.core.stat_rules import rules_for_character, round_half_away
        from app.models.character import (
            get_character_profile, get_character_config, save_character_profile,
            get_character_current_location, get_character_current_room,
            record_state_change,
        )
        from app.core import sync_topics

        # Resolve conditions before the profile lock: state expressions may
        # acquire other locks, including the places lock (which comes first).
        profile = get_character_profile(character_name)
        config = get_character_config(character_name)
        rules = rules_for_character(character_name, profile=profile, config=config)
        location = get_character_current_location(character_name)
        room = get_character_current_room(character_name)
        from app.models.world import get_location_by_id, get_room_by_id
        place = get_location_by_id(location) if location else None
        room_data = get_room_by_id(place, room) if place and room else None
        rate_parts = {}
        for key, rule in rules.items():
            parts = []
            if rule["per_hour"]:
                parts.append({"label": "Base", "delta": rule["per_hour"]})
            for rate in rule["rates"]:
                condition = rate["condition"]
                if evaluate_condition(condition, character_name, location, room)[0]:
                    parts.append({"label": rate["label"] or condition,
                                  "delta": rate["per_hour"]})
            for source, prefix in ((place, "Place"), (room_data, "Room")):
                if source:
                    for rate in source.get("stat_rates", []):
                        if rate.get("stat") == key:
                            parts.append({"label": f"{prefix}: {source.get('name', '')}",
                                          "delta": rate["per_hour"]})
            rate_parts[key] = parts

        changes = {}
        history_parts = {}
        pending_carry = {}
        with keyed_lock("character_profile", character_name):
            # Re-read for the actual RMW so concurrent effects are retained.
            profile = get_character_profile(character_name)
            status = profile.get("status_effects", {}) or {}
            for key, rule in rules.items():
                if key not in status:
                    continue
                old = status[key]
                parts = list(rate_parts[key])
                carry_key = (character_name, key)
                if rule["baseline"] is not None and rule["pull"]:
                    exact = (_HOURLY_PULL_CARRY.get(carry_key, 0.0)
                             + (rule["baseline"] - old) * rule["pull"])
                    pull_delta = round_half_away(exact)
                    pending_carry[carry_key] = exact - pull_delta
                    parts.append({"label": "Rest value", "delta": pull_delta})
                else:
                    pending_carry[carry_key] = 0.0
                new = max(0, min(100, old + sum(part["delta"] for part in parts)))
                if new != old:
                    status[key] = new
                    changes[key] = {"old": old, "new": new}
                    history_parts[key] = parts
            if changes:
                profile["status_effects"] = status
                if not save_character_profile(character_name, profile):
                    return
            # A rounded zero still accumulates its fractional remainder.
            _HOURLY_PULL_CARRY.update(pending_carry)

        if changes:
            record_state_change(character_name, "effects", "hourly", metadata={
                "changes": changes, "source": "hourly", "parts": history_parts})
            sync_topics.changed_at(character_name, topics=("presence", "self"))
    except Exception as e:
        logger.warning("Hourly status tick failed for %s: %s", character_name, e)

    # Clean up expired conditions.
    cleanup_expired_conditions(character_name)
