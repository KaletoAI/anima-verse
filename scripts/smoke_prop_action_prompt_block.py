#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_prop_action_prompt_block.py

The furniture context of every LLM (``prop_actions.prompt_block`` for one that
calls tools, ``narrative_block`` for an rp_first roleplay reply) carries what
a decision needs and nothing more: furniture NAMES with their action names,
a pair action's partners. No ids, revisions, targets or distances — the
server resolves a named request at execution (``execute``). History: one
thought prompt once carried 267 offers / 207 KB (2026-10-31T12:51:53), a
later id-carrying version still ~15 KB.

Hand-derived, ``offers`` and ``state_for`` patched (no world):
offers = Chair p "Sit" (enabled, 3.0 m), Chair q "Sit" (enabled, 1.0 m),
Chair p "Lie" (blocked), Bed b "Cuddle" (pair: Mia enabled, Ben blocked),
Bed b "Kiss" (pair: both blocked).
a. prompt_block lines, in offer order: "- Chair: Sit" and
   "- Bed: Cuddle (with Mia)" — one line per furniture name, blocked offers
   and blocked partners left out; "(none available right now)" when nothing.
b. No id, revision, "location_id", "distance" or "operation" anywhere.
c. Own state in words: a current run "Doze" with Mia on target b ->
   "You are doing: Doze with Mia on Bed"; an outgoing "Kiss" to Ben ->
   "You asked Ben for Kiss on Bed — waiting for the answer".
d. narrative_block: "Furniture here (just describe what you do with it):"
   plus the same lines, no "PropAction"; "" with nothing at all.
e. chat/chat_moment.md context: prop_actions_executable False puts the
   narrative block there and takes the contract out of known_activities;
   True keeps prompt_block. replace_contract swaps the section in a text.
f. execute by names: {"furniture": "chair", "action": "sit"} requests the
   NEAREST usable piece (q, 1.0 m) with its own action id/revision/target and
   answers in names, no execution id: {status, furniture "Chair", action "Sit"};
   "Lie" (only blocked) -> refused with its reason; an unknown name ->
   refused "no_such_offer" with the available lines; "Cuddle" with "mia" ->
   partner Mia, without a partner -> refused "partner_required";
   {"stop": true} with nothing running -> refused "nothing_to_stop".
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def offer(action_id, label, prop, placement, enabled=True, *, distance=2.0, partners=None):
    target = dict(location_id="l", room_id="r", placement_id=placement, variant_uid="v")
    return dict(action_id=action_id, definition_revision=f"rev-{action_id}", placement_id=placement,
                variant_uid="v", prop_label=prop, distance_m=distance, target=target, label=label,
                description="", enabled=enabled, reason="" if enabled else "presence_not_met",
                required_partner=partners is not None,
                available_targets=[dict(partner=n, enabled=e, reason="" if e else "presence_not_met")
                                   for n, e in (partners or [])],
                effects=[])


ROWS = [offer("sit", "Sit", "Chair", "p", distance=3.0), offer("sit", "Sit", "Chair", "q", distance=1.0),
        offer("lie", "Lie", "Chair", "p", False),
        offer("cuddle", "Cuddle", "Bed", "b", partners=[("Mia", True), ("Ben", False)]),
        offer("kiss", "Kiss", "Bed", "b", False, partners=[("Mia", False), ("Ben", False)])]


def empty(actor=""):
    return dict(incoming=[], outgoing=[], current=[], recent_results=[])


def main():
    with tempfile.TemporaryDirectory(prefix="prompt-block-") as tmp:
        from app.core import paths
        paths.init(tmp)
        checks()


def checks():
    from app.core import prop_actions, prop_action_engine, prompt_templates

    def rows(actor, **kw):
        return json.loads(json.dumps(ROWS))

    def pieces():
        return patch.object(prop_actions, "piece_label",
                            lambda target: {"b": "Bed"}.get(target["placement_id"], ""))

    with patch.object(prop_actions, "offers", rows), pieces(), \
            patch.object(prop_action_engine, "state_for", empty):
        block = prop_actions.prompt_block("Kai")
        prose = prop_actions.narrative_block("Kai")
    lines = block.split("\n")
    assert lines[0] == "<prop_actions_contract>" and lines[-1] == "</prop_actions_contract>"
    assert lines[2:-1] == ["- Chair: Sit", "- Bed: Cuddle (with Mia)"], lines
    with patch.object(prop_actions, "offers", lambda actor, **kw: [offer("lie", "Lie", "Chair", "p", False)]), \
            patch.object(prop_action_engine, "state_for", empty):
        assert "(none available right now)" in prop_actions.prompt_block("Kai")
        assert prop_actions.narrative_block("Kai") == ""
    print("PASS a: one line per furniture name, only what can be requested")
    for word in ("rev-", "action_id", "location_id", "distance", "operation", "1.0"):
        assert word not in block, word
    print("PASS b: no ids, revisions, targets or distances")

    target = dict(location_id="l", room_id="r", placement_id="b", variant_uid="v")
    state = dict(empty(), current=[dict(label="Doze", actor="Kai", partner="Mia", target=target)],
                 outgoing=[dict(label="Kiss", actor="Kai", partner="Ben", target=target)])
    with patch.object(prop_actions, "offers", rows), pieces(), \
            patch.object(prop_action_engine, "state_for", lambda actor: state):
        own = prop_actions.prompt_block("Kai").split("\n")
    assert own[-3:-1] == ["You are doing: Doze with Mia on Bed",
                          "You asked Ben for Kiss on Bed — waiting for the answer"], own
    print("PASS c: the own state in words")

    assert prose.split("\n") == ["Furniture here (just describe what you do with it):",
                                 "- Chair: Sit", "- Bed: Cuddle (with Mia)"], prose
    assert "PropAction" not in prose
    print("PASS d: the roleplay reply gets the same names, no syntax")

    with patch.object(prop_actions, "offers", rows), pieces(), \
            patch.object(prop_action_engine, "state_for", empty):
        contract = prop_actions.prompt_block("Kai")
        known = "Places here: x\n" + contract
        narrative, nblock = prompt_templates._prop_action_context(
            "chat/chat_moment.md", dict(character_name="Kai", known_activities=known,
                                        prop_actions_executable=False))
        executable, eblock = prompt_templates._prop_action_context(
            "chat/chat_moment.md", dict(character_name="Kai", known_activities=known))
        swapped = prop_actions.replace_contract("A\n" + contract + "\nB", "NAMES")
    assert narrative["known_activities"].strip() == "Places here: x", narrative["known_activities"]
    assert narrative["prop_actions_block"] == nblock == prose
    assert executable["prop_actions_block"] == eblock == contract
    assert swapped == "A\nNAMES\nB", swapped
    print("PASS e: chat_moment carries the contract only for a tool-calling chat LLM")

    sent = []
    real_execute = prop_actions.execute

    def record(actor, payload):
        if "operation" in payload:
            sent.append(payload)
            return dict(status="approaching", execution_id="x", reason="")
        return real_execute(actor, payload)

    with patch.object(prop_actions, "offers", rows), \
            patch.object(prop_actions, "execute", record), \
            patch.object(prop_action_engine, "state_for", empty):
        sit = record("Kai", {"furniture": "chair", "action": "sit"})
        lie = record("Kai", {"furniture": "Chair", "action": "Lie"})
        unknown = record("Kai", {"furniture": "Sofa", "action": "Sit"})
        record("Kai", {"furniture": "Bed", "action": "Cuddle", "partner": "mia"})
        alone = record("Kai", {"furniture": "Bed", "action": "Cuddle"})
        stop = record("Kai", {"stop": True})
    assert sit == dict(status="approaching", furniture="Chair", action="Sit"), sit
    assert sent[0] == dict(operation="request", action_id="sit", revision="rev-sit",
                           target=dict(location_id="l", room_id="r", placement_id="q", variant_uid="v")), sent[0]
    assert (lie["status"], lie["reason"]) == ("refused", "presence_not_met"), lie
    assert unknown["reason"] == "no_such_offer"
    assert unknown["available"] == ["- Chair: Sit", "- Bed: Cuddle (with Mia)"], unknown
    assert sent[1]["partner"] == "Mia" and sent[1]["target"]["placement_id"] == "b", sent[1]
    assert alone["reason"] == "partner_required" and len(sent) == 2, alone
    assert stop["reason"] == "nothing_to_stop"
    print("PASS f: a named request runs on the nearest usable piece, refusals say why")


if __name__ == "__main__":
    main()
