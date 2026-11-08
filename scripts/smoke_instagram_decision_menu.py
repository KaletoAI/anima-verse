#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_instagram_decision_menu.py

The rp_first tool LLM gets the pending Instagram posts and comments WITH
their exact ids (``decision_menu`` of InstagramComment / InstagramReply),
because it sees the roleplay prose, not the thought block that lists them.
Before, it invented ids ("Kiras Post", "Valleries_Post", "post_abc123") and
every such comment failed with "post not found" (2026-10-20..2026-11-08:
44 attempts in the logs, only the few whose prose quoted the id landed).

Runs without a server and without network; storage is a temp dir, the feed
is patched. Feed for "Rosi" (window 4 h, the shipped default), times
relative to now:
  post_1  Kira,     1 h ago, caption "Power Play", no Rosi comment -> comment menu
  post_2  Vallerie, 1 h ago, Rosi already commented                -> not offered
  post_3  Kira,     6 h ago                                        -> outside window
  post_4  Rosi (own): Ylva 2 h ago, Rosi 1 h ago (answered), Kira 30 min ago
          "Cheers"                                                 -> reply menu (Kira only)
Hand-derived expectations (f-strings in pending_block.comment_menu/reply_menu):
  comment: ['Kira: "Power Play" = {"post_id": "post_1"}']
  reply:   ['Kira on your post: "Cheers" = {"post_id": "post_4", "commenter": "Kira"}']
The tool-decision note renders each under its verb with the overridden
heading, and the menu object plus a "text" passes the real skills' execute
(only add_comment / get_post / like / bump are stubbed).
"""
import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        FAILURES.append(name)


def main():
    with tempfile.TemporaryDirectory(prefix="ig-menu-") as tmp:
        root = Path(tmp)
        os.environ.update(STORAGE_DIR=str(root / "world"), INSTANCE_DIR=str(root / "instance"),
                          ANIMATION_CLIPS_DIR=str(root / "clips"),
                          ANIMATION_RIG_FILE=str(root / "rig.fbx"))
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config, db
        paths.get_config_path().write_text("{}")
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        db.init_schema()

        from app.core.timeutils import utc_now
        from app.core import streaming
        from app.models import instagram as IG
        from app.plugins.context import PluginContext
        from plugins.instagram import pending_block as PB
        from plugins.instagram import skill_comment as SC, skill_reply as SR

        now = utc_now()

        def ago(**kw):
            return (now - timedelta(**kw)).isoformat()

        feed = [
            {"id": "post_1", "agent_name": "Kira", "caption": "Power Play",
             "timestamp": ago(hours=1), "comments": []},
            {"id": "post_2", "agent_name": "Vallerie", "caption": "Lernen",
             "timestamp": ago(hours=1),
             "comments": [{"author": "Rosi", "text": "Hi", "timestamp": ago(minutes=50)}]},
            {"id": "post_3", "agent_name": "Kira", "caption": "Old",
             "timestamp": ago(hours=6), "comments": []},
            {"id": "post_4", "agent_name": "Rosi", "caption": "Waldkante",
             "timestamp": ago(hours=3), "comments": [
                 {"author": "Ylva", "text": "Schön", "timestamp": ago(hours=2)},
                 {"author": "Rosi", "text": "@Ylva Danke", "timestamp": ago(hours=1)},
                 {"author": "Kira", "text": "Cheers", "timestamp": ago(minutes=30)}]},
        ]
        by_id = {p["id"]: p for p in feed}

        comment = SC.InstagramCommentSkill({}, PluginContext("instagram"))
        reply = SR.InstagramReplySkill({}, PluginContext("instagram"))
        comment.name, reply.name = "InstagramComment", "InstagramReply"

        exp_comment = ['Kira: "Power Play" = {"post_id": "post_1"}']
        exp_reply = ['Kira on your post: "Cheers" = {"post_id": "post_4", "commenter": "Kira"}']

        with patch.object(IG, "load_feed", return_value=feed):
            got_c, got_r = comment.decision_menu("Rosi"), reply.decision_menu("Rosi")
            check("[1] comment menu = the one pending foreign post with its id",
                  got_c == exp_comment, got_c)
            check("[2] reply menu = the one unanswered comment with post_id + commenter",
                  got_r == exp_reply, got_r)
            check("[3] Ylva: post_1 + post_2 offered (post_4 already commented, post_3 too old), "
                  "no own post -> no reply menu",
                  sorted(json.loads(l.split(" = ", 1)[1])["post_id"] for l in comment.decision_menu("Ylva"))
                  == ["post_1", "post_2"] and reply.decision_menu("Ylva") == [],
                  (comment.decision_menu("Ylva"), reply.decision_menu("Ylva")))
            block = PB.build_pending_block("Rosi")
            check("[4] thought block still lists the same ids",
                  "[post_1] Kira:" in block and "[post_4] Kira: \"Cheers\"" in block
                  and "post_2" not in block and "post_3" not in block, block)

            class Manager:
                def get_skill_by_name(self, name):
                    return {"InstagramComment": comment, "InstagramReply": reply}.get(name)

            with patch("app.core.dependencies.get_skill_manager", return_value=Manager()):
                note = streaming.decision_menu_note(
                    "Rosi", {"InstagramComment": None, "InstagramReply": None}, indent="   ")
            exp_note = ('   InstagramComment takes these posts — copy the object after = exactly '
                        'and add your "text":\n'
                        f'   - {exp_comment[0]}\n'
                        '   InstagramReply takes these comments — copy the object after = exactly '
                        'and add your "text":\n'
                        f'   - {exp_reply[0]}\n')
            check("[5] tool-decision note renders both menus under their verbs", note == exp_note,
                  repr(note))

        added = []

        def add_comment(post_id, commenter_name, text):
            added.append((post_id, commenter_name, text))
            return {"author": commenter_name, "text": text}

        from app.core import agent_loop
        with patch.object(SC, "get_post", side_effect=by_id.get), \
             patch.object(SR, "get_post", side_effect=by_id.get), \
             patch.object(SC, "add_comment", side_effect=add_comment), \
             patch.object(SR, "add_comment", side_effect=add_comment), \
             patch.object(SC, "add_character_like", return_value=True), \
             patch.object(agent_loop, "get_agent_loop", return_value=None):
            c_in = dict(json.loads(exp_comment[0].split(" = ", 1)[1]), text="Stark!", agent_name="Rosi")
            r_in = dict(json.loads(exp_reply[0].split(" = ", 1)[1]), text="Prost!", agent_name="Rosi")
            c_res = comment.execute(json.dumps(c_in))
            r_res = reply.execute(json.dumps(r_in))
        check("[6] menu object + text passes InstagramComment",
              c_res.startswith("Comment posted on post_1") and added[0] == ("post_1", "Rosi", "Stark!"),
              (c_res, added))
        check("[7] menu object + text passes InstagramReply, addressed to the commenter",
              r_res.startswith("Reply posted on post_4")
              and added[1] == ("post_4", "Rosi", "@Kira Prost!"), (r_res, added))

    print("PASS" if not FAILURES else f"FAIL ({len(FAILURES)})")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
