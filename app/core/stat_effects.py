"""Stat effects from events & ongoing activities (plan-activity-stat-effects.md).

Shared evaluator with three producers:
- chat beats: extraction_chat_state (its template now allows big swings at
  turning points) — unchanged path, only the stat-list builder lives here.
- EndIntimate hook (on_intimacy_end): ONE "significant event" round right
  after intimacy ends — the post-climax drop.
- activity tick (maybe_activity_tick): agent-loop evaluation of the RUNNING
  activity; the LLM returns PER-HOUR deltas, scaled to the elapsed time.

Stats stay fully template-driven (store=status_effects incl. per-value
hint) — this code knows NO stat name.
"""
import json
import re
import threading
import time
from typing import Any, Dict, Tuple

from app.core.log import get_logger

logger = get_logger("stat_effects")

# Activity tick: at most one evaluation per character per interval; a long
# pause is capped so a stale baseline cannot produce absurd jumps.
_TICK_MIN = 30.0
_TICK_CAP_MIN = 180.0
_last_tick: Dict[str, float] = {}
_tick_lock = threading.Lock()


def build_stat_list(character_name: str) -> Tuple[bool, str]:
    """Bullet list of the character's status values (+hint, current value)
    from the character template — the single source for every evaluator.
    Returns (enabled, list); disabled feature or no values -> (False, '')."""
    try:
        from app.models.character_template import is_feature_enabled, get_template
        from app.models.character import get_character_profile
        if not is_feature_enabled(character_name, "status_effects_enabled"):
            return False, ""
        prof = get_character_profile(character_name) or {}
        cur = prof.get("status_effects", {}) or {}
        tmpl = get_template(prof.get("template", "")) if prof.get("template") else None
        if not tmpl or not cur:
            return False, ""
        lines = []
        for section in tmpl.get("sections", []):
            for fld in section.get("fields", []):
                if fld.get("store") != "status_effects":
                    continue
                k = fld.get("key")
                if not k or k not in cur:
                    continue
                hint = (fld.get("hint") or "").strip()
                line = f"- {k}, currently {cur.get(k)}/100"
                if hint:
                    line += f" — {hint}"
                lines.append(line)
        if not lines:
            return False, ""
        return True, "\n".join(lines)
    except Exception as e:
        logger.debug("stat list failed for %s: %s", character_name, e)
        return False, ""


def evaluate_stat_effects(character_name: str, situation_text: str, *,
                          source: str, per_hour: bool = False,
                          elapsed_min: float = 0.0) -> Dict[str, int]:
    """One LLM round (tasks/stat_effects.md) -> deltas applied via
    adjust_status_effects. per_hour scales the result to elapsed_min."""
    enabled, stat_list = build_stat_list(character_name)
    if not enabled:
        return {}
    try:
        from app.core.prompt_templates import render_task
        from app.core.llm_router import llm_call
        sys_p, user_p = render_task(
            "stat_effects", target_name=character_name,
            stat_list=stat_list, per_hour=per_hour,
            situation_text=situation_text)
        # Routing via the established extraction task (tool model) — the
        # template is our own (same pattern as scene_photo/image_prompt).
        resp = llm_call(task="extraction_chat_state", system_prompt=sys_p,
                        user_prompt=user_p, agent_name=character_name)
        raw = (getattr(resp, "content", "") or "").strip()
    except Exception as e:
        logger.debug("stat evaluation failed for %s: %s", character_name, e)
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    stats = data.get("stats") if isinstance(data, dict) else None
    if not isinstance(stats, dict) or not stats:
        return {}
    scale = min(elapsed_min, _TICK_CAP_MIN) / 60.0 if per_hour else 1.0
    deltas: Dict[str, int] = {}
    for k, v in stats.items():
        try:
            d = int(round(float(v) * scale))
        except (TypeError, ValueError):
            continue
        if d:
            deltas[str(k)] = d
    if not deltas:
        return {}
    try:
        from app.models.character import adjust_status_effects
        adjust_status_effects(character_name, deltas, source=source)
        logger.info("stat effects [%s] %s: %s", source, character_name, deltas)
        return deltas
    except Exception as e:
        logger.warning("stat apply failed for %s: %s", character_name, e)
        return {}


def on_intimacy_end(character_name: str, partner: str = "") -> None:
    """EndIntimate hook: one 'significant event' round for both
    participants — the big post-climax swing is allowed; direction/size
    semantics live in each value's template hint. Background thread, never
    blocks the skill."""
    names = [n for n in dict.fromkeys([character_name, partner]) if n]

    def _run():
        for n in names:
            other = next((o for o in names if o != n), "")
            if other:
                txt = (f"The intimate encounter between {n} and {other} just "
                       f"ended after reaching its climax. Judge the immediate "
                       f"aftermath for {n}: release, satisfaction, spent energy.")
            else:
                txt = (f"{n}'s intimate moment just ended after reaching its "
                       f"climax. Judge the immediate aftermath: release, "
                       f"satisfaction, spent energy.")
            evaluate_stat_effects(n, txt, source="intimate_end")

    threading.Thread(target=_run, daemon=True, name="intimacy-end-stats").start()


def maybe_activity_tick(character_name: str) -> None:
    """Agent-loop hook: evaluates the RUNNING activity at most every
    _TICK_MIN minutes — "X has been doing <activity> for N minutes" →
    per-hour deltas scaled to the elapsed interval. Skips empty activity
    and sleeping characters (sleep recovery is its own path). The interval
    gate is cheap and synchronous; the LLM round runs in a background
    thread so the loop turn is never blocked."""
    now = time.time()
    with _tick_lock:
        last = _last_tick.get(character_name)
        if last is None:
            # Baseline after start/restart — no retroactive effects.
            _last_tick[character_name] = now
            return
        elapsed_min = (now - last) / 60.0
        if elapsed_min < _TICK_MIN:
            return
        _last_tick[character_name] = now
    try:
        from app.models.character import (get_effective_activity,
                                          is_character_sleeping)
        if is_character_sleeping(character_name):
            return
        activity = (get_effective_activity(character_name) or "").strip()
    except Exception:
        return
    if not activity or activity.lower() == "sleeping":
        return
    minutes = int(min(elapsed_min, _TICK_CAP_MIN))
    txt = (f"{character_name} has been doing this for about {minutes} "
           f"minutes: {activity}")
    threading.Thread(
        target=evaluate_stat_effects, args=(character_name, txt),
        kwargs={"source": "activity", "per_hour": True,
                "elapsed_min": elapsed_min},
        daemon=True, name="activity-stat-tick").start()
