#!/usr/bin/env python3
"""Smoke synthetic respond summaries; usage: ./.venv/bin/python scripts/smoke_respond_synthetic_input.py.

Hand-derived expectations: the invitation hint is not Ann's speech. With
synthetic_input=True only Bob's reply belongs in the history:
'Bob: Gern, komm her, ich habe darauf gewartet.'. With False the existing
summary includes Ann's input, an em dash, then Bob's reply. Both events keep
the chat type and default 0.05 sentiment. No model calls or real storage.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="respond-synthetic-") as tmp:
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(Path(tmp) / "instance")
    from app.core import config, db
    config.load(Path(tmp) / "config.json")
    db.init_schema()
    from app.core import chat_engine
    from app.models.character import save_character_profile
    from app.models.relationship import get_relationship

    for name in ("Ann", "Bob"):
        save_character_profile(name, {"language": "en"}, create_new=True)
    hint = "Ann suggests embracing to you."
    reply = "Gern, komm her, ich habe darauf gewartet."
    original_get = config.get
    def setting(key, default=None):
        return False if key == "relationships.summary_enabled" else original_get(key, default)

    with ExitStack() as stack:
        stack.enter_context(patch.object(config, "get", side_effect=setting))
        stack.enter_context(patch.object(chat_engine, "run_follow_up",
                                       side_effect=lambda fn, *args, **kw: fn(*args)))
        for name in ("_extract_mood", "_extract_location", "_extract_activity",
                     "_extract_context_from_last_chat"):
            stack.enter_context(patch("app.routes.chat." + name, return_value=None))
        stack.enter_context(patch("app.models.intents.parse_and_apply_intent_markers", return_value=[]))
        for synthetic in (True, False):
            chat_engine.post_process_response(
                owner_id="", character_name="Bob", user_input=hint,
                full_response=reply, agent_config={}, llm=None,
                user_display_name="Ann", full_chat_history=[], synthetic_input=synthetic)
            row = get_relationship("Ann", "Bob")["history"][-1]
            expected = "Bob: " + reply if synthetic else "Ann: " + hint + " — Bob: " + reply
            assert row["summary"] == expected, row
            assert row["type"] == "chat" and row["sentiment_delta"] == 0.05, row
    print("PASS: synthetic respond input excluded from relationship speech; real input retained")
