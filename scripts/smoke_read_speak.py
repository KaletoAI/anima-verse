#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_read_speak.py

Hand-derived expectations (owner O with tts_voice="v-O", pages p1..p3):
[a] read_page payload has can_speak=True when owner is set and TTS enabled;
    can_speak=False when TTS disabled; can_speak=False for an item without owner.
[b] speak_page on page index 1 returns {"audio_url": "/tts/tmp/<file>"}, calls
    generate once with page-1 text and voice="v-O" without holding locks, and
    leaves reader's memories count unchanged.
[c] After end_session, speak_page returns {"error": "The reading session has ended."}
    and does not call generate.
[d] When watching_owner returns "O", speak_page returns {"caught_by": "O"} and
    does not call generate.
[e] Disabled TTS returns {"error": "Reading aloud is not available."} without
    calling generate; generate returning None returns {"error": "Reading aloud failed."}.
[f] Item without owner returns {"error": "This has no voice to read it."} without
    calling generate.
[g] _play_read_speak_sync raises HTTPException 409 when no active avatar,
    400 when body is not a dict, and 400 when index is "x".
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="read-speak-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import hooks
        from app.core.db import get_connection, init_schema, transaction
        from app.core.game_time import GameTime
        from app.core.item_reading import end_session, read_page, speak_page
        from app.core.timeutils import set_game_factor, set_game_time
        from app.models.inventory import add_item, add_item_to_room
        from app.models.secrets import add_secret
        from app.models.world import add_location, add_room
        from app.routes.play import _play_read_speak_sync
        from fastapi import HTTPException

        init_schema()
        set_game_factor(0)
        set_game_time(GameTime.parse("Y0002-D109T12:00:00"))

        with transaction() as conn:
            for name in ("O", "A"):
                conn.execute(
                    "INSERT INTO characters (name, created_at, updated_at) VALUES (?, ?, ?)",
                    (name, "", ""),
                )

        loc = add_location(name="Study", description="A quiet study")["id"]
        room = add_room(loc, "Desk", sync_world=True)["id"]
        s1 = add_secret("O", "Secret one")["id"]
        s2 = add_secret("O", "Secret two")["id"]
        pages = [
            {"ref": "p1", "heading": "Page 1", "text": "First diary entry.", "secret_id": s1},
            {"ref": "p2", "heading": "Page 2", "text": "Second diary entry.", "secret_id": s2},
            {"ref": "p3", "heading": "Page 3", "text": "Third diary entry.", "secret_id": ""},
        ]

        def assert_unlocked():
            from app.core.keyed_lock import _LOCKS
            from app.models.world import world_write_lock
            assert not world_write_lock._is_owned(), "world_write_lock held during TTS"
            assert not any(
                lock._is_owned() for bucket in _LOCKS.values() for lock in bucket.values()
            ), "keyed_lock held during TTS"
            assert not get_connection().in_transaction, "DB transaction open during TTS"

        hooks.register_provider("item_pages.speak_pages", lambda item, reader: pages)
        owned = add_item("Diary", category="document", owner="O", pages_source="speak_pages", portable=False)
        unowned = add_item("Pamphlet", category="document", owner="", pages_source="speak_pages", portable=False)
        add_item_to_room(loc, room, owned["id"])
        add_item_to_room(loc, room, unowned["id"])

        audio_dir = Path(tmp) / "tmp" / "tts_audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        class FakeTTS:
            def __init__(self):
                self.enabled = True
                self.return_none = False
                self.calls = []

            def get_character_config(self, agent_config):
                voice = (agent_config or {}).get("tts_voice", "")
                return {
                    "voice": voice,
                    "speaker_wav": "",
                    "language": "de",
                    "model": "",
                    "param": "",
                }

            def generate(self, **kwargs):
                assert_unlocked()
                self.calls.append(kwargs)
                if self.return_none:
                    return None
                out = audio_dir / f"page-{len(self.calls)}.wav"
                out.write_bytes(b"RIFF")
                return out

        fake_tts = FakeTTS()

        def fake_char_cfg(name):
            return {"tts_voice": "v-O"} if name == "O" else {}

        def memory_count(reader):
            return get_connection().execute(
                "SELECT COUNT(*) FROM memories WHERE character_name=?", (reader,)
            ).fetchone()[0]

        with patch("app.core.item_reading.get_tts_service", return_value=fake_tts), \
                patch("app.models.character.get_character_config", side_effect=fake_char_cfg), \
                patch("app.models.character.get_character_current_location", return_value=loc), \
                patch("app.models.character.get_character_current_room", return_value=room), \
                patch("app.models.character.list_character_places",
                      side_effect=lambda: {"A": (loc, room), "O": (loc, room)}), \
                patch("app.models.character.get_character_language", return_value="en"):

            # [a] read_page can_speak flag
            out_enabled = read_page("A", owned["id"], 0, opening=True)
            assert out_enabled["can_speak"] is True, out_enabled
            fake_tts.enabled = False
            out_disabled = read_page("A", owned["id"], 0)
            assert out_disabled["can_speak"] is False, out_disabled
            fake_tts.enabled = True
            out_unowned = read_page("A", unowned["id"], 0, opening=True)
            assert out_unowned["can_speak"] is False, out_unowned
            print("PASS [a]")

            # [b] speak_page on page index 1
            read_page("A", owned["id"], 0, opening=True)
            mem_before = memory_count("A")
            res = speak_page("A", owned["id"], 1)
            assert res == {"audio_url": "/tts/tmp/page-1.wav"}, res
            assert len(fake_tts.calls) == 1
            assert fake_tts.calls[0]["text"] == "Second diary entry."
            assert fake_tts.calls[0]["voice"] == "v-O"
            assert fake_tts.calls[0]["language"] == "de"
            assert memory_count("A") == mem_before
            print("PASS [b]")

            # [c] no active session
            end_session("A", "test")
            calls_before = len(fake_tts.calls)
            res_ended = speak_page("A", owned["id"], 1)
            assert res_ended == {"error": "The reading session has ended."}, res_ended
            assert len(fake_tts.calls) == calls_before
            print("PASS [c]")

            # [d] owner watching
            read_page("A", owned["id"], 0, opening=True)
            calls_before = len(fake_tts.calls)
            with patch("app.core.reading_watch.watching_owner", return_value="O"):
                res_caught = speak_page("A", owned["id"], 0)
            assert res_caught == {"caught_by": "O"}, res_caught
            assert len(fake_tts.calls) == calls_before
            print("PASS [d]")

            # [e] disabled service & generate returning None
            fake_tts.enabled = False
            calls_before = len(fake_tts.calls)
            res_off = speak_page("A", owned["id"], 0)
            assert res_off == {"error": "Reading aloud is not available."}, res_off
            assert len(fake_tts.calls) == calls_before

            fake_tts.enabled = True
            fake_tts.return_none = True
            res_fail = speak_page("A", owned["id"], 0)
            assert res_fail == {"error": "Reading aloud failed."}, res_fail
            fake_tts.return_none = False
            print("PASS [e]")

            # [f] item without owner
            read_page("A", unowned["id"], 0, opening=True)
            calls_before = len(fake_tts.calls)
            res_no_owner = speak_page("A", unowned["id"], 0)
            assert res_no_owner == {"error": "This has no voice to read it."}, res_no_owner
            assert len(fake_tts.calls) == calls_before
            print("PASS [f]")

            # [g] _play_read_speak_sync validation
            with patch("app.models.account.get_active_character", return_value=""):
                try:
                    _play_read_speak_sync({"item_id": owned["id"], "index": 0})
                except HTTPException as exc:
                    assert exc.status_code == 409, exc.status_code
                else:
                    raise AssertionError("missing avatar must raise 409")

            with patch("app.models.account.get_active_character", return_value="A"):
                for bad_body in ("not-a-dict", {"item_id": owned["id"], "index": "x"}):
                    try:
                        _play_read_speak_sync(bad_body)
                    except HTTPException as exc:
                        assert exc.status_code == 400, (bad_body, exc.status_code)
                    else:
                        raise AssertionError(f"bad body {bad_body!r} must raise 400")
            print("PASS [g]")

    print("OK")


if __name__ == "__main__":
    main()
