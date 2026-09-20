"""Danger System — location hazards, access checks, condition reminder.

Locations may carry these fields:
- danger_level (0-5): general hazard level
- hazards: possible hazard events
"""
from app.core.game_time import GameDuration, GameTime
from app.core.timeutils import game_time
from typing import Any, Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger("danger_system")


# ============================================================
# 1. LOCATION DANGER HELPERS
# ============================================================

def get_danger_level(location: Dict[str, Any]) -> int:
    """Gibt danger_level einer Location zurueck (0-5, default 0)."""
    try:
        return max(0, min(5, int(location.get("danger_level", 0))))
    except (ValueError, TypeError):
        return 0


def get_hazards(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Gibt hazards-Liste einer Location zurueck."""
    return location.get("hazards") or []


# ============================================================
# 2. ZUGANGS-CHECK (fuer SetLocationSkill)
# ============================================================

def check_location_access(character_name: str,
    location: Dict[str, Any]) -> Tuple[bool, str]:
    """Prueft ob ein Character eine Location betreten darf.

    Delegiert an die Rules Engine (app/models/rules.py).
    Alte restrictions wurden entfernt — alles laeuft ueber Rules.
    """
    from app.models.rules import check_access
    loc_id = location.get("id", "")
    return check_access(character_name, loc_id)


# ============================================================
# 3. PROMPT-MODIFIER (Status-Effekte im System-Prompt)
# ============================================================

def build_condition_reminder(character_name: str) -> str:
    """Kurzer Reminder fuer aktive Conditions — fuer Ende des System-Prompts.

    Wird spaet im Prompt platziert, damit das LLM es waehrend der Generierung
    staerker beruecksichtigt als die frueh platzierte Status-Sektion.
    """
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        active = profile.get("active_conditions", []) or []
        if not active:
            return ""

        now_game = game_time()   # condition lifetimes are WORLD durations
        names: List[str] = []
        for cond in active:
            duration_h = cond.get("duration_hours", 0) or 0
            if duration_h:
                try:
                    started = GameTime.parse(cond["started_at"])
                    if (now_game - started) > GameDuration.of(hours=duration_h):
                        continue
                except (ValueError, KeyError, TypeError):
                    pass
            name = (cond.get("name") or "").strip()
            if name:
                names.append(name)
        if not names:
            return ""
        names_str = ", ".join(names).upper()
        return (f"\nREMINDER — YOU ARE {names_str}. Your next response MUST clearly show this "
                f"state. Do not default to normal/sober behavior.")
    except Exception:
        return ""
