"""Stat effects from events & ongoing activities (plan-activity-stat-effects.md).

Shared evaluator with these producers:
- chat beats: extraction_chat_state (its template now allows big swings at
  turning points) — the stat-list builder lives here.
- activity tick (maybe_activity_tick): agent-loop evaluation of the RUNNING
  activity; the LLM returns PER-HOUR deltas, scaled to the elapsed time.
- skill packages: verbs call evaluate_stat_effects directly for
  "significant event" rounds with their OWN situation text (e.g. a
  package's end-of-activity round) — the text is package policy, the
  evaluation is this core mechanism.

Stats stay fully template-driven (store=status_effects incl. per-value
hint; packages contribute stats via character-template fragments) — this
code knows NO stat name.
"""
import json
import re
import threading
from typing import Dict, Tuple

from app.core.game_time import GameTime
from app.core.stat_rules import round_half_away
from app.core.log import get_logger

logger = get_logger("stat_effects")

# Activity tick: at most one evaluation per character per interval; a long
# pause is capped so a stale baseline cannot produce absurd jumps.
_TICK_MIN = 30.0
_TICK_CAP_MIN = 180.0
_last_tick: Dict[str, GameTime] = {}
_activity_rates: dict[str, tuple[str, dict[str, int]]] = {}
_activity_carry: dict[tuple[str, str, str], float] = {}
_tick_pending: set[str] = set()
_tick_lock = threading.Lock()


def build_stat_list(character_name: str, *, excluded=frozenset()) -> Tuple[bool, str]:
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
        from app.core.stat_rules import rules_for_character
        rules = rules_for_character(character_name, profile=prof)
        lines = []
        for section in tmpl.get("sections", []):
            for fld in section.get("fields", []):
                if fld.get("store") != "status_effects":
                    continue
                k = fld.get("key")
                if not k or k not in cur or k in excluded:
                    continue
                hint = (fld.get("hint") or "").strip()
                line = f"- {k}, currently {cur.get(k)}/100"
                baseline = rules.get(k, {}).get("baseline")
                if baseline is not None:
                    line += f", rests at {baseline}"
                if hint:
                    line += f" — {hint}"
                lines.append(line)
        if not lines:
            return False, ""
        return True, "\n".join(lines)
    except Exception as e:
        logger.debug("stat list failed for %s: %s", character_name, e)
        return False, ""


def _evaluate_deltas(character_name: str, situation_text: str, *,
                     per_hour: bool) -> Dict[str, int]:
    """Ask for event deltas or activity rates without applying them."""
    enabled, stat_list = build_stat_list(character_name,
        excluded=declared_action_stats(character_name) if per_hour else frozenset())
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
    deltas: Dict[str, int] = {}
    for k, v in stats.items():
        try:
            d = round_half_away(float(v))
        except (TypeError, ValueError, OverflowError):
            continue
        if d:
            deltas[str(k)] = d
    return deltas


def evaluate_stat_rates(name: str, situation: str) -> dict[str, int]:
    """Return per-hour activity rates without changing the character."""
    return _evaluate_deltas(name, situation, per_hour=True)


def declared_action_stats(name: str) -> set[str]:
    """Current semantic targets, not clip A/B; no authority from stale LLM work."""
    from app.core import prop_action_store
    result = set()
    for run in prop_action_store.live_runs():
        if run["status"] not in ("active", "sleeping") or name not in (run["actor"], run["partner"]):
            continue
        role = "actor" if name == run["actor"] else "partner"
        result.update(effect["stat"] for effect in run["definition"]["effects"]
                      if effect["type"] == "stat_delta" and effect["target"] in (role, "both"))
    return result


def _apply_deltas(name: str, deltas: dict[str, int], source: str) -> dict[str, int]:
    if not deltas:
        return {}
    try:
        from app.models.character import adjust_status_effects
        adjust_status_effects(name, deltas, source=source)
        logger.info("stat effects [%s] %s: %s", source, name, deltas)
        return deltas
    except Exception as exc:
        logger.warning("stat apply failed for %s: %s", name, exc)
        return {}


def _scaled_deltas(name: str, rates: dict[str, int], elapsed_min: float,
                   source: str) -> dict[str, int]:
    """Scale rates with a fractional carry per character, stat and source."""
    scale = max(0.0, min(elapsed_min, _TICK_CAP_MIN)) / 60.0
    deltas = {}
    excluded = declared_action_stats(name) if source == "activity" else set()
    with _tick_lock:
        for key, rate in rates.items():
            carry_key = (name, key, source)
            if key in excluded:
                _activity_carry.pop(carry_key, None)
                continue
            value = rate * scale + _activity_carry.get(carry_key, 0.0)
            delta = round_half_away(value)
            _activity_carry[carry_key] = value - delta
            if delta:
                deltas[key] = delta
    return deltas


def evaluate_stat_effects(character_name: str, situation_text: str, *,
                          source: str, per_hour: bool = False,
                          elapsed_min: float = 0.0) -> Dict[str, int]:
    """Evaluate and apply event deltas, or rates scaled to game minutes."""
    deltas = _evaluate_deltas(character_name, situation_text, per_hour=per_hour)
    if per_hour:
        deltas = _scaled_deltas(character_name, deltas, elapsed_min, source)
    return _apply_deltas(character_name, deltas, source)


def maybe_activity_tick(character_name: str) -> None:
    """Apply activity rates every 30 game minutes, querying only on changes.

    First sight establishes the clock baseline. LLM work runs outside all
    locks, with at most one pending evaluation per character.
    """
    from app.core.timeutils import game_time
    from app.models.character import get_effective_activity, is_character_sleeping
    now = game_time()
    with _tick_lock:
        last = _last_tick.get(character_name)
        if last is None or now < last:
            _last_tick[character_name] = now
            return
        elapsed_min = (now - last).total_seconds / 60.0
        if elapsed_min < _TICK_MIN or character_name in _tick_pending:
            return
        _last_tick[character_name] = now
        _tick_pending.add(character_name)

    def finish(activity: str, rates: dict[str, int]) -> None:
        with _tick_lock:
            _activity_rates[character_name] = (activity, rates)
        deltas = _scaled_deltas(character_name, rates, elapsed_min, "activity")
        _apply_deltas(character_name, deltas, "activity")

    def evaluate(activity: str) -> None:
        try:
            minutes = int(min(elapsed_min, _TICK_CAP_MIN))
            text = (f"{character_name} has been doing this for about {minutes} "
                    f"minutes: {activity}")
            finish(activity, evaluate_stat_rates(character_name, text))
        finally:
            with _tick_lock:
                _tick_pending.discard(character_name)

    started = False
    try:
        if is_character_sleeping(character_name):
            return
        activity = (get_effective_activity(character_name) or "").strip()
        if not activity or activity.lower() == "sleeping":
            return
        with _tick_lock:
            cached = _activity_rates.get(character_name)
        if cached is not None and cached[0] == activity:
            finish(activity, cached[1])
            return
        thread = threading.Thread(target=evaluate, args=(activity,),
                                  daemon=True, name="activity-stat-tick")
        thread.start()
        started = True
    except Exception as exc:
        logger.debug("activity tick failed for %s: %s", character_name, exc)
    finally:
        # Early returns and start failures must release the marker; a live
        # worker releases its own marker after applying the result.
        if not started:
            with _tick_lock:
                _tick_pending.discard(character_name)
