#!/usr/bin/env python3
"""World Dev free mode — set_skill / restore_skill_config (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 9,
decision E6).

Usage: ./.venv/bin/python scripts/smoke_world_dev_skills.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR temp,
paths.init before any world-DB import), no server, no LLM. Tool calls go
through world_dev_tools.run_tool exactly as the agent loop calls them.

WHAT IS CHECKED, and where every expected value comes from:

Skill: `setlocation` — plugins/movement/plugin.yaml declares it (package
`movement`, `enabled_default: true`, so the skill manager of a temp world
loads it), class SetLocationSkill in plugins/movement/skill_set_location.py
has no ALWAYS_LOAD, so its default without a character setting is ON
(PluginSkill.default_enabled_for = not ALWAYS_LOAD; the same rule
character_ops.build_available_skills applies). Its display name is read from
the loaded skill (the one runtime-read value; source: skill.name).

The temp instance has no package list: `packages.enabled` is patched to
"movement" while the skill manager loads (the smoke_new_character_skills way).

Fixture: Demo Guard and Demo Cook, created with save_character_profile
(create_new); their `skills/` directories are removed when the creation
left them empty, so neither has a skill config file.

(a) set_skill{Demo Guard, setlocation, false} -> ok, line
    "skill setlocation of Demo Guard: off"; skills/setlocation.json parses
    as {"enabled": false} (the writer: {**{} , "enabled": false});
    build_available_skills reports setlocation disabled; one write row,
    target ("character", "Demo Guard"), inverse op restore_skill_config with
    before ABSENT and had_dir False. get_character{fields:["skills"]} has the
    line "setlocation off (set)"; list_catalog{name:"skills"} has the line
    "setlocation — <skill name>".
(b) the same call again -> refused "already off"; skill "nope" -> refused,
    the line points to list_catalog; enabled "no" (a string) -> refused;
    unknown character -> refused; no new write row.
(c) discard_preview -> [] (a restore, nothing the run created); undo ->
    complete; skills/setlocation.json absent again, and the skills/
    directory is gone (there was none before: had_dir False, empty now).
    get_character skills line is "setlocation on (default)" afterwards, and
    that read leaves no skills/ directory (reads are side-effect free); a
    refused set_skill{Demo Guard, setlocation, true} ("already on" — the
    default is on) leaves none either.
(d) new run: Demo Cook's file written as the bytes
    b'{"x":1,  "enabled":true}\\n' (compact, odd spacing — not the writer's
    indent-2 format) -> set off -> the file parses as {"x": 1, "enabled":
    false} (other keys kept) -> undo complete -> the file BYTES equal the
    fixture bytes.
(e) new run: set Demo Guard off, then the toggle route body
    _toggle_character_skill_sync(Demo Guard, setlocation, {"enabled": True})
    -> discard_preview is exactly ["Demo Guard: skill setlocation was changed
    since — the discard leaves it alone"] (the line mirrors the undo's skip)
    -> undo not complete, one skip "changed since" with keys ["setlocation"];
    the file still holds enabled true (the route's write is never clobbered).
(f) Demo Cook's file written as b'{not json' -> set_skill on -> refused
    "not readable"; the file bytes unchanged; no write row. The same for
    b'[1]' (JSON, but no object).
(g) enabling while character_ops.skill_dependency_block (patched) answers
    "requires package 'demo_pkg'" -> refused with that text, nothing written.
(h) the toggle route takes keyed_lock("skill_config", name): while this
    thread holds the lock, the route body in another thread does not finish
    within 0.5 s; released, it finishes.
(i) save_character_skill_config itself takes that lock (every writer, not
    only the routes): the same hold-and-release test with a direct
    save_character_skill_config(Demo Cook, setlocation, {"enabled": true}).
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_skills_"))
atexit.register(shutil.rmtree, ROOT, True)
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

from app.core import character_ops  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.dependencies import get_skill_manager  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models import character as ch  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


SKILL = "setlocation"
GUARD, COOK = "Demo Guard", "Demo Cook"
# The package list is instance config; the temp instance has none, so the
# movement package is enabled the way smoke_new_character_skills does it.
_real_get = config.get
with patch("app.core.config.get", side_effect=lambda key, default=None:
           "movement" if key == "packages.enabled" else _real_get(key, default)):
    loaded = {s.SKILL_ID: s for s in get_skill_manager().skills if s.SKILL_ID}
check("fixture: setlocation is loaded", SKILL in loaded, sorted(loaded))
SKILL_NAME = loaded[SKILL].name if SKILL in loaded else ""


def skills_dir(name):
    return paths.get_storage_dir() / "characters" / name / "skills"


def make(name):
    ok = ch.save_character_profile(name, {"template": "human-roleplay"}, create_new=True)
    check(f"fixture: {name} created", ok)
    d = ch.get_character_dir(name) / "skills"
    if d.is_dir() and not any(d.iterdir()):
        d.rmdir()


make(GUARD)
make(COOK)
SKILLS_GUARD = ch.get_character_dir(GUARD) / "skills"
SKILLS_COOK = ch.get_character_dir(COOK) / "skills"
check("fixture: no skills dir for Demo Guard", not SKILLS_GUARD.exists())


def new_run(label):
    open_ = wr.open_run()
    if open_:
        wr.set_status(open_["id"], "accepted")
    return wr.create_run(label, "m", "p", "u", 80, 300000)


run = new_run("skills 1")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def effective(name):
    entry = next(s for s in character_ops.build_available_skills(name)["skills"]
                 if s["skill_id"] == SKILL)
    return entry["enabled"]


# (a)
res = call("set_skill", {"name": GUARD, "skill": SKILL, "enabled": False})
check("(a) ok", res.ok and res.wrote, res.line)
check("(a) line", res.line == f"skill {SKILL} of {GUARD}: off", res.line)
f_guard = SKILLS_GUARD / f"{SKILL}.json"
check("(a) file holds enabled false",
      f_guard.is_file() and json.loads(f_guard.read_text()) == {"enabled": False},
      f_guard.read_text() if f_guard.is_file() else None)
check("(a) build_available_skills: off", effective(GUARD) is False)
w = writes()
inv = (w[0].get("inverse") or {}) if w else {}
check("(a) one write row, restore_skill_config",
      len(w) == 1 and w[0].get("target_kind") == "character"
      and w[0].get("target_id") == GUARD and inv.get("op") == "restore_skill_config"
      and wu.is_absent(inv.get("before")) and inv.get("had_dir") is False,
      w)
res = call("get_character", {"name": GUARD, "fields": ["skills"]})
check("(a) get_character skills: off (set)", f"{SKILL} off (set)" in res.line.split("\n"),
      res.line)
res = call("list_catalog", {"name": "skills"})
check("(a) list_catalog skills", f"{SKILL} — {SKILL_NAME}" in res.line.split("\n"), res.line)

# (b)
res = call("set_skill", {"name": GUARD, "skill": SKILL, "enabled": False})
check("(b) already off", not res.ok and "already off" in res.line, res.line)
res = call("set_skill", {"name": GUARD, "skill": "nope", "enabled": False})
check("(b) unknown skill", not res.ok and "list_catalog" in res.line, res.line)
res = call("set_skill", {"name": GUARD, "skill": SKILL, "enabled": "no"})
check("(b) enabled must be a bool", not res.ok, res.line)
res = call("set_skill", {"name": "Demo Nobody", "skill": SKILL, "enabled": True})
check("(b) unknown character", not res.ok, res.line)
check("(b) no new write row", len(writes()) == 1, len(writes()))

# (c)
check("(c) discard_preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(c) undo complete", rep["complete"], rep)
check("(c) file absent again", not f_guard.exists())
check("(c) no skills dir left behind", not SKILLS_GUARD.exists())
res = call("get_character", {"name": GUARD, "fields": ["skills"]})
check("(c) get_character skills: on (default)",
      f"{SKILL} on (default)" in res.line.split("\n"), res.line)
check("(c) the skills read leaves no skills dir", not SKILLS_GUARD.exists())
res = call("set_skill", {"name": GUARD, "skill": SKILL, "enabled": True})
check("(c) already on refused", not res.ok and "already on" in res.line, res.line)
check("(c) the refused call leaves no skills dir", not SKILLS_GUARD.exists())

# (d)
run = new_run("skills 2")
SKILLS_COOK.mkdir(parents=True, exist_ok=True)
f_cook = SKILLS_COOK / f"{SKILL}.json"
FIXTURE = b'{"x":1,  "enabled":true}\n'
f_cook.write_bytes(FIXTURE)
res = call("set_skill", {"name": COOK, "skill": SKILL, "enabled": False})
check("(d) ok", res.ok and res.wrote, res.line)
check("(d) other keys kept", json.loads(f_cook.read_text()) == {"x": 1, "enabled": False},
      f_cook.read_text())
rep = wu.undo(run)
check("(d) undo complete", rep["complete"], rep)
check("(d) bytes equal the fixture", f_cook.read_bytes() == FIXTURE, f_cook.read_bytes())

# (e)
run = new_run("skills 3")
res = call("set_skill", {"name": GUARD, "skill": SKILL, "enabled": False})
check("(e) ok", res.ok and res.wrote, res.line)
from app.routes.characters import _toggle_character_skill_sync  # noqa: E402

_toggle_character_skill_sync(GUARD, SKILL, {"enabled": True})
prev = wu.discard_preview(run)
check("(e) discard_preview names the switch changed since",
      prev == [f"{GUARD}: skill {SKILL} was changed since — the discard leaves it alone"],
      prev)
rep = wu.undo(run)
skips = rep.get("skipped") or []
check("(e) undo not complete, changed since [setlocation]",
      not rep["complete"] and len(skips) == 1
      and skips[0].get("reason") == wu.REASON_CHANGED
      and skips[0].get("keys") == [SKILL], rep)
check("(e) the route's write stays", json.loads(f_guard.read_text()) == {"enabled": True},
      f_guard.read_text())

# (f)
run = new_run("skills 4")
for raw in (b"{not json", b"[1]"):
    f_cook.write_bytes(raw)
    res = call("set_skill", {"name": COOK, "skill": SKILL, "enabled": True})
    check(f"(f) {raw!r} refused not readable", not res.ok and "not readable" in res.line,
          res.line)
    check(f"(f) {raw!r} bytes unchanged", f_cook.read_bytes() == raw, f_cook.read_bytes())
check("(f) no write row", writes() == [], writes())

# (g)
f_cook.write_bytes(b'{"enabled": false}')
_real_block = character_ops.skill_dependency_block
character_ops.skill_dependency_block = lambda n, s: "requires package 'demo_pkg'"
try:
    res = call("set_skill", {"name": COOK, "skill": SKILL, "enabled": True})
finally:
    character_ops.skill_dependency_block = _real_block
check("(g) dependency refusal", not res.ok and "requires package 'demo_pkg'" in res.line,
      res.line)
check("(g) nothing written", f_cook.read_bytes() == b'{"enabled": false}' and writes() == [])

# (h)
done = threading.Event()


def _route():
    _toggle_character_skill_sync(COOK, SKILL, {"enabled": False})
    done.set()


with keyed_lock("skill_config", COOK):
    t = threading.Thread(target=_route)
    t.start()
    t.join(0.5)
    check("(h) the route waits for the skill_config lock", not done.is_set())
t.join(5)
check("(h) the route finishes once released", done.is_set())

# (i)
done_i = threading.Event()


def _save():
    ch.save_character_skill_config(COOK, SKILL, {"enabled": True})
    done_i.set()


with keyed_lock("skill_config", COOK):
    t = threading.Thread(target=_save)
    t.start()
    t.join(0.5)
    check("(i) save_character_skill_config waits for the lock", not done_i.is_set())
t.join(5)
check("(i) it finishes once released",
      done_i.is_set() and json.loads(f_cook.read_text()) == {"enabled": True},
      f_cook.read_text())

if failures:
    print(f"FAIL smoke_world_dev_skills: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("PASS smoke_world_dev_skills")
