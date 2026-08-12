"""Zentrale SQLite-DB-Zugriffsschicht fuer die Welt-Daten.

Eine DB pro Welt: `{storage_dir}/world.db`
WAL-Mode, JSON1-Extension, Foreign Keys aktiviert.

Alle Welt-Daten (Runtime + Content) liegen hier drin. Ausnahmen:
- Shared-Templates bleiben JSON unter `shared/`
- Image-Dateien + ihre Sidecar-JSONs bleiben auf Disk (Debugging)
- Task-Queue hat eigene `task_queue.db` (Legacy, bleibt getrennt)
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

from app.core.log import get_logger
from app.core.paths import get_storage_dir

logger = get_logger("db")

_connections: dict = {}
_lock = threading.Lock()


def get_db_path() -> Path:
    return get_storage_dir() / "world.db"


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")


def get_connection() -> sqlite3.Connection:
    """Thread-lokale Connection (SQLite benoetigt pro Thread eine eigene)."""
    tid = threading.get_ident()
    conn = _connections.get(tid)
    if conn is None:
        with _lock:
            conn = _connections.get(tid)
            if conn is None:
                db_path = get_db_path()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
                _configure(conn)
                _connections[tid] = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Kontextmanager fuer atomare Writes."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise




def init_schema() -> None:
    """Fuehrt alle Schema-Create-Statements aus (idempotent)."""
    import sqlite3
    from app.core.world_db_schema import (
        ALTER_MIGRATIONS, POST_MIGRATION_STATEMENTS,
        SCHEMA_STATEMENTS, SCHEMA_VERSION,
    )

    conn = get_connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    current = conn.execute(
        "SELECT value FROM schema_meta WHERE key='version'"
    ).fetchone()
    current_version = int(current["value"]) if current else 0

    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)

    for table, column, typedef in ALTER_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
        except sqlite3.OperationalError:
            pass

    # Indizes auf migrierte Spalten erst nach ALTERs anlegen.
    for stmt in POST_MIGRATION_STATEMENTS:
        conn.execute(stmt)

    # One-shot Daten-Cleanup: Items mit rarity="generic" auf "common"
    # migrieren (das alte "Generic = einfaerbbar"-Feature wurde entfernt).
    # Idempotent: laeuft nur solange noch generic-Items existieren.
    try:
        import json as _json
        rows = conn.execute("SELECT id, meta FROM items").fetchall()
        migrated = 0
        for iid, meta_raw in rows:
            try:
                meta = _json.loads(meta_raw or "{}")
            except Exception:
                continue
            if (meta.get("rarity") or "").strip().lower() == "generic":
                meta["rarity"] = "common"
                conn.execute("UPDATE items SET meta=? WHERE id=?",
                             (_json.dumps(meta, ensure_ascii=False), iid))
                migrated += 1
        if migrated:
            logger.info("items rarity-Migration: %d 'generic' -> 'common'",
                        migrated)
    except Exception as e:
        logger.warning("items rarity-Migration fehlgeschlagen: %s", e)

    # One-shot Daten-Cleanup: Lebensdauer-Feature (auto_expire_minutes/TTL)
    # wurde entfernt. Ueberbleibsel ``expires_at`` aus inventory_items.meta
    # rauspulen, sonst bleibt es ewig als toter String drin. Idempotent —
    # via schema_meta-Flag gegated, laeuft genau einmal pro Welt.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='inventory_expires_at_purged'"
    ).fetchone()
    if not flag:
        try:
            import json as _json
            rows = conn.execute(
                "SELECT character_name, item_id, meta FROM inventory_items"
            ).fetchall()
            purged = 0
            for char_name, item_id, meta_raw in rows:
                try:
                    meta = _json.loads(meta_raw or "{}")
                except Exception:
                    continue
                if "expires_at" in meta:
                    meta.pop("expires_at", None)
                    conn.execute(
                        "UPDATE inventory_items SET meta=? "
                        "WHERE character_name=? AND item_id=?",
                        (_json.dumps(meta, ensure_ascii=False), char_name, item_id),
                    )
                    purged += 1
            if purged:
                logger.info("inventory_items expires_at-Cleanup: %d Eintraege bereinigt",
                            purged)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('inventory_expires_at_purged', '1')"
            )
        except Exception as e:
            logger.warning("inventory_items expires_at-Cleanup fehlgeschlagen: %s", e)

    # One-shot Migration: summaries.UNIQUE-Constraint von 3 auf 4 Spalten
    # umstellen (zusaetzlich `partner`). SQLite kann Constraints nicht inline
    # aendern — Tabelle muss rebuilt werden. Idempotent via schema_meta-Flag.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='summaries_partner_unique_v2'"
    ).fetchone()
    if not flag:
        try:
            # Pruefen ob die alte UNIQUE noch aktiv ist: SQLite legt sie als
            # sqlite_autoindex_summaries_* an. Wenn der hoechste Index nur 3
            # Spalten hat → migrieren.
            old_idx = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='summaries' "
                "AND name LIKE 'sqlite_autoindex_summaries_%'"
            ).fetchall()
            needs_rebuild = False
            for (idx_name,) in old_idx:
                cols = conn.execute(
                    f"PRAGMA index_info({idx_name})"
                ).fetchall()
                if len(cols) == 3:
                    needs_rebuild = True
                    break
            if needs_rebuild:
                logger.info("summaries: UNIQUE-Constraint wird auf 4 Spalten "
                            "umgebaut (partner ergaenzt)")
                conn.execute("ALTER TABLE summaries RENAME TO summaries_old_v1")
                conn.execute("""
                    CREATE TABLE summaries (
                        id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        character_name TEXT NOT NULL,
                        kind           TEXT NOT NULL,
                        date_key       TEXT NOT NULL,
                        partner        TEXT NOT NULL DEFAULT '',
                        content        TEXT NOT NULL,
                        meta           TEXT DEFAULT '{}',
                        UNIQUE(character_name, kind, date_key, partner),
                        FOREIGN KEY(character_name) REFERENCES characters(name)
                            ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    INSERT INTO summaries
                    (id, character_name, kind, date_key, partner, content, meta)
                    SELECT id, character_name, kind, date_key,
                           COALESCE(partner, ''), content, COALESCE(meta, '{}')
                    FROM summaries_old_v1
                """)
                conn.execute("DROP TABLE summaries_old_v1")
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('summaries_partner_unique_v2', '1')"
            )
        except Exception as e:
            logger.warning("summaries partner-Migration fehlgeschlagen: %s", e)

    # One-shot migration: rooms.PRIMARY KEY from (id) to (location_id, id).
    # Room ids are unique per LOCATION (plan-grundflaeche.md § 3) — the global
    # key let a save of location A steal the physical row of location B, which
    # is exactly what ONE reserved ground-room id in every location runs into.
    # SQLite cannot change a primary key in place, so the table is rebuilt.
    # Runs inside init_schema and therefore BEFORE migrate_ground_rooms_once,
    # which only writes ground rooms in the lifespan. Idempotent via
    # schema_meta flag AND via the pk shape itself.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='rooms_composite_pk_v1'"
    ).fetchone()
    if not flag:
        try:
            from app.core.world_db_schema import (
                ROOMS_COLUMNS, ROOMS_TABLE_SQL, rooms_rebuild_needed,
            )
            cols = ", ".join(ROOMS_COLUMNS)
            if rooms_rebuild_needed(
                    conn.execute("PRAGMA table_info(rooms)").fetchall()):
                logger.info("rooms: PRIMARY KEY wird auf (location_id, id) "
                            "umgebaut")
                conn.execute("ALTER TABLE rooms RENAME TO rooms_old_v1")
                conn.execute(ROOMS_TABLE_SQL)
                conn.execute(f"INSERT INTO rooms ({cols}) "
                             f"SELECT {cols} FROM rooms_old_v1")
                conn.execute("DROP TABLE rooms_old_v1")

            # Heal what the old key had already destroyed. The rooms table is
            # a PROJECTION of locations.meta (that blob is what _load_world_data
            # reads whenever it carries an id), so re-project it: every room a
            # location's blob knows gets its row back. Rows of locations
            # without such a blob are left untouched — those are the only ones
            # for which the table itself is the truth.
            import json as _json
            healed = 0
            for loc_id, meta_raw in conn.execute(
                    "SELECT id, meta FROM locations").fetchall():
                try:
                    meta = _json.loads(meta_raw or "{}")
                except Exception:
                    continue
                if not isinstance(meta, dict) or "id" not in meta:
                    continue
                for room in (meta.get("rooms") or []):
                    if not isinstance(room, dict) or not room.get("id"):
                        continue
                    cur = conn.execute(
                        "SELECT 1 FROM rooms WHERE location_id=? AND id=?",
                        (loc_id, room["id"])).fetchone()
                    if cur:
                        continue
                    conn.execute(
                        f"INSERT INTO rooms ({cols}) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (room["id"], loc_id, room.get("name", "") or "",
                         room.get("outfit_type", "") or "",
                         room.get("decency", "") or "",
                         room.get("style_hint", "") or "",
                         1 if room.get("swim_allowed") else 0,
                         room.get("activity_hint", "") or "",
                         _json.dumps(room, ensure_ascii=False)))
                    healed += 1
            if healed:
                logger.info("rooms: %d Raum-Zeile(n) aus locations.meta "
                            "wiederhergestellt", healed)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('rooms_composite_pk_v1', '1')"
            )
        except Exception as e:
            logger.warning("rooms composite-PK-Migration fehlgeschlagen: %s", e)

    # One-shot Backfill: known_locations-Feld auf jedem Character verpflichtend
    # machen. Frueher bedeutete "Feld fehlt" → unrestricted (Legacy-Bypass);
    # der Bypass ist raus und Read-Pfade liefern jetzt immer eine Liste.
    # Damit Bestands-Charaktere nach dem Bypass-Removal nicht ganz festsitzen,
    # seeden wir die Liste mit der aktuellen Location (falls real) — von dort
    # erweitert sich die Liste durch Auto-Discovery beim Betreten und durch
    # Discover-Regeln. Idempotent via schema_meta-Flag.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='known_locations_backfill_v1'"
    ).fetchone()
    if not flag:
        try:
            import json as _json
            char_rows = conn.execute(
                "SELECT name, config_json FROM characters"
            ).fetchall()
            real_loc_ids = {
                r[0] for r in conn.execute("SELECT id FROM locations").fetchall()
            }
            state_locs = {
                r[0]: r[1] for r in conn.execute(
                    "SELECT character_name, current_location FROM character_state"
                ).fetchall()
            }
            backfilled = 0
            for char_name, conf_raw in char_rows:
                try:
                    conf = _json.loads(conf_raw or "{}")
                except Exception:
                    continue
                if "known_locations" in conf and isinstance(conf["known_locations"], list):
                    continue
                seed: List[str] = []
                cur_loc = (state_locs.get(char_name) or "").strip()
                if cur_loc and cur_loc in real_loc_ids:
                    seed.append(cur_loc)
                conf["known_locations"] = seed
                conn.execute(
                    "UPDATE characters SET config_json=?, updated_at=datetime('now') "
                    "WHERE name=?",
                    (_json.dumps(conf, ensure_ascii=False), char_name),
                )
                backfilled += 1
            if backfilled:
                logger.info("known_locations Backfill: %d Characters geseedet "
                            "(je current_location)", backfilled)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('known_locations_backfill_v1', '1')"
            )
        except Exception as e:
            logger.warning("known_locations Backfill fehlgeschlagen: %s", e)

    # One-shot Migration: outfit_locked + runtime_outfit_skip → outfit_intent.
    # Plan: development_instructions/plan-outfit-system-rethink.md §3
    # Vereint die beiden alten Felder in einen Intent-Container in
    # character_state.meta. Alte Felder bleiben fuers Erste stehen (werden
    # in Schritt 8 Cleanup entfernt) — die Reader/Writer ignorieren sie
    # bereits. Idempotent via schema_meta-Flag.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='outfit_intent_migrated_v1'"
    ).fetchone()
    if not flag:
        try:
            import json as _json
            char_rows = conn.execute(
                "SELECT name, profile_json FROM characters"
            ).fetchall()
            state_rows = {
                r[0]: r[1] for r in conn.execute(
                    "SELECT character_name, meta FROM character_state"
                ).fetchall()
            }
            migrated = 0
            for char_name, prof_raw in char_rows:
                try:
                    prof = _json.loads(prof_raw or "{}")
                except Exception:
                    prof = {}
                old_locked = bool(prof.get("outfit_locked", False))
                state_meta_raw = state_rows.get(char_name) or "{}"
                try:
                    state_meta = _json.loads(state_meta_raw or "{}")
                except Exception:
                    state_meta = {}
                old_forbidden = list(state_meta.get("runtime_outfit_skip") or [])
                existing_intent = state_meta.get("outfit_intent")
                if isinstance(existing_intent, dict) and (
                    existing_intent.get("locked") or
                    existing_intent.get("forbidden_slots") or
                    existing_intent.get("forced_pieces")
                ):
                    # Schon migriert oder bereits aktiv genutzt — nicht ueberschreiben
                    continue
                if not old_locked and not old_forbidden:
                    continue
                intent = {
                    "forced_pieces": {},
                    "forbidden_slots": sorted(set(old_forbidden)),
                    "target_outfit_type": None,
                    "locked": old_locked,
                }
                state_meta["outfit_intent"] = intent
                # state-Row muss existieren — UPSERT
                conn.execute(
                    "INSERT INTO character_state (character_name, meta) "
                    "VALUES (?, ?) "
                    "ON CONFLICT(character_name) DO UPDATE SET meta=excluded.meta",
                    (char_name, _json.dumps(state_meta, ensure_ascii=False)),
                )
                migrated += 1
            if migrated:
                logger.info(
                    "outfit_intent-Migration: %d Characters migriert "
                    "(outfit_locked/runtime_outfit_skip → outfit_intent)",
                    migrated,
                )
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('outfit_intent_migrated_v1', '1')"
            )
        except Exception as e:
            logger.warning("outfit_intent-Migration fehlgeschlagen: %s", e)

    # One-shot migration: pose free text → pose catalog fields
    # (plan-pose-katalog.md). The old pose_intent column held whatever the LLM
    # wrote; pose_key/pose_flavor replace it. A clean cut, no conversion: the
    # pose is volatile — every location/room change clears it anyway.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='pose_catalog_fields_v1'"
    ).fetchone()
    if not flag:
        try:
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(character_state)").fetchall()}
            if "pose_intent" in cols:
                conn.execute(
                    "ALTER TABLE character_state DROP COLUMN pose_intent")
                conn.execute(
                    "UPDATE character_state SET pose_key='', pose_flavor=''")
                logger.info("pose catalog fields: pose_intent column dropped, "
                            "stale poses cleared")
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('pose_catalog_fields_v1', '1')"
            )
        except Exception as e:
            logger.warning("pose catalog field migration failed: %s", e)

    # One-shot Migration: Legacy-Keys aus character_state.meta entfernen.
    # Plan §8 (Schritt 8 Cleanup, May 2026):
    #   - runtime_outfit_skip → outfit_intent.forbidden_slots (Schritt 2)
    #   - equipped_pieces_meta → Items sind eindeutig (Schritt 3)
    # Beide Keys waren parallel zur neuen Welt noch im Profile-Lesen drin —
    # jetzt aktiv aus state.meta entfernen.
    flag = conn.execute(
        "SELECT value FROM schema_meta WHERE key='state_meta_legacy_purged_v1'"
    ).fetchone()
    if not flag:
        try:
            import json as _json
            rows = conn.execute(
                "SELECT character_name, meta FROM character_state"
            ).fetchall()
            purged = 0
            for char_name, meta_raw in rows:
                try:
                    meta = _json.loads(meta_raw or "{}")
                except Exception:
                    continue
                if not isinstance(meta, dict):
                    continue
                changed = False
                for key in ("runtime_outfit_skip", "equipped_pieces_meta"):
                    if key in meta:
                        meta.pop(key, None)
                        changed = True
                if changed:
                    conn.execute(
                        "UPDATE character_state SET meta=? WHERE character_name=?",
                        (_json.dumps(meta, ensure_ascii=False), char_name),
                    )
                    purged += 1
            if purged:
                logger.info("state.meta Legacy-Purge: %d Characters bereinigt "
                            "(runtime_outfit_skip + equipped_pieces_meta)",
                            purged)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES "
                "('state_meta_legacy_purged_v1', '1')"
            )
        except Exception as e:
            logger.warning("state.meta Legacy-Purge fehlgeschlagen: %s", e)

    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),)
    )
    conn.commit()
    if current_version != SCHEMA_VERSION:
        logger.info(
            "World-DB Schema initialisiert: version %d (war %d)",
            SCHEMA_VERSION, current_version
        )

    # Default-Rules seeden — Sleep + Wake. Idempotent: nur fehlende werden
    # angelegt (Match by id), User-Aenderungen bleiben. Frueher waren
    # diese Pfade hardcoded im AgentLoop / hourly_tick — durch das Seed
    # sind frische Welten direkt funktional, bestehende Welten bekommen
    # die Defaults beim naechsten Restart nachgereicht.
    try:
        from app.models.rules import ensure_default_rules
        ensure_default_rules()
    except Exception as e:
        logger.warning("Default-Rules seeding fehlgeschlagen: %s", e)
