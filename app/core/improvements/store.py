"""DB access for improvements + steps (world.db).  No engine logic here."""
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now_iso
from app.models.world import get_world_setting, set_world_setting

logger = get_logger("improvements.store")

SETTING_ENABLED = "improvements_enabled"
SETTING_IDLE_MINUTES = "improvements_idle_minutes"
DEFAULT_IDLE_MINUTES = 15

# Columns `update()` accepts — everything else is either derived (counters) or
# identity (id, type_id, created_at, position; the order has its own setter).
_UPDATABLE = {"label", "params", "mode", "status", "last_scan_at",
              "done_count", "failed_count"}

_STEP_STATUSES = ("pending", "running", "done", "failed", "skipped")


def _row_to_improvement(row) -> Dict[str, Any]:
    """sqlite Row -> dict, with `params` decoded and the counters at zero."""
    d = dict(row)
    try:
        d["params"] = json.loads(d.get("params") or "{}")
    except (ValueError, TypeError):
        d["params"] = {}
    for s in _STEP_STATUSES:
        d.setdefault(s, 0)
    return d


def _counters() -> Dict[str, Dict[str, int]]:
    """One GROUP BY for every improvement: {improvement_id: {status: count}}."""
    conn = get_connection()
    out: Dict[str, Dict[str, int]] = {}
    for r in conn.execute(
        "SELECT improvement_id, status, COUNT(*) AS n "
        "FROM improvement_steps GROUP BY improvement_id, status"
    ).fetchall():
        out.setdefault(r["improvement_id"], {})[r["status"]] = r["n"]
    return out


def _apply_counters(row: Dict[str, Any], counts: Dict[str, int]) -> Dict[str, Any]:
    for s in _STEP_STATUSES:
        row[s] = int(counts.get(s, 0))
    return row


def create(type_id: str, label: str, params: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """position = max(position)+1; returns the row dict."""
    improvement_id = uuid.uuid4().hex[:12]
    now = utc_now_iso()
    with transaction() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), 0) AS p FROM improvements"
        ).fetchone()
        position = int(row["p"]) + 1
        conn.execute(
            "INSERT INTO improvements (id, type_id, label, params, mode, "
            "status, position, created_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
            (improvement_id, type_id, label or "", json.dumps(params or {}),
             mode or "one_shot", position, now),
        )
    return get(improvement_id) or {}


def get(improvement_id: str) -> Optional[Dict[str, Any]]:
    """Row dict incl. the same counters as list_all() (pending/running/done/failed/skipped)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM improvements WHERE id=?", (improvement_id,)
    ).fetchone()
    if not row:
        return None
    counts: Dict[str, int] = {}
    for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM improvement_steps "
        "WHERE improvement_id=? GROUP BY status", (improvement_id,)
    ).fetchall():
        counts[r["status"]] = r["n"]
    return _apply_counters(_row_to_improvement(row), counts)


def list_all() -> List[Dict[str, Any]]:
    """ORDER BY position, created_at; each row gets counters pending/running/
    done/failed/skipped from improvement_steps (one GROUP BY query);
    `params` already json-decoded."""
    conn = get_connection()
    counts = _counters()
    return [
        _apply_counters(_row_to_improvement(r), counts.get(r["id"], {}))
        for r in conn.execute(
            "SELECT * FROM improvements ORDER BY position, created_at"
        ).fetchall()
    ]


def update(improvement_id: str, **fields) -> None:
    """label, params(json), mode, status, last_scan_at, done_count, failed_count."""
    sets: List[str] = []
    values: List[Any] = []
    for key, value in fields.items():
        if key not in _UPDATABLE:
            raise ValueError(f"improvements.update: unknown field '{key}'")
        if key == "params":
            value = json.dumps(value or {}) if not isinstance(value, str) else value
        sets.append(f"{key}=?")
        values.append(value)
    if not sets:
        return
    values.append(improvement_id)
    with transaction() as conn:
        conn.execute(
            f"UPDATE improvements SET {', '.join(sets)} WHERE id=?", values)


def delete(improvement_id: str) -> None:
    """Deletes the improvement and its steps."""
    with transaction() as conn:
        conn.execute("DELETE FROM improvement_steps WHERE improvement_id=?",
                     (improvement_id,))
        conn.execute("DELETE FROM improvements WHERE id=?", (improvement_id,))


def set_order(ids: List[str]) -> None:
    """position = index."""
    with transaction() as conn:
        for index, improvement_id in enumerate(ids):
            conn.execute("UPDATE improvements SET position=? WHERE id=?",
                         (index, improvement_id))


def replace_steps_scan(improvement_id: str,
                       candidates: List[Tuple[str, str]]) -> Dict[str, int]:
    """candidates = [(key, label)].  INSERT OR IGNORE new keys as pending;
    pending/skipped steps whose key is no longer listed -> done (is_done elsewhere);
    running/done/failed rows untouched.  Returns {"added": n, "closed": m}."""
    listed = {str(key) for key, _label in candidates}
    now = utc_now_iso()
    added = 0
    closed = 0
    with transaction() as conn:
        for key, label in candidates:
            cur = conn.execute(
                "INSERT OR IGNORE INTO improvement_steps "
                "(improvement_id, candidate_key, candidate_label, status) "
                "VALUES (?, ?, ?, 'pending')",
                (improvement_id, str(key), label or ""),
            )
            added += cur.rowcount if cur.rowcount > 0 else 0
        open_keys = [
            r["candidate_key"] for r in conn.execute(
                "SELECT candidate_key FROM improvement_steps "
                "WHERE improvement_id=? AND status IN ('pending', 'skipped')",
                (improvement_id,),
            ).fetchall()
        ]
        for key in open_keys:
            if key in listed:
                continue
            # Gone from the candidate list = the type no longer names it, which
            # can only mean the subject is done. No duration: nothing was worked.
            conn.execute(
                "UPDATE improvement_steps SET status='done', error='', "
                "finished_at=? WHERE improvement_id=? AND candidate_key=?",
                (now, improvement_id, key),
            )
            closed += 1
    return {"added": added, "closed": closed}


def list_steps(improvement_id: str) -> List[Dict[str, Any]]:
    """Running first (that is what the panel wants at the top), then by label."""
    conn = get_connection()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM improvement_steps WHERE improvement_id=? "
        "ORDER BY (status='running') DESC, candidate_label, candidate_key",
        (improvement_id,),
    ).fetchall()]


def next_pending(improvement_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM improvement_steps WHERE improvement_id=? "
        "AND status='pending' ORDER BY candidate_label, candidate_key LIMIT 1",
        (improvement_id,),
    ).fetchone()
    return dict(row) if row else None


def running_steps() -> List[Dict[str, Any]]:
    """All rows status='running' (any improvement)."""
    conn = get_connection()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM improvement_steps WHERE status='running' "
        "ORDER BY started_at, candidate_key"
    ).fetchall()]


def mark_running(improvement_id: str, key: str) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE improvement_steps SET status='running', started_at=? "
            "WHERE improvement_id=? AND candidate_key=?",
            (utc_now_iso(), improvement_id, key),
        )


def mark_result(improvement_id: str, key: str, *, status: str,
                error: str = "", count_attempt: bool) -> None:
    """status in done|pending|skipped; sets finished_at + duration_s (from
    started_at) on done/skipped; attempts += 1 when count_attempt."""
    if status not in ("done", "pending", "skipped"):
        raise ValueError(f"improvements.mark_result: bad status '{status}'")
    with transaction() as conn:
        row = conn.execute(
            "SELECT started_at FROM improvement_steps "
            "WHERE improvement_id=? AND candidate_key=?",
            (improvement_id, key),
        ).fetchone()
        if not row:
            return
        finished_at: Optional[str] = None
        duration_s: Optional[float] = None
        if status in ("done", "skipped"):
            finished_at = utc_now_iso()
            duration_s = _duration(row["started_at"], finished_at)
        conn.execute(
            "UPDATE improvement_steps SET status=?, error=?, "
            "attempts = attempts + ?, finished_at=?, duration_s=? "
            "WHERE improvement_id=? AND candidate_key=?",
            (status, error or "", 1 if count_attempt else 0,
             finished_at, duration_s, improvement_id, key),
        )


def retry_step(improvement_id: str, key: str) -> None:
    """The user's undo of a skip: a skipped step becomes runnable again, with a
    clean slate (attempts back to 0, error and finish stamps gone)."""
    with transaction() as conn:
        conn.execute(
            "UPDATE improvement_steps SET status='pending', attempts=0, "
            "error='', finished_at=NULL, duration_s=NULL "
            "WHERE improvement_id=? AND candidate_key=? AND status='skipped'",
            (improvement_id, key),
        )


def reset_running_to_pending() -> int:
    """A crash leaves 'running' rows behind — make them runnable again."""
    with transaction() as conn:
        cur = conn.execute(
            "UPDATE improvement_steps SET status='pending', started_at=NULL "
            "WHERE status='running'")
        return cur.rowcount if cur.rowcount > 0 else 0


def recent_done(limit: int = 20) -> List[Dict[str, Any]]:
    """done/skipped ORDER BY finished_at DESC, joined with improvement label/type."""
    conn = get_connection()
    return [dict(r) for r in conn.execute(
        "SELECT s.*, i.label AS label, i.type_id AS type_id "
        "FROM improvement_steps s JOIN improvements i ON i.id = s.improvement_id "
        "WHERE s.status IN ('done', 'skipped') "
        "ORDER BY s.finished_at DESC LIMIT ?", (int(limit),),
    ).fetchall()]


def avg_duration_by_type() -> Dict[str, float]:
    """AVG(duration_s) of done steps grouped by improvements.type_id."""
    conn = get_connection()
    return {r["type_id"]: float(r["avg_s"]) for r in conn.execute(
        "SELECT i.type_id AS type_id, AVG(s.duration_s) AS avg_s "
        "FROM improvement_steps s JOIN improvements i ON i.id = s.improvement_id "
        "WHERE s.status='done' AND s.duration_s IS NOT NULL "
        "GROUP BY i.type_id"
    ).fetchall()}


def pending_count_by_type(open_only: bool = True) -> Dict[str, int]:
    """Pending steps grouped by the improvement's type_id.

    ``open_only`` (the default) counts only steps of an entry that is still
    'open' — that is what the panel means by "waiting".  A paused entry runs
    nothing, so its steps must inflate neither the pending total nor the
    estimate; pass False to count every pending step regardless of the entry.
    """
    conn = get_connection()
    entry_filter = " AND i.status='open'" if open_only else ""
    return {r["type_id"]: int(r["n"]) for r in conn.execute(
        "SELECT i.type_id AS type_id, COUNT(*) AS n "
        "FROM improvement_steps s JOIN improvements i ON i.id = s.improvement_id "
        f"WHERE s.status='pending'{entry_filter} GROUP BY i.type_id"
    ).fetchall()}


def get_settings() -> Dict[str, Any]:
    raw = get_world_setting(SETTING_IDLE_MINUTES, "")
    try:
        idle_minutes = int(raw) if raw else DEFAULT_IDLE_MINUTES
    except ValueError:
        idle_minutes = DEFAULT_IDLE_MINUTES
    return {
        "enabled": get_world_setting(SETTING_ENABLED, "0") == "1",
        "idle_minutes": _clamp_idle(idle_minutes),
    }


def set_settings(enabled: bool, idle_minutes: int) -> None:
    set_world_setting(SETTING_ENABLED, "1" if enabled else "0")
    set_world_setting(SETTING_IDLE_MINUTES, str(_clamp_idle(idle_minutes)))


def _clamp_idle(minutes: int) -> int:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES
    return max(1, min(1440, value))


def _duration(started_at: Optional[str], finished_at: str) -> Optional[float]:
    """Seconds between two ISO stamps; None when the step never started."""
    if not started_at:
        return None
    try:
        return max(0.0, (parse_iso(finished_at) - parse_iso(started_at)).total_seconds())
    except (ValueError, TypeError) as e:
        logger.debug("duration from %r failed: %s", started_at, e)
        return None
