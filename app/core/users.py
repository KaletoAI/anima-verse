"""User management (multiuser phase 1).

One users table per world. Roles: admin | user.
An admin has full access, a user is limited to the assigned characters.
"""
import hashlib
import json
import secrets
import uuid
from datetime import datetime

from app.core.timeutils import utc_now_iso
from typing import Dict, Any, List, Optional

import bcrypt

from app.core import sessions
from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("users")


ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}

DEFAULT_ADMIN_USERNAME = "admin"
MIN_PASSWORD_LENGTH = 8
# Length of the one-time bootstrap password. token_urlsafe(n) yields ~1.3*n
# characters of base64url, so 18 bytes is a ~24-character password.
BOOTSTRAP_PASSWORD_BYTES = 18


def _now_iso() -> str:
    return utc_now_iso()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def _row_to_user(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["allowed_characters"] = json.loads(d.get("allowed_characters") or "[]")
    except Exception:
        d["allowed_characters"] = []
    try:
        d["settings"] = json.loads(d.get("settings") or "{}")
    except Exception:
        d["settings"] = {}
    d.pop("password_hash", None)
    return d


#: The fields ``update_user`` writes — and so the ones an admin edit could
#: overwrite. The revision of a user covers exactly these: a change to any of
#: them by another admin or by the player's own actions (an avatar switch, a
#: character grant) makes an edit based on the older state stale.
REVISION_FIELDS = ("username", "role", "allowed_characters", "theme", "settings")


class UserStale(Exception):
    """The user changed since the revision the edit was based on."""


def user_revision(user: Dict[str, Any]) -> str:
    """The revision token of a user dict (as ``get_user_by_id`` returns it). Pure."""
    payload = json.dumps({f: user.get(f) for f in REVISION_FIELDS},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def list_users() -> List[Dict[str, Any]]:
    """All users (without password_hash), each with its ``revision``."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, username, role, allowed_characters, theme, settings, "
        "created_at, last_login FROM users ORDER BY created_at ASC"
    ).fetchall()
    out = [_row_to_user(r) for r in rows]
    for user in out:
        user["revision"] = user_revision(user)
    return out


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, username, role, allowed_characters, theme, settings, "
        "created_at, last_login FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, username, role, allowed_characters, theme, settings, "
        "created_at, last_login FROM users WHERE username=?",
        (username,),
    ).fetchone()
    return _row_to_user(row) if row else None


def _get_password_hash(user_id: str) -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id=?", (user_id,)
    ).fetchone()
    return row["password_hash"] if row else ""


def check_user_password(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Check username + password. The user dict on success, None otherwise."""
    user = get_user_by_username(username)
    if not user:
        return None
    pwd_hash = _get_password_hash(user["id"])
    if not verify_password(password, pwd_hash):
        return None
    return user


def create_user(
    username: str,
    password: str,
    role: str = ROLE_USER,
    allowed_characters: Optional[List[str]] = None,
) -> str:
    """Create a new user. Returns the user id."""
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if get_user_by_username(username):
        raise ValueError(f"Username already exists: {username}")

    user_id = f"u_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, "
            "allowed_characters, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id, username, hash_password(password), role,
                json.dumps(allowed_characters or [], ensure_ascii=False),
                now,
            ),
        )
    logger.info("User angelegt: %s (role=%s)", username, role)
    return user_id


def update_user(user_id: str, **fields) -> bool:
    """Updates user fields. Supports: username, role, allowed_characters, theme, settings."""
    allowed = {"username", "role", "allowed_characters", "theme", "settings"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if "role" in updates and updates["role"] not in VALID_ROLES:
        raise ValueError(f"Invalid role: {updates['role']}")
    if "allowed_characters" in updates:
        updates["allowed_characters"] = json.dumps(
            updates["allowed_characters"], ensure_ascii=False
        )
    if "settings" in updates:
        updates["settings"] = json.dumps(updates["settings"], ensure_ascii=False)

    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [user_id]
    try:
        with transaction() as conn:
            cur = conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", values)
            return cur.rowcount > 0
    finally:
        # Role, allowed_characters and the active character (settings) are what
        # the auth lookup cache holds — the next request must see the change.
        sessions.invalidate_user(user_id)


def update_user_checked(user_id: str, base_revision: str, fields: Dict[str, Any],
                        password: Optional[str] = None) -> Optional[str]:
    """An admin edit: write ``fields`` (and ``password`` when given) only if the
    user is still at ``base_revision``. Returns the new revision, None for an
    unknown user. Raises ``UserStale`` (nothing written) or ``ValueError``.

    Runs under ``keyed_lock("user_settings", <id>)`` — the lock every other
    writer of the users row takes (the avatar switch, the login restore, the
    creator grant) — and re-reads the user INSIDE it, so no change can land
    between the check and the write. Only the given fields are written; the
    caller sends the ones that changed.
    """
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("user_settings", user_id):
        fresh = get_user_by_id(user_id)
        if not fresh:
            return None
        if user_revision(fresh) != base_revision:
            raise UserStale(user_id)
        # Validate everything before the first write, so a refused value
        # never leaves half an edit behind.
        if "role" in fields and fields["role"] not in VALID_ROLES:
            raise ValueError(f"Invalid role: {fields['role']}")
        if password and len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        if password:
            set_user_password(user_id, password)
        if fields:
            update_user(user_id, **fields)
        return user_revision(get_user_by_id(user_id) or {})


def set_user_password(user_id: str, password: str) -> bool:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    try:
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (hash_password(password), user_id),
            )
            return cur.rowcount > 0
    finally:
        # The hash is not cached, but whoever changes a password also ends
        # sessions (sessions.delete_*), and a fresh read costs nothing here.
        sessions.invalidate_user(user_id)


def delete_user(user_id: str) -> bool:
    try:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            return cur.rowcount > 0
    finally:
        # A session whose user is gone resolves to no user from now on, even
        # before the caller deletes the user's sessions.
        sessions.invalidate_user(user_id)


def touch_last_login(user_id: str) -> None:
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE users SET last_login=? WHERE id=?", (_now_iso(), user_id)
            )
    finally:
        sessions.invalidate_user(user_id)


def ensure_default_admin() -> None:
    """Create the default admin when no user exists yet."""
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count > 0:
        return

    # Migration: take over the old account.user_name + password_hash if present
    acc = conn.execute(
        "SELECT user_name, password_hash, theme, settings FROM account WHERE id=1"
    ).fetchone()
    if acc and acc["user_name"] and acc["password_hash"]:
        user_id = f"u_{uuid.uuid4().hex[:12]}"
        with transaction() as c:
            c.execute(
                "INSERT INTO users (id, username, password_hash, role, "
                "allowed_characters, theme, settings, created_at) "
                "VALUES (?, ?, ?, 'admin', '[]', ?, ?, ?)",
                (
                    user_id, acc["user_name"], acc["password_hash"],
                    acc["theme"] or "", acc["settings"] or "{}", _now_iso(),
                ),
            )
        logger.info("Default-Admin aus account.json migriert: %s", acc["user_name"])
        return

    # Fresh world: bootstrap admin with a RANDOM password. A fixed default
    # ("admin1234") made every freshly created world takeable by anyone who
    # knew the project. The password exists only in this one log line — it is
    # never stored in clear text anywhere — so it has to be picked up now.
    password = secrets.token_urlsafe(BOOTSTRAP_PASSWORD_BYTES)
    create_user(DEFAULT_ADMIN_USERNAME, password, role=ROLE_ADMIN)
    logger.warning(
        "=== BOOTSTRAP ADMIN CREATED === username='%s' password='%s' — "
        "shown ONCE, log in and change it. ===",
        DEFAULT_ADMIN_USERNAME, password,
    )
