"""Activity Engine - Condition-Auswertung, Visibility, Cooldowns, Duration, Triggers.

Zentrale Logik fuer erweiterte Spezial-Aktivitaeten.
Wird von set_activity_skill.py und chat.py genutzt.
"""
import re
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now, utc_now_iso
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
    """Wertet eine Condition-String aus.

    Returns:
        (passed: bool, reason: str) - reason ist leer wenn passed=True
    """
    global _last_matched_partner
    _last_matched_partner = None

    if not condition or not condition.strip():
        return True, ""

    # OR-verknuepfte Gruppen zuerst splitten, dann AND innerhalb jeder Gruppe
    # Beispiel: "alone AND night OR alone AND day" → Gruppe1: alone AND night, Gruppe2: alone AND day
    or_groups = [g.strip() for g in re.split(r"\s+OR\s+", condition, flags=re.IGNORECASE)]

    last_reason = ""
    for group in or_groups:
        # AND-verknuepfte Bedingungen innerhalb einer Gruppe
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

    # Keine OR-Gruppe hat bestanden
    return False, last_reason


def _evaluate_single_condition(
    condition: str, character_name: str,
    location_id: str, room_id: str = "") -> Tuple[bool, str]:
    """Wertet eine einzelne Condition aus."""
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
    """Wertet eine einzelne Condition aus (ohne NOT-Handling)."""

    # --- always / true: bedingungslos wahr (z.B. fuer eine harte Block-Regel,
    # die einen Ort generell unbetretbar macht). ---
    if cond in ("always", "true"):
        return True, ""

    # --- alone ---
    if cond == "alone":
        return _check_alone(character_name, location_id)

    # --- night / day mit optionalem Minuten-Offset auf den Startzeitpunkt ---
    # Beispiele:
    #   night       — 18:00 bis 06:00
    #   night-30    — Start 30 Min FRUEHER: 17:30 bis 06:00
    #   night+30    — Start 30 Min SPAETER: 18:30 bis 06:00
    #   day         — 06:00 bis 18:00
    #   day-30      — 05:30 bis 18:00
    #   day+30      — 06:30 bis 18:00
    # Der Offset verschiebt nur den START — das Ende bleibt 06:00 bzw. 18:00.
    # Negativ (-) = Vorbereitungsfenster, positiv (+) = Verzoegerung.
    td_match = re.match(r"^(night|day)(?:([+-])(\d+))?$", cond)
    if td_match:
        base = td_match.group(1)
        sign = td_match.group(2) or ""
        offset_min = int(td_match.group(3) or 0)
        if sign == "+":
            shift = offset_min        # Start spaeter
        else:
            shift = -offset_min       # Start frueher (default fuer "-")
        now = utc_now()
        now_min = now.hour * 60 + now.minute
        lbl_offset = f"{sign}{offset_min}" if offset_min else ""
        if base == "night":
            start_min = 18 * 60 + shift
            end_min = 6 * 60
            # Normalisieren in [0, 1440)
            start_min %= 24 * 60
            # Wrap-Around: night liegt typischerweise um Mitternacht herum.
            if start_min < end_min:
                # Start liegt VOR end_min (z.B. shift gross negativ +
                # ueberlauf nicht passiert) — ungewoehnlich aber moeglich
                in_window = start_min <= now_min < end_min
            else:
                # Normaler Fall: Fenster spannt ueber Mitternacht
                in_window = (now_min >= start_min) or (now_min < end_min)
            if in_window:
                return True, ""
            return False, f"Nur nachts verfuegbar (night{lbl_offset})"
        else:  # day
            start_min = 6 * 60 + shift
            end_min = 18 * 60
            start_min_norm = start_min % (24 * 60)
            if start_min < 0:
                # Stark negativer Offset zieht Day-Beginn vor Mitternacht
                in_window = (now_min >= start_min_norm) or (now_min < end_min)
            elif start_min_norm >= end_min:
                # Stark positiver Offset oder ueberlauf — Fenster leer
                in_window = False
            else:
                in_window = start_min_norm <= now_min < end_min
            if in_window:
                return True, ""
            return False, f"Nur tagsueber verfuegbar (day{lbl_offset})"

    # --- present:Name --- (Ziel-Character im selben Raum/Ort)
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

    # --- {stat}>N / {stat}<N / {stat}=N — generisch fuer beliebige im Template
    # definierten Stat-Felder (store=status_effects). Reihenfolge: NACH den
    # spezifischen Praefixen (mood:, relationship:, etc.), sonst wuerde dies
    # "condition:drunk" o.ae. fehl-matchen.
    stat_match = re.match(r"([a-z_]+)([><=])(\d+)$", cond)
    if stat_match:
        stat_name = stat_match.group(1)
        # Reservierte Namen ausschliessen (haben eigene Handler oben)
        if stat_name not in ("mood", "relationship", "romantic", "has_item", "condition",
                             "event_active", "has_secret", "alone", "night", "day", "npc_present",
                             "current_activity"):
            operator = stat_match.group(2)
            threshold = int(stat_match.group(3))
            return _check_status_effect(character_name, stat_name, operator, threshold)

    # --- State-Flags: is_sleeping / is_wet / is_intimate (Boolean) ---
    # B1: regelbasiertes Bedingen auf den orthogonalen Zustands-Flags — der Flag
    # ist die Autoritaet (nicht der Activity-String). "is_sleeping" → True wenn
    # gesetzt; "NOT is_sleeping" via NOT-Prefix.
    flag_m = re.match(r"(is_sleeping|is_wet|is_intimate)$", cond)
    if flag_m:
        fname = flag_m.group(1)
        try:
            from app.models.character import get_state_flags
            if bool(get_state_flags(character_name).get(fname)):
                return True, ""
            return False, f"{fname} ist nicht gesetzt"
        except Exception as e:
            logger.debug("state-flag-Check fehlgeschlagen: %s", e)
            return False, f"{fname}-Check fehlgeschlagen"

    # --- current_activity:X (freie Pose des Characters, Substring-Match) ---
    # Activity-Library entfernt: Match gegen get_effective_activity (pose_intent
    # bzw. "Sleeping" via is_sleeping-Flag), per Substring in beide Richtungen.
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

    # --- schedule:X (aktueller Tagesablauf-Slot) ---
    # Beispiel: "schedule:sleeping" matched wenn der aktuelle Stunden-Slot
    # in daily_schedule.slots als sleep-Slot markiert ist (sleep=True oder
    # activity="__sleep__" o.ae.). "schedule:awake" matched die Negation.
    sched_match = re.match(r"schedule:(.+)", cond)
    if sched_match:
        target = sched_match.group(1).strip().lower()
        try:
            from app.models.character import get_character_daily_schedule
            schedule = get_character_daily_schedule(character_name) or {}
            if not schedule.get("enabled", False):
                # Kein aktiver Schedule — schedule-Bedingungen matchen nicht
                # (weder sleeping noch awake werden erzwungen).
                return False, "Tagesablauf nicht aktiv"
            current_hour = utc_now().hour
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
            # Sonst: target gegen slot.activity matchen (z.B. "schedule:Working")
            slot_act = (slot.get("activity") if slot else "") or ""
            if slot_act.lower() == target:
                return True, ""
            return False, f"Schedule sagt nicht '{target}' (ist: '{slot_act}')"
        except Exception as e:
            logger.debug("schedule-condition Fehler: %s", e)
            return False, f"Schedule-Bedingung nicht auswertbar: {target}"

    # --- condition:X (active_conditions im Profil) ---
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

    # --- has_item:<id|name> --- (Character-Inventar)
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

    # --- room_has_item:<id|name> --- (Ziel-Raum enthaelt Item)
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
                # Name-Match fallback
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
        # Placeholder fuer NPC-System
        return True, ""

    # --- event_active:category ---
    event_match = re.match(r"event_active:(.+)", cond)
    if event_match:
        # Placeholder fuer Event-Kategorien
        return True, ""

    # Unbekannte Condition: durchlassen mit Warnung
    logger.warning("Unbekannte Condition: '%s'", cond)
    return True, ""


def _check_alone(character_name: str, location_id: str) -> Tuple[bool, str]:
    """Prueft ob der Character allein an der Location ist."""
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
    """Prueft ob ``target_name`` im selben Raum wie ``character_name`` ist
    (bzw. am selben Ort, wenn kein Raum bekannt). Fuer Presence-gekoppelte
    Effekte: ``condition:charmed AND present:Lirien``."""
    if not target_name:
        return False, "present: kein Zielname"
    try:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        loc = location_id or get_character_current_location(character_name)
        if not loc:
            return False, f"{target_name} nicht hier (kein Ort)"
        room = room_id or get_character_current_room(character_name)
        from app.core.room_entry import _list_characters_in_room
        present = _list_characters_in_room(loc, room)
        if target_name in present:
            return True, ""
        return False, f"{target_name} nicht im selben Raum"
    except Exception as e:
        logger.warning("present-Check fehlgeschlagen: %s", e)
        return False, "present-Check Fehler"


def _check_mood(character_name: str, target_mood: str) -> Tuple[bool, str]:
    """Prueft ob der aktuelle Mood dem Ziel entspricht."""
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
    """Prueft eine Beziehungs-Bedingung.

    - target_char kann ein Name oder "any" sein
    - Prueft ob der Ziel-Character am gleichen Ort ist
    - field: "strength" (Freundschaft 0-100) oder "romantic" (romantic_tension 0-100, intern 0-1)
    - Bei Erfolg wird der gematchte Partner-Name in _last_matched_partner gespeichert
    """
    global _last_matched_partner
    try:
        from app.models.character import list_available_characters, get_character_current_location
        from app.models.relationship import get_relationship

        label = "Romantik" if field == "romantic" else "Beziehung"

        # Kandidaten bestimmen
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
            # Konkreter Name: muss am gleichen Ort sein
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


# Letzter gematchter Partner (fuer partner_activity)
_last_matched_partner: Optional[str] = None


def _check_status_effect(character_name: str,
    stat_name: str, operator: str, threshold: int) -> Tuple[bool, str]:
    """Prueft einen Status-Wert generisch gegen profile.status_effects.

    Fehlt der Stat-Wert komplett, wird 100 angenommen (Character startet voll).
    """
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name)
        status = profile.get("status_effects", {})
        value = status.get(stat_name, 100)
        if operator == ">" and value > threshold:
            return True, ""
        if operator == "<" and value < threshold:
            return True, ""
        if operator == "=" and int(value) == threshold:
            return True, ""
        return False, f"{stat_name}: {int(value)} (braucht {operator}{threshold})"
    except Exception:
        return True, ""


def _check_has_secret(character_name: str) -> Tuple[bool, str]:
    """Prueft ob der Character Geheimnisse hat."""
    try:
        from app.models.secrets import list_secrets
        secrets = list_secrets(character_name)
        if secrets:
            return True, ""
        return False, "Keine Geheimnisse vorhanden"
    except Exception:
        return True, ""


# ============================================================
# 2. VISIBILITY RESOLVER
# ============================================================

def is_character_interruptible(character_name: str) -> Tuple[bool, str]:
    """Pose-Modell: keine ``interruptible``-Flags mehr (Activity-Library
    entfernt). Ein Character ist immer unterbrechbar.

    Returns (True, "") — Signatur fuer Aufrufer (talk_to/chat/partner_consent)
    bleibt erhalten.
    """
    return True, ""


# ============================================================
# 7. STUNDENTIMER — Decay/Regen fuer alle Status-Werte
# ============================================================

def cleanup_expired_conditions(character_name: str) -> int:
    """Entfernt abgelaufene Conditions (``duration_hours`` ueberschritten) aus
    ``active_conditions``. Liefert die Anzahl entfernter Conditions.

    Wird sowohl aus ``apply_effects`` (Item/Danger) als auch periodisch
    (periodic_jobs status_tick) aufgerufen — so klingen Effekte mit Abklingzeit
    auch ohne neuen Item-/Danger-Trigger zuverlaessig ab.
    """
    try:
        from app.models.character import get_character_profile, save_character_profile
        _prof = get_character_profile(character_name)
        _conditions = (_prof or {}).get("active_conditions", []) or []
        if not _conditions:
            return 0
        _now = utc_now()
        _active = []
        for cond in _conditions:
            if not isinstance(cond, dict):
                _active.append(cond)
                continue
            duration_h = cond.get("duration_hours", 0)
            if duration_h:
                try:
                    started = parse_iso(cond["started_at"])
                    if (_now - started).total_seconds() > float(duration_h) * 3600:
                        logger.info("Condition '%s' abgelaufen fuer %s", cond.get("name"), character_name)
                        continue  # Abgelaufen — nicht behalten
                except (ValueError, KeyError, TypeError):
                    pass
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
    """Zentrale Funktion: Wendet ein Effects-Dict auf einen Character an.

    Verarbeitet ``mood_influence`` (sofort) + alle ``*_change``-Keys als
    Stat-Deltas (geclamped 0-100). ``apply_condition``/``condition_duration_hours``
    werden hier NICHT verarbeitet — der Aufrufer (z.B. apply_item_effects) macht
    das. Status-Werte liegen in ``character_state.meta.status_effects`` und werden
    transparent ueber get_/save_character_profile gelesen/geschrieben.

    War in ff1f7d1 (Activity-Library-Entfernung) versehentlich geloescht worden,
    obwohl apply_item_effects + danger_system sie noch importieren — der
    ImportError wurde im try/except verschluckt, sodass Item-/Spell-Effekte und
    Danger-Drain still NICHTS bewirkten.

    Returns dict with applied changes: {"stamina": {"old": 80, "new": 65}, ...}
    """
    if not effects or not isinstance(effects, dict):
        return {}

    log_prefix = f"[{source}] " if source else ""

    # Mood-Einfluss (sofort wirksam)
    mood = effects.get("mood_influence")
    if mood:
        try:
            from app.models.character import save_character_current_feeling
            save_character_current_feeling(character_name, mood)
            logger.info("%sMood gesetzt: %s -> %s", log_prefix, character_name, mood)
        except Exception as e:
            logger.warning("Mood setzen fehlgeschlagen: %s", e)

    # Generische Status-Effects: Jeder Key mit "_change" Suffix wird angewendet
    from app.models.character import get_character_profile, save_character_profile
    changes: Dict[str, Any] = {}
    try:
        profile = get_character_profile(character_name)
        status = profile.get("status_effects", {}) or {}
        changed = False

        for key, delta in effects.items():
            if not key.endswith("_change") or not delta:
                continue
            stat_key = key[:-7]  # "stamina_change" -> "stamina"
            current = status.get(stat_key, 100)
            new_val = max(0, min(100, current + int(delta)))
            if new_val != current:
                status[stat_key] = new_val
                changes[stat_key] = {"old": current, "new": new_val}
                changed = True
                logger.info("%s%s: %s %d -> %d", log_prefix, character_name, stat_key, current, new_val)

        if changed:
            profile["status_effects"] = status
            save_character_profile(character_name, profile)
    except Exception as e:
        logger.warning("Effects anwenden fehlgeschlagen: %s", e)

    return changes


_LAST_HOURLY_TICK: Dict[str, str] = {}  # key: "character_name" -> ISO timestamp

def apply_hourly_status_tick(character_name: str):
    """Wendet stuendliche Veraenderung auf alle Status-Werte an.

    Liest bar_hourly aus dem Template pro Trait-Feld.
    Positiv = steigt pro Stunde, negativ = sinkt pro Stunde, 0 = keine Aenderung.
    Character-Config kann den Template-Wert ueberschreiben via {stat_key}_hourly.

    Wird vom ThoughtLoop aufgerufen (jede 60s), fuehrt aber nur einmal pro
    Stunde pro Character die Aenderung durch.
    """
    # Feature-Gate: status_effects aus -> kein Hourly-Tick
    try:
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "status_effects_enabled"):
            return
    except Exception:
        pass

    tick_key = character_name
    now = utc_now()

    # Pruefen ob eine Stunde seit dem letzten Tick vergangen ist
    last_tick_iso = _LAST_HOURLY_TICK.get(tick_key)
    if last_tick_iso:
        try:
            from datetime import timedelta
            last_tick = parse_iso(last_tick_iso)
            if (now - last_tick).total_seconds() < 3600:
                return  # Noch keine Stunde her
        except (ValueError, TypeError):
            pass

    _LAST_HOURLY_TICK[tick_key] = now.isoformat()

    try:
        from app.models.character import get_character_profile, get_character_config, save_character_profile
        from app.models.character_template import get_template

        profile = get_character_profile(character_name)
        config = get_character_config(character_name)
        status = profile.get("status_effects", {})

        if not status:
            return  # Keine Status-Werte initialisiert

        # Template laden fuer bar_hourly Werte
        template_name = profile.get("template", "human-default")
        template = get_template(template_name)
        if not template:
            return

        # Pro Stat-Feld die Stunden-Rate sammeln: Wach (``bar_hourly``) UND
        # optional Schlaf (``bar_hourly_sleeping``). Letzteres ERSETZT die mit den
        # Activities abgeschaffte aktivitaets-basierte Schlaf-Auffuellung — jetzt
        # ZUSTANDS-getrieben (is_sleeping), von Activities entkoppelt, aber weiter
        # rein TEMPLATE-getrieben (kein Hardcoding). Stats mit nur einem Schlaf-Wert
        # (bar_hourly=0) werden ebenfalls erfasst.
        stat_rates = {}  # stat_key -> (awake, sleeping_or_None)
        for section in template.get("sections", []):
            for field in section.get("fields", []):
                if field.get("store") != "status_effects":
                    continue
                stat_key = field.get("key", "")
                if not stat_key:
                    continue
                awake = field.get("bar_hourly", 0)
                sleeping = field.get("bar_hourly_sleeping", None)
                if awake or sleeping is not None:
                    stat_rates[stat_key] = (awake, sleeping)

        if not stat_rates:
            return

        # Ruhephase = schlafend ODER offmap/abwesend. Ein gesteuerter Avatar wird
        # vom Spieler nie schlafen gelegt — die Erholung passiert, waehrend niemand
        # ihn steuert und er von der Karte verschwunden ist (current_location leer).
        # Solange zaehlt die Zeit wie Schlaf, damit Energie sich erholt statt zu
        # verfallen. Template-getrieben ueber bar_hourly_sleeping (kein Hardcoding).
        from app.models.character import get_character_current_location
        is_sleeping = bool(profile.get("is_sleeping"))
        is_offmap = not (get_character_current_location(character_name) or "").strip()
        resting = is_sleeping or is_offmap
        changed = False
        for stat_key, (awake, sleeping) in stat_rates.items():
            if stat_key not in status:
                continue

            # Im Ruhezustand den Schlaf-Wert nehmen (falls definiert), sonst Wach-Wert.
            use_sleep = resting and sleeping is not None
            base = sleeping if use_sleep else awake
            # Character-Override: config.{stat}_hourly[_sleeping] ueberschreibt Template.
            override_key = f"{stat_key}_hourly_sleeping" if use_sleep else f"{stat_key}_hourly"
            try:
                hourly = int(config.get(override_key, base))
            except (ValueError, TypeError):
                hourly = base

            if not hourly:
                continue

            current = status[stat_key]
            new_val = max(0, min(100, current + hourly))
            if new_val != current:
                status[stat_key] = new_val
                changed = True
                logger.debug("Hourly tick %s: %s %d -> %d (%+d/h%s)",
                             character_name, stat_key, current, new_val, hourly,
                             ", sleeping" if use_sleep else "")

        if changed:
            profile["status_effects"] = status
            save_character_profile(character_name, profile)
            logger.info("Hourly status tick fuer %s angewendet", character_name)

        # (Force-Rules laufen jetzt zentral im world_admin_tick
        # → periodic_jobs._sub_force_rules; Activity-Effekte gibt es nicht
        # mehr — Activity-Library entfernt. Hier bleibt nur der bar_hourly-
        # Drift oben + der Danger-Drain unten.)
    except Exception as e:
        logger.warning("Hourly status tick fehlgeschlagen fuer %s: %s", character_name, e)

    # Location-basierter Danger-Drain (gefaehrliche Orte kosten Stamina)
    try:
        from app.models.character import get_character_current_location
        from app.models.world import get_location_by_id
        from app.core.danger_system import apply_danger_drain
        loc_id = get_character_current_location(character_name)
        if loc_id:
            loc_data = get_location_by_id(loc_id)
            if loc_data:
                drain_changes = apply_danger_drain(character_name, loc_data)
                if drain_changes:
                    from app.models.character import _record_state_change
                    _record_state_change(character_name, "effects",
                                         f"danger:{loc_data.get('name', '?')}",
                                         metadata={"changes": drain_changes, "hourly": True})
    except Exception as e:
        logger.debug("Hourly danger drain fehlgeschlagen: %s", e)

    # Abgelaufene Conditions aufraeumen (drunk, exhausted, charmed, etc.)
    cleanup_expired_conditions(character_name)
