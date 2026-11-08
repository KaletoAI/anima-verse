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
JSON_FIELDS = ("members", "target", "definition", "data")


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
        from app.core.prop_actions import invalidate_offers_cache
        invalidate_offers_cache()
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


def people(run):
    """Everyone of ``run``: the initiator, then its invitees in invitation order."""
    return [run["actor"], *run["members"]]


#: SQL: the run names ``?`` as initiator or invitee (two parameters).
TAKES_PART = "(actor=? OR EXISTS (SELECT 1 FROM json_each(members) WHERE value=?))"


def acquire(conn, run, slots):
    """Caller rechecks guards under BEGIN IMMEDIATE before this all-or-none write."""
    entries = [(person_key(n), "person", {"name": n}) for n in people(run)]
    entries += [(slot_key(run["target"], s["marker_id"], s["slot"]), "slot", s) for s in slots]
    seen = set()
    for key, kind, subject in entries:
        # A pair sharing one place lists that slot once per role: one claim.
        if key in seen:
            continue
        seen.add(key)
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


def mark_late_answer(execution_id, name) -> bool:
    """Record ``name``'s answer to an invitation that had already EXPIRED
    (cancelled/consent_expired) — once: True only the first time, so the
    inviter hears of a late "yes" once per invitee. The one write a terminal
    run takes (``save`` never touches one); its status stays as it is."""
    with transaction() as conn:
        run = get(execution_id, conn=conn)
        if not run or (run["status"], run["reason"]) != ("cancelled", "consent_expired"):
            return False
        late = run["data"].setdefault("late_answers", [])
        if name in late:
            return False
        late.append(name)
        conn.execute("UPDATE prop_action_runs SET data=?,updated_at=? WHERE execution_id=?",
                     (encode(run["data"]), utc_now_iso(), execution_id))
    return True


def migrate_members(conn):
    """One-shot (db.init_schema): the old ``partner`` column becomes the
    ``members`` list, and a run's per-person data is keyed by NAME instead
    of the roles ``actor``/``partner`` — a group has several invitees. An
    open pair invitation gets its one ``consents`` entry. Returns the number
    of rows moved; 0 when the column is already gone."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prop_action_runs)")}
    if "partner" not in cols:
        return 0
    if "members" not in cols:
        conn.execute("ALTER TABLE prop_action_runs ADD COLUMN members TEXT NOT NULL DEFAULT '[]'")
    rows = conn.execute("SELECT execution_id, actor, partner, status, data FROM prop_action_runs").fetchall()
    for execution_id, actor, partner, status, raw in rows:
        data = json.loads(raw)
        names = {"actor": actor, "partner": partner}
        for key in ("plans", "access_roles"):
            if isinstance(data.get(key), dict):
                data[key] = {names.get(role) or role: value for role, value in data[key].items()}
        if partner and status == "awaiting_consent":
            data["consents"] = {partner: "pending"}
        conn.execute("UPDATE prop_action_runs SET members=?, data=? WHERE execution_id=?",
                     (encode([partner] if partner else []), encode(data), execution_id))
    conn.execute("ALTER TABLE prop_action_runs DROP COLUMN partner")
    return len(rows)


def pending_cleanup():
    return [_decode(r) for r in db.get_connection().execute(
        "SELECT * FROM prop_action_runs WHERE status IN ('completed','cancelled','failed') "
        "AND json_extract(data,'$.cleanup_pending')=1")]


def cleanup_finished(execution_id, exit_motions):
    with transaction() as conn:
        conn.execute("UPDATE prop_action_runs SET data=json_set(data,'$.cleanup_pending',json('false'),'$.exit_motions',json_patch(COALESCE(json_extract(data,'$.exit_motions'),'{}'),json(?))) "
                     "WHERE execution_id=? AND status IN ('completed','cancelled','failed')", (encode(exit_motions), execution_id))
