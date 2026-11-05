#!/usr/bin/env python3
"""Smoke: linked characters — ONE mind (task 5 of the linked-characters plan).

Usage:  ./.venv/bin/python scripts/smoke_linked_mind.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server; the one LLM call
(the day recap) is replaced by a recorder.

THE SPEC (docs/superpowers/specs/2026-11-05-linked-characters-design.md:
"The decided split (mind vs. body)", rulings R3 and R4, "Prompts"):
  * memories, thoughts, consolidated summaries, secrets kept and learned and
    diary entries are MIND stores: stored at and read from ``mind_of(name)``,
    whichever body acts; what a body writes carries ``body = <body>`` and a
    prompt renders it "(as <body>)";
  * consolidation runs ONCE per mind over the whole family's material, body
    material marked "(as <body>)"; any member's wake trigger starts the
    MIND's consolidation, deduplicated per mind; a dormant leader's mind is
    still maintained, a body never consolidates on its own;
  * R3: on a BODY, "Wipe memory" touches only body stores (the mind belongs
    to the leader); on a LEADER it wipes the mind incl. body-marked rows;
    "Fresh start" on a DORMANT leader is refused ("revert first");
  * a linked body's identity block (system part, stable) says "You are also
    <leader> — one mind in another body".

FIXTURE
    Location "Inn" (room taproom, the entry room). Characters (template
    human-roleplay): Tilda, Luna, Obs, all in Inn/taproom. create_linked(Tilda,
    "Glut") -> Glut dormant; swap_presence(Tilda, Glut) -> Glut stands in the
    world, Tilda is DORMANT for the rest of the run (a dormant leader whose
    body acts — the case the maintenance loops must not lose).

WHAT FOLLOWS BY HAND
[A] Memories. add_memory(Glut, "I kissed Luna under the bridge.", episodic)
    -> one row under "Tilda", none under "Glut"; its meta.body "Glut";
    memory_body(entry) "Glut". add_memory(Tilda, "I fed the cat.") -> no
    body (memory_body ""). load_memories(Glut) == load_memories(Tilda) (same
    ids). retrieve_relevant_memories(Tilda, "Luna bridge") contains the kiss;
    after that retrieval's write-back the stored meta.body is still "Glut".
    build_memory_prompt_section(Glut) contains "(as Glut) I kissed Luna under
    the bridge." and "I fed the cat." with no "(as" in front of it.
    memory_situational.render_block([{content "X", body "Glut"}]) contains
    "(as Glut) X". act_engine._tagged_memories_since(Glut, "act_x", "") finds
    the one row Glut wrote with tag act_x. clear_memories(Glut) raises
    ValueError (the mind belongs to Tilda) and Tilda keeps her 3 rows.
[B] Thoughts. add_thought(Glut, "Nobody may learn it.") -> 0 rows under
    "Glut", list_thoughts(Tilda) newest row content that text, body "Glut";
    list_thoughts(Glut) the same rows; recent_thoughts_block(Glut) contains
    "(as Glut)".
[C] Secrets. Luna owns "Luna stole the bell."; add_known_by(Luna, it, Glut,
    discovered=True) -> known_by ["Tilda"], discovered_by ["Tilda"];
    knows(secret, "Glut") True, knows(secret, "Obs") False;
    get_known_secrets_about(Glut) names owner Luna. add_secret(Glut, "I am the
    fire.") -> stored under Tilda (0 rows under Glut), body "Glut";
    add_known_by(Glut, that id, Luna) -> stored on Tilda's row;
    get_known_secrets_about(Luna) has it although Tilda is DORMANT;
    known_about_others_block(Luna) says "About Glut: I am the fire." and never
    "About Tilda"; build_secrets_prompt_section(Glut) lists "(as Glut) I am the
    fire.".
[D] Diary. diary.add_summary(Glut, "Dear diary.", D) -> _load_stored(Tilda)
    has it with metadata.body "Glut"; 0 rows under Glut;
    has_daily_summary(Tilda, D) True.
[E] Consolidation. Scenes (consolidated): #1 [Glut, Luna] "Glut fought the
    troll with Luna." (now-3h .. now-2h), #2 [Tilda, Obs] "Tilda baked bread
    with Obs." (now-90m .. now-1h). Thought of Glut at now-100m "The troll
    smelled of rain.". Flags woke_main_sleep:Glut AND woke_main_sleep:Tilda.
    periodic _sub_day_consolidation() -> exactly ONE recap call; its user
    prompt names "Scenes of the day for Tilda", holds "- (as Glut) Glut
    fought the troll with Luna.", "- Tilda baked bread with Obs." (unmarked)
    and "- (as Glut) The troll smelled of rain."; both flags cleared; the daily
    row (partner '') is under Tilda only; day_cursor:Tilda set, none for Glut.
    A second pass -> no further call. submit_consolidation_for_all() submits
    [Luna, Obs, Tilda] — the dormant leader yes, the body no.
    handle_memory_consolidation({character_name: Glut}) -> character "Tilda".
[F] Summaries. save_daily_summary(Glut, "Y0001-D050", "General.") -> under
    Tilda (partner ''); with partner Luna "Talked with Luna." -> under Glut.
    load_daily_summaries_combined(Tilda)["Y0001-D050"] == "General.\n(as Glut)
    With Luna: Talked with Luna."; load_daily_summaries(Glut)["Y0001-D050"] ==
    {"": "General.", "Luna": "Talked with Luna."}. chat_retention
    _summarized_keys(Glut) daily set contains Tilda's day key from [E] and
    "Y0001-D050".
    The admin History tab reads the same way:
    character_ops.build_memory_history(Glut, "daily") lists the mind's
    general entry ("", "General.") AND Glut's own Luna row, and
    build_memory_history(Glut, "diary") has the same total as Tilda's (>= 1,
    the [D] entry).

[G] Prompts. _build_chat_prompt(Glut, partner Luna).system contains "You are
    also Tilda — one mind in another body" exactly once, in the IDENTITY part
    (after "=== YOUR IDENTITY ==="), not in the scene state; Luna's system
    prompt has no "You are also". build_thought_context(Glut)["linked_leader"]
    "Tilda" and the rendered chat/agent_thought.md contains the line; for Luna
    "" and no line.
[H] Resets. Tilda's soul/beliefs.md holds "- Fire is honest.".
    reset_character(Glut, memory) -> Tilda still has her memories (count
    unchanged), her thought, her diary entry, her beliefs line;
    day_cursor:Tilda unchanged; "the mind belongs to Tilda" in result
    "kept". seed_intro_memory(Glut, "I woke up.") -> 0, nothing written.
    Mind panel: update_relationship_manual(Luna, Tilda, strength 40) ->
    build_memory_relationships(Luna) partners contain "Tilda" (dormant).
    clear_character_knowledge(Glut) -> HTTP 409. fresh_start_character(Tilda)
    (dormant leader) -> HTTP 409 "revert first"; reset_character(Tilda,
    reinit) raises ValueError. wipe_character_memory(Tilda) (dormant) works
    and reports 4 memories — the 3 of [A] plus the day recap [E] stored as a
    "daily" memory of the mind — leaving 0 under Tilda (the Glut-marked ones
    too).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="linked-mind-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from datetime import timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def guarded(label, fn, expected):
    """check() around a call that may raise on the old code."""
    try:
        actual = fn()
    except Exception as e:  # noqa: BLE001
        actual = f"raised {type(e).__name__}: {e}"
    check(label, actual, expected)


def section(title):
    print(title)


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        p.update(values)
        assert ch.save_character_profile(name, p), name


def count(table, name, col="character_name"):
    return db.get_connection().execute(
        f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (name,)).fetchone()[0]


def kv(key):
    row = db.get_connection().execute(
        "SELECT value FROM world_kv WHERE key=?", (key,)).fetchone()
    return (row[0] or "") if row else ""


def set_kv(key, value):
    with db.transaction() as conn:
        conn.execute("INSERT INTO world_kv(key,value) VALUES (?,?) ON CONFLICT(key) "
                     "DO UPDATE SET value=excluded.value", (key, value))


# ── fixture ─────────────────────────────────────────────────────────────────
INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)
for _name in ("Tilda", "Luna", "Obs"):
    assert ch.save_character_profile(
        _name, {"character_name": _name, "template": "human-roleplay"}, create_new=True)
    edit(_name, current_location=INN, current_room="taproom")

from app.core import linked_characters as lc  # noqa: E402
assert lc.create_linked("Tilda", "Glut")["ok"]
_swap = lc.swap_presence("Tilda", "Glut", reason="smoke")
assert _swap["ok"], _swap
assert ch.get_character_status("Tilda") == ch.DORMANT_STATUS

# ── [A] memories ────────────────────────────────────────────────────────────
section("[A] memories")
from app.models import memory as mem  # noqa: E402
mem.add_memory("Glut", "I kissed Luna under the bridge.", memory_type="episodic",
               importance=4)
check("row under Tilda", count("memories", "Tilda"), 1)
check("no row under Glut", count("memories", "Glut"), 0)
_meta = json.loads(db.get_connection().execute(
    "SELECT meta FROM memories WHERE content LIKE 'I kissed%'").fetchone()[0])
check("meta.body", _meta.get("body"), "Glut")
mem.add_memory("Tilda", "I fed the cat.", importance=4)
_by_content = {m["content"]: m for m in mem.load_memories("Tilda")}
guarded("memory_body(kiss)",
        lambda: mem.memory_body(_by_content["I kissed Luna under the bridge."]), "Glut")
guarded("memory_body(cat)", lambda: mem.memory_body(_by_content["I fed the cat."]), "")
check("load_memories(Glut) == load_memories(Tilda)",
      sorted(m["id"] for m in mem.load_memories("Glut")),
      sorted(m["id"] for m in mem.load_memories("Tilda")))
check("leader retrieves the body's memory",
      "I kissed Luna under the bridge." in
      [m["content"] for m in mem.retrieve_relevant_memories("Tilda", "Luna bridge")], True)
_meta = json.loads(db.get_connection().execute(
    "SELECT meta FROM memories WHERE content LIKE 'I kissed%'").fetchone()[0])
check("meta.body survives the retrieval write-back", _meta.get("body"), "Glut")
_section = mem.build_memory_prompt_section("Glut")
check("prompt marks the body memory", "(as Glut) I kissed Luna under the bridge." in _section, True)
check("prompt leaves the mind's own memory unmarked",
      "I fed the cat." in _section and "(as Glut) I fed the cat." not in _section, True)
from app.core import memory_situational  # noqa: E402
check("situational block marks the body",
      "(as Glut) X" in memory_situational.render_block([{"content": "X", "body": "Glut"}]), True)
from app.core import act_engine  # noqa: E402
mem.add_memory("Glut", "I waved.", tags=["act_x"])
check("act window finds the body's tagged memory",
      len(act_engine._tagged_memories_since("Glut", "act_x", "")), 1)
guarded("clear_memories(Glut) refused", lambda: mem.clear_memories("Glut"),
        "raised ValueError: The mind of Glut belongs to Tilda — clear it on Tilda.")
check("Tilda keeps her memories", count("memories", "Tilda"), 3)

# ── [B] thoughts ────────────────────────────────────────────────────────────
section("[B] thoughts")
from app.models import thought_store  # noqa: E402
thought_store.add_thought("Glut", "Nobody may learn it.")
check("no thought row under Glut", count("thoughts", "Glut"), 0)
_rows = thought_store.list_thoughts("Tilda")
check("leader's journal has it", (_rows[0]["content"], _rows[0].get("body")) if _rows else None,
      ("Nobody may learn it.", "Glut"))
check("list_thoughts(Glut) == list_thoughts(Tilda)",
      [r["id"] for r in thought_store.list_thoughts("Glut")], [r["id"] for r in _rows])
from app.core import thought_context  # noqa: E402
check("recent thoughts block marks the body",
      "(as Glut)" in thought_context.recent_thoughts_block("Glut"), True)

# ── [C] secrets ─────────────────────────────────────────────────────────────
section("[C] secrets")
from app.models import secrets  # noqa: E402
_bell = secrets.add_secret("Luna", "Luna stole the bell.")
secrets.add_known_by("Luna", _bell["id"], "Glut", discovered=True)
_bell = secrets.get_secret("Luna", _bell["id"])
check("known_by is the mind", _bell["known_by"], ["Tilda"])
check("discovered_by is the mind", _bell["discovered_by"], ["Tilda"])
guarded("knows(bell, Glut)", lambda: secrets.knows(_bell, "Glut"), True)
guarded("knows(bell, Obs)", lambda: secrets.knows(_bell, "Obs"), False)
check("body knows Luna's secret",
      [e["secret_owner"] for e in secrets.get_known_secrets_about("Glut")], ["Luna"])
_fire = secrets.add_secret("Glut", "I am the fire.")
check("secret stored under Tilda", count("secrets", "Tilda"), 1)
check("no secret row under Glut", count("secrets", "Glut"), 0)
check("secret body", _fire.get("body"), "Glut")
secrets.add_known_by("Glut", _fire["id"], "Luna")
check("Luna learned it on Tilda's row",
      secrets.get_secret("Tilda", _fire["id"])["known_by"], ["Luna"])
check("dormant owner's secret still known",
      [e["secret_owner"] for e in secrets.get_known_secrets_about("Luna")], ["Tilda"])
_block = secrets.known_about_others_block("Luna")
check("named by the body", "About Glut: I am the fire." in _block, True)
check("never the leader's name", "About Tilda" in _block, False)
check("own secret marked in the body's prompt",
      "(as Glut) I am the fire." in secrets.build_secrets_prompt_section("Glut"), True)

# ── [D] diary ───────────────────────────────────────────────────────────────
section("[D] diary")
from app.core.timeutils import game_time  # noqa: E402
from app.models import diary  # noqa: E402
DAY = game_time().day_key()
diary.add_summary("Glut", "Dear diary.", DAY)
_stored = [e for e in diary._load_stored("Tilda") if e.get("content") == "Dear diary."]
check("entry in Tilda's diary", len(_stored), 1)
check("entry marked", (_stored[0].get("metadata") or {}).get("body") if _stored else None, "Glut")
check("no diary row under Glut", count("diary_entries", "Glut"), 0)
check("has_daily_summary(Tilda)", diary.has_daily_summary("Tilda", DAY), True)

# ── [E] consolidation ───────────────────────────────────────────────────────
section("[E] consolidation")
NOW = utc_now()


def iso(delta):
    return (NOW - delta).isoformat()


with db.transaction() as conn:
    conn.execute("INSERT INTO scenes (location_id, room_id, started_ts, last_activity_ts, "
                 "participants, status, summary) VALUES (?,?,?,?,?,?,?)",
                 (INN, "taproom", iso(timedelta(hours=3)), iso(timedelta(hours=2)),
                  json.dumps(["Glut", "Luna"]), "consolidated",
                  "Glut fought the troll with Luna."))
    conn.execute("INSERT INTO scenes (location_id, room_id, started_ts, last_activity_ts, "
                 "participants, status, summary) VALUES (?,?,?,?,?,?,?)",
                 (INN, "taproom", iso(timedelta(minutes=90)), iso(timedelta(hours=1)),
                  json.dumps(["Tilda", "Obs"]), "consolidated", "Tilda baked bread with Obs."))
thought_store.add_thought("Glut", "The troll smelled of rain.", ts=iso(timedelta(minutes=100)))
set_kv("woke_main_sleep:Glut", "x")
set_kv("woke_main_sleep:Tilda", "x")

CALLS = []


class _Resp:
    content = "Recap of the day."


def _fake_llm_call(task="", system_prompt="", user_prompt="", **kw):
    CALLS.append({"task": task, "system": system_prompt, "user": user_prompt,
                  "agent": kw.get("agent_name")})
    return _Resp()


import app.core.llm_router as _llm_router  # noqa: E402
_llm_router.llm_call = _fake_llm_call
from app.core import periodic_jobs  # noqa: E402
periodic_jobs._sub_day_consolidation()
check("one recap call", len(CALLS), 1)
_user = CALLS[0]["user"] if CALLS else ""
check("recap is the mind's", "Scenes of the day for Tilda" in _user, True)
check("body scene marked", "- (as Glut) Glut fought the troll with Luna." in _user, True)
check("leader scene unmarked", "- Tilda baked bread with Obs." in _user, True)
check("body thought marked", "- (as Glut) The troll smelled of rain." in _user, True)
check("flags cleared", (kv("woke_main_sleep:Glut"), kv("woke_main_sleep:Tilda")), ("", ""))
check("daily row under Tilda",
      db.get_connection().execute("SELECT COUNT(*) FROM summaries WHERE character_name='Tilda' "
                                  "AND kind='daily' AND partner=''").fetchone()[0], 1)
check("no summary row under Glut", count("summaries", "Glut"), 0)
check("cursor of the mind", bool(kv("day_cursor:Tilda")), True)
check("no cursor for the body", kv("day_cursor:Glut"), "")
periodic_jobs._sub_day_consolidation()
check("second pass: no further call", len(CALLS), 1)
SUBMITTED = []


class _TQ:
    def submit(self, task_type="", payload=None, **kw):
        SUBMITTED.append((payload or {}).get("character_name"))


import app.core.task_queue as _task_queue  # noqa: E402
_task_queue.get_task_queue = lambda: _TQ()
from app.core import memory_service  # noqa: E402
memory_service.submit_consolidation_for_all()
check("consolidation submitted per mind", sorted(SUBMITTED), ["Luna", "Obs", "Tilda"])
check("handle_memory_consolidation(Glut) works on the mind",
      memory_service.handle_memory_consolidation({"character_name": "Glut"}).get("character"),
      "Tilda")

# ── [F] summaries ───────────────────────────────────────────────────────────
section("[F] summaries")
from app.utils import history_manager as hm  # noqa: E402
hm.save_daily_summary("Glut", "Y0001-D050", "General.")
hm.save_daily_summary("Glut", "Y0001-D050", "Talked with Luna.", partner="Luna")
check("general slot under Tilda",
      db.get_connection().execute("SELECT COUNT(*) FROM summaries WHERE character_name='Tilda' "
                                  "AND date_key='Y0001-D050' AND partner=''").fetchone()[0], 1)
check("partner slot under Glut",
      db.get_connection().execute("SELECT COUNT(*) FROM summaries WHERE character_name='Glut' "
                                  "AND date_key='Y0001-D050' AND partner='Luna'").fetchone()[0], 1)
check("combined over the family", hm.load_daily_summaries_combined("Tilda").get("Y0001-D050"),
      "General.\n(as Glut) With Luna: Talked with Luna.")
check("body's prompt view", hm.load_daily_summaries("Glut").get("Y0001-D050"),
      {"": "General.", "Luna": "Talked with Luna."})
from app.core import chat_retention  # noqa: E402
_daily = chat_retention._summarized_keys("Glut")[0]
_tilda_days = {r[0] for r in db.get_connection().execute(
    "SELECT date_key FROM summaries WHERE character_name='Tilda' AND kind='daily'")}
check("retention sees the mind's days", _tilda_days <= _daily and "Y0001-D050" in _daily, True)
from app.core import character_ops as _cops
_hist = _cops.build_memory_history("Glut", "daily", limit=200)
_d050 = sorted((i["partner"], i["content"]) for i in _hist["items"] if i["date"] == "Y0001-D050")
check("History tab of the body: mind's general entry + own partner row", _d050,
      [("", "General."), ("Luna", "Talked with Luna.")])
_diary_glut = _cops.build_memory_history("Glut", "diary")["total"]
check("History tab diary of the body is the mind's",
      (_diary_glut, _diary_glut >= 1),
      (_cops.build_memory_history("Tilda", "diary")["total"], True))

# ── [G] prompts ─────────────────────────────────────────────────────────────
section("[G] prompts")
from app.routes.chat import _build_chat_prompt  # noqa: E402
LINE = "You are also Tilda — one mind in another body"


def build(speaker, partner):
    return _build_chat_prompt(character_name=speaker, lang_instruction="Respond in English.",
                              history_summary="", tools_enabled=False,
                              agent_config=ch.get_character_config(speaker),
                              partner_override=partner, medium="in_person")


_pg = build("Glut", "Luna")
check("body's system prompt carries the line once", _pg.system.count(LINE), 1)
check("inside the identity block",
      _pg.system.find("=== YOUR IDENTITY ===") < _pg.system.find(LINE), True)
check("not in the scene state", LINE in _pg.moment, False)
check("a mind's own prompt has no line", "You are also" in build("Luna", "Glut").system, False)
from app.core.prompt_templates import render  # noqa: E402
_ctx = thought_context.build_thought_context("Glut")
check("thought ctx linked_leader", _ctx.get("linked_leader"), "Tilda")
check("thought prompt carries the line", LINE in render("chat/agent_thought.md", **_ctx), True)
_ctx_l = thought_context.build_thought_context("Luna")
check("thought ctx unlinked", _ctx_l.get("linked_leader"), "")
check("no line for an unlinked mind", "You are also" in render("chat/agent_thought.md", **_ctx_l),
      False)

# ── [H] resets ──────────────────────────────────────────────────────────────
section("[H] resets")
from app.core import character_reset  # noqa: E402
from app.core.soul_writer import get_soul_file_path  # noqa: E402
_beliefs = get_soul_file_path("Tilda", "beliefs")
_beliefs.parent.mkdir(parents=True, exist_ok=True)
_beliefs.write_text("# Beliefs\n\n## About myself\n- Fire is honest.\n", encoding="utf-8")
_before = {t: count(t, "Tilda") for t in ("memories", "thoughts", "diary_entries")}
_cursor = kv("day_cursor:Tilda")
_res = character_reset.reset_character("Glut", character_reset.SCOPE_MEMORY)
check("mind stores of Tilda untouched",
      {t: count(t, "Tilda") for t in ("memories", "thoughts", "diary_entries")}, _before)
check("leader's beliefs untouched", "Fire is honest." in _beliefs.read_text(encoding="utf-8"),
      True)
check("leader's cursor untouched", kv("day_cursor:Tilda"), _cursor)
check("result says whose mind", any("the mind belongs to Tilda" in k for k in _res["kept"]), True)
check("no intro memory on a body", character_reset.seed_intro_memory("Glut", "I woke up."), 0)
check("still unchanged", count("memories", "Tilda"), _before["memories"])
from app.models import relationship  # noqa: E402
relationship.update_relationship_manual("Luna", "Tilda", strength=40)
from app.core import character_ops  # noqa: E402
check("Mind panel lists the dormant leader",
      "Tilda" in [i["partner"] for i in character_ops.build_memory_relationships("Luna")["items"]],
      True)
from app.routes import characters as char_routes  # noqa: E402


def _status(fn):
    try:
        fn()
        return 200
    except HTTPException as e:
        return e.status_code


check("clear knowledge on a body -> 409",
      _status(lambda: char_routes.clear_character_knowledge("Glut")), 409)
try:
    character_ops.fresh_start_character("Tilda")
    _fresh = "allowed"
except HTTPException as e:
    _fresh = (e.status_code, "revert first" in str(e.detail))
check("fresh start on a dormant leader refused", _fresh, (409, True))
guarded("reset_character(Tilda, reinit) refused",
        lambda: type(character_reset.reset_character("Tilda", character_reset.SCOPE_REINIT)).__name__,
        "raised ValueError: Tilda is dormant — revert first (a fresh start would place "
        "Tilda in the world).")
guarded("wipe the dormant leader",
        lambda: character_ops.wipe_character_memory("Tilda").get("memories"), 4)
check("the mind is empty, body rows included", count("memories", "Tilda"), 0)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print("  failed:", f)
    sys.exit(1)
print("smoke_linked_mind: OK")
