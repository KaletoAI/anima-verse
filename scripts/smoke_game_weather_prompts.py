#!/usr/bin/env python3
"""Smoke run for the prompt variable ``game_weather`` — the world calendar's
season atmosphere in every prompt where the LLM sees the world.

What the feature is: ``GameTime.atmosphere(lang)["label"]`` reads e.g.
``"freezing, snow — often fog in the morning"``. It rides along with
``time_of_day``/``game_date`` into every chat / thought / action prompt, into
the dressing prompt, and — ONLY for open-air renders — into the image prompts.

The expected values below are derived BY HAND from a hand-built one-season
calendar (winter, 30 days, freezing/snow, note "often fog in the morning",
sunrise 07:00 / sunset 17:00, noon hour 12, evening hour 18) and a frozen
clock at day 3, 07:14:

  atmosphere label -> "freezing, snow — often fog in the morning"
                      (= "<temperature>, <weather> — <note>")
  date_label("en") -> "Winter, day 3 · Year 1"
  time_hhmm()      -> "07:14"
  day_bucket()     -> "morning"   (07:14 is past sunrise 07:00, before noon 12)
  outdoor clause   -> "outdoor conditions: morning, freezing, snow — often
                       fog in the morning"

Cases:
  [1] Static supplier check — every module under app/ that hands a
      ``game_date`` to a prompt hands a ``game_weather`` too. Two files are
      exempt on purpose (listed in EXEMPT): they summarize a PAST day, where
      today's weather would be an invented fact.
  [2] Thought / perception templates carry the weather line.
  [3] Storyteller + random-event templates carry it.
  [4] The dressing context block carries Season AND Weather, and the
      outfit_generation template renders them.
  [5] ``prompt_compose.outdoor_conditions`` — empty indoors, the full clause
      outdoors.
  [6] ``compose()`` weaves the clause in for an outdoor render and leaves an
      indoor one untouched; the clause is its own meta field.
  [7] The LLM compose template shows the OUTDOOR CONDITIONS block only when
      ``is_outdoor``; the chat scene template likewise.
  [8] ``prompt_compose_llm.cache_key`` changes with the conditions — a summer
      prompt must not be served back in a blizzard.

Touches no world.db, starts no server, calls no LLM: the calendar is built in
memory and the game clock is monkeypatched.

Usage:
    ./.venv/bin/python scripts/smoke_game_weather_prompts.py
Exit code 0 = all checks passed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.core.game_time as gt          # noqa: E402
import app.core.timeutils as timeutils   # noqa: E402

FAILURES: list = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILURES.append(f"{name} {detail}".strip())


# ── Hand-built world: one season, frozen clock ────────────────────────────
WINTER = gt.Season(key="winter", name="Winter", days=30,
                   sunrise_min=7 * 60, sunset_min=17 * 60,
                   temperature="freezing", weather="snow",
                   weather_note="often fog in the morning")
gt._CALENDAR_CACHE = gt.Calendar(seasons=(WINTER,), noon_hour=12,
                                 evening_hour=18)
FROZEN = gt.GameTime(2 * gt.DAY_SECONDS + 7 * 3600 + 14 * 60)   # day 3, 07:14
timeutils.game_time = lambda: FROZEN

LABEL = "freezing, snow — often fog in the morning"
DATE = "Winter, day 3 · Year 1"
CLAUSE = f"outdoor conditions: morning, {LABEL}"


def test_clock_fixture() -> None:
    print("\n[0] the hand-built calendar produces the documented values")
    check("atmosphere label", FROZEN.atmosphere("en")["label"] == LABEL,
          f"got {FROZEN.atmosphere('en')['label']!r}")
    check("date label", FROZEN.date_label("en") == DATE,
          f"got {FROZEN.date_label('en')!r}")
    check("time", FROZEN.time_hhmm() == "07:14", FROZEN.time_hhmm())
    check("day bucket", FROZEN.day_bucket() == "morning", FROZEN.day_bucket())


# ── [1] suppliers ─────────────────────────────────────────────────────────
# Past-day summaries: the day's own season IS known, but the summary must not
# state weather that never appeared in the recorded events.
EXEMPT = {"app/core/memory_service.py", "app/routes/diary.py"}


def test_suppliers() -> None:
    print("\n[1] every game_date supplier is a game_weather supplier")
    missing = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if "game_date" not in text or rel in EXEMPT:
            continue
        if "game_weather" not in text:
            missing.append(rel)
    check("no supplier hands the date without the weather", not missing,
          f"missing in {missing}")


# ── [2]/[3] templates ─────────────────────────────────────────────────────
THOUGHT_CTX = {
    "character_name": "Mira", "lang_instruction": "Always respond in German.",
    "personality": "curious", "location_name": "Village Square",
    "activity": "sweeping", "feeling": "Neutral",
    "time_of_day": "07:14", "game_date": DATE, "game_weather": LABEL,
    "has_assignments": False, "alone_here": False,
    "action_instruction": "Decide what you want to do next.",
    "present_people_block": "Ren (idle)",
}
_OPTIONAL = ("inbox_block", "events_block", "assignments_block",
             "general_task", "commitments_block", "state_flags_block",
             "outfit_decision_block", "arc_block", "retrospective_block",
             "skill_context_blocks", "effects_block", "recent_chat_block",
             "recent_thoughts", "outfit_self_block", "outfit_avatar_block",
             "room_items_block", "inventory_block", "elsewhere_block",
             "tracker_block", "activity_hint_block", "daily_schedule_block",
             "tools_hint")
THOUGHT_CTX.update({k: "" for k in _OPTIONAL})

PERCEPTION_VARS = {
    "action_actor": "Ren", "action_narration": "Ren hauls the cart away.",
    "action_scope": "here", "relationship_to_actor": "",
    "action_actor_location": "", "action_actor_room": "",
}


def test_thought_templates() -> None:
    print("\n[2] thought / perception prompts carry the weather line")
    from app.core.prompt_templates import render

    for name, extra in (("chat/agent_thought.md", {}),
                        ("chat/agent_thought_in_chat.md", {}),
                        ("tasks/perceive_action.md", PERCEPTION_VARS)):
        out = render(name, **{**THOUGHT_CTX, **extra})
        check(f"{name}: weather line", f"- Weather: {LABEL}" in out)
        check(f"{name}: still dated", f"- Date: {DATE}" in out)


def test_task_templates() -> None:
    print("\n[3] storyteller + random-event prompts carry the weather line")
    from app.core.prompt_templates import render_task

    sys_p, user_p = render_task(
        "storyteller_react", subject_name="Mira", subject_profile="",
        subject_outfit="", subject_mood="calm", location_name="Village Square",
        room_name="", scope_label="this room", current_time="07:14",
        time_of_day="morning", game_date=DATE, game_weather=LABEL,
        setting_block="", active_events_block="", present_people_block="",
        user_action_text="Mira sweeps the steps.", language_name="German")
    check("storyteller_react: weather line", f"Weather: {LABEL}" in sys_p,
          "not in the system half")

    sys_p, user_p = render_task(
        "random_event_general", location_name="Village Square",
        category="ambient", category_description="small ambient happenings",
        current_time="07:14", time_of_day="morning", game_date=DATE,
        game_weather=LABEL, location_description="a wide cobbled square",
        setting_block="", rooms_block="", characters_block="",
        hazards_block="", last_event_block="", blacklist_block="",
        language_name="German")
    check("random_event_general: weather line", f"Weather: {LABEL}" in user_p,
          "not in the user half")


# ── [4] dressing ──────────────────────────────────────────────────────────
def test_outfit_context() -> None:
    print("\n[4] the dressing context block carries Season and Weather")
    from app.skills.outfit_creation_skill import build_context_block
    from app.core.prompt_templates import render_task

    block = build_context_block(location_label="Village Square",
                                activity="sweeping", feeling="calm",
                                style_hint="rustic", decency="public",
                                lang="en")
    check("Season line", "Season: Winter" in block, block)
    check("Weather line", f"Weather: {LABEL}" in block, block)
    check("situation kept", "Location: Village Square" in block, block)

    _sys, user_p = render_task(
        "outfit_generation", character_name="Mira", personality="curious",
        appearance="tall", context_block=block, hint_block="",
        existing_block="(none)", type_hint="Pick one coherent style.",
        required_block="", max_pieces=4, allowed_slots="top, bottom, feet",
        language_hint="", outfit_types_vocab="casual, home")
    check("template renders the weather", f"Weather: {LABEL}" in user_p)
    check("template renders the season", "Season: Winter" in user_p)


# ── [5]/[6] image composer ────────────────────────────────────────────────
def test_outdoor_conditions() -> None:
    print("\n[5] outdoor_conditions: indoors nothing, outdoors the clause")
    from app.core.prompt_compose import outdoor_conditions

    check("indoor -> empty", outdoor_conditions(False) == "",
          repr(outdoor_conditions(False)))
    check("outdoor -> clause", outdoor_conditions(True) == CLAUSE,
          repr(outdoor_conditions(True)))


def test_compose() -> None:
    print("\n[6] compose() weaves the clause in only when it is handed one")
    from app.core.prompt_compose import compose, outdoor_conditions

    indoor = compose(use_case="location", subject="a small kitchen",
                     backend=None, conditions=outdoor_conditions(False))
    check("indoor prompt has no weather", "snow" not in indoor.prompt.lower(),
          indoor.prompt)
    check("indoor meta conditions empty", indoor.meta["conditions"] == "")

    outdoor = compose(use_case="location", subject="a wide cobbled square",
                      backend=None, conditions=outdoor_conditions(True))
    check("outdoor prompt carries the clause", CLAUSE in outdoor.prompt,
          outdoor.prompt)
    check("clause is PREPENDED (early tokens steer diffusion)",
          outdoor.prompt.index(CLAUSE)
          < outdoor.prompt.index("wide cobbled square"), outdoor.prompt)
    check("outdoor meta conditions", outdoor.meta["conditions"] == CLAUSE)


# ── [7] conditional image templates ───────────────────────────────────────
def test_image_templates() -> None:
    print("\n[7] the image templates gate the weather on outdoor")
    from app.core.prompt_templates import render_task

    def compose_tpl(is_outdoor: bool, conditions: str):
        return render_task("image_prompt_compose", hints="3 by 4 metres",
                           style="product render", subject="a cobbled square",
                           family="natural", is_outdoor=is_outdoor,
                           conditions=conditions)

    _s, out = compose_tpl(True, CLAUSE)
    check("compose/outdoor: block present", "OUTDOOR CONDITIONS" in out
          and CLAUSE in out, out)
    _s, out = compose_tpl(False, "")
    check("compose/indoor: no block", "OUTDOOR CONDITIONS" not in out, out)
    check("compose/indoor: no snow in the living room",
          "snow" not in out.lower(), out)

    def scene_tpl(conditions: str):
        return render_task("image_prompt_scene", model_context="",
                           instruction_context="", photographer_context="",
                           identity_context="", scene_text="They stand still.",
                           setting_block="Setting: Location: Village Square",
                           outdoor_conditions=conditions,
                           characters_present_block="")

    _s, out = scene_tpl(CLAUSE)
    check("scene/outdoor: clause present", CLAUSE in out, out)
    _s, out = scene_tpl("")
    check("scene/indoor: no clause", "outdoor conditions" not in out.lower(),
          out)


# ── [8] cache identity ────────────────────────────────────────────────────
def test_cache_key() -> None:
    print("\n[8] the LLM-compose cache key follows the weather")
    from app.core.prompt_compose_llm import cache_key

    base = ("style", "subject", "hint", "natural")
    check("no conditions != winter conditions",
          cache_key(*base, "") != cache_key(*base, CLAUSE))
    check("winter != summer",
          cache_key(*base, CLAUSE)
          != cache_key(*base, "outdoor conditions: morning, hot, dry"))
    check("same conditions -> same key",
          cache_key(*base, CLAUSE) == cache_key(*base, CLAUSE))


def main() -> int:
    test_clock_fixture()
    test_suppliers()
    test_thought_templates()
    test_task_templates()
    test_outfit_context()
    test_outdoor_conditions()
    test_compose()
    test_image_templates()
    test_cache_key()

    print(f"\n{CHECKS} checks, {len(FAILURES)} failed")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
