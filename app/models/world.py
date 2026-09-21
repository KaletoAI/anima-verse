"""Welt-Daten: Orte, Raeume und Aktivitaeten (User-Level)

Orte und ihre Raeume werden pro User gespeichert in:
  storage/users/{username}/world.json

Jeder Ort hat eine persistente ID (8-Zeichen Hex), damit Umbenennungen
keine Referenzen in Character-Profilen, Schedulern etc. zerstoeren.

Jeder Ort hat Raeume (rooms) mit Name, Beschreibung und Aktivitaeten.
Aktivitaeten sind als Objekte {name, description} in den Raeumen eingebettet.
Galerie-Bilder werden Raeumen zugeordnet (statt direkt Aktivitaeten).
"""
import json
import math
import random as _random
import re
import threading
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("world")

from app.core.paths import get_storage_dir
from app.core.timeutils import game_time, utc_now_iso
from app.core.view_prompts import building_view


def _get_world_file() -> Path:
    """Gibt den Pfad zur world.json zurueck."""
    sd = get_storage_dir()
    sd.mkdir(parents=True, exist_ok=True)
    return sd / "world.json"


def _migrate_room_image_prompts(data: Dict[str, Any]) -> bool:
    """Migriert Room image_prompt -> image_prompt_day (einmalig beim Laden).

    Returns True wenn Daten geaendert wurden.
    """
    changed = False
    for loc in data.get("locations", []):
        for room in loc.get("rooms", []):
            if "image_prompt" in room and "image_prompt_day" not in room:
                room["image_prompt_day"] = room.pop("image_prompt")
                changed = True
            if "image_prompt_night" not in room:
                room["image_prompt_night"] = ""
                changed = True
    return changed


# --- Read cache -----------------------------------------------------------
# WHY. ``get_location_by_id`` (90 call sites), ``list_locations`` (54) and
# ``resolve_location`` (36) each re-read and re-parse the WHOLE world; the
# travel ticker does it once per traveller every five seconds and a chat turn
# dozens of times. The world only changes when one of the three writers below
# runs, so the parse is cached and a write bumps a generation counter.
#
# WHAT IS HANDED OUT ARE COPIES. Half the callers mutate what they got back
# (load → change one location → save), so the cache stores each location's
# JSON TEXT and every read parses its own object. json.loads is C-fast, keeps
# no reference to cached state, and is measurably cheaper than a deepcopy of
# the same dict (scripts/smoke_world_cache.py prints both).
#
# The key is the DB path, so switching world/storage (``paths.init``) cannot
# serve the previous world's locations.
_world_cache_lock = threading.Lock()
_world_generation = 0
_world_cache: Dict[str, Any] = {"key": None, "gen": None,
                                "texts": None, "by_id": None}


def _bump_world_generation() -> None:
    """A location write happened — the cached parse is stale."""
    global _world_generation
    with _world_cache_lock:
        _world_generation += 1
        _world_cache["gen"] = None
        _world_cache["texts"] = None
        _world_cache["by_id"] = None


def _world_cache_key() -> str:
    try:
        from app.core.db import get_db_path
        return str(get_db_path())
    except Exception:
        return ""


def _cached_texts() -> Optional[List[str]]:
    """The active world's locations as JSON texts, or None when the cache is
    cold/stale. Never returns objects — the caller parses its own."""
    key = _world_cache_key()
    with _world_cache_lock:
        if (_world_cache["texts"] is not None
                and _world_cache["key"] == key
                and _world_cache["gen"] == _world_generation):
            return _world_cache["texts"]
    return None


def _fill_world_cache(locations: List[Dict[str, Any]], gen_at_read: int) -> None:
    """Store the parse — unless a write landed while we were reading it."""
    key = _world_cache_key()
    try:
        texts = [json.dumps(loc, ensure_ascii=False) for loc in locations]
    except (TypeError, ValueError):
        return   # something in there is not JSON — simply do not cache
    by_id: Dict[str, str] = {}
    for loc, text in zip(locations, texts):
        lid = loc.get("id") if isinstance(loc, dict) else None
        if lid and lid not in by_id:
            by_id[str(lid)] = text
    with _world_cache_lock:
        if _world_generation != gen_at_read:
            return
        _world_cache.update(key=key, gen=gen_at_read, texts=texts, by_id=by_id)


def _load_world_data() -> Dict[str, Any]:
    """The world data (locations plus their rooms) — cached, copies only.

    Same answer as a fresh read: every call returns freshly parsed dicts that
    the caller may mutate without touching the cache or another caller.
    """
    texts = _cached_texts()
    if texts is not None:
        try:
            return {"locations": [json.loads(t) for t in texts]}
        except (TypeError, ValueError):
            pass   # fall through to a fresh read
    gen_at_read = _world_generation
    data = _read_world_data_uncached()
    locations = data.get("locations", [])
    if isinstance(locations, list):
        _fill_world_cache(locations, gen_at_read)
    return data


def _read_world_data_uncached() -> Dict[str, Any]:
    """Loads the world data from the DB (locations plus their rooms).

    A location comes out of the ``meta`` blob as a complete dict whenever the
    blob holds one; otherwise it is reconstructed from the columns, and the
    rooms are read from the ``rooms`` table. Rooms of a blob-backed location
    are embedded in ``locations.meta.rooms``.

    Falls back to the legacy ``world.json`` when the DB is empty or unreadable.
    """
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, name, description, pos_x, pos_z, outfit_type, "
            "image_prompt_day, image_prompt_night, "
            "visible_when, accessible_when, background_images, meta, "
            "decency, style_hint, swim_allowed, activity_hint, yaw_deg "
            "FROM locations ORDER BY name ASC"
        ).fetchall()
        if rows:
            locations = []
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r[11] or "{}")
                except Exception:
                    pass
                if meta and "id" in meta:
                    # A complete location dict straight out of meta
                    loc = meta
                else:
                    # Reconstruct from columns
                    loc = {
                        "id": r[0],
                        "name": r[1] or "",
                        "description": r[2] or "",
                        "pos_x": r[3],
                        "pos_z": r[4],
                        "yaw_deg": float(r[16] or 0.0),
                        "outfit_type": r[5] or "",
                        "image_prompt_day": r[6] or "",
                        "image_prompt_night": r[7] or "",
                        "decency": r[12] or "",
                        "style_hint": r[13] or "",
                        "swim_allowed": bool(r[14]),
                        "activity_hint": r[15] or "",
                        "rooms": [],
                    }
                    try:
                        loc["visible_when"] = json.loads(r[8] or "[]")
                    except Exception:
                        loc["visible_when"] = []
                    try:
                        loc["accessible_when"] = json.loads(r[9] or "[]")
                    except Exception:
                        loc["accessible_when"] = []
                    try:
                        loc["background_images"] = json.loads(r[10] or "[]")
                    except Exception:
                        loc["background_images"] = []
                    loc.update(meta)

                    # Load rooms from rooms table
                    room_rows = conn.execute(
                        "SELECT id, name, outfit_type, meta, "
                        "decency, style_hint, swim_allowed, activity_hint "
                        "FROM rooms "
                        "WHERE location_id=? ORDER BY rowid ASC",
                        (r[0],),
                    ).fetchall()
                    rooms = []
                    for rr in room_rows:
                        rmeta = {}
                        try:
                            rmeta = json.loads(rr[3] or "{}")
                        except Exception:
                            pass
                        if rmeta and "id" in rmeta:
                            room_dict = rmeta
                        else:
                            room_dict = {
                                "id": rr[0],
                                "name": rr[1] or "",
                                "outfit_type": rr[2] or "",
                                "decency": rr[4] or "",
                                "style_hint": rr[5] or "",
                                "swim_allowed": bool(rr[6]),
                                "activity_hint": rr[7] or "",
                                "description": "",
                                "activities": [],
                                **rmeta,
                            }
                        # Column fallback: decency fields missing from the
                        # meta blob are pulled in from the columns (even when
                        # the column holds the default, so defaults stay
                        # consistent: '' instead of None, False instead of
                        # None).
                        for key, col_idx, cast in (
                            ("decency",       4, str),
                            ("style_hint",    5, str),
                            ("swim_allowed",  6, bool),
                            ("activity_hint", 7, str),
                        ):
                            if key not in room_dict:
                                val = rr[col_idx]
                                room_dict[key] = (bool(val) if cast is bool
                                                  else (val or ""))
                        rooms.append(room_dict)
                    loc["rooms"] = rooms
                # Column fallback: fields missing from the meta blob are
                # pulled in from the columns (even when the column holds the
                # default, so defaults stay consistent: '' instead of None,
                # False instead of None, 0.0 instead of None). yaw_deg is
                # part of this: the contract says every location dict carries
                # a float rotation, and the blob only gets the key once a
                # rotation was actually set.
                for key, col_idx, cast in (
                    ("decency",       12, str),
                    ("style_hint",    13, str),
                    ("swim_allowed",  14, bool),
                    ("activity_hint", 15, str),
                    ("yaw_deg",       16, float),
                ):
                    if key not in loc:
                        val = r[col_idx]
                        if cast is bool:
                            loc[key] = bool(val)
                        elif cast is float:
                            loc[key] = float(val or 0.0)
                        else:
                            loc[key] = val or ""
                locations.append(loc)
            data = {"locations": locations}
            _migrate_room_image_prompts(data)
            return data
    except Exception as e:
        logger.warning("_load_world_data DB error: %s", e)

    # Fallback: the legacy JSON file
    path = _get_world_file()
    if path.exists():
        try:
            with _world_file_lock:
                data = json.loads(path.read_text(encoding="utf-8"))
                if _migrate_room_image_prompts(data):
                    path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    logger.info("Room image_prompt -> image_prompt_day migrated")
            return data
        except Exception:
            pass
    return {"locations": []}


_world_file_lock = threading.Lock()

#: ONE process-wide lock for every write to the locations/rooms tables — and,
#: just as importantly, for the read-modify-write block around it: a caller
#: that loads the world, changes a location and stores it again holds this
#: from the load to the upsert. Re-entrant on purpose, because the upsert
#: acquires it again.
#:
#: WHY. Until 2026-09-21 every writer handed the WHOLE world snapshot to
#: ``_save_world_data``, which deleted every location the snapshot did not
#: mention, and nothing serialized the load against the save. Two threads that
#: had both read the world before either wrote therefore deleted each other's
#: fresh locations — an NPC dropping an item in a room could purge a place the
#: editor had just created, silently. Delete-by-absence is now opt-in
#: (:func:`replace_all_locations`); everything else upserts what it touched.
world_write_lock = threading.RLock()


def _write_location_rows(conn, locations: List[Dict[str, Any]],
                         now: str) -> None:
    """Upsert the given locations and their rooms into an OPEN transaction.

    Rooms that are MISSING from a location's ``rooms`` list are deleted —
    within that one location, because a location dict is the unit of editing
    (a room the editor removed arrives as a list that simply lacks it).
    Locations that are not in ``locations`` are never touched here: deleting a
    place is explicit (:func:`delete_location_row`, or the opt-in
    :func:`replace_all_locations`).
    """
    for loc in locations:
        lid = loc.get("id")
        if not lid:
            continue
        # No entry_room default is written here any more: the field is
        # optional (plan-grundflaeche.md § 6), and filling it in on
        # every save made "empty = arrive on the ground" unreachable.
        # A value pointing at a deleted room is answered by
        # get_entry_room_id, which reads it as "none declared".
        conn.execute("""
            INSERT INTO locations
                (id, name, description, pos_x, pos_z, yaw_deg, outfit_type,
                 image_prompt_day, image_prompt_night,
                 visible_when, accessible_when, background_images, meta,
                 decency, style_hint, swim_allowed, activity_hint,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                pos_x=excluded.pos_x,
                pos_z=excluded.pos_z,
                yaw_deg=excluded.yaw_deg,
                outfit_type=excluded.outfit_type,
                image_prompt_day=excluded.image_prompt_day,
                image_prompt_night=excluded.image_prompt_night,
                visible_when=excluded.visible_when,
                accessible_when=excluded.accessible_when,
                background_images=excluded.background_images,
                meta=excluded.meta,
                decency=excluded.decency,
                style_hint=excluded.style_hint,
                swim_allowed=excluded.swim_allowed,
                activity_hint=excluded.activity_hint,
                updated_at=excluded.updated_at
        """, (
            lid,
            loc.get("name", ""),
            loc.get("description", ""),
            loc.get("pos_x"),
            loc.get("pos_z"),
            float(loc.get("yaw_deg") or 0.0),
            loc.get("outfit_type", ""),
            loc.get("image_prompt_day", ""),
            loc.get("image_prompt_night", ""),
            json.dumps(loc.get("visible_when", []), ensure_ascii=False),
            json.dumps(loc.get("accessible_when", []), ensure_ascii=False),
            json.dumps(loc.get("background_images", []), ensure_ascii=False),
            json.dumps(loc, ensure_ascii=False),
            loc.get("decency", "") or "",
            loc.get("style_hint", "") or "",
            1 if loc.get("swim_allowed") else 0,
            loc.get("activity_hint", "") or "",
            now,
            now,
        ))

        # Upsert rooms
        rooms = loc.get("rooms", [])
        existing_room_ids = {r[0] for r in conn.execute(
            "SELECT id FROM rooms WHERE location_id=?", (lid,)
        ).fetchall()}
        new_room_ids = {r.get("id") for r in rooms if r.get("id")}
        for rid in existing_room_ids - new_room_ids:
            # Room ids are unique per LOCATION — without the second
            # condition this deletes another location's room of the
            # same id (every location has the ground room).
            conn.execute(
                "DELETE FROM rooms WHERE id=? AND location_id=?",
                (rid, lid))

        for room in rooms:
            rid = room.get("id")
            if not rid:
                continue
            conn.execute("""
                INSERT INTO rooms (id, location_id, name, outfit_type, meta,
                                   decency, style_hint, swim_allowed,
                                   activity_hint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(location_id, id) DO UPDATE SET
                    name=excluded.name,
                    outfit_type=excluded.outfit_type,
                    meta=excluded.meta,
                    decency=excluded.decency,
                    style_hint=excluded.style_hint,
                    swim_allowed=excluded.swim_allowed,
                    activity_hint=excluded.activity_hint
            """, (
                rid,
                lid,
                room.get("name", ""),
                room.get("outfit_type", ""),
                json.dumps(room, ensure_ascii=False),
                room.get("decency", "") or "",
                room.get("style_hint", "") or "",
                1 if room.get("swim_allowed") else 0,
                room.get("activity_hint", "") or "",
            ))


def _after_world_write() -> None:
    """Runs AFTER the transaction of every location write.

    Drops the read cache — whoever reads next must see what was just written —
    and re-rasters the relief.

    THE PLATEAU FOLLOWS THE PLACE (E8 task 4; "Ein Boden" E1 § G5 made it a
    LAW). The world's relief is levelled flat under every footprint that
    draws a built floor (``draws_built_floor``), so moving, turning,
    resizing, placing, deleting — or closing a room of — such a location
    changes the heightfield, and with it what every client draws and what
    the walking rule judges. The location table has exactly three writers
    (upsert, delete, replace) and all three end here, so this is the one
    place that has to say so.
    AFTER the transaction: the re-raster reads the locations back, and it
    must read the written ones. It costs a signature compare when nothing
    moved.
    """
    _bump_world_generation()
    try:
        from app.models.heightfield import note_world_write
        note_world_write()
    except Exception as e:   # noqa: BLE001 — a cache must never fail a write
        logger.warning("heightfield refresh after a world write failed: %s", e)


def _upsert_locations(locations: List[Dict[str, Any]]) -> None:
    rows = [l for l in (locations or [])
            if isinstance(l, dict) and l.get("id")]
    if not rows:
        return
    with world_write_lock:
        try:
            with transaction() as conn:
                _write_location_rows(conn, rows, utc_now_iso())
        except Exception as e:
            logger.error("upsert_location DB-Fehler: %s", e)
        _after_world_write()


def upsert_location(location: Dict[str, Any]) -> None:
    """Write exactly ONE location (and its rooms). The mutation path.

    Everything that loads the world, changes ONE place and stores it again
    goes through here — under :data:`world_write_lock`, and touching no row
    but this location's. That is what keeps an item drop in a room from
    rewriting (and, before 2026-09-21, deleting) the rest of the world.
    """
    _upsert_locations([location])


def upsert_locations(locations: List[Dict[str, Any]]) -> None:
    """Write SEVERAL locations in one transaction — the migrations and the
    sweeps that touch many places at once. Still no delete-by-absence."""
    _upsert_locations(locations)


def delete_location_row(location_id: str) -> bool:
    """Delete ONE location and its rooms. True when a row was removed.

    The row-level counterpart of :func:`upsert_location`: a place disappears
    because someone said so, never because it was missing from a snapshot.
    """
    lid = (location_id or "").strip()
    if not lid:
        return False
    gone = False
    with world_write_lock:
        try:
            with transaction() as conn:
                # The rooms go first: the FK cascade would take them too, but
                # only while PRAGMA foreign_keys is on.
                conn.execute("DELETE FROM rooms WHERE location_id=?", (lid,))
                gone = conn.execute(
                    "DELETE FROM locations WHERE id=?", (lid,)).rowcount > 0
        except Exception as e:
            logger.error("delete_location_row DB-Fehler (%s): %s", lid, e)
            return False
        _after_world_write()
    return gone


def replace_all_locations(data: Any) -> None:
    """Make the world BE this snapshot — every location the snapshot does not
    mention is deleted.

    Delete-by-absence lives here and nowhere else. It is what a world-level
    import or a test fixture that builds a world from scratch wants, and it
    is exactly what a normal mutation must never get: two threads that both
    loaded the world before either wrote used to delete each other's fresh
    locations this way.
    """
    locations = (data.get("locations", []) if isinstance(data, dict)
                 else list(data or []))
    rows = [l for l in locations if isinstance(l, dict) and l.get("id")]
    keep = {l["id"] for l in rows}
    with world_write_lock:
        try:
            with transaction() as conn:
                existing = {r[0] for r in conn.execute(
                    "SELECT id FROM locations").fetchall()}
                for lid in existing - keep:
                    conn.execute("DELETE FROM rooms WHERE location_id=?", (lid,))
                    conn.execute("DELETE FROM locations WHERE id=?", (lid,))
                _write_location_rows(conn, rows, utc_now_iso())
        except Exception as e:
            logger.error("replace_all_locations DB-Fehler: %s", e)
        _after_world_write()


def _save_world_data(data: Dict[str, Any]) -> None:
    """Upsert every location of the snapshot (locations + their rooms).

    NOT a full replace: a location that is missing from ``data`` stays where
    it is. Whoever really means "the world is now exactly this" says so with
    :func:`replace_all_locations`; whoever changed ONE place says
    :func:`upsert_location`.
    """
    _upsert_locations(data.get("locations", []) if isinstance(data, dict)
                      else list(data or []))


# === Welt-Settings (world_kv) ===

def get_world_setting(key: str, default: str = "") -> str:
    """Read a world setting value from world_kv.

    Convention: keys are ``<area>.<field>``, e.g. ``news.style`` or
    ``game_time.factor``. Values are strings — anything more structured has
    to serialize itself.
    """
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT value FROM world_kv WHERE key=?", (key,),
        ).fetchone()
        return (row[0] or default) if row else default
    except Exception as e:
        logger.debug("get_world_setting(%s) Fehler: %s", key, e)
        return default


def set_world_setting(key: str, value: str) -> None:
    """Write a world setting value into world_kv."""
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO world_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value or ""),
            )
    except Exception as e:
        logger.warning("set_world_setting(%s) Fehler: %s", key, e)


# --- World Freeze ---------------------------------------------------------
# Persistenter Schalter, der die AUTONOME Welt-Simulation einfriert (AgentLoop,
# hourly Ticks, Scheduler-Jobs, Telegram-Polling), damit man die Welt in Ruhe
# aufbauen kann. TaskQueue (Bildgenerierung) und LLM-Tools bleiben bewusst
# aktiv — daher NICHT die queue_paused-Pause wiederverwenden.
# Siehe development_instructions/plan-world-freeze.md.
WORLD_FROZEN_KEY = "world_frozen"


def is_world_frozen() -> bool:
    """True wenn die Welt eingefroren ist (autonome Simulation angehalten)."""
    return get_world_setting(WORLD_FROZEN_KEY, "0") == "1"


def set_world_frozen(frozen: bool) -> None:
    """Friert die Welt ein (True) oder taut sie wieder auf (False).

    Freeze stoppt auch die GAME-Uhr (on_freeze_change re-ankert sie);
    Unfreeze laesst sie ab dem eingefrorenen Stand weiterlaufen."""
    from app.core.timeutils import on_freeze_change
    set_world_setting(WORLD_FROZEN_KEY, "1" if frozen else "0")
    try:
        on_freeze_change(frozen)
    except Exception as e:
        logger.warning("game clock freeze hook failed: %s", e)


# --- World Sleep -----------------------------------------------------------
# Persistenter Schalter: alle NPCs schlafen (echtes is_sleeping, siehe
# world_ops.sleep_world/wake_world). Waehrend des Schlafmodus loesen NPCs
# keine LLM-Chat-Calls aus (AgentLoop-Turns/Reaktionen/Bumps, Telegram,
# direkter Chat) — Memory-Konsolidierung, periodische Ticks, Scheduler,
# TaskQueue und LLM-Tools laufen bewusst weiter. Die GAME-Uhr laeuft weiter
# (anders als Freeze). Siehe development_instructions/plan-game-time.md.
WORLD_SLEEPING_KEY = "world_sleeping"
# JSON-Liste der Characters, die schon VOR dem Sleep-Button schliefen —
# wake_world laesst diese schlafen (natuerlicher Schlaf bleibt unangetastet).
WORLD_SLEEP_PRIOR_KEY = "world_sleep_prior"


def is_world_sleeping() -> bool:
    """True wenn der Welt-Schlafmodus aktiv ist (alle NPCs schlafen)."""
    return get_world_setting(WORLD_SLEEPING_KEY, "0") == "1"


def set_world_sleeping(sleeping: bool) -> None:
    set_world_setting(WORLD_SLEEPING_KEY, "1" if sleeping else "0")


# Temperature and weather are NOT world-level any more: they belong to the
# SEASON (`game_seasons` in the world config, see app/core/game_time.Season).
# `GameTime.atmosphere()` is the one reader.


# === Orte ===

def _generate_location_id() -> str:
    """Generiert eine eindeutige 8-Zeichen Hex-ID fuer einen Ort."""
    return uuid.uuid4().hex[:8]


def _generate_room_id() -> str:
    """Generiert eine eindeutige 8-Zeichen Hex-ID fuer einen Raum."""
    return uuid.uuid4().hex[:8]


# The GROUND of a location — the area no room takes up — IS a room, with one
# reserved id that is the same in every location (room ids are unique per
# location, so no second namespace appears).
#
# Why a reserved id and not a flag on the room: a flag would have to be taught
# to every consumer, one by one. An id has to be taught to nobody — decency
# checks, earshot, rules, the room heuristic and both renderers see a room and
# do with it what they always do with rooms. The predecessor tried the other
# way round, giving the EMPTY room id that meaning, and the same bug appeared
# four times over: in Python an empty string reads as "not set" everywhere
# (plan-grundflaeche.md § 2 / § 4).
#
# Authors never create it. ``migrate_ground_rooms_once`` brings it along, and
# the reserved shape keeps it out of the 8-hex space ``_generate_room_id``
# draws from.
GROUND_ROOM_ID = "__ground__"


# THE CORRIDOR OF A STOREY IS A ROOM TOO (spec 2026-09-09-etagen-flur, § 2).
# Same reasoning as the ground: a reserved id per storey, stored in rooms[],
# so every consumer sees an ordinary room. The level rides in the id because
# a character's storey must be knowable from its room alone.
FLOOR_ROOM_PREFIX = "__floor__"


def floor_room_id(level: int) -> str:
    """Reserved id of the corridor room of ``level`` (``__floor__-1``)."""
    return f"{FLOOR_ROOM_PREFIX}{int(level)}"


def floor_room_level(room_id: str) -> Optional[int]:
    """The storey a corridor id names, None for every other id."""
    rid = str(room_id or "")
    if not rid.startswith(FLOOR_ROOM_PREFIX):
        return None
    try:
        return int(rid[len(FLOOR_ROOM_PREFIX):])
    except ValueError:
        return None


def is_floor_room(room_id: str) -> bool:
    """True for a reserved corridor id — the cheap test every consumer uses."""
    return floor_room_level(room_id) is not None


# === Raum-Hilfsfunktionen ===

def get_location_rooms(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Gibt die Raeume eines Orts zurueck."""
    return location.get("rooms", [])


def resolve_indoor_flag(location: Optional[Dict[str, Any]],
                        room: Optional[Dict[str, Any]] = None) -> str:
    """Effective indoor/outdoor flag for a location+room: the ROOM's own
    flag wins over the location's (a pool room in an indoor house is
    'outdoor'). Returns 'indoor' | 'outdoor' | '' (unset)."""
    flag = str((room or {}).get("indoor") or "").strip().lower()
    if flag in ("indoor", "outdoor"):
        return flag
    flag = str((location or {}).get("indoor") or "").strip().lower()
    return flag if flag in ("indoor", "outdoor") else ""


def get_room_by_id(location: Dict[str, Any], room_id: str) -> Optional[Dict[str, Any]]:
    """Findet einen Raum per ID in einem Ort."""
    if not room_id:
        return None
    for room in location.get("rooms", []):
        if room.get("id") == room_id:
            return room
    return None


def find_location_by_room(room_id: str) -> Optional[Dict[str, Any]]:
    """The location OWNING a room id. Used by the per-room model routes
    (AV3D-2), where only the owner's store matters. None when unknown."""
    if not room_id:
        return None
    data = _load_world_data()
    for loc in data.get("locations", []):
        for room in loc.get("rooms", []) or []:
            if room.get("id") == room_id:
                return loc
    return None


def get_room_by_name(location: Dict[str, Any], room_name: str) -> Optional[Dict[str, Any]]:
    """Findet einen Raum per Name (exakt oder fuzzy) in einem Ort."""
    if not room_name:
        return None
    rooms = location.get("rooms", [])
    name_lower = room_name.lower()
    # Exakter Match
    for room in rooms:
        if room.get("name", "").lower() == name_lower:
            return room
    # Substring Match
    for room in rooms:
        rn = room.get("name", "").lower()
        if rn and (rn in name_lower or name_lower in rn):
            return room
    # Wort-basierter Match: alle Wörter des kürzeren im längeren enthalten
    # z.B. "Private Büro" matched "Privates Büro" (büro in beiden, privat* in beiden)
    query_words = name_lower.split()
    for room in rooms:
        rn = room.get("name", "").lower()
        if not rn:
            continue
        room_words = rn.split()
        # Prüfe ob jedes Query-Wort als Prefix eines Raum-Worts vorkommt (oder umgekehrt)
        if query_words and room_words and all(
            any(qw.startswith(rw) or rw.startswith(qw) for rw in room_words)
            for qw in query_words
        ):
            return room
    return None


def get_room_activity_hint(location_id: str, room_id: str = "") -> str:
    """Freitext-Richtung „was man hier typischerweise tut" aus dem Raum
    (Fallback: Location). Ersetzt die fruehere Activity-Namen-Liste — der
    Raum gibt nur die Richtung vor, das LLM entscheidet frei.
    """
    if not location_id:
        return ""
    try:
        loc = get_location_by_id(location_id) or {}
        if room_id:
            for r in (loc.get("rooms") or []):
                if r.get("id") == room_id:
                    h = (r.get("activity_hint") or "").strip()
                    if h:
                        return h
                    break
        return (loc.get("activity_hint") or "").strip()
    except Exception:
        return ""



def _validate_room_description(text: str) -> str:
    """Letzte Sicherheitspruefung bevor eine Raum-Beschreibung gespeichert wird.

    Lehnt Texte ab die offensichtlich keine Raum-Beschreibungen sind
    (eingebettete JSON-Objekte, Tool-Call-Tags, Appearance-Daten).
    """
    if not text or not text.strip():
        return text
    stripped = text.strip()
    # JSON-Objekte (halluzinierte Tool-Calls)
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped) if stripped.endswith("}") else None
            if isinstance(parsed, dict) and ("location_id" in parsed or "room" in parsed):
                logger.warning("Raum-Beschreibung ist JSON-Objekt — abgelehnt")
                return ""
        except Exception:
            pass
        # JSON-Praefix gefolgt von anderem Text
        if '}\n' in stripped or '}<' in stripped:
            logger.warning("Raum-Beschreibung enthaelt JSON-Praefix — abgelehnt")
            return ""
    # Tool-Call-Tags
    if re.search(r'<tool\s+name=', stripped):
        logger.warning("Raum-Beschreibung enthaelt Tool-Tags — abgelehnt")
        return ""
    # Appearance-Daten (physische Character-Beschreibungen)
    appearance_hits = sum(1 for p in [
        r'\b\d+\s*years?\s*(young|old)\b',
        r'\b(large|small|round|perfect)\s+(breasts?|butt|chest)\b',
        r'\b(short|tall|athletic|slim)\s+(frame|build|body)\b',
    ] if re.search(p, stripped, re.IGNORECASE))
    if appearance_hits >= 2:
        logger.warning("Raum-Beschreibung enthaelt Appearance-Daten — abgelehnt")
        return ""
    return text


def add_room(location_id: str, room_name: str, description: str = "",
             image_prompt_day: str = "", image_prompt_night: str = "") -> Optional[Dict[str, Any]]:
    """Adds a new room to a location. Returns the room, or None on error.

    A corridor room counts with its DISPLAY name: unnamed, it answers with the
    translated default of its storey, and a second room carrying that word
    would shadow it everywhere the corridor is named (spec § 4). That
    comparison runs in ENGLISH (lang ""), because this function knows no
    language — a caller that showed the localized name has to match it
    language-aware BEFORE calling here, the way ``describe_room_skill``
    does, or a German "Diele" would still land as a new room.
    """
    # Validation
    description = _validate_room_description(description)
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                rooms = loc.setdefault("rooms", [])
                # Duplicate check (case-insensitive), including the corridors'
                # default names.
                taken = {r.get("name", "").lower() for r in rooms}
                taken |= {floor_room_display_name(r).lower() for r in rooms
                          if is_floor_room(str(r.get("id") or ""))}
                if room_name.lower() in taken:
                    logger.warning("Room '%s' already exists in location %s", room_name, location_id)
                    return None
                new_room = {
                    "id": _generate_room_id(),
                    "name": room_name,
                    "description": description,
                    "image_prompt_day": image_prompt_day,
                    "image_prompt_night": image_prompt_night,
                    "activities": [],
                }
                if image_prompt_day or image_prompt_night:
                    new_room["prompt_changed"] = True
                rooms.append(new_room)
                upsert_location(loc)
                logger.info("Room '%s' added to location %s (id=%s)", room_name, location_id, new_room["id"])
                return new_room
        return None


def update_room_description(location_id: str, room_id: str,
                            new_description: str,
                            image_prompt_day: str = None,
                            image_prompt_night: str = None) -> bool:
    """Aktualisiert Beschreibung und/oder Image-Prompts eines Raums. Returns True bei Erfolg."""
    # Validierung
    new_description = _validate_room_description(new_description)
    if not new_description and image_prompt_day is None and image_prompt_night is None:
        logger.warning("Raum-Beschreibung nach Validierung leer und kein image_prompt — Update abgelehnt")
        return False
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                for room in loc.get("rooms", []):
                    if room.get("id") == room_id:
                        if new_description:
                            room["description"] = new_description
                        if image_prompt_day is not None:
                            if image_prompt_day != room.get("image_prompt_day", ""):
                                room["prompt_changed"] = True
                            room["image_prompt_day"] = image_prompt_day
                        if image_prompt_night is not None:
                            if image_prompt_night != room.get("image_prompt_night", ""):
                                room["prompt_changed"] = True
                            room["image_prompt_night"] = image_prompt_night
                        upsert_location(loc)
                        return True
        return False


def append_room_props(location_id: str, room_id: str,
                      placements: List[Dict[str, Any]]) -> bool:
    """Append prop placements to a room's ``layout.props`` (room_furnish
    accept, plan-room-furnish.md stage 4).

    ADDITIVE only — existing placements are never touched. The merged layout
    runs through the layout sanitizer OF ITS CARRIER — the reduced ground one
    for ``__ground__`` (§ A13a), the room one otherwise — so accepted
    placements obey the exact same whitelist/limits as hand-placed ones.
    False when the location or the room does not exist.

    The GROUND may still be layout-less when the first furnishing lands on it:
    its layout IS the placements, so an empty one is created here rather than
    demanded up front.
    """
    if not placements:
        return False
    from app.core.world_ops import _sanitize_room_layout, sanitize_ground_layout
    is_ground = room_id == GROUND_ROOM_ID
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") != location_id:
                continue
            for room in loc.get("rooms", []):
                if room.get("id") != room_id:
                    continue
                layout = room.get("layout")
                if not isinstance(layout, dict):
                    if not is_ground:
                        return False
                    layout = {}
                merged = dict(layout)
                merged["props"] = list(layout.get("props") or []) + list(placements)
                clean = (sanitize_ground_layout(merged) if is_ground
                         else _sanitize_room_layout(merged))
                if not clean:
                    return False
                room["layout"] = clean
                upsert_location(loc)
                # Accepted props bring markers — the seat inventory is stale.
                from app.core import places; places.invalidate()
                logger.info("Room %s: %d prop placements accepted",
                            room_id, len(placements))
                return True
        return False


def clear_room_prompt_changed(location_id: str, room_id: str) -> bool:
    """Remove the prompt_changed flag from a room. Returns True on success."""
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                for room in loc.get("rooms", []):
                    if room.get("id") == room_id:
                        if room.pop("prompt_changed", None):
                            upsert_location(loc)
                        return True
        return False


def clear_location_prompt_changed(location_id: str) -> bool:
    """Remove the prompt_changed flag from a location. Returns True on success."""
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                if loc.pop("prompt_changed", None):
                    upsert_location(loc)
                return True
        return False


def list_locations() -> List[Dict[str, Any]]:
    """All locations of the world, exactly as stored — no merge of any kind."""
    return _load_world_data().get("locations", [])


def resolve_location(identifier: str) -> Optional[Dict[str, Any]]:
    """Findet einen Ort per ID, Name oder Teilstring (Backwards-Compatibility).

    Sucht: 1) exakte ID, 2) exakter Name, 3) Teilstring-Match (bidirektional).
    """
    if not identifier:
        return None
    locations = list_locations()
    # 1) Exakte ID
    for location in locations:
        if location.get("id") == identifier:
            return location
    # 2) Exakter Name
    for location in locations:
        if location.get("name") == identifier:
            return location
    # 3) Teilstring: "Studentenwohnheim - Gemeinschaftsraum" matched "Studentenwohnheim"
    id_lower = identifier.lower()
    for location in locations:
        loc_name = location.get("name", "").lower()
        if loc_name and (loc_name in id_lower or id_lower in loc_name):
            return location
    return None


def get_location(identifier: str) -> Optional[Dict[str, Any]]:
    """Gibt einen Ort anhand von ID oder Name zurueck (Backwards-Compatible)."""
    return resolve_location(identifier)


# ============================================================
# KNOWLEDGE-ITEM VISIBILITY
# Ein Ort oder Raum kann ein Item verlangen, das der Character besitzen
# muss um diesen Ort/Raum zu "kennen" (im Picker/Chat/Scheduler sichtbar).
# Vererbung: ist das Item auf Location-Ebene gesetzt, gilt es automatisch
# auch fuer alle Raeume darunter — der Character muss es dann erst haben,
# bevor er ueberhaupt die Location sieht.
# ============================================================

def _character_item_ids(character_name: str) -> Set[str]:
    """All item ids in the character's inventory (empty set on any failure)."""
    if not character_name:
        return set()
    try:
        from app.models.inventory import _load_inventory
        inv = _load_inventory(character_name).get("inventory", []) or []
    except Exception:
        return set()
    return {e.get("item_id") for e in inv if e.get("item_id")}


def _character_has_item(character_name: str, item_id: str) -> bool:
    """Check whether the character carries the given item."""
    if not item_id or not character_name:
        return False
    return item_id in _character_item_ids(character_name)


def _character_known_locations(character_name: str) -> List[str]:
    """The character's known_locations list (always a list).

    Empty list = the character knows no place yet and can go nowhere.
    Auto-discovery on entering and discover rules extend the list.
    """
    if not character_name:
        return []
    try:
        from app.models.character import get_character_config
        cfg = get_character_config(character_name) or {}
    except Exception:
        return []
    val = cfg.get("known_locations")
    if isinstance(val, list):
        return [str(v) for v in val if v]
    return []


def visibility_context(character_name: str) -> Dict[str, Any]:
    """Everything ``location_visible_to_character`` reads about the character,
    fetched ONCE.

    Callers that test many locations for the same character (the worldmap
    payload does, on a 3-second poll) pass the result back in instead of
    letting the predicate re-read the character config and the inventory per
    location. The rules themselves stay in the predicate — this only supplies
    its inputs.
    """
    return {
        "known": set(_character_known_locations(character_name)),
        "items": _character_item_ids(character_name),
    }


def location_knowledge_gate_open(character_name: str,
                                    location: Dict[str, Any],
                                    context: Optional[Dict[str, Any]] = None
) -> bool:
    """True when the character owns the location's knowledge item — or none is
    set. The ITEM half of ``location_visible_to_character``, on its own.

    It exists separately for the one caller that must ask the item gate but
    NOT the known half: the discover rule (``rules.check_discover_rules``)
    picks from locations that are by definition still unknown, and a gated
    place must stay out of that pool — otherwise the roll is burnt on
    something that stays invisible and its NAME lands in the state history.
    The gate expression itself lives here only, never twice.

    ``context``: a ``visibility_context()`` result for this character.
    """
    if not isinstance(location, dict):
        return False
    iid = (location.get("knowledge_item_id") or "").strip()
    if not iid:
        return True
    return iid in context["items"] if context is not None \
        else _character_has_item(character_name, iid)


def location_visible_to_character(character_name: str,
                                    location: Dict[str, Any],
                                    context: Optional[Dict[str, Any]] = None
) -> bool:
    """True when the character owns the location's knowledge item (or none is
    set) AND the location is in its known_locations list. Strict — an empty
    list means nothing is visible.

    ``context``: a ``visibility_context()`` result for this character; when
    given, its precomputed sets replace the per-call DB reads. Same answer,
    one lookup instead of two per location.
    """
    if not isinstance(location, dict):
        return False
    if not location_knowledge_gate_open(character_name, location, context):
        return False
    known = context["known"] if context is not None \
        else _character_known_locations(character_name)
    loc_id = location.get("id") or ""
    if loc_id not in known:
        return False
    return True


def room_visible_to_character(character_name: str,
                                location: Dict[str, Any],
                                room: Dict[str, Any],
                                context: Optional[Dict[str, Any]] = None
) -> bool:
    """True when the character has the location's AND the room's knowledge
    item (both optional).

    ``context``: a ``visibility_context()`` result for this character; when
    given, its precomputed sets replace the per-call DB reads — of the
    location gate below AND of this room's item. Same answer, no lookup.
    """
    if not location_visible_to_character(character_name, location, context):
        return False
    if not isinstance(room, dict):
        return False
    iid = (room.get("knowledge_item_id") or "").strip()
    if not iid:
        return True
    return iid in context["items"] if context is not None \
        else _character_has_item(character_name, iid)


def list_locations_for_character(character_name: str) -> List[Dict[str, Any]]:
    """Liefert alle Locations die der Character dank Wissens-Items sehen darf.
    Raeume werden pro Location ebenfalls gefiltert — nur sichtbare bleiben im
    zurueckgelieferten 'rooms'-Array.

    The character's known list and inventory are fetched ONCE
    (``visibility_context``) and passed down. Without it a 30-location world
    with 7 rooms each asked for the character config and the inventory 240
    times — per chat turn.
    """
    ctx = visibility_context(character_name)
    visible = []
    for loc in list_locations():
        if not location_visible_to_character(character_name, loc, ctx):
            continue
        rooms = [r for r in (loc.get("rooms") or [])
                 if room_visible_to_character(character_name, loc, r, ctx)]
        visible.append({**loc, "rooms": rooms})
    return visible


def get_location_by_id(location_id: str) -> Optional[Dict[str, Any]]:
    """Gibt einen Ort per exakter ID-Suche zurueck.

    Served from the read cache's id index when it is warm — one parse instead
    of one per location of the world.
    """
    if not location_id:
        return None
    if _cached_texts() is None:
        _load_world_data()          # warm the cache, then use the index
    with _world_cache_lock:
        by_id = _world_cache["by_id"] if (
            _world_cache["key"] == _world_cache_key()
            and _world_cache["gen"] == _world_generation) else None
        text = by_id.get(location_id) if by_id else None
    if text is not None:
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            pass
    for location in list_locations():
        if location.get("id") == location_id:
            return location
    return None


def get_room_name(location_id: str, room_id: str, lang: str = "") -> str:
    """Display name of a room within a location.

    Falls back to the raw ``room_id`` when it cannot be resolved (hand-made
    rooms may use the name itself as id); '' when either id is missing.

    The GROUND room is the one id that must never surface — it is reserved,
    not authored, and would read as gibberish in a prompt or a narrated line.
    Unnamed, it answers with the translated default; ``get_ground_name`` owns
    that default, here and everywhere else (plan-grundflaeche.md § 3). The
    corridor of a storey is reserved the same way and answers the same way —
    the author's name if there is one, else the default of its level.
    """
    if not (location_id and room_id):
        return ""
    if room_id == GROUND_ROOM_ID:
        return get_ground_name(location_id, lang)
    lv = floor_room_level(room_id)
    if lv is not None:
        loc = get_location_by_id(location_id) or {}
        for room in (loc.get("rooms") or []):
            if str(room.get("id") or "") == room_id:
                return floor_room_display_name(room, lang)
        return get_floor_name(lv, lang)
    try:
        loc = get_location_by_id(location_id) or {}
        for room in (loc.get("rooms") or []):
            if str(room.get("id") or "") == room_id:
                return str(room.get("name") or "") or room_id
    except Exception:
        pass
    return room_id


def get_ground_name(location_id: str, lang: str = "") -> str:
    """Display name of a location's GROUND — the area no room takes up.

    Reads the reserved GROUND room like any other room. Authors may give it a
    name of its own ("Market square", "Clearing") by editing that room;
    without one every location falls back to the same translated word.
    """
    loc = get_location_by_id(location_id) or {} if location_id else {}
    for room in (loc.get("rooms") or []):
        if str(room.get("id") or "") == GROUND_ROOM_ID:
            name = str(room.get("name") or "").strip()
            if name:
                return name
            break
    from app.core.i18n import t
    return t("Outside", lang)


def ground_room_action(location: Dict[str, Any]) -> str:
    """What the ground migration has to do for ONE location.

    A pure decision, so ``scripts/smoke_ground_room.py`` can check it by hand
    while the loop around it touches rows:

    - ``"add"`` — the location carries no room with the reserved id and gets
      one. The normal case, with or without rooms of its own: the ground
      exists in every location.
    - ``"present"`` — a room already carries the reserved id. Nothing is
      touched: on a repeated run that is this migration's own room, and when
      an author assigned the id by hand, overwriting would destroy their
      room. Both are the same case here — the caller reports it and moves on.
    """
    for room in (location.get("rooms") or []):
        if str(room.get("id") or "") == GROUND_ROOM_ID:
            return "present"
    return "add"


def ground_room_target(current_room: str, room_ids: List[str]) -> str:
    """The room a character has to be moved into, ``""`` when it stays put.

    ``room_ids`` are the room ids of the character's current location, the
    ground room among them. Pure, checked by hand in
    ``scripts/smoke_ground_room.py``:

    - no room at all: it stood on the ground all along;
    - a room its location actually has (the ground included): it stays;
    - a room its location does NOT have: it stood nowhere, and the ground is
      the honest place for that.
    """
    if current_room and current_room in room_ids:
        return ""
    return GROUND_ROOM_ID


def ensure_ground_room(rooms: List[Dict[str, Any]],
                       previous: Optional[List[Dict[str, Any]]] = None) -> None:
    """Keep the reserved ground room in a location's room list, in place.

    The server brings the ground, the author never creates or deletes it
    (plan-grundflaeche.md § 3) — but the editor submits WHOLE room lists, so
    a delete arrives as a list that simply lacks it. This puts it back, with
    the name AND the yard the location had for it (``previous`` = the stored
    room list; since § A13a the ground carries placements, and a client that
    simply does not send the room must not wipe them), appended LAST so it
    never displaces an authored room in the editor's order — position carries
    no meaning any more, ``entry_room`` is declared or it is not
    (``get_entry_room_id``).

    It is also what gives a location created AFTER the one-time migration its
    ground: the migration runs once, this runs on every write.

    A list that still carries the id is left untouched — including a
    location where an author put their own room on that id, which the
    migration reports as a collision rather than overwriting.
    """
    if any(str(r.get("id") or "") == GROUND_ROOM_ID
           for r in rooms if isinstance(r, dict)):
        return
    name = ""
    layout: Any = None
    for r in (previous or []):
        if isinstance(r, dict) and str(r.get("id") or "") == GROUND_ROOM_ID:
            name = str(r.get("name") or "")
            layout = r.get("layout")
            break
    entry: Dict[str, Any] = {"id": GROUND_ROOM_ID, "name": name,
                             "description": "", "activities": []}
    if isinstance(layout, dict) and layout:
        entry["layout"] = layout
    rooms.append(entry)


def floor_levels(rooms: List[Dict[str, Any]],
                 map3d: Optional[Dict[str, Any]]) -> Set[int]:
    """Storeys that own a corridor: every storey a layout room stands on,
    except 0 — the ground floor's complement is the yard unless the location
    opts in (``map3d.ground_corridor``). The ground's reduced layout carries
    no level and never counts (spec § 2.2)."""
    used: Set[int] = set()
    for r in rooms or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        if rid == GROUND_ROOM_ID or is_floor_room(rid):
            continue
        lay = r.get("layout")
        if not isinstance(lay, dict) or not lay:
            continue
        try:
            used.add(int(lay.get("level") or 0))
        except (TypeError, ValueError):
            used.add(0)
    opt_in = bool((map3d or {}).get("ground_corridor"))
    return {lv for lv in used if lv != 0 or opt_in}


def ensure_floor_rooms(rooms: List[Dict[str, Any]],
                       map3d: Optional[Dict[str, Any]],
                       previous: Optional[List[Dict[str, Any]]] = None
                       ) -> List[str]:
    """Two-way sync of the corridor rooms in a location's room list, in place.

    Missing corridors of used storeys are appended LAST (name/description from
    ``previous`` — the editor submits whole lists and must not wipe a name),
    corridors of storeys no room stands on any more are removed. Returns the
    removed ids so the caller can move characters/utterances off them
    (:func:`evict_rooms_to_ground`). An entry that is already there is never
    touched.
    """
    wanted = floor_levels(rooms, map3d)
    present: Dict[Optional[int], Dict[str, Any]] = {}
    removed: List[str] = []
    # The stale entries are collected BY INDEX during the scan: two corridor
    # entries that happen to be equal dicts would make ``list.remove`` drop
    # the wrong one.
    stale: List[int] = []
    for idx, r in enumerate(rooms):
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        if not is_floor_room(rid):
            continue
        lv = floor_room_level(rid)
        present[lv] = r
        if lv not in wanted:
            stale.append(idx)
            removed.append(rid)
    for idx in reversed(stale):
        del rooms[idx]
    prev_by_id = {str(r.get("id") or ""): r
                  for r in (previous or []) if isinstance(r, dict)}
    for lv in sorted(wanted):
        if lv in present:
            continue
        old = prev_by_id.get(floor_room_id(lv)) or {}
        rooms.append({"id": floor_room_id(lv), "level": lv,
                      "name": str(old.get("name") or ""),
                      "description": str(old.get("description") or ""),
                      "activities": []})
    return removed


def get_floor_name(level: int, lang: str = "") -> str:
    """Default display name of a storey's corridor (spec § 2.1).

    Like the ground, an unnamed corridor answers with a translated default so
    the reserved id never surfaces in a prompt or a chip.
    """
    from app.core.i18n import t
    lv = int(level)
    if lv == 0:
        return t("Hallway", lang)
    if lv == -1:
        return t("Corridor (basement)", lang)
    if lv < -1:
        return t("Corridor (basement {n})", lang).format(n=lv)
    return t("Corridor (floor {n})", lang).format(n=lv)


def floor_room_display_name(room: Dict[str, Any], lang: str = "") -> str:
    """Name of a corridor room: the author's if there is one, else the default."""
    name = str((room or {}).get("name") or "").strip()
    if name:
        return name
    lv = floor_room_level(str((room or {}).get("id") or ""))
    return get_floor_name(lv if lv is not None else 0, lang)


def valid_entry_room(rooms: List[Dict[str, Any]], entry_room: str) -> str:
    """The entry room an author may declare: a room of the list, and of the
    corridors only the ground floor's (one arrives in the hallway, never in a
    basement corridor — spec § 4)."""
    rid = str(entry_room or "").strip()
    if not rid:
        return ""
    ids = {str(r.get("id") or "") for r in rooms if isinstance(r, dict)}
    if rid not in ids:
        return ""
    lv = floor_room_level(rid)
    if lv is not None and lv != 0:
        return ""
    return rid


def evict_rooms_to_ground(location_id: str, room_ids: List[str]) -> Dict[str, int]:
    """Move everyone standing in one of ``room_ids`` of ``location_id`` onto
    the ground — used when a corridor room disappears because its storey lost
    its last room. The server does not know a roomless character's storey, so
    the ground is the one honest place (spec § 2.4)."""
    counts = {"characters": 0, "utterances": 0}
    ids = [r for r in room_ids if r]
    if not (location_id and ids):
        return counts
    marks = ",".join("?" for _ in ids)
    with transaction() as conn:
        cur = conn.execute(
            f"UPDATE character_state SET current_room=? "
            f"WHERE current_location=? AND current_room IN ({marks})",
            (GROUND_ROOM_ID, location_id, *ids))
        counts["characters"] = cur.rowcount or 0
        cur = conn.execute(
            f"UPDATE utterances SET room_id=? "
            f"WHERE location_id=? AND room_id IN ({marks})",
            (GROUND_ROOM_ID, location_id, *ids))
        counts["utterances"] = cur.rowcount or 0
    return counts


def migrate_ground_rooms_once() -> Dict[str, int]:
    """One-time, idempotent: give every location its ground room and move
    everything that stood in no room onto it.

    Three passes — locations, characters, utterances — and the counts come
    back so the boot log can state them: ``locations`` added, ``characters``
    moved, ``utterances`` moved, ``collisions`` reported. Guarded by a
    world_kv marker, so a second boot returns zeros without touching a row;
    the per-location decision is idempotent on its own as well
    (``ground_room_action`` never adds a second one).

    A collision — an author's room on the reserved id — is skipped WHOLE:
    neither its characters nor its utterances are moved, because that id does
    not address a ground there. Each one is logged with its location id, or
    the author would never find it.
    """
    counts = {"locations": 0, "characters": 0, "utterances": 0,
              "collisions": 0}
    if get_world_setting("migration.ground_room_v1", "") == "done":
        return counts
    try:
        with world_write_lock:
            data = _load_world_data()
            collisions: set = set()
            changed = False
            for loc in data.get("locations", []):
                lid = str(loc.get("id") or "")
                action = ground_room_action(loc)
                # The former location field `ground_name` becomes the room's own
                # name and is gone from the location for good; empty keeps the
                # translated default.
                name = str(loc.pop("ground_name", "") or "").strip()
                if name:
                    changed = True
                if action == "add":
                    loc.setdefault("rooms", []).append({
                        "id": GROUND_ROOM_ID,
                        "name": name,
                        "description": "",
                        "activities": [],
                    })
                    counts["locations"] += 1
                    changed = True
                elif action == "present":
                    collisions.add(lid)
                    counts["collisions"] += 1
                    logger.warning(
                        "ground-room migration: location %s (%s) already has a "
                        "room with the reserved id %r — skipped, nothing moved "
                        "there", lid, loc.get("name", ""), GROUND_ROOM_ID)
            if changed:
                upsert_locations(data.get("locations", []))

        # Which locations have a usable ground now — collisions excluded.
        rooms_by_loc: Dict[str, List[str]] = {}
        for loc in list_locations():
            lid = str(loc.get("id") or "")
            if not lid or lid in collisions:
                continue
            ids = [str(r.get("id") or "") for r in (loc.get("rooms") or [])]
            if GROUND_ROOM_ID in ids:
                rooms_by_loc[lid] = ids

        with transaction() as conn:
            rows = conn.execute(
                "SELECT character_name, current_location, current_room "
                "FROM character_state").fetchall()
            for name, cur_loc, cur_room in rows:
                ids = rooms_by_loc.get(str(cur_loc or ""))
                if ids is None:
                    continue
                target = ground_room_target(str(cur_room or ""), ids)
                if not target:
                    continue
                conn.execute(
                    "UPDATE character_state SET current_room=? "
                    "WHERE character_name=?", (target, name))
                counts["characters"] += 1
            for lid in rooms_by_loc:
                cur = conn.execute(
                    "UPDATE utterances SET room_id=? "
                    "WHERE location_id=? AND room_id=''",
                    (GROUND_ROOM_ID, lid))
                counts["utterances"] += cur.rowcount or 0

        set_world_setting("migration.ground_room_v1", "done")
        logger.info(
            "ground-room migration: %d location(s) got the ground room, "
            "%d character(s) and %d utterance(s) moved onto it, "
            "%d collision(s)", counts["locations"], counts["characters"],
            counts["utterances"], counts["collisions"])
    except Exception as e:
        logger.warning("ground-room migration failed: %s", e)
    return counts


def count_corridor_doors(location: Dict[str, Any]) -> int:
    """Doors of ``location`` that now lead into a corridor (spec § 3.5).

    Pure. A door or passage nobody linked (`to` empty), drawn in an ordinary
    room that stands on a storey owning a corridor, used to cut a hole into
    the building hull and is an interior door from now on (decision 2 — there
    are no balcony doors). The migration reports the number per location so
    the change of meaning is visible in the boot log.
    """
    rooms = location.get("rooms") or []
    levels = floor_levels(rooms, location.get("map3d"))
    n = 0
    for r in rooms:
        if not isinstance(r, dict):
            continue
        lay = r.get("layout")
        if not isinstance(lay, dict) or not lay:
            continue
        rid = str(r.get("id") or "")
        if rid == GROUND_ROOM_ID or is_floor_room(rid):
            continue
        try:
            level = int(lay.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        if level not in levels:
            continue
        for op in lay.get("openings") or []:
            if not isinstance(op, dict):
                continue
            if str(op.get("type") or "door").lower() not in ("door", "passage"):
                continue
            if not str(op.get("to") or "").strip():
                n += 1
    return n


def corridor_door_rooms(location: Dict[str, Any]) -> List[str]:
    """The ROOMS behind :func:`count_corridor_doors`, in ``rooms[]`` order.

    Pure, and deliberately the same walk: the migration log says how many
    doors changed meaning, and a bare number leaves the author hunting for
    them. Each entry is the room's name, or its id when it was never named —
    what the floor-plan editor prints in its room list. A room with two such
    doors appears ONCE: the author opens a room, not a door.
    """
    rooms = location.get("rooms") or []
    levels = floor_levels(rooms, location.get("map3d"))
    out: List[str] = []
    for r in rooms:
        if not isinstance(r, dict):
            continue
        lay = r.get("layout")
        if not isinstance(lay, dict) or not lay:
            continue
        rid = str(r.get("id") or "")
        if rid == GROUND_ROOM_ID or is_floor_room(rid):
            continue
        try:
            level = int(lay.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        if level not in levels:
            continue
        for op in lay.get("openings") or []:
            if not isinstance(op, dict):
                continue
            if str(op.get("type") or "door").lower() not in ("door", "passage"):
                continue
            if not str(op.get("to") or "").strip():
                out.append(str(r.get("name") or "").strip() or rid)
                break
    return out


def migrate_floor_rooms_once() -> Dict[str, int]:
    """One-time, idempotent: give every used storey its corridor room.

    Normally no character moves — nobody stood in a corridor before it
    existed; only a hand-authored or imported ``__floor__X`` on a storey
    without rooms is removed, and then its occupants land on the ground.
    Storey 0 only joins on the location's opt-in, so at first nowhere. Per
    location the log states how many corridors were added and how many doors
    change meaning (spec § 3.5, decision 2). Guarded by a world_kv marker, so a
    second boot returns zeros without touching a row.
    """
    counts = {"locations": 0, "corridors": 0, "doors": 0}
    if get_world_setting("migration.floor_rooms_v1", "") == "done":
        return counts
    try:
        with world_write_lock:
            data = _load_world_data()
            changed = False
            evicted: List[Tuple[str, List[str]]] = []
            for loc in data.get("locations", []):
                rooms = loc.get("rooms")
                if not isinstance(rooms, list):
                    # A blob with ``rooms: null`` must not abort the whole run.
                    loc["rooms"] = rooms = []
                before = len(rooms)
                removed = ensure_floor_rooms(rooms, loc.get("map3d"))
                # The removals are added back in: a location that loses one stale
                # corridor and gains one real one has the same room count, and
                # the bare length delta would report "0 added".
                added = len(rooms) - before + len(removed)
                lid = loc.get("id")
                if removed:
                    # A hand-authored or imported ``__floor__X`` on a storey no
                    # room stands on: it goes, and whoever stood in it lands on
                    # the ground (spec § 2.4). The eviction itself waits for the
                    # save below — see there.
                    logger.warning(
                        "floor-room migration: location %s: corridor room(s) on "
                        "storeys without rooms removed: %s", lid, ", ".join(removed))
                    evicted.append((lid, removed))
                    changed = True
                doors = count_corridor_doors(loc)
                if added or doors:
                    logger.info(
                        "floor-room migration: location %s (%s): %d corridor(s) "
                        "added, %d door(s) now lead into a corridor%s",
                        lid, loc.get("name", ""), added, doors,
                        (": " + ", ".join(corridor_door_rooms(loc))) if doors else "")
                    counts["locations"] += 1
                    counts["corridors"] += added
                    counts["doors"] += doors
                changed = changed or bool(added)
            if changed:
                upsert_locations(data.get("locations", []))
        # AFTER THE SAVE, like every write path: the room is gone from the
        # blob first, then the characters standing in it are moved. The other
        # way round a crash in between would leave a character pointing at a
        # room that is still stored — and the eviction would have to run
        # again to find it.
        for lid, removed in evicted:
            evict_rooms_to_ground(lid, removed)
        set_world_setting("migration.floor_rooms_v1", "done")
        logger.info(
            "floor-room migration: %d location(s) got %d corridor room(s), "
            "%d door(s) now lead into a corridor", counts["locations"],
            counts["corridors"], counts["doors"])
    except Exception as e:
        logger.warning("floor-room migration failed: %s", e)
    return counts


# === Exit point -> door opening (plan-betreten-und-tueren.md § 6) ===
# The editor's standard door — OPENING_DEFAULT in
# frontend/src/tabs/world/planGeometry.ts. Change both or neither.
EXIT_DOOR_WIDTH_M = 1.0
EXIT_DOOR_HEIGHT_M = 2.1


def project_exit_to_opening(layout: Any) -> Optional[Dict[str, Any]]:
    """The door a stored ``layout.exit`` becomes — or None.

    A pure function. ``exit`` is a point in fractions of the room RECTANGLE
    (the one legacy field this one-time migration still reads); it is clamped
    into that rectangle, converted to ABSOLUTE LOCAL METRES (the frame of
    x/y/w/d since contract v6 Nr. 2) and
    projected onto the nearest edge of the room hull. The hull is the drawn
    ``outline`` or, absent that, the implicit unit square with the edge
    indices 0=N, 1=E, 2=S, 3=W; the result carries the edge INDEX, the way
    the editor writes openings.

    None — nothing is invented — when:
    - the layout has no usable rectangle or no ``exit``,
    - the target edge already carries a walkable opening (door/passage; a
      window is not a way out), letters and indices read alike,
    - the target edge is curved (openings on curved edges are rejected on
      save, and a neighbouring edge would be the wrong wall),
    - the target edge is shorter than the standard door.
    """
    from app.core.room_recipe import (  # local: keeps world.py import-light
        _WALKABLE_TYPES, _abs_outline, _normalize_opening, _unit_edge,
        room_transform)

    if not isinstance(layout, dict):
        return None
    ex = layout.get("exit")
    if not isinstance(ex, (list, tuple)) or len(ex) != 2:
        return None
    try:
        u = min(max(float(ex[0]), 0.0), 1.0)
        v = min(max(float(ex[1]), 0.0), 1.0)
        # Through the room transform, like the hull below — the projection is
        # only meaningful when point and hull sit in the SAME frame, and a
        # turned room turns both (contract v6 addendum).
        px, py = room_transform(layout)(u * float(layout["w"]),
                                        v * float(layout["d"]))
    except (KeyError, TypeError, ValueError):
        return None
    outline = _abs_outline(layout)
    if len(outline) < 3:
        return None

    best = None  # (distance², edge index, at, edge length)
    for i in range(len(outline)):
        edge = _unit_edge(outline, i)
        if not edge:
            continue
        ax, ay, ux, uy, length = edge
        t = min(max((px - ax) * ux + (py - ay) * uy, 0.0), length)
        qx, qy = ax + ux * t, ay + uy * t
        dist2 = (px - qx) ** 2 + (py - qy) ** 2
        if best is None or dist2 < best[0]:
            best = (dist2, i, t / length, length)
    if best is None:
        return None
    _, index, at, span = best

    for curve in layout.get("outline_curves") or []:
        if isinstance(curve, dict) and curve.get("edge") == index:
            return None
    for op in layout.get("openings") or []:
        if not isinstance(op, dict) or op.get("type") not in _WALKABLE_TYPES:
            continue
        if _normalize_opening(op).get("edge") == index:
            return None

    # Edge lengths are metres now, so the door's clear width IS the number.
    door = EXIT_DOOR_WIDTH_M
    if span < door:
        return None
    half = (door / 2) / span
    return {
        "edge": index,
        "at": round(min(max(at, half), 1.0 - half), 4),
        "type": "door",
        "width_m": EXIT_DOOR_WIDTH_M,
        "height_m": EXIT_DOOR_HEIGHT_M,
        "sill_m": 0.0,
    }


def migrate_room_exits_once() -> Dict[str, int]:
    """One-time, idempotent: every stored exit point becomes a door.

    The doors are the way in and out (plan-betreten-und-tueren.md § 4/§ 6),
    so a room that only had an exit point gets a door where that point sat.
    Afterwards ``exit`` is REMOVED from the layout — that is the idempotency,
    a second run finds nothing left to migrate — and no reader falls back to
    it.

    The counts come back so the boot log can state them: ``rooms`` carried an
    exit, ``openings`` were created, ``skipped`` had a walkable opening on
    that wall already (or no wall with room for a door), ``broken`` had no
    usable hull at all. Guarded by a world_kv marker.
    """
    counts = {"rooms": 0, "openings": 0, "skipped": 0, "broken": 0}
    if get_world_setting("migration.room_exit_doors_v1", "") == "done":
        return counts
    try:
        from app.core.room_recipe import _abs_outline

        with world_write_lock:
            data = _load_world_data()
            changed = False
            for loc in data.get("locations", []):
                for room in loc.get("rooms") or []:
                    if not isinstance(room, dict):
                        continue
                    layout = room.get("layout")
                    if not isinstance(layout, dict) or layout.get("exit") is None:
                        continue
                    counts["rooms"] += 1
                    opening = project_exit_to_opening(layout)
                    if opening:
                        layout.setdefault("openings", []).append(opening)
                        counts["openings"] += 1
                    elif len(_abs_outline(layout)) < 3:
                        counts["broken"] += 1
                        logger.warning(
                            "exit-door migration: room %s of location %s has an "
                            "exit but no usable hull — dropped",
                            room.get("id", ""), loc.get("id", ""))
                    else:
                        counts["skipped"] += 1
                    layout.pop("exit", None)
                    changed = True
            if changed:
                upsert_locations(data.get("locations", []))
        set_world_setting("migration.room_exit_doors_v1", "done")
        logger.info(
            "exit-door migration: %d room(s) with an exit point, %d door(s) "
            "created, %d skipped, %d without a hull",
            counts["rooms"], counts["openings"], counts["skipped"],
            counts["broken"])
    except Exception as e:
        logger.warning("exit-door migration failed: %s", e)
    return counts


def migrate_clear_entry_rooms_once() -> Dict[str, int]:
    """One-time, idempotent: no location declares an entry room any more.

    ``entry_room`` used to be filled everywhere, mostly with the first room —
    a value nobody had authored, which behaved like a gate one had to walk to.
    The default is now "arrive on the ground" (plan-grundflaeche.md § 6), so
    every stored value is cleared, the deliberate ones included: the field
    stays in the editor and an author who really means "here one arrives
    indoors" sets it again by hand.

    The count comes back so the boot log can state it: ``locations`` were
    cleared. Guarded by a world_kv marker, so a second boot returns zero
    without touching a row. Every cleared value is logged with its location
    BEFORE it goes — the clear is irreversible, and the log is the only place
    an authored arrival room can be read back from.
    """
    counts = {"locations": 0}
    if get_world_setting("migration.clear_entry_room_v1", "") == "done":
        return counts
    # The ground must exist before arrivals are sent to it — if the ground
    # migration did not finish, this one waits for the next boot.
    if get_world_setting("migration.ground_room_v1", "") != "done":
        return counts
    try:
        with world_write_lock:
            data = _load_world_data()
            changed = False
            for loc in data.get("locations", []):
                if not isinstance(loc, dict):
                    continue
                if not str(loc.get("entry_room") or "").strip():
                    continue
                logger.info(
                    "entry-room migration: location %s (%s) had entry room %r — "
                    "cleared", loc.get("id", ""), loc.get("name", ""),
                    loc["entry_room"])
                loc["entry_room"] = ""
                counts["locations"] += 1
                changed = True
            if changed:
                upsert_locations(data.get("locations", []))
        set_world_setting("migration.clear_entry_room_v1", "done")
        logger.info(
            "entry-room migration: %d location(s) cleared — arrivals land on "
            "the ground now", counts["locations"])
    except Exception as e:
        logger.warning("entry-room migration failed: %s", e)
    return counts


def get_location_name(location_id: str) -> str:
    """Gibt den Namen eines Ortes anhand seiner ID zurueck.

    Wenn die ID aufgeloest werden kann: Name zurueck.
    Wenn es wie eine Hex-ID aussieht aber nicht gefunden wird: "" (stale Referenz).
    Sonst (temporaerer Ortsname wie "Café"): Wert direkt zurueck.
    """
    loc = resolve_location(location_id)
    if loc:
        return loc.get("name", location_id)
    # Hex-ID die nicht aufgeloest werden konnte = geloeschter Ort
    if re.match(r'^[0-9a-f]{8}$', location_id):
        return ""
    # Temporaerer Ortsname (z.B. "Café") — direkt zurueckgeben
    return location_id


def get_location_id(identifier: str) -> str:
    """Gibt die ID eines Ortes zurueck (per ID oder Name gesucht).

    Nuetzlich um von Name auf ID zu konvertieren.
    """
    loc = resolve_location(identifier)
    if loc:
        return loc.get("id", "")
    return ""


def add_location(name: str, description: str,
                  rooms: List[Dict[str, Any]] = None,
                  activities: List[Dict[str, str]] = None,
                  image_prompt_day: str = None,
                  image_prompt_night: str = None,
                  image_prompt_building: str = None,
                  decency: str = None,
                  style_hint: str = None,
                  swim_allowed: bool = None,
                  indoor: str = None,
                  activity_hint: str = None,
                  danger_level: int = None,
                  location_id: str = None,
                  create_new: bool = False) -> Dict[str, Any]:
    """Adds a new location or updates an existing one.

    Args:
        rooms: list of {id, name, description, activities} objects
        activities: legacy — ignored when rooms is given
        image_prompt_day: prompt for the daytime background image (6-18h)
        image_prompt_night: prompt for the nighttime background image (18-6h)
        image_prompt_building: prompt for the building exterior view
            (source image for the location's 3D building model)
        decency/style_hint/swim_allowed/indoor/activity_hint: location-level
            semantic fields (only set when not None) — mirrors the fields the
            LocationEditor writes via PUT.
        danger_level: 0-5, clamped; only written when given (same rule as the
            LocationEditor PUT path in world_ops).
        location_id: When set, the location to update is found by ID
            (unambiguous) instead of by name. NEEDED with duplicate names —
            otherwise the name search hits the wrong place.
        create_new: Always create, never update. Without it a name that already
            exists is read as an EDIT of that place, which is right for an
            author typing a name into a form and wrong for anything generating
            places in bulk (a map draft): there a name is a label, not a key,
            and two mills on the same river are two mills.
    """
    with world_write_lock:
        data = _load_world_data()
        locations = data.get("locations", [])

        # Room-IDs sicherstellen
        if rooms is not None:
            for room in rooms:
                if not room.get("id"):
                    room["id"] = _generate_room_id()

        # Find the location to update: by ID when one is given (unambiguous),
        # otherwise by name.
        def _is_target(loc: Dict[str, Any]) -> bool:
            return (loc.get("id") == location_id) if location_id else (loc.get("name") == name)

        for location in ([] if create_new else locations):
            if _is_target(location):
                location["description"] = description
                # An ID-based update writes the (possibly new) name along.
                if location_id and name:
                    location["name"] = name
                removed_corridors: List[str] = []
                if rooms is not None:
                    # The old rooms as a lookup for the prompt_changed comparison
                    # AND for keeping server state (items, prompt_changed, ...).
                    # On a room edit the frontend sends only the fields it knows —
                    # items placed separately via /inventory/rooms are missing
                    # from its list and would otherwise be dropped on save.
                    old_rooms_by_id = {r["id"]: r for r in location.get("rooms", []) if r.get("id")}
                    # Fields the room editor does NOT manage — taken from the
                    # stored room on update when they are not submitted.
                    _server_state_fields = ("items",)
                    for room in rooms:
                        old_room = old_rooms_by_id.get(room.get("id"))
                        if old_room:
                            # Keep the server-state fields the frontend left out
                            for fld in _server_state_fields:
                                if fld not in room and fld in old_room:
                                    room[fld] = old_room[fld]
                            # Set prompt_changed only when the prompts really changed
                            day_changed = room.get("image_prompt_day", "") != old_room.get("image_prompt_day", "")
                            night_changed = room.get("image_prompt_night", "") != old_room.get("image_prompt_night", "")
                            if day_changed or night_changed:
                                room["prompt_changed"] = True
                            else:
                                # Keep the existing prompt_changed state
                                if old_room.get("prompt_changed"):
                                    room["prompt_changed"] = True
                        else:
                            # New room — set the flag when it carries prompts
                            if room.get("image_prompt_day") or room.get("image_prompt_night"):
                                room.setdefault("prompt_changed", True)
                    # The ground is not the author's to delete — a submitted list
                    # without it gets it back, keeping the name it had.
                    ensure_ground_room(rooms, list(old_rooms_by_id.values()))
                    # The corridors follow the storeys this list uses: a storey
                    # that gained its first room gets one, a storey that lost its
                    # last one loses it — and whoever stood in that corridor is
                    # put on the ground, because no storey holds them any more.
                    removed_corridors = ensure_floor_rooms(
                        rooms, location.get("map3d"), list(old_rooms_by_id.values()))
                    location["rooms"] = rooms
                    location.pop("activities", None)
                if image_prompt_day is not None:
                    if image_prompt_day != location.get("image_prompt_day", ""):
                        location["prompt_changed"] = True
                    location["image_prompt_day"] = image_prompt_day
                if image_prompt_night is not None:
                    if image_prompt_night != location.get("image_prompt_night", ""):
                        location["prompt_changed"] = True
                    location["image_prompt_night"] = image_prompt_night
                if image_prompt_building is not None:
                    location["image_prompt_building"] = image_prompt_building
                # Location-level semantic fields — only when given.
                if decency is not None:
                    location["decency"] = decency
                if style_hint is not None:
                    location["style_hint"] = style_hint
                if swim_allowed is not None:
                    location["swim_allowed"] = bool(swim_allowed)
                if indoor is not None:
                    location["indoor"] = indoor
                if activity_hint is not None:
                    location["activity_hint"] = activity_hint
                if danger_level is not None:
                    try:
                        location["danger_level"] = max(0, min(5, int(danger_level)))
                    except (TypeError, ValueError):
                        pass
                # Backfill a missing ID
                if not location.get("id"):
                    location["id"] = _generate_location_id()
                upsert_location(location)
                # Only now: whoever stood in a corridor that just vanished is
                # moved onto the ground. The room list is stored FIRST, exactly
                # like the ground migration writes — the character rows are
                # corrected against a list that really lost that corridor, never
                # against one a failed save left untouched.
                if removed_corridors:
                    evict_rooms_to_ground(str(location.get("id") or ""),
                                          removed_corridors)
                return location

        # New location — set prompt_changed for every room that has prompts.
        if rooms is not None:
            for room in rooms:
                if room.get("image_prompt_day") or room.get("image_prompt_night"):
                    room.setdefault("prompt_changed", True)
        # Every location has a ground, including one created after the one-time
        # migration has already run.
        new_rooms = list(rooms or [])
        ensure_ground_room(new_rooms)
        # A brand-new location has no ``map3d`` yet, so it never opts into a
        # ground-floor corridor here; the first write that brings one syncs it.
        ensure_floor_rooms(new_rooms, None)
        new_location = {
            "id": _generate_location_id(),
            "name": name,
            "description": description,
            "rooms": new_rooms,
            "image_prompt_day": image_prompt_day or "",
            "image_prompt_night": image_prompt_night or "",
            "image_prompt_building": image_prompt_building or "",
            "decency": decency or "",
            "style_hint": style_hint or "",
            "swim_allowed": bool(swim_allowed),
            "indoor": indoor or "",
            "activity_hint": activity_hint or "",
        }
        if danger_level is not None:
            try:
                new_location["danger_level"] = max(0, min(5, int(danger_level)))
            except (TypeError, ValueError):
                pass
        if image_prompt_day or image_prompt_night:
            new_location["prompt_changed"] = True
        upsert_location(new_location)
        return new_location


def rename_location(location_id: str, new_name: str) -> Optional[Dict[str, Any]]:
    """Benennt einen Ort um. ID bleibt gleich."""
    with world_write_lock:
        data = _load_world_data()
        locations = data.get("locations", [])

        for location in locations:
            if location.get("id") == location_id:
                location["name"] = new_name
                upsert_location(location)
                return location
        return None


def get_entry_room_id(location: Dict[str, Any]) -> str:
    """The declared entry room of a location — '' when none is declared.

    ``entry_room`` is OPTIONAL (plan-grundflaeche.md § 6): set, it is the
    deliberate exception "here one arrives indoors" and stays the gate one has
    to stand in to leave; empty, arrival lands on the ground room and leaving
    is free. There is no implicit "first room" default any more — that behaved
    like an entry room nobody had authored.

    A declared room that no longer exists counts as not declared.
    """
    if not isinstance(location, dict):
        return ""
    explicit = (location.get("entry_room") or "").strip()
    if not explicit:
        return ""
    for r in (location.get("rooms") or []):
        if isinstance(r, dict) and r.get("id") == explicit:
            return explicit
    return ""


def get_arrival_room_id(location: Dict[str, Any]) -> str:
    """The room a character lands in when it arrives at ``location``.

    The ONE rule for every arrival path (avatar step, journey, scheduler,
    move/set-location skills, admin move): the declared entry room when there
    is one, otherwise the ground — which is a room like any other since the
    ground migration, so nobody arrives roomless. A boundary opening WITH a
    room link answers the question by itself and never gets here.
    """
    return get_entry_room_id(location) or GROUND_ROOM_ID


def _finite_number(value: Any, label: str) -> float:
    """Coerce one metre/angle value and reject everything non-finite.

    Same shape as the guard in ``app/models/terrain.py``: isfinite BEFORE
    any rounding, because every NaN comparison is False and ``round(nan)``
    is still NaN. One NaN reaching the DB poisons the world map for every
    client afterwards — Starlette encodes responses with ``allow_nan=False``,
    so ``GET /play/worldmap`` would 500 until someone edits the DB by hand.
    OverflowError is caught as well: a JSON body may legitimately carry a
    400-digit integer literal, and ``float()`` on that raises it.
    """
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(num):
        raise ValueError(f"{label} must be a finite number")
    return num


def update_location_position(location_id: str, pos_x: Optional[float],
                             pos_z: Optional[float],
                             yaw_deg: Optional[float] = None
                             ) -> Optional[Dict[str, Any]]:
    """Place a location on the free world map (metres) or unplace it.

    ``pos_x``/``pos_z`` in world metres; either being None unplaces the
    location (and resets the rotation — an unplaced location has no
    orientation). ``yaw_deg`` None leaves the stored rotation untouched,
    so moving never silently re-orients.

    Raises ValueError on a non-finite coordinate or angle (the caller turns
    that into a 400) — nothing is written in that case.

    Re-placing takes the occupants along (E2 decision): every character
    standing in this location keeps its place in the location's LOCAL
    frame, so the scene keeps its shape — turning the location turns its
    occupants with it instead of leaving them outside the footprint they
    are recorded in. Unplacing leaves the characters' points untouched.
    """
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                _old_x, _old_z = loc.get("pos_x"), loc.get("pos_z")
                _old_yaw = loc.get("yaw_deg")
                if pos_x is None or pos_z is None:
                    loc.pop("pos_x", None)
                    loc.pop("pos_z", None)
                    loc.pop("yaw_deg", None)
                else:
                    # Validate BOTH values before the first write, so a junk
                    # pos_z cannot leave a half-moved location behind.
                    _px = round(_finite_number(pos_x, "pos_x"), 2)
                    _pz = round(_finite_number(pos_z, "pos_z"), 2)
                    _yaw = (None if yaw_deg is None
                            else round(_finite_number(yaw_deg, "yaw_deg"), 1) % 360.0)
                    loc["pos_x"] = _px
                    loc["pos_z"] = _pz
                    if _yaw is not None:
                        loc["yaw_deg"] = _yaw
                upsert_location(loc)
                # Occupant sync AFTER the position write — local import, like the
                # other character cross-references in this module.
                from app.models.character import _shift_location_occupants
                _shift_location_occupants(
                    location_id,
                    None if _old_x is None else float(_old_x),
                    None if _old_z is None else float(_old_z),
                    None if _old_yaw is None else float(_old_yaw),
                    loc.get("pos_x"), loc.get("pos_z"),
                    loc.get("yaw_deg"))
                return loc
        return None


def cleanup_orphan_backgrounds() -> Dict[str, int]:
    """Remove dead entries from ``background_images`` and the gallery meta
    dicts (``image_types``, ``image_rooms``, ``image_metas``,
    ``image_prompts``).

    "Dead" means: referenced in the DB / meta JSON, but the PNG behind it no
    longer exists on disk (often the aftermath of an unclean image-delete
    round trip or a gallery tidied up by hand).

    Deletes NO files — it only prunes references. Every location is checked
    against its OWN gallery directory (the location id).

    Idempotent. Returns stats.
    """
    with world_write_lock:
        data = _load_world_data()
        locations = data.get("locations", [])
        gallery_root = get_storage_dir() / "world_gallery"

        pruned_bgs = 0
        pruned_meta = 0
        touched_locs = 0
        touched_meta_files = 0

        # DB entries: prune dead background_images references.
        for loc in locations:
            loc_id = loc.get("id") or ""
            if not loc_id:
                continue
            gallery_dir = gallery_root / loc_id
            bgs = loc.get("background_images", [])
            if bgs:
                valid = [img for img in bgs if (gallery_dir / img).exists()]
                if len(valid) != len(bgs):
                    loc["background_images"] = valid
                    pruned_bgs += len(bgs) - len(valid)
                    touched_locs += 1

        if touched_locs:
            upsert_locations(data.get("locations", []))

    # Meta-JSONs: image_types/rooms/metas/prompts pro Owner-Dir.
    if gallery_root.exists():
        import json as _json
        for owner_dir in gallery_root.iterdir():
            if not owner_dir.is_dir():
                continue
            meta_path = owner_dir / "gallery_meta.json"
            prompts_path = owner_dir / "prompts.json"
            existing_pngs = {p.name for p in owner_dir.glob("*.png")} \
                            | {p.name for p in owner_dir.glob("*.jpg")} \
                            | {p.name for p in owner_dir.glob("*.webp")}

            # gallery_meta.json
            if meta_path.exists():
                try:
                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = None
                if isinstance(meta, dict):
                    changed = False
                    for key in ("image_types", "image_rooms", "image_metas"):
                        block = meta.get(key) or {}
                        if not isinstance(block, dict):
                            continue
                        stale = [n for n in block.keys() if n not in existing_pngs]
                        if stale:
                            for n in stale:
                                block.pop(n, None)
                            meta[key] = block
                            pruned_meta += len(stale)
                            changed = True
                    if changed:
                        meta_path.write_text(
                            _json.dumps(meta, indent=2, ensure_ascii=False),
                            encoding="utf-8")
                        touched_meta_files += 1

            # prompts.json
            if prompts_path.exists():
                try:
                    prompts = _json.loads(prompts_path.read_text(encoding="utf-8"))
                except Exception:
                    prompts = None
                if isinstance(prompts, dict):
                    stale = [n for n in prompts.keys() if n not in existing_pngs]
                    if stale:
                        for n in stale:
                            prompts.pop(n, None)
                        prompts_path.write_text(
                            _json.dumps(prompts, indent=2, ensure_ascii=False),
                            encoding="utf-8")
                        pruned_meta += len(stale)
                        touched_meta_files += 1

    logger.info(
        "cleanup_orphan_backgrounds: pruned_bgs=%d (locations=%d), pruned_meta=%d (files=%d)",
        pruned_bgs, touched_locs, pruned_meta, touched_meta_files)
    return {
        "pruned_bgs": pruned_bgs,
        "touched_locations": touched_locs,
        "pruned_meta": pruned_meta,
        "touched_meta_files": touched_meta_files,
    }


def move_orphan_gallery_files() -> Dict[str, int]:
    """Verschiebt Bilder, die NIRGENDS mehr referenziert sind, in einen
    Backup-Ordner.

    "Orphan" heisst: PNG/JPG/WEBP-Datei liegt in ``world_gallery/<owner>/``,
    aber ist weder in der ``background_images``-Liste einer Location noch in
    ``gallery_meta.json`` (image_types / image_rooms / image_metas) noch in
    ``prompts.json``.

    Loescht die Datei NICHT. Verschiebt sie nach
    ``world_gallery_backup/<owner>/<filename>``. Bei Konflikt mit
    existierender Backup-Datei wird ein Timestamp-Suffix angehaengt.

    Sollte NACH ``cleanup_orphan_backgrounds`` laufen — sonst werden
    Files verschoben, deren DB-Eintrag erst danach gepruned wuerde, mit
    falsch wirkender Reihenfolge.

    Returns Stats.
    """
    import json as _json
    import shutil as _shutil
    from datetime import datetime as _dt

    data = _load_world_data()
    locations = data.get("locations", [])
    gallery_root = get_storage_dir() / "world_gallery"
    backup_root = get_storage_dir() / "world_gallery_backup"

    if not gallery_root.exists():
        return {"moved": 0, "owners_touched": 0, "backup_dir": str(backup_root)}

    # Per owner dir: collect the set of every referenced file name.
    referenced: Dict[str, set] = {}
    for loc in locations:
        loc_id = (loc.get("id") or "").strip()
        if not loc_id:
            continue
        bucket = referenced.setdefault(loc_id, set())
        for img in (loc.get("background_images") or []):
            if isinstance(img, str) and img:
                bucket.add(img)

    moved_total = 0
    owners_touched = 0

    for owner_dir in gallery_root.iterdir():
        if not owner_dir.is_dir():
            continue
        owner_id = owner_dir.name

        # Referenzierte Files aus DB + Meta einsammeln.
        refs: set = set(referenced.get(owner_id, set()))

        meta_path = owner_dir / "gallery_meta.json"
        if meta_path.exists():
            try:
                meta = _json.loads(meta_path.read_text(encoding="utf-8")) or {}
                for key in ("image_types", "image_rooms", "image_metas"):
                    block = meta.get(key) or {}
                    if isinstance(block, dict):
                        refs.update(block.keys())
            except Exception:
                pass

        prompts_path = owner_dir / "prompts.json"
        if prompts_path.exists():
            try:
                prompts = _json.loads(prompts_path.read_text(encoding="utf-8")) or {}
                if isinstance(prompts, dict):
                    refs.update(prompts.keys())
            except Exception:
                pass

        # Orphans = Dateien im Dir, die nicht referenziert sind.
        # JSON-Sidecars (gallery_meta.json, prompts.json, etc.) ueberspringen.
        moved_this = 0
        for fp in owner_dir.iterdir():
            if not fp.is_file():
                continue
            if fp.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            if fp.name in refs:
                continue
            # Orphan — verschieben.
            dest_dir = backup_root / owner_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / fp.name
            if dest.exists():
                # Kollision (z.B. wenn cleanup mehrfach laeuft): Suffix
                # mit Zeitstempel anhaengen.
                stem = fp.stem
                ts = _dt.now().strftime("%Y%m%d-%H%M%S")
                dest = dest_dir / f"{stem}__{ts}{fp.suffix}"
            try:
                _shutil.move(str(fp), str(dest))
                moved_this += 1
            except Exception as e:
                logger.warning("Konnte Orphan-Bild nicht verschieben (%s -> %s): %s", fp, dest, e)

        if moved_this:
            moved_total += moved_this
            owners_touched += 1

    logger.info(
        "move_orphan_gallery_files: moved=%d (owners=%d, backup=%s)",
        moved_total, owners_touched, backup_root)
    return {
        "moved": moved_total,
        "owners_touched": owners_touched,
        "backup_dir": str(backup_root),
    }


def delete_location(identifier: str) -> bool:
    """Delete a location by id or name. True when something was removed.

    Deleting the record is only half the job: characters point AT places, and
    a dangling pointer is not inert. A daily-schedule slot naming the deleted
    id used to reach the thought prompt as a raw hex string the character was
    told to be at; a ``known_locations`` entry kept offering it as a travel
    target the engine then refused; a ``home_location`` pointing nowhere sends
    the auto-sleep down its no-path branch every single time. So every
    reference goes with the place — see :func:`purge_location_references`.
    """
    with world_write_lock:
        locations = list_locations()
        target_ids = {loc.get("id") for loc in locations
                      if loc.get("id") == identifier or loc.get("name") == identifier}
        target_ids = {tid for tid in target_ids if tid}
        if not target_ids:
            return False

        # One explicit DELETE per place, never "everything the snapshot does
        # not mention" — a concurrent writer's fresh location is none of this
        # delete's business.
        removed = False
        for tid in target_ids:
            if delete_location_row(tid):
                removed = True
        if removed:
            # AFTER the write: the reference sweep reads the world list to
            # decide what is dangling, so it has to see the place already gone.
            purge_location_references(target_ids)
            return True
        return False


def cleanup_orphan_location_references() -> Dict[str, int]:
    """Sweep character pointers that name places the world does not have.

    The counterpart of :func:`purge_location_references` for what is ALREADY
    dangling: every place deleted before the delete path swept up after
    itself left its id behind in travel knowledge, daily plans and home
    fields. Idempotent by content and cheap when there is nothing to do —
    a read of the pointers, and a write only where one is dead.

    Deliberately blind to WHICH place vanished and when: a pointer is either
    resolvable against the current world or it is not.
    """
    live = {(loc.get("id") or "").strip()
            for loc in list_locations() or []}
    live.discard("")
    if not live:
        # No locations at all — either an empty world or an unreadable list.
        # Purging every pointer against that would be vandalism, not hygiene.
        return {"known": 0, "schedule": 0, "home": 0, "standing": 0}
    dangling: Set[str] = set()
    try:
        from app.models.character import (get_character_config,
                                          get_character_daily_schedule,
                                          get_known_locations,
                                          list_available_characters)
        for name in list_available_characters(include_pooled=True) or []:
            try:
                dangling.update(i for i in (get_known_locations(name) or [])
                                if i and i not in live)
                for slot in (get_character_daily_schedule(name)
                             or {}).get("slots") or []:
                    place = (slot.get("location") or "").strip()
                    if place and place not in live:
                        dangling.add(place)
                home = ((get_character_config(name) or {})
                        .get("home_location") or "").strip()
                if home and home not in live and not home.startswith("__"):
                    # "__offmap__" is a sentinel, not a place — it resolves
                    # to no location on purpose and must survive the sweep.
                    dangling.add(home)
            except Exception as e:
                logger.debug("orphan scan failed for %s: %s", name, e)
    except Exception as e:
        logger.warning("orphan location scan unavailable: %s", e)
        return {"known": 0, "schedule": 0, "home": 0, "standing": 0}
    if not dangling:
        return {"known": 0, "schedule": 0, "home": 0, "standing": 0}
    logger.info("Found %d place id(s) referenced but no longer in the world",
                len(dangling))
    return purge_location_references(dangling)


def purge_location_references(location_ids: Set[str]) -> Dict[str, int]:
    """Drop every character-side pointer to the given (deleted) places.

    Three pointers, all of them silent when they dangle:

    * ``known_locations`` — the travel-target list. A dead id stays offered
      in "Places you can go" while ``start_journey`` refuses it, so the
      character walks into a wall it was shown.
    * ``daily_schedules`` slots — the rhythm hint. The slot's ROLE survives
      the purge (it is still true); only the place is cleared, and a slot
      left with neither place, role nor sleep flag drops out entirely.
    * ``home_location`` / ``home_room`` — where auto-sleep walks to.

    ``current_location`` is deliberately NOT rewritten: where a character
    standing in a deleted place belongs is an authoring decision, so it is
    reported by name and left for an admin.

    Returns a per-kind count of what was touched. Never raises — a failed
    sweep must not take the deletion down with it.
    """
    touched = {"known": 0, "schedule": 0, "home": 0, "standing": 0}
    ids = {i for i in (location_ids or set()) if i}
    if not ids:
        return touched
    try:
        from app.models.character import (
            get_character_config, get_character_daily_schedule,
            get_character_profile, get_known_locations,
            list_available_characters, save_character_config,
            save_character_daily_schedule, set_known_locations)
    except Exception as e:  # pragma: no cover — import-time only
        logger.warning("location reference purge unavailable: %s", e)
        return touched

    for name in list_available_characters(include_pooled=True) or []:
        # --- the travel-target list -------------------------------------
        try:
            known = get_known_locations(name) or []
            keep = [i for i in known if i not in ids]
            if len(keep) != len(known):
                set_known_locations(name, keep)
                touched["known"] += 1
        except Exception as e:
            logger.debug("known_locations purge failed for %s: %s", name, e)

        # --- the daily rhythm -------------------------------------------
        try:
            schedule = get_character_daily_schedule(name) or {}
            slots = schedule.get("slots") or []
            changed = False
            kept_slots = []
            for slot in slots:
                if (slot.get("location") or "").strip() in ids:
                    slot = dict(slot, location="")
                    changed = True
                if (slot.get("location") or slot.get("role")
                        or slot.get("sleep")):
                    kept_slots.append(slot)
                else:
                    changed = True
            if changed:
                schedule["slots"] = kept_slots
                if save_character_daily_schedule(name, schedule):
                    touched["schedule"] += 1
                else:
                    # The template gate refused the write (a temporary NPC
                    # takes its rhythm from its spawn window instead). Its
                    # block is never rendered either, so the stale rows are
                    # unread — worth a line, not a workaround.
                    logger.info(
                        "daily schedule of %s still names a deleted place — "
                        "its template switches 'activity_home_enabled' off, "
                        "so the rows stay and are never read", name)
        except Exception as e:
            logger.debug("daily_schedule purge failed for %s: %s", name, e)

        # --- where auto-sleep walks to ----------------------------------
        try:
            cfg = get_character_config(name) or {}
            if (cfg.get("home_location") or "").strip() in ids:
                save_character_config(name, dict(cfg, home_location="",
                                                 home_room=""))
                touched["home"] += 1
        except Exception as e:
            logger.debug("home_location purge failed for %s: %s", name, e)

        # --- standing in the deleted place: reported, never moved -------
        try:
            here = (get_character_profile(name) or {}).get("current_location")
            if here and here in ids:
                touched["standing"] += 1
                logger.warning(
                    "character %s stood in the deleted place %s — place it "
                    "anew, nothing was moved automatically", name, here)
        except Exception as e:
            logger.debug("standing check failed for %s: %s", name, e)

    if any(touched.values()):
        logger.info(
            "Deleted %d place(s): cleared travel knowledge for %d character(s), "
            "daily plans for %d, home for %d; %d stood there",
            len(ids), touched["known"], touched["schedule"], touched["home"],
            touched["standing"])
    return touched


_TRANSIT_KEYS = ("passable", "template_location_id", "variant_seed")


def migrate_transit_places_once() -> Dict[str, int]:
    """Delete transit places and template copies (plan-rueckbau-2d-karte.md E5).

    A record flagged ``passable`` or carrying ``template_location_id`` is
    deleted together with its gallery directory; ``variant_seed`` (the copy's
    only own number) is stripped from every survivor. Idempotent by content,
    runs at every boot. Characters whose ``current_location`` pointed at a
    deleted id are logged by name — an admin places them anew.
    """
    with world_write_lock:
        return _migrate_transit_places_locked()


def _migrate_transit_places_locked() -> Dict[str, int]:
    """The body of :func:`migrate_transit_places_once`, under the write lock."""
    import shutil
    data = _load_world_data()
    locations = data.get("locations", [])
    # ONE pass, so the count and the effect can never disagree: a flagged
    # record goes onto the victim pile whether or not it has an id. An
    # id-less one is unaddressable garbage — it has no gallery, it never
    # reached a DB row, and leaving it in the list would report a deletion
    # that did not happen.
    victims: List[Dict[str, Any]] = []
    survivors: List[Dict[str, Any]] = []
    for l in locations:
        if bool(l.get("passable")) or (l.get("template_location_id") or "").strip():
            victims.append(l)
        else:
            survivors.append(l)
    victim_ids = {l.get("id") for l in victims if l.get("id")}
    # Name every victim before it goes: a deleted record leaves no trace an
    # admin could read afterwards, so the log is the only record of what the
    # boot threw away.
    for l in victims:
        lid = l.get("id") or ""
        has_gallery = bool(lid) and (get_storage_dir() / "world_gallery" / lid).is_dir()
        logger.warning("transit place deleted: id=%s name=%r gallery=%s",
                       lid or "-", l.get("name") or "",
                       "yes" if has_gallery else "no")
    deleted_galleries = 0
    for vid in victim_ids:
        gdir = get_storage_dir() / "world_gallery" / vid
        if not gdir.is_dir():
            continue
        try:
            shutil.rmtree(gdir)
            deleted_galleries += 1
        except OSError as e:
            # One unreadable directory must never abort the boot — the record
            # still goes, the files stay behind and are named for a human.
            logger.warning("transit gallery %s could not be removed: %s",
                           gdir, e)
    fields_stripped = 0
    for l in survivors:
        for k in _TRANSIT_KEYS:
            if k in l:
                l.pop(k)
                fields_stripped += 1
    if victims or fields_stripped:
        # Explicit deletes for the victims, an upsert for the survivors — the
        # snapshot is never handed over as "this is the whole world".
        for vid in victim_ids:
            delete_location_row(vid)
        if fields_stripped:
            upsert_locations(survivors)
        if victim_ids:
            # The migration deletes places like any other delete does, so it
            # owes the same reference sweep — otherwise it hands the world a
            # fresh set of dangling travel targets and daily-plan slots at
            # every boot it runs.
            purge_location_references(victim_ids)
        logger.info("transit places removed: %d locations, %d galleries, %d fields",
                    len(victims), deleted_galleries, fields_stripped)
    return {"deleted_locations": len(victims),
            "deleted_galleries": deleted_galleries,
            "fields_stripped": fields_stripped}


# === Hintergrundbilder ===

def get_background_path(location_identifier: str, room: str = "",
                        strict_room: bool = False,
                        stable: bool = False) -> Optional[Path]:
    """Returns the path of a background image chosen for location + room.

    Rules:
    - room set AND room has images → one of the room images (day/night preferred)
    - room unset OR room has no images → one of the location images
      (not room-tagged, day/night preferred) — except with ``strict_room=True``
      and except for the ground room (see below)
    - ground room without its own images → the location's EXTERIOR images
      (gallery types "building-<view>"), never the untagged interior default
    - location unset OR location has no images → None

    Day/night comes from the GAME calendar, never from a caller and never
    from the system clock: :meth:`GameTime.is_day` reads the current season's
    sunrise/sunset. This is the only place that decides it for a background
    image, so the picture cannot disagree with the prompt text that asks the
    same calendar.

    Args:
        strict_room: If True and ``room`` is set: NO fallback to the location
            default. Returns None when the room has no dedicated images. Used
            by the regenerate path so that an explicit room change in the
            dialogue does not silently return the same default file (the user
            would never notice the change).
        stable: If True the pick inside a category is deterministic instead of
            random — the same (location, room, time of day) always yields the
            same image. Used by /play, where the displayed image must be
            stable (figure positions are keyed to the file name).
    """
    loc = resolve_location(location_identifier)
    if not loc:
        return None
    loc_id = loc.get("id", "")
    if not loc_id:
        return None

    # New list, or fallback to the old single field
    bg_images = loc.get("background_images", [])
    if not bg_images and loc.get("background_image"):
        bg_images = [loc["background_image"]]

    owner_id = _location_id_of(location_identifier) or loc_id
    gallery_base = get_storage_dir() / "world_gallery" / owner_id

    # Only consider images that exist on disk
    valid = [img for img in bg_images if (gallery_base / img).exists()]

    image_rooms = get_gallery_image_rooms(owner_id) or {}
    image_types = get_gallery_image_types(owner_id) or {}

    # Candidate selection by rule:
    # 1) room set → try the room images
    # 2) no room images / no room → location images (without a room tag)
    candidates: List[str] = []
    if room:
        candidates = [img for img in valid if image_rooms.get(img, "") == room]
        if not candidates and room == GROUND_ROOM_ID:
            # The ground room is the outdoors. The untagged location images are
            # the inside, so it must not fall back to them — it falls back to
            # the location's EXTERIOR renders instead: gallery images of a
            # building VIEW type ("building-front" and its three siblings, the
            # same marker location_model3d.py reads for the 3D building; the
            # bare "building" was migrated away on 2026-09-02). Two details
            # make this its own lookup:
            #   * building renders are deliberately never flagged as background
            #     images (world_ops skips the flag for them), so they are not
            #     in `valid` — they come straight from the gallery type map.
            #   * only LOCATION-level ones count; a room-tagged building image
            #     is that room's model source, an interior cutaway.
            # The pick itself (day/night, stable/random) is the shared tail
            # below — the ground uses the very same mechanism as every room.
            candidates = [img for img, tp in image_types.items()
                          if building_view(tp) and not image_rooms.get(img, "")
                          and (gallery_base / img).exists()]
            if not candidates:
                # No exterior at all: None is the ground's normal state and the
                # caller must tolerate a missing background.
                return None
        elif not candidates and strict_room:
            # Strict mode: the user picked the room deliberately — NO fallback.
            # Used by the regenerate path (see docstring).
            return None
    if not candidates:
        candidates = [img for img in valid if image_rooms.get(img, "") == ""]
    if not candidates:
        return None

    # Pick inside a category: random (default, variety) or deterministic
    # (stable=True, for /play — otherwise the displayed image would jump on
    # every poll and the figure positions keyed to it would jump along).
    def _pick(lst: List[str]) -> str:
        return sorted(lst)[0] if stable else _random.choice(lst)

    # Time of day — the world calendar answers it (season sunrise/sunset).
    time_type = "day" if game_time().is_day() else "night"

    # Prefer the matching day/night image
    timed = [img for img in candidates if image_types.get(img, "") == time_type]
    if timed:
        return gallery_base / _pick(timed)

    # Images without a time-of-day assignment (neutral) are preferred over the
    # one that does not fit the current time.
    untyped = [img for img in candidates if not image_types.get(img, "")]
    if untyped:
        return gallery_base / _pick(untyped)

    return gallery_base / _pick(candidates)


def get_background_file_path(location_identifier: str, file: str) -> Optional[Path]:
    """Pfad zu einem KONKRETEN Hintergrundbild (per Dateiname/bg_id), validiert
    gegen die als Hintergrund markierten Bilder der Location. None, wenn der
    Name nicht zu einem bekannten Hintergrund gehoert oder die Datei fehlt.

    Wird vom /play-Pin verwendet: Frontend kennt den gewaehlten Dateinamen und
    fordert exakt dieses Bild an, damit Figuren-Positionen daran haften."""
    if not (location_identifier and file):
        return None
    loc = resolve_location(location_identifier)
    if not loc:
        return None
    loc_id = loc.get("id", "")
    if not loc_id:
        return None
    bg_images = loc.get("background_images", [])
    if not bg_images and loc.get("background_image"):
        bg_images = [loc["background_image"]]
    match = next((img for img in bg_images if Path(img).name == file or img == file), None)
    if not match:
        return None
    owner_id = _location_id_of(location_identifier) or loc_id
    p = get_storage_dir() / "world_gallery" / owner_id / match
    return p if p.exists() else None


def get_background_images(location_id: str) -> List[str]:
    """Gibt die Liste der als Hintergrund markierten Bilder zurueck."""
    loc = get_location_by_id(location_id)
    if not loc:
        return []
    bg_images = loc.get("background_images", [])
    if not bg_images and loc.get("background_image"):
        bg_images = [loc["background_image"]]
    return bg_images


def toggle_background_image(location_id: str, image_name: str) -> bool:
    """Toggled ob ein Bild als Hintergrund markiert ist.

    Returns True wenn das Bild jetzt markiert ist, False wenn entfernt.
    """
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                bg_images = loc.get("background_images", [])
                # Altes Einzelfeld migrieren
                if "background_image" in loc:
                    old_bg = loc.pop("background_image", "")
                    if old_bg and old_bg not in bg_images:
                        bg_images.append(old_bg)

                if image_name in bg_images:
                    bg_images.remove(image_name)
                    loc["background_images"] = bg_images
                    upsert_location(loc)
                    return False
                else:
                    bg_images.append(image_name)
                    loc["background_images"] = bg_images
                    upsert_location(loc)
                    return True
        return False


def remove_background_image(location_id: str, image_name: str) -> None:
    """Entfernt ein Bild aus der Hintergrund-Liste (z.B. bei Bild-Loeschung)."""
    with world_write_lock:
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                bg_images = loc.get("background_images", [])
                if image_name in bg_images:
                    bg_images.remove(image_name)
                    loc["background_images"] = bg_images
                    upsert_location(loc)


def _location_id_of(location_identifier: str) -> str:
    """The id of the location addressed by id, name or substring, or "".

    The gallery and background lookups take an identifier the caller happens
    to hold; this is the one place that turns it into the id their file paths
    are keyed by.
    """
    loc = resolve_location(location_identifier)
    return (loc or {}).get("id", "") or ""


def get_gallery_dir(location_identifier: str) -> Path:
    """The gallery directory of a location. Accepts id or name; the directory
    is named by the location id."""
    loc_id = _location_id_of(location_identifier)
    if loc_id:
        dir_name = loc_id
    else:
        dir_name = re.sub(r'[^\w\-]', '_', location_identifier)
    return get_storage_dir() / "world_gallery" / dir_name


def list_gallery_images(location_name: str) -> List[str]:
    """Gibt alle Galerie-Bilder eines Ortes zurueck (Dateinamen, neueste zuerst)."""
    gallery_dir = get_gallery_dir(location_name)
    if not gallery_dir.exists():
        return []
    images = sorted(
        [f.name for f in gallery_dir.iterdir() if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')],
        reverse=True
    )
    return images


def save_gallery_prompt(location_name: str, image_name: str, prompt: str):
    """Speichert den Generierungs-Prompt zu einem Galerie-Bild."""
    gallery_dir = get_gallery_dir(location_name)
    prompts_file = gallery_dir / "prompts.json"
    prompts = {}
    if prompts_file.exists():
        try:
            prompts = json.loads(prompts_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    prompts[image_name] = prompt
    gallery_dir.mkdir(parents=True, exist_ok=True)
    prompts_file.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")


def get_all_gallery_prompts(location_name: str) -> Dict[str, str]:
    """Gibt alle gespeicherten Prompts eines Ortes zurueck."""
    gallery_dir = get_gallery_dir(location_name)
    prompts_file = gallery_dir / "prompts.json"
    if prompts_file.exists():
        try:
            return json.loads(prompts_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_gallery_meta(location_name: str) -> dict:
    """Laedt gallery_meta.json (upgraded-Status etc.)."""
    gallery_dir = get_gallery_dir(location_name)
    meta_file = gallery_dir / "gallery_meta.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_gallery_meta(location_name: str, meta: dict):
    """Speichert gallery_meta.json."""
    gallery_dir = get_gallery_dir(location_name)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    meta_file = gallery_dir / "gallery_meta.json"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")



def set_gallery_image_room(location_name: str, image_name: str, room_id: str):
    """Setzt den Raum eines Galerie-Bildes."""
    meta = _load_gallery_meta(location_name)
    rooms = meta.get("rooms", {})
    if room_id:
        rooms[image_name] = room_id
    else:
        rooms.pop(image_name, None)
    meta["rooms"] = rooms
    _save_gallery_meta(location_name, meta)


def find_room_by_gallery_image(image_name: str) -> tuple:
    """Sucht einen Raum/Ort anhand eines Galerie-Bildnamens.

    Iteriert ueber alle world_gallery-Ordner und prueft ob die Datei dort liegt
    und ggf. einem Raum zugeordnet ist.

    Returns: (location_id, room_id) — beides leer wenn nicht gefunden.
    """
    base = get_storage_dir() / "world_gallery"
    if not base.exists() or not image_name:
        return ("", "")
    for loc_dir in base.iterdir():
        if not loc_dir.is_dir():
            continue
        if not (loc_dir / image_name).exists():
            continue
        # Bild gefunden — Raum-Zuordnung aus gallery_meta.json lesen
        meta_file = loc_dir / "gallery_meta.json"
        room_id = ""
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                room_id = (meta.get("rooms") or {}).get(image_name, "")
            except Exception:
                pass
        return (loc_dir.name, room_id)
    return ("", "")


def get_gallery_image_rooms(location_name: str) -> Dict[str, str]:
    """Gibt alle Bild-Raum-Zuordnungen zurueck."""
    meta = _load_gallery_meta(location_name)
    return meta.get("rooms", {})


def remove_gallery_image_room(location_name: str, image_name: str):
    """Entfernt die Raum-Zuordnung eines geloeschten Bildes."""
    meta = _load_gallery_meta(location_name)
    rooms = meta.get("rooms", {})
    if image_name in rooms:
        del rooms[image_name]
        meta["rooms"] = rooms
        _save_gallery_meta(location_name, meta)


# === Image type assignment (day/night/building-<view>) ===

def set_gallery_image_type(location_name: str, image_name: str, image_type: str):
    """Set the type of a gallery image: 'day', 'night', 'building-<view>' or '' (no type)."""
    meta = _load_gallery_meta(location_name)
    types = meta.get("image_types", {})
    if image_type:
        types[image_name] = image_type
    else:
        types.pop(image_name, None)
    meta["image_types"] = types
    _save_gallery_meta(location_name, meta)


def get_gallery_image_types(location_name: str) -> Dict[str, str]:
    """Return all image type assignments: {image_name: 'day'|'night'|'building-<view>'}."""
    meta = _load_gallery_meta(location_name)
    return meta.get("image_types", {})


def remove_gallery_image_type(location_name: str, image_name: str):
    """Removes the type assignment of a deleted image."""
    meta = _load_gallery_meta(location_name)
    types = meta.get("image_types", {})
    if image_name in types:
        del types[image_name]
        meta["image_types"] = types
        _save_gallery_meta(location_name, meta)


def rewrite_building_types(meta: dict) -> bool:
    """Rename the retired bare ``building`` image type to ``building-front``
    IN PLACE (2026-09-02: the location model source got four view types).
    Returns whether anything changed. Pure — the migration below and the
    smoke check call it on a dict."""
    types = meta.get("image_types")
    if not isinstance(types, dict):
        return False
    changed = False
    for name, value in list(types.items()):
        if value == "building":
            types[name] = "building-front"
            changed = True
    return changed


def migrate_building_image_type_once() -> Dict[str, int]:
    """Walk every gallery's ``gallery_meta.json`` and rename the bare
    ``building`` image type to ``building-front``. Idempotent by construction
    (a migrated file holds no ``building`` value any more), so it needs no
    marker; touches only files that change. Returns ``{galleries, images}``
    counts for the boot log, ``{}`` when nothing changed."""
    root = get_storage_dir() / "world_gallery"
    if not root.is_dir():
        return {}
    galleries = images = 0
    for meta_file in root.glob("*/gallery_meta.json"):
        # Read, count, rewrite and write under ONE guard: a gallery whose file
        # is corrupt, whose image_types is not a dict, or that cannot be
        # written is skipped — it must never strand the galleries after it.
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            types = meta.get("image_types")
            renamed = (sum(1 for v in types.values() if v == "building")
                       if isinstance(types, dict) else 0)
            if not rewrite_building_types(meta):
                continue
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception as exc:
            logger.warning("building image-type migration skipped %s: %s",
                           meta_file, exc)
            continue
        galleries += 1
        images += renamed
    return {"galleries": galleries, "images": images} if galleries else {}


_MAP_ICON_KEYS = ("map_image", "map_image_2d", "map_rotation_2d",
                  "image_prompt_map_2d", "image_prompt_map")
_MAP_ICON_TYPES = ("map", "map_2d")


def _drop_gallery_prompt(gallery_dir: Path, image_name: str) -> None:
    """Remove one image's entry from a gallery's ``prompts.json``.

    Does nothing when the file is missing or unreadable — a prompt sidecar is
    a convenience, never the source of truth."""
    prompts_file = gallery_dir / "prompts.json"
    if not prompts_file.exists():
        return
    try:
        prompts = json.loads(prompts_file.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(prompts, dict) or image_name not in prompts:
        return
    prompts.pop(image_name, None)
    prompts_file.write_text(json.dumps(prompts, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def migrate_map_images_once() -> Dict[str, int]:
    """Delete the map-icon era from a world (plan-rueckbau-2d-karte.md E3).

    Every gallery image typed ``map`` (isometric) or ``map_2d`` (flat icon)
    is deleted from disk, from the ``gallery_meta.json`` sections
    ``image_types``, ``image_metas`` and ``rooms``, from the sibling
    ``prompts.json`` and from the location's background list; the five
    map-icon keys are stripped from every location record. Idempotent by
    content: a world that carries nothing of it reports zeros. Runs at
    every boot — an old content ZIP may re-import the keys, and this is the
    one place that removes them again.
    """
    images_deleted = 0
    fields_stripped = 0
    with world_write_lock:
        data = _load_world_data()
        changed = False
        for loc in data.get("locations", []):
            for k in _MAP_ICON_KEYS:
                if k in loc:
                    loc.pop(k)
                    fields_stripped += 1
                    changed = True
            lid = loc.get("id") or ""
            if not lid:
                continue
            # The cheap file check comes first: _load_gallery_meta resolves the id
            # through a full world load, so a location without a gallery must not
            # pay for one.
            if not (get_storage_dir() / "world_gallery" / lid / "gallery_meta.json").exists():
                continue
            meta = _load_gallery_meta(lid)
            types = meta.get("image_types") or {}
            victims = [fn for fn, t in types.items() if t in _MAP_ICON_TYPES]
            if not victims:
                continue
            gdir = get_gallery_dir(lid)
            for fn in victims:
                p = gdir / fn
                if p.exists():
                    p.unlink()
                types.pop(fn, None)
                for section in ("image_metas", "rooms"):
                    if isinstance(meta.get(section), dict):
                        meta[section].pop(fn, None)
                _drop_gallery_prompt(gdir, fn)
                if fn in (loc.get("background_images") or []):
                    loc["background_images"].remove(fn)
                    changed = True
                images_deleted += 1
            meta["image_types"] = types
            _save_gallery_meta(lid, meta)
        if changed:
            upsert_locations(data.get("locations", []))
    if images_deleted or fields_stripped:
        logger.info("map icons removed: %d images, %d fields",
                    images_deleted, fields_stripped)
    return {"images_deleted": images_deleted, "fields_stripped": fields_stripped}


def set_gallery_image_meta(location_name: str, image_name: str, meta_info: dict):
    """Speichert Erzeugungs-Metadaten (Backend, Model etc.) fuer ein Galerie-Bild."""
    meta = _load_gallery_meta(location_name)
    image_metas = meta.get("image_metas", {})
    image_metas[image_name] = meta_info
    meta["image_metas"] = image_metas
    _save_gallery_meta(location_name, meta)


def get_gallery_image_metas(location_name: str) -> Dict[str, dict]:
    """Gibt alle Bild-Metadaten zurueck: {image_name: {backend: ..., model: ...}}."""
    meta = _load_gallery_meta(location_name)
    return meta.get("image_metas", {})


def move_gallery_image(src_location: str, target_location: str, image_name: str) -> Optional[str]:
    """Verschiebt ein Galerie-Bild von einer Location in eine andere.

    Die Datei wandert in die Ziel-Galerie (Owner-aufgeloest); Prompt, Typ und
    Erzeugungs-Metadaten werden uebertragen. Raum-Zuordnung + Hintergrund-Flag
    der Quelle werden geloescht (gelten nur dort). Rueckgabe: der (ggf.
    kollisionssicher umbenannte) Ziel-Dateiname, sonst None.
    """
    import shutil
    if not image_name or "/" in image_name or ".." in image_name:
        return None
    src = resolve_location(src_location)
    target = resolve_location(target_location)
    if not src or not target:
        return None
    src_id = src.get("id", src_location)
    target_id = target.get("id", target_location)
    src_dir = get_gallery_dir(src_id)
    target_dir = get_gallery_dir(target_id)
    src_file = src_dir / image_name
    if not src_file.exists():
        return None

    # Metadaten der Quelle einsammeln (vor dem Verschieben).
    prompt = get_all_gallery_prompts(src_id).get(image_name, "")
    itype = get_gallery_image_types(src_id).get(image_name, "")
    imeta = get_gallery_image_metas(src_id).get(image_name, {})

    # Quell-spezifische Zuordnungen loesen (gelten nur in der Quell-Location).
    remove_background_image(src_id, image_name)
    remove_gallery_image_room(src_id, image_name)

    # Source and target are the same directory -> the file stays put.
    if src_dir.resolve() == target_dir.resolve():
        return image_name

    # Datei kollisionssicher verschieben.
    target_dir.mkdir(parents=True, exist_ok=True)
    new_name = image_name
    if (target_dir / new_name).exists():
        import time as _t
        new_name = f"{Path(image_name).stem}_{int(_t.time())}{Path(image_name).suffix or '.png'}"
    shutil.move(str(src_file), str(target_dir / new_name))

    # Metadaten in die Ziel-Galerie uebertragen.
    if prompt:
        save_gallery_prompt(target_id, new_name, prompt)
    if itype:
        set_gallery_image_type(target_id, new_name, itype)
    if imeta:
        set_gallery_image_meta(target_id, new_name, imeta)

    # Quell-Metadaten aufraeumen (Typ + Prompt + Meta-Eintrag).
    remove_gallery_image_type(src_id, image_name)
    _pf = src_dir / "prompts.json"
    if _pf.exists():
        try:
            _pp = json.loads(_pf.read_text(encoding="utf-8"))
            if _pp.pop(image_name, None) is not None:
                _pf.write_text(json.dumps(_pp, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    _m = _load_gallery_meta(src_id)
    _im = _m.get("image_metas", {})
    if _im.pop(image_name, None) is not None:
        _m["image_metas"] = _im
        _save_gallery_meta(src_id, _m)

    return new_name


# === Room-Migration ===


# === Location-ID Migration ===

def migrate_location_ids():
    """Fuegt persistente IDs zu bestehenden Locations hinzu und migriert Referenzen.

    Wird beim Server-Start aufgerufen. Idempotent: ueberspringt bereits migrierte User.

    Schritte:
    1. Fuer jeden User world.json laden
    2. Locations ohne 'id' bekommen eine neue ID
    3. Filesystem-Pfade umbenennen (backgrounds, gallery)
    4. Alle Referenzen in Character-Profilen, Configs, Scheduler etc. umschreiben
    """
    sd = get_storage_dir()
    if not sd.exists():
        return

    # Single-world: world.json lives directly in storage root
    user_dir = sd
    world_file = sd / "world.json"
    if not world_file.exists():
        return

    try:
        world_data = json.loads(world_file.read_text(encoding="utf-8"))
    except Exception:
        return

    locations = world_data.get("locations", [])
    if not locations:
        return

    changed = False

    # Phase 1: IDs zuweisen (falls noetig)
    name_to_id = {}
    needs_ids = any(not loc.get("id") for loc in locations)
    if needs_ids:
        for loc in locations:
            if not loc.get("id"):
                loc["id"] = _generate_location_id()
            name_to_id[loc["name"]] = loc["id"]
        changed = True

    # Phase 2: Filesystem bereinigen + backgrounds migrieren (IMMER)
    fs_changed = _migrate_filesystem_and_backgrounds(user_dir, locations)
    if fs_changed:
        changed = True

    # world.json speichern wenn geaendert
    if changed:
        world_data["locations"] = locations
        world_file.write_text(
            json.dumps(world_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # Referenzen migrieren (nur bei neuer ID-Zuweisung)
    if needs_ids:
        _migrate_references_to_ids(user_dir, name_to_id)
        logger.info("Location-IDs migriert")


def _migrate_filesystem_and_backgrounds(user_dir: Path, locations: List[Dict]) -> bool:
    """Migriert backgrounds/ nach gallery/ und setzt background_image Referenzen.

    Laeuft bei JEDEM Server-Start fuer ALLE User:
    - Gallery-Ordner: safe_name/ -> id/ umbenennen (falls noch noetig)
    - backgrounds/{id_or_name}.png -> gallery/{id}/ verschieben
    - background_image Referenz in Location setzen
    - Leeres backgrounds/ Verzeichnis aufraemen

    Returns True wenn world.json-Aenderungen vorgenommen wurden.
    """
    import shutil

    world_dir = user_dir / "world"
    if not world_dir.exists():
        return False

    bg_dir = world_dir / "backgrounds"
    gallery_dir = get_storage_dir() / "world_gallery"
    changed = False

    for loc in locations:
        loc_id = loc.get("id", "")
        if not loc_id:
            continue
        loc_name = loc.get("name", "")
        safe_name = re.sub(r'[^\w\-]', '_', loc_name)

        # Gallery: safe_name/ -> id/ umbenennen
        if gallery_dir.exists() and safe_name != loc_id:
            old_gallery = gallery_dir / safe_name
            new_gallery = gallery_dir / loc_id
            if old_gallery.exists() and not new_gallery.exists():
                old_gallery.rename(new_gallery)
                logger.info("Gallery umbenannt: %s/ -> %s/", safe_name, loc_id)

        # Altes Einzelfeld zu Liste migrieren
        if loc.get("background_image") and not loc.get("background_images"):
            loc["background_images"] = [loc.pop("background_image")]
            changed = True
        elif loc.get("background_image") and loc.get("background_images"):
            old_bg = loc.pop("background_image")
            if old_bg not in loc["background_images"]:
                loc["background_images"].append(old_bg)
            changed = True
        elif "background_image" in loc:
            loc.pop("background_image")
            changed = True

        # Ungueltige Eintraege in background_images bereinigen
        if loc.get("background_images"):
            loc_gallery = gallery_dir / loc_id if gallery_dir.exists() else None
            if loc_gallery:
                valid = [img for img in loc["background_images"] if (loc_gallery / img).exists()]
                if len(valid) != len(loc["background_images"]):
                    loc["background_images"] = valid
                    changed = True
            if loc["background_images"]:
                continue

        # backgrounds/{id}.png oder {safe_name}.png -> gallery/{id}/ verschieben
        if bg_dir.exists():
            bg_file = None
            for candidate in [bg_dir / f"{loc_id}.png", bg_dir / f"{safe_name}.png"]:
                if candidate.exists():
                    bg_file = candidate
                    break

            if bg_file:
                loc_gallery = gallery_dir / loc_id
                loc_gallery.mkdir(parents=True, exist_ok=True)
                ts = int(bg_file.stat().st_mtime)
                dest = loc_gallery / f"{ts}.png"
                if not dest.exists():
                    shutil.move(str(bg_file), str(dest))
                    logger.info("Background migriert: %s -> gallery/%s/%s", bg_file.name, loc_id, dest.name)
                else:
                    bg_file.unlink()
                    logger.info("Background entfernt (bereits in Gallery): %s", bg_file.name)
                bg_list = loc.get("background_images", [])
                if dest.name not in bg_list:
                    bg_list.append(dest.name)
                loc["background_images"] = bg_list
                changed = True

        # Keine background_images gesetzt -> neuestes Gallery-Bild nehmen
        if not loc.get("background_images"):
            loc_gallery = gallery_dir / loc_id if gallery_dir.exists() else None
            if loc_gallery and loc_gallery.exists():
                images = sorted(
                    [f.name for f in loc_gallery.iterdir()
                     if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')],
                    reverse=True
                )
                if images:
                    loc["background_images"] = [images[0]]
                    changed = True
                    logger.info("Background-Referenz gesetzt: %s -> %s", loc_name, images[0])

    # backgrounds/ Ordner aufraemen wenn leer
    if bg_dir.exists():
        remaining = [f for f in bg_dir.iterdir()]
        if not remaining:
            bg_dir.rmdir()
            logger.info("Leeres backgrounds/ Verzeichnis entfernt")

    return changed


def _migrate_references_to_ids(user_dir: Path, name_to_id: Dict[str, str]):
    """Migriert alle Location-Name-Referenzen zu IDs in Character-Daten.

    Migriert:
    - character_profile.json: current_location, outfits[].location
    - character_config.json: allowed_locations
    - scheduler/jobs.json: action.location
    - scheduler/daily_schedule.json: slots[].location
    - User-Profile: current_location
    """
    username = user_dir.name

    # Character-Verzeichnisse
    for subdir_name in ("characters", "agents"):
        chars_dir = user_dir / subdir_name
        if not chars_dir.exists():
            continue
        for char_dir in chars_dir.iterdir():
            if not char_dir.is_dir():
                continue
            _migrate_character_refs(char_dir, name_to_id)

    # User-Profile ({username}.json im Storage-Root)
    profile_path = get_storage_dir() / f"{username}.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            changed = False
            cur_loc = profile.get("current_location", "")
            if cur_loc and cur_loc in name_to_id:
                profile["current_location"] = name_to_id[cur_loc]
                changed = True
            if changed:
                profile_path.write_text(
                    json.dumps(profile, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
        except Exception:
            pass


def _migrate_character_refs(char_dir: Path, name_to_id: Dict[str, str]):
    """Migriert Location-Referenzen in einem Character-Verzeichnis."""
    # 1. character_profile.json
    profile_path = char_dir / "character_profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            changed = False

            # current_location
            cur_loc = profile.get("current_location", "")
            if cur_loc and cur_loc in name_to_id:
                profile["current_location"] = name_to_id[cur_loc]
                changed = True

            # outfits[].location
            for outfit in profile.get("outfits", []):
                loc = outfit.get("location", "")
                if loc and loc in name_to_id:
                    outfit["location"] = name_to_id[loc]
                    changed = True

            if changed:
                profile_path.write_text(
                    json.dumps(profile, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
        except Exception:
            pass

    # 2. character_config.json
    config_path = char_dir / "character_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            changed = False

            # allowed_locations
            allowed = config.get("allowed_locations", [])
            if allowed:
                new_allowed = [name_to_id.get(loc, loc) for loc in allowed]
                if new_allowed != allowed:
                    config["allowed_locations"] = new_allowed
                    changed = True

            if changed:
                config_path.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
        except Exception:
            pass

    # 3. scheduler/jobs.json
    jobs_path = char_dir / "scheduler" / "jobs.json"
    if jobs_path.exists():
        try:
            jobs_data = json.loads(jobs_path.read_text(encoding="utf-8"))
            changed = False
            for job in jobs_data.get("jobs", []):
                action = job.get("action", {})
                loc = action.get("location", "")
                if loc and loc in name_to_id:
                    action["location"] = name_to_id[loc]
                    changed = True
            if changed:
                jobs_path.write_text(
                    json.dumps(jobs_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
        except Exception:
            pass

    # 4. scheduler/daily_schedule.json
    schedule_path = char_dir / "scheduler" / "daily_schedule.json"
    if schedule_path.exists():
        try:
            schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            changed = False
            for slot in schedule.get("slots", []):
                loc = slot.get("location", "")
                if loc and loc in name_to_id:
                    slot["location"] = name_to_id[loc]
                    changed = True
            if changed:
                schedule_path.write_text(
                    json.dumps(schedule, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
        except Exception:
            pass
