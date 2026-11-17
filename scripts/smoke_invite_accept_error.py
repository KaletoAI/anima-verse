#!/usr/bin/env python3
"""A "yes" whose start raises an unexpected error must not leave the claimed
invitation in ``answering`` (review 11#6).

Usage: ./.venv/bin/python scripts/smoke_invite_accept_error.py

Temp world (``paths.init`` on a temp dir before any world-DB import, schema
created), two invitation rows written directly, no characters needed: the pair
check is stubbed to pass (``check_can_pair`` -> None) and ``start_interaction``
raises ``RuntimeError("database is locked")`` — not a ValueError, so none of
the handled refusals catches it. Narration, the event bus and presence pushes
are stubbed and recorded. Hand-derived from ``interaction_engine``:

  [1] ``resolve_invite(i1, True)`` on a "pending" row: ``_claim_invite``
      moves it to "answering", the start raises -> the call still raises
      RuntimeError (the caller sees the error), and the row is "failed" with
      reason "an internal error"; one "interaction.invite_failed" event.
      Old code: the row stayed "answering" (nothing else moves it until the
      sweep).
  [2] ``_settle_reactions()`` on a "reacting" row whose reaction wait is over
      (``pair_reaction.waited_s`` stubbed to 10**6 s): it claims the row and
      swallows the error per row (returns 0 moved) — the row is "failed" /
      "an internal error" too, not "answering".
  [3] A refusal the accept path handles itself (``start_interaction`` raising
      ValueError("pair_roles_changed")) is unchanged: status "cannot", row
      "failed" with THAT reason, nothing raised.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
os.environ["STORAGE_DIR"] = _tmp.name
os.environ["INSTANCE_DIR"] = _tmp.name
from app.core import paths  # noqa: E402
paths.init(_tmp.name)
from app.core import db  # noqa: E402
db.init_schema()
from app.core import interaction_engine as IE  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("PASS: " if cond else "FAIL: ") + msg)
    if not cond:
        FAILS.append(msg)


def row(invite_id, status):
    with db.transaction() as conn:
        conn.execute("INSERT INTO interaction_invites (invite_id, inviter, invitee, pose_key, created_at, status) "
                     "VALUES (?, 'demo', 'demo2', 'embracing', ?, ?)", (invite_id, utc_now_iso(), status))


def stored(invite_id):
    inv = IE.get_invite(invite_id)
    return (inv["status"], inv["reason"]) if inv else None


def main():
    events = []
    common = [patch.object(IE, "check_can_pair", return_value=None),
              patch.object(IE, "_narrate", lambda *a, **k: None),
              patch("app.core.hooks.emit", lambda name, **kw: events.append(name)),
              patch("app.core.sync_topics.avatars", lambda *a, **k: None)]
    for p in common:
        p.start()
    try:
        with patch.object(IE, "start_interaction", side_effect=RuntimeError("database is locked")):
            row("i1", "pending")
            raised = None
            try:
                IE.resolve_invite("i1", True)
            except RuntimeError as exc:
                raised = exc
            check(raised is not None, "[1] the unexpected error still reaches the caller")
            check(stored("i1") == ("failed", "an internal error"),
                  f"[1] the claimed row is failed, not answering ({stored('i1')})")
            check(events.count("interaction.invite_failed") == 1, "[1] one invite_failed event")

            row("i2", "reacting")
            with patch("app.core.pair_reaction.waited_s", return_value=10 ** 6):
                moved = IE._settle_reactions()
            check(moved == 0, f"[2] the failing reaction row is not counted as moved ({moved})")
            check(stored("i2") == ("failed", "an internal error"),
                  f"[2] the settled react row is failed, not answering ({stored('i2')})")

        with patch.object(IE, "start_interaction", side_effect=ValueError("pair_roles_changed")):
            row("i3", "pending")
            out = IE.resolve_invite("i3", True)
            check(out["status"] == "cannot" and out["reason"] == "pair_roles_changed",
                  f"[3] a handled refusal answers cannot ({out.get('status')}, {out.get('reason')})")
            check(stored("i3") == ("failed", "pair_roles_changed"), f"[3] with its own reason ({stored('i3')})")
    finally:
        for p in common:
            p.stop()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
