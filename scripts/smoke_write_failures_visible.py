#!/usr/bin/env python3
"""Smoke: a failed write is reported as a failure, not as a success.

Usage:
    ./.venv/bin/python scripts/smoke_write_failures_visible.py

Throwaway storage (tempfile + ``paths.init``), no server, no real world DB, no
LLM. The failure is produced by replacing ``transaction`` in the module under
test with one that raises ``sqlite3.OperationalError("database is locked")`` —
exactly the error DATA-1's long world writes produce under load.

WHY (DATA-13 of the 2026-09-20 review)
--------------------------------------
Both write paths caught every exception, logged it and then carried on as if
the row were there:

  * ``UnifiedChatManager.save_message`` returned ``None`` either way. A chat
    turn whose message did not persist ran on, the reply stood in the thread's
    prompt context and in the UI — and was gone after the next reload.
  * ``notifications.create_notification`` returned the freshly minted id even
    when the INSERT had failed, so ``scheduler_manager._action_notify`` and the
    ``notify_user`` skill reported a notification nobody would ever see.

EXPECTED, derived by hand from the two contracts:

  [1] HAPPY PATH UNCHANGED.
        save_message(...) -> True, and the row is in chat_messages.
        create_notification(...) -> a 12-hex-character id, and the row is in
        notifications (``uuid4().hex[:12]``).
      No caller passes anything that changes on the success path.

  [2] FAILING WRITE.
        save_message(...) -> False (falsy) and NO row was added.
        create_notification(...) -> "" (falsy) and NO row was added.
      Both are the values the review asked for: a falsy result the caller can
      test. On the old code BOTH returned a truthy/"looks fine" value (None is
      falsy but was also returned on success, so it carried no information —
      check [4] pins the return type down).

  [3] THE FAILURE IS LOGGED AT ERROR WITH A TRACEBACK. A logging handler
      collects the records of the two loggers: exactly one ERROR record each,
      and ``record.exc_info`` is set — without it the log line names the
      exception but not the line that raised it.

  [4] ``save_message`` ANSWERS A QUESTION AT ALL: it returns ``True`` on
      success, so a caller can distinguish it from the failure. On the old code
      it returned ``None`` in both cases; this check therefore fails there.
      Same for the empty character name, which never even tries: ``False``.
"""
import logging
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="writefail-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models import notifications as notif  # noqa: E402
from app.models import unified_chat as uc  # noqa: E402
from app.models.channel import Message  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class Exploding:
    """A ``transaction()`` context manager that raises on enter — what a
    ``database is locked`` looks like to these two functions."""

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        raise sqlite3.OperationalError("database is locked")

    def __exit__(self, *a):
        return False


def chat_rows():
    return db.get_connection().execute(
        "SELECT COUNT(*) FROM chat_messages").fetchone()[0]


def notif_rows():
    return db.get_connection().execute(
        "SELECT COUNT(*) FROM notifications").fetchone()[0]


with db.transaction() as c:
    c.execute("INSERT INTO characters (name, template, profile_json, config_json, "
              "created_at, updated_at) VALUES ('Ann', '', '{}', '{}', 'T00', 'T00')")


def msg():
    return Message(content="hello", role="assistant", timestamp="T01",
                   channel="web")


print("[1] happy path unchanged")
before = chat_rows()
ok = uc.UnifiedChatManager.save_message(msg(), "Ann", partner_name="Bob")
check("save_message -> True", ok is True, repr(ok))
check("the row is there", chat_rows() == before + 1)

before_n = notif_rows()
nid = notif.create_notification("Ann", "hi", "message")
check("create_notification -> a 12-hex id",
      isinstance(nid, str) and len(nid) == 12 and all(
          c in "0123456789abcdef" for c in nid), repr(nid))
check("the row is there", notif_rows() == before_n + 1)

print("[2]/[3] a failing write is falsy and loud")
chat_log = Collector()
notif_log = Collector()
uc.logger.addHandler(chat_log)
notif.logger.addHandler(notif_log)
_real_chat_tx, _real_notif_tx = uc.transaction, notif.transaction
uc.transaction = Exploding()
notif.transaction = Exploding()
try:
    before = chat_rows()
    res = uc.UnifiedChatManager.save_message(msg(), "Ann", partner_name="Bob")
    check("save_message -> falsy", not res, repr(res))
    check("no row was added", chat_rows() == before)

    before_n = notif_rows()
    nid2 = notif.create_notification("Ann", "hi", "message")
    check('create_notification -> ""', nid2 == "", repr(nid2))
    check("no row was added", notif_rows() == before_n)
finally:
    uc.transaction, notif.transaction = _real_chat_tx, _real_notif_tx
    uc.logger.removeHandler(chat_log)
    notif.logger.removeHandler(notif_log)

chat_errors = [r for r in chat_log.records if r.levelno >= logging.ERROR]
notif_errors = [r for r in notif_log.records if r.levelno >= logging.ERROR]
check("save_message logged exactly one ERROR", len(chat_errors) == 1,
      str([r.getMessage() for r in chat_log.records]))
check("…with a traceback", bool(chat_errors and chat_errors[0].exc_info))
check("create_notification logged exactly one ERROR", len(notif_errors) == 1,
      str([r.getMessage() for r in notif_log.records]))
check("…with a traceback", bool(notif_errors and notif_errors[0].exc_info))

print("[4] the return value carries information")
check("success is True, not None",
      uc.UnifiedChatManager.save_message(msg(), "Ann", partner_name="Bob") is True)
check("no character name -> False",
      uc.UnifiedChatManager.save_message(msg(), "") is False)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
