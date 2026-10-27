"""Durable prop runs; exclusive person and exact slot claims share one transaction.

No profile locks/callbacks are taken here. Claim acquisition reads guards only.
Effect adapters acquire sorted participant profile locks BEFORE transaction(),
then write bounded state, receipts and run progress on its dedicated connection.
Notifications and journey/cleanup callbacks run after commit.
"""
from contextlib import contextmanager
import json
import sqlite3
from app.core import db
from app.core.timeutils import utc_now_iso

TERMINAL = frozenset(("completed", "cancelled", "failed"))
JSON_FIELDS = ("target", "definition", "data")


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@contextmanager
def transaction():
    # Dedicated connection: lazy catalog readers must not commit the claims
    # transaction through db.transaction's thread-local connection.
    conn = sqlite3.connect(str(db.get_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _decode(row):
    if row is None:
        return None
    result = dict(row)
    for key in JSON_FIELDS:
        result[key] = json.loads(result[key])
    return result


def get(execution_id, *, conn=None):
    return _decode((conn or db.get_connection()).execute(
        "SELECT * FROM prop_action_runs WHERE execution_id=?", (execution_id,)).fetchone())


def by_request(actor, request_id, *, conn=None):
    if not request_id:
        return None
    return _decode((conn or db.get_connection()).execute(
        "SELECT * FROM prop_action_runs WHERE actor=? AND request_id=?", (actor, request_id)).fetchone())


def live_runs():
    return [_decode(r) for r in db.get_connection().execute(
        "SELECT * FROM prop_action_runs WHERE status NOT IN ('completed','cancelled','failed') ORDER BY created_at,execution_id")]


def claims(execution_id=None, *, conn=None):
    sql = "SELECT * FROM prop_action_claims"
    args = ()
    if execution_id is not None:
        sql += " WHERE execution_id=?"
        args = (execution_id,)
    return [dict(r) for r in (conn or db.get_connection()).execute(sql, args)]


def person_key(name):
    return encode(["person", name])


def slot_key(target, marker_id, slot):
    return encode(["slot", target["location_id"], target["room_id"], target["placement_id"],
                   target["variant_uid"], marker_id, slot])


def held(key, *, conn=None):
    row = (conn or db.get_connection()).execute(
        "SELECT execution_id FROM prop_action_claims WHERE claim_key=?", (key,)).fetchone()
    return row[0] if row else None


def acquire(conn, run, slots):
    """Caller rechecks guards under BEGIN IMMEDIATE before this all-or-none write."""
    entries = [(person_key(n), "person", {"name": n}) for n in (run["actor"], run["partner"]) if n]
    entries += [(slot_key(run["target"], s["marker_id"], s["slot"]), "slot", s) for s in slots]
    for key, kind, subject in entries:
        conn.execute("INSERT INTO prop_action_claims VALUES (?,?,?,?)",
                     (key, run["execution_id"], kind, encode(subject)))


def insert(conn, run):
    row = dict(run, created_at=utc_now_iso(), updated_at=utc_now_iso())
    keys = tuple(row)
    conn.execute("INSERT INTO prop_action_runs (" + ",".join(keys) + ") VALUES (" +
                 ",".join("?" for _ in keys) + ")",
                 tuple(encode(row[k]) if k in JSON_FIELDS else row[k] for k in keys))


def save(conn, run):
    """Never resurrect a terminal execution, including stale callback snapshots."""
    current = get(run["execution_id"], conn=conn)
    if not current or current["status"] in TERMINAL:
        return False
    conn.execute("UPDATE prop_action_runs SET status=?,phase=?,reason=?,data=?,updated_at=? WHERE execution_id=?",
                 (run["status"], run["phase"], run["reason"], encode(run["data"]), utc_now_iso(), run["execution_id"]))
    if run["status"] in TERMINAL:
        conn.execute("DELETE FROM prop_action_claims WHERE execution_id=?", (run["execution_id"],))
    return True


def pending_cleanup():
    return [_decode(r) for r in db.get_connection().execute(
        "SELECT * FROM prop_action_runs WHERE status IN ('completed','cancelled','failed') "
        "AND json_extract(data,'$.cleanup_pending')=1")]


def cleanup_finished(execution_id):
    with transaction() as conn:
        conn.execute("UPDATE prop_action_runs SET data=json_set(data,'$.cleanup_pending',json('false')) "
                     "WHERE execution_id=? AND status IN ('completed','cancelled','failed')", (execution_id,))
