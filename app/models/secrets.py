"""Character secrets, stored in the selected world's world.db secrets table.

Track a character's own secrets and what it knows about others.
Prompt construction includes both owned secrets and known information.
"""
import json
import uuid

from app.core.timeutils import utc_now_iso, game_time
from app.core.keyed_lock import keyed_lock
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("secrets")

SEVERITY_LABELS = {
    1: "harmless",
    2: "embarrassing",
    3: "serious",
    4: "dangerous",
    5: "devastating",
}

VALID_CATEGORIES = ("personal", "relationship", "location", "criminal")
VALID_SOURCES = ("manual", "generated", "discovered", "event", "conversation", "record")

KNOWN_PER_OWNER = 3
KNOWN_TOTAL = 8


def is_record(secret: dict) -> bool:
    """Whether a secret mirrors a written record."""
    return secret.get("source") == "record"


def _row_to_secret(row, *, strict: bool = False) -> Dict[str, Any]:
    """Convert a database row into a secret dictionary.
    Schema: (id INTEGER, character_name, content, visibility, meta)
    """
    meta = {}
    try:
        meta = json.loads(row[4] or "{}")
    except Exception:
        if strict:
            raise
        pass
    if not isinstance(meta, dict):
        if strict:
            raise ValueError("Secret metadata is not an object")
        meta = {}
    # Metadata normally holds the complete original secret. Imported or older
    # rows may keep required fields only in their columns, so fill them here.
    if not meta.get("content"):
        meta["content"] = row[2] or ""
    meta.setdefault("id", f"sec_{row[0]}")
    meta.setdefault("category", "personal")
    meta.setdefault("severity", 2)
    if "known_by" not in meta or "discovered_by" not in meta:
        vis = {}
        try:
            vis = json.loads(row[3] or "{}")
        except Exception:
            if strict:
                raise
            pass
        if strict and not isinstance(vis, dict):
            raise ValueError("Secret visibility is not an object")
        meta.setdefault("known_by", vis.get("known_by", []) if isinstance(vis, dict) else [])
        meta.setdefault("discovered_by", vis.get("discovered_by", []) if isinstance(vis, dict) else [])
    meta.setdefault("source_ref", "")
    meta.setdefault("known_at", {})
    return meta


def _load_secrets(character_name: str, *, strict: bool = False) -> List[Dict[str, Any]]:
    """Load a character's secrets; strict reads propagate storage/JSON errors."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, character_name, content, visibility, meta "
            "FROM secrets WHERE character_name=? ORDER BY id ASC",
            (character_name,),
        ).fetchall()
        return [_row_to_secret(r, strict=strict) for r in rows]
    except Exception as e:
        if strict:
            raise
        logger.error("_load_secrets DB-Fehler fuer %s: %s", character_name, e)
        return []


def _save_secrets(character_name: str, secrets: List[Dict[str, Any]]):
    """Save all of a character's secrets to the DB."""
    try:
        with transaction() as conn:
            # Load existing rows as DB ID -> string ID.
            existing_rows = conn.execute(
                "SELECT id, meta FROM secrets WHERE character_name=?",
                (character_name,),
            ).fetchall()
            db_to_str: Dict[int, str] = {}
            str_to_db: Dict[str, int] = {}
            for db_id, meta_str in existing_rows:
                try:
                    m = json.loads(meta_str or "{}")
                    str_id = m.get("id", f"sec_{db_id}")
                except Exception:
                    str_id = f"sec_{db_id}"
                db_to_str[db_id] = str_id
                str_to_db[str_id] = db_id

            new_str_ids = {s.get("id") for s in secrets if s.get("id")}

            # Geloeschte entfernen
            for db_id, str_id in db_to_str.items():
                if str_id not in new_str_ids:
                    conn.execute("DELETE FROM secrets WHERE id=?", (db_id,))

            # Upsert
            for secret in secrets:
                str_id = secret.get("id")
                if not str_id:
                    continue
                visibility = json.dumps({
                    "known_by": secret.get("known_by", []),
                    "discovered_by": secret.get("discovered_by", []),
                }, ensure_ascii=False)
                meta_str = json.dumps(secret, ensure_ascii=False)

                if str_id in str_to_db:
                    conn.execute(
                        "UPDATE secrets SET content=?, visibility=?, meta=? WHERE id=?",
                        (secret.get("content", ""), visibility, meta_str,
                         str_to_db[str_id]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO secrets (character_name, content, visibility, meta) "
                        "VALUES (?, ?, ?, ?)",
                        (character_name, secret.get("content", ""), visibility, meta_str),
                    )
    except Exception as e:
        logger.error("_save_secrets DB-Fehler fuer %s: %s", character_name, e)


def list_secrets(character_name: str, *, strict: bool = False) -> List[Dict[str, Any]]:
    """List a character's secrets, optionally propagating read errors."""
    return _load_secrets(character_name, strict=strict)


def get_secret(character_name: str, secret_id: str) -> Optional[Dict[str, Any]]:
    """Gibt ein einzelnes Geheimnis zurueck."""
    secrets = _load_secrets(character_name)
    for s in secrets:
        if s.get("id") == secret_id:
            return s
    return None


def add_secret(character_name: str,
    content: str,
    category: str = "personal",
    severity: int = 2,
    related_characters: Optional[List[str]] = None,
    related_location: Optional[str] = None,
    consequences_if_revealed: str = "",
    source: str = "manual",
    known_by: Optional[List[str]] = None,
    source_ref: str = "") -> Dict[str, Any]:
    """Create a secret for a character."""
    with keyed_lock("secrets", character_name):
        if category not in VALID_CATEGORIES:
            category = "personal"
        severity = max(1, min(5, severity))
        if source not in VALID_SOURCES:
            source = "manual"

        secrets = _load_secrets(character_name)
        now = utc_now_iso()

        secret = {
            "id": f"sec_{uuid.uuid4().hex[:8]}",
            "content": content.strip(),
            "category": category,
            "severity": severity,
            "known_by": known_by or [],
            "discovered_by": [],
            "created_at": now,
            "discovered_at": None,
            "source": source,
            "source_ref": source_ref,
            "known_at": {},
            "related_characters": related_characters or [],
            "related_location": related_location or None,
            "consequences_if_revealed": consequences_if_revealed.strip(),
        }

        secrets.append(secret)
        _save_secrets(character_name, secrets)
        logger.info("Secret erstellt: %s fuer %s (severity=%d, category=%s)",
                    secret["id"], character_name, severity, category)
        return secret


def update_secret(character_name: str,
    secret_id: str,
    updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update editable fields of an existing secret."""
    with keyed_lock("secrets", character_name):
        secrets = _load_secrets(character_name)
        for s in secrets:
            if s.get("id") == secret_id:
                # Update allowed fields.
                allowed = {
                    "content", "category", "severity", "known_by", "discovered_by",
                    "related_characters", "related_location", "consequences_if_revealed",
                    "discovered_at", "source",
                }
                for key, value in updates.items():
                    if key in allowed:
                        s[key] = value
                # Validate editable values.
                if s.get("category") not in VALID_CATEGORIES:
                    s["category"] = "personal"
                s["severity"] = max(1, min(5, s.get("severity", 2)))
                _save_secrets(character_name, secrets)
                logger.info("Secret aktualisiert: %s", secret_id)
                return s
        return None


def delete_secret(character_name: str, secret_id: str) -> bool:
    """Delete a secret by id."""
    with keyed_lock("secrets", character_name):
        secrets = _load_secrets(character_name)
        new_secrets = [s for s in secrets if s.get("id") != secret_id]
        if len(new_secrets) < len(secrets):
            _save_secrets(character_name, new_secrets)
            logger.info("Secret geloescht: %s", secret_id)
            return True
        return False


def add_known_by(character_name: str,
    secret_id: str,
    knower_name: str,
    discovered: bool = False) -> bool:
    """Add a knower, stamping first learning with game time.

    discovered=True marks independent discovery.
    """
    with keyed_lock("secrets", character_name):
        secrets = _load_secrets(character_name)
        for s in secrets:
            if s.get("id") == secret_id:
                known_by = s.get("known_by", [])
                if knower_name not in known_by:
                    known_by.append(knower_name)
                    s["known_by"] = known_by
                    s.setdefault("known_at", {})[knower_name] = game_time().canonical()
                if discovered:
                    discovered_by = s.get("discovered_by", [])
                    if knower_name not in discovered_by:
                        discovered_by.append(knower_name)
                        s["discovered_by"] = discovered_by
                    if not s.get("discovered_at"):
                        s["discovered_at"] = utc_now_iso()
                _save_secrets(character_name, secrets)
                logger.info("Secret %s: %s weiss jetzt davon (discovered=%s)",
                            secret_id, knower_name, discovered)
                return True
        return False


def delete_secrets_by_ref(character_name: str, source_ref: str) -> int:
    """Delete all secrets with this exact source reference; return the count."""
    with keyed_lock("secrets", character_name):
        secrets = _load_secrets(character_name)
        remaining = [s for s in secrets if s.get("source_ref", "") != source_ref]
        count = len(secrets) - len(remaining)
        if count:
            _save_secrets(character_name, remaining)
        return count


# Secrets about other characters that this observer knows.

def get_known_secrets_about(observer_name: str) -> List[Dict[str, Any]]:
    """Return secrets about others whose known_by list contains this observer."""
    from app.models.character import list_available_characters

    known = []
    all_chars = list_available_characters()
    for char_name in all_chars:
        if char_name == observer_name:
            continue
        secrets = _load_secrets(char_name)
        for s in secrets:
            if observer_name in s.get("known_by", []):
                known.append({
                    "secret_owner": char_name,
                    "secret": s,
                })
    return known


# --- Prompt-Injection ---

def known_about_others_block(character_name: str) -> str:
    """Render known secrets with the chat limits and learning order."""
    # Learning stamps precede legacy entries; creation time orders the latter.
    def learned_order(entry):
        secret = entry["secret"]
        stamp = secret.get("known_at", {}).get(character_name)
        return (bool(stamp), stamp or secret.get("created_at") or "")

    candidates = sorted(get_known_secrets_about(character_name),
                        key=learned_order, reverse=True)
    known_about_others = []
    counts = {}
    for entry in candidates:
        owner = entry["secret_owner"]
        if not (entry["secret"].get("content") or "").strip():
            continue
        if counts.get(owner, 0) >= KNOWN_PER_OWNER:
            continue
        known_about_others.append(entry)
        counts[owner] = counts.get(owner, 0) + 1
        if len(known_about_others) >= KNOWN_TOTAL:
            break

    if known_about_others:
        lines = []
        for entry in known_about_others:
            owner = entry["secret_owner"]
            s = entry["secret"]
            content = (s.get("content") or "").strip()
            if not content:
                continue
            discovered = character_name in s.get("discovered_by", [])
            method = "you discovered this yourself" if discovered else "someone told you"
            sev = s.get("severity", 2)
            lines.append(f"- About {owner}: {content} ({method}, severity {sev}/5)")

        return (
            "\nSecrets you know about others:\n"
            + "\n".join(lines)
            + "\n\nWhen someone asks directly about one of these people, consider sharing what you know — "
            + "BUT only if: (a) you trust them more than the secret's owner, OR (b) the severity is low, "
            + "OR (c) you have reason to betray the owner (bad relationship, recent conflict). "
            + "Otherwise deflect, lie, or partially reveal. Never volunteer high-severity secrets unprompted."
        )

    return ""


def build_secrets_prompt_section(character_name: str) -> str:
    """Build own secrets and a bounded list of recently learned secrets."""
    own_secrets = [s for s in list_secrets(character_name) if not is_record(s)]
    known_block = known_about_others_block(character_name)
    parts = []

    # Own secrets
    if own_secrets:
        lines = []
        for s in own_secrets:
            content = (s.get("content") or "").strip()
            if not content:
                continue
            severity_label = SEVERITY_LABELS.get(s.get("severity", 2), "unknown")
            line = f"- {content} (severity: {severity_label})"
            if s.get("consequences_if_revealed"):
                line += f" — if revealed: {s['consequences_if_revealed']}"
            visible_knowers = [name for name in s.get("known_by", [])
                               if name not in s.get("discovered_by", [])]
            if visible_knowers:
                knowers = ", ".join(visible_knowers)
                line += f" [known by: {knowers}]"
            lines.append(line)

        parts.append(
            "\nYour secrets (things you keep to yourself — never reveal these unless you choose to):\n"
            + "\n".join(lines)
        )

    if known_block:
        parts.append(known_block)
    return "\n".join(parts)
