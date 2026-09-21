#!/usr/bin/env python3
"""Smoke: the ``[INTENT: send_message]`` follow-up is delivered IN-PROCESS.

Usage:  ./.venv/bin/python scripts/smoke_send_message_intent.py

No server, no network, no real world: a throwaway storage root, two characters
created by hand, and ``requests`` rigged to raise on every call.

THE RULE, and what was broken
---------------------------------------------------------------------------
``SendMessageSkill.handle_intent`` runs on a TaskQueue worker thread inside
this very server (``intent_engine._dispatch_intent`` -> the skill declaring the
intent type).  It used to POST to the server's OWN ``/chat/{user_id}``:

    requests.post(f"http://localhost:{os.environ.get('PORT','8000')}/chat/"
                  f"{payload.get('user_id','')}",
                  json={"agent": …, "message": …, "silent": True})

Three things are wrong with that, and the auth gate only made the first fatal:

  * Since commit d92b2470 (``auth_gate_middleware``) an anonymous request is
    answered 401 — a background thread carries no session cookie, and
    ``/chat/*`` is not a public path.  The follow-up simply vanished.
  * ``payload["user_id"]`` is ALWAYS the empty string: the payload is built in
    ``intent_engine._submit_to_task_queue`` as ``{"user_id": "", "agent_name":
    …, "intent_type": …, **intent.params}``.  The URL was ``/chat/``.
  * The endpoint reads neither ``agent`` nor ``silent`` (grep both in
    app/routes/chat.py) — it takes its responder from ``_get_chat_partner()``
    and treats ``message`` as what the PLAYER typed.  So on the happy path the
    character's own follow-up would have been recorded as a user utterance to
    whoever the current chat partner happened to be, and answered by an LLM.
  * ``os.environ["PORT"]`` is an env read, which this project forbids
    (CLAUDE.md: "no .env file, no environment variables").

The in-process delivery already exists: ``execute()`` is the verb, and it
writes BOTH history rows (inbox model: sender = ``assistant`` in its own
history, ``user`` in the recipient's), bridges to Telegram, notifies and bumps.
``handle_intent`` now only has to name the recipient: the one the intent gave,
otherwise the player's avatar — "reaches the player" is what the follow-up is
for.

Hand-derived expectations
---------------------------------------------------------------------------
Characters: ``Nia`` (NPC, the sender) and ``Ash`` (the player's avatar, set via
``set_active_character``).  ``Bo`` is a second NPC.  All three start with an
EMPTY chat history, so every count below is an absolute number, not a delta.

  [1] No HTTP.  ``requests.post`` / ``.request`` / ``Session.request`` raise
      ``_NoHttp``; the intent must finish without touching any of them.
  [2] The intent engine's payload shape: ``user_id`` is "" and there is no
      recipient key in it — so the recipient CANNOT come from the payload in
      the default case.  (Derived from ``_submit_to_task_queue``.)
  [3] ``handle_intent("send_message", {user_id:"", agent_name:"Nia",
      intent_type:"send_message", message:M})`` with Ash active ->
      ``success`` True, and afterwards EXACTLY ONE row each:
        get_chat_history("Ash", "Nia") == 1 row, role "user",      speaker Nia
        get_chat_history("Nia", "Ash") == 1 row, role "assistant", speaker Nia
      both with ``medium == "messaging"`` and content M.  "Exactly once" is the
      point: a second delivery path (HTTP + in-process) would double them.
  [4] An explicit recipient wins over the avatar: the same call with
      ``"to": "Bo"`` lands in Bo's history (1 row) and leaves Ash's at 1.
  [5] An empty message is refused (``success`` False, error "missing message")
      and writes nothing — Ash still has 1 row, Bo still 1.
  [6] No recipient at all (no ``to``, no active avatar) is refused and writes
      nothing.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="send-message-intent-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="send-message-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

import requests  # noqa: E402

from app.core import embedding  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.chat import get_chat_history  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402

# Offline: no embedding model download for the pose catalog.
embedding.embed = lambda text: None
# No worker threads — nothing here executes a queued task.
get_task_queue()._started = True

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ------------------------------------------------------------------ [1] no HTTP

class _NoHttp(AssertionError):
    """Raised if anything in the intent path still speaks HTTP."""


def _forbid(*a, **k):
    raise _NoHttp(f"HTTP call attempted: {a!r} {k!r}")


requests.post = _forbid
requests.request = _forbid
requests.Session.request = _forbid

# --------------------------------------------------------------- the world

SENDER = "Nia"
AVATAR = "Ash"
OTHER = "Bo"
MESSAGE = "I will be at the harbour at eight."

for name in (SENDER, AVATAR, OTHER):
    save_character_profile(name, {"name": name, "language": "en"}, create_new=True)
set_active_character(AVATAR)

# Load the verb the way the loader does: the package class + a PluginContext.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "send_message_skill",
    Path(__file__).resolve().parents[1] / "plugins" / "send_message" / "skill.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
skill = _mod.SendMessageSkill({"enabled": True}, PluginContext("send_message"))


def history(owner, partner):
    return get_chat_history(owner, partner)


# ------------------------------------------- [2] what the engine really sends

print("[2] the payload the intent engine builds carries no recipient")
from app.core.intent_engine import Intent  # noqa: E402

_intent = Intent(type="send_message", delay_seconds=0,
                 params={"message": MESSAGE}, raw="")
_payload = {"user_id": "", "agent_name": SENDER,
            "intent_type": _intent.type, **_intent.params}
check("payload user_id", _payload["user_id"], "")
check("payload has no recipient key",
      [k for k in ("to", "target", "recipient") if k in _payload], [])

# ------------------------------------------------------ [3] the happy path

print("[3] the follow-up lands in both histories exactly once")
res = skill.handle_intent("send_message", dict(_payload))
check("success", res.get("success"), True)

inbox = history(AVATAR, SENDER)
outbox = history(SENDER, AVATAR)
check("avatar rows", len(inbox), 1)
check("sender rows", len(outbox), 1)
if inbox:
    check("avatar row role", inbox[0].get("role"), "user")
    check("avatar row speaker", inbox[0].get("speaker"), SENDER)
    check("avatar row content", inbox[0].get("content"), MESSAGE)
    check("avatar row medium", inbox[0].get("medium"), "messaging")
if outbox:
    check("sender row role", outbox[0].get("role"), "assistant")
    check("sender row speaker", outbox[0].get("speaker"), SENDER)

# ----------------------------------------- [4] an explicit target wins

print("[4] an explicit recipient wins over the avatar")
res = skill.handle_intent("send_message",
                          dict(_payload, to=OTHER, message="Bring the rope."))
check("success", res.get("success"), True)
check("other rows", len(history(OTHER, SENDER)), 1)
check("avatar rows unchanged", len(history(AVATAR, SENDER)), 1)

# ------------------------------------------------- [5] an empty message

print("[5] an empty message is refused and writes nothing")
res = skill.handle_intent("send_message", dict(_payload, message=""))
check("success", res.get("success"), False)
check("error", res.get("error"), "missing message")
check("avatar rows unchanged", len(history(AVATAR, SENDER)), 1)
check("other rows unchanged", len(history(OTHER, SENDER)), 1)

# --------------------------------------------------- [6] no recipient

print("[6] without a recipient and without an avatar the intent is refused")
set_active_character("")
res = skill.handle_intent("send_message", dict(_payload))
check("success", res.get("success"), False)
check("error names the cause", "no recipient" in str(res.get("error", "")), True)
check("avatar rows unchanged", len(history(AVATAR, SENDER)), 1)
set_active_character(AVATAR)

# ------------------------------------------------------------- [1] verdict

print("[1] nothing in the intent path spoke HTTP")
check("requests untouched", True, True)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}/{CHECKED}): " + ", ".join(FAILURES))
    sys.exit(1)
print(f"all {CHECKED} checks passed")
sys.exit(0)
