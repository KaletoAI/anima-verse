"""Quest storage — templates, runs and facts (world.db).

Storage only: no engine logic, no effects, no notifications. Tables are
declared in ``world_db_schema`` (``quest_templates``, ``quest_runs``,
``quest_facts``).

A **template** refers to roles; its editable fields carry an integer
``revision`` (``update_template`` compares ``base_revision`` inside the
transaction and raises ``StaleRevision``). A **run** binds the roles to
world entities and freezes ``template_snapshot`` at creation; nothing here
reads the live template for a run.

Run states — open: ``preparing``, ``hidden``, ``open``; ended: ``done``,
``failed``, ``cancelled``, ``broken``. An ended run never changes state
again. Entering an ended state stamps ``ended_game_ts`` (GAME time,
canonical) and ``ended_at`` (SYSTEM time).

A **fact** is what a MIND did (``linked_characters.mind_of`` of the acting
avatar — the caller resolves it): ``(mind, kind, subject)``, written once.

Locks: ``keyed_lock("quest_run", run_id)`` / ``keyed_lock("quest_template",
template_id)`` are innermost — nothing here takes another lock or calls out.
Every writer is ONE ``db.transaction()``; since that does not nest, never
call these from inside an open transaction.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.keyed_lock import keyed_lock
from app.core.timeutils import game_time, utc_now_iso

RUN_OPEN_STATES = ("preparing", "hidden", "open")
RUN_ENDED_STATES = ("done", "failed", "cancelled", "broken")

_TEMPLATE_JSON_FIELDS = {
    "roles": list, "steps": list, "start_condition": dict, "prerequisites": dict,
    "dependencies": list, "setup_effects": list, "rewards": list, "repeat": dict,
}
_RUN_JSON_FIELDS = {
    "bindings": dict, "binding_labels": dict, "template_snapshot": dict, "step_log": list, "issues": list,
}
#: The keys ``update_template`` accepts; everything else is a ValueError.
EDITABLE_TEMPLATE_KEYS = ("title", "summary", "gm_notes", "roles", "steps",
                          "start_condition", "prerequisites", "time_limit_s",
                          "state", "kept")
#: The run fields ``set_run_field`` may write.
_SETTABLE_RUN_FIELDS = ("news_event_id",)


class StaleRevision(Exception):
    """The template changed since the caller loaded it; ``current`` is the
    stored revision."""

    def __init__(self, template_id: str, current: int):
        super().__init__(f"quest template {template_id} is at revision {current}")
        self.template_id = template_id
        self.current = current


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _decode(row, fields: Dict[str, type]) -> Dict[str, Any]:
    d = dict(row)
    for key, kind in fields.items():
        raw = d.get(key)
        try:
            value = json.loads(raw) if isinstance(raw, str) and raw else kind()
        except (TypeError, ValueError):
            value = kind()
        d[key] = value if isinstance(value, kind) else kind()
    return d


def _template_dict(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = _decode(row, _TEMPLATE_JSON_FIELDS)
    d["kept"] = bool(d.get("kept"))
    return d


def _run_dict(row) -> Optional[Dict[str, Any]]:
    return None if row is None else _decode(row, _RUN_JSON_FIELDS)


def _container(value: Any, kind: type) -> Any:
    return value if isinstance(value, kind) else kind()


# ── Templates ────────────────────────────────────────────────────────────

def create_template(*, title: str, summary: str = "", gm_notes: str = "",
                    roles: list | None = None, steps: list | None = None,
                    start_condition: dict | None = None,
                    prerequisites: dict | None = None, time_limit_s: int = 0,
                    origin: str = "admin", state: str = "draft") -> dict:
    """Insert a new template at revision 1. An unknown origin/state is
    refused by the table's CHECK (sqlite3.IntegrityError)."""
    template_id = "qt_" + uuid.uuid4().hex[:12]
    now = utc_now_iso()
    with keyed_lock("quest_template", template_id), transaction() as conn:
        conn.execute(
            "INSERT INTO quest_templates (id, title, summary, gm_notes, origin, "
            "state, roles, steps, start_condition, prerequisites, time_limit_s, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (template_id, title or "", summary or "", gm_notes or "", origin, state,
             _dump(_container(roles, list)), _dump(_container(steps, list)),
             _dump(_container(start_condition, dict)),
             _dump(_container(prerequisites, dict)), int(time_limit_s or 0),
             now, now))
    return get_template(template_id)


def get_template(template_id: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM quest_templates WHERE id=?", (template_id,)).fetchone()
    return _template_dict(row)


def list_templates(*, origin: str = "", state: str = "") -> list[dict]:
    """Templates, newest first, optionally filtered by origin and state."""
    where, params = [], []
    if origin:
        where.append("origin=?")
        params.append(origin)
    if state:
        where.append("state=?")
        params.append(state)
    sql = "SELECT * FROM quest_templates"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, rowid DESC"
    return [_template_dict(r) for r in get_connection().execute(sql, params).fetchall()]


def update_template(template_id: str, changes: dict, *, base_revision: int) -> dict:
    """Apply ``changes`` (editable keys only) when the stored revision is
    ``base_revision``; the revision goes up by one.

    Raises ValueError for a key outside ``EDITABLE_TEMPLATE_KEYS``, KeyError
    for an unknown id and ``StaleRevision`` when the revision moved on —
    in both refusal cases nothing is written.
    """
    unknown = sorted(set(changes) - set(EDITABLE_TEMPLATE_KEYS))
    if unknown:
        raise ValueError(f"not editable on a quest template: {', '.join(unknown)}")
    cols, params = [], []
    for key, value in changes.items():
        if key in _TEMPLATE_JSON_FIELDS:
            value = _dump(_container(value, _TEMPLATE_JSON_FIELDS[key]))
        elif key in ("time_limit_s", "kept"):
            value = int(value or 0)
        else:
            value = value if isinstance(value, str) else str(value or "")
        cols.append(f"{key}=?")
        params.append(value)
    with keyed_lock("quest_template", template_id), transaction() as conn:
        row = conn.execute("SELECT revision FROM quest_templates WHERE id=?",
                           (template_id,)).fetchone()
        if row is None:
            raise KeyError(template_id)
        if int(row[0]) != int(base_revision):
            raise StaleRevision(template_id, int(row[0]))
        conn.execute(
            "UPDATE quest_templates SET " + ", ".join(
                cols + ["revision=revision+1", "updated_at=?"]) + " WHERE id=?",
            (*params, utc_now_iso(), template_id))
    return get_template(template_id)


def delete_template(template_id: str) -> bool:
    """Delete one template row. Runs keep their snapshot; whether a delete is
    allowed while a run is open is the caller's decision."""
    with keyed_lock("quest_template", template_id), transaction() as conn:
        cur = conn.execute("DELETE FROM quest_templates WHERE id=?", (template_id,))
        return cur.rowcount > 0


# ── Runs ─────────────────────────────────────────────────────────────────

def create_run(*, template: dict, bindings: dict, state: str, started_by: str = "",
               expires_at: str = "", binding_labels: dict | None = None) -> dict:
    """Insert a run that freezes ``template`` as its snapshot and
    ``binding_labels`` (role key -> display label, frozen at start: a rename
    later never changes what the quest book says).

    A run created ``open`` gets ``started_game_ts`` stamped here; a
    ``hidden``/``preparing`` run gets it from ``open_run``. An unknown
    state is refused by the table's CHECK (sqlite3.IntegrityError).
    """
    run_id = "qr_" + uuid.uuid4().hex[:12]
    started = game_time().canonical() if state == "open" else ""
    now = utc_now_iso()
    snapshot = dict(template or {})
    with keyed_lock("quest_run", run_id), transaction() as conn:
        conn.execute(
            "INSERT INTO quest_runs (id, template_id, state, bindings, "
            "binding_labels, template_snapshot, started_by, started_game_ts, "
            "expires_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, str(snapshot.get("id") or ""), state,
             _dump(_container(bindings, dict)),
             _dump(_container(binding_labels, dict)), _dump(snapshot), started_by or "",
             started, expires_at or "", now, now))
    return get_run(run_id)


def get_run(run_id: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM quest_runs WHERE id=?", (run_id,)).fetchone()
    return _run_dict(row)


def list_runs(*, states: tuple[str, ...] = (), limit: int = 0) -> list[dict]:
    """Runs newest first, optionally only those in ``states``."""
    sql, params = "SELECT * FROM quest_runs", []
    if states:
        sql += " WHERE state IN (%s)" % ",".join("?" * len(states))
        params.extend(states)
    sql += " ORDER BY created_at DESC, rowid DESC"
    if limit and int(limit) > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [_run_dict(r) for r in get_connection().execute(sql, params).fetchall()]


def list_chronicle(limit: int) -> list[dict]:
    """The ``limit`` most recently ended runs that ever opened (a non-empty
    ``started_game_ts``), latest end first, ties newest-created first.
    Filtered and cut in SQL, so a caller decodes at most ``limit`` snapshots."""
    states = RUN_ENDED_STATES
    sql = ("SELECT * FROM quest_runs WHERE state IN (%s) AND started_game_ts<>'' "
           "ORDER BY COALESCE(ended_at, '') DESC, created_at DESC, rowid DESC LIMIT ?"
           % ",".join("?" * len(states)))
    rows = get_connection().execute(sql, (*states, max(0, int(limit)))).fetchall()
    return [_run_dict(r) for r in rows]


def count_runs(states: tuple[str, ...], *, template_id: str = "") -> int:
    """How many runs are in ``states`` (all runs for an empty tuple)."""
    where, params = [], []
    if states:
        where.append("state IN (%s)" % ",".join("?" * len(states)))
        params.extend(states)
    if template_id:
        where.append("template_id=?")
        params.append(template_id)
    sql = "SELECT COUNT(*) FROM quest_runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return int(get_connection().execute(sql, params).fetchone()[0])


def open_run(run_id: str, *, started_game_ts: str, expires_at: str = "") -> bool:
    """``hidden`` → ``open`` with the given stamps; any other state is refused."""
    with keyed_lock("quest_run", run_id), transaction() as conn:
        cur = conn.execute(
            "UPDATE quest_runs SET state='open', started_game_ts=?, expires_at=?, "
            "updated_at=? WHERE id=? AND state='hidden'",
            (started_game_ts, expires_at or "", utc_now_iso(), run_id))
        return cur.rowcount > 0


def set_run_state(run_id: str, state: str, *, issues: list | None = None,
                  from_states: tuple[str, ...] = ()) -> bool:
    """Move a run to ``state`` (optionally only from ``from_states``).

    Refused (False) for an unknown id, a run that already ended, or a
    current state outside ``from_states``. ``issues`` replaces the stored
    list when given. Entering an ended state stamps ``ended_game_ts`` and
    ``ended_at``. An unknown state raises sqlite3.IntegrityError (CHECK).

    The precondition lives in the UPDATE itself (``state`` must still be the
    one just read): the read runs outside any transaction, and
    ``expire_runs`` takes no run lock, so a run ended in between is refused
    by the rowcount instead of being overwritten.
    """
    ended = state in RUN_ENDED_STATES
    game_stamp = game_time().canonical() if ended else ""
    with keyed_lock("quest_run", run_id), transaction() as conn:
        row = conn.execute("SELECT state FROM quest_runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row[0] in RUN_ENDED_STATES:
            return False
        if from_states and row[0] not in from_states:
            return False
        now = utc_now_iso()
        cols, params = ["state=?", "updated_at=?"], [state, now]
        if issues is not None:
            cols.append("issues=?")
            params.append(_dump(_container(issues, list)))
        if ended:
            cols += ["ended_game_ts=?", "ended_at=?"]
            params += [game_stamp, now]
        cur = conn.execute(
            "UPDATE quest_runs SET " + ", ".join(cols) + " WHERE id=? AND state=?",
            (*params, run_id, row[0]))
        return cur.rowcount > 0


def set_run_field(run_id: str, field: str, value: str) -> bool:
    """Write one plain run field; only ``news_event_id`` is settable."""
    if field not in _SETTABLE_RUN_FIELDS:
        raise ValueError(f"not settable on a quest run: {field}")
    with keyed_lock("quest_run", run_id), transaction() as conn:
        cur = conn.execute(
            f"UPDATE quest_runs SET {field}=?, updated_at=? WHERE id=?",
            (value or "", utc_now_iso(), run_id))
        return cur.rowcount > 0


def record_step_done(run_id: str, step_index: int, *, avatar: str,
                     mind: str) -> dict | None:
    """Record that ``avatar`` (mind ``mind``) fulfilled step ``step_index``.

    Under the run lock: read the row, refuse (None) unless the run is
    ``open`` and its ``current_step`` is ``step_index`` — a second avatar
    fulfilling the same step, or a stale signal, writes nothing. Otherwise
    the step log gets ``{step, avatar, mind, game_ts}`` and the run advances,
    or ends ``done`` after the snapshot's last step. Returns the updated run.

    The read is not part of the write's transaction (autocommit SELECT) and
    ``expire_runs`` takes no run lock, so the UPDATE repeats the
    precondition (``state='open' AND current_step=?``); a rowcount of 0 —
    the run ended or moved on in between — is a refusal (None).
    """
    game_stamp = game_time().canonical()
    with keyed_lock("quest_run", run_id), transaction() as conn:
        run = _run_dict(conn.execute(
            "SELECT * FROM quest_runs WHERE id=?", (run_id,)).fetchone())
        if run is None or run["state"] != "open" or int(run["current_step"]) != int(step_index):
            return None
        log = list(run["step_log"])
        log.append({"step": int(step_index), "avatar": avatar, "mind": mind,
                    "game_ts": game_stamp})
        steps = run["template_snapshot"].get("steps")
        total = len(steps) if isinstance(steps, list) else 0
        now = utc_now_iso()
        if int(step_index) + 1 >= total:
            cur = conn.execute(
                "UPDATE quest_runs SET step_log=?, current_step=?, state='done', "
                "ended_game_ts=?, ended_at=?, updated_at=? "
                "WHERE id=? AND state='open' AND current_step=?",
                (_dump(log), int(step_index) + 1, game_stamp, now, now, run_id,
                 int(step_index)))
        else:
            cur = conn.execute(
                "UPDATE quest_runs SET step_log=?, current_step=?, updated_at=? "
                "WHERE id=? AND state='open' AND current_step=?",
                (_dump(log), int(step_index) + 1, now, run_id, int(step_index)))
        if cur.rowcount == 0:
            return None
    return get_run(run_id)


def expire_runs(now_canonical: str) -> list[str]:
    """Fail every hidden/open run whose ``expires_at`` lies before
    ``now_canonical`` (canonical game stamps compare as text); returns the
    ids. ``ended_game_ts`` is the passed stamp."""
    now = utc_now_iso()
    with transaction() as conn:
        rows = conn.execute(
            "UPDATE quest_runs SET state='failed', ended_game_ts=?, ended_at=?, "
            "updated_at=? WHERE state IN ('hidden', 'open') AND expires_at<>'' "
            "AND expires_at<? RETURNING id",
            (now_canonical, now, now, now_canonical)).fetchall()
    return [r[0] for r in rows]


# ── Facts ────────────────────────────────────────────────────────────────

def add_fact(mind: str, kind: str, subject: str) -> bool:
    """Record a fact once; True only when it was newly written."""
    with transaction() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO quest_facts (mind, kind, subject, game_ts, "
            "created_at) VALUES (?,?,?,?,?)",
            (mind, kind, subject, game_time().canonical(), utc_now_iso()))
        return cur.rowcount > 0


def has_fact(mind: str, kind: str, subject: str) -> bool:
    return get_connection().execute(
        "SELECT 1 FROM quest_facts WHERE mind=? AND kind=? AND subject=?",
        (mind, kind, subject)).fetchone() is not None


def delete_facts_about(name: str) -> int:
    """Delete every fact whose mind OR subject is ``name``; returns the count.

    ``delete_character`` and the import wipe run the same DELETE as raw SQL
    on their own connection (one transaction each).
    """
    with transaction() as conn:
        cur = conn.execute("DELETE FROM quest_facts WHERE mind=? OR subject=?",
                           (name, name))
        return cur.rowcount
