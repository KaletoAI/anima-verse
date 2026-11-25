#!/usr/bin/env python3
"""Chat-state stats: an omitted pair is "no effect", the delivered pairs apply;
and each stat source of extraction_chat_state starts on its own line.

Usage: ./.venv/bin/python scripts/smoke_chat_stat_omission.py
No server, no LLM. Storage is a temp dir, initialised before any world-DB
module is imported.

Background (2026-11-25): a 9B model asked for the pairs (S0,T0) and (S1,T0)
regularly answered only (S0,T0); the parser then threw the WHOLE stat part
away, the valid pair included (35 lost evaluations in five days).

Part A -- parse_stat_results on a hand-built pair map with two required
pairs (S0,T0) and (S1,T0), stat key "calm" allowed for both:
  [1] only (S0,T0) with {"calm": 2} -> exactly that one result returned
      (recipient "Bo", deltas {"calm": 2}); one WARNING naming "S1/T0".
  [2] {"stat_results": []} -> [] and one WARNING naming both pairs.
  [3] both pairs delivered -> 2 results, no WARNING.
  Hard errors stay hard (ValueError): an unknown token ("S9"), a repeated
  pair, a foreign key ("extra"), an invalid delta (1.5, True, 101), a
  missing deltas object, stat_results not a list, the legacy {"stats":...}.
  A valid pair next to an invalid one still raises (no partial result).

Part B -- the template's user part rendered with the loader's own Jinja options
(trim_blocks / lstrip_blocks / keep_trailing_newline read off
prompt_templates._env) and two stat sources:
  S0 actor "Ann", medium "speech", text "Hello there."
  S1 actor ""    , medium "self"  , text "Walked away."
  Expected rendered lines, in this order and each a line of its own:
    "S0 — actor: Ann; medium: speech"
    "Hello there."
    "S1 — actor: self / unattributed; medium: self"
    "Walked away."
  Before the fix trim_blocks ate the newline after {% endif %} and the
  second header was glued to the first text: "Hello there.S1 — actor: ...".
"""
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


with tempfile.TemporaryDirectory() as tmp:
    paths.init(Path(tmp))
    from app.core import chat_stat_effects  # noqa: E402
    from app.core.chat_stat_effects import parse_stat_results  # noqa: E402

    records = []

    class _H(logging.Handler):
        def emit(self, rec):
            if rec.levelno >= logging.WARNING:
                records.append(rec.getMessage())

    logging.getLogger(chat_stat_effects.logger.name).addHandler(_H())

    src0, src1 = object(), object()
    targets = {"pair_map": {
        ("S0", "T0"): {"source": src0, "recipient": "Bo", "keys": {"calm"}},
        ("S1", "T0"): {"source": src1, "recipient": "Bo", "keys": {"calm"}},
    }}

    def pair(event, deltas, target="T0"):
        return {"event": event, "target": target, "deltas": deltas}

    print("[A] parser")
    records.clear()
    got = parse_stat_results({"stat_results": [pair("S0", {"calm": 2})]}, targets)
    ok("[1] omitted S1 -> the delivered S0 pair applies",
       len(got) == 1 and got[0]["source"] is src0 and got[0]["recipient"] == "Bo"
       and got[0]["deltas"] == {"calm": 2}, repr(got))
    ok("[1] one WARNING naming S1/T0",
       len(records) == 1 and "S1/T0" in records[0] and "S0/T0" not in records[0], repr(records))

    records.clear()
    got = parse_stat_results({"stat_results": []}, targets)
    ok("[2] empty list -> []", got == [], repr(got))
    ok("[2] WARNING names both pairs",
       len(records) == 1 and "S0/T0" in records[0] and "S1/T0" in records[0], repr(records))

    records.clear()
    got = parse_stat_results({"stat_results": [pair("S0", {}), pair("S1", {"calm": -3})]}, targets)
    ok("[3] both pairs -> 2 results, no warning",
       len(got) == 2 and got[1]["deltas"] == {"calm": -3} and not records, repr((got, records)))

    hard = [
        {"stat_results": [pair("S9", {})]},
        {"stat_results": [pair("S0", {}), pair("S0", {})]},
        {"stat_results": [dict(pair("S0", {}), extra=1)]},
        {"stat_results": [pair("S0", {"calm": 1.5})]},
        {"stat_results": [pair("S0", {"calm": True})]},
        {"stat_results": [pair("S0", {"calm": 101})]},
        {"stat_results": [pair("S0", {"other": 1})]},
        {"stat_results": [{"event": "S0", "target": "T0"}]},
        {"stat_results": {}},
        {"stats": {"calm": 3}},
        {"stat_results": [pair("S0", {"calm": 1}), pair("S1", {}, target="T7")]},
    ]
    refused = 0
    for bad in hard:
        try:
            parse_stat_results(bad, targets)
        except ValueError:
            refused += 1
        else:
            print("     accepted:", bad)
    ok(f"hard errors stay hard ({refused}/{len(hard)})", refused == len(hard))

    print("[B] template")
    from jinja2.sandbox import SandboxedEnvironment  # noqa: E402
    from jinja2 import ChainableUndefined  # noqa: E402
    from app.core import prompt_templates  # noqa: E402
    live = prompt_templates._env
    env = SandboxedEnvironment(autoescape=False, undefined=ChainableUndefined,
                               trim_blocks=live.trim_blocks,
                               lstrip_blocks=live.lstrip_blocks,
                               keep_trailing_newline=live.keep_trailing_newline)
    ok("loader options read (trim_blocks + lstrip_blocks on)",
       live.trim_blocks and live.lstrip_blocks)
    text = (Path(__file__).resolve().parents[1]
            / "shared/templates/llm/tasks/extraction_chat_state.md").read_text(encoding="utf-8")
    # The user part holds the stat sources; the system part is not needed.
    text = text.split("## user", 1)[1]
    rendered = env.from_string(text).render(
        stats_enabled=True, rp_first=False, is_avatar=False,
        source_label="Character reply", target_name="Bo", source_text="Something else.",
        context_text="",
        stat_sources=[
            {"id": "S0", "actor": "Ann", "medium": "speech", "text": "Hello there."},
            {"id": "S1", "actor": "", "medium": "self", "text": "Walked away."},
        ])
    lines = rendered.splitlines()
    want = ["S0 — actor: Ann; medium: speech", "Hello there.",
            "S1 — actor: self / unattributed; medium: self", "Walked away."]
    try:
        at = lines.index(want[0])
        block = lines[at:at + 4]
    except ValueError:
        block = []
    ok("each stat source on its own lines", block == want,
       repr([ln for ln in lines if "actor:" in ln or "Hello" in ln]))

print("PASSED" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
