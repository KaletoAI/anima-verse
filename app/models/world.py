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
from typing import Dict, Any, List, Optional, Set

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("world")

from app.core.paths import get_storage_dir
from app.core.timeutils import utc_now_iso


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


def _load_world_data() -> Dict[str, Any]:
    """Laedt die Weltdaten aus der DB (Locations + ihre Raeume).

    Locations werden als vollstaendige Dicts aus dem meta-Blob geladen.
    Raeume sind eingebettet in locations.meta.rooms.
    Fallback auf world.json wenn DB leer oder fehlerhaft.
    """
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, name, description, pos_x, pos_z, outfit_type, "
            "image_prompt_day, image_prompt_night, image_prompt_map, "
            "visible_when, accessible_when, background_images, meta, "
            "decency, style_hint, swim_allowed, activity_hint, yaw_deg "
            "FROM locations ORDER BY name ASC"
        ).fetchall()
        if rows:
            locations = []
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r[12] or "{}")
                except Exception:
                    pass
                if meta and "id" in meta:
                    # Vollstaendiges Location-Dict aus meta
                    loc = meta
                else:
                    # Reconstruct from columns
                    loc = {
                        "id": r[0],
                        "name": r[1] or "",
                        "description": r[2] or "",
                        "pos_x": r[3],
                        "pos_z": r[4],
                        "yaw_deg": float(r[17] or 0.0),
                        "outfit_type": r[5] or "",
                        "image_prompt_day": r[6] or "",
                        "image_prompt_night": r[7] or "",
                        "image_prompt_map": r[8] or "",
                        "decency": r[13] or "",
                        "style_hint": r[14] or "",
                        "swim_allowed": bool(r[15]),
                        "activity_hint": r[16] or "",
                        "rooms": [],
                    }
                    try:
                        loc["visible_when"] = json.loads(r[9] or "[]")
                    except Exception:
                        loc["visible_when"] = []
                    try:
                        loc["accessible_when"] = json.loads(r[10] or "[]")
                    except Exception:
                        loc["accessible_when"] = []
                    try:
                        loc["background_images"] = json.loads(r[11] or "[]")
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
                        # Column-Fallback: Decency-Felder die im meta-Blob
                        # fehlen aus den Spalten nachziehen (auch wenn Spalte
                        # default-leer ist, damit Default-Werte konsistent
                        # sind: '' statt None, False statt None).
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
                    ("decency",       13, str),
                    ("style_hint",    14, str),
                    ("swim_allowed",  15, bool),
                    ("activity_hint", 16, str),
                    ("yaw_deg",       17, float),
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
        logger.warning("_load_world_data DB-Fehler: %s", e)

    # Fallback: JSON-Datei
    path = _get_world_file()
    if path.exists():
        try:
            with _world_file_lock:
                data = json.loads(path.read_text(encoding="utf-8"))
                if _migrate_room_image_prompts(data):
                    path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    logger.info("Room image_prompt -> image_prompt_day migriert")
            return data
        except Exception:
            pass
    return {"locations": []}


_world_file_lock = threading.Lock()


def _save_world_data(data: Dict[str, Any]):
    """Speichert die Weltdaten in die DB (Locations + Raeume als Upsert)."""
    now = utc_now_iso()
    locations = data.get("locations", [])
    try:
        with transaction() as conn:
            existing_loc_ids = {r[0] for r in conn.execute(
                "SELECT id FROM locations"
            ).fetchall()}
            new_loc_ids = {loc.get("id") for loc in locations if loc.get("id")}

            for lid in existing_loc_ids - new_loc_ids:
                conn.execute("DELETE FROM locations WHERE id=?", (lid,))

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
                         image_prompt_day, image_prompt_night, image_prompt_map,
                         visible_when, accessible_when, background_images, meta,
                         decency, style_hint, swim_allowed, activity_hint,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        pos_x=excluded.pos_x,
                        pos_z=excluded.pos_z,
                        yaw_deg=excluded.yaw_deg,
                        outfit_type=excluded.outfit_type,
                        image_prompt_day=excluded.image_prompt_day,
                        image_prompt_night=excluded.image_prompt_night,
                        image_prompt_map=excluded.image_prompt_map,
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
                    loc.get("image_prompt_map", ""),
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
    except Exception as e:
        logger.error("_save_world_data DB-Fehler: %s", e)


# === Welt-Settings (world_kv) ===

def get_world_setting(key: str, default: str = "") -> str:
    """Liest einen Welt-Setting-Wert aus world_kv.

    Konvention: Keys sind ``world.<feld>``, z.B. ``world.temperature``,
    ``world.weather``. Werte sind Strings — komplexere Strukturen sind
    selbst zu serialisieren.
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
    """Schreibt einen Welt-Setting-Wert in world_kv."""
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


# Erlaubte Werte fuer Welt-Wetter / Temperatur — reine LLM-Hinweise,
# keine Compliance-Logik. Siehe plan-outfit-system-rethink.md §1.2.
WORLD_TEMPERATURE_VALUES = ("freezing", "cold", "mild", "hot")
WORLD_WEATHER_VALUES     = ("dry", "rain", "snow")


def get_world_temperature() -> str:
    return get_world_setting("world.temperature", "mild")


def set_world_temperature(value: str) -> None:
    set_world_setting("world.temperature", value)


def get_world_weather() -> str:
    return get_world_setting("world.weather", "dry")


def set_world_weather(value: str) -> None:
    set_world_setting("world.weather", value)


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
    """The location OWNING a room id (templates/originals only — clone records
    store ``rooms: []`` and inherit the template's rooms on merge, so their
    room ids are template-identical). Used by the per-room model routes
    (AV3D-2), where only the owner's store matters. None when unknown."""
    if not room_id:
        return None
    data = _load_world_data()
    for loc in data.get("locations", []):
        if (loc.get("template_location_id") or "").strip():
            continue
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
    """Fuegt einen neuen Raum zu einem Ort hinzu. Gibt den Raum zurueck oder None bei Fehler."""
    # Validierung
    description = _validate_room_description(description)
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            rooms = loc.setdefault("rooms", [])
            # Duplikat-Check (case-insensitive)
            if any(r.get("name", "").lower() == room_name.lower() for r in rooms):
                logger.warning("Raum '%s' existiert bereits in Location %s", room_name, location_id)
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
            _save_world_data(data)
            logger.info("Raum '%s' hinzugefuegt zu Location %s (id=%s)", room_name, location_id, new_room["id"])
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
                    _save_world_data(data)
                    return True
    return False


def append_room_props(location_id: str, room_id: str,
                      placements: List[Dict[str, Any]]) -> bool:
    """Append prop placements to a room's ``layout.props`` (room_furnish
    accept, plan-room-furnish.md stage 4).

    ADDITIVE only — existing placements are never touched. The merged layout
    runs through the normal layout sanitizer, so accepted placements obey the
    exact same whitelist/limits as hand-placed ones. False when the location,
    the room or its layout does not exist.
    """
    if not placements:
        return False
    from app.core.world_ops import _sanitize_room_layout
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") != location_id:
            continue
        for room in loc.get("rooms", []):
            if room.get("id") != room_id:
                continue
            layout = room.get("layout")
            if not isinstance(layout, dict):
                return False
            merged = dict(layout)
            merged["props"] = list(layout.get("props") or []) + list(placements)
            clean = _sanitize_room_layout(merged)
            if not clean:
                return False
            room["layout"] = clean
            _save_world_data(data)
            logger.info("Raum %s: %d Prop-Platzierungen uebernommen",
                        room_id, len(placements))
            return True
    return False


def clear_room_prompt_changed(location_id: str, room_id: str) -> bool:
    """Entfernt das prompt_changed Flag von einem Raum. Returns True bei Erfolg."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            for room in loc.get("rooms", []):
                if room.get("id") == room_id:
                    if room.pop("prompt_changed", None):
                        _save_world_data(data)
                    return True
    return False


def clear_location_prompt_changed(location_id: str) -> bool:
    """Entfernt das prompt_changed Flag von einer Location. Returns True bei Erfolg."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            if loc.pop("prompt_changed", None):
                _save_world_data(data)
            return True
    return False


_CLONE_TEMPLATE_ONLY_KEYS = ("background_images",)


def _resolve_clones(locations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge passable clones with their template.

    A clone stores the bare minimum: id, template_location_id, pos_x, pos_z
    (plus yaw_deg) and optionally a name. On read every remaining field is
    inherited from the template, so template edits apply to all its clones
    automatically. template_location_id stays in the output so the frontend
    can filter clones out of the world tree.
    """
    by_id = {l.get("id"): l for l in locations if l.get("id")}
    resolved: List[Dict[str, Any]] = []
    for loc in locations:
        tmpl_id = (loc.get("template_location_id") or "").strip()
        if not tmpl_id:
            resolved.append(loc)
            continue
        tmpl = by_id.get(tmpl_id)
        if not tmpl:
            # Template geloescht — Klon wird zur Waise; spaeter beim
            # naechsten Save aufraeumen lassen, jetzt aber rendern.
            resolved.append(loc)
            continue
        merged = {**tmpl, **{
            k: v for k, v in loc.items()
            if k in ("id", "pos_x", "pos_z", "yaw_deg", "template_location_id")
            or (k not in _CLONE_TEMPLATE_ONLY_KEYS and v not in (None, "", [], {}))
        }}
        # Forget the template identity, or the clone would take on the
        # template's id. Override with the REAL clone identifier:
        merged["id"] = loc.get("id")
        merged["template_location_id"] = tmpl_id
        # The placement is the clone's OWN — never the template's, or an
        # unplaced clone would silently sit on top of its template.
        merged["pos_x"] = loc.get("pos_x")
        merged["pos_z"] = loc.get("pos_z")
        merged["yaw_deg"] = float(loc.get("yaw_deg") or 0.0)
        # Gallery-related fields ALWAYS come from the template — the gallery
        # path goes through _gallery_owner_id (= template id) anyway, and
        # clones would otherwise keep stale lists when the template gains or
        # loses images.
        for k in _CLONE_TEMPLATE_ONLY_KEYS:
            if k in tmpl:
                merged[k] = tmpl[k]
        resolved.append(merged)
    return resolved


def list_locations() -> List[Dict[str, Any]]:
    """Gibt alle Orte eines Users zurueck (Klone gemerged mit Template)."""
    raw = _load_world_data().get("locations", [])
    return _resolve_clones(raw)


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
                                room: Dict[str, Any]) -> bool:
    """True wenn der Character sowohl das Location- als auch das Raum-
    Wissens-Item hat (beide optional)."""
    if not location_visible_to_character(character_name, location):
        return False
    if not isinstance(room, dict):
        return False
    iid = (room.get("knowledge_item_id") or "").strip()
    if not iid:
        return True
    return _character_has_item(character_name, iid)


def list_locations_for_character(character_name: str) -> List[Dict[str, Any]]:
    """Liefert alle Locations die der Character dank Wissens-Items sehen darf.
    Raeume werden pro Location ebenfalls gefiltert — nur sichtbare bleiben im
    zurueckgelieferten 'rooms'-Array.
    """
    visible = []
    for loc in list_locations():
        if not location_visible_to_character(character_name, loc):
            continue
        rooms = [r for r in (loc.get("rooms") or [])
                 if room_visible_to_character(character_name, loc, r)]
        visible.append({**loc, "rooms": rooms})
    return visible


def get_location_by_id(location_id: str) -> Optional[Dict[str, Any]]:
    """Gibt einen Ort per exakter ID-Suche zurueck."""
    if not location_id:
        return None
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
    that default, here and everywhere else (plan-grundflaeche.md § 3).
    """
    if not (location_id and room_id):
        return ""
    if room_id == GROUND_ROOM_ID:
        return get_ground_name(location_id, lang)
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
    - ``"skip"`` — a CLONE. It stores ``rooms: []`` and inherits its
      template's rooms on read, so its ground comes from the template.
    - ``"present"`` — a room already carries the reserved id. Nothing is
      touched: on a repeated run that is this migration's own room, and when
      an author assigned the id by hand, overwriting would destroy their
      room. Both are the same case here — the caller reports it and moves on.
    """
    if str(location.get("template_location_id") or "").strip():
        return "skip"
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
    the name the location had for it (``previous`` = the stored room list),
    appended LAST so it never displaces an authored room in the editor's
    order — position carries no meaning any more, ``entry_room`` is declared
    or it is not (``get_entry_room_id``).

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
    for r in (previous or []):
        if isinstance(r, dict) and str(r.get("id") or "") == GROUND_ROOM_ID:
            name = str(r.get("name") or "")
            break
    rooms.append({"id": GROUND_ROOM_ID, "name": name,
                  "description": "", "activities": []})


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
            _save_world_data(data)

        # Which locations have a usable ground now — clones included, they
        # inherit it, collisions excluded.
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


# === Exit point -> door opening (plan-betreten-und-tueren.md § 6) ===
# The editor's standard door — OPENING_DEFAULT in
# frontend/src/tabs/world/planGeometry.ts. Change both or neither.
EXIT_DOOR_WIDTH_M = 1.0
EXIT_DOOR_HEIGHT_M = 2.1


def project_exit_to_opening(
        layout: Any,
        plan_width_m: float = 0.0) -> Optional[Dict[str, Any]]:
    """The door a stored ``layout.exit`` becomes — or None.

    A pure function. ``exit`` is a point in fractions of the room RECTANGLE;
    it is clamped into that rectangle, converted to ABSOLUTE plate fractions
    (the frame of x/y/w/d, in which a distance is proportional to real metres
    — the bbox-local frame is not, it stretches u by w and v by d) and
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

    ``plan_width_m`` is the location's scale anchor (``map3d.plan_width_m``);
    without it the recipe's unanchored assumption applies. It decides how wide
    the door is IN PLATE FRACTIONS, hence whether it fits and how far its
    centre is pushed off a corner.
    """
    from app.core.room_recipe import (  # local: keeps world.py import-light
        _UNANCHORED_PLAN_WIDTH_M, _WALKABLE_TYPES, _abs_outline,
        _normalize_opening, _unit_edge)

    if not isinstance(layout, dict):
        return None
    ex = layout.get("exit")
    if not isinstance(ex, (list, tuple)) or len(ex) != 2:
        return None
    try:
        u = min(max(float(ex[0]), 0.0), 1.0)
        v = min(max(float(ex[1]), 0.0), 1.0)
        px = float(layout["x"]) + u * float(layout["w"])
        py = float(layout["y"]) + v * float(layout["d"])
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

    planw = float(plan_width_m or 0) or _UNANCHORED_PLAN_WIDTH_M
    door = EXIT_DOOR_WIDTH_M / planw
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

        data = _load_world_data()
        changed = False
        for loc in data.get("locations", []):
            map3d = loc.get("map3d")
            plan_width_m = 0.0
            if isinstance(map3d, dict):
                try:
                    plan_width_m = float(map3d.get("plan_width_m") or 0)
                except (TypeError, ValueError):
                    plan_width_m = 0.0
            for room in loc.get("rooms") or []:
                if not isinstance(room, dict):
                    continue
                layout = room.get("layout")
                if not isinstance(layout, dict) or layout.get("exit") is None:
                    continue
                counts["rooms"] += 1
                opening = project_exit_to_opening(layout, plan_width_m)
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
            _save_world_data(data)
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
            _save_world_data(data)
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
                  image_prompt_map: str = None,
                  image_prompt_map_2d: str = None,
                  image_prompt_building: str = None,
                  decency: str = None,
                  style_hint: str = None,
                  swim_allowed: bool = None,
                  indoor: str = None,
                  activity_hint: str = None,
                  location_id: str = None) -> Dict[str, Any]:
    """Fuegt einen neuen Ort hinzu oder aktualisiert einen bestehenden.

    Args:
        rooms: Liste von {id, name, description, activities} Objekten
        activities: Legacy — wird ignoriert wenn rooms angegeben
        image_prompt_day: Prompt fuer Hintergrundbild bei Tag (6-18 Uhr)
        image_prompt_night: Prompt fuer Hintergrundbild bei Nacht (18-6 Uhr)
        image_prompt_map: Prompt fuer isometrisches Kartenbild (Legacy)
        image_prompt_map_2d: Prompt fuer flaches 2D-Kartenicon
        image_prompt_building: Prompt fuer die Gebaeude-Aussenansicht
            (Quellbild fuer das 3D-Gebaeudemodell der Location)
        decency/style_hint/swim_allowed/indoor/activity_hint: Location-Level
            Semantik-Felder (nur gesetzt wenn nicht None) — analog zu den
            Feldern die der LocationEditor per PUT schreibt.
        location_id: Wenn gesetzt, wird der zu aktualisierende Ort per ID
            gefunden (eindeutig) statt per Name. NOETIG bei doppelten Namen —
            sonst trifft die Name-Suche den falschen Ort (z.B. einen Klon).
    """
    data = _load_world_data()
    locations = data.get("locations", [])

    # Room-IDs sicherstellen
    if rooms is not None:
        for room in rooms:
            if not room.get("id"):
                room["id"] = _generate_room_id()

    # Suche zum Updaten: per ID wenn gegeben (eindeutig), sonst per Name.
    def _is_target(loc: Dict[str, Any]) -> bool:
        return (loc.get("id") == location_id) if location_id else (loc.get("name") == name)

    for location in locations:
        if _is_target(location):
            location["description"] = description
            # Bei ID-basiertem Update den (ggf. neuen) Namen mitschreiben.
            if location_id and name:
                location["name"] = name
            if rooms is not None:
                # Alte Rooms als Lookup fuer prompt_changed-Vergleich UND
                # Server-State-Erhalt (items, prompt_changed, etc.). Die FE
                # schickt beim Raum-Edit nur die Felder die sie kennt — Items,
                # die separat ueber /inventory/rooms platziert wurden, fehlen
                # in der FE-Liste und wuerden sonst beim Save geloescht.
                old_rooms_by_id = {r["id"]: r for r in location.get("rooms", []) if r.get("id")}
                # Felder die NICHT vom Raum-Editor verwaltet werden — bei
                # Update aus dem Bestand uebernehmen wenn nicht mitgegeben.
                _server_state_fields = ("items",)
                for room in rooms:
                    old_room = old_rooms_by_id.get(room.get("id"))
                    if old_room:
                        # Server-State-Felder erhalten falls FE sie weggelassen hat
                        for fld in _server_state_fields:
                            if fld not in room and fld in old_room:
                                room[fld] = old_room[fld]
                        # Nur prompt_changed setzen wenn sich Prompts tatsaechlich geaendert haben
                        day_changed = room.get("image_prompt_day", "") != old_room.get("image_prompt_day", "")
                        night_changed = room.get("image_prompt_night", "") != old_room.get("image_prompt_night", "")
                        if day_changed or night_changed:
                            room["prompt_changed"] = True
                        else:
                            # Bestehenden prompt_changed-Status beibehalten
                            if old_room.get("prompt_changed"):
                                room["prompt_changed"] = True
                    else:
                        # Neuer Raum — Flag setzen wenn Prompts vorhanden
                        if room.get("image_prompt_day") or room.get("image_prompt_night"):
                            room.setdefault("prompt_changed", True)
                # The ground is not the author's to delete — a submitted list
                # without it gets it back, keeping the name it had.
                ensure_ground_room(rooms, list(old_rooms_by_id.values()))
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
            if image_prompt_map is not None:
                location["image_prompt_map"] = image_prompt_map
            if image_prompt_map_2d is not None:
                location["image_prompt_map_2d"] = image_prompt_map_2d
            if image_prompt_building is not None:
                location["image_prompt_building"] = image_prompt_building
            # Location-Level Semantik-Felder — nur wenn mitgegeben.
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
            # ID nachrüsten falls fehlend
            if not location.get("id"):
                location["id"] = _generate_location_id()
            _save_world_data(data)
            return location

    # Neue Location — prompt_changed fuer alle Rooms mit Prompts setzen
    if rooms is not None:
        for room in rooms:
            if room.get("image_prompt_day") or room.get("image_prompt_night"):
                room.setdefault("prompt_changed", True)
    # Every location has a ground, including one created after the one-time
    # migration has already run.
    new_rooms = list(rooms or [])
    ensure_ground_room(new_rooms)
    new_location = {
        "id": _generate_location_id(),
        "name": name,
        "description": description,
        "rooms": new_rooms,
        "image_prompt_day": image_prompt_day or "",
        "image_prompt_night": image_prompt_night or "",
        "image_prompt_map": image_prompt_map or "",
        "image_prompt_map_2d": image_prompt_map_2d or "",
        "image_prompt_building": image_prompt_building or "",
        "decency": decency or "",
        "style_hint": style_hint or "",
        "swim_allowed": bool(swim_allowed),
        "indoor": indoor or "",
        "activity_hint": activity_hint or "",
    }
    if image_prompt_day or image_prompt_night:
        new_location["prompt_changed"] = True
    locations.append(new_location)
    data["locations"] = locations
    _save_world_data(data)
    return new_location


def rename_location(location_id: str, new_name: str) -> Optional[Dict[str, Any]]:
    """Benennt einen Ort um. ID bleibt gleich."""
    data = _load_world_data()
    locations = data.get("locations", [])

    for location in locations:
        if location.get("id") == location_id:
            location["name"] = new_name
            _save_world_data(data)
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
            _save_world_data(data)
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


def set_location_map_image(location_id: str, field: str, filename: str) -> Optional[Dict[str, Any]]:
    """Set the per-cell map image of a location/clone.

    ``field`` is ``map_image`` (iso) or ``map_image_2d`` (flat), ``filename``
    the gallery file name (empty = remove the choice → first-match fallback).
    Written directly on the (possibly thin clone) dict, so it survives the
    clone merge."""
    if field not in ("map_image", "map_image_2d"):
        return None
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            if filename:
                loc[field] = filename
            else:
                loc.pop(field, None)
            _save_world_data(data)
            return loc
    return None


def first_map_image(owner_id: str, image_type: str = "map_2d") -> str:
    """Erste Galerie-Datei des angegebenen Map-Typs eines Galerie-Owners.

    Gleiche Reihenfolge wie der Lese-Fallback in ``routes/world.py`` (Typ-Dict).
    Leerer String, wenn der Owner kein Bild dieses Typs hat."""
    if not owner_id:
        return ""
    gallery_dir = get_gallery_dir(owner_id)
    for fn, tp in (get_gallery_image_types(owner_id) or {}).items():
        if tp == image_type and (gallery_dir / fn).exists():
            return fn
    return ""


def clear_map_image_references(image_name: str) -> int:
    """Remove dangling ``map_image``/``map_image_2d`` pointers to a (deleted)
    gallery image from ALL locations/clones — otherwise the cell shows the
    first tile instead of the chosen one. Returns the number of cleaned
    pointers."""
    if not image_name:
        return 0
    data = _load_world_data()
    locations = data.get("locations", [])
    n = 0
    for loc in locations:
        for field in ("map_image", "map_image_2d"):
            if loc.get(field) == image_name:
                loc.pop(field, None)
                n += 1
    if n:
        _save_world_data(data)
    return n


def set_location_map_rotation(location_id: str, rotation: int) -> Optional[Dict[str, Any]]:
    """Setzt die 90°-Drehung des 2D-Karten-Icons eines Ortes/Klons.

    ``rotation`` in {0, 90, 180, 270}; 0 entfernt das Feld (keine Drehung). Wird
    nur als Anzeige-Transform genutzt (CSS rotate) — das Bild bleibt unveraendert.
    Direkt auf dem (Klon-)Dict gesetzt, ueberlebt den Clone-Merge."""
    rot = int(rotation) % 360
    if rot not in (0, 90, 180, 270):
        return None
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            if rot:
                loc["map_rotation_2d"] = rot
            else:
                loc.pop("map_rotation_2d", None)
            _save_world_data(data)
            return loc
    return None


def cleanup_orphan_backgrounds() -> Dict[str, int]:
    """Entfernt tote Eintraege aus ``background_images`` und den Galerie-
    Meta-Dicts (``image_types``, ``image_rooms``, ``image_metas``,
    ``image_prompts``).

    "Tot" heisst: in der DB / Meta-JSON referenziert, aber die zugehoerige
    PNG existiert nicht mehr auf der Disk (oft Folge von:
    Bild-Loesch-Round-Trip nicht sauber, Klon teilt Galerie mit Template
    und der eine sah eine Datei die der andere schon weg hat, alte
    Galerien manuell aufgeraeumt, etc.).

    Loescht KEINE Dateien — pruned nur Referenzen.

    Klon-Hinweis: Klone teilen die Galerie mit ihrem Template
    (``_gallery_owner_id``). Wir pruefen pro Location gegen den
    jeweiligen Owner-Dir. Da Klone ihre ``background_images``-Liste seit
    dem letzten Refactor ohnehin vom Template erben, raeumen wir hier
    primaer Template-Daten auf.

    Idempotent. Returns Stats.
    """
    data = _load_world_data()
    locations = data.get("locations", [])
    gallery_root = get_storage_dir() / "world_gallery"

    pruned_bgs = 0
    pruned_meta = 0
    touched_locs = 0
    touched_meta_files = 0

    # DB-Eintraege: background_images + tote map_image/map_image_2d-Wahl pruunen.
    pruned_mapchoice = 0
    for loc in locations:
        loc_id = loc.get("id") or ""
        if not loc_id:
            continue
        owner_id = (loc.get("template_location_id") or "").strip() or loc_id
        gallery_dir = gallery_root / owner_id
        bgs = loc.get("background_images", [])
        if bgs:
            valid = [img for img in bgs if (gallery_dir / img).exists()]
            if len(valid) != len(bgs):
                loc["background_images"] = valid
                pruned_bgs += len(bgs) - len(valid)
                touched_locs += 1
        # Remove a dangling tile choice (pointing at a deleted file) —
        # otherwise the cell shows the first instead of the chosen tile.
        for field in ("map_image", "map_image_2d"):
            choice = (loc.get(field) or "").strip()
            if choice and not (gallery_dir / choice).exists():
                loc.pop(field, None)
                pruned_mapchoice += 1
                touched_locs += 1

    if touched_locs:
        _save_world_data(data)

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
        "cleanup_orphan_backgrounds: pruned_bgs=%d (locations=%d), pruned_meta=%d (files=%d), pruned_mapchoice=%d",
        pruned_bgs, touched_locs, pruned_meta, touched_meta_files, pruned_mapchoice)
    return {
        "pruned_bgs": pruned_bgs,
        "touched_locations": touched_locs,
        "pruned_meta": pruned_meta,
        "touched_meta_files": touched_meta_files,
        "pruned_mapchoice": pruned_mapchoice,
    }


def move_orphan_gallery_files() -> Dict[str, int]:
    """Verschiebt Bilder, die NIRGENDS mehr referenziert sind, in einen
    Backup-Ordner.

    "Orphan" heisst: PNG/JPG/WEBP-Datei liegt in ``world_gallery/<owner>/``,
    aber ist weder in der ``background_images``-Liste einer Location
    (Template oder Klon) noch in ``gallery_meta.json`` (image_types /
    image_rooms / image_metas) noch in ``prompts.json``.

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

    # Pro Owner-Dir: Set aller referenzierten Dateinamen sammeln.
    # Klone teilen die Galerie mit ihrem Template — alle Klon-bg-Listen
    # gelten als Referenz fuer die Template-Owner-ID.
    referenced: Dict[str, set] = {}
    for loc in locations:
        loc_id = (loc.get("id") or "").strip()
        if not loc_id:
            continue
        owner_id = (loc.get("template_location_id") or "").strip() or loc_id
        bucket = referenced.setdefault(owner_id, set())
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


def cleanup_orphan_clones() -> Dict[str, int]:
    """Clean up clone records:

    - Clones without a position (off-map) -> delete.
    - Clones with a non-existent template_location_id -> delete.
    - Several clones of the same template on the exact same spot -> keep only
      the first, delete the rest.

    Idempotent. Returns a stats dict.
    """
    data = _load_world_data()
    locations = data.get("locations", [])
    existing_ids = {l.get("id") for l in locations if l.get("id")}

    delete_ids: set = set()
    seen_spots: set = set()  # (template_id, pos_x, pos_z)

    # First pass: mark off-map clones and orphans
    for loc in locations:
        tid = (loc.get("template_location_id") or "").strip()
        if not tid:
            continue
        # Orphan: the template no longer exists
        if tid not in existing_ids:
            delete_ids.add(loc.get("id"))
            continue
        # Off-map: no metre position. A clone that still carries the legacy
        # grid keys predates the metre model (no data was migrated, by
        # decision) — it is stale, not off-map, and boot must never delete
        # it. Only clones born on the metre model are cleaned up here.
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            if "grid_x" in loc or "grid_y" in loc:
                continue
            delete_ids.add(loc.get("id"))
            continue

    # Second pass: duplicates per (template, position). Unplaced survivors of
    # the first pass (legacy grid clones) share the spot key (None, None) —
    # they are not duplicates of each other and stay out of this.
    for loc in locations:
        tid = (loc.get("template_location_id") or "").strip()
        if not tid or loc.get("id") in delete_ids:
            continue
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            continue
        spot = (tid, loc.get("pos_x"), loc.get("pos_z"))
        if spot in seen_spots:
            delete_ids.add(loc.get("id"))
        else:
            seen_spots.add(spot)

    if not delete_ids:
        return {"removed": 0, "off_map": 0, "duplicates": 0,
                "orphan_template": 0, "kept": len(locations)}

    new_locations = [l for l in locations if l.get("id") not in delete_ids]
    data["locations"] = new_locations
    _save_world_data(data)

    # Break the removals down by reason
    off_map = duplicates = orphan = 0
    for loc in locations:
        if loc.get("id") not in delete_ids:
            continue
        tid = (loc.get("template_location_id") or "").strip()
        if tid not in existing_ids:
            orphan += 1
        elif loc.get("pos_x") is None or loc.get("pos_z") is None:
            off_map += 1
        else:
            duplicates += 1

    logger.info("cleanup_orphan_clones: removed=%d (off_map=%d, duplicates=%d, orphan=%d)",
                len(delete_ids), off_map, duplicates, orphan)
    return {"removed": len(delete_ids),
            "off_map": off_map,
            "duplicates": duplicates,
            "orphan_template": orphan,
            "kept": len(new_locations)}


def clone_location(template_id: str, pos_x: float,
                   pos_z: float) -> Optional[Dict[str, Any]]:
    """Create a new clone instance of a (passable) template at a metre position.

    A clone stores the bare minimum: id, template_location_id, pos_x, pos_z
    plus its own ``variant_seed``. Every other field is merged in from the
    template at read time.
    Returns the resolved dict of the clone, or None when there is no such
    template. Raises ValueError on a non-numeric/non-finite position — a
    clone dropped at NaN would poison every later worldmap response.
    """
    if not template_id:
        return None
    # Guard: clones without a valid position never reach the DB.
    px = round(_finite_number(pos_x, "pos_x"), 2)
    pz = round(_finite_number(pos_z, "pos_z"), 2)
    data = _load_world_data()
    template = None
    for loc in data.get("locations", []):
        if loc.get("id") == template_id:
            template = loc
            break
    if not template:
        return None
    # Avoid duplicate clones of the same template at the very same spot — the
    # first clone wins, a second drop on the identical position is discarded.
    for loc in data.get("locations", []):
        if (loc.get("template_location_id") or "") == template_id \
                and loc.get("pos_x") == px and loc.get("pos_z") == pz:
            logger.info("clone_location: existing clone at (%.2f,%.2f) for "
                        "template %s, no new entry", px, pz, template_id)
            return loc
    new_id = _generate_location_id()
    clone = {
        "id": new_id,
        "template_location_id": template_id,
        "pos_x": px,
        "pos_z": pz,
        "rooms": [],
        # The one number this copy owns. Every seed it inherits from the
        # template (prop scattering, ground relief) is mixed with it, so two
        # copies of one template stop looking identical. Drawn once, here:
        # it is stored, never re-drawn, so the copy keeps its look. Never 0 —
        # that value is reserved for "no variant", which is what every
        # location predating this carries.
        "variant_seed": _random.randint(1, 0xFFFFFFFF),
    }
    # No "auto" mode: assign the template's first map image right away (if
    # there is one) — otherwise generation sets it later.
    _fm = first_map_image(template_id, "map_2d")
    if _fm:
        clone["map_image_2d"] = _fm
    data["locations"].append(clone)
    _save_world_data(data)
    # Return it resolved — the frontend gets the merge-ready instance.
    for loc in _resolve_clones(data["locations"]):
        if loc.get("id") == new_id:
            return loc
    return clone


def delete_location(identifier: str) -> bool:
    """Loescht einen Ort per ID oder Name. Wenn ein Template geloescht wird,
    werden alle Klone (Locations mit template_location_id == template_id)
    kaskadierend mitentfernt.
    """
    data = _load_world_data()
    locations = data.get("locations", [])
    # Ziel-IDs ermitteln: das Original und ggf. abhaengige Klone
    target_ids = set()
    for loc in locations:
        if loc.get("id") == identifier or loc.get("name") == identifier:
            target_ids.add(loc.get("id"))
    if not target_ids:
        return False
    # Cascade: alle Klone deren template in target_ids ist
    cascade = True
    while cascade:
        cascade = False
        for loc in locations:
            tid = (loc.get("template_location_id") or "").strip()
            lid = loc.get("id")
            if tid and tid in target_ids and lid and lid not in target_ids:
                target_ids.add(lid)
                cascade = True

    new_locations = [loc for loc in locations if loc.get("id") not in target_ids]
    if len(new_locations) < len(locations):
        data["locations"] = new_locations
        _save_world_data(data)
        return True
    return False


# === Hintergrundbilder ===

def get_background_path(location_identifier: str, room: str = "",
                        hour: int = -1, strict_room: bool = False,
                        stable: bool = False) -> Optional[Path]:
    """Returns the path of a background image chosen for location + room.

    Rules:
    - room set AND room has images → one of the room images (day/night preferred)
    - room unset OR room has no images → one of the location images
      (not room-tagged, day/night preferred) — except with ``strict_room=True``
      and except for the ground room (see below)
    - ground room without its own images → the location's EXTERIOR images
      (gallery type "building"), never the untagged interior default
    - location unset OR location has no images → None

    Args:
        hour: Current hour (0-23). -1 = no time-of-day filtering.
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

    # Clones share the template's image material — lookups run over the owner
    # ID (the template ID for clones, the own ID otherwise).
    owner_id = _gallery_owner_id(location_identifier) or loc_id
    gallery_base = get_storage_dir() / "world_gallery" / owner_id

    # Only consider images that exist on disk
    valid = [img for img in bg_images if (gallery_base / img).exists()]

    image_rooms = get_gallery_image_rooms(owner_id) or {}
    image_types = get_gallery_image_types(owner_id) or {}

    def _not_map(img: str) -> bool:
        # Map tiles are never room backgrounds. "map" is the legacy type,
        # "map_2d" the current tile type since the 2.5D→2D consolidation —
        # the missing map_2d filter let tiles end up as chat-image room
        # references (they were also background-flagged by the fit/edge
        # save paths; both fixed, this filter heals existing worlds).
        return image_types.get(img, "") not in ("map", "map_2d")

    # Candidate selection by rule:
    # 1) room set → try the room images
    # 2) no room images / no room → location images (without a room tag)
    candidates: List[str] = []
    if room:
        candidates = [img for img in valid if image_rooms.get(img, "") == room and _not_map(img)]
        if not candidates and room == GROUND_ROOM_ID:
            # The ground room is the outdoors. The untagged location images are
            # the inside, so it must not fall back to them — it falls back to
            # the location's EXTERIOR renders instead: gallery images of type
            # "building", the same marker location_model3d.py reads for the 3D
            # building. Two details make this its own lookup:
            #   * building renders are deliberately never flagged as background
            #     images (world_ops skips the flag for them), so they are not
            #     in `valid` — they come straight from the gallery type map.
            #   * only LOCATION-level ones count; a room-tagged building image
            #     is that room's model source, an interior cutaway.
            # The pick itself (day/night, stable/random) is the shared tail
            # below — the ground uses the very same mechanism as every room.
            candidates = [img for img, tp in image_types.items()
                          if tp == "building" and not image_rooms.get(img, "")
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
        candidates = [img for img in valid if image_rooms.get(img, "") == "" and _not_map(img)]
    if not candidates:
        return None

    # Pick inside a category: random (default, variety) or deterministic
    # (stable=True, for /play — otherwise the displayed image would jump on
    # every poll and the figure positions keyed to it would jump along).
    def _pick(lst: List[str]) -> str:
        return sorted(lst)[0] if stable else _random.choice(lst)

    # Determine the time of day
    time_type = ""
    if 0 <= hour <= 23:
        time_type = "day" if 6 <= hour < 18 else "night"

    # Prefer day/night
    if time_type:
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
    owner_id = _gallery_owner_id(location_identifier) or loc_id
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
                _save_world_data(data)
                return False
            else:
                bg_images.append(image_name)
                loc["background_images"] = bg_images
                _save_world_data(data)
                return True
    return False


def remove_background_image(location_id: str, image_name: str) -> None:
    """Entfernt ein Bild aus der Hintergrund-Liste (z.B. bei Bild-Loeschung)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            bg_images = loc.get("background_images", [])
            if image_name in bg_images:
                bg_images.remove(image_name)
                loc["background_images"] = bg_images
                _save_world_data(data)


def _gallery_owner_id(location_identifier: str) -> str:
    """Liefert die ID, unter der die Galerie-Bilder eines Ortes liegen.

    Fuer Klone (template_location_id gesetzt) gibt sie die Template-ID
    zurueck — Klone teilen sich das Bildmaterial mit ihrem Template.
    Fuer eigenstaendige Locations die eigene ID. Wird von Galerie- und
    Hintergrund-Lookups genutzt.
    """
    loc = resolve_location(location_identifier)
    if not loc:
        return ""
    tmpl_id = (loc.get("template_location_id") or "").strip()
    if tmpl_id:
        return tmpl_id
    return loc.get("id", "") or ""


def get_gallery_dir(location_identifier: str) -> Path:
    """Gibt den Pfad zum Galerie-Verzeichnis eines Ortes zurueck.

    Akzeptiert ID oder Name. Verwendet die Location-ID fuer den Dateipfad
    — Klone werden auf ihre Template-ID umgeleitet, damit alle Klone das
    gleiche Bildmaterial sehen.
    """
    owner_id = _gallery_owner_id(location_identifier)
    if owner_id:
        dir_name = owner_id
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


# === Bild-Typ-Zuordnung (day/night/map) ===

def set_gallery_image_type(location_name: str, image_name: str, image_type: str):
    """Setzt den Typ eines Galerie-Bildes: 'day', 'night', 'map' oder '' (kein Typ)."""
    meta = _load_gallery_meta(location_name)
    types = meta.get("image_types", {})
    if image_type:
        types[image_name] = image_type
    else:
        types.pop(image_name, None)
    meta["image_types"] = types
    _save_gallery_meta(location_name, meta)


def get_gallery_image_types(location_name: str) -> Dict[str, str]:
    """Gibt alle Bild-Typ-Zuordnungen zurueck: {image_name: 'day'|'night'|'map'}."""
    meta = _load_gallery_meta(location_name)
    return meta.get("image_types", {})


def remove_gallery_image_type(location_name: str, image_name: str):
    """Entfernt die Typ-Zuordnung eines geloeschten Bildes."""
    meta = _load_gallery_meta(location_name)
    types = meta.get("image_types", {})
    if image_name in types:
        del types[image_name]
        meta["image_types"] = types
        _save_gallery_meta(location_name, meta)


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

    # Geteilte Galerie (Klone desselben Templates) -> Datei bleibt, nichts zu tun.
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
