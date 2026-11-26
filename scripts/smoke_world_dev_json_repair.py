#!/usr/bin/env python3
"""Smoke: World Dev free mode — trailing closer repair and structural JSON hints.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_json_repair.py

A temp world (paths.init BEFORE any world-DB import); no server, no real LLM.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------
Unit cases for ``world_dev_agent._repair_closers``:
  1. Live case: one extra ``}`` before ``]`` at the end of a nested rooms patch
     -> repaired string parses to the intended dict.
  2. One missing ``}`` at the end -> repaired, equals the intended dict.
  3. Swapped ``}]`` / ``]}`` at the end -> repaired, equals the intended dict.
  4. A ``}`` inside a string value is untouched (both on a valid body and when
     an extra ``}`` sits at the end).
  5. A body broken in the middle (missing comma between two keys) -> None.
  6. An unclosed string -> None.
  7. A valid body -> returned string parses equal to the original dict.

Unit cases for ``world_dev_agent._bad_json_line``:
  8. Extra closer -> keeps exact ``BAD_BODY_LINE (JSON error: ... at line L
     column C)`` prefix, names the column of the extra closer and contains the
     excerpt around it.
  9. Mismatched closer (``]`` closing ``{``) and unclosed brackets at the end
     -> precise structural hint naming the mismatch / needed closers.
 10. Quote error inside a string -> keeps exact prefix and still contains
     ``BAD_JSON_HINT``.

Agent-loop cases (modelled on ``smoke_world_dev_agent.py``):
 11. Fake LLM sends ``update_location`` with an extra closing ``}`` before ``]``
     in the trailing closer run, then a final reply -> the tool runs (journal
     row kind is ``write``, not ``refused``), the location's rooms are updated,
     and the history text sent to the model on the next call contains the
     repair note.
 12. Fake LLM sends an unclosed ``get_location`` call whose body is a complete
     JSON object followed by foreign tags (``</｜DSML｜ parameter>``) -> the
     tool runs (journal row kind is ``read``, not ``refused``), and the history
     text sent to the model on the next call contains ``UNCLOSED_NOTE``.
 13. Fake LLM sends an unclosed ``get_location`` call with incomplete JSON
     (``{"id": "x"``) -> still refused with ``error: tool call not closed``.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_jsonfix_clips_")

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_jsonfix_"))
paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core.llm_client import LLMChunk  # noqa: E402
from app.models.world import (add_location, get_location_by_id,  # noqa: E402
                              set_world_frozen)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def parse_err(body):
    try:
        json.loads(body)
    except json.JSONDecodeError as e:
        return e
    raise AssertionError(f"expected JSONDecodeError for {body!r}")


# ── Unit cases: _repair_closers ──────────────────────────────────────────
print("1. _repair_closers unit cases")

live_body = (
    '{"id": "d366703c", "patch": {"rooms": ['
    '{"name": "Vorhalle"}, '
    '{"name": "Ruheraum", "image_prompt_night": "lantern light and warm shadows"}}]}}'
)
live_expected = {
    "id": "d366703c",
    "patch": {
        "rooms": [
            {"name": "Vorhalle"},
            {"name": "Ruheraum", "image_prompt_night": "lantern light and warm shadows"},
        ]
    },
}
rep_live = wa._repair_closers(live_body)
check("live case (extra } before ]) repaired",
      rep_live is not None and json.loads(rep_live) == live_expected, rep_live)

missing_body = '{"id": "loc1", "patch": {"description": "quiet"'
rep_missing = wa._repair_closers(missing_body)
check("one/two missing } at end repaired",
      rep_missing is not None
      and json.loads(rep_missing) == {"id": "loc1", "patch": {"description": "quiet"}},
      rep_missing)

one_missing_body = '{"id": "loc1", "patch": {"description": "quiet"}'
rep_one_missing = wa._repair_closers(one_missing_body)
check("one missing } at end repaired",
      rep_one_missing is not None
      and json.loads(rep_one_missing) == {"id": "loc1", "patch": {"description": "quiet"}},
      rep_one_missing)

swapped_body = '{"id": "loc1", "patch": {"rooms": [{"name": "Hall"]}}'
rep_swapped = wa._repair_closers(swapped_body)
check("swapped }] / ]} at end repaired",
      rep_swapped is not None
      and json.loads(rep_swapped) == {"id": "loc1", "patch": {"rooms": [{"name": "Hall"}]}},
      rep_swapped)

brace_in_str_extra = '{"text": "use { and } carefully"}}'
rep_brace_str = wa._repair_closers(brace_in_str_extra)
check("} inside string untouched when repairing extra trailing }",
      rep_brace_str is not None
      and json.loads(rep_brace_str) == {"text": "use { and } carefully"},
      rep_brace_str)

broken_mid = '{"a": 1 "b": 2}'
check("broken in middle (missing comma) -> None",
      wa._repair_closers(broken_mid) is None, wa._repair_closers(broken_mid))

unclosed_str = '{"a": "unclosed string}'
check("unclosed string -> None",
      wa._repair_closers(unclosed_str) is None, wa._repair_closers(unclosed_str))

valid_body = '{"a": [1, {"b": "x } y"}]}'
rep_valid = wa._repair_closers(valid_body)
check("valid body -> parsed equal",
      rep_valid is not None and json.loads(rep_valid) == json.loads(valid_body),
      rep_valid)


# ── Unit cases: _bad_json_line ───────────────────────────────────────────
print("2. _bad_json_line unit cases")

# Extra closer in the middle (not repairable): second '}' is at index 24 -> col 25.
extra_mid = '{"rooms": [{"name": "A"}}, {"name": "B"}]}'
e_extra = parse_err(extra_mid)
line_extra = wa._bad_json_line(e_extra, extra_mid)
check("extra closer keeps exact prefix",
      line_extra.startswith(f"{wa.BAD_BODY_LINE} (JSON error: {e_extra.msg} at line "
                            f"{e_extra.lineno} column {e_extra.colno})"),
      line_extra)
check("extra closer names column 25 and excerpt",
      "column 25" in line_extra and '{"name": "A"}},' in line_extra, line_extra)

mismatch_mid = '{"a": {"b": 1], "c": 2}'
e_mis = parse_err(mismatch_mid)
line_mis = wa._bad_json_line(e_mis, mismatch_mid)
check("mismatched closer names ] closing {",
      '"]" closes a "{" at column 14' in line_mis, line_mis)

unclosed_body = '{"a": [1, {"b": "ok"'
e_unc = parse_err(unclosed_body)
line_unc = wa._bad_json_line(e_unc, unclosed_body)
check("unclosed brackets at end names count and needed closers",
      '3 brackets not closed at the end (need "}]}")' in line_unc, line_unc)

quote_body = '{"name": "X", "patch": {"soul:a": "he said "hi""}}'
e_quote = parse_err(quote_body)
line_quote = wa._bad_json_line(e_quote, quote_body)
check("quote error still contains BAD_JSON_HINT",
      wa.BAD_JSON_HINT in line_quote, line_quote)


# ── Agent-loop case ──────────────────────────────────────────────────────
print("3. agent-loop repair case")

COUNTS = {"active": 0, "done": 0}


async def fake_active(llm_instance):
    COUNTS["active"] += 1
    return f"t{COUNTS['active']}"


def fake_done(task_id):
    if task_id:
        COUNTS["done"] += 1


wa._chat_active = fake_active
wa._chat_done = fake_done


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def astream(self, messages):
        self.calls.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else "Done."
        half = len(reply) // 2
        yield LLMChunk(content=reply[:half])
        yield LLMChunk(content=reply[half:])


async def settle(rm, run_id, timeout=20.0):
    for _ in range(int(timeout / 0.02)):
        run = wr.get_run(run_id)
        if run["status"] != "running" and not rm.is_busy(run_id):
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} still running")


async def run_agent_case():
    set_world_frozen(False)
    loc = add_location("Demo Bath", "warm", rooms=[{"name": "Vorhalle"}])
    loc_id = loc["id"]
    vorhalle_id = loc["rooms"][0]["id"]
    broken_call = (
        '<tool name="update_location">'
        '{"id": "%s", "patch": {"rooms": [{"id": "%s", "name": "Vorhalle"}, '
        '{"name": "Ruheraum", "description": "warm shadows"}}]}}'
        '</tool>'
    ) % (loc_id, vorhalle_id)

    rm = wa.RunManager()
    fake = FakeLLM([broken_call, "Updated the rooms."])
    rm.llm_factory = lambda model, provider, max_tokens: (fake, None)

    run_id = await rm.start("add Ruheraum", "fake-model", "fake", "u1")
    run = await settle(rm, run_id)

    steps = wr.steps(run_id)
    check("run reaches awaiting_review", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    check("tool ran as write, not refused",
          [s["kind"] for s in steps] == ["write"],
          [(s["kind"], s["line"]) for s in steps])
    updated = get_location_by_id(loc_id)
    room_names = [r["name"] for r in (updated.get("rooms") or []) if r.get("name")]
    check("location updated with Ruheraum", room_names == ["Vorhalle", "Ruheraum"], room_names)
    check("second LLM call received repair note in history",
          len(fake.calls) == 2 and any(
              wa.REPAIR_NOTE in m["content"] and m["content"].startswith("[result update_location]")
              for m in fake.calls[1]
          ),
          [m["content"] for m in (fake.calls[1] if len(fake.calls) >= 2 else [])
           if m["content"].startswith("[result ")])
    await rm.discard(run_id)

    # (a) Unclosed tool call with complete JSON object followed by foreign tags
    print("4. agent-loop unclosed tool call cases")
    unclosed_ok = (
        'Ich schaue mir den Ort an.\n\n'
        '<tool name="get_location">{"id": "%s"}</｜DSML｜ parameter>\n'
        '</｜DSML｜ invoke>'
    ) % loc_id
    rm2 = wa.RunManager()
    fake2 = FakeLLM([unclosed_ok, "Looked at Demo Bath."])
    rm2.llm_factory = lambda model, provider, max_tokens: (fake2, None)
    run_id2 = await rm2.start("inspect bath", "fake-model", "fake", "u1")
    run2 = await settle(rm2, run_id2)
    steps2 = wr.steps(run_id2)
    check("unclosed complete JSON -> awaiting_review",
          run2["status"] == "awaiting_review", (run2["status"], run2["note"]))
    check("unclosed complete JSON -> tool ran as read, not refused",
          [s["kind"] for s in steps2] == ["read"],
          [(s["kind"], s["line"]) for s in steps2])
    check("unclosed complete JSON -> history contains UNCLOSED_NOTE",
          len(fake2.calls) == 2 and any(
              wa.UNCLOSED_NOTE in m["content"] and m["content"].startswith("[result get_location]")
              for m in fake2.calls[1]
          ),
          [m["content"] for m in (fake2.calls[1] if len(fake2.calls) >= 2 else [])
           if m["content"].startswith("[result ")])
    await rm2.discard(run_id2)

    # (b) Unclosed tool call with incomplete JSON -> still refused
    unclosed_bad = '<tool name="get_location">{"id": "x"'
    rm3 = wa.RunManager()
    fake3 = FakeLLM([unclosed_bad, '<tool name="world_overview">{}</tool>', "Done."])
    rm3.llm_factory = lambda model, provider, max_tokens: (fake3, None)
    run_id3 = await rm3.start("inspect broken", "fake-model", "fake", "u1")
    run3 = await settle(rm3, run_id3)
    steps3 = wr.steps(run_id3)
    check("unclosed incomplete JSON -> awaiting_review after follow-up call",
          run3["status"] == "awaiting_review", (run3["status"], run3["note"]))
    check("unclosed incomplete JSON -> refused + read",
          [s["kind"] for s in steps3] == ["refused", "read"],
          [(s["kind"], s["line"]) for s in steps3])
    check("unclosed incomplete JSON -> tool call not closed line",
          steps3 and (steps3[0]["line"] or "").startswith("error: tool call not closed"),
          steps3 and steps3[0]["line"])
    await rm3.discard(run_id3)

    check("every LLM registration closed", COUNTS["active"] == COUNTS["done"] > 0, COUNTS)


try:
    asyncio.run(run_agent_case())
finally:
    shutil.rmtree(STORAGE, ignore_errors=True)
    shutil.rmtree(os.environ["ANIMATION_CLIPS_DIR"], ignore_errors=True)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
