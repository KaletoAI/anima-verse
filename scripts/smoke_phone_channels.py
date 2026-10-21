#!/usr/bin/env python3
"""Phone isolation against a throwaway world; no server or provider required.

Usage: ./.venv/bin/python scripts/smoke_phone_channels.py

Hand-derived contract: only explicit messaging belongs to the phone/inbox.
Two mirrored DMs yield exactly two messages, one incoming/unread. A spoken
line with identical text/time is not a DM; 220 newer spoken lines must neither
hide the DMs (filter before LIMIT) nor affect preview, unread or read markers.
A speech-only partner is absent from contacts and has no phone thread/inbox.
Reading the phone advances only to its latest DM, not to the later speech.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="phone-channels-") as tmp:
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    from app.core import config, db
    # Packages load only when the world enables them explicitly (ba172904).
    (Path(tmp) / "config.json").write_text(
        json.dumps({"packages": {"enabled": "notify_user"}}), encoding="utf-8")
    config.load(Path(tmp) / "config.json")
    db.init_schema()
    from app.core.agent_inbox import load_unread_messages
    from app.models.character import save_character_profile
    from app.models.chat import save_message
    from app.core.timeutils import utc_now
    import app.routes.play as play

    avatar, partner, spoken = "demo", "demo_agent", "demo_room"
    for name in (avatar, partner, spoken):
        assert save_character_profile(name, {"character_name": name,
                                            "template": "human-default"}, create_new=True)
    day = utc_now().isoformat()[:10]
    first, last, speech_ts = (f"{day}T10:00:00+00:00", f"{day}T10:01:00+00:00",
                              f"{day}T11:00:00+00:00")

    def deliver(sender, recipient, text, stamp, medium):
        for owner, other, role in ((sender, recipient, "assistant"),
                                    (recipient, sender, "user")):
            assert save_message({"role": role, "content": text, "timestamp": stamp,
                                 "speaker": sender, "medium": medium}, owner, other)

    deliver(avatar, partner, "Meet later?", first, "messaging")
    deliver(partner, avatar, "Yes, later.", last, "messaging")
    deliver(partner, avatar, "Yes, later.", last, "in_person")
    deliver(spoken, avatar, "Spoken only.", speech_ts, "in_person")
    for n in range(220):
        deliver(partner, avatar, f"Room speech {n}", speech_ts, "in_person")
    # A legacy malformed row must not make valid messages disappear.
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chat_messages (character_name, partner, ts, role, content, metadata) "
            "VALUES (?, ?, ?, 'user', 'Broken old metadata', '{broken')",
            (avatar, partner, speech_ts))

    with patch("app.models.account.get_active_character", return_value=avatar):
        contacts = play.play_messages_list(user={})["conversations"]
        assert [c["partner"] for c in contacts] == [partner], contacts
        assert (contacts[0]["last"], contacts[0]["unread"]) == ("Yes, later.", 1), contacts
        thread = play.play_messages_thread(partner=partner, user={})["messages"]
        assert [(m["mine"], m["content"]) for m in thread] == [
            (True, "Meet later?"), (False, "Yes, later.")], thread
        assert play._phone_read_ts(avatar, partner) == last
        assert play.play_messages_thread(partner=spoken, user={})["messages"] == []
        assert play.play_messages_list(user={})["conversations"][0]["unread"] == 0
        assert play.play_messages_read_all(user={})["conversations"] == 1
        assert play._phone_read_ts(avatar, spoken) == ""

    inbox = load_unread_messages(avatar)
    assert set(inbox) == {partner}, inbox
    assert [(m["role"], m["content"]) for m in inbox[partner]] == [
        ("assistant", "Meet later?"), ("user", "Yes, later.")], inbox
    from app.core.dependencies import get_skill_manager
    notify = get_skill_manager().get_skill("notify_user")
    assert notify is not None
    before = db.get_connection().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    with patch("app.models.account.get_player_identity", return_value=avatar):
        result = notify.execute('{"agent_name":"demo_agent","input":"World event notice."}')
    assert not result.startswith("Error"), result
    after = db.get_connection().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    assert after == before, "System notifications must not create phone or room messages"
    from app.models.notifications import get_notifications
    assert [n["content"] for n in get_notifications()] == ["World event notice."]
    print("PASS: phone contacts, thread, preview, unread, read markers and inbox isolate messaging")
