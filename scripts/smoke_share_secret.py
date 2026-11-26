#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_share_secret.py

Throwaway storage, no server, no LLM, no network.

Hand-derived expectations for plugins/share_secret (ShareSecret verb):
[a] Giver shares its own secret s1 with Hero (same room) -> add_known_by called
    once with ("Giver", s1, "Hero"); exactly 1 secret.learned event with
    owner="Giver", secret_id=s1, knower="Hero", discovered=False;
    knows(get_secret("Giver", s1), "Hero") is True; result does not start with "Error".
[b] Giver shares known secret s2 (owned by Other) with Stranger (same room) ->
    add_known_by called once with ("Other", s2, "Stranger"); 1 more event
    (total 2) with owner="Other", secret_id=s2, knower="Stranger", discovered=False.
[c] Giver shares s3 (neither owned nor known by Giver) with Hero -> result starts
    with "Error", add_known_by not called, no new event, Hero does not know s3.
[d] Giver shares s1 with Other (different room) -> result starts with "Error",
    add_known_by not called.
[e] Unknown id "sec_nope", missing to, missing secret_id, and to == speaker ->
    each returns a string starting with "Error" and does not call add_known_by.
[f] Repeating [a] (Hero already knows s1) -> non-error result, add_known_by not
    called, no new event.
[g] JSON-in-input form with lowercase recipient "stranger" for s1 -> resolves to
    "Stranger" (case-insensitive exact match) and Stranger learns s1;
    available_now(TurnFacts("Giver", "thought", ())) == "nobody is present" and
    available_now(TurnFacts("Giver", "thought", ("Hero",))) is None.
[h] Deletion test: discovering packages from a temp plugins dir containing every
    repo plugin except share_secret yields no skill_id "share_secret", while
    consume_item, talk_to, and read_item remain present and load cleanly.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import app  # noqa: E402
assert Path(app.__file__).resolve().is_relative_to(REPO), f"wrong repo: {app.__file__}"


def main():
    with tempfile.TemporaryDirectory(prefix="share-secret-smoke-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core import config, hooks
        from app.core.db import init_schema, transaction
        from app.models import secrets as secrets_mod
        from app.models.secrets import add_known_by, add_secret, get_secret, knows
        from app.models.world import add_location, add_room
        from app.plugins.loader import discover_packages, load_plugin
        from app.skills.base import TurnFacts

        init_schema()
        with transaction() as conn:
            for name in ("Giver", "Hero", "Stranger", "Other"):
                conn.execute(
                    "INSERT INTO characters (name, created_at, updated_at) VALUES (?, '', '')",
                    (name,),
                )

        loc = add_location(name="Tavern", description="A quiet tavern")["id"]
        room_a = add_room(loc, "Taproom", sync_world=True)["id"]
        room_b = add_room(loc, "Cellar", sync_world=True)["id"]
        positions = {
            "Giver": room_a,
            "Hero": room_a,
            "Stranger": room_a,
            "Other": room_b,
        }

        s1 = add_secret("Giver", "The box lies under the roots.", source="quest")["id"]
        s2 = add_secret("Other", "Other hides a key.")["id"]
        assert add_known_by("Other", s2, "Giver") is True
        s3 = add_secret("Other", "Unknown to Giver.")["id"]

        events = []
        hooks.register("secret.learned", lambda **kw: events.append(kw))

        enabled_str = "consume_item,talk_to,read_item,share_secret"
        real_get = config.get
        with patch(
            "app.core.config.get",
            side_effect=lambda key, default=None: enabled_str if key == "packages.enabled" else real_get(key, default),
        ):
            packages = discover_packages()

        pkg = next((p for p in packages if p.id == "share_secret"), None)
        assert pkg is not None, "share_secret package missing"
        skill = dict(load_plugin(pkg))["share_secret"]

        with patch("app.models.character.get_character_current_location", return_value=loc), \
                patch("app.models.character.get_character_current_room",
                      side_effect=lambda name, profile=None: positions[name]), \
                patch("app.models.character.list_character_places",
                      side_effect=lambda: {n: (loc, positions[n]) for n in sorted(positions)}), \
                patch("app.models.secrets.add_known_by", wraps=secrets_mod.add_known_by) as mock_add:

            # [a] Giver shares own s1 with Hero
            out = skill.execute(json.dumps({"agent_name": "Giver", "secret_id": s1, "to": "Hero"}))
            assert not out.startswith("Error"), out
            mock_add.assert_called_once_with("Giver", s1, "Hero")
            assert len(events) == 1, events
            assert events[0]["owner"] == "Giver"
            assert events[0]["secret_id"] == s1
            assert events[0]["knower"] == "Hero"
            assert events[0]["discovered"] is False
            assert knows(get_secret("Giver", s1), "Hero") is True
            print("PASS [a]")

            # [b] Giver shares known s2 (owned by Other) with Stranger
            mock_add.reset_mock()
            out = skill.execute(json.dumps({"agent_name": "Giver", "secret_id": s2, "to": "Stranger"}))
            assert not out.startswith("Error"), out
            mock_add.assert_called_once_with("Other", s2, "Stranger")
            assert len(events) == 2, events
            assert events[1]["owner"] == "Other"
            assert events[1]["secret_id"] == s2
            assert events[1]["knower"] == "Stranger"
            assert events[1]["discovered"] is False
            assert knows(get_secret("Other", s2), "Stranger") is True
            print("PASS [b]")

            # [c] Giver shares s3 (neither owns nor knows) with Hero
            mock_add.reset_mock()
            out = skill.execute(json.dumps({"agent_name": "Giver", "secret_id": s3, "to": "Hero"}))
            assert out.startswith("Error"), out
            mock_add.assert_not_called()
            assert len(events) == 2, events
            assert not knows(get_secret("Other", s3), "Hero")
            print("PASS [c]")

            # [d] Giver shares s1 with Other (different room)
            mock_add.reset_mock()
            out = skill.execute(json.dumps({"agent_name": "Giver", "secret_id": s1, "to": "Other"}))
            assert out.startswith("Error"), out
            mock_add.assert_not_called()
            print("PASS [d]")

            # [e] unknown id, missing to, missing secret_id, to == speaker
            for payload in (
                {"agent_name": "Giver", "secret_id": "sec_nope", "to": "Hero"},
                {"agent_name": "Giver", "secret_id": s1},
                {"agent_name": "Giver", "to": "Hero"},
                {"agent_name": "Giver", "secret_id": s1, "to": "Giver"},
            ):
                mock_add.reset_mock()
                out = skill.execute(json.dumps(payload))
                assert out.startswith("Error"), (payload, out)
                mock_add.assert_not_called()
            print("PASS [e]")

            # [f] repeat [a] (Hero already knows s1)
            mock_add.reset_mock()
            out = skill.execute(json.dumps({"agent_name": "Giver", "secret_id": s1, "to": "Hero"}))
            assert not out.startswith("Error"), out
            mock_add.assert_not_called()
            assert len(events) == 2, events
            print("PASS [f]")

            # [g] JSON-in-input form with lowercase recipient + available_now checks
            mock_add.reset_mock()
            out = skill.execute(json.dumps({
                "agent_name": "Giver",
                "input": json.dumps({"secret_id": s1, "to": "stranger"}),
            }))
            assert not out.startswith("Error"), out
            mock_add.assert_called_once_with("Giver", s1, "Stranger")
            assert knows(get_secret("Giver", s1), "Stranger") is True
            assert skill.available_now(TurnFacts("Giver", "thought", ())) == "nobody is present"
            assert skill.available_now(TurnFacts("Giver", "thought", ("Hero",))) is None
            print("PASS [g]")

        # [h] Deletion test: every repo plugin except share_secret
        plugins_root = REPO / "plugins"
        with tempfile.TemporaryDirectory(prefix="share-secret-del-") as tmp_plugins:
            tmp_plugins_path = Path(tmp_plugins)
            for entry in sorted(plugins_root.iterdir()):
                if entry.name == "share_secret":
                    continue
                if not entry.is_dir():
                    continue
                if not (entry / "plugin.yaml").is_file():
                    continue
                (tmp_plugins_path / entry.name).symlink_to(entry)

            with patch(
                "app.core.config.get",
                side_effect=lambda key, default=None: enabled_str if key == "packages.enabled" else real_get(key, default),
            ):
                remaining = discover_packages(plugin_dir=tmp_plugins_path, force=True)

            all_skill_ids = {s.skill_id for p in remaining for s in p.skills}
            assert "share_secret" not in all_skill_ids, all_skill_ids
            by_id = {p.id: p for p in remaining}
            for req in ("consume_item", "talk_to", "read_item"):
                assert req in by_id, f"missing package {req}"
                loaded = dict(load_plugin(by_id[req]))
                assert req in loaded, f"missing skill {req}"
            print("PASS [h]")

    print("PASS smoke_share_secret")


if __name__ == "__main__":
    main()
