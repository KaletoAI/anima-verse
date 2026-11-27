"""Automatic quests offered by nearby NPCs (quest stage 3, Task 6).

Flow:
  1. A periodic sub-task (:func:`tick`, every 300 s) checks ``quests.auto_enabled``,
     the cap ``quests.max_open_auto_quests`` against open ``origin="auto"`` runs,
     and :func:`pick_giver` (an awake non-avatar NPC in the same room — else same
     location — as a player avatar, not already bound as giver of an open run).
     No LLM ever runs in :func:`tick`; when eligible it submits at most ONE
     deduplicated background task-queue job (``quest_auto``).
  2. The task-queue worker (:func:`_handle`) re-checks every precondition at run
     time (switch, world freeze, cap, giver presence/sleep/busy, avatar presence,
     shared location), calls ``quest_authoring.generate(..., mode="auto")``,
     stores a ready unkept ``auto`` template with a mandatory game-hour time
     limit (``quests.auto_expiry_game_hours``), and starts the run. Any refusal
     or error deletes the template so nothing orphaned remains.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("quest_auto")

TASK_TYPE = "quest_auto"
DEDUP_KEY = "auto_quest"

_DEFAULT_AUTO_ENABLED = False
_DEFAULT_MAX_OPEN = 2
_DEFAULT_EXPIRY_GAME_HOURS = 48


def auto_enabled() -> bool:
    """Whether automatic quest generation is enabled."""
    from app.core import config

    val = config.get("quests.auto_enabled", None)
    if isinstance(val, bool):
        return val
    return _DEFAULT_AUTO_ENABLED


def max_open() -> int:
    """Maximum number of open automatic quest runs allowed at once (0 = none)."""
    from app.core import config

    val = config.get("quests.max_open_auto_quests", None)
    if val is None or isinstance(val, bool):
        return _DEFAULT_MAX_OPEN
    try:
        num = int(val)
        return num if num >= 0 else _DEFAULT_MAX_OPEN
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_MAX_OPEN


def expiry_game_hours() -> int:
    """Game hours after which an automatic quest expires and fails (>= 1)."""
    from app.core import config

    val = config.get("quests.auto_expiry_game_hours", None)
    if val is None or isinstance(val, bool):
        return _DEFAULT_EXPIRY_GAME_HOURS
    try:
        num = int(val)
        return num if num >= 1 else _DEFAULT_EXPIRY_GAME_HOURS
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_EXPIRY_GAME_HOURS


def open_auto_count() -> int:
    """Count of currently open runs whose live template has ``origin='auto'``."""
    from app.models import quests

    return quests.count_runs(quests.RUN_OPEN_STATES, origin="auto")


def live_givers() -> Set[str]:
    """Character names bound as giver of any run in ``RUN_OPEN_STATES``."""
    from app.models import quests

    givers: Set[str] = set()
    for run in quests.list_runs(states=quests.RUN_OPEN_STATES):
        snap = run.get("template_snapshot") or {}
        giver_role = snap.get("giver_role")
        if not isinstance(giver_role, str) or not giver_role.strip():
            continue
        binding = (run.get("bindings") or {}).get(giver_role)
        if isinstance(binding, dict):
            name = binding.get("name")
            if isinstance(name, str) and name.strip():
                givers.add(name)
    return givers


def pick_giver() -> Optional[Tuple[str, str]]:
    """Pick ``(npc, avatar)`` for an automatic quest, or ``None`` when none qualifies."""
    from app.models.account import get_all_avatars
    from app.models.character import (
        is_character_sleeping,
        list_available_characters,
        list_character_places,
    )

    avatars = set(get_all_avatars() or ())
    if not avatars:
        return None
    places = list_character_places() or {}
    roster = list_available_characters() or []
    busy = live_givers()

    pre_candidates = sorted(
        name
        for name in roster
        if name not in avatars
        and name not in busy
        and bool((places.get(name) or ("", ""))[0])
    )
    if not pre_candidates:
        return None

    sleeping_cache: Dict[str, bool] = {}

    def _awake(name: str) -> bool:
        if name not in sleeping_cache:
            sleeping_cache[name] = bool(is_character_sleeping(name))
        return not sleeping_cache[name]

    for avatar in sorted(avatars):
        av_loc, av_room = places.get(avatar) or ("", "")
        if not av_loc:
            continue
        if av_room:
            for npc in pre_candidates:
                npc_loc, npc_room = places.get(npc) or ("", "")
                if npc_loc == av_loc and npc_room == av_room and _awake(npc):
                    return (npc, avatar)
        for npc in pre_candidates:
            npc_loc, _npc_room = places.get(npc) or ("", "")
            if npc_loc == av_loc and _awake(npc):
                return (npc, avatar)
    return None


def submit(giver: str, avatar: str) -> str:
    """Enqueue one deduplicated ``quest_auto`` background job."""
    from app.core.task_queue import get_task_queue

    return get_task_queue().submit(
        TASK_TYPE,
        {"giver": giver, "avatar": avatar},
        queue_name="background",
        priority=30,
        agent_name=DEDUP_KEY,
        deduplicate=True,
        max_retries=0,
    )


def tick() -> Dict[str, Any]:
    """Periodic check (no LLM): queue at most one ``quest_auto`` job when eligible."""
    try:
        if not auto_enabled():
            return {"skipped": "disabled"}
        if open_auto_count() >= max_open():
            return {"skipped": "cap"}
        picked = pick_giver()
        if picked is None:
            return {"skipped": "no_giver"}
        npc, avatar = picked
        task_id = submit(npc, avatar)
        return {"queued": task_id, "giver": npc, "avatar": avatar}
    except Exception as e:  # noqa: BLE001
        logger.debug("quest_auto tick failed: %s", e)
        return {"skipped": "error"}


def _handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Task-queue worker: re-check state, author an auto quest, store and start it."""
    from app.core import quest_authoring, quest_engine
    from app.models import quests
    from app.models.account import get_all_avatars
    from app.models.character import (
        is_character_sleeping,
        list_available_characters,
        list_character_places,
    )
    from app.models.world import is_world_frozen

    if not auto_enabled():
        return {"skipped": "disabled"}
    if is_world_frozen():
        return {"skipped": "world frozen"}
    if open_auto_count() >= max_open():
        return {"skipped": "cap"}

    data = payload if isinstance(payload, dict) else {}
    giver = str(data.get("giver") or "").strip()
    avatar = str(data.get("avatar") or "").strip()

    avatars = set(get_all_avatars() or ())
    roster = set(list_available_characters() or ())
    if not giver or giver not in roster or giver in avatars:
        return {"skipped": "giver gone"}
    if is_character_sleeping(giver):
        return {"skipped": "giver asleep"}
    if giver in live_givers():
        return {"skipped": "giver busy"}
    if not avatar or avatar not in avatars:
        return {"skipped": "avatar gone"}

    places = list_character_places() or {}
    giver_loc = (places.get(giver) or ("", ""))[0]
    avatar_loc = (places.get(avatar) or ("", ""))[0]
    if not giver_loc or not avatar_loc or giver_loc != avatar_loc:
        return {"skipped": "apart"}

    brief = (
        f"{giver} offers a small quest to {avatar}, who is standing nearby. "
        f"It should fit {giver}'s situation and the place."
    )
    result = quest_authoring.generate(brief, giver=giver, avatar=avatar, mode="auto")
    template = result.get("template")
    if not result.get("ok") or not isinstance(template, dict):
        codes = [
            str(i.get("code") or "invalid")
            for i in (result.get("issues") or [])
            if isinstance(i, dict)
        ] or ["invalid"]
        phase = str(result.get("phase") or "")
        logger.info(
            "auto quest for %s/%s dropped at phase %s: %s",
            giver, avatar, phase or "-", ", ".join(codes),
        )
        return {"dropped": codes, "phase": phase}

    content = {k: template[k] for k in quests.TEMPLATE_CONTENT_KEYS if k in template}
    content["time_limit_s"] = expiry_game_hours() * 3600
    try:
        tpl = quests.create_template(**content, origin="auto", state="ready", kept=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("auto quest template store failed for %s/%s: %s", giver, avatar, e)
        return {"dropped": ["error"]}

    bindings = result.get("bindings") if isinstance(result.get("bindings"), dict) else {}
    try:
        run = quest_engine.start_run(tpl["id"], bindings, started_by="auto")
    except quest_engine.QuestRefused as e:
        codes = [
            str(i.get("code") or "refused")
            for i in (e.issues or [])
            if isinstance(i, dict)
        ] or ["refused"]
        logger.info(
            "auto quest %s refused at start for %s/%s (%s) — dropping template",
            tpl["id"], giver, avatar, ", ".join(codes),
        )
        quests.delete_template(tpl["id"])
        return {"dropped": codes}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "auto quest %s failed at start for %s/%s (%s) — dropping template",
            tpl["id"], giver, avatar, e,
        )
        quests.delete_template(tpl["id"])
        return {"dropped": ["error"]}

    logger.info(
        "auto quest started: template=%s run=%s giver=%s avatar=%s",
        tpl["id"], run["id"], giver, avatar,
    )
    return {
        "template_id": str(tpl["id"]),
        "run_id": str(run["id"]),
        "giver": giver,
        "avatar": avatar,
    }


def register() -> None:
    """Register the ``quest_auto`` task-queue handler."""
    from app.core.task_queue import get_task_queue

    get_task_queue().register_handler(TASK_TYPE, _handle)
