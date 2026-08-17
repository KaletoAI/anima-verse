"""Diary routes — timeline / daily diary API.

The diary is generated on demand from existing data sources, not stored in
real time. The Generate button rebuilds the view.

**Days are GAME days.** Every ``date`` in and out of these routes is a game-day
key (``Y0002-D109``), and the server ships the readable ``date_label`` next to
it — the client renders, it never computes the world calendar.
"""
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.models.diary import (
    day_label,
    generate_for_day,
    get_available_dates_fast,
    has_daily_summary,
    build_daily_summary_input,
    add_summary,
    resolve_day_key,
    ENTRY_TYPES,
    ENTRY_ICONS)

logger = get_logger("diary_route")

router = APIRouter(prefix="/diary", tags=["diary"])


@router.get("/{user_id}/{character_name}")
def get_diary_entries(character_name: str,
    type: Optional[str] = None,
    date: Optional[str] = None,
    lang: str = "en",
    limit: int = 100,
    offset: int = 0) -> Dict[str, Any]:
    """Get diary entries for a character, generated from all sources.

    Query params:
        type:   filter by entry type
        date:   game day key (``Y0002-D109``) or "all"; default today
        lang:   language for the rendered date label
        limit:  max entries
        offset: pagination offset

    The response echoes the resolved ``date`` (a day key) plus its
    ``date_label``; for "all" both stay empty.
    """
    if not date or date == "all":
        # All days: aggregate every day that has data
        all_days = get_available_dates_fast(character_name)
        entries = []
        for d in all_days:
            entries.extend(generate_for_day(character_name, d))
        day_key = ""
    else:
        day_key = resolve_day_key(date)
        entries = generate_for_day(character_name, day_key)

    if type:
        entries = [e for e in entries if e.get("type") == type]

    # Newest first — sorted deterministically by timestamp (also across days).
    entries.sort(key=lambda e: e.get("timestamp", "") or "", reverse=True)

    return {
        "entries": entries[offset:offset + limit],
        "date": day_key,
        "date_label": day_label(day_key, lang) if day_key else "",
        "types": ENTRY_TYPES,
        "icons": ENTRY_ICONS,
    }


@router.get("/{user_id}/{character_name}/dates")
def get_diary_dates(character_name: str, lang: str = "en") -> List[Dict[str, str]]:
    """Game days that have data (newest first), each with its world label."""
    return [{"date": key, "date_label": day_label(key, lang)}
            for key in get_available_dates_fast(character_name)]


@router.post("/{user_id}/{character_name}/summary")
async def generate_daily_summary(character_name: str, request: Request
) -> Dict[str, Any]:
    """Generate a daily summary (LLM diary entry) in the background.

    Body: ``{"date": "Y0002-D109"}`` (optional, defaults to today's game day)
    Returns immediately — the summary appears on the next panel refresh.
    """
    data = await request.json()
    day_key = resolve_day_key(data.get("date"))

    if has_daily_summary(character_name, day_key):
        raise HTTPException(status_code=409, detail="Diary entry already exists")

    day_text = build_daily_summary_input(character_name, day_key)
    if not day_text:
        raise HTTPException(status_code=404, detail="No events for this day")

    import asyncio
    asyncio.get_event_loop().run_in_executor(
        None, _generate_summary_sync, character_name, day_key, day_text)

    return {"status": "generating", "date": day_key,
            "date_label": day_label(day_key)}


def _generate_summary_sync(character_name: str, day_key: str, day_text: str):
    """Background: LLM generates a personal diary entry from the day's events."""
    from app.models.character import get_character_profile
    from app.core.llm_router import llm_call

    profile = get_character_profile(character_name)
    char_name = profile.get("character_name", character_name)
    personality = profile.get("character_personality", "")

    # Write the diary in the character's language (otherwise the LLM often
    # defaults to English). Same pattern as history_manager.
    lang_instruction = ""
    lang_code = profile.get("language", "")
    if lang_code and lang_code != "en":
        from app.models.character import LANGUAGE_MAP
        lang_name = LANGUAGE_MAP.get(lang_code, lang_code)
        lang_instruction = f"\nWrite the diary entry in {lang_name}."

    # Inner life of that day (plan-thought-journal.md) — a diary is exactly the
    # place for it. Thoughts carry their own game stamp, so the day window is
    # exact here, not a projection.
    try:
        from app.core.day_consolidation import thoughts_of_date
        thoughts_of_day = thoughts_of_date(character_name, day_key)
    except Exception:
        thoughts_of_day = ""

    from app.core.prompt_templates import render_task
    system_prompt, user_prompt = render_task(
        "consolidation_daily_diary",
        character_name=char_name,
        # The diary is dated in-world. The label is rendered in the
        # character's own language, like the entry it heads.
        game_date=day_label(day_key, lang_code or "en"),
        personality=personality,
        lang_instruction=lang_instruction,
        day_text=day_text,
        thoughts_of_day=thoughts_of_day)

    try:
        response = llm_call(
            task="consolidation",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            agent_name=character_name)
        summary = (response.content or "").strip() if response else ""
        if summary:
            add_summary(character_name, summary, day_key)
            logger.info("Diary summary generated: %s/%s", character_name, day_key)
    except Exception as e:
        logger.error("Diary summary error for %s: %s", character_name, e)
