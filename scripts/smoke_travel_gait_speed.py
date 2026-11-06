#!/usr/bin/env python3
"""Smoke run: the server decides the GAIT of a journey, delivers each
character's travel-speed FACTOR and LOCOMOTION override, and judges the
avatar's free-walk reports with that factor.

Usage: ./.venv/bin/python scripts/smoke_travel_gait_speed.py

Runs against a THROWAWAY storage directory and an empty temp clip library
(``ANIMATION_CLIPS_DIR``) — never a real world, never the real clips.

THE WORLD. ``game.travel_speed_m_s`` = 1 m/s (the walking pace, W). Every
shipped rule is replaced by an inert ``info`` row, and the one live rule is
"Modify travel_speed × 2.5 when condition:glutgestalt". Two locations, Origin
at (0, 0) and Goal at (100, 0), square 10 m boundaries with an opening on
every edge. The walker stands at Origin; the avatar out in the open at
(500, 500), far from both.

HAND-DERIVED EXPECTATIONS

  [1] THE GAIT RULE (``travel_engine.journey_gait``): "run" when the journey's
      nominal pace is at least RUN_GAIT_RATIO = 1.5 × the world's walking
      pace, else "walk". With W = 1: 1.5 → run (≥ is inclusive), 1.4999 →
      walk, 2.5 → run, 1.0 → walk. A broken walking pace (0) never runs:
      walk.

  [2] 1× — no condition. ``factor`` = 1, so the journey's ``speed_m_s`` is
      1 × 1 = 1.0 and 1.0 < 1.5 → gait "walk", stored on the journey and
      handed out in the worldmap travel block. ``travel_speed_factor`` rides
      on the AVATAR's row only (1.0 here); the walker's row has null (someone
      else's speed is fogged knowledge), and no row has a ``locomotion`` key.

  [3] 2.5× — the walker gets the condition "glutgestalt". No cache
      invalidation by hand: the factor cache is keyed on the active condition
      names too, so the very next ask (the journey start) sees the condition
      although [2] warmed the cache seconds ago. ``factor`` = 2.5, the speed
      1 × 2.5 = 2.5 ≥ 1.5 → gait "run", and the travel block says "run".

  [4] THE POSITION REPORT. Allowance = max(5, 3 × f × W × e, 3 × f × 3.4 × e)
      with the client's own elapsed e. Two stamped reports 1000 ms apart, the
      second 15 m from the first:
        f = 1   → max(5, 3, 10.2)  = 10.2 m — 15 m is REFUSED (409 too_far);
        f = 2.5 → max(5, 7.5, 25.5) = 25.5 m — the same 15 m is ACCEPTED.
      ``play.pos_step_allowance`` answers exactly these two numbers for the
      elapsed 1.0 s, and with the condition the avatar's row says
      ``travel_speed_factor`` 2.5 — the number the client walks with.

  [5] LOCOMOTION per STATE (``prompt_filters.collect_locomotion``). The clip
      library holds ``float.fbx`` and ``hover.fbx``, so ``clip_kinds()`` is
      [float, hover]. Saving a state whose ``locomotion`` names a kind the
      library lacks ("nope") is a 400, as is a non-object or an unknown slot.
        a) state "glutgestalt" {walk: float} — the walker has the condition →
           row ``locomotion`` == {walk: float}; the plain avatar has none →
           the key is ABSENT;
        b) a second active state "aura" (id sorts BEFORE "glutgestalt")
           {walk: hover, run: hover} — per slot the first state by id wins:
           walk = hover (aura), run = hover (aura) — and with aura's walk
           emptied ({run: hover}) the walk slot falls through to
           glutgestalt: {walk: float, run: hover};
        c) glutgestalt DISABLED → only aura's {run: hover} is left; aura
           deleted as well → no state applies → the key is absent.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="gait-speed-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="gait-speed-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
for _kind in ("float", "hover"):
    (CLIPS / f"{_kind}.fbx").write_bytes(b"")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")

from app.core import config, db  # noqa: E402

(STORAGE / "config.json").write_text("{}")
config.load(STORAGE / "config.json")
db.init_schema()
config._CONFIG.setdefault("game", {})["travel_speed_m_s"] = 1

from fastapi import HTTPException  # noqa: E402

from app.core import travel_engine  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models import rules  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)
from app.routes import play as play_route  # noqa: E402
from app.routes.play import play_pos  # noqa: E402

FAILURES = []
CHECKED = 0
USER = {"username": "demo", "role": "admin"}
AVATAR = "demo_avatar"
WALKER = "Walker"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def row(name):
    payload = build_worldmap_payload(AVATAR, show_all=True)
    return next((c for c in payload["characters"] if c["name"] == name), {})


def set_conditions(name, names):
    with keyed_lock("character_profile", name):
        prof = ch.get_character_profile(name)
        prof["active_conditions"] = [{"name": n, "source": "smoke"} for n in names]
        ch.save_character_profile(name, prof)


def report(x, z, seq, t_ms, session):
    body = {"x": x, "z": z, "seq": seq, "t_ms": t_ms, "session": session}
    try:
        return "ok", asyncio.run(play_pos(_FakeRequest(body), user=USER))
    except HTTPException as exc:
        return "refused", (exc.status_code, exc.detail)


def park(x, z):
    ch.set_character_pos(AVATAR, x, z)
    for store in (play_route._pos_report_at, play_route._pos_client_at,
                  play_route._pos_session_current, play_route._pos_session_retired,
                  play_route._pos_session_seq):
        store.pop(AVATAR, None)


def save_state(body):
    from app.routes.admin_settings import _prompt_filters_save_sync
    try:
        return _prompt_filters_save_sync(USER, body)
    except HTTPException as exc:
        return exc.status_code


# ── the world ───────────────────────────────────────────────────────────
set_game_factor(0.0)
set_game_time(GameTime.parse("Y0001-D001T12:00:00"))
rules.save_rules([{"id": r["id"], "type": "info"} for r in rules.load_rules()] + [{
    "id": "glut_speed", "name": "Glut speed", "type": "modify",
    "condition": "condition:glutgestalt", "character": "",
    "modify": {"quantity": "travel_speed", "factor": 2.5}}])
ORIGIN = add_location(name="Origin", description="fixture")["id"]
GOAL = add_location(name="Goal", description="fixture")["id"]
update_location_position(ORIGIN, 0, 0)
update_location_position(GOAL, 100, 0)
_data = _load_world_data()
for _loc in _data["locations"]:
    _loc["map3d"] = {"boundary": [[-5, -5], [-5, 5], [5, 5], [5, -5]],
                     "boundary_openings": [{"edge": i, "at": .5, "width_m": 4,
                                            "type": "passage"} for i in range(4)]}
_save_world_data(_data)
ch.save_character_profile(WALKER, {"language": "en"}, create_new=True)
ch.save_character_current_location(WALKER, ORIGIN)
ch.set_character_pos(WALKER, 0, 0)
ch.set_known_locations(WALKER, [ORIGIN, GOAL])
ch.save_character_profile(AVATAR, {"current_location": "", "language": "en"},
                          create_new=True)
ch.set_character_pos(AVATAR, 500.0, 500.0)
ch.set_known_locations(AVATAR, [])
set_active_character(AVATAR)
play_route._POS_REPORT_INTERVAL_S = 0.0


def main() -> int:
    print("\n[1] the gait rule")
    gait = getattr(travel_engine, "journey_gait", None)
    check("journey_gait exists", callable(gait), True)
    if callable(gait):
        check("1.5 × W runs (inclusive)", gait(1.5, 1.0), "run")
        check("1.4999 × W walks", gait(1.4999, 1.0), "walk")
        check("2.5 × W runs", gait(2.5, 1.0), "run")
        check("1 × W walks", gait(1.0, 1.0), "walk")
        check("a broken walking pace never runs", gait(2.0, 0.0), "walk")

    print("\n[2] 1× — no condition")
    journey, reason = travel_engine.start_journey(WALKER, GOAL)
    check("the journey started", bool(journey), True)
    journey = journey or {}
    check("speed_m_s", journey.get("speed_m_s"), 1.0)
    check("gait stored on the journey", journey.get("gait"), "walk")
    r = row(WALKER)
    check("travel block gait", (r.get("travel") or {}).get("gait"), "walk")
    check("a foreign row carries no factor", r.get("travel_speed_factor"), None)
    check("the avatar's row: travel_speed_factor", row(AVATAR).get("travel_speed_factor"), 1.0)
    check("no locomotion key", "locomotion" in r, False)
    travel_engine.cancel_journey(WALKER)

    print("\n[3] 2.5× — condition glutgestalt (no manual cache flush)")
    set_conditions(WALKER, ["glutgestalt"])
    journey, reason = travel_engine.start_journey(WALKER, GOAL)
    check("the journey started", bool(journey), True)
    journey = journey or {}
    check("speed_m_s", journey.get("speed_m_s"), 2.5)
    check("gait stored on the journey", journey.get("gait"), "run")
    check("travel block gait", (row(WALKER).get("travel") or {}).get("gait"), "run")
    travel_engine.cancel_journey(WALKER)

    print("\n[4] the position report scales with the factor")
    allowance = getattr(play_route, "pos_step_allowance", None)
    check("pos_step_allowance exists", callable(allowance), True)
    park(500.0, 500.0)
    report(500.0, 500.0, 1, 0.0, "sessGAIT01")
    status, res = report(515.0, 500.0, 2, 1000.0, "sessGAIT01")
    check("15 m in 1 s at 1× is refused", status, "refused")
    check("…as too_far", (res[1] or {}).get("reason") if status == "refused" else res,
          "too_far")
    if callable(allowance):
        check("allowance at 1×", round(allowance(AVATAR, 1.0), 6), 10.2)
    set_conditions(AVATAR, ["glutgestalt"])
    check("the avatar's row carries 2.5", row(AVATAR).get("travel_speed_factor"), 2.5)
    park(500.0, 500.0)
    report(500.0, 500.0, 1, 0.0, "sessGAIT02")
    status, res = report(515.0, 500.0, 2, 1000.0, "sessGAIT02")
    check("the same 15 m at 2.5× is accepted", status == "ok" and res.get("ok"), True)
    if callable(allowance):
        check("allowance at 2.5×", round(allowance(AVATAR, 1.0), 6), 25.5)
    set_conditions(AVATAR, [])

    print("\n[5] locomotion override per state")
    from app.core.animation_clips import clip_kinds
    check("clip library", clip_kinds(), ["float", "hover"])
    base = {"id": "glutgestalt", "label": "Glutgestalt", "enabled": True}
    check("unknown clip kind → 400", save_state({**base, "locomotion": {"walk": "nope"}}), 400)
    check("non-object → 400", save_state({**base, "locomotion": "float"}), 400)
    check("unknown slot → 400", save_state({**base, "locomotion": {"swim": "float"}}), 400)
    saved = save_state({**base, "locomotion": {"walk": "float", "run": ""}})
    check("valid override saved", isinstance(saved, dict) and saved.get("status"), "ok")
    check("a) walker (condition active)", row(WALKER).get("locomotion"), {"walk": "float"})
    check("a) avatar (no condition) has no key", "locomotion" in row(AVATAR), False)
    set_conditions(WALKER, ["glutgestalt", "aura"])
    save_state({"id": "aura", "label": "Aura", "enabled": True,
                "locomotion": {"walk": "hover", "run": "hover"}})
    check("b) first state by id wins per slot", row(WALKER).get("locomotion"),
          {"walk": "hover", "run": "hover"})
    save_state({"id": "aura", "label": "Aura", "enabled": True,
                "locomotion": {"run": "hover"}})
    check("b) an empty slot falls through", row(WALKER).get("locomotion"),
          {"walk": "float", "run": "hover"})
    save_state({**base, "enabled": False, "locomotion": {"walk": "float"}})
    check("c) a disabled state contributes nothing", row(WALKER).get("locomotion"),
          {"run": "hover"})
    from app.routes.admin_settings import prompt_filters_delete
    prompt_filters_delete("aura", user=USER)
    check("c) disabled state → absent", "locomotion" in row(WALKER), False)

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS, ignore_errors=True)
