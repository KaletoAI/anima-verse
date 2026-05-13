#!/usr/bin/env python3
"""Migration: room/location outfit_type -> decency + style_hint + swim_allowed.

Plan: development_instructions/plan-outfit-system-rethink.md (Schritt 1).

Mapping (Plan §10.1):
    casual / business / work / formal / sport         -> decency=public
    beach / pool                                      -> decency=public, swim=1
    home / bed / intimate                             -> decency=private
    bath                                              -> decency=private, swim=1
    nude_ok-Raeume (Sauna, FKK) -> manuell, kein Auto-Mapping aus alten Types

Idempotent: Eintraege mit bereits gesetztem decency werden uebersprungen.
Aktualisiert sowohl die einzelnen Spalten als auch den meta-JSON-Blob
(letzterer ist der "Quell"-Speicher, Reader bevorzugt ihn).
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORLDS_DIR = ROOT / "worlds"

# (outfit_type lowercase) -> (decency, style_hint, swim_allowed)
MAPPING = {
    "casual":    ("public",  "casual",   0),
    "business":  ("public",  "business", 0),
    "work":      ("public",  "business", 0),
    "formal":    ("public",  "elegant",  0),
    "sport":     ("public",  "sporty",   0),
    "beach":     ("public",  "beach",    1),
    "pool":      ("public",  "beach",    1),
    "home":      ("private", "casual",   0),
    "bed":       ("private", "",         0),
    "bath":      ("private", "",         1),
    "intimate":  ("private", "",         0),
}


def derive(outfit_type: str) -> tuple[str, str, int]:
    """outfit_type -> (decency, style_hint, swim_allowed).

    Unbekannte Types: decency=public (defensive), style_hint = der alte
    Type-Name (LLM-Hinweis), swim_allowed=0.
    """
    key = (outfit_type or "").strip().lower()
    if key in MAPPING:
        return MAPPING[key]
    if key:
        return ("public", key, 0)
    return ("", "", 0)


def ensure_columns(conn: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN fuer alle benoetigten Spalten — idempotent."""
    additions = [
        ("locations", "decency",       "TEXT DEFAULT ''"),
        ("locations", "style_hint",    "TEXT DEFAULT ''"),
        ("locations", "swim_allowed",  "INTEGER NOT NULL DEFAULT 0"),
        ("locations", "activity_hint", "TEXT DEFAULT ''"),
        ("rooms",     "decency",       "TEXT DEFAULT ''"),
        ("rooms",     "style_hint",    "TEXT DEFAULT ''"),
        ("rooms",     "swim_allowed",  "INTEGER NOT NULL DEFAULT 0"),
        ("rooms",     "activity_hint", "TEXT DEFAULT ''"),
    ]
    for table, column, typedef in additions:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
        except sqlite3.OperationalError:
            pass


def _migrate_room_dict(room: dict, summary: dict) -> bool:
    """Mutiert ein room-Dict in-place. Returns True wenn geaendert.

    Setzt fuer Rooms ohne outfit_type die Default-Felder, damit der
    Reader nirgends None liefert. Fuer Rooms mit outfit_type wird das
    Mapping aus MAPPING angewandt.
    """
    if not isinstance(room, dict):
        return False
    if room.get("decency"):
        return False  # bereits migriert
    changed = False
    outfit_type = (room.get("outfit_type") or "").strip()
    if outfit_type:
        new_decency, style_hint, swim = derive(outfit_type)
        if outfit_type.lower() not in MAPPING:
            summary["unknown_type"].append((room.get("id"), outfit_type))
        room["decency"] = new_decency
        room["style_hint"] = style_hint
        room["swim_allowed"] = bool(swim)
        changed = True
    # Defaults fuer alle vier Felder setzen (auch bei outfit_type='')
    for key, default in (("decency", ""), ("style_hint", ""),
                         ("swim_allowed", False), ("activity_hint", "")):
        if key not in room:
            room[key] = default
            changed = True
    return changed


def migrate_locations(conn: sqlite3.Connection) -> dict:
    summary = {"checked": 0, "migrated": 0, "skipped_already": 0,
               "skipped_empty_type": 0, "unknown_type": [],
               "embedded_rooms_migrated": 0}
    rows = conn.execute(
        "SELECT id, outfit_type, decency, meta FROM locations"
    ).fetchall()
    for lid, outfit_type, decency, meta_raw in rows:
        summary["checked"] += 1
        # meta-Blob in jedem Fall parsen — auch wenn der Location selbst
        # schon migriert wurde, koennen die eingebetteten rooms noch
        # unmigriert sein.
        try:
            meta = json.loads(meta_raw or "{}")
        except Exception:
            meta = {}
        meta_changed = False
        loc_migrated = False

        if decency:
            summary["skipped_already"] += 1
            new_decency = decency
            style_hint = meta.get("style_hint", "") if isinstance(meta, dict) else ""
            swim = 1 if (isinstance(meta, dict) and meta.get("swim_allowed")) else 0
        elif not (outfit_type or "").strip():
            summary["skipped_empty_type"] += 1
            new_decency = ""
            style_hint = ""
            swim = 0
        else:
            new_decency, style_hint, swim = derive(outfit_type)
            if (outfit_type or "").strip().lower() not in MAPPING:
                summary["unknown_type"].append((lid, outfit_type))
            if isinstance(meta, dict):
                meta["decency"] = new_decency
                meta["style_hint"] = style_hint
                meta["swim_allowed"] = bool(swim)
                meta.setdefault("activity_hint", "")
                meta_changed = True
            loc_migrated = True
            summary["migrated"] += 1

        # Eingebettete Rooms im meta-Blob ebenfalls migrieren.
        if isinstance(meta, dict) and isinstance(meta.get("rooms"), list):
            for room in meta["rooms"]:
                if _migrate_room_dict(room, summary):
                    summary["embedded_rooms_migrated"] += 1
                    meta_changed = True

        if loc_migrated or meta_changed:
            conn.execute(
                "UPDATE locations SET decency=?, style_hint=?, swim_allowed=?, "
                "meta=? WHERE id=?",
                (new_decency, style_hint, swim,
                 json.dumps(meta, ensure_ascii=False), lid),
            )
    return summary


def migrate_rooms(conn: sqlite3.Connection) -> dict:
    summary = {"checked": 0, "migrated": 0, "skipped_already": 0,
               "skipped_empty_type": 0, "unknown_type": []}
    rows = conn.execute(
        "SELECT id, outfit_type, decency, meta FROM rooms"
    ).fetchall()
    for rid, outfit_type, decency, meta_raw in rows:
        summary["checked"] += 1
        if decency:
            summary["skipped_already"] += 1
            continue
        if not (outfit_type or "").strip():
            summary["skipped_empty_type"] += 1
            continue
        new_decency, style_hint, swim = derive(outfit_type)
        if (outfit_type or "").strip().lower() not in MAPPING:
            summary["unknown_type"].append((rid, outfit_type))
        try:
            meta = json.loads(meta_raw or "{}")
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            meta["decency"] = new_decency
            meta["style_hint"] = style_hint
            meta["swim_allowed"] = bool(swim)
            meta.setdefault("activity_hint", "")
        conn.execute(
            "UPDATE rooms SET decency=?, style_hint=?, swim_allowed=?, "
            "meta=? WHERE id=?",
            (new_decency, style_hint, swim,
             json.dumps(meta, ensure_ascii=False), rid),
        )
        summary["migrated"] += 1
    return summary


def migrate_world(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_columns(conn)
        loc_summary = migrate_locations(conn)
        room_summary = migrate_rooms(conn)
        conn.commit()
        return {"locations": loc_summary, "rooms": room_summary}
    finally:
        conn.close()


def main() -> int:
    if not WORLDS_DIR.exists():
        print(f"worlds/ nicht gefunden: {WORLDS_DIR}", file=sys.stderr)
        return 1
    worlds = sorted(p for p in WORLDS_DIR.iterdir()
                    if p.is_dir() and (p / "world.db").exists())
    if not worlds:
        print("Keine world.db gefunden.")
        return 0
    print(f"Migration auf {len(worlds)} Welten: "
          f"{[w.name for w in worlds]}")
    print()
    total_migrated_loc = 0
    total_migrated_room = 0
    for world_dir in worlds:
        db = world_dir / "world.db"
        print(f"=== {world_dir.name} ({db}) ===")
        res = migrate_world(db)
        loc = res["locations"]
        room = res["rooms"]
        print(f"  Locations: {loc['checked']} geprueft, "
              f"{loc['migrated']} migriert, "
              f"{loc['skipped_already']} schon migriert, "
              f"{loc['skipped_empty_type']} ohne outfit_type")
        if loc["unknown_type"]:
            print(f"    Unbekannte outfit_types: {loc['unknown_type']}")
        print(f"  Rooms:     {room['checked']} geprueft, "
              f"{room['migrated']} migriert, "
              f"{room['skipped_already']} schon migriert, "
              f"{room['skipped_empty_type']} ohne outfit_type")
        if room["unknown_type"]:
            print(f"    Unbekannte outfit_types: {room['unknown_type']}")
        total_migrated_loc += loc["migrated"]
        total_migrated_room += room["migrated"]
        print()
    print(f"Gesamt: {total_migrated_loc} Locations + "
          f"{total_migrated_room} Rooms migriert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
