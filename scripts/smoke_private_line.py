#!/usr/bin/env python3
"""Smoke: narrator lines for chosen recipients + the /play/say intercept.

Usage:  ./.venv/bin/python scripts/smoke_private_line.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at a temp
dir BEFORE anything from ``app`` is imported, ``paths.init`` runs before any
world-DB module). No server, no LLM, no real world.

THE FIXTURE, by hand: three characters in one room — Cara, Kim, Obs — at
location "loc-inn", room "taproom". The private line does not resolve presence
(the recipients ARE the audience), so no location row is needed; the room
stream query only joins ``utterances`` on the location/room columns.

Hand-derived expectations:

  (a) ``record_private_line(recipients=["Cara", "Kim"], content="x",
      location_id="loc-inn", room_id="taproom")`` returns an int utterance id
      U. The perceptions table holds EXACTLY two rows for U — Cara and Kim,
      kind ``in_room`` (the kind a normal room listener gets; there is no
      "heard" kind in ``perception``), content "x". Obs has none, not even a
      contentless ``whisper_meta``; the Storyteller (the speaker, not a
      character) gets no ``spoken_self`` row either. So:
        get_character_room_stream("Cara", loc, room) contains content "x" (U)
        get_character_room_stream("Kim",  loc, room) contains content "x" (U)
        get_character_room_stream("Obs",  loc, room) has no row with id U
      The utterance row carries speaker "Storyteller", game_ts non-empty
      (the game clock's canonical stamp), meta source "smoke" and the
      perception meta merged in.
      Sync: ``sync_topics.avatars`` is called once with exactly
      ["Cara", "Kim"] and topic "scene" — never with Obs.

  (b) ``recipients=[]`` returns None and writes NO utterance: the utterance
      count before and after is the same. Blank names are dropped, so
      ``recipients=["", "  "]`` is the same as [] (None, no row); a duplicate
      recipient yields one row (["Kim", "Kim"] → 1 perception row).

  (c) The intercept helper ``play._run_say_intercepts`` (the loop /play/say
      runs before spell detection):
        * no provider registered → None for any text;
        * provider order: a RAISING provider first (skipped, never fatal),
          then a provider that consumes only "magic words" and answers
          {"consumed": True, "result": {"cast": "first"}}, then a second
          consumer answering {"cast": "second"} for every text.
          "magic words" → {"cast": "first"} (first consuming provider wins);
          "hello" → the first consumer answers None, so the second wins:
          {"cast": "second"}.
        * with only the selective consumer left, "hello" → None.
        * the provider receives the keywords avatar, content, volume,
          addressees, location_id, room_id exactly as passed.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="private-line-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "rig.fbx")
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(root / "instance")
        from app.core import config
        config.load(root / "config.json")
        from app.core.db import init_schema, get_connection
        init_schema()

        from app.models.character import save_character_profile
        for name in ("Cara", "Kim", "Obs"):
            assert save_character_profile(
                name, {"template": "human-roleplay"}, create_new=True), name

        from app.core import perception, sync_topics
        from app.models.perception_store import get_character_room_stream

        loc, room = "loc-inn", "taproom"
        conn = get_connection()

        def utterance_count() -> int:
            return conn.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]

        # ---- (a) two recipients ------------------------------------------
        sync_calls = []
        real_avatars = sync_topics.avatars
        sync_topics.avatars = lambda names, topics: sync_calls.append(
            (list(names), topics))
        try:
            uid = perception.record_private_line(
                recipients=["Cara", "Kim"], content="x",
                location_id=loc, room_id=room, source="smoke",
                perception_meta={"marker": "m"})
        finally:
            sync_topics.avatars = real_avatars
        check(isinstance(uid, int), f"(a) returns an utterance id ({uid!r})")
        rows = conn.execute(
            "SELECT perceiver, kind, content FROM perceptions "
            "WHERE utterance_id=? ORDER BY perceiver", (uid,)).fetchall()
        check([tuple(r) for r in rows] == [("Cara", "in_room", "x"),
                                          ("Kim", "in_room", "x")],
              f"(a) exactly Cara+Kim, kind in_room, content x ({[tuple(r) for r in rows]})")
        for name in ("Cara", "Kim"):
            stream = get_character_room_stream(name, loc, room)
            check(any(r.get("utterance_id") == uid and r.get("content") == "x"
                      for r in stream), f"(a) {name}'s room stream has the line")
        obs_stream = get_character_room_stream("Obs", loc, room)
        check(not any(r.get("utterance_id") == uid for r in obs_stream),
              "(a) Obs's room stream has no row for the line")
        urow = conn.execute(
            "SELECT speaker, location_id, room_id, game_ts, meta FROM utterances "
            "WHERE id=?", (uid,)).fetchone()
        import json
        umeta = json.loads(urow["meta"] or "{}")
        check(urow["speaker"] == perception.STORYTELLER_SPEAKER,
              "(a) speaker defaults to the Storyteller")
        check((urow["location_id"], urow["room_id"]) == (loc, room),
              "(a) utterance carries location + room")
        check(bool(urow["game_ts"]), f"(a) game stamp set ({urow['game_ts']!r})")
        check(umeta.get("source") == "smoke" and umeta.get("marker") == "m",
              f"(a) utterance meta has source + perception meta ({umeta})")
        pmeta = json.loads(conn.execute(
            "SELECT meta FROM perceptions WHERE utterance_id=? AND perceiver='Kim'",
            (uid,)).fetchone()[0])
        check(pmeta.get("speaker") == perception.STORYTELLER_SPEAKER
              and pmeta.get("marker") == "m",
              f"(a) perception meta has speaker + marker ({pmeta})")
        check(sync_calls == [(["Cara", "Kim"], "scene")],
              f"(a) sync notifies exactly the recipients ({sync_calls})")

        # ---- (b) empty / blank / duplicate recipients ----------------------
        before = utterance_count()
        check(perception.record_private_line(
            recipients=[], content="y", location_id=loc, room_id=room) is None,
            "(b) recipients=[] returns None")
        check(perception.record_private_line(
            recipients=["", "  "], content="y", location_id=loc,
            room_id=room) is None, "(b) blank recipients return None")
        check(utterance_count() == before, "(b) no utterance row written")
        dup = perception.record_private_line(
            recipients=["Kim", "Kim"], content="z", location_id=loc, room_id=room)
        n_dup = conn.execute("SELECT COUNT(*) FROM perceptions WHERE utterance_id=?",
                             (dup,)).fetchone()[0]
        check(n_dup == 1, f"(b) duplicate recipient yields one row ({n_dup})")

        # ---- (c) say intercept ---------------------------------------------
        from app.core import hooks
        from app.routes import play

        call_kw = dict(avatar="Cara", content="magic words", volume="normal",
                       addressees=["Kim"], location_id=loc, room_id=room)
        check(play._run_say_intercepts(**call_kw) is None,
              "(c) no provider → None")

        seen = []

        def raising(**kw):
            raise RuntimeError("boom")

        def selective(**kw):
            seen.append(kw)
            if kw["content"] == "magic words":
                return {"consumed": True, "result": {"cast": "first"}}
            return None

        def greedy(**kw):
            return {"consumed": True, "result": {"cast": "second"}}

        cap = "play.say_intercept"
        hooks.register_provider(cap, raising, owner="smoke-a", multiple=True)
        hooks.register_provider(cap, selective, owner="smoke-b", multiple=True)
        hooks.register_provider(cap, greedy, owner="smoke-c", multiple=True)
        try:
            check(play._run_say_intercepts(**call_kw) == {"cast": "first"},
                  "(c) magic words → first consuming provider wins, raiser skipped")
            check(seen and seen[0] == call_kw,
                  f"(c) provider got the exact keywords ({seen[:1]})")
            check(play._run_say_intercepts(**{**call_kw, "content": "hello"})
                  == {"cast": "second"}, "(c) hello → the next consumer wins")
            hooks.unregister_owned_providers("smoke-c")
            check(play._run_say_intercepts(**{**call_kw, "content": "hello"})
                  is None, "(c) hello with only the selective consumer → None")
        finally:
            for owner in ("smoke-a", "smoke-b", "smoke-c"):
                hooks.unregister_owned_providers(owner)

    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        return 1
    print("OK smoke_private_line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
