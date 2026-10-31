#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_prop_action_prompt_block.py

The furniture block every LLM consumer reads (``prop_actions.prompt_block``)
lists only what can be requested now, each fact once. A room with a few
chairs and a package's pair poses once produced 267 offers / 207 KB in one
thought prompt (logs/llm_calls.jsonl, 2026-10-31T12:51:53), 225 of them
blocked.

Hand-derived expectations, ``offers`` and ``state_for`` patched (no world):
offers = sit (enabled), lie (blocked), pair-a (partners Mia enabled, Ben
blocked), pair-b (both partners blocked).
a. The block lists exactly [sit, pair-a]; pair-a carries partners ["Mia"].
b. No row carries enabled / reason / available_targets / placement_id /
   variant_uid (target holds the last two), and empty description/effects
   are left out; action_id, definition_revision and target stay.
c. The words "blocked reasons" are gone from the instruction text.
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def offer(action_id, enabled, *, partners=None, description=""):
    target = dict(location_id="l", room_id="r", placement_id="p", variant_uid="v")
    return dict(action_id=action_id, definition_revision="rev", placement_id="p", variant_uid="v",
                prop_label="Chair", target=target, label=action_id, description=description,
                enabled=enabled, reason="" if enabled else "presence_not_met",
                required_partner=partners is not None,
                available_targets=[dict(partner=n, enabled=e, reason="" if e else "presence_not_met")
                                   for n, e in (partners or [])],
                effects=[])


ROWS = [offer("sit", True, description="Sit down"), offer("lie", False),
        offer("pair-a", True, partners=[("Mia", True), ("Ben", False)]),
        offer("pair-b", False, partners=[("Mia", False), ("Ben", False)])]


def main():
    with tempfile.TemporaryDirectory(prefix="prompt-block-") as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core import prop_actions, prop_action_engine
        with patch.object(prop_actions, "offers", lambda actor: json.loads(json.dumps(ROWS))), \
                patch.object(prop_action_engine, "state_for", lambda actor: {}):
            block = prop_actions.prompt_block("Kai")
    listed = json.loads(block.split("offers=", 1)[1].split("\nown_state=", 1)[0])
    assert [row["action_id"] for row in listed] == ["sit", "pair-a"], listed
    assert listed[1]["partners"] == ["Mia"] and "partners" not in listed[0]
    print("PASS a: only requestable offers, a pair with its enabled partners")
    for row in listed:
        assert not {"enabled", "reason", "available_targets", "placement_id", "variant_uid"} & set(row), row
        assert row["definition_revision"] == "rev" and row["target"]["placement_id"] == "p"
        assert "effects" not in row
    assert listed[0]["description"] == "Sit down" and "description" not in listed[1]
    print("PASS b: each fact once, nothing empty")
    assert "blocked reasons" not in block
    print("PASS c: the instruction no longer speaks of blocked offers")


if __name__ == "__main__":
    main()
