#!/usr/bin/env python3
"""Strict loop-guard checks for three async routes that used to read the
world DB on the event loop (loop_guard reported them, 2026-11-25).

Usage: ./.venv/bin/python scripts/smoke_async_routes_off_loop.py
Storage is a temp dir, initialised before any world-DB module is imported.
No server, no HTTP, no LLM, no image job.

Each case runs the route coroutine inside a fresh event loop whose thread is
registered as the server loop, with loop_guard.strict(True): any call that
reaches the DB choke point (db.get_connection -> loop_guard.check) on the
loop thread is recorded in loop_guard.violations before it raises. Work
moved into asyncio.to_thread runs on a worker thread and is not counted.

Expected, derived by hand from the route code:
  [1] play_scene_photo_prepare: get_active_character and
      _player_action_gate are replaced by stubs that call
      loop_guard.check("stub") -- the stand-in for their DB reads -- and
      prepare_scene_photo by a stub returning {"ok": True}. Result
      {"ok": True}, violations == [].
  [2] the same route with the gate raising HTTPException(403) -> the route
      raises HTTPException with status 403 (passed through the thread hop),
      violations == []; with no avatar ("") -> 409.
  [3] play_scene_photo with body {} and accept_photo stubbed to return
      {"photo_id": "p1"} -> a 202 JSONResponse, violations == [].
  [4] chat_ops.save_chat_upload with a real 2x2 PNG: the file lands in
      <storage>/chat_uploads/<image_id>, one chat_upload_owners row for user
      "u1" with purpose "chat" is written -- through the real db.transaction
      -- and violations == [].
  [5] character_ops.detect_characters_core for character "demo" (one
      character in the temp world, no image meta) -> "available" names
      "demo" and violations == [] (list_available_characters,
      get_user_profile, the image meta read all run off the loop).
"""
import asyncio
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


class FakeRequest:
    def __init__(self, body=None, form=None, query=None):
        self._body, self._form = body, form
        self.query_params = query or {}
        self.headers = {}

    async def json(self):
        return self._body

    async def form(self):
        return self._form


class FakeUpload:
    def __init__(self, filename, data):
        self.filename = filename
        self._io = io.BytesIO(data)

    async def read(self, n=-1):
        return self._io.read(n)


USER = {"id": "u1", "username": "demo", "role": "admin",
        "allowed_characters": ["demo"], "settings": {"active_character": "demo"}}


def run_strict(make_coro):
    """(result, exception, violations) of the coroutine run on a strict loop."""
    from app.core import loop_guard
    from app.core.auth_dependency import current_user_ctx

    async def main():
        loop_guard.register_server_loop()
        loop_guard.strict(True)
        token = current_user_ctx.set(USER)
        try:
            return await make_coro()
        finally:
            current_user_ctx.reset(token)
            loop_guard.strict(False)
            loop_guard.unregister()

    loop_guard.clear_violations()
    result = error = None
    try:
        result = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        error = exc
    return result, error, list(loop_guard.violations)


with tempfile.TemporaryDirectory() as tmp:
    paths.init(Path(tmp))
    from app.core import db  # noqa: E402
    db.init_schema()
    from fastapi import HTTPException  # noqa: E402
    from app.core import loop_guard  # noqa: E402
    from app.models import account  # noqa: E402
    from app.models.character import save_character_profile  # noqa: E402
    save_character_profile("demo", {"name": "demo", "language": "en"}, create_new=True)

    from app.routes import play  # noqa: E402
    from app.core import scene_photo, scene_photo_jobs  # noqa: E402

    state = {"avatar": "demo", "gate": None}

    def fake_active():
        loop_guard.check("stub:get_active_character")
        return state["avatar"]

    def fake_gate(avatar, action):
        loop_guard.check("stub:_player_action_gate")
        if state["gate"]:
            raise HTTPException(status_code=403, detail={"reason": "skill_blocked", "message": "no"})
        return None

    account.get_active_character = fake_active
    play._player_action_gate = fake_gate
    scene_photo.prepare_scene_photo = lambda avatar, view=None: {"ok": True}
    scene_photo_jobs.accept_photo = lambda *a, **kw: {"photo_id": "p1"}

    print("[1] scene-photo prepare")
    res, err, vio = run_strict(lambda: play.play_scene_photo_prepare(FakeRequest({}), USER))
    ok("result {'ok': True}", res == {"ok": True} and err is None, repr((res, err)))
    ok("no DB read on the loop", vio == [], repr(vio))

    print("[2] HTTPException passes the hop")
    state["gate"] = True
    res, err, vio = run_strict(lambda: play.play_scene_photo_prepare(FakeRequest({}), USER))
    ok("gate 403 reaches the caller", isinstance(err, HTTPException) and err.status_code == 403, repr(err))
    ok("no DB read on the loop (403)", vio == [], repr(vio))
    state["gate"], state["avatar"] = None, ""
    res, err, vio = run_strict(lambda: play.play_scene_photo(FakeRequest({}), USER))
    ok("no avatar -> 409", isinstance(err, HTTPException) and err.status_code == 409, repr(err))
    state["avatar"] = "demo"

    print("[3] scene-photo take")
    res, err, vio = run_strict(lambda: play.play_scene_photo(FakeRequest({}), USER))
    ok("202 accepted", err is None and getattr(res, "status_code", None) == 202, repr((res, err)))
    ok("no DB read on the loop", vio == [], repr(vio))

    print("[4] chat upload")
    from PIL import Image  # noqa: E402
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buf, format="PNG")
    from app.core import chat_ops  # noqa: E402
    req = FakeRequest(form={"file": FakeUpload("pic.png", buf.getvalue())})
    res, err, vio = run_strict(lambda: chat_ops.save_chat_upload(req))
    image_id = (res or {}).get("image_id", "")
    ok("upload stored", err is None and image_id.endswith(".png")
       and (Path(tmp) / "chat_uploads" / image_id).is_file(), repr((res, err)))
    with db.transaction() as conn:
        rows = conn.execute("SELECT user_id, purpose FROM chat_upload_owners WHERE image_id=?",
                            (image_id,)).fetchall()
    ok("owner row u1/chat", [tuple(r) for r in rows] == [("u1", "chat")], repr(rows))
    ok("no DB read/write on the loop", vio == [], repr(vio))

    print("[5] detect characters")
    from app.core import character_ops  # noqa: E402
    res, err, vio = run_strict(lambda: character_ops.detect_characters_core(
        "demo", "missing.png", FakeRequest({})))
    names = [a["name"] for a in (res or {}).get("available", [])]
    ok("demo is available", err is None and "demo" in names, repr((res, err)))
    ok("no DB read on the loop", vio == [], repr(vio))

print("PASSED" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
