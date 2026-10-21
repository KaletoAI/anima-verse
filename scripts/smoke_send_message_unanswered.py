#!/usr/bin/env python3
"""SendMessage unanswered brake against a throwaway world; no server or provider.

Usage: ./.venv/bin/python scripts/smoke_send_message_unanswered.py

Hand-derived contract (defaults max_unanswered=3, retry_after_game_hours=24,
game clock stopped with factor 0 and set by hand):
  - A writes B three times at D010 10:00 → all three go out; the fourth is
    refused ("Not sent:", count 3) and names the release time D011 10:00.
  - B answers on the phone → the streak restarts: A may write again (1),
    two more (3), the next is refused.
  - At D011 09:59 (23 h 59 min after the third) it is still refused; at
    D011 10:00 exactly one reminder goes out (streak 4), the next is refused.
  - Messages without a game stamp (written before the stamp existed) have an
    unknown age: five of them do not hold a send back; that send is stamped,
    so the one after it is refused.
  - max_unanswered=0 switches the brake off.
  - The thought block lists B with "4 messages" and "do NOT message B".
  - A sleeping recipient still receives the message (inbox row written) and
    the sender is told so — it used to be dropped while reporting "queued".
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="send-unanswered-") as tmp:
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    from app.core import config, db
    # Packages load only when the world enables them explicitly.
    (Path(tmp) / "config.json").write_text(
        json.dumps({"packages": {"enabled": "send_message"}}), encoding="utf-8")
    config.load(Path(tmp) / "config.json")
    db.init_schema()
    from app.core.game_time import GameDuration, GameTime
    from app.core.timeutils import set_game_factor, set_game_time, utc_now_iso
    from app.models.character import save_character_profile
    from app.models.chat import get_chat_history, save_message
    from app.core.dependencies import get_skill_manager

    A, B, C, S = "demo", "demo_agent", "demo_room", "demo_sleeper"
    for name in (A, B, C, S):
        assert save_character_profile(name, {"character_name": name,
                                            "template": "human-default"}, create_new=True)
    set_game_factor(0.0)
    t0 = GameTime.parse("Y0001-D010T10:00:00")
    set_game_time(t0)

    skill = get_skill_manager().get_skill("send_message")
    assert skill is not None

    def send(sender, target, text):
        return skill.execute(json.dumps({"agent_name": sender, "to": target,
                                         "message": text}))

    def ok(result):
        assert result.startswith("Message sent"), result

    def refused(result, count):
        assert result.startswith("Not sent:"), result
        assert f"{count} messages without a reply" in result, result

    for i in range(3):
        ok(send(A, B, f"hello {i}"))
    r = send(A, B, "hello 3")
    refused(r, 3)
    assert (t0 + GameDuration.of(hours=24)).label() in r, r
    stamps = [m["metadata"].get("game_ts") for m in
              get_chat_history(A, partner_name=B, medium="messaging")]
    assert stamps == ["Y0001-D010T10:00:00"] * 3, stamps

    stamp = utc_now_iso()  # the phone route's format
    for owner, other, role in ((B, A, "assistant"), (A, B, "user")):
        assert save_message({"role": role, "content": "hi back", "timestamp": stamp,
                             "speaker": B, "medium": "messaging"}, owner, other)
    for i in range(3):
        ok(send(A, B, f"after reply {i}"))
    refused(send(A, B, "after reply 3"), 3)

    set_game_time(t0 + GameDuration.of(hours=23, minutes=59))
    refused(send(A, B, "too early"), 3)
    set_game_time(t0 + GameDuration.of(hours=24))
    ok(send(A, B, "reminder"))
    refused(send(A, B, "after reminder"), 4)

    for i in range(5):
        for owner, other, role in ((A, C, "assistant"), (C, A, "user")):
            assert save_message({"role": role, "content": f"old {i}",
                                 "timestamp": f"2026-01-01T10:0{i}:00+00:00",
                                 "speaker": A, "medium": "messaging"}, owner, other)
    ok(send(A, C, "unknown age"))
    refused(send(A, C, "stamped now"), 6)

    with patch.object(skill.ctx, "get_config",
                      lambda path, default=None: 0 if path.endswith("max_unanswered") else default):
        ok(send(A, C, "brake off"))

    block = skill.thought_context_block(A)
    assert block.startswith("=== Waiting for replies ==="), block
    line_b = next(l for l in block.splitlines() if l.startswith(f"- {B}:"))
    assert "you sent 4 messages" in line_b and f"do NOT message {B}" in line_b, line_b
    assert skill.thought_context_block(B) == "", skill.thought_context_block(B)

    with patch("app.models.character.is_character_sleeping", return_value=True):
        r = send(A, S, "good night")
    assert "asleep" in r and r.startswith("Message sent"), r
    inbox = [m["content"] for m in get_chat_history(S, partner_name=A, medium="messaging")]
    assert inbox == ["good night"], inbox

print("smoke_send_message_unanswered: OK")
