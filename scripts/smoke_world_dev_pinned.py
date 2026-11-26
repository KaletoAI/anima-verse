#!/usr/bin/env python3
"""Smoke: World Dev free mode — pinned reference reads and the token budget.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_pinned.py

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md,
Task 10 (gap 9). A temp world (paths.init BEFORE any world-DB import); no
server, no LLM: RunManager._add_result is driven directly on a fresh
_RunState, exactly as the agent loop calls it (tool, line, parsed args).

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Rules (plan Task 10 "Produces"): read_manual and describe_template are
pinned (ToolSpec.pinned), world_overview is not. A pinned result is never
shrunk; a newer result of the same tool with the same args (key = tool +
json.dumps(args, sort_keys=True)) turns the older copy into the stub
"[result <tool>] (superseded — see the later copy)". Every other read result
outside the newest KEEP_RESULTS = 4 results becomes
"[result <tool>] (shrunk — call again if needed)"; pinned results still
count among the newest 4.

(0) spec flags: read_manual pinned, describe_template pinned,
    world_overview not pinned; DEFAULT_MAX_TOKENS_TOTAL == 600000 (D9).
(a) manual(characters) "M1", then world_overview "O1".."O5": 6 results,
    newest 4 = O2..O5, results[:-4] = [M1, O1]. M1 pinned -> whole; O1 ->
    shrunk stub. Contents in order: M1 whole, O1 stub, O2..O5 whole
    (1 stub).
(b) then manual(characters) again "M2": 7 results, newest 4 = O3, O4, O5,
    M2; results[:-4] = [M1, O1, O2]. M1 has M2's key -> superseded stub;
    O1 stays shrunk, O2 now shrunk; M2 whole. Contents: M1 superseded, O1
    stub, O2 stub, O3, O4, O5 whole, M2 whole (3 stubs).
(c) then manual(homes) "H1": key differs from M2 (section homes), so M2 is
    NOT superseded; 8 results, newest 4 = O4, O5, M2, H1; O3 now shrunk.
    M2 and H1 whole; stubs M1 (superseded), O1, O2, O3 (shrunk) = 4 stubs.
(d) describe_template {"template": "human-roleplay"} "D1", then
    {"template": "human-roleplay", "gender": "female"} "D2", then the same two
    keys in the other order "D3": D3 has D2's key (sort_keys) -> D2
    superseded; D1 has other args -> whole. Contents: D1, D2 stub, D3.
(e) only an ok result is pinned: read_manual{characters} refused
    (ok=False, line "error: no such section") "E1", then world_overview
    "Q1".."Q4": 5 results, newest 4 = Q1..Q4, results[:-4] = [E1]; E1 is not
    pinned (_pinned False) -> shrunk stub. Then an ok read_manual{characters}
    "K1": the refused E1 is not a pinned copy, so it stays the shrunk stub
    (not "superseded"); K1 whole.
(f) a rollback cut restores a superseded copy whose newer copy is gone:
    turn 1 read_manual{characters} "T1"; mark = index of the next user
    message "turn 2" (appended by hand, as message() does); turn 2
    read_manual{characters} "T2" -> T1 superseded, _orig "[result
    read_manual] T1". Cut as _fail does for turn 2 (del history[mark + 1:])
    and RunManager._restore_superseded -> T1 reads "[result read_manual] T1"
    again, _superseded False. A copy whose newer copy SURVIVES the cut stays
    a stub: U1, U2 both before the mark, cut after -> U1 superseded, U2
    whole. A chain of three: A1 (turn 1), A2 (turn 2, kept), A3 (turn 3,
    cut) -> the NEWEST surviving copy A2 is restored, A1 stays a stub:
    [superseded, whole A2]. The loop path of both (the _loop call sites pass the parsed args
    and _fail restores) is smoke_world_dev_agent.py (z).
(g) smoke_world_dev_free_routes.py 2 expects max_tokens_total 600000 and
    smoke_world_dev_agent.py (u) 40 / 600000 (updated in this task); (k)
    there still shrinks world_overview (not pinned) — run them in the
    regression set.
(h) manual render (plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-
    terrain.md, Task 8): read_manual renders each section through the tool's
    own function (no run needed — the read writes nothing).
    locations: a "## NPC slots" section naming the seven keys normalize_slot
    reads besides template/briefing (role, count_min, count_max, when, room,
    radius_m, character), the count range 0…20 (npc_spawn.normalize_slot
    _count: max(0, min(20, int(value)))), the "day"/"night"/"HH:MM-HH:MM"
    windows (npc_windows.normalize_when), when a slot fits versus a full
    character (create_character), and "there is no fill tool" (E7).
    map: area slots need a label and take no room / radius_m.
    characters: one line pointing to slots (npc_slots, read_manual
    locations) for crowds.
    Behaviour behind the documented range: the manual's "whole <lo>…<hi>"
    is parsed, and npc_spawn.normalize_slot must store count_min <hi>+1 as
    <hi> (min(20, ...) clamps 21 to 20) and count_min -1 as <lo> (max(0, ...)
    clamps to 0) — so a moved cap in the code no longer matches the text.
(i) a pinned read is capped in the history (plan
    docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md, Task 8, F8a):
    MAX_PINNED_CHARS = 16000 (the longest shipped manual is 12534 characters
    — manual_map.md after this task — so every manual stays whole).
    read_manual{map} with a line of 20000 "x" -> content ==
    "[result read_manual] " (21 characters) + 16000 "x" +
    "\n[cut — 16000 of 20000 characters kept]". A line of 12 399 characters
    stays whole: content length 21 + 12 399 = 12 420. A non-pinned read
    (world_overview, 20000 "y") is stored whole (21 + 2 = "[result
    world_overview] " is 24 characters: 24 + 20000 = 20024). Every shipped
    manual section (each of wt.MANUAL_SECTIONS, so a new section is covered
    too), rendered through read_manual, is <= 16000 characters.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_pinned_clips_")

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_pinned_"))
paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"  -> {detail!r}"))
    if not cond:
        failures.append(label)


SHRUNK = "(shrunk — call again if needed)"
SUPERSEDED = "(superseded — see the later copy)"


def shrunk(tool):
    return f"[result {tool}] {SHRUNK}"


def superseded(tool):
    return f"[result {tool}] {SUPERSEDED}"


def whole(tool, line):
    return f"[result {tool}] {line}"


def contents(st):
    return [m["content"] for m in st.history if m.get("_result")]


def stubs(st):
    return sum(1 for c in contents(st) if c.endswith(SHRUNK) or c.endswith(SUPERSEDED))


print("(0) spec flags and budget")
check("(0) read_manual pinned", getattr(wt.TOOLS["read_manual"], "pinned", None) is True)
check("(0) describe_template pinned",
      getattr(wt.TOOLS["describe_template"], "pinned", None) is True)
check("(0) world_overview not pinned",
      getattr(wt.TOOLS["world_overview"], "pinned", None) is False)
check("(0) DEFAULT_MAX_TOKENS_TOTAL 600000", wa.DEFAULT_MAX_TOKENS_TOTAL == 600_000,
      wa.DEFAULT_MAX_TOKENS_TOTAL)

rm = wa.RunManager()
st = wa._RunState()
CHARS = {"section": "characters"}
HOMES = {"section": "homes"}
MAN, OV, DT = "read_manual", "world_overview", "describe_template"

print("(a) a pinned manual survives the newest-4 rule")
rm._add_result(st, MAN, "M1", CHARS)
for i in range(1, 6):
    rm._add_result(st, OV, f"O{i}", {})
exp_a = [whole(MAN, "M1"), shrunk(OV)] + [whole(OV, f"O{i}") for i in range(2, 6)]
check("(a) contents", contents(st) == exp_a, contents(st))
check("(a) 1 stub", stubs(st) == 1, stubs(st))

print("(b) the same manual again supersedes the older copy")
rm._add_result(st, MAN, "M2", dict(CHARS))
exp_b = ([superseded(MAN), shrunk(OV), shrunk(OV)]
         + [whole(OV, f"O{i}") for i in range(3, 6)] + [whole(MAN, "M2")])
check("(b) contents", contents(st) == exp_b, contents(st))
check("(b) 3 stubs", stubs(st) == 3, stubs(st))

print("(c) another section is a different key")
rm._add_result(st, MAN, "H1", HOMES)
exp_c = ([superseded(MAN), shrunk(OV), shrunk(OV), shrunk(OV)]
         + [whole(OV, "O4"), whole(OV, "O5"), whole(MAN, "M2"), whole(MAN, "H1")])
check("(c) contents", contents(st) == exp_c, contents(st))
check("(c) 4 stubs", stubs(st) == 4, stubs(st))

print("(d) describe_template: key order does not matter, other args do")
st2 = wa._RunState()
rm._add_result(st2, DT, "D1", {"template": "human-roleplay"})
rm._add_result(st2, DT, "D2", {"template": "human-roleplay", "gender": "female"})
rm._add_result(st2, DT, "D3", {"gender": "female", "template": "human-roleplay"})
exp_d = [whole(DT, "D1"), superseded(DT), whole(DT, "D3")]
check("(d) contents", contents(st2) == exp_d, contents(st2))

print("(e) a refused reference read is not pinned")
st3 = wa._RunState()
rm._add_result(st3, MAN, "error: no such section", CHARS, ok=False)
check("(e) refused result not pinned", st3.history[-1]["_pinned"] is False,
      st3.history[-1])
for i in range(1, 5):
    rm._add_result(st3, OV, f"Q{i}", {})
check("(e) refused manual shrunk outside the newest 4",
      contents(st3)[0] == shrunk(MAN), contents(st3)[0])
rm._add_result(st3, MAN, "K1", CHARS)
check("(e) an ok read does not supersede the refused one",
      contents(st3)[0] == shrunk(MAN) and contents(st3)[-1] == whole(MAN, "K1"),
      contents(st3))

print("(f) a rollback cut restores the older copy")
st4 = wa._RunState()
rm._add_result(st4, MAN, "T1", CHARS)
st4.history.append({"role": "user", "content": "turn 2"})
mark = len(st4.history) - 1
rm._add_result(st4, MAN, "T2", dict(CHARS))
check("(f) T1 superseded before the cut", contents(st4)[0] == superseded(MAN),
      contents(st4))
del st4.history[mark + 1:]
wa.RunManager._restore_superseded(st4)
check("(f) T1 whole again after the cut", contents(st4) == [whole(MAN, "T1")],
      contents(st4))
check("(f) T1 no longer marked superseded", st4.history[0].get("_superseded") is False,
      st4.history[0])
st5 = wa._RunState()
rm._add_result(st5, MAN, "U1", CHARS)
rm._add_result(st5, MAN, "U2", CHARS)
st5.history.append({"role": "user", "content": "turn 2"})
mark = len(st5.history) - 1
rm._add_result(st5, MAN, "U3", HOMES)
del st5.history[mark + 1:]
wa.RunManager._restore_superseded(st5)
check("(f) a surviving newer copy keeps the older stub",
      contents(st5) == [superseded(MAN), whole(MAN, "U2")], contents(st5))
st6 = wa._RunState()
rm._add_result(st6, MAN, "A1", CHARS)
st6.history.append({"role": "user", "content": "turn 2"})
rm._add_result(st6, MAN, "A2", dict(CHARS))
st6.history.append({"role": "user", "content": "turn 3"})
mark = len(st6.history) - 1
rm._add_result(st6, MAN, "A3", dict(CHARS))
del st6.history[mark + 1:]
wa.RunManager._restore_superseded(st6)
check("(f) chain of three: the newest surviving copy A2 is restored",
      contents(st6) == [superseded(MAN), whole(MAN, "A2")], contents(st6))
check("(f) chain of three: A1 stays superseded",
      st6.history[0].get("_superseded") is True, st6.history[0])

print("(h) manual render: NPC slots")
_manual = wt.TOOLS["read_manual"].fn


def manual(section):
    return _manual(None, {"section": section})


_loc = manual("locations")
_sec = _loc.split("## NPC slots", 1)[1].split("\n## ", 1)[0] if "## NPC slots" in _loc else ""
check("(h) locations has a '## NPC slots' section", bool(_sec), _loc[-400:])
for _key in ("role", "count_min", "count_max", "when", "room", "radius_m", "character"):
    check(f"(h) NPC slots names `{_key}`", f"`{_key}`" in _sec)
check("(h) NPC slots: counts 0…20", "0…20" in _sec, _sec[:400])
import re  # noqa: E402
from app.core import npc_spawn  # noqa: E402
_rng = re.search(r"whole (\d+)…(\d+)", _sec)
check("(h) NPC slots: the count range is written 'whole <lo>…<hi>'", bool(_rng), _sec[:400])
if _rng:
    _lo, _hi = int(_rng.group(1)), int(_rng.group(2))
    _above = npc_spawn.normalize_slot({"role": "probe", "count_min": _hi + 1}) or {}
    check(f"(h) normalize_slot: count_min {_hi + 1} is stored as {_hi} (manual's cap)",
          _above.get("count_min") == _hi, _above)
    _below = npc_spawn.normalize_slot({"role": "probe", "count_min": _lo - 1}) or {}
    check(f"(h) normalize_slot: count_min {_lo - 1} is stored as {_lo} (manual's floor)",
          _below.get("count_min") == _lo, _below)
check("(h) NPC slots: windows day/night/HH:MM-HH:MM",
      all(w in _sec for w in ('"day"', '"night"', '"HH:MM-HH:MM"')), _sec[:400])
check("(h) NPC slots: slot vs full character (create_character)",
      "create_character" in _sec and "staff" in _sec, _sec[:600])
check("(h) NPC slots: there is no fill tool", "there is no fill tool" in _sec, _sec[:600])
_map = manual("map")
check("(h) map: area slots need a label, no room / radius_m",
      "npc_slots" in _map and "needs a `label`" in _map
      and "without `room` and `radius_m`" in _map)
_chars = manual("characters")
check("(h) characters: crowds point to npc_slots",
      "npc_slots" in _chars and "read_manual locations" in _chars)

print("(i) pinned reads are capped in the history")
check("(i) MAX_PINNED_CHARS 16000", getattr(wa, "MAX_PINNED_CHARS", None) == 16000,
      getattr(wa, "MAX_PINNED_CHARS", None))
st7 = wa._RunState()
rm._add_result(st7, MAN, "x" * 20000, {"section": "map"})
_want = "[result read_manual] " + "x" * 16000 + "\n[cut — 16000 of 20000 characters kept]"
check("(i) a 20000-character manual is cut to 16000", contents(st7)[-1] == _want,
      (len(contents(st7)[-1]), contents(st7)[-1][-60:]))
rm._add_result(st7, MAN, "z" * 12399, {"section": "characters"})
check("(i) a 12 399-character manual stays whole", len(contents(st7)[-1]) == 12420
      and contents(st7)[-1] == "[result read_manual] " + "z" * 12399, len(contents(st7)[-1]))
rm._add_result(st7, OV, "y" * 20000, {})
check("(i) a non-pinned read is not capped", len(contents(st7)[-1]) == 20024,
      len(contents(st7)[-1]))
for _section in wt.MANUAL_SECTIONS:
    try:
        _len = len(manual(_section))
    except Exception as exc:  # noqa: BLE001 - a missing section is reported, not raised
        _len = repr(exc)
    check(f"(i) manual {_section} fits MAX_PINNED_CHARS",
          isinstance(_len, int) and _len <= 16000, _len)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("ALL OK")
