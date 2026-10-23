#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_new_character_skills.py

Throwaway storage, no server, no LLM.

Hand-derived expectations (decision 2026-10-23, the repertoire a permanent
character starts with):
[a] The repo packages declare `default_enabled: true` for exactly
    consume_item, instagram_comment, instagram_reply, interact, setlocation,
    go_to_character, cancel_travel, notify_user, invite_to_party, join_party,
    leave_party, read_item, send_message, set_pose, sleep, wakeup,
    image_generation, talk_to, undress, get_dressed, enter_water, dry_off,
    allow_exposed, require_decency. Niche or setup-bound verbs stay off:
    act, instagram, knowledge_extract, knowledge_search, markdown_writer, n8n,
    retrospect, searx.
[b] A NEW character applied through World Dev gets one skill file with
    `enabled: true` per default id (built-in outfit_change included), the same
    set the Characters-tab creation writes.
[c] Applying the same character again leaves its skill files alone: a skill
    switched off in between stays off.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_PACKAGES = ("act", "consume_item", "decency_exempt", "instagram", "interact",
                 "knowledge", "markdown_writer", "movement", "n8n", "notify_user",
                 "party", "read_item", "retrospect", "searx", "send_message",
                 "set_pose", "sleep", "take_photo", "talk_to", "undress", "wet")
EXPECTED_ON = {"consume_item", "instagram_comment", "instagram_reply", "interact",
               "setlocation", "go_to_character", "cancel_travel", "notify_user",
               "invite_to_party", "join_party", "leave_party", "read_item",
               "send_message", "set_pose", "sleep", "wakeup", "image_generation",
               "talk_to", "undress", "get_dressed", "enter_water", "dry_off",
               "allow_exposed", "require_decency"}
EXPECTED_OFF = {"act", "instagram", "knowledge_extract", "knowledge_search",
                "markdown_writer", "n8n", "retrospect", "searx"}


def main():
    with tempfile.TemporaryDirectory(prefix="new-char-skills-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import config
        from app.core.db import init_schema
        from app.plugins.loader import discover_packages
        init_schema()

        real_get = config.get
        enabled = ",".join(REPO_PACKAGES)
        with patch("app.core.config.get", side_effect=lambda key, default=None:
                   enabled if key == "packages.enabled" else real_get(key, default)):
            packages = [p for p in discover_packages() if p.id in REPO_PACKAGES]
        assert {p.id for p in packages} == set(REPO_PACKAGES), "a repo package is missing"
        entries = {s.skill_id: s for p in packages for s in p.skills}
        on = {sid for sid, s in entries.items() if s.default_enabled}
        assert on == EXPECTED_ON, f"defaults differ: +{on - EXPECTED_ON} -{EXPECTED_ON - on}"
        assert EXPECTED_OFF <= set(entries) and not (on & EXPECTED_OFF)
        print("PASS [a]")

        from app.core.character_ops import DEFAULT_NEW_CHARACTER_SKILLS
        from app.models.character import get_character_skills_dir, save_character_skill_config
        from app.routes.world_dev import _apply_character_internal
        with patch("app.plugins.registry.default_enabled_skill_ids",
                   return_value=sorted(EXPECTED_ON)):
            _apply_character_internal({"character_name": "Mira"}, "human-default")
            files = {f.stem: json.loads(f.read_text())
                     for f in get_character_skills_dir("Mira").glob("*.json")}
            assert set(files) == EXPECTED_ON | set(DEFAULT_NEW_CHARACTER_SKILLS), set(files)
            assert all(v == {"enabled": True} for v in files.values())
            print("PASS [b]")
            save_character_skill_config("Mira", "sleep", {"enabled": False})
            _apply_character_internal({"character_name": "Mira"}, "human-default")
            sleep = get_character_skills_dir("Mira") / "sleep.json"
            assert json.loads(sleep.read_text()) == {"enabled": False}
            print("PASS [c]")
    print("PASS smoke_new_character_skills")


if __name__ == "__main__":
    main()
