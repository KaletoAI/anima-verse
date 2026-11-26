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

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("ALL OK")
