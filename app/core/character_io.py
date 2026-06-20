"""Character Export / Import — DB rows + filesystem char dir bundled in a ZIP.

ZIP layout (manifest version 2):
    manifest.json         — version, character_name, exported_at, options
    files/<rel-path>      — original character_dir contents (soul/, skills/,
                            images/, outfits/, *.json sidecars, ...)
    db/<table>.json       — list of dict rows for that character

Source of truth is `world.db`. The `characters` row carries profile_json /
config_json (the FS *.json files are only a legacy fallback). Without the DB
slice an "imported" character would have no memories, inventory, outfits,
schedule etc. — even though their FS dir would look intact.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

from app.core.timeutils import utc_now_iso
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.models.character import get_character_dir

logger = get_logger("character_io")

MANIFEST_VERSION = 2

# Per-character tables — `character_name` column.
# Order matters for import: insert into `characters` first, then everything else.
_OWNED_TABLES: Tuple[str, ...] = (
    "character_state",
    "memories",
    "summaries",
    "knowledge",
    "diary_entries",
    "state_history",
    "mood_history",
    "evolution_history",
    "inventory_items",
    "equipped_items",
    "equipped_pieces",
    "outfits_sets",
    "secrets",
    "daily_schedules",
    "scheduler_jobs",
    "assignments",
    "image_metadata",
    "telegram_mapping",
)

# Optional tables — only included when the matching flag is set.
_OPTIONAL_TABLES: Dict[str, str] = {
    "include_chats": "chat_messages",
    "include_stories": "stories",
}

# Tables we deliberately skip:
#   character_locks   — per-user runtime lock, not portable
#   llm_call_stats    — telemetry, agent_name reference only
#   session_kv / world_kv / users / account / schema_meta — not character-owned
#   notifications     — global notifications, no character ownership column

# Files we never include in the export (stale caches, hashes).
_FILE_EXCLUDE_NAMES = {".profile_hash"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone())


def _column_names(conn, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _row_to_dict(row, columns: List[str]) -> Dict[str, Any]:
    return {col: row[i] for i, col in enumerate(columns)}


def _dump_table(conn, table: str, where_sql: str, params: Tuple) -> List[Dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    cols = _column_names(conn, table)
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE {where_sql}", params
    ).fetchall()
    return [_row_to_dict(r, cols) for r in rows]


def _safe_relpath(rel: str) -> Optional[str]:
    """Reject absolute / traversal paths; return normalized POSIX rel or None."""
    if not rel or rel.endswith("/"):
        return None
    if rel.startswith("/") or rel.startswith("\\"):
        return None
    if ".." in Path(rel).parts:
        return None
    return rel


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_character_to_zip(
    character_name: str,
    *,
    include_chats: bool = False,
    include_stories: bool = False,
) -> bytes:
    """Bundles all character data (DB rows + char dir files) into a ZIP."""
    if not character_name or "/" in character_name or ".." in character_name:
        raise ValueError(f"invalid character_name: {character_name!r}")

    conn = get_connection()
    if not _table_exists(conn, "characters"):
        raise RuntimeError("world.db has no `characters` table — schema not initialized")

    # `characters` master row (profile_json + config_json)
    char_rows = _dump_table(conn, "characters", "name=?", (character_name,))
    if not char_rows:
        # Allow export even without a DB row (legacy FS-only chars), but mark it.
        logger.warning("export: no `characters` DB row for %s — exporting FS only",
                       character_name)

    db_dump: Dict[str, List[Dict[str, Any]]] = {}
    if char_rows:
        db_dump["characters"] = char_rows

    for table in _OWNED_TABLES:
        rows = _dump_table(conn, table, "character_name=?", (character_name,))
        if rows:
            db_dump[table] = rows

    # Optional tables
    if include_chats:
        rows = _dump_table(conn, "chat_messages", "character_name=?", (character_name,))
        if rows:
            db_dump["chat_messages"] = rows
    if include_stories:
        rows = _dump_table(conn, "stories", "character_name=?", (character_name,))
        if rows:
            db_dump["stories"] = rows

    # Relationships: outgoing edges only (from_char=X). Incoming edges belong
    # to the partner character; importing them on a fresh system would create
    # dangling references.
    rel_rows = _dump_table(conn, "relationships", "from_char=?", (character_name,))
    if rel_rows:
        db_dump["relationships"] = rel_rows

    # Filesystem slice
    char_dir = get_character_dir(character_name)
    file_entries: List[str] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if char_dir.exists():
            for fp in sorted(char_dir.rglob("*")):
                if not fp.is_file():
                    continue
                rel = fp.relative_to(char_dir).as_posix()
                if Path(rel).name in _FILE_EXCLUDE_NAMES:
                    continue
                # Apply scope flags also to FS — chats/stories were never in FS
                # in the new architecture, but legacy dirs may still have them.
                top = rel.split("/", 1)[0]
                if not include_chats and top == "chats":
                    continue
                if not include_stories and top == "stories":
                    continue
                zf.write(fp, f"files/{rel}")
                file_entries.append(rel)

        # DB dump
        for table, rows in db_dump.items():
            zf.writestr(
                f"db/{table}.json",
                json.dumps(rows, ensure_ascii=False, indent=2),
            )

        # Referenced world items (definitions + image files) — equipped/inventory/
        # outfit rows only hold item_id references; the items themselves live in
        # the world-level `items` table and would otherwise be missing on import.
        # Stored separately (db/items.json + item_files/) so the character import
        # can restore them WITHOUT overwriting existing world items.
        embedded_item_ids: List[str] = []
        try:
            from app.models.inventory import get_item
            from app.core.content_io import _strip_runtime_keys, _item_dir_for
            ref_ids: set = set()
            for r in db_dump.get("inventory_items", []):
                ref_ids.add((r.get("item_id") or "").strip())
            for r in db_dump.get("equipped_items", []):
                ref_ids.add((r.get("item_id") or "").strip())
            for r in db_dump.get("equipped_pieces", []):
                ref_ids.add((r.get("item_id") or "").strip())
            for r in db_dump.get("outfits_sets", []):
                try:
                    for iid in json.loads(r.get("pieces") or "[]"):
                        if isinstance(iid, str):
                            ref_ids.add(iid.strip())
                except Exception:
                    pass
            ref_ids.discard("")
            item_rows: List[Dict[str, Any]] = []
            for iid in sorted(ref_ids):
                it = get_item(iid)
                if not it or it.get("_shared"):
                    continue  # shared-library items ship with every world
                item_rows.append(_strip_runtime_keys(it))
                src = _item_dir_for(iid, shared=False)
                if src.exists():
                    for fp in sorted(src.rglob("*")):
                        if fp.is_file():
                            zf.write(fp, f"item_files/{iid}/{fp.relative_to(src).as_posix()}")
            if item_rows:
                zf.writestr("db/items.json",
                            json.dumps(item_rows, ensure_ascii=False, indent=2))
                embedded_item_ids = [it["id"] for it in item_rows]
        except Exception as e:
            logger.warning("export: embedding items for %s failed: %s", character_name, e)

        # Manifest last so it sees the final list of entries
        manifest = {
            "version": MANIFEST_VERSION,
            "character_name": character_name,
            "exported_at": utc_now_iso(),
            "options": {
                "include_chats": include_chats,
                "include_stories": include_stories,
            },
            "db_tables": sorted(db_dump.keys()),
            "embedded_items": sorted(embedded_item_ids),
            "files": sorted(file_entries),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _resolve_target_name_v2(zf: zipfile.ZipFile) -> Tuple[str, Dict[str, Any]]:
    """Read the v2 manifest and return (character_name, manifest)."""
    if "manifest.json" not in zf.namelist():
        raise ValueError("manifest.json missing — not a v2 export")
    manifest = json.loads(zf.read("manifest.json"))
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(
            f"unsupported manifest version: {manifest.get('version')!r} "
            f"(expected {MANIFEST_VERSION})"
        )
    name = (manifest.get("character_name") or "").strip()
    if not name:
        raise ValueError("character_name missing in manifest")
    if "/" in name or ".." in name or name.startswith("."):
        raise ValueError(f"invalid character_name in manifest: {name!r}")
    return name, manifest


def _wipe_db_for_character(conn, character_name: str) -> None:
    """Remove all DB rows owned by character_name across all known tables.

    Mirrors `delete_character` — keep both in sync if you add new tables.
    """
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for tbl in tables:
        cols = {c[1] for c in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        if "character_name" in cols:
            conn.execute(f"DELETE FROM {tbl} WHERE character_name=?", (character_name,))
    if _table_exists(conn, "characters"):
        conn.execute("DELETE FROM characters WHERE name=?", (character_name,))
    if _table_exists(conn, "relationships"):
        conn.execute(
            "DELETE FROM relationships WHERE from_char=? OR to_char=?",
            (character_name, character_name),
        )


def _restore_table(conn, table: str, rows: List[Dict[str, Any]]) -> int:
    """INSERT OR REPLACE rows. Silently drops columns that don't exist in
    the local schema (forward-compat for slightly older DBs)."""
    if not rows or not _table_exists(conn, table):
        return 0
    local_cols = set(_column_names(conn, table))
    inserted = 0
    for row in rows:
        usable = {k: v for k, v in row.items() if k in local_cols}
        if not usable:
            continue
        cols = list(usable.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
                tuple(usable[c] for c in cols),
            )
            inserted += 1
        except Exception as e:
            logger.warning("import: skip row in %s: %s", table, e)
    return inserted


# Fresh-start ("neu zugezogen"): welt-gebundene Historie verwerfen, Identität
# (Profil, Outfits, Items, Secrets, Beziehungen, Wissen, Tagesablauf) behalten.
# Siehe development_instructions/plan-character-import-fresh-start.md.
_FRESH_SKIP_TABLES = {
    "memories", "summaries", "diary_entries", "mood_history",
    "state_history", "evolution_history", "chat_messages", "stories",
    "scheduler_jobs", "assignments",
}


def import_character_from_zip(
    content: bytes,
    *,
    overwrite: bool = False,
    mode: str = "full",
    intro_text: str = "",
) -> Dict[str, Any]:
    """Import a v2 character ZIP. Returns a stats dict.

    mode:
      - "full": restore everything (re-import into the same/compatible world).
      - "fresh": keep identity (profile, outfits, inventory, secrets,
        relationships, knowledge, daily schedule), DROP world-bound history
        (memories/summaries/diary/mood/state/evolution/chats/…) and seed one
        intro memory from ``intro_text``. Dangling references (to characters not
        in this world) are filtered read-side at prompt build time.

    Raises ValueError on bad input, FileExistsError on existing character
    without overwrite=True.
    """
    fresh = (mode or "full").strip().lower() == "fresh"
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    character_name, manifest = _resolve_target_name_v2(zf)

    char_dir = get_character_dir(character_name)
    conn = get_connection()
    db_row_exists = bool(_table_exists(conn, "characters") and conn.execute(
        "SELECT 1 FROM characters WHERE name=?", (character_name,)
    ).fetchone())

    already_exists = char_dir.exists() or db_row_exists
    if already_exists and not overwrite:
        raise FileExistsError(
            f"Character '{character_name}' already exists "
            f"(use overwrite=true to replace)"
        )

    # Wipe existing state on overwrite — both DB and FS.
    if already_exists and overwrite:
        with transaction() as t_conn:
            _wipe_db_for_character(t_conn, character_name)
        if char_dir.exists():
            import shutil
            shutil.rmtree(char_dir)

    # Restore filesystem
    char_dir.mkdir(parents=True, exist_ok=True)
    file_count = 0
    for member in zf.namelist():
        if not member.startswith("files/"):
            continue
        rel = member[len("files/"):]
        safe_rel = _safe_relpath(rel)
        if not safe_rel:
            continue
        target = char_dir / safe_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(member))
        file_count += 1

    # Restore DB — `characters` first so FK-like consumers see it.
    db_stats: Dict[str, int] = {}
    db_tables: List[str] = list(manifest.get("db_tables") or [])

    def _restore_named(table: str) -> None:
        path = f"db/{table}.json"
        if path not in zf.namelist():
            return
        try:
            rows = json.loads(zf.read(path))
        except json.JSONDecodeError as e:
            logger.warning("import: %s.json invalid JSON: %s", table, e)
            return
        if not isinstance(rows, list):
            return
        with transaction() as t_conn:
            db_stats[table] = _restore_table(t_conn, table, rows)

    if "characters" in db_tables:
        _restore_named("characters")
    for table in db_tables:
        if table == "characters":
            continue
        if fresh and table in _FRESH_SKIP_TABLES:
            db_stats[table] = 0  # bewusst verworfen (fresh start)
            continue
        _restore_named(table)

    # Embedded world items: restore ONLY those missing in the target world —
    # never overwrite existing items (a character import must not mutate the
    # world's item library). `items` is intentionally NOT in db_tables.
    if "db/items.json" in zf.namelist():
        try:
            item_rows = json.loads(zf.read("db/items.json"))
        except Exception as e:
            logger.warning("import: items.json invalid JSON: %s", e)
            item_rows = []
        if isinstance(item_rows, list) and item_rows:
            from app.core.content_io import _existing_item_ids, _item_dir_for
            from app.models.inventory import _save_items
            existing = _existing_item_ids()
            # items.json holds the flattened get_item() shape (meta spread to
            # top level, pieces -> outfit_piece, no updated_at). _save_items is
            # the inverse writer that rebuilds the meta/pieces/slots columns and
            # stamps created_at/updated_at — the generic _restore_table would
            # drop those columns and fail the updated_at NOT NULL constraint.
            # Keep original ids so outfit/inventory references stay valid.
            new_items = [
                it for it in item_rows
                if (it.get("id") or "").strip()
                and (it.get("id") or "").strip() not in existing
            ]
            if new_items:
                _save_items(new_items)
            new_ids: List[str] = [(it.get("id") or "").strip() for it in new_items]
            for iid in new_ids:
                dest = _item_dir_for(iid, shared=False)
                prefix = f"item_files/{iid}/"
                for member in zf.namelist():
                    if not member.startswith(prefix):
                        continue
                    safe = _safe_relpath(member[len(prefix):])
                    if not safe:
                        continue
                    fp = dest / safe
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(zf.read(member))
            if new_ids:
                db_stats["items"] = len(new_ids)
            logger.info("Import: %s — %d new world item(s) restored", character_name, len(new_ids))

    zf.close()

    # Fresh start: seed one intro memory (identity kept, world history dropped).
    if fresh and (intro_text or "").strip():
        try:
            from app.models.memory import add_memory
            add_memory(
                character_name,
                (intro_text or "").strip(),
                memory_type="semantic",
                importance=4,
                tags=["intro", "fresh_start"],
            )
            db_stats["intro_memory"] = 1
        except Exception as e:
            logger.warning("Fresh import: intro memory seed failed for %s: %s", character_name, e)

    logger.info(
        "Import: %s — %d files, db: %s (mode=%s)",
        character_name, file_count, db_stats, "fresh" if fresh else "full",
    )
    return {
        "status": "success",
        "character": character_name,
        "mode": "fresh" if fresh else "full",
        "files_imported": file_count,
        "db_rows_imported": db_stats,
        "overwritten": already_exists and overwrite,
        "manifest": {
            "version": manifest.get("version"),
            "exported_at": manifest.get("exported_at"),
            "options": manifest.get("options", {}),
        },
    }
