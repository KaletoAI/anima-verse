#!/usr/bin/env python3
"""Smoke Package B: completed plans and idempotent progress.

Usage: ./.venv/bin/python scripts/smoke_intent_done.py

Hand-derived expectations:
- Both rendered rp_first user prompts list the two open plan ids and tell
  the tool model to finish exactly the reached plan with DONE, not PROGRESS.
- A due-plan hint contains DONE with that actual plan id.
- "Found the book!" and " found THE book " normalize to the same words:
  one participant gets one entry, unchanged timestamps and no second write.
  "Packed the book" is different and adds a second entry. Another participant
  or intent may independently record the original note.
- Parsing the same PROGRESS twice stores one note; DONE closes that plan
  while the other plan stays active.

All storage is temporary; paths.init precedes every world-DB import.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths

with tempfile.TemporaryDirectory(prefix="intent-done-") as storage:
    paths.init(Path(storage))
    from app.core import config, db
    config.load(Path(storage) / "config.json")
    db.init_schema()
    from app.models import intents
    from app.core.chat_engine import _rp_tool_decision_input
    from app.core.streaming import StreamingAgent

    checks = []

    def check(label, condition):
        checks.append(bool(condition))
        print(f"{'OK' if condition else 'FAIL'}: {label}")

    first = intents.create_intent(owner="demo", title="Find the book")
    second = intents.create_intent(owner="demo", title="Pack the bag")
    with patch("app.routes.chat._marker_travel_refusal", return_value="no_name"):
        room = _rp_tool_decision_input("Hello", "Found the book.", {}, agent_name="demo")
        agent = StreamingAgent(llm=None, tool_format="tag", tools_dict={},
                               mode="rp_first", agent_name="demo",
                               tool_system_content="Stable tools")
        stream = agent.build_tool_decision_input("Hello", "Found the book.")
    for label, prompt in (("room", room), ("streaming", stream)):
        check(f"{label}: both open ids", all(
            f"{it['id']} | {it['title']}" in prompt for it in (first, second)))
        check(f"{label}: explicit completion decision", all(token in prompt for token in (
            "goal reached", "awaited person arrived", "task carried out",
            "[INTENT_DONE: <id>] for exactly that plan", "DONE, not PROGRESS")))
    check("streaming system stays stable", agent.tool_system_content == "Stable tools")
    check("hint uses actual id", f"[INTENT_DONE: {first['id']}]" in intents._intent_hint(first))

    iid = first["id"]
    original = intents.add_progress(iid, "demo", "Found the book!")
    with patch.object(intents, "update_intent", wraps=intents.update_intent) as update:
        duplicate = intents.add_progress(iid, "demo", " found THE book ")
        check("duplicate returns unchanged intent", duplicate == original)
        check("duplicate does not write", update.call_count == 0)
    different = intents.add_progress(iid, "demo", "Packed the book")
    check("different note appended", len(different["participants"]["demo"]["progress"]) == 2)
    # Distinct keys exercise participant scoping without a second character name.
    parts = intents.add_progress(iid, "", "Found the book!")["participants"]
    check("another participant has its own note", len(parts[""]["progress"]) == 1)
    other = intents.add_progress(second["id"], "demo", "Found the book!")
    check("another intent has its own note", len(other["participants"]["demo"]["progress"]) == 1)

    marker = f"[INTENT_PROGRESS: {second['id']} | Closed the bag]"
    intents.parse_and_apply_intent_markers("demo", marker + "\n" + marker)
    notes = intents.get_intent(second["id"])["participants"]["demo"]["progress"]
    check("repeated marker records one note", [p["note"] for p in notes] == [
        "Found the book!", "Closed the bag"])
    intents.parse_and_apply_intent_markers("demo", f"[INTENT_DONE: {iid}]")
    check("DONE closes exactly its plan", intents.get_intent(iid)["status"] == "done"
          and intents.get_intent(second["id"])["status"] == "active")

    fragment = (Path(__file__).resolve().parents[1] /
                "shared/templates/llm/chat/intent_markers.md").read_text()
    check("grammar restricts progress", all(token in fragment for token in (
        "still open", "ONE plan", "never repeat", "goal is reached")))

print(f"{sum(checks)}/{len(checks)} checks passed")
sys.exit(0 if all(checks) else 1)
