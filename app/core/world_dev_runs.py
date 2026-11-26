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
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger("world_dev_runs")

OPEN_STATUSES = ("running", "awaiting_review", "interrupted")
TERMINAL_STATUSES = ("accepted", "rolled_back", "rollback_incomplete")
STATUSES = OPEN_STATUSES + TERMINAL_STATUSES
KINDS = ("read", "write", "refused")
TARGET_KINDS = ("location", "terrain", "height", "character", "world_prop", "terrain_type",
                "item", "relationship", "secret", "rule", "event", "quest_template")
# Media lane (world_dev_media): row statuses and the run's media state.
MEDIA_STATUSES = ("queued", "running", "done", "failed", "skipped", "cancelled", "removed")
MEDIA_STATES = ("open", "accepted", "closed")


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
            from app.core.world_db_schema import ALTER_MIGRATIONS, SCHEMA_STATEMENTS
            for stmt in SCHEMA_STATEMENTS:
                if "world_dev_" in stmt:
                    self.conn.execute(stmt)
            for table, column, typedef in ALTER_MIGRATIONS:
                if table.startswith("world_dev_"):
                    try:
                        self.conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
                    except sqlite3.OperationalError:
                        pass  # the column exists
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
    d["media_enabled"] = bool(d.get("media_enabled", 1))
    d["media_state"] = d.get("media_state") or "open"
    d["skipped"] = _load(d.get("skipped_json")) or []
    bounds = _load(d.get("bounds"))
    d["bounds"] = bounds if isinstance(bounds, dict) else None
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
               max_steps: int, max_tokens_total: int,
               max_tokens: Optional[int] = None, effort: str = "",
               media_enabled: bool = True) -> str:
    """Insert a new ``running`` run; raises ``RunOpenError`` when one is open.
    ``media_enabled`` is the run's media switch (world_dev_media);
    ``max_tokens`` is the per-reply cap (None = the model's default);
    ``effort`` the Effort level ('' = the model's default), stored lowercased;
    ValueError for a level not in EFFORT_LEVELS (checked before the insert)."""
    # Lazy: world_dev_agent imports this module.
    from app.core.world_dev_agent import EFFORT_LEVELS
    effort = (effort or "").strip().lower()
    if effort and effort not in EFFORT_LEVELS:
        raise ValueError(f"unknown effort {effort!r} (allowed: {', '.join(EFFORT_LEVELS)})")
    run_id = "wdr_" + uuid.uuid4().hex[:12]
    try:
        with _Db() as conn:
            conn.execute(
                "INSERT INTO world_dev_runs (id, task, model, provider, user_id, "
                "status, max_steps, max_tokens_total, max_tokens, effort, "
                "media_enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)",
                (run_id, task or "", model or "", provider or "", user_id or "",
                 int(max_steps), int(max_tokens_total),
                 None if max_tokens is None else int(max_tokens),
                 effort,
                 1 if media_enabled else 0,
                 utc_now_iso()))
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


def set_bounds(run_id: str, box: Dict[str, float]) -> None:
    """Store the run's build box {min_x, min_z, max_x, max_z} (metres) —
    run metadata, not world data: the undo and the discard never touch it.
    The caller validates the numbers; this only stores them as floats."""
    clean = {k: float(box[k]) for k in ("min_x", "min_z", "max_x", "max_z")}
    _update_run(run_id, "bounds=?", (_dump(clean),))


def set_backup(run_id: str, path: str) -> None:
    _update_run(run_id, "backup_path=?", (str(path or ""),))


def set_media_enabled(run_id: str, on: bool) -> None:
    """The run's media switch (world_dev_media decides what it means)."""
    _update_run(run_id, "media_enabled=?", (1 if on else 0,))


def set_media_state(run_id: str, state: str) -> None:
    """open · accepted · closed; ValueError for anything else."""
    if state not in MEDIA_STATES:
        raise ValueError(f"unknown media state: {state!r}")
    _update_run(run_id, "media_state=?", (state,))


# ── Media baselines ──────────────────────────────────────────────────────

def note_baseline(run_id: str, kind: str, target_id: str,
                  fps: Optional[dict]) -> bool:
    """Store an element's look at the run's first touch ({step_id: fp};
    None = created by the run). INSERT OR IGNORE: the first baseline wins;
    True when this call inserted it."""
    with _Db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO world_dev_media_baseline "
            "(run_id, kind, target_id, fps_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, kind, str(target_id), _dump(fps), utc_now_iso()))
        return cur.rowcount > 0


def mark_created(run_id: str, kind: str, target_id: str) -> None:
    """The run created this element: its baseline becomes NULL, overriding
    any baseline stored earlier (UPSERT)."""
    with _Db() as conn:
        conn.execute(
            "INSERT INTO world_dev_media_baseline "
            "(run_id, kind, target_id, fps_json, created_at) VALUES (?, ?, ?, NULL, ?) "
            "ON CONFLICT (run_id, kind, target_id) DO UPDATE SET fps_json=NULL",
            (run_id, kind, str(target_id), utc_now_iso()))


def baselines(run_id: str) -> Dict[Tuple[str, str], Optional[dict]]:
    """{(kind, target_id): fps or None} of every element the run touched."""
    with _Db() as conn:
        rows = conn.execute(
            "SELECT kind, target_id, fps_json FROM world_dev_media_baseline "
            "WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
    return {(r["kind"], r["target_id"]): _load(r["fps_json"]) for r in rows}


# ── Media rows ───────────────────────────────────────────────────────────

def _media_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["steps"] = _load(d.pop("steps_json", None)) or []
    d["produced"] = _load(d.pop("produced_json", None)) or []
    return d


def add_media_row(run_id: str, kind: str, target_id: str, steps: List[dict],
                  scheduled_turn: Optional[int] = None) -> int:
    """Insert a ``queued`` element job and return its id."""
    now = utc_now_iso()
    with _Db() as conn:
        cur = conn.execute(
            "INSERT INTO world_dev_media (run_id, kind, target_id, status, "
            "scheduled_turn, steps_json, produced_json, note, created_at, updated_at) "
            "VALUES (?, ?, ?, 'queued', ?, ?, '[]', '', ?, ?)",
            (run_id, kind, str(target_id),
             None if scheduled_turn is None else int(scheduled_turn),
             _dump(list(steps or [])), now, now))
        return int(cur.lastrowid)


def oldest_queued_row() -> Optional[Dict[str, Any]]:
    """The queued row with the lowest id across ALL runs (the one lane)."""
    with _Db() as conn:
        row = conn.execute(
            "SELECT * FROM world_dev_media WHERE status='queued' "
            "ORDER BY id ASC LIMIT 1").fetchone()
    return _media_dict(row) if row is not None else None


def media_rows(run_id: str, kind: Optional[str] = None,
               target_id: Optional[str] = None,
               statuses: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
    """The run's media rows oldest-first (steps/produced JSON-decoded),
    optionally narrowed by kind, target and statuses. ValueError on an
    unknown status in statuses (a misspelled filter must not read as
    "no rows")."""
    if statuses is not None:
        statuses = tuple(statuses)
        bad = [s for s in statuses if s not in MEDIA_STATUSES]
        if bad:
            raise ValueError(f"unknown media status: {bad[0]!r}")
    where = ["run_id=?"]
    params: list = [run_id]
    if kind is not None:
        where.append("kind=?")
        params.append(kind)
    if target_id is not None:
        where.append("target_id=?")
        params.append(str(target_id))
    if statuses is not None:
        if not statuses:
            return []
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    with _Db() as conn:
        rows = conn.execute(
            f"SELECT * FROM world_dev_media WHERE {' AND '.join(where)} "
            "ORDER BY id ASC", params).fetchall()
    return [_media_dict(r) for r in rows]


def media_row(row_id: int) -> Optional[Dict[str, Any]]:
    """One media row by id (steps/produced JSON-decoded), None when unknown."""
    with _Db() as conn:
        row = conn.execute("SELECT * FROM world_dev_media WHERE id=?", (int(row_id),)).fetchone()
    return _media_dict(row) if row is not None else None


def media_rows_with_status(statuses: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """The media rows of ALL runs in the given statuses, oldest first (the
    lane's boot reset). ValueError on an unknown status."""
    statuses = tuple(statuses)
    bad = [s for s in statuses if s not in MEDIA_STATUSES]
    if bad:
        raise ValueError(f"unknown media status: {bad[0]!r}")
    if not statuses:
        return []
    with _Db() as conn:
        rows = conn.execute(
            f"SELECT * FROM world_dev_media WHERE status IN ({','.join('?' * len(statuses))}) "
            "ORDER BY id ASC", statuses).fetchall()
    return [_media_dict(r) for r in rows]


def update_media_row(row_id: int, *, status: Optional[str] = None,
                     steps: Optional[List[dict]] = None,
                     produced: Optional[List[dict]] = None,
                     note: Optional[str] = None) -> None:
    """Update the given fields and stamp ``updated_at``. ValueError on an
    unknown status (nothing written), KeyError on an unknown row."""
    if status is not None and status not in MEDIA_STATUSES:
        raise ValueError(f"unknown media status: {status!r}")
    cols, vals = ["updated_at=?"], [utc_now_iso()]
    if status is not None:
        cols.append("status=?")
        vals.append(status)
    if steps is not None:
        cols.append("steps_json=?")
        vals.append(_dump(list(steps)))
    if produced is not None:
        cols.append("produced_json=?")
        vals.append(_dump(list(produced)))
    if note is not None:
        cols.append("note=?")
        vals.append(note)
    with _Db() as conn:
        cur = conn.execute(
            f"UPDATE world_dev_media SET {', '.join(cols)} WHERE id=?",
            (*vals, int(row_id)))
        if cur.rowcount == 0:
            raise KeyError(f"unknown world-dev media row: {row_id}")


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


def _json_truthy(jtype: Optional[str], value: Any) -> bool:
    """Python truthiness of a JSON value read by json_type/json_extract
    (arrays and objects arrive as JSON text)."""
    if jtype in (None, "null", "false"):
        return False
    if jtype in ("array", "object"):
        return bool(_load(value))
    if jtype == "true":
        return True
    return bool(value)


def entry_digests(run_id: str, keys: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
    """A slim view of the same rows as ``entries(run_id)`` (live write rows,
    newest-first): seq, turn, tool, target_kind, target_id, state, the
    inverse's ``op`` and, under ``changed``, whether each inverse key of
    ``keys`` holds a truthy value. The inverses themselves (whole snapshots
    of a recreate_* row, soul texts) are never loaded."""
    for key in keys:
        if not key.replace("_", "").isalnum():
            raise ValueError(f"bad inverse key: {key!r}")
    cols = "".join(f", json_type(inverse_json, '$.{k}') AS t_{k}, "
                   f"json_extract(inverse_json, '$.{k}') AS v_{k}" for k in keys)
    with _Db() as conn:
        rows = conn.execute(
            "SELECT seq, turn, tool, target_kind, target_id, state, "
            "inverse_json IS NOT NULL AS has_inverse, "
            "json_extract(inverse_json, '$.op') AS op" + cols
            + " FROM world_dev_journal WHERE run_id=? AND kind='write' "
            "AND undone_at IS NULL ORDER BY seq DESC", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in ("seq", "turn", "tool", "target_kind", "target_id",
                               "state", "op")}
        d["has_inverse"] = bool(r["has_inverse"])
        d["changed"] = {k: _json_truthy(r[f"t_{k}"], r[f"v_{k}"]) for k in keys}
        out.append(d)
    return out


def steps(run_id: str) -> List[Dict[str, Any]]:
    """Every journal row of the run oldest-first (all kinds), for the UI."""
    with _Db() as conn:
        rows = conn.execute(
            "SELECT * FROM world_dev_journal WHERE run_id=? ORDER BY seq ASC",
            (run_id,)).fetchall()
    return [_entry_dict(r) for r in rows]


def mark_undone(run_id: str, seq: int) -> None:
    _update_entry(run_id, seq, "undone_at=?", (utc_now_iso(),))
