"""World Dev free mode — run store and two-phase journal.

One row per agent run in ``world_dev_runs`` and one row per tool call in
``world_dev_journal`` (both in world.db, declared in ``world_db_schema``).
Plan: docs/superpowers/plans/2026-11-22-world-dev-free-mode.md (Task 2, run
state machine).

Run statuses — open: ``running``, ``awaiting_review``, ``interrupted``;
terminal: ``accepted``, ``rolled_back``, ``rollback_incomplete``. A partial
unique index allows at most one open run, so ``create_run`` is the atomic
claim (``RunOpenError`` names the run that holds it). This module only
stores; the transitions themselves belong to the run manager.

Journal protocol for a write tool: ``begin`` (state ``pending``, inserted
BEFORE the write, with the inverse when the target is already known) →
``attach`` (target id + inverse as soon as they exist) → ``complete``
(state ``done`` with the values re-read from storage). A pending write row
is therefore a write that may or may not have happened — the undo must
consider it. Stamps are SYSTEM time (``utc_now_iso``), never game time.

Every access uses a short-lived connection of its own: the thread-local
``db.get_connection`` may carry a caller's open transaction, and a commit or
rollback here must never commit or drop someone else's writes. The flip
side: never call these functions from inside an open ``db.transaction()``
or with an uncommitted write on the thread connection — they would wait for
that write lock. Journal BEFORE a writer starts and AFTER it has committed.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger("world_dev_runs")

OPEN_STATUSES = ("running", "awaiting_review", "interrupted")
TERMINAL_STATUSES = ("accepted", "rolled_back", "rollback_incomplete")
STATUSES = OPEN_STATUSES + TERMINAL_STATUSES
KINDS = ("read", "write", "refused")
TARGET_KINDS = ("location", "terrain", "height", "character")


class RunOpenError(RuntimeError):
    """A run is already open; ``run_id`` names it."""

    def __init__(self, run_id: str):
        super().__init__(f"a World Dev free-mode run is already open ({run_id})")
        self.run_id = run_id


_SCHEMA_READY: set = set()


class _Db:
    """Own connection per access, committed on success, rolled back on error."""

    def __init__(self, immediate: bool = False):
        self.immediate = immediate

    def __enter__(self) -> sqlite3.Connection:
        from app.core.db import _configure, get_db_path
        path = get_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=10)
        _configure(self.conn)
        if str(path) not in _SCHEMA_READY:
            # The tables belong to the world schema (init_schema at boot); a
            # tool that opens a world without them must still work.
            from app.core.world_db_schema import SCHEMA_STATEMENTS
            for stmt in SCHEMA_STATEMENTS:
                if "world_dev_" in stmt:
                    self.conn.execute(stmt)
            self.conn.commit()
            _SCHEMA_READY.add(str(path))
        if self.immediate:
            self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def _dump(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _load(raw: Optional[str]) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _run_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["was_frozen"] = bool(d.get("was_frozen"))
    d["skipped"] = _load(d.get("skipped_json")) or []
    return d


def _entry_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["args"] = _load(d.pop("args_json", None)) or {}
    d["before"] = _load(d.pop("before_json", None))
    d["written"] = _load(d.pop("written_json", None))
    d["inverse"] = _load(d.pop("inverse_json", None))
    return d


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown run status: {status!r}")


# ── Runs ─────────────────────────────────────────────────────────────────

def create_run(task: str, model: str, provider: str, user_id: str,
               max_steps: int, max_tokens_total: int) -> str:
    """Insert a new ``running`` run; raises ``RunOpenError`` when one is open."""
    run_id = "wdr_" + uuid.uuid4().hex[:12]
    try:
        with _Db() as conn:
            conn.execute(
                "INSERT INTO world_dev_runs (id, task, model, provider, user_id, "
                "status, max_steps, max_tokens_total, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (run_id, task or "", model or "", provider or "", user_id or "",
                 int(max_steps), int(max_tokens_total), utc_now_iso()))
    except sqlite3.IntegrityError as exc:
        if "idx_world_dev_runs_one_open" not in str(exc):
            raise
        holder = open_run()
        raise RunOpenError(holder["id"] if holder else "") from exc
    logger.info("world-dev run %s created (model %s/%s)", run_id, provider, model)
    return run_id


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _Db() as conn:
        row = conn.execute("SELECT * FROM world_dev_runs WHERE id=?",
                           (run_id,)).fetchone()
    return _run_dict(row)


def open_run() -> Optional[Dict[str, Any]]:
    """The one run in an open status, or None."""
    marks = ",".join("?" * len(OPEN_STATUSES))
    with _Db() as conn:
        row = conn.execute(
            f"SELECT * FROM world_dev_runs WHERE status IN ({marks}) LIMIT 1",
            OPEN_STATUSES).fetchone()
    return _run_dict(row)


def list_runs(limit: int = 30) -> List[Dict[str, Any]]:
    """Runs newest-first."""
    with _Db() as conn:
        rows = conn.execute(
            "SELECT * FROM world_dev_runs ORDER BY created_at DESC, rowid DESC "
            "LIMIT ?", (int(limit),)).fetchall()
    return [_run_dict(r) for r in rows]


def _update_run(run_id: str, sql_set: str, params: tuple) -> None:
    with _Db() as conn:
        cur = conn.execute(f"UPDATE world_dev_runs SET {sql_set} WHERE id=?",
                           (*params, run_id))
        if cur.rowcount == 0:
            raise KeyError(f"unknown world-dev run: {run_id}")


def set_status(run_id: str, status: str, note: Optional[str] = None) -> None:
    """Set the status; a terminal status also stamps ``ended_at``. ``note``
    None keeps the stored note, a string replaces it."""
    _check_status(status)
    ended = utc_now_iso() if status in TERMINAL_STATUSES else None
    if note is None:
        _update_run(run_id, "status=?, ended_at=?", (status, ended))
    else:
        _update_run(run_id, "status=?, ended_at=?, note=?", (status, ended, note))


def set_was_frozen(run_id: str, was_frozen: bool) -> None:
    _update_run(run_id, "was_frozen=?", (1 if was_frozen else 0,))


def next_turn(run_id: str) -> int:
    """Increment the run's turn counter and return the new turn number."""
    with _Db(immediate=True) as conn:
        cur = conn.execute("UPDATE world_dev_runs SET turn=turn+1 WHERE id=?",
                           (run_id,))
        if cur.rowcount == 0:
            raise KeyError(f"unknown world-dev run: {run_id}")
        return int(conn.execute("SELECT turn FROM world_dev_runs WHERE id=?",
                                (run_id,)).fetchone()["turn"])


def add_usage(run_id: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    _update_run(run_id,
                "tokens_in=tokens_in+?, tokens_out=tokens_out+?, cost_total=cost_total+?",
                (int(tokens_in or 0), int(tokens_out or 0), float(cost or 0.0)))


def set_budgets(run_id: str, max_steps: int, max_tokens_total: int) -> None:
    _update_run(run_id, "max_steps=?, max_tokens_total=?",
                (int(max_steps), int(max_tokens_total)))


def set_skipped(run_id: str, skipped: List[Any]) -> None:
    _update_run(run_id, "skipped_json=?", (_dump(list(skipped or [])),))


def set_backup(run_id: str, path: str) -> None:
    _update_run(run_id, "backup_path=?", (str(path or ""),))


# ── Journal ──────────────────────────────────────────────────────────────

def begin(run_id: str, turn: int, kind: str, tool: str, args: Any,
          target_kind: Optional[str] = None, target_id: Optional[str] = None,
          inverse: Optional[dict] = None) -> int:
    """Insert a ``pending`` step (BEFORE the write) and return its seq.
    Increments the run's ``steps`` counter in the same transaction."""
    if kind not in KINDS:
        raise ValueError(f"unknown journal kind: {kind!r}")
    if target_kind is not None and target_kind not in TARGET_KINDS:
        raise ValueError(f"unknown target kind: {target_kind!r}")
    with _Db(immediate=True) as conn:
        cur = conn.execute("UPDATE world_dev_runs SET steps=steps+1 WHERE id=?",
                           (run_id,))
        if cur.rowcount == 0:
            raise KeyError(f"unknown world-dev run: {run_id}")
        seq = int(conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM world_dev_journal "
            "WHERE run_id=?", (run_id,)).fetchone()["n"])
        conn.execute(
            "INSERT INTO world_dev_journal (run_id, seq, turn, kind, tool, "
            "args_json, target_kind, target_id, state, inverse_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (run_id, seq, int(turn), kind, tool or "", _dump(args if args is not None else {}),
             target_kind, target_id, _dump(inverse), utc_now_iso()))
    return seq


def _update_entry(run_id: str, seq: int, sql_set: str, params: tuple) -> None:
    with _Db() as conn:
        cur = conn.execute(
            f"UPDATE world_dev_journal SET {sql_set} WHERE run_id=? AND seq=?",
            (*params, run_id, int(seq)))
        if cur.rowcount == 0:
            raise KeyError(f"unknown journal step: {run_id}#{seq}")


def attach(run_id: str, seq: int, target_id: Optional[str],
           inverse: Optional[dict], before: Any = None) -> None:
    """Record the target id and inverse of a pending step as soon as they
    exist; ``inverse`` and ``before`` are only written when given, so a
    later attach never erases an inverse ``begin`` already stored."""
    cols, vals = ["target_id=?"], [target_id]
    if inverse is not None:
        cols.append("inverse_json=?")
        vals.append(_dump(inverse))
    if before is not None:
        cols.append("before_json=?")
        vals.append(_dump(before))
    _update_entry(run_id, seq, ", ".join(cols), tuple(vals))


def complete(run_id: str, seq: int, written: Any, line: str,
             kind: Optional[str] = None) -> None:
    """Mark a step ``done`` with the values re-read from storage and its
    one-line result; ``kind`` optionally re-classifies it (e.g. refused)."""
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown journal kind: {kind!r}")
    if kind is None:
        _update_entry(run_id, seq, "state='done', written_json=?, line=?",
                      (_dump(written), line or ""))
    else:
        _update_entry(run_id, seq, "state='done', written_json=?, line=?, kind=?",
                      (_dump(written), line or "", kind))


def entries(run_id: str, turn: Optional[int] = None, writes_only: bool = True,
            include_undone: bool = False) -> List[Dict[str, Any]]:
    """Journal rows newest-first — by default every WRITE row (pending or
    done, with or without inverse) not yet undone; the undo's work list."""
    where = ["run_id=?"]
    params: list = [run_id]
    if turn is not None:
        where.append("turn=?")
        params.append(int(turn))
    if writes_only:
        where.append("kind='write'")
    if not include_undone:
        where.append("undone_at IS NULL")
    with _Db() as conn:
        rows = conn.execute(
            f"SELECT * FROM world_dev_journal WHERE {' AND '.join(where)} "
            "ORDER BY seq DESC", params).fetchall()
    return [_entry_dict(r) for r in rows]


def steps(run_id: str) -> List[Dict[str, Any]]:
    """Every journal row of the run oldest-first (all kinds), for the UI."""
    with _Db() as conn:
        rows = conn.execute(
            "SELECT * FROM world_dev_journal WHERE run_id=? ORDER BY seq ASC",
            (run_id,)).fetchall()
    return [_entry_dict(r) for r in rows]


def mark_undone(run_id: str, seq: int) -> None:
    _update_entry(run_id, seq, "undone_at=?", (utc_now_iso(),))
