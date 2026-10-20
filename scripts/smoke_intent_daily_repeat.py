#!/usr/bin/env python3
"""Daily intent cycles, using only temporary storage.

Usage: ./.venv/bin/python scripts/smoke_intent_daily_repeat.py

Hand-derived expectations (year 1, game days D010..D040):
1. D010 10:00 standing daily, target 1 instagram: deadline D011 midnight.
   Talkto adds zero; one instagram adds one and completes the task.
2. D011 00:05 renews to active, empty progress, deadline D012 midnight;
   the closed D010 cycle logs done with count 1, retaining participant roles.
3. Expiry then renewal at D012 00:05 logs D011 missed with count 0.
4. D012 08:00 daily 09:00 schedules today's bump; at 10:00 no bump.
   D013 00:05 renewal schedules D013 09:00, replacing any old bump.
5. Cancellation never renews. A jump D013 -> D016 adds exactly one log,
   for D013 (no synthetic D014/D015). Twenty more days retain 14 logs.
6. Prompt uses daily counted/open lines with the same marker id. Client
   repeat_state, executable repeat, invalid repeat/kind/time all yield 400,
   including PATCH merged with existing action/trigger. Loaded skill types
   are unique, sorted and exclude non-trackable skills. PATCH keeps server
   state and recomputes the current deadline/time, ignoring duration presets.
   A PATCH across D036 -> D037 before the tick logs missed/1 and clears progress.

Removing cycle initialization, filtering, renewal, scheduling guards or route
validation breaks the corresponding assertions below. No real world is opened.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory(prefix="intent-daily-") as storage:
    paths.init(Path(storage))
    from app.core import config, db
    config.load(Path(storage) / "config.json")
    db.init_schema()
    from app.core.game_time import GameTime
    from app.core.timeutils import set_game_factor, set_game_time
    from app.models import intents
    from app.routes.intents import _create_route_sync, _patch_route_sync, progress_types_route
    from fastapi import HTTPException
    from app.scheduler.scheduler_manager import get_scheduler_manager

    set_game_factor(0)

    def clock(day, time="00:05"):
        set_game_time(GameTime.parse(f"Y0001-D{day:03d}T{time}:00"))

    def create(**extra):
        return _create_route_sync({"owner": "demo", "title": "Daily task",
                                   "trigger": {"kind": "standing", "repeat": "daily"}, **extra})

    def current(it):
        return intents.get_intent(it["id"])

    def rejected(data, it=None):
        try:
            (_patch_route_sync(it["id"], data) if it else create(**data))
        except HTTPException as exc:
            assert exc.status_code == 400, exc
        else:
            raise AssertionError(f"Accepted invalid payload: {data}")

    clock(10, "10:00")
    daily = create(target_count=1, meta={"progress_type": "instagram"})
    assert daily["status"] == "active"
    assert daily["expires_at"] == "Y0001-D011T00:00:00"
    assert intents.auto_track_progress("demo", "talkto") is None
    assert current(daily)["participants"]["demo"]["progress"] == []
    intents.auto_track_progress("demo", "instagram")
    assert current(daily)["status"] == "done"
    clock(11)
    intents.renew_repeating()
    it = current(daily)
    assert it["status"] == "active" and it["participants"]["demo"]["progress"] == []
    assert it["meta"]["repeat_state"] == {"day": "Y0001-D011", "log": [
        {"day": "Y0001-D010", "result": "done", "count": 1}]}
    assert it["expires_at"] == "Y0001-D012T00:00:00"
    # A participant's role survives; every participant's progress is reset.
    intents.update_intent(daily["id"], participants={
        "demo": {"role": "lead", "progress": []},
        "": {"role": "helper", "progress": []}})
    clock(12)
    intents.expire_overdue()
    intents.renew_repeating()
    assert current(daily)["meta"]["repeat_state"]["log"][-1] == {
        "day": "Y0001-D011", "result": "missed", "count": 0}
    assert current(daily)["status"] == "active"
    assert current(daily)["participants"] == {
        "demo": {"role": "lead", "progress": []}, "": {"role": "helper", "progress": []}}
    print("OK: cases 1–3, filtering, completion and daily renewal")

    scheduler = get_scheduler_manager()
    def jobs(it):
        return [j for j in scheduler.get_jobs() if j["id"] == f"intent_{it['id']}"]

    clock(12, "08:00")
    early = create(trigger={"kind": "at_time", "repeat": "daily", "at": "09:00"})
    assert early["trigger"]["run_date"] == "Y0001-D012T09:00:00"
    assert len(jobs(early)) == 1
    clock(12, "10:00")
    late = create(trigger={"kind": "at_time", "repeat": "daily", "at": "09:00"})
    assert late["trigger"]["run_date"] == "Y0001-D012T09:00:00" and not jobs(late)
    _patch_route_sync(early["id"], {"trigger": {"kind": "at_time", "repeat": "daily", "at": "10:00"}})
    assert not jobs(early), "equal/past time must also remove an old bump"
    intents.update_intent(early["id"], participants={
        "demo": {"role": "lead", "progress": [{"note": "worked"}]},
        "": {"role": "helper", "progress": [{"note": "helped"}]}})
    clock(13)
    intents.renew_repeating()
    assert current(early)["participants"] == {
        "demo": {"role": "lead", "progress": []}, "": {"role": "helper", "progress": []}}
    for task in (early, late):
        assert len(jobs(task)) == 1
        assert jobs(task)[0]["trigger"]["run_date"].startswith("Y0001-D013T")
    print("OK: case 4, future-only bump and renewal")

    intents.cancel_intent(late["id"])
    cancelled = current(late)
    before = len(current(daily)["meta"]["repeat_state"]["log"])
    clock(16)
    intents.renew_repeating()
    log = current(daily)["meta"]["repeat_state"]["log"]
    assert len(log) == before + 1 and log[-1]["day"] == "Y0001-D013"
    assert current(late) == cancelled
    assert intents.renew_repeating() == 0
    for day in range(17, 37):
        clock(day)
        intents.renew_repeating()
    assert len(current(daily)["meta"]["repeat_state"]["log"]) == 14
    print("OK: case 5, cancellation, skipped days, idempotence and log cap")

    prompt = intents.build_intents_prompt_section("demo")
    assert "Daily task — comes back every day; today: 0 of 1" in prompt
    assert f"(id {daily['id']})" in prompt
    assert "Daily task — comes back every day; today: open" in prompt
    for data in ({"meta": {"repeat_state": {}}}, {"action": {"type": "demo"}},
                 {"trigger": {"kind": "standing", "repeat": "weekly"}},
                 {"trigger": {"kind": "now", "repeat": "daily"}},
                 *({"trigger": {"kind": "at_time", "repeat": "daily", "at": at}}
                   for at in ("9:00", "24:00", "09:60", None))):
        rejected(data)
    rejected({"action": {"type": "demo"}}, daily)
    rejected({"meta": {"repeat_state": {}}}, daily)
    executable = intents.create_intent(owner="demo", title="Executable", action={"type": "demo"})
    rejected({"trigger": {"kind": "standing", "repeat": "daily"}}, executable)
    from app.skills.skill_manager import SkillManager
    manager = SkillManager()
    manager.skills = [SimpleNamespace(name=name, PROGRESS_TYPE=kind) for name, kind in (
        ("Post", "instagram"), ("Talk", "talkto"), ("OtherPost", "instagram"), ("NoProgress", ""))]
    with patch("app.core.dependencies._skill_manager", manager):
        assert progress_types_route() == ["instagram", "talkto"]
    state = current(daily)["meta"]["repeat_state"]
    edited = _patch_route_sync(daily["id"], {"duration_minutes": 60, "meta": {"progress_type": "talkto"}})
    assert edited["expires_at"] == "Y0001-D037T00:00:00"
    assert edited["meta"]["repeat_state"] == state
    plain = intents.create_intent(owner="demo", title="One off", target_count=2,
                                  meta={"progress_type": "search"})
    intents.auto_track_progress("demo", "instagram")
    assert current(plain)["participants"] == {}
    no_count = create(title="Daily open task")
    intents.complete_intent(no_count["id"])
    assert "Daily task — comes back every day; today: done" in intents.build_intents_prompt_section("demo")
    boundary = create(title="Boundary task", target_count=5)
    intents.add_progress(boundary["id"], "demo", "Yesterday's work")
    clock(37)
    patched = _patch_route_sync(boundary["id"], {
        "description": "Edited before periodic tick",
        "participants": current(boundary)["participants"]})
    assert patched["meta"]["repeat_state"]["log"] == [
        {"day": "Y0001-D036", "result": "missed", "count": 1}]
    assert patched["participants"]["demo"]["progress"] == []
    assert f"(id {no_count['id']})" not in intents.build_intents_prompt_section("demo")
    scheduler.shutdown()
    print("OK: case 6, prompt, validation, patch state and non-repeating filter")

print("All six daily-repeat cases passed")
