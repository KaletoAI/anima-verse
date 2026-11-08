#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_prop_action_narration.py

A prop action tells the room what happens: the storyteller line for taking a
place, leaving it, an invitation and its answer (prop_action_engine
``_narrate`` / ``_narrate_finish`` / ``_group_line``).

Hand-derived expectations, private catalog: sitting = seat, lying = lie,
kneeling = ground, leaning = stand, kissing = pair pose (no group).

a. Taking a place, by the group of the held pose: sitting -> "sits down on",
   lying -> "lies down on", kneeling -> "settles down by", leaning ->
   "steps up to". A combined run holds its CURRENT phase's pose: phase p2 =
   kneeling -> ground.
b. Ending (``_narrate_finish(run, before, status, reason, keep_seated)``):
   - active solo sitting, completed/ended -> "{actor} gets up from the {prop}."
   - active solo leaning -> "{actor} steps away from the {prop}."
   - active, keep_seated = the actor (seat switch) -> no line
   - active pair -> no line (end_interaction tells the room)
   - sleep run, sleeping, completed/awake -> the wake line
   - approaching, failed/approach_timeout -> "does not get to ... after all"
   - approaching, cancelled/cancelled (the player called it off) -> no line
   - awaiting_consent, cancelled/consent_declined -> the decline line with
     inviter = actor, invitee = partner; consent_expired -> the expiry line
     naming who did not answer — a pair (Bob silent): "The invitation from
     {inviter} has expired — {silent} did not answer in time." with inviter
     Kai, silent Bob, no parenthesis; a group Bob + Cleo where Bob had said
     yes: the same line plus " ({agreed} had agreed)", silent Cleo, agreed
     Bob. Each expiry line goes to the inviter as a notice too
     (``_tell_inviter``, same key and values); a decline sends none.
d. The notice (``_tell_inviter``) for a PLAYER-steered inviter: one
   notification for Kai, type "prop_action", text in Kai's language — the
   German expiry line "Die Einladung von {inviter} ist abgelaufen — keine
   rechtzeitige Antwort von {silent}." with Kai / Bob -> "Die Einladung von
   Kai ist abgelaufen — keine rechtzeitige Antwort von Bob."; an NPC inviter
   gets none.
c. Delivery formats in the ACTOR's language in the run's room: German
   "{actor} gets up from the {prop}." = "{actor} steht auf ({prop})." with
   actor Kai and the prop's localized name "Sofa" -> "Kai steht auf (Sofa).",
   speaker = the storyteller, source "prop_action", room = the run's target.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CATALOG = {"sitting": {"group": "seat"}, "lying": {"group": "lie"},
           "kneeling": {"group": "ground"}, "leaning": {"group": "stand"},
           "kissing": {"participants": 2}}


def run_of(ability, pose="sitting", phase="", partner=""):
    definition = dict(ability=ability, pose_key=pose)
    if ability == "combined":
        definition["phases"] = [dict(id="p1", pose_key="sitting"), dict(id="p2", pose_key="kneeling")]
    members = partner if isinstance(partner, list) else [partner] if partner else []
    return dict(execution_id="run1", actor="Kai", members=members, definition=definition, phase=phase, data={},
                target=dict(location_id="loc", room_id="room", placement_id="pl1", variant_uid="v"))


def main():
    with tempfile.TemporaryDirectory(prefix="prop-narration-") as tmp:
        os.environ.update(STORAGE_DIR=tmp, INSTANCE_DIR=tmp)
        from app.core import paths
        paths.init(tmp)
        from app.core import prop_action_engine as E
        from app.core import pose_catalog as pc

        with patch.object(pc, "get_catalog", return_value=CATALOG):
            assert E._group_line(E._SETTLE_LINES, run_of("pose")) == "{actor} sits down on the {prop}."
            assert E._group_line(E._SETTLE_LINES, run_of("pose", "lying")) == "{actor} lies down on the {prop}."
            assert E._group_line(E._SETTLE_LINES, run_of("pose", "kneeling")) == "{actor} settles down by the {prop}."
            assert E._group_line(E._SETTLE_LINES, run_of("pose", "leaning")) == "{actor} steps up to the {prop}."
            assert E._group_line(E._SETTLE_LINES, run_of("combined", phase="p2")) == "{actor} settles down by the {prop}."
            print("PASS a: the place line follows the held pose's group")

            said, told = [], []
            with patch.object(E, "_narrate", side_effect=lambda run, key, **fmt: said.append((key, fmt))), \
                    patch.object(E, "_tell_inviter", side_effect=lambda run, key, **fmt: told.append((key, fmt))):
                def finish(run, before, status, reason, keep=""):
                    said.clear()
                    told.clear()
                    E._narrate_finish(run, before, status, reason, keep)
                    return said[:]
                assert finish(run_of("pose"), "active", "completed", "ended") == [
                    ("{actor} gets up from the {prop}.", {})]
                assert finish(run_of("pose", "leaning"), "active", "cancelled", "pose") == [
                    ("{actor} steps away from the {prop}.", {})]
                assert finish(run_of("pose"), "active", "completed", "ended", keep="Kai") == []
                assert finish(run_of("pair", "kissing", partner="Bob"), "active", "completed", "ended") == []
                assert finish(run_of("sleep", "lying"), "sleeping", "completed", "awake") == [
                    ("{actor} wakes up and gets up from the {prop}.", {})]
                assert finish(run_of("pose"), "approaching", "failed", "approach_timeout") == [
                    ("{actor} does not get to the {prop} after all.", {})]
                assert finish(run_of("pose"), "approaching", "cancelled", "cancelled") == []
                assert finish(run_of("pair", "kissing", partner="Bob"), "awaiting_consent", "cancelled",
                              "consent_declined") == [
                    ("{invitee} does not feel like {pose} with {inviter} right now.",
                     {"inviter": "Kai", "invitee": "Bob"})]
                assert told == []
                expired = [("The invitation from {inviter} has expired — {silent} did not answer in time.",
                            {"inviter": "Kai", "silent": "Bob"})]
                assert finish(run_of("pair", "kissing", partner="Bob"), "awaiting_consent", "cancelled",
                              "consent_expired") == expired
                assert told == expired, told
                group = run_of("pose", partner=["Bob", "Cleo"])
                group["data"]["consents"] = {"Bob": "yes", "Cleo": "pending"}
                agreed = [("The invitation from {inviter} has expired — {silent} did not answer in time "
                           "({agreed} had agreed).", {"inviter": "Kai", "silent": "Cleo", "agreed": "Bob"})]
                assert finish(group, "awaiting_consent", "cancelled", "consent_expired") == agreed, said
                assert told == agreed, told
            print("PASS b: each ending gets its line, a seat switch and a pair none")

        class Query:
            def room_places(self, location_id, room_id):
                assert (location_id, room_id) == ("loc", "room")
                return [dict(placement_id="pl1", prop_id="sofa")]

            def prop_document(self, prop_id):
                return {"name": "Couch", "name_de": "Sofa"}

        utterances = []
        with patch.object(E.places, "_GeometryQuery", Query), \
                patch.object(E.C, "get_character_language", return_value="de"), \
                patch.object(pc, "pose_label", return_value="Sitzen"), \
                patch("app.core.perception.record_utterance", side_effect=lambda **kw: utterances.append(kw)):
            E._narrate(run_of("pose"), "{actor} gets up from the {prop}.")
        from app.core.perception import STORYTELLER_SPEAKER
        assert len(utterances) == 1, utterances
        u = utterances[0]
        assert u["content"] == "Kai steht auf (Sofa).", u["content"]
        assert (u["speaker"], u["source"], u["location_id"], u["room_id"]) == (
            STORYTELLER_SPEAKER, "prop_action", "loc", "room"), u
        print("PASS c: the line is told in the actor's language in the run's room")

        notes = []
        key = "The invitation from {inviter} has expired — {silent} did not answer in time."
        with patch.object(E.C, "get_character_language", return_value="de"), \
                patch("app.models.notifications.create_notification",
                      side_effect=lambda *a, **kw: notes.append((a, kw))):
            with patch("app.models.account.is_player_controlled", return_value=True):
                E._tell_inviter(run_of("pose", partner="Bob"), key, inviter="Kai", silent="Bob")
            assert notes == [(("Kai", "Die Einladung von Kai ist abgelaufen — keine rechtzeitige Antwort von Bob."),
                              {"notification_type": "prop_action", "metadata": {"execution_id": "run1"}})], notes
            notes.clear()
            with patch("app.models.account.is_player_controlled", return_value=False):
                E._tell_inviter(run_of("pose", partner="Bob"), key, inviter="Kai", silent="Bob")
            assert notes == [], notes
        print("PASS d: a player-steered inviter gets the line as a notice, an NPC none")


if __name__ == "__main__":
    main()
