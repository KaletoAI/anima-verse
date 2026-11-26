#!/usr/bin/env python3
"""World Dev free mode — set_skill / restore_skill_config (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 9,
decision E6) and the capability-group rule of plan
docs/superpowers/plans/2026-11-25-world-dev-free-complete-characters-budget.md,
Task 4, decision 9 (cases (G a)-(G j) below).

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
    that read leaves no skills/ directory (reads are side-effect free).
    set_skill{Demo Guard, setlocation, true} while the default is on is NOT
    refused any more (decision 9: refused only when the value is already
    STORED): ok, line "skill setlocation of Demo Guard: on (decided)" (the
    effective state stays on), the file holds {"enabled": true}; the same
    call again -> "already on"; undo complete -> no skills/ dir again.
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

CAPABILITY GROUPS (Task 4, decision 9). The skill manager's list is replaced
by five fake skills whose default comes from default_enabled_for, and
app.plugins.registry.package_of_skill is patched to give the two demo_pair
verbs one package with a capability label; the tools read the REAL config
files of the temp world through character_ops.skill_effective_enabled
(stored "enabled" wins, else the default — the Skills tab's rule):
  demo_on      default on,  no capability
  demo_always  default off, no capability
  demo_off2    default off, no capability
  demo_pair_a  default off, capability demo_pair
  demo_pair_b  default off, capability demo_pair
Groups in loader order: demo_on, demo_always, demo_off2, demo_pair
(members demo_pair_a, demo_pair_b). A group is decided when it is on (every
member on) or every member STORES "enabled" with one value.
(G a) fresh Demo X: open ids == ["demo_always", "demo_off2", "demo_pair"]
    (demo_on is on -> decided); text of the last ==
    "demo_pair (demo_pair_a+demo_pair_b)", of the first "demo_always".
(G b) set_skill{X, demo_always, false} -> ok, line
    "skill demo_always of Demo X: off (decided)" (default off, stays off);
    skills/demo_always.json == {"enabled": false}; open ids ==
    ["demo_off2", "demo_pair"].
(G c) the same call again -> line "error: skill demo_always of Demo X is
    already off".
(G d) discard_preview == [] (a restore is reversible, nothing created);
    undo complete -> file removed and skills/ removed (had_dir False); open
    ids == (G a).
(G f) the smoke writes skills/demo_pair_a.json = {"enabled": true} (the old
    per-verb result) -> "demo_pair" still open (b not stored, group not on).
(G g) set_skill{X, demo_pair_a, true} -> the whole group; a already stores
    true -> only demo_pair_b.json written -> exactly 1 write row (inverse
    skill demo_pair_b, before ABSENT, had_dir True — the dir exists since
    (G f)); line "skill group demo_pair (demo_pair_a+demo_pair_b) of Demo X:
    on" (the group was off, now on); "demo_pair" no longer open.
(G h) fresh Demo Y: set_skill{Y, demo_pair, false} -> 2 write rows in group
    order: demo_pair_a (before ABSENT, had_dir False), demo_pair_b (before
    ABSENT, had_dir True); line "skill group demo_pair
    (demo_pair_a+demo_pair_b) of Demo Y: off (decided)"; open ids ==
    ["demo_always", "demo_off2"]; discard_preview == []; undo complete ->
    both files and skills/ gone, open ids == (G a).
(G i) skill_dependency_block patched to "requires package 'p'" for
    demo_pair_b only -> set_skill{Z, demo_pair, true} on fresh Demo Z ->
    line "error: cannot switch demo_pair on for Demo Z: requires package
    'p'", no write row, no skills/ dir.
(G j) Demo Mix with demo_pair_a.json {"enabled": true} and demo_pair_b.json
    {"enabled": false} written by the smoke -> "demo_pair" open (mixed);
    set_skill{Mix, demo_pair, false} -> 1 write row (demo_pair_a, before =
    the smoke's raw text), "demo_pair" decided (not open); a.json now
    parses as {"enabled": false}.
(G k) Demo Stale with demo_pair_a.json {"enabled": true} written by the
    smoke; skill_dependency_block patched to "requires package 'old'" for
    demo_pair_a only -> set_skill{Stale, demo_pair, true} is NOT refused:
    only the members the call writes are checked, and a already stores true
    -> 1 write row (demo_pair_b, before ABSENT, had_dir True); line "skill
    group demo_pair (demo_pair_a+demo_pair_b) of Demo Stale: on".
(G l) a write that fails partway: save_character_skill_config patched to
    raise RuntimeError("disk full") for demo_pair_b only -> set_skill{Fail,
    demo_pair, true} on fresh Demo Fail raises (a failure, not a refusal,
    goes to the runner); the journal then holds exactly one write row
    (demo_pair_a, before ABSENT, had_dir False) and demo_pair_a.json exists
    with enabled true, demo_pair_b.json does not. discard_preview == [] (a
    restore creates nothing), the turn rollback undo(run, turn=1) is
    complete and reverses exactly that row -> neither demo_pair_a.json nor
    the skills/ dir exists; open ids == (G a).
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
from app.plugins import registry as plugin_registry  # noqa: E402

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
check("(c) storing the default on is ok, (decided)",
      res.ok and res.line == f"skill {SKILL} of {GUARD}: on (decided)", res.line)
check("(c) file holds enabled true",
      f_guard.is_file() and json.loads(f_guard.read_text()) == {"enabled": True})
res = call("set_skill", {"name": GUARD, "skill": SKILL, "enabled": True})
check("(c) stored on -> already on", not res.ok and "already on" in res.line, res.line)
rep = wu.undo(run)
check("(c) undo complete again", rep["complete"], rep)
check("(c) no skills dir after that undo", not SKILLS_GUARD.exists())

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

# ── capability groups (G a)-(G j) ──
FAKE = [("demo_on", True, ""), ("demo_always", False, ""), ("demo_off2", False, ""),
        ("demo_pair_a", False, "demo_pair"), ("demo_pair_b", False, "demo_pair")]


class _FakeSkill:
    ALWAYS_LOAD = False

    def __init__(self, sid, default):
        self.SKILL_ID = sid
        self.name = sid
        self.description = ""
        self._default = default

    def default_enabled_for(self, _name):
        return self._default

    def get_config_fields(self):
        return {}


class _FakePackage:
    def __init__(self, pid):
        self.id = pid
        self.capability_label = "Demo pair"


# Only the fake skills are in the manager from here on, so the groups are
# exactly the five below; their capability comes from a patched
# package_of_skill (the real one for every other id).
get_skill_manager().skills[:] = [_FakeSkill(sid, d) for sid, d, _c in FAKE]
_FAKE_CAP = {sid: c for sid, _d, c in FAKE if c}
_real_package_of_skill = plugin_registry.package_of_skill
plugin_registry.package_of_skill = (
    lambda sid: _FakePackage(_FAKE_CAP[sid]) if sid in _FAKE_CAP
    else _real_package_of_skill(sid))
OPEN_A = ["demo_always", "demo_off2", "demo_pair"]
PAIR_TEXT = "demo_pair (demo_pair_a+demo_pair_b)"


def open_ids(name):
    return [g["id"] for g in wt._open_skill_decisions(name)]


def sdir(name):
    return ch.get_character_dir(name) / "skills"


X, Y, Z, MIX = "Demo X", "Demo Y", "Demo Z", "Demo Mix"
for who in (X, Y, Z, MIX):
    make(who)

# (G a)
run = new_run("groups 1")
ops = wt._open_skill_decisions(X)
check("(G a) open ids", [g["id"] for g in ops] == OPEN_A, ops)
check("(G a) texts", [g.get("text") for g in ops][:1] == ["demo_always"]
      and (ops[-1].get("text") if ops else None) == PAIR_TEXT, ops)
# (G b)
res = call("set_skill", {"name": X, "skill": "demo_always", "enabled": False})
check("(G b) line", res.ok and res.line == f"skill demo_always of {X}: off (decided)", res.line)
fa = sdir(X) / "demo_always.json"
check("(G b) file", fa.is_file() and json.loads(fa.read_text()) == {"enabled": False})
check("(G b) open ids", open_ids(X) == ["demo_off2", "demo_pair"], open_ids(X))
# (G c)
res = call("set_skill", {"name": X, "skill": "demo_always", "enabled": False})
check("(G c) already off", not res.ok
      and res.line == f"error: skill demo_always of {X} is already off", res.line)
# (G d)
check("(G d) discard_preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(G d) undo complete", rep["complete"], rep)
check("(G d) file and dir gone", not fa.exists() and not sdir(X).exists())
check("(G d) open ids == (G a)", open_ids(X) == OPEN_A, open_ids(X))
# (G f)
run = new_run("groups 2")
sdir(X).mkdir(parents=True, exist_ok=True)
(sdir(X) / "demo_pair_a.json").write_text('{"enabled": true}', encoding="utf-8")
check("(G f) one member on leaves the group open", "demo_pair" in open_ids(X), open_ids(X))
# (G g)
res = call("set_skill", {"name": X, "skill": "demo_pair_a", "enabled": True})
check("(G g) line", res.ok and res.line == f"skill group {PAIR_TEXT} of {X}: on", res.line)
w = writes()
inv = (w[0].get("inverse") or {}) if w else {}
check("(G g) exactly one row, for demo_pair_b",
      len(w) == 1 and inv.get("skill") == "demo_pair_b" and wu.is_absent(inv.get("before"))
      and inv.get("had_dir") is True, w)
check("(G g) group decided", "demo_pair" not in open_ids(X), open_ids(X))
# (G h)
run = new_run("groups 3")
res = call("set_skill", {"name": Y, "skill": "demo_pair", "enabled": False})
check("(G h) line", res.ok and res.line == f"skill group {PAIR_TEXT} of {Y}: off (decided)",
      res.line)
w = sorted(writes(), key=lambda e: int(e["seq"]))
invs = [e.get("inverse") or {} for e in w]
check("(G h) two rows, exact inverses",
      [(i.get("skill"), wu.is_absent(i.get("before")), i.get("had_dir")) for i in invs]
      == [("demo_pair_a", True, False), ("demo_pair_b", True, True)], invs)
check("(G h) open ids", open_ids(Y) == ["demo_always", "demo_off2"], open_ids(Y))
check("(G h) discard_preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(G h) undo complete", rep["complete"], rep)
check("(G h) files and dir gone", not sdir(Y).exists())
check("(G h) open ids == (G a)", open_ids(Y) == OPEN_A, open_ids(Y))
# (G i)
run = new_run("groups 4")
character_ops.skill_dependency_block = (
    lambda n, s: "requires package 'p'" if s == "demo_pair_b" else "")
try:
    res = call("set_skill", {"name": Z, "skill": "demo_pair", "enabled": True})
finally:
    character_ops.skill_dependency_block = _real_block
check("(G i) refused", not res.ok
      and res.line == f"error: cannot switch demo_pair on for {Z}: requires package 'p'",
      res.line)
check("(G i) nothing written", writes() == [] and not sdir(Z).exists(), writes())
# (G j)
run = new_run("groups 5")
sdir(MIX).mkdir(parents=True, exist_ok=True)
A_RAW = '{"enabled": true}'
(sdir(MIX) / "demo_pair_a.json").write_text(A_RAW, encoding="utf-8")
(sdir(MIX) / "demo_pair_b.json").write_text('{"enabled": false}', encoding="utf-8")
check("(G j) mixed is open", "demo_pair" in open_ids(MIX), open_ids(MIX))
res = call("set_skill", {"name": MIX, "skill": "demo_pair", "enabled": False})
w = writes()
inv = (w[0].get("inverse") or {}) if w else {}
check("(G j) one row for demo_pair_a, before = the raw text",
      res.ok and len(w) == 1 and inv.get("skill") == "demo_pair_a"
      and inv.get("before") == A_RAW, (res.line, w))
check("(G j) decided", "demo_pair" not in open_ids(MIX), open_ids(MIX))
check("(G j) a now off",
      json.loads((sdir(MIX) / "demo_pair_a.json").read_text()) == {"enabled": False})
# (G k)
run = new_run("groups 6")
STALE = "Demo Stale"
make(STALE)
sdir(STALE).mkdir(parents=True, exist_ok=True)
(sdir(STALE) / "demo_pair_a.json").write_text('{"enabled": true}', encoding="utf-8")
character_ops.skill_dependency_block = (
    lambda n, s: "requires package 'old'" if s == "demo_pair_a" else "")
try:
    res = call("set_skill", {"name": STALE, "skill": "demo_pair", "enabled": True})
finally:
    character_ops.skill_dependency_block = _real_block
check("(G k) not refused", res.ok and res.line == f"skill group {PAIR_TEXT} of {STALE}: on",
      res.line)
w = writes()
inv = (w[0].get("inverse") or {}) if w else {}
check("(G k) one row for demo_pair_b",
      len(w) == 1 and inv.get("skill") == "demo_pair_b" and wu.is_absent(inv.get("before"))
      and inv.get("had_dir") is True, w)
# (G l)
run = new_run("groups 7")
FAIL = "Demo Fail"
make(FAIL)
_real_save_skill = ch.save_character_skill_config


def _failing_save(n, s, cfg):
    if s == "demo_pair_b":
        raise RuntimeError("disk full")
    return _real_save_skill(n, s, cfg)


ch.save_character_skill_config = _failing_save
raised = None
try:
    call("set_skill", {"name": FAIL, "skill": "demo_pair", "enabled": True})
except RuntimeError as exc:
    raised = exc
finally:
    ch.save_character_skill_config = _real_save_skill
check("(G l) the failure reaches the runner", str(raised) == "disk full", raised)
w = writes()
inv = (w[0].get("inverse") or {}) if w else {}
check("(G l) one write row, for demo_pair_a",
      len(w) == 1 and inv.get("skill") == "demo_pair_a" and wu.is_absent(inv.get("before"))
      and inv.get("had_dir") is False, w)
fa = sdir(FAIL) / "demo_pair_a.json"
check("(G l) a written, b not",
      fa.is_file() and json.loads(fa.read_text()).get("enabled") is True
      and not (sdir(FAIL) / "demo_pair_b.json").exists())
check("(G l) discard_preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run, turn=1)
check("(G l) turn rollback complete, exactly that row",
      rep["complete"] and rep["reversed"] == [w[0]["seq"] if w else None], rep)
check("(G l) neither a.json nor skills/ left", not fa.exists() and not sdir(FAIL).exists())
check("(G l) open ids == (G a)", open_ids(FAIL) == OPEN_A, open_ids(FAIL))

if failures:
    print(f"FAIL smoke_world_dev_skills: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("PASS smoke_world_dev_skills")
