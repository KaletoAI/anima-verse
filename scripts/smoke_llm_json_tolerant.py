#!/usr/bin/env python3
"""The tolerant JSON-object decoder (llm_json.loads_object) and its consumers.

Usage: ./.venv/bin/python scripts/smoke_llm_json_tolerant.py
No server, no LLM. Storage is a temp dir, initialised before any world-DB
module is imported (memory_service is imported for the extraction check, the
LLM call is replaced by a canned answer).

The four malformed shapes come from the memory-extraction analysis of
2026-11-25 (17 % of the local model's answers failed the greedy regex).
Expected values, derived by hand:

  [1] missing outer brace: '{"memories":[{"content":"Likes tea","importance":4,
      "tags":["tea"]}]' -- outside strings: '{' open, '[' open, '{' open,
      '[' open, ']' close, '}' close, ']' close -> one '{' left -> append
      '}' -> 1 memory, importance 4. The old regex cut at the inner '}'
      and lost the ']'.
  [2] code fence: '```json\n{"memories":[],"completed_ids":["a1b2c3d4"]}\n```'
      -> raw_decode from the first '{' stops at the object's end, the fence
      is ignored -> completed_ids == ["a1b2c3d4"].
  [3] trailing text and one brace too many: '{"memories":[{"content":"x"}]}}
      Hope this helps {:)}' -> raw_decode reads the first complete object and
      ignores the rest -> 1 memory "x".
  [4] truncated array (cut after a complete element, then a comma):
      '{"memories":[{"content":"a"},{"content":"b"},' -> trailing comma
      dropped, stack '{' '[' -> append ']}' -> 2 memories a, b.
  [5] plans branch, missing outer brace behind completed_ids:
      '{"memories":[],"completed_ids":["a1b2c3d4"]' -> append '}' ->
      completed_ids kept (the "_list" fallback would have lost it).
  [6] really broken: 'I cannot help with that {not json at all' -> None;
      cut inside a string: '{"memories":[{"content":"unfinish' -> None (an
      open string is never "repaired").
  [7] parse_json keeps the bare-array contract: '[{"a":1},{"b":2}]' ->
      {"_list":[{"a":1},{"b":2}]} (NOT the first element as an object);
      prose '[3] facts: {"a":1}' -> {"a":1} (the array does not enclose the
      object).
  [9] truncated outer value -> None, never a nested fragment (the outer
      value is incomplete, so there is no answer):
      '{"needs":[{"kind":"bed","count":1},{"kind":"ta' -- the string "ta is
      open at the end -> None (not the complete inner {"kind":"bed",...});
      '{"action":"say","args":{"text":"hi"},"note":"cut' -> None (not
      {"text":"hi"});
      '{"memories":[{"content":"abc","importance":3},{"content":"def' -> None
      for loads_object, and memory extraction logs the failure line;
      '{"a":"text with ``` fence inside","b":[1' -- the fence is inside a
      string, so it does not end the run; the body ends on the digit 1
      (maybe a cut 15) -> None (not {"_list":[1]});
      '{"deltas":{"mood": 1' -> None (cut inside a number), while
      '{"deltas":{"mood": 1,' -> {"deltas":{"mood":1}} (the comma proves the
      number complete);
      truncated bare array '[{"a":1},{"b":' -> parse_json None (not {"a":1}).
      Prose with a stray complete brace pair still resumes BEHIND it:
      'Use {x} then {"a":1}' -> {"a":1}.
  [8] memory_service.extract_memories_from_exchange with answer [1] and the
      LLM stubbed: exactly 1 memory, content "Likes tea", importance 4.
      With answer [6a] (broken): [] and the error log line carries the
      first characters of the answer ("I cannot help").
"""
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
    from app.core import db  # noqa: E402
    db.init_schema()
    from app.core import llm_json  # noqa: E402
    loads_object = getattr(llm_json, "loads_object", None)
    ok("[0] llm_json.loads_object exists", callable(loads_object))
    if not callable(loads_object):
        print(f"FAILED: {failed}")
        sys.exit(1)

    a1 = '{"memories":[{"content":"Likes tea","importance":4,"tags":["tea"]}]'
    r = loads_object(a1)
    ok("[1] missing outer brace -> 1 memory, importance 4",
       isinstance(r, dict) and len(r.get("memories", [])) == 1
       and r["memories"][0]["importance"] == 4, repr(r))

    a2 = '```json\n{"memories":[],"completed_ids":["a1b2c3d4"]}\n```'
    r = loads_object(a2)
    ok("[2] fence -> completed_ids kept", isinstance(r, dict) and r.get("completed_ids") == ["a1b2c3d4"], repr(r))

    a3 = '{"memories":[{"content":"x"}]}}\nHope this helps {:)}'
    r = loads_object(a3)
    ok("[3] trailing text + extra brace -> 1 memory x",
       isinstance(r, dict) and [m["content"] for m in r.get("memories", [])] == ["x"], repr(r))

    a4 = '{"memories":[{"content":"a"},{"content":"b"},'
    r = loads_object(a4)
    ok("[4] truncated array -> a, b",
       isinstance(r, dict) and [m["content"] for m in r.get("memories", [])] == ["a", "b"], repr(r))

    a5 = '{"memories":[],"completed_ids":["a1b2c3d4"]'
    r = loads_object(a5)
    ok("[5] plans branch -> completed_ids kept", isinstance(r, dict) and r.get("completed_ids") == ["a1b2c3d4"], repr(r))

    ok("[6a] broken text -> None", loads_object("I cannot help with that {not json at all") is None)
    ok("[6b] open string -> None", loads_object('{"memories":[{"content":"unfinish') is None)
    ok("[6c] empty -> None", loads_object("") is None and loads_object(None) is None)

    r = llm_json.parse_json('[{"a":1},{"b":2}]')
    ok("[7a] bare array -> _list", r == {"_list": [{"a": 1}, {"b": 2}]}, repr(r))
    r = llm_json.parse_json('[3] facts: {"a":1}')
    ok("[7b] prose array before object -> object", r == {"a": 1}, repr(r))
    r = llm_json.parse_json(a1)
    ok("[7c] parse_json repairs the missing brace too",
       isinstance(r, dict) and len(r.get("memories", [])) == 1, repr(r))

    # [9] truncated outer value -> no nested fragment
    for label, txt in [
        ("needs list cut in a string", '{"needs":[{"kind":"bed","count":1},{"kind":"ta'),
        ("action cut in a note", '{"action":"say","args":{"text":"hi"},"note":"cut'),
        ("memories cut in a string", '{"memories":[{"content":"abc","importance":3},{"content":"def'),
        ("fence inside a string, cut number", '{"a":"text with ``` fence inside","b":[1'),
        ("cut inside a number", '{"deltas":{"mood": 1'),
        ("truncated bare array", '[{"a":1},{"b":'),
    ]:
        r1 = llm_json.parse_json(txt)
        r2 = loads_object(txt)
        ok(f"[9] {label} -> None", r1 is None and r2 is None, repr((r1, r2)))
    r = llm_json.parse_json('{"deltas":{"mood": 1,')
    ok("[9] number before a comma is complete", r == {"deltas": {"mood": 1}}, repr(r))
    r = llm_json.parse_json('Use {x} then {"a":1}')
    ok("[9] stray brace pair -> resume behind it", r == {"a": 1}, repr(r))

    # [8] the memory extraction itself
    from app.core import memory_service, llm_router, prompt_templates  # noqa: E402
    answers = []
    llm_router.llm_call = lambda **kw: SimpleNamespace(content=answers.pop(0))
    prompt_templates.render_task = lambda *a, **kw: ("sys", "user")
    import app.models.character_template as ct  # noqa: E402
    ct.feature_disabled = lambda *a, **kw: False

    records = []

    class _H(logging.Handler):
        def emit(self, rec):
            records.append(rec.getMessage())

    logging.getLogger(memory_service.logger.name).addHandler(_H())

    def run(answer):
        answers[:] = [answer]
        return memory_service.extract_memories_from_exchange(
            "demo", "Partner", "Do you like tea?", "I really like tea.", None, plans=False)

    got = run(a1)
    ok("[8a] extraction keeps the memory of a brace-less answer",
       len(got) == 1 and got[0]["content"] == "Likes tea" and got[0]["importance"] == 4, repr(got))
    records.clear()
    got = run("I cannot help with that {not json at all")
    ok("[8b] broken answer -> []", got == [], repr(got))
    ok("[8c] failure log carries the answer head",
       any("I cannot help" in m for m in records), repr(records))

    records.clear()
    got = run('{"memories":[{"content":"abc","importance":3},{"content":"def')
    ok("[9] truncated extraction -> [] and logged",
       got == [] and any('{"memories"' in m for m in records), repr((got, records)))

print("PASSED" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
