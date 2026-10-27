#!/usr/bin/env python3
"""Influence provenance is private across all character-history exits.

Usage: ./.venv/bin/python scripts/smoke_influence_privacy.py

Hand-derived fixture: signal40 + base3 * factor2 =46. Admin history keeps
rule/event identity; assigned players see only observed actor and numeric
cause, never rule IDs/names/event IDs. The same distinction must hold in
stat-history, debug-activity, the actual character ZIP and /play/self.
Unrelated existing metadata must survive; public projection cannot mutate DB.
All users, sessions, profiles, history and server routes are temporary.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="influence-privacy-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(root / "instance")
        from app.core import config
        config.load(root / "config.json")
        from app.core.db import init_schema, get_connection
        init_schema()
        from app.core import auth_dependency, sessions, users
        from app.models.character import save_character_profile, record_state_change
        from app.models.chat import save_direct_message
        from app.routes.characters import router as character_router
        from app.routes.play import router as play_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        assert save_character_profile("demo", {"template": "human-roleplay", "status_effects": {"signal": 46}}, create_new=True)
        assert save_character_profile("demo-actor", {"template": "human-roleplay"}, create_new=True)
        private_rule = "private-rule-token"
        private_event = "room:private-event-token"
        trace = {"actor": "demo-actor", "base_delta": 3, "modified_delta": 6,
                 "capped_delta": 6, "factor": 2.0,
                 "rules": [{"id": private_rule, "name": "Private rule name", "factor": 2.0}]}
        assert record_state_change("demo", "effects", "chat", metadata={
            "source": "chat", "event_id": private_event, "cause": {"signal": trace},
            "changes": {"signal": {"old": 40, "new": 46}}, "ordinary_note": "retain-me",
        })
        admin_id = users.create_user("demo", "temporary-password", role="admin")
        player_id = users.create_user("demo-player", "temporary-password", role="user")
        assert users.update_user(player_id, allowed_characters=["demo"], settings={"active_character": "demo"})
        admin_token = sessions.create_session(admin_id)
        player_token = sessions.create_session(player_id)
        assert save_direct_message("demo-actor", "demo", "An attached reference.",
                                   metadata={"image": "/fixture/reference.png"})
        app = FastAPI()
        app.include_router(character_router)
        app.include_router(play_router)
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        with TestClient(app, raise_server_exceptions=False) as admin, TestClient(app, raise_server_exceptions=False) as player:
            admin.cookies.set(sessions.SESSION_COOKIE_NAME, admin_token)
            player.cookies.set(sessions.SESSION_COOKIE_NAME, player_token)
            phone = player.get("/play/messages/thread", params={"partner": "demo-actor"})
            assert phone.status_code == 200, phone.text
            assert [(message["mine"], message["content"], message["image"])
                    for message in phone.json()["messages"]] == [
                (False, "An attached reference.", "/fixture/reference.png")]
            # This is the secondary raw-history exit that previously leaked.
            debug = player.get("/characters/demo/debug-activity")
            assert debug.status_code == 200, debug.text
            assert private_rule not in debug.text and private_event not in debug.text, debug.text
            public_debug = next(row for row in debug.json()["state_recent"] if row["type"] == "effects")
            assert public_debug["metadata"]["ordinary_note"] == "retain-me"
            assert "rules" not in public_debug["metadata"]["cause"]["signal"]
            for client, is_admin in ((player, False), (admin, True)):
                response = client.get("/characters/demo/stat-history")
                assert response.status_code == 200, response.text
                row = response.json()["rows"][0]
                assert row["changes"]["signal"] == {"old": 40, "new": 46}
                cause = row["cause"]["signal"]
                assert {key: cause[key] for key in ("actor", "base_delta", "modified_delta", "capped_delta", "factor")} == {
                    "actor": "demo-actor", "base_delta": 3, "modified_delta": 6, "capped_delta": 6, "factor": 2.0}
                if is_admin:
                    assert row["event_id"] == private_event
                    assert cause["rules"][0]["id"] == private_rule
                else:
                    assert "event_id" not in row and "rules" not in cause
                exported = client.get("/characters/demo/export")
                assert exported.status_code == 200, exported.text
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    history = json.loads(archive.read("db/state_history.json"))
                state = json.loads(history[0]["state_json"])
                assert state["metadata"]["ordinary_note"] == "retain-me"
                encoded = json.dumps(state)
                assert (private_rule in encoded) == is_admin, encoded
                assert (private_event in encoded) == is_admin, encoded
            self_payload = player.get("/play/self")
            assert self_payload.status_code == 200, self_payload.text
            own = self_payload.json()["stat_changes"][0]
            assert own["cause"]["signal"]["base_delta"] == 3
            assert private_rule not in self_payload.text and private_event not in self_payload.text
            assert admin.get("/characters/demo/debug-activity").json()["state_recent"][0]["metadata"]["event_id"] == private_event
        stored = get_connection().execute("SELECT state_json FROM state_history WHERE character_name='demo' ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert private_rule in stored and private_event in stored, "Projection must not erase persisted admin provenance"
        print("PASS influence privacy: real player/admin history, debug, ZIP, self and unmodified stored provenance")


if __name__ == "__main__":
    main()
