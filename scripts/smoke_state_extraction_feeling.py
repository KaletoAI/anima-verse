#!/usr/bin/env python3
"""State extraction feeling and single-copy reply contract.

Usage: ./.venv/bin/python scripts/smoke_state_extraction_feeling.py

Hand-derived from Task 6: asking adds exactly one schema field, feeling;
S0 references the reply, so its text occurs once. A prose marker wins over
extracted müde with one history row; absent a marker müde adds one row.
Disabled tracking, avatars, empty and malformed feelings write nothing.
Single mode keeps explicit mood markers and ignores inferred feeling.
All storage is temporary; the LLM and background scheduling are stubbed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fixture():
    return dict(target_name="Mira", piece_list="", source_label="Character reply",
                source_text="Character: Ich setze mich und ruhe aus.", context_text="",
                outfit_locked=True, is_avatar=False, pose_keys=["standing", "sitting"],
                current_pose="standing", ask_feeling=True, rp_first=True, stats_enabled=True,
                stat_sources=[dict(id="S0", actor=None, medium="self",
                                   text="Ich setze mich und ruhe aus.")],
                stat_targets=[dict(id="T0", name="Mira", stat_list="stamina: energy")],
                required_stat_pairs=[["S0", "T0"]])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORAGE_DIR"] = os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import embedding
        embedding.embed = lambda text: None
        from app.core.db import init_schema, transaction
        init_schema()
        from app.core.prompt_templates import render_task
        args = fixture()
        system, user = render_task("extraction_chat_state", **args)
        Path("/tmp/task6-prompt.json").write_text(json.dumps(
            dict(system=system, user=user, size=len(system)+len(user)), ensure_ascii=False))
        failures = []
        def check(condition, message):
            if not condition:
                failures.append(message)
        schema = json.loads(system.split("Reply schema:")[1].replace('<integer delta>', '0'))
        without, _ = render_task("extraction_chat_state", **dict(args, ask_feeling=False))
        without_schema = json.loads(without.split("Reply schema:")[1].replace('<integer delta>', '0'))
        check(set(schema) - set(without_schema) == {"feeling"}, "[1] missing feeling schema")
        check('"feeling"' not in without, "[1] disabled field present")
        check(user.count("Ich setze mich und ruhe aus.") == 1, "[2] reply duplicated")
        preview_args = {key: value for key, value in args.items()
                        if key not in {"ask_feeling", "rp_first"}}
        preview_system, _ = render_task("extraction_chat_state", **preview_args)
        check('"feeling"' not in preview_system, "preview must not infer feeling without opt-in")
        from app.routes import chat
        from app.models.character import get_character_current_feeling
        from app.models.memory import load_mood_history
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name,template,profile_json,config_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         ("Mira", "", "{}", '{"mood_tracking":true}', "", ""))
        response = SimpleNamespace(content=json.dumps(dict(pose="", detail="", feeling="müde")))
        with patch("app.core.llm_router.llm_call", return_value=response), patch(
                "app.core.chat_engine.run_follow_up", side_effect=lambda callback, **kwargs: callback()), patch(
                "app.models.account.get_active_character", return_value=""), patch(
                "app.models.account.is_player_controlled", return_value=False), patch(
                "app.models.character.is_outfit_locked", return_value=True):
            for index, (marker, enabled, value, expected, added) in enumerate([
                    (True, True, "müde", "froh", 1),
                    (False, True, "müde", "müde", 1),
                    (False, False, "wach", "müde", 0),
                    (False, True, "", "müde", 0),
                    (False, True, ["wach"], "müde", 0),
                    (False, True, "sehr müde", "müde", 0)], start=3):
                before = len(load_mood_history("Mira"))
                if marker:
                    chat._extract_mood("Mira", "Ich lächle. **I feel froh**")
                response.content = json.dumps(dict(pose="", detail="", feeling=value))
                kwargs = dict(rp_mood_marker=marker)
                chat._extract_context_from_last_chat("Mira", [dict(role="assistant", content="Ich ruhe aus.")],
                                                     dict(mood_tracking=enabled, chat_mode="rp_first"), **kwargs)
                check(get_character_current_feeling("Mira") == expected, f"[{index}] wrong feeling")
                check(len(load_mood_history("Mira")) == before + added, f"[{index}] wrong history count")
            # Exercise the real postprocessor, including prose before cleaning.
            from app.core.chat_engine import post_process_response
            with patch("app.models.character_template.feature_disabled", return_value=True):
                for prose, combined, expected in [
                        ("Ich ruhe mich auf meinem Stuhl aus. **I feel froh**",
                         "Ich ruhe mich auf meinem Stuhl aus.", "froh"),
                        ("Ich ruhe mich auf meinem Stuhl aus.",
                         'Ich ruhe mich auf meinem Stuhl aus.\n<tool name="Example">**I feel wach**</tool>', "müde")]:
                    before = len(load_mood_history("Mira"))
                    response.content = json.dumps(dict(pose="", detail="", feeling="müde"))
                    post_process_response(
                        owner_id="", character_name="Mira", user_input="",
                        full_response=combined, rp_response=prose,
                        agent_config=dict(mood_tracking=True, chat_mode="rp_first"), llm=None,
                        user_display_name="", full_chat_history=[])
                    check(get_character_current_feeling("Mira") == expected,
                          "postprocessor must use original prose for marker priority")
                    check(len(load_mood_history("Mira")) == before + 1,
                          "postprocessor must write exactly one mood row")
            before = len(load_mood_history("Mira"))
            response.content = json.dumps(dict(pose="", detail="", feeling="wach"))
            chat._extract_context_from_last_chat(
                "Mira", [dict(role="assistant", content="Ich ruhe aus.")],
                dict(mood_tracking=True, chat_mode="single"))
            check(get_character_current_feeling("Mira") == "müde",
                  "single mode must not apply inferred feeling")
            check(len(load_mood_history("Mira")) == before,
                  "single mode without a marker must not write mood history")
            before = len(load_mood_history("Mira"))
            with patch("app.models.account.is_player_controlled", return_value=True):
                chat._extract_context_from_last_chat(
                    "Mira", [dict(role="assistant", content="Ich ruhe aus.")],
                    dict(mood_tracking=True, chat_mode="rp_first"))
            check(len(load_mood_history("Mira")) == before, "avatar mood must not change")
            before = len(load_mood_history("Mira"))
            post_process_response(
                owner_id="", character_name="Mira", user_input="",
                full_response="Ich nicke.", rp_response="Ich nicke. **I feel froh**",
                agent_config=dict(mood_tracking=True, chat_mode="single"), llm=None,
                user_display_name="", full_chat_history=[])
            check(get_character_current_feeling("Mira") == "froh",
                  "single mode must keep explicit mood markers")
            check(len(load_mood_history("Mira")) == before + 1,
                  "single-mode marker must write exactly one mood row")
        if failures:
            raise AssertionError("\n".join(failures))
        print("PASS smoke_state_extraction_feeling: schema, single reply, marker priority, history, tracking, avatars, single mode, empty/malformed")


if __name__ == "__main__":
    main()
