"""The player's quest book — the spoiler-free payload of ``GET /play/quests`` (quest stage 1, plan D14).

Built UP from two whitelists (:data:`QUEST_FIELDS`, :data:`STEP_FIELDS`) out of each run's ``template_snapshot``
(D2): a field the model gains later can never leak by omission. Withheld by construction: ``gm_notes``, roles,
bindings, every ``hint``, every condition, the snapshot itself, and the text of every step after the current one.

Listed runs: every ``open`` run (newest first), then at most :data:`CHRONICLE_SIZE` ended ones (latest end
first). ``preparing`` and ``hidden`` runs are not listed, and neither is an ended run that never opened (no
``started_game_ts``: a hidden run cancelled or broken before its start condition passed) — its title would be a
spoiler. Quests are world-wide, so every avatar sees the same runs; only ``locked`` is per avatar.

Steps: an open run shows its done steps and the current one (``state`` ``done`` / ``current``); an ended run
only its done steps. A done step carries ``done_by`` (the avatar name stored when it was fulfilled) and
``done_label`` (its game stamp as a finished label).

Texts (title, summary, step text, the author's lock text) go through ``quest_engine.render_text``: a ``{role}``
placeholder becomes the label frozen on the run at start. A label is not a spoiler; ids and hints still are.

Labels are finished server strings in ``lang`` (D14): ``done_label`` / ``ended_label`` through
``GameTime.parse(...).display_label(lang)``, ``time_left_label`` through :func:`_time_left_label`. ``locked`` is
the author's lock text from ``quest_engine.avatar_view`` (D8); the engine's English fallback is translated.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger("quest_book")

#: How many ended runs the book lists after the open ones.
CHRONICLE_SIZE = 10
#: The run fields an entry is built from (title/summary come from the snapshot, id/state from the run).
QUEST_FIELDS = ("id", "title", "summary", "state")
#: The fields of one listed step.
STEP_FIELDS = ("text", "state")


def _label(canonical: str, lang: str) -> str:
    """The game label of a canonical stamp; "" for an empty or unreadable one."""
    if not canonical:
        return ""
    from app.core.game_time import GameTime
    try:
        return GameTime.parse(canonical).display_label(lang)
    except ValueError:
        return ""


def _time_left_label(d, lang: str) -> str:
    """``d`` (a GameDuration) as a short label in whole units, rounded down: a day or more -> "{d} d {h} h",
    an hour or more -> "{h} h {m} min", else "{m} min". A negative span reads as "0 min"."""
    from app.core.game_time import DAY_SECONDS
    from app.core.i18n import t
    total = max(0, int(d.total_seconds))
    days, rest = divmod(total, DAY_SECONDS)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return t("{d} d {h} h", lang).replace("{d}", str(days)).replace("{h}", str(hours))
    if hours:
        return t("{h} h {m} min", lang).replace("{h}", str(hours)).replace("{m}", str(minutes))
    return t("{m} min", lang).replace("{m}", str(minutes))


def _steps(run: Dict[str, Any], lang: str) -> List[Dict[str, Any]]:
    from app.core.quest_engine import render_text
    snapshot = run.get("template_snapshot") or {}
    steps = snapshot.get("steps") if isinstance(snapshot.get("steps"), list) else []
    done = {}
    for entry in run.get("step_log") or []:
        if isinstance(entry, dict) and isinstance(entry.get("step"), int):
            done.setdefault(entry["step"], entry)
    shown = len(steps)
    if run.get("state") != "done":
        current = run.get("current_step")
        current = current if isinstance(current, int) and not isinstance(current, bool) else 0
        shown = min(len(steps), current + (1 if run.get("state") == "open" else 0))
    out: List[Dict[str, Any]] = []
    for index in range(shown):
        step = steps[index] if isinstance(steps[index], dict) else {}
        source = {"text": render_text(str(step.get("text") or ""), run),
                  "state": "done" if index in done else "current"}
        row = {key: source[key] for key in STEP_FIELDS}
        if index in done:
            row["done_by"] = str(done[index].get("avatar") or "")
            row["done_label"] = _label(str(done[index].get("game_ts") or ""), lang)
        out.append(row)
    return out


def _entry(run: Dict[str, Any], avatar: str, lang: str, now) -> Dict[str, Any]:
    from app.core import quest_engine
    from app.core.game_time import GameTime
    from app.core.i18n import t
    snapshot = run.get("template_snapshot") or {}
    source = {"id": run.get("id") or "", "title": quest_engine.render_text(str(snapshot.get("title") or ""), run),
              "summary": quest_engine.render_text(str(snapshot.get("summary") or ""), run),
              "state": run.get("state") or ""}
    entry: Dict[str, Any] = {key: source[key] for key in QUEST_FIELDS}
    entry["steps"] = _steps(run, lang)
    if run.get("state") == "open":
        expires = run.get("expires_at") or ""
        if expires and now is not None:
            try:
                entry["time_left_label"] = _time_left_label(GameTime.parse(expires) - now, lang)
            except ValueError:
                pass
        view = quest_engine.avatar_view(run, avatar)
        if view.get("locked"):
            text = view.get("locked_text") or quest_engine.DEFAULT_LOCKED_TEXT
            entry["locked"] = (t(text, lang) if text == quest_engine.DEFAULT_LOCKED_TEXT
                               else quest_engine.render_text(text, run))
    else:
        label = _label(run.get("ended_game_ts") or "", lang)
        if label:
            entry["ended_label"] = label
    return entry


def build_player_quests(avatar: str, lang: str = "en") -> dict:
    """The quest book of ``avatar`` (D14); without an avatar ``{"avatar": "", "quests": []}``.
    A storage failure is logged and answers the avatar with an empty list."""
    avatar = (avatar or "").strip()
    if not avatar:
        return {"avatar": "", "quests": []}
    from app.core.timeutils import game_time
    from app.models import quests
    try:
        open_runs = quests.list_runs(states=("open",))
        ended = quests.list_chronicle(CHRONICLE_SIZE)  # filtered, ordered and cut in SQL
        try:
            now = game_time(strict=True)
        except Exception as e:  # noqa: BLE001 - no clock, no time-left label
            logger.warning("quest book: game clock unavailable: %s", e)
            now = None
        entries = [_entry(r, avatar, lang, now) for r in open_runs + ended]
    except Exception as e:  # noqa: BLE001 - the panel shows an empty book rather than an error
        logger.warning("quest book for %s failed: %s", avatar, e)
        return {"avatar": avatar, "quests": []}
    return {"avatar": avatar, "quests": entries}
