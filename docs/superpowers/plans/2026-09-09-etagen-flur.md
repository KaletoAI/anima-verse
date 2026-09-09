# Etagen-Flur Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jede genutzte Etage einer Location bekommt einen automatischen, reservierten Flur-Raum `__floor__<level>`, der wie die Grundfläche ein Raum ohne Geometrie ist — Türen ohne Ziel führen hinein statt die Hülle zu durchbrechen, Clients stellen Figuren an einem Server-Anker auf, und ein Erdgeschoss mit Diele kann eine Haustür auf der Gebäudekontur tragen.

**Architecture:** Gespeicherter Raumeintrag pro Etage nach dem Muster von `__ground__` (`ensure_*` bei jedem Write + Einmal-Migration), Türregel und Flur-Anker im Szenen-Rezept (`app/core/scene_recipe.py`, der einzige Ort für Geometrie), Clients lesen Etage und Anker aus dem Payload (`corridors[]`, `rooms[].level/is_floor`) und leiten nichts her. Phase 3 ergänzt Hüllentüren (`map3d.hull_openings`), die der Konturwand-Builder wie Außentüren schneidet.

**Tech Stack:** Python/FastAPI (`app/`), Jinja-freie Server-Payloads, React/Vite Game-Admin (`frontend/`), Vite/Three 3D-Client (`client3d/`), geteilte Typen in `packages/scene-render`, Smoke-Skripte unter `scripts/` (Python) und `client3d/scripts/smoke_walk_math.mjs` (Node).

**Spec:** `docs/superpowers/specs/2026-09-09-etagen-flur-design.md` — die Ist-Befunde stehen in `development_instructions/analyse-etagen-flur.md` (gitignored, lokal lesbar).

## Global Constraints

- Keine `.env`, keine Env-Variablen für Konfiguration; Welt-Daten nur in `world.db` (`save_*` schreibt keine JSON-Spiegel).
- **Nie SQL gegen `worlds/<w>/world.db` ausführen, während der Server läuft** (SQLite-Locks). Smokes sind rein, ohne Welt.
- Code-Kommentare/Docstrings Englisch; wer eine Datei anfasst, übersetzt deutsche Kommentare darin. Admin-UI-Strings Englisch und über `t()` (React: `useI18n()`; Python: `t(en, lang)` aus `app/core/i18n.py`; Übersetzung in `shared/languages/de.json`).
- Keine Backward-Compat-Shims, keine Alias-Felder. Kein hartkodierter Charakter-Stat. Keine echten Usernamen in Code/Beispielen (`demo` ist okay).
- Zwei Uhren: in Spiel-Logik nie `datetime.now()`/`time.time()`; hier wird keine Zeit gebraucht — nichts davon einführen.
- Geometrie lebt nur in `app/core/scene_recipe.py`; Clients rendern. Befunde numerisch (§ B5a), nie per Screenshot.
- Reservierte Raum-Ids sind Server-Sache: Clients erkennen Flur/Grundfläche an Payload-Flags (`is_ground`, `is_floor`), nie an der Konstante.
- Commits: **immer `git commit -- <pfade>`** (geteilter Arbeitsbaum, nie `git add -A`, nie `--amend`). Commit-Message endet mit
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `development_instructions/` ist gitignored — dort nichts committen.
- Frontend: `npm run lint` und `npm run build` (Repo-Root; baut `static/game_admin/assets/`, die committed werden), 3D-Client `npm run build -w client3d` (sein einziger Type-Check). Python-Smokes mit `./.venv/bin/python scripts/<name>.py`.
- Smoke-Zahlen werden **von Hand aus der Spec hergeleitet und im Docstring begründet**, nie aus der Ausgabe abgeschrieben.
- Der User testet/startet den Server selbst — „Server neu starten" ist kein offener Punkt.

---

## Phase 1 — Server-Kern

### Task 1: Flur-Helfer und `ensure_floor_rooms` in `app/models/world.py`

**Files:**
- Modify: `app/models/world.py` (direkt nach `GROUND_ROOM_ID = "__ground__"`, Zeile ~460, und neben `ensure_ground_room`, Zeile ~1010)
- Create: `scripts/smoke_floor_rooms.py`

**Interfaces:**
- Produces:
  - `FLOOR_ROOM_PREFIX = "__floor__"`
  - `floor_room_id(level: int) -> str` — `"__floor__-1"`, `"__floor__0"`, `"__floor__2"`
  - `floor_room_level(room_id: str) -> Optional[int]` — `None` für jede Nicht-Flur-Id
  - `is_floor_room(room_id: str) -> bool`
  - `floor_levels(rooms: List[dict], map3d: Optional[dict]) -> Set[int]` — Etagen, die einen Flur brauchen
  - `ensure_floor_rooms(rooms: List[dict], map3d: Optional[dict], previous: Optional[List[dict]] = None) -> List[str]` — gleicht in place ab, gibt die **entfernten** Flur-Ids zurück
  - `get_floor_name(level: int, lang: str = "") -> str`
  - `floor_room_display_name(room: dict, lang: str = "") -> str` — Name des Raums oder Standard

- [ ] **Step 1: Smoke-Skript mit den handgeleiteten Erwartungen anlegen (Part 1 + 2)**

```python
#!/usr/bin/env python3
"""Smoke check: every used storey of a location owns a corridor room.

Usage:  ./.venv/bin/python scripts/smoke_floor_rooms.py

Pure functions, no server, no world.db. Every expectation below is derived
BY HAND from docs/superpowers/specs/2026-09-09-etagen-flur-design.md § 2,
never recorded from output.

Part 1 — ids (§ 2.1):
    floor_room_id(-1)  -> "__floor__-1"     the level rides in the id, sign included
    floor_room_id(0)   -> "__floor__0"
    floor_room_level("__floor__-1") -> -1
    floor_room_level("__floor__x")  -> None  not an int, not a corridor
    floor_room_level("__ground__")  -> None  the ground is not a corridor
    is_floor_room("abc12345")       -> False

Part 2 — which storeys get a corridor (§ 2.2, floor_levels):
    rooms: k1 (layout level -1), eg (layout level 0), ground (props only)
      map3d {}                       -> {-1}       storey 0 only on opt-in
      map3d {ground_corridor: true}  -> {-1, 0}    opt-in AND a room on 0
    rooms: only k1 (level -1), map3d {ground_corridor: true}
                                     -> {-1}       opt-in without a room on 0 is nothing
    rooms: eg without layout         -> set()      no layout, no used storey
    the ground's reduced layout (props, no level) never counts as a storey

Part 2b — ensure_floor_rooms is a two-way sync:
    [] with k1                       -> appends {"id": "__floor__-1", "level": -1,
                                        "name": "", "description": "", "activities": []}
                                        and returns [] (nothing removed)
    run twice                        -> second run appends nothing (idempotent)
    previous had __floor__-1 named "Kellerflur" -> the name comes back
    rooms carry __floor__2 but no room on level 2 -> entry removed,
                                        returns ["__floor__2"]
    an authored __floor__-1 (id present, room on -1) -> left untouched

Part 3 — get_floor_name (§ 2.1): English defaults, lang "" = English
    level 0  -> "Hallway"
    level -1 -> "Corridor (basement)"
    level -2 -> "Corridor (basement -2)"
    level 1  -> "Corridor (floor 1)"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import world  # noqa: E402

FAILS = 0


def check(label, actual, expected):
    global FAILS
    ok = actual == expected
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILS += 1


def room(rid, level=None, layout=True, name=""):
    r = {"id": rid, "name": name, "description": "", "activities": []}
    if layout and level is not None:
        r["layout"] = {"level": level, "x": -4, "y": -4, "w": 3, "d": 3}
    return r


def main():
    print("Part 1 — ids")
    check("floor_room_id(-1)", world.floor_room_id(-1), "__floor__-1")
    check("floor_room_id(0)", world.floor_room_id(0), "__floor__0")
    check("level of __floor__-1", world.floor_room_level("__floor__-1"), -1)
    check("level of __floor__x", world.floor_room_level("__floor__x"), None)
    check("level of ground", world.floor_room_level(world.GROUND_ROOM_ID), None)
    check("is_floor_room(abc12345)", world.is_floor_room("abc12345"), False)

    print("Part 2 — floor_levels")
    ground = {"id": world.GROUND_ROOM_ID, "name": "", "layout": {"props": []}}
    rooms = [room("k1", -1), room("eg", 0), ground]
    check("no opt-in", world.floor_levels(rooms, {}), {-1})
    check("opt-in", world.floor_levels(rooms, {"ground_corridor": True}), {-1, 0})
    check("opt-in without room on 0",
          world.floor_levels([room("k1", -1)], {"ground_corridor": True}), {-1})
    check("no layout", world.floor_levels([room("eg", layout=False)], {}), set())

    print("Part 2b — ensure_floor_rooms")
    rs = [room("k1", -1)]
    removed = world.ensure_floor_rooms(rs, {})
    check("appended", [r["id"] for r in rs], ["k1", "__floor__-1"])
    check("entry shape", rs[1], {"id": "__floor__-1", "level": -1, "name": "",
                                 "description": "", "activities": []})
    check("nothing removed", removed, [])
    world.ensure_floor_rooms(rs, {})
    check("idempotent", [r["id"] for r in rs], ["k1", "__floor__-1"])
    rs2 = [room("k1", -1)]
    world.ensure_floor_rooms(rs2, {}, previous=[{"id": "__floor__-1", "name": "Kellerflur"}])
    check("name restored", rs2[1]["name"], "Kellerflur")
    rs3 = [room("k1", -1), {"id": "__floor__2", "level": 2, "name": ""}]
    removed = world.ensure_floor_rooms(rs3, {})
    check("stale corridor removed", [r["id"] for r in rs3], ["k1", "__floor__-1"])
    check("removed ids", removed, ["__floor__2"])
    rs4 = [room("k1", -1), {"id": "__floor__-1", "level": -1, "name": "Mine"}]
    world.ensure_floor_rooms(rs4, {})
    check("present entry untouched", rs4[1]["name"], "Mine")

    print("Part 3 — get_floor_name")
    check("0", world.get_floor_name(0), "Hallway")
    check("-1", world.get_floor_name(-1), "Corridor (basement)")
    check("-2", world.get_floor_name(-2), "Corridor (basement -2)")
    check("1", world.get_floor_name(1), "Corridor (floor 1)")

    print("FAILED" if FAILS else "ALL OK")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke laufen lassen — muss mit `AttributeError: floor_room_id` scheitern**

Run: `./.venv/bin/python scripts/smoke_floor_rooms.py`
Expected: Traceback `AttributeError: module 'app.models.world' has no attribute 'floor_room_id'`

- [ ] **Step 3: Helfer implementieren** (in `app/models/world.py`, direkt unter `GROUND_ROOM_ID`)

```python
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
    return floor_room_level(room_id) is not None


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
    present = {floor_room_level(str(r.get("id") or "")): r
               for r in rooms if isinstance(r, dict) and is_floor_room(str(r.get("id") or ""))}
    removed: List[str] = []
    for lv, entry in list(present.items()):
        if lv not in wanted:
            rooms.remove(entry)
            removed.append(entry["id"])
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
    """Default display name of a storey's corridor (spec § 2.1)."""
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
    name = str((room or {}).get("name") or "").strip()
    if name:
        return name
    lv = floor_room_level(str((room or {}).get("id") or ""))
    return get_floor_name(lv if lv is not None else 0, lang)
```

Außerdem `Set` in den `typing`-Import aufnehmen, falls nicht vorhanden. In `de.json` (Task 4) kommen die Übersetzungen — hier reicht Englisch, weil `t()` ohne Treffer den Quelltext liefert (prüfen: `t("x", "")` gibt `"x"`).

- [ ] **Step 4: Smoke laufen lassen — ALL OK**

Run: `./.venv/bin/python scripts/smoke_floor_rooms.py`
Expected: letzte Zeile `ALL OK`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(world): reserved corridor room per storey — ids, floor_levels, ensure_floor_rooms

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/models/world.py scripts/smoke_floor_rooms.py
```

---

### Task 2: Schreibpfade rufen `ensure_floor_rooms`, Räumung auf die Grundfläche

**Files:**
- Modify: `app/models/world.py` (`add_location`, Zeilen ~1439 und ~1482; neue Funktion `evict_rooms_to_ground`)
- Modify: `app/core/world_ops.py` (die Stelle, an der `_l["map3d"] = _sanitize_map3d(...)` geschrieben wird — `grep -n '"map3d"\] =' app/core/world_ops.py`)
- Modify: `app/core/layout_apply.py` (nach dem Schreiben der Layouts, vor `_save_world_data`)
- Modify: `app/core/content_io.py` (Import: nach dem Remap der Raum-Ids, Zeile ~940)
- Modify: `app/routes/world_dev.py` (Apply-Pfad, der Räume schreibt — `grep -n "ensure_ground_room\|rooms" app/routes/world_dev.py`)

**Interfaces:**
- Consumes: `ensure_floor_rooms`, `floor_room_id` (Task 1)
- Produces: `evict_rooms_to_ground(location_id: str, room_ids: List[str]) -> Dict[str, int]` — setzt `character_state.current_room` und `utterances.room_id` auf `GROUND_ROOM_ID`, gibt `{"characters": n, "utterances": m}` zurück

- [ ] **Step 1: `evict_rooms_to_ground` schreiben** (neben `migrate_ground_rooms_once`, dieselbe `transaction()`-Nutzung)

```python
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
```

- [ ] **Step 2: `add_location` — beide Zweige**

Update-Zweig (direkt nach `ensure_ground_room(rooms, list(old_rooms_by_id.values()))`):

```python
                removed = ensure_floor_rooms(
                    rooms, location.get("map3d"), list(old_rooms_by_id.values()))
                if removed:
                    evict_rooms_to_ground(str(location.get("id") or ""), removed)
```

Neu-Zweig (nach `ensure_ground_room(new_rooms)`): `ensure_floor_rooms(new_rooms, None)` — eine neue Location hat noch kein `map3d`, also nie einen Erdgeschoss-Flur; das holt der nächste Write nach.

- [ ] **Step 3: `world_ops` — wo `map3d` gespeichert wird**, nach der Zuweisung dieselben zwei Zeilen wie im Update-Zweig (`ensure_floor_rooms(_l.setdefault("rooms", []), _l.get("map3d"))`, Eviction bei `removed`). Das ist der Pfad, über den der Opt-in-Schalter (Task 3) wirkt. In `layout_apply.py`, `content_io.py` (Import) und `world_dev.py` analog: `ensure_ground_room` ist dort schon der Anker — direkt danach `ensure_floor_rooms(rooms, loc.get("map3d"))` einfügen. Falls eine der Dateien `ensure_ground_room` nicht ruft, weil sie `add_location` verwendet, ist nichts zu tun (das steht dann als Kommentar an der Stelle).

- [ ] **Step 4: Prüfen, dass alle Location-Writes abgedeckt sind**

Run: `grep -rn "_save_world_data(data)" app/models/world.py app/core/world_ops.py app/core/layout_apply.py app/core/content_io.py app/routes/world_dev.py | wc -l` und für jede Stelle, die `rooms` oder `map3d` einer Location ändert, sicherstellen, dass vorher `ensure_floor_rooms` läuft. Ergebnis als Liste (Datei:Zeile → abgedeckt/irrelevant) im Commit-Body festhalten.

- [ ] **Step 5: Smoke + Import-Check**

Run: `./.venv/bin/python scripts/smoke_floor_rooms.py && ./.venv/bin/python -c "import app.core.world_ops, app.core.layout_apply, app.core.content_io, app.routes.world_dev; print('imports ok')"`
Expected: `ALL OK` und `imports ok`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(world): every location write syncs the corridor rooms, a vanished corridor evicts to the ground

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/models/world.py app/core/world_ops.py app/core/layout_apply.py app/core/content_io.py app/routes/world_dev.py
```

---

### Task 3: Sanitizer — Flur ohne Layout, `ground_corridor`, Entry-Raum, reservierte Id

**Files:**
- Modify: `app/core/world_ops.py`: `_sanitize_rooms_layout` (Zeile ~1850), `_sanitize_map3d` (Zeile ~797), `create_location_with_extras` + der zweite Update-Pfad (Zeilen ~1900–1960 und ~2015–2080, `entry_room`)
- Test: `scripts/smoke_floor_rooms.py` (Part 4)

**Interfaces:**
- Produces: `valid_entry_room(rooms: List[dict], entry_room: str) -> str` (rein, in `app/models/world.py`) — gibt `entry_room` zurück, wenn er ein Raum der Liste ist und kein Flur einer Etage ≠ 0; sonst `""`.

- [ ] **Step 1: Part 4 ins Smoke-Skript** (Docstring ergänzen + Checks)

```
Part 4 — entry room (§ 4): __floor__0 may be the arrival room, no other corridor
    valid_entry_room([eg, __floor__0], "__floor__0")  -> "__floor__0"
    valid_entry_room([k1, __floor__-1], "__floor__-1") -> ""
    valid_entry_room([eg], "zzz")                      -> ""   unknown room
    valid_entry_room([eg], "eg")                       -> "eg"
```

```python
    print("Part 4 — valid_entry_room")
    check("hallway ok", world.valid_entry_room([room("eg", 0), {"id": "__floor__0"}], "__floor__0"), "__floor__0")
    check("basement corridor refused", world.valid_entry_room([room("k1", -1), {"id": "__floor__-1"}], "__floor__-1"), "")
    check("unknown", world.valid_entry_room([room("eg", 0)], "zzz"), "")
    check("plain", world.valid_entry_room([room("eg", 0)], "eg"), "eg")
```

- [ ] **Step 2: Smoke laufen lassen — Part 4 scheitert mit AttributeError**

- [ ] **Step 3: Implementieren**

`app/models/world.py`:

```python
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
```

`app/core/world_ops.py`:

1. `_sanitize_rooms_layout`: vor dem Ground-Zweig

```python
        if is_floor_room(str(room.get("id") or "")):
            # A corridor has no geometry of its own (spec § 2.1): whatever an
            # API call put here is dropped, and logged so the author finds it.
            logger.info("room %s: layout dropped — corridor rooms carry none",
                        room.get("id"))
            room.pop("layout", None)
            continue
```

2. `_sanitize_map3d`: nach dem `style`/`color`-Block

```python
    # Ground-floor corridor opt-in (spec § 2.3): only the explicit True is
    # stored — absent means "the complement of the rooms is the yard".
    if raw.get("ground_corridor") is True:
        out["ground_corridor"] = True
```

3. Beide Stellen `_l["entry_room"] = (entry_room or "").strip()` werden zu `_l["entry_room"] = valid_entry_room(_l.get("rooms") or [], entry_room)`; und in `create_location_with_extras` vor `add_location(...)`: Räume mit einer Flur-Id, die die gespeicherte Location nicht schon hat, werden mit 400 abgelehnt:

```python
    if isinstance(rooms, list):
        stored = get_location_by_id(...)  # die bestehende Location, falls Update — sonst None
        known = {r.get("id") for r in ((stored or {}).get("rooms") or [])}
        for r in rooms:
            rid = str((r or {}).get("id") or "")
            if is_floor_room(rid) and rid not in known:
                raise HTTPException(status_code=400,
                                    detail=f"room id {rid!r} is reserved for the storey corridor")
```

(Wie die bestehende Location im Update-Fall gefunden wird, steht wenige Zeilen weiter unten in derselben Funktion — dieselbe Auflösung verwenden, nicht neu erfinden.)

- [ ] **Step 4: Smoke ALL OK; Import-Check von `app.core.world_ops`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(world): corridor rooms carry no layout, map3d.ground_corridor opt-in, entry room may be the hallway

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/models/world.py app/core/world_ops.py scripts/smoke_floor_rooms.py
```

---

### Task 4: Spieler-Payload `rooms[]` mit `level`/`is_floor`, Namen, i18n, Rezept-Route

**Files:**
- Modify: `app/core/world_ops.py` (`build_avatar_rooms`, Zeile 44–78)
- Modify: `app/models/world.py` (`get_room_name`, Zeile ~915)
- Modify: `app/routes/play.py` (`play_room_recipe`, Zeile ~1571)
- Modify: `shared/languages/de.json`
- Modify: `docs/schnittstellen-3d.md` § A14 (Zeile ~2886: der `rooms[]`-Eintrag)

- [ ] **Step 1: `build_avatar_rooms`**

```python
    for room in ((location.get("rooms") if location else None) or []):
        rid = room.get("id", "") or ""
        name = room.get("name", "") or ""
        floor_lv = floor_room_level(rid)
        if rid == GROUND_ROOM_ID and not name:
            name = get_ground_name(loc_id, lang)
        elif floor_lv is not None and not name:
            name = get_floor_name(floor_lv, lang)
        lay = room.get("layout") if isinstance(room.get("layout"), dict) else None
        if rid == GROUND_ROOM_ID:
            level: Optional[int] = 0
        elif floor_lv is not None:
            level = floor_lv
        elif lay:
            level = int(lay.get("level") or 0)
        else:
            level = None
        enterable, reason = check_access(avatar, loc_id, room_id=rid)
        out.append({"id": rid, "name": name, "is_entry": rid == entry_id,
                    "is_ground": rid == GROUND_ROOM_ID,
                    "is_floor": floor_lv is not None, "level": level,
                    "enterable": enterable, "reason": reason})
```

Docstring um `is_floor`/`level` ergänzen (englisch).

- [ ] **Step 2: `get_room_name`**: nach dem Ground-Zweig

```python
    lv = floor_room_level(room_id)
    if lv is not None:
        loc = get_location_by_id(location_id) or {}
        for room in (loc.get("rooms") or []):
            if str(room.get("id") or "") == room_id:
                return floor_room_display_name(room, lang)
        return get_floor_name(lv, lang)
```

- [ ] **Step 3: `play_room_recipe`**: die 400-Prüfung wird zu `if room_id == GROUND_ROOM_ID or is_floor_room(room_id):` mit Detail `"Reserved rooms (ground, corridors) are not addressable by room id — read them from GET /play/locations/{id}/scene"`.

- [ ] **Step 4: `de.json`** — vier Einträge (alphabetisch einsortieren, Datei ist flach):

```json
    "Hallway": "Diele",
    "Corridor (basement)": "Flur (Keller)",
    "Corridor (basement {n})": "Flur (Keller {n})",
    "Corridor (floor {n})": "Flur ({n}. Stock)",
```

- [ ] **Step 5: § A14 in `docs/schnittstellen-3d.md`**: den Satz `jeder Eintrag {id, name, is_entry, is_ground, enterable, reason}` erweitern zu `{id, name, is_entry, is_ground, is_floor, level, enterable, reason}` mit zwei Sätzen: `is_floor` = der Flur einer Etage (§ A13b), `level` = Etage des Raums (Layout-Level; 0 für die Grundfläche; `null` für einen Raum ohne Layout) — Clients brauchen die Etage eines geometrielosen Raums und leiten sie nicht her.

- [ ] **Step 6: Prüfen**

Run: `./.venv/bin/python -c "import json;json.load(open('shared/languages/de.json'));print('json ok')" && ./.venv/bin/python -c "import app.core.world_ops, app.routes.play; print('ok')" && ./.venv/bin/python scripts/smoke_floor_rooms.py | tail -1`

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(play): rooms[] names the storey and marks corridors, corridor names translate

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/core/world_ops.py app/models/world.py app/routes/play.py shared/languages/de.json docs/schnittstellen-3d.md
```

---

### Task 5: Türregel im Rezept — Tür ohne Ziel führt in den Flur

**Files:**
- Modify: `app/core/scene_recipe.py`: `_doorways` (Zeile ~1485, `_rooms_of` Zeile ~1541) und ihr Aufruf in `compose_scene` (Zeile ~3691)
- Test: `scripts/smoke_floor_rooms.py` (Part 5, über `compose_scene`)

**Interfaces:**
- `_doorways(recipes, storey, default_door_prop_id, floor_levels: Set[int] = frozenset())` — neuer Keyword-Parameter
- `compose_scene` berechnet `corridor_levels = {floor_room_level(r["id"]) for r in location["rooms"] if is_floor_room(r["id"])}` **aus den gespeicherten Räumen** (nicht aus `floor_levels()` — der Raum ist die Wahrheit)

- [ ] **Step 1: Part 5 ins Smoke-Skript** — Fixture und Erwartungen im Docstring:

```
Part 5 — the door rule (§ 3.1), through compose_scene on a hand-built location:
  contour 10 x 10 (corners (-5,-5) (5,-5) (5,5) (-5,5)), storey 3 m
  k1  level -1  x -4 y -4 w 3 d 3   door on edge "S" at 0.5, 0.9 x 2.0, no `to`
  k2  level -1  x  1 y -4 w 3 d 3   door on edge "S" at 0.5, no `to`
  eg  level  0  x -4 y -4 w 4 d 3   door on edge "S" at 0.5, no `to`
  rooms[] also carries __ground__ and __floor__-1 (the server put it there)
    k1 doorway rooms  -> ["k1", "__floor__-1"], outside False   (corridor exists on -1)
    eg doorway rooms  -> ["eg"], outside True                   (no corridor on 0)
    walls on level -1 with "leaf": 0                            (no hull hole downstairs)
    walls on level 0 with "leaf": 1                             (the front door)
    problems: no "no_building_entrance"                         (eg's door is one)
  the same location WITHOUT the __floor__-1 entry:
    k1 doorway outside True, level -1 leaf count 2  (the old behaviour, as a red probe)
```

Der Fixture-Code lehnt sich an `scripts/smoke_scene_recipe.py::fixture` an (Räume mit `layout: {level, x, y, w, d, openings: [{edge: "S", at: 0.5, width_m: 0.9, height_m: 2.0, type: "door"}]}`, `map3d: {outline: [[-5,-5],[5,-5],[5,5],[-5,5]], storey_height_m: 3}`). Wie das Kanten-Feld eines Rechteck-Raums heißt/gezählt wird, dort nachlesen und übernehmen.

```python
def cellar_fixture(with_corridor=True):
    def rm(rid, level, x, y, w, d):
        return {"id": rid, "name": rid, "layout": {
            "level": level, "x": x, "y": y, "w": w, "d": d,
            "openings": [{"edge": "S", "at": 0.5, "width_m": 0.9,
                          "height_m": 2.0, "type": "door"}]}}
    rooms = [rm("k1", -1, -4, -4, 3, 3), rm("k2", -1, 1, -4, 3, 3),
             rm("eg", 0, -4, -4, 4, 3),
             {"id": world.GROUND_ROOM_ID, "name": ""}]
    if with_corridor:
        rooms.append({"id": "__floor__-1", "level": -1, "name": ""})
    return {"id": "loc1", "name": "Cellar house", "rooms": rooms,
            "map3d": {"outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                      "storey_height_m": 3}}
```

Checks: `sc = scene_recipe.compose_scene(cellar_fixture())`, `dw = {d["rooms"][0]: d for d in sc["doorways"]}`, dann die Erwartungen oben; `leaf_count(level) = sum(1 for w in sc["walls"] if w.get("leaf") and w["level"] == level)` — nur Konturwände zählen: Raumwände tragen ein `room_id`-Feld (prüfen, wie `walls[]` Kontur von Raum unterscheidet, und im Docstring festhalten).

- [ ] **Step 2: Smoke laufen lassen — Part 5 FAIL (k1 outside True)**

- [ ] **Step 3: Implementieren**

In `_doorways` Signatur `floor_levels: Set[int] = frozenset()` ergänzen; `_rooms_of`:

```python
    def _rooms_of(room_id: str, to: str, level: int) -> List[str]:
        out = [room_id]
        if to and to.lower() != "outside" and to != GROUND_ROOM_ID \
                and to != room_id:
            out.append(to)
        elif not to and level in floor_levels:
            # A door nobody linked leads into the storey's corridor where
            # there is one (spec § 3.1) — it is a door in a hallway wall, not
            # a hole in the building hull. ``to: "outside"`` stays the
            # explicit exterior door.
            out.append(floor_room_id(level))
        return out
```

Aufruf `_rooms_of(room_id, to, level)` anpassen (das `level` ist dort schon berechnet). In `compose_scene` vor dem `_doorways`-Aufruf:

```python
    from app.models.world import floor_room_level, is_floor_room
    corridor_levels = {floor_room_level(str(r.get("id") or ""))
                       for r in (location.get("rooms") or [])
                       if isinstance(r, dict) and is_floor_room(str(r.get("id") or ""))}
    doorways = _doorways(recipes, storey, default_door_prop_id,
                         floor_levels=corridor_levels)
```

Die Docstrings von `_doorways` (Absatz „outside is decided HERE") um einen Satz ergänzen: „…a single room means no second room's wall meets this gap AND no corridor claims it".

- [ ] **Step 4: Alle Smokes**

Run: `./.venv/bin/python scripts/smoke_floor_rooms.py | tail -1 && ./.venv/bin/python scripts/smoke_scene_recipe.py | tail -1`
Expected: beide `ALL OK` (bzw. die Erfolgszeile des Rezept-Smokes)

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(scene): a door without a target leads into the storey's corridor, not through the hull

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/core/scene_recipe.py scripts/smoke_floor_rooms.py
```

---

### Task 6: Flur-Anker `corridors[]` und Befunde

**Files:**
- Modify: `app/core/scene_recipe.py`: neue Funktionen `_point_segment_distance`, `floor_anchor`, `_corridors`; `compose_scene` (Payload-Block neben `"doorways"`); `_problems` (Zeile ~1751: `rooms`-Filter und neuer Befund)
- Test: `scripts/smoke_floor_rooms.py` (Part 6)
- Modify: `docs/schnittstellen-3d.md` § B1 (Payload-Liste bei `outdoor_rooms`, Zeile ~4727) — `corridors[]` dokumentieren

**Interfaces:**
- `floor_anchor(outline: List[List[float]], hulls: List[List[List[float]]], elevator: Optional[List[float]], pads: List[List[float]]) -> Tuple[Optional[List[float]], bool]` — rein; `(anchor, free)` mit `free=False`, wenn kein freier Rasterpunkt existiert (Anker = Umriss-Mittelpunkt)
- Payload: `"corridors": [{"room_id": str, "level": int, "anchor": [x, z]}]`, sortiert nach `level`
- Befund: `{"kind": "corridor_without_floor", "location_id", "level", "message"}`

- [ ] **Step 1: Part 6 — Handrechnung im Docstring**

```
Part 6 — the corridor anchor (§ 3.2), floor_anchor() is pure:
  outline = the 10 x 10 square, one hull = k1's shell x -4..-1, z -4..-1
  (a) no lift, no pads -> grid rule. Clearance of a candidate = min distance
      to any hull edge or outline edge. Outline clearance >= 3.5 needs
      x, z in [-1.5, 1.5]; in that box the hull distance is
      sqrt((x+1)^2 + (z+1)^2) for x, z > -1, and only (1.5, 1.5) reaches
      3.536 >= 3.5. Every other grid point scores below 3.5 (e.g. (1.0, 1.5)
      -> hull 3.20; (2.0, 2.0) -> outline 3.0). So: anchor [1.5, 1.5], free.
  (b) lift at (3, -3): inside the outline, outside the hull -> [3, -3] (rule 1)
  (c) lift at (-2.5, -2.5): inside the hull -> ignored; pad at (2, 3) -> [2, 3]
  (d) hull = the whole square -> no free point -> centroid [0, 0], free False
  (e) no outline -> (None, False)
Part 6b — corridors[] through compose_scene on cellar_fixture():
  one entry {room_id "__floor__-1", level -1, anchor [-2.0, 2.0]}. Derivation:
  the level -1 hulls are k1 (x -4..-1, z -4..-1) and k2 (x 1..4, z -4..-1).
  Clearance(x, z) = min(outline clearance 5 - max(|x|,|z|), dist to k1,
  dist to k2). For a value v the outline needs |x|, |z| <= 5 - v, and standing
  above the rooms the hull distance is at least z + 1, so v <= z + 1 <= 6 - v,
  i.e. v <= 3. v = 3 is reached exactly on the row z = 2.0 for every x with
  |x| <= 2 (outline 3.0; hull distance is 3.0 vertically over a room and
  sqrt((x∓1)^2 + 9) >= 3 beside one). Between the rooms (|x| < 1, z < -1) the
  hull distance is at most 2 and the rows z = 1.5 / 2.5 score 2.5 or less
  (e.g. (0, 1.5): min(3.5, sqrt(1 + 6.25) = 2.69) = 2.69; (0, 2.5): outline
  2.5). So the maximum 3.0 ties along z = 2.0, x in {-2.0, ..., 2.0}, and the
  tie rule (smallest x, then smallest z) picks [-2.0, 2.0].
  no "corridor_without_floor" problem
Part 6c — a level -1 room filling the square (x -5 y -5 w 10 d 10) plus
  __floor__-1 -> corridors anchor [0, 0] and ONE problem corridor_without_floor
  with level -1.
```

Diese Rechnung ist Teil des Tasks: **die Zahlen im Docstring müssen stimmen** — wer sie beim Implementieren widerlegt, korrigiert die Herleitung und dokumentiert, warum (nicht die Erwartung an die Ausgabe anpassen).

- [ ] **Step 2: Smoke FAIL (AttributeError `floor_anchor`)**

- [ ] **Step 3: Implementieren**

```python
ANCHOR_GRID_M = 0.5


def _point_segment_distance(px: float, pz: float, a: List[float],
                            b: List[float]) -> float:
    ax, az, bx, bz = a[0], a[1], b[0], b[1]
    dx, dz = bx - ax, bz - az
    seg = dx * dx + dz * dz
    t = 0.0 if seg <= 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / seg))
    cx, cz = ax + t * dx, az + t * dz
    return math.hypot(px - cx, pz - cz)


def _ring_clearance(px: float, pz: float, ring: List[List[float]]) -> float:
    return min(_point_segment_distance(px, pz, ring[i], ring[(i + 1) % len(ring)])
               for i in range(len(ring)))


def floor_anchor(outline: List[List[float]],
                 hulls: List[List[List[float]]],
                 elevator: Optional[List[float]],
                 pads: List[List[float]]) -> Tuple[Optional[List[float]], bool]:
    """Where figures of a storey's corridor stand (spec § 3.2). PURE.

    1. the lift's holding point, if inside the outline and in no hull;
    2. else the first stair pad with the same property;
    3. else the ANCHOR_GRID_M raster point inside the outline and outside
       every hull with the largest clearance to any edge — ties fall to the
       smallest x, then the smallest z;
    4. else (rooms fill the storey) the outline's centroid, flagged False.
    Returns (None, False) without an outline.
    """
    if len(outline) < 3:
        return None, False

    def free(x: float, z: float) -> bool:
        return _point_in_polygon(x, z, outline) and not any(
            _point_in_polygon(x, z, h) for h in hulls)

    for cand in ([elevator] if elevator else []) + list(pads):
        if isinstance(cand, (list, tuple)) and len(cand) >= 2 \
                and free(_num(cand[0]), _num(cand[1])):
            return [_r(_num(cand[0])), _r(_num(cand[1]))], True
    xs = [p[0] for p in outline]
    zs = [p[1] for p in outline]
    best: Optional[Tuple[float, float, float]] = None
    x = math.floor(min(xs) / ANCHOR_GRID_M) * ANCHOR_GRID_M
    while x <= max(xs) + 1e-9:
        z = math.floor(min(zs) / ANCHOR_GRID_M) * ANCHOR_GRID_M
        while z <= max(zs) + 1e-9:
            if free(x, z):
                clear = min([_ring_clearance(x, z, outline)]
                            + [_ring_clearance(x, z, h) for h in hulls])
                if best is None or clear > best[0] + 1e-9:
                    best = (clear, x, z)
            z += ANCHOR_GRID_M
        x += ANCHOR_GRID_M
    if best:
        return [_r(best[1]), _r(best[2])], True
    n = len(outline)
    return [_r(sum(xs) / n), _r(sum(zs) / n)], False
```

`_corridors(location, map3d, room_hulls, flights)` in `compose_scene` (nach `room_hulls`/`flights`):

```python
    corridors: List[Dict[str, Any]] = []
    corridor_problems: List[Dict[str, Any]] = []
    lift = (map3d or {}).get("elevator")
    for lv in sorted(corridor_levels):
        outline = _outline_world(map3d, lv)
        pads = [[f["block"]["foot"][0], f["block"]["foot"][2]] for f in flights
                if f["block"]["from_level"] == lv] + \
               [[f["block"]["head"][0], f["block"]["head"][2]] for f in flights
                if f["block"]["to_level"] == lv]
        anchor, free_spot = floor_anchor(outline, room_hulls.get(lv, []),
                                         list(lift) if isinstance(lift, (list, tuple)) and len(lift) == 2 else None,
                                         pads)
        if anchor is None:
            continue
        corridors.append({"room_id": floor_room_id(lv), "level": lv, "anchor": anchor})
        if not free_spot:
            corridor_problems.append({
                "kind": "corridor_without_floor", "location_id": str(location.get("id") or ""),
                "level": lv,
                "message": "The rooms of this storey leave no floor for its corridor: "
                           "figures in the corridor will stand inside a room. Shrink a "
                           "room, or draw the corridor's storey wider."})
```

Achtung Reihenfolge: `flights` wird in `compose_scene` erst später berechnet (Zeile ~3886) — den Flur-Block **nach** `flights` einfügen und `"corridors": corridors` in den Payload aufnehmen; `corridor_problems` an das Ergebnis von `_problems(...)` anhängen. In `_problems` den `rooms`-Filter erweitern: `... and str(r.get("id") or "") != GROUND_ROOM_ID and not is_floor_room(str(r.get("id") or ""))`.

- [ ] **Step 4: Smokes**

Run: `./.venv/bin/python scripts/smoke_floor_rooms.py | tail -1 && ./.venv/bin/python scripts/smoke_scene_recipe.py | tail -1`

- [ ] **Step 5: § B1 dokumentieren**: in der Payload-Aufzählung nach `outdoor_rooms` den Block `corridors: [{room_id, level, anchor: [x, z]}]` mit der Vier-Stufen-Regel (Lift → Treppen-Pad → freiester Rasterpunkt 0,5 m → Mittelpunkt + Befund `corridor_without_floor`) und dem Satz „Clients stellen Flur-Figuren hier auf und führen Lift/Treppe hierher; sie berechnen keinen eigenen Punkt".

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(scene): corridors[] carries a deterministic anchor per storey corridor

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/core/scene_recipe.py scripts/smoke_floor_rooms.py docs/schnittstellen-3d.md
```

---

### Task 7: Einmal-Migration und Boot-Hook

**Files:**
- Modify: `app/models/world.py` (neben `migrate_ground_rooms_once`)
- Modify: `app/server.py` (nach dem Ground-Room-Block, Zeile ~455)
- Test: `scripts/smoke_floor_rooms.py` (Part 7: die reine Zählfunktion)

**Interfaces:**
- `count_corridor_doors(location: dict) -> int` — rein: Türen/Passagen ohne `to` in Layout-Räumen auf Etagen, die laut `floor_levels` einen Flur bekommen
- `migrate_floor_rooms_once() -> Dict[str, int]` — `{"locations": n, "corridors": m, "doors": k}`, world_kv-Marker `migration.floor_rooms_v1`

- [ ] **Step 1: Part 7 Docstring + Check**

```
Part 7 — the migration's door count (count_corridor_doors), what the boot log
  reports per location as "doors that now lead into a corridor":
    cellar_fixture rooms (k1, k2 doors on -1 without `to`; eg on 0) -> 2
    with map3d.ground_corridor true                                 -> 3
    a door with to "outside" on -1                                  -> not counted
    a window on -1                                                  -> not counted
```

- [ ] **Step 2: Implementieren**

```python
def count_corridor_doors(location: Dict[str, Any]) -> int:
    rooms = location.get("rooms") or []
    levels = floor_levels(rooms, location.get("map3d"))
    n = 0
    for r in rooms:
        lay = r.get("layout") if isinstance(r, dict) and isinstance(r.get("layout"), dict) else None
        if not lay or is_floor_room(str(r.get("id") or "")) or r.get("id") == GROUND_ROOM_ID:
            continue
        if int(lay.get("level") or 0) not in levels:
            continue
        for op in lay.get("openings") or []:
            if isinstance(op, dict) and str(op.get("type") or "door").lower() in ("door", "passage") \
                    and not str(op.get("to") or "").strip():
                n += 1
    return n


def migrate_floor_rooms_once() -> Dict[str, int]:
    """One-time, idempotent: give every used storey its corridor room. No
    character moves — nobody stood in a corridor before it existed. Logs per
    location how many doors change meaning (spec § 3.5, decision 2)."""
    counts = {"locations": 0, "corridors": 0, "doors": 0}
    if get_world_setting("migration.floor_rooms_v1", "") == "done":
        return counts
    try:
        data = _load_world_data()
        changed = False
        for loc in data.get("locations", []):
            rooms = loc.setdefault("rooms", [])
            before = len(rooms)
            ensure_floor_rooms(rooms, loc.get("map3d"))
            added = len(rooms) - before
            doors = count_corridor_doors(loc)
            if added or doors:
                logger.info("floor-room migration: location %s (%s): %d corridor(s) "
                            "added, %d door(s) now lead into a corridor",
                            loc.get("id"), loc.get("name", ""), added, doors)
                counts["locations"] += 1
                counts["corridors"] += added
                counts["doors"] += doors
                changed = changed or bool(added)
        if changed:
            _save_world_data(data)
        set_world_setting("migration.floor_rooms_v1", "done")
    except Exception as e:
        logger.warning("floor-room migration failed: %s", e)
    return counts
```

`server.py`: Block nach der Ground-Migration, gleiche Form (`try/except`, `logger.info("Floor-room migration: %s", _fr)` wenn `any(_fr.values())`).

- [ ] **Step 3: Smoke + Import**

Run: `./.venv/bin/python scripts/smoke_floor_rooms.py | tail -1 && ./.venv/bin/python -c "import app.server; print('server imports')"`

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(world): one-time corridor-room migration with a per-location door report at boot

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/models/world.py app/server.py scripts/smoke_floor_rooms.py
```

---

### Task 8: Übrige Server-Verbraucher (Export/Import, World-Dev, describe_room, Regeln)

**Files:**
- Modify: `app/core/content_io.py` (Zeile ~935: `new_id = old_id if old_id == GROUND_ROOM_ID or is_floor_room(old_id) else ...`; Export-Seite Zeile ~776 prüfen, ob dort Räume gefiltert werden)
- Modify: `app/core/layout_apply.py` (Zeile ~289: ein Layout für eine Flur-Id → Warnung `reserved_room` „the corridor of a storey carries no layout" und Eintrag überspringen)
- Modify: `app/routes/world_dev.py` (Zeile ~490: `if room_id == GROUND_ROOM_ID or is_floor_room(room_id): continue`)
- Modify: `app/skills/describe_room_skill.py` (Zeile ~203: Zählung der Custom-Räume ohne Grundfläche und Flure; vor `add_room`: Name gegen `floor_room_display_name` jedes Flur-Raums der Location vergleichen — Treffer → die Beschreibung landet am Flur statt in einem neuen Raum)
- Modify: `app/models/world.py` (`add_room`: der Duplikat-Check vergleicht zusätzlich gegen die Standardnamen der Flur-Räume via `floor_room_display_name`)
- Modify: `app/models/rules.py` (`_names_every_room`, Zeile 436): nur Docstring-Satz ergänzen: „Corridor rooms count like the ground: a location-wide rule has to name them, and the RulesTab lists them."

- [ ] **Step 1: Änderungen umsetzen** (jede ist ein Zweizeiler; die deutschen Kommentare/Docstrings in `add_room` und in `describe_room_skill.py` beim Anfassen ins Englische übersetzen — nur die berührten Funktionen)

- [ ] **Step 2: Prüfen**

Run: `./.venv/bin/python -c "import app.core.content_io, app.core.layout_apply, app.routes.world_dev, app.skills.describe_room_skill, app.models.rules; print('ok')" && ./.venv/bin/python scripts/smoke_floor_rooms.py | tail -1 && ls scripts/smoke_worlddev_fields.py && ./.venv/bin/python scripts/smoke_worlddev_fields.py | tail -1`

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(world): corridor rooms survive export/import and stay out of world-dev, layout apply and describe_room

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/core/content_io.py app/core/layout_apply.py app/routes/world_dev.py app/skills/describe_room_skill.py app/models/world.py app/models/rules.py
```

---

### Task 9: Doku § A13b und Änderungsvermerke

**Files:**
- Modify: `docs/schnittstellen-3d.md`: neuer Abschnitt `### A13b. Der Flur einer Etage ist ein Raum — neu 2026-09-09` direkt nach § A13a (vor `## A14`, Zeile ~2877); Ergänzung in § A6 beim Satz „Die Hülle nimmt ihr Loch von der Tür" (Zeile ~1607); Ergänzung in § B1 Nr. 13 (Boundary-Öffnung/Ankunft: `__floor__0` darf `entry_room` sein)

- [ ] **Step 1: § A13b schreiben** (Deutsch, Stil der Nachbarabschnitte, 30–50 Zeilen): reservierte Id `__floor__<level>`, Server bringt ihn (Einmal-Migration + `ensure_floor_rooms` bei jedem Write), Etagen ≠ 0 automatisch, Etage 0 per `map3d.ground_corridor`, keine Geometrie/kein Layout, Name am Raum mit übersetztem Standard, Türregel (Tür ohne `to` → Flur; `to: "outside"` = Außentür), `corridors[]`-Anker (Verweis § B1), Hörweite/Regeln/Anstand gewöhnlich, `entry_room` nur `__floor__0`, Ids sind Server-Sache (`is_floor`, `level` im Spieler-Payload), Befund `corridor_without_floor`, Migration schreibt je Location die betroffenen Türen ins Boot-Log. Verweis auf die Spec-Datei.

- [ ] **Step 2: § A6-Absatz** um einen Satz ergänzen: „**Seit A13b:** eine Tür ohne `to` auf einer Etage mit Flur ist keine Außentür und öffnet die Hülle nicht; nur `to: "outside"` oder eine Hüllentür (§ A13c, Phase 3) tut das."

- [ ] **Step 3: Commit**

```bash
git commit -m "docs(3d): § A13b — the corridor of a storey is a room

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- docs/schnittstellen-3d.md
```

**Abnahme P1 (sichtbar, durch den User nach Restart):** Raumliste einer Kellerlocation zeigt „Flur (Keller)", Admin-Grundriss-Vorschau zeigt auf Etage −1 keine Hüllenlöcher mehr, Boot-Log nennt die Migration, `GET /play/locations/{id}/scene` trägt `corridors[]`.

---

## Phase 2 — Clients

### Task 10: Geteilte Typen und Payload-Einlese (scene-render, client3d api, Player-UI)

**Files:**
- Modify: `packages/scene-render/src/types.ts` (`SceneRoom`-Nachbarschaft Zeile ~555; `ScenePayload` Zeile ~676)
- Modify: `client3d/src/api.ts` (Import-Liste Zeile 6–11; Normaliser Zeile ~731)
- Modify: `client3d/src/scene/sceneRecipe.ts` (nach der `scene.rooms`-Schleife, Zeile ~990) und `client3d/src/scene/tiles.ts` (dort, wo `Tile` deklariert ist: neues Feld `levelOutlines`)
- Modify: `packages/player-ui/src/ScenePanel.tsx` (`RoomInfo`, Zeile 45), `frontend/src/player/TravelPanel.tsx` (Zeile 43), `client3d/src/hud/Hud.tsx` + `client3d/src/hud/bus.ts` (neben `groundRoomId`)

**Interfaces:**
- `export interface SceneCorridor { room_id: string; level: number; anchor: [number, number] }`
- `ScenePayload.corridors: SceneCorridor[]`
- `RoomInfo` (beide Player-Dateien und der HUD-Typ): `+ is_floor: boolean; level: number | null`
- Game-State (bus.ts): `floorRoomIds: Record<string, string>` — `{ "-1": "__floor__-1", ... }`, gefüllt in `Hud.tsx` aus `data.rooms` wie `groundRoomId`
- `tile.levelOutlines: Map<number, [number, number][]>` — tile-lokale Etagenplatten-Umrisse aus `scene.plates` (eine Platte je Etage; bei mehreren die erste)

- [ ] **Step 1: Typen** in `types.ts` ergänzen (mit Doku-Kommentar: „server-computed anchor, § B1 corridors — the client places corridor figures here and never computes a point of its own").

- [ ] **Step 2: `api.ts`**: `corridors: arr<SceneCorridor>(data.corridors)` im Normaliser und `SceneCorridor` in den Import/Re-Export.

- [ ] **Step 3: `sceneRecipe.ts`** nach der Raumschleife:

```ts
  // THE CORRIDORS (§ A13b): rooms without geometry. Level and stand come from
  // the payload — `roomLevels` so the storey filter, the door gate and the
  // storey follow treat them like any room, `roomCenters` so the placement
  // puts their figures at the server's anchor instead of in front of the
  // building (the `else` branch of the placement is the yard huddle).
  for (const c of scene.corridors) {
    if (!c.room_id) continue;
    tile.roomLevels.set(c.room_id, c.level);
    const plate = scene.plates.find((p) => p.level === c.level);
    const y = plate ? plate.top_y : 0;          // storey 0 has no plate: terrain
    const centre = tileToWorld(tile, c.anchor[0], c.anchor[1], 0);
    centre.setY(c.level === 0 ? tileGroundY(tile, centre) : y);
    tile.roomCenters.set(c.room_id, centre);
    tile.roomSpots.set(c.room_id, []);
  }
  for (const p of scene.plates) {
    if (!tile.levelOutlines.has(p.level)) tile.levelOutlines.set(p.level, p.outline);
  }
```

Wie die Platte ihre Oberkante nennt (`top_y`?), in `ScenePlate` nachsehen; wie `roomCenters` sonst ihre Höhe bekommen (`WALK_CLEARANCE_M` in `tiles.ts` Zeile ~1006), übernehmen. `tileGroundY` ist in `main.ts` — falls es in `sceneRecipe.ts` nicht erreichbar ist, den Level-0-Fall wie den Raum-Mittelpunkt über `roomFloorWorldY`-Äquivalent für die Etage lösen oder das Y in `main.ts` beim Lesen setzen; entscheidend ist: **eine** Höhenquelle, keine neue Herleitung.

- [ ] **Step 4: Player-UI/HUD Typen und `floorRoomIds`** im Bus + `Hud.tsx`:

```ts
  const floorRoomIds = Object.fromEntries((data?.rooms || [])
    .filter((r) => r.is_floor && r.level !== null)
    .map((r) => [String(r.level), r.id]));
  useEffect(() => { setGameState({ floorRoomIds }); }, [JSON.stringify(floorRoomIds)]);
```

- [ ] **Step 5: Build-Check**

Run: `npm run build -w client3d 2>&1 | tail -3 && npm run lint 2>&1 | tail -3`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(client3d): corridors[] and rooms[].is_floor/level reach the client — levels, anchors, ids

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- packages/scene-render/src/types.ts client3d/src/api.ts client3d/src/scene/sceneRecipe.ts client3d/src/scene/tiles.ts packages/player-ui/src/ScenePanel.tsx frontend/src/player/TravelPanel.tsx client3d/src/hud/Hud.tsx client3d/src/hud/bus.ts
```

---

### Task 11: Raumwechsel-Heuristik, Lift- und Treppenziel im 3D-Client

**Files:**
- Modify: `client3d/src/game/roomwalk.ts` (neue reine Funktion `roomWalkCandidates`)
- Modify: `client3d/src/game/stairs.ts` (`nearestRoomAt`, Zeile ~359) und `client3d/src/game/elevator.ts` (Typen `ElevatorRoom`)
- Modify: `client3d/src/main.ts` (Kandidatenbildung Zeile ~4800–4822; `interiorRooms` Zeile ~4498; Türgatter Zeile ~1340; Etagen-Folge Zeile ~4709)
- Test: `client3d/scripts/smoke_walk_math.mjs` (neue Abschnitte)

**Interfaces:**
- `roomwalk.ts`:
  ```ts
  export interface CandidateInput {
    current: string | null; ownLevel: number | undefined; pos: {x:number; z:number};
    rooms: RoomWalkRoom[];                 // rooms with a rectangle on the shown interior (already lock-filtered)
    insideRect: (id: string) => boolean;   // does a room's rectangle hold pos
    insideLevelOutline: (level: number) => boolean; // storey plate outline holds pos (false = unknown/no plate)
    groundId: string;                      // '' when locked
    floorIdOf: (level: number) => string;  // '' when the storey has no corridor or it is locked
  }
  export function roomWalkCandidates(i: CandidateInput): RoomWalkRoom[]
  ```
  Regel: `inside = rooms.filter(insideRect)`; wenn nicht leer → `inside`. Sonst, mit `L = ownLevel ?? 0`: `floor = floorIdOf(L)`; wenn `L !== 0` und `floor` → `[{id: floor, level: L, center: pos}]`; wenn `L === 0`: `floor && insideLevelOutline(0)` → Flur, sonst `groundId` → `[{id: groundId, level: 0, center: pos}]`; sonst `rooms` (heutiger Rest). Ohne `rooms.length` (Szene noch nicht da) → `[]`.
- `stairs.ts`: `nearestRoomAt(level, pos, rooms)` — Räume bekommen optionales `floor?: boolean`; **ein Flur der Etage gewinnt vor jeder Distanz**; sonst wie heute. `interiorRooms(tile)` setzt `floor: Object.values(getGameState().floorRoomIds).includes(r.id)`.

- [ ] **Step 1: Smoke-Abschnitte schreiben** (Handzahlen im Kommentar; Stil der Datei: `check(label, actual, expected)`):

```js
  console.log('roomWalkCandidates — the corridor is the fallback of its storey (§ A13b)');
  {
    const rooms = [{ id: 'k1', level: -1, center: { x: -2.5, z: -2.5 } },
                   { id: 'k2', level: -1, center: { x: 2.5, z: -2.5 } }];
    const base = { current: 'k1', ownLevel: -1, pos: { x: 0, z: 2 }, rooms,
      insideRect: () => false, insideLevelOutline: () => true, groundId: '__ground__',
      floorIdOf: (lv) => (lv === -1 ? '__floor__-1' : '') };
    // outside both rectangles on storey -1 -> the corridor, level -1, centre = pos
    check('cellar -> corridor', roomWalkCandidates(base).map((r) => r.id), ['__floor__-1']);
    check('corridor carries the storey', roomWalkCandidates(base)[0].level, -1);
    // inside k2's rectangle -> k2 alone, the corridor is no candidate
    check('inside k2', roomWalkCandidates({ ...base, insideRect: (id) => id === 'k2' }).map((r) => r.id), ['k2']);
    // storey 0 with a hallway: inside the plate outline -> hallway, outside -> ground
    const g = { ...base, ownLevel: 0, floorIdOf: (lv) => (lv === 0 ? '__floor__0' : '') };
    check('hallway inside outline', roomWalkCandidates(g).map((r) => r.id), ['__floor__0']);
    check('yard outside outline', roomWalkCandidates({ ...g, insideLevelOutline: () => false }).map((r) => r.id), ['__ground__']);
    // storey 0 without a hallway (no opt-in) -> the ground, as before
    check('no hallway -> ground', roomWalkCandidates({ ...g, floorIdOf: () => '' }).map((r) => r.id), ['__ground__']);
    // locked corridor -> falls through to the room list (the old behaviour), never the corridor
    check('locked corridor', roomWalkCandidates({ ...base, floorIdOf: () => '' }).map((r) => r.id), ['k1', 'k2']);
    // no scene yet -> nothing
    check('no rooms', roomWalkCandidates({ ...base, rooms: [] }), []);
  }
  console.log('nearestRoomAt / elevatorTargetRoom — the lift opens into the corridor');
  {
    const rooms = [{ id: 'k1', level: -1, center: { x: -2.5, z: -2.5 } },
                   { id: '__floor__-1', level: -1, center: { x: 3, z: -3 }, floor: true },
                   { id: 'eg', level: 0, center: { x: -2, z: -2.5 } }];
    const stops = [{ level: -1, pos: { x: 3, z: -3 } }, { level: 0, pos: { x: 3, z: -3 } }];
    // stop at (3,-3): k1 is 7.8 m away, the corridor 0 m — and even from k1's own centre the corridor wins
    check('lift -> corridor', elevatorTargetRoom(-1, stops, rooms), '__floor__-1');
    check('corridor wins regardless of distance', nearestRoomAt(-1, { x: -2.5, z: -2.5 }, rooms), '__floor__-1');
    check('storey without corridor -> nearest room', elevatorTargetRoom(0, stops, rooms), 'eg');
    check('levels served count the corridor', elevatorLevels(stops, rooms), [-1, 0]);
  }
```

- [ ] **Step 2: Smoke laufen lassen — FAIL (roomWalkCandidates fehlt)**

Run: `node client3d/scripts/smoke_walk_math.mjs 2>&1 | tail -5` (die Datei transpiliert die TS-Module selbst; wie ein neues Modul-Export importiert wird, steht ab Zeile ~977 — `roomwalk` ist schon geladen).

- [ ] **Step 3: Implementieren** — `roomWalkCandidates` in `roomwalk.ts`; `nearestRoomAt` mit Flur-Vorrang:

```ts
  const corridor = rooms.find((r) => r.level === level && r.floor);
  if (corridor) return corridor.id;
```

`main.ts`: den Block zwischen `const groundId = ...` und `nearestRoomSwitch(...)` durch den Aufruf von `roomWalkCandidates` ersetzen (Kommentar behalten und um den Flur ergänzen); `insideLevelOutline` über `tile.levelOutlines` + `worldToTile` + `pointInPolygon` aus `game/polygon.ts`; `floorIdOf(lv)` = `getGameState().floorRoomIds[String(lv)]`, `''` wenn `isLocked(state.lockedRooms, id)` (der eigene Raum bleibt, wie beim Ground). Türgatter (Zeile ~1340) und Etagen-Folge (Zeile ~4709) brauchen keine Änderung, weil `roomLevels` die Flure jetzt kennt — **prüfen und im Commit-Body festhalten**.

- [ ] **Step 4: Smoke + Build**

Run: `node client3d/scripts/smoke_walk_math.mjs 2>&1 | tail -3 && npm run build -w client3d 2>&1 | tail -3`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(client3d): stepping out of a room lands in the storey's corridor, the lift opens into it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- client3d/src/game/roomwalk.ts client3d/src/game/stairs.ts client3d/src/game/elevator.ts client3d/src/main.ts client3d/scripts/smoke_walk_math.mjs
```

---

### Task 12: Game-Admin — Flur-Räume anzeigen, Opt-in-Schalter, Türziel-Anzeige

**Files:**
- Modify: `frontend/src/tabs/world/worldTypes.ts` (neben `GROUND_ROOM_ID`/`groundRoomLabel`; `Map3D` um `ground_corridor?: boolean`; `Room` um `level?: number`)
- Modify: `frontend/src/tabs/world/WorldTab.tsx` (Zeile ~268 Sortierung, ~308 Label/Title)
- Modify: `frontend/src/tabs/world/LocationEditor.tsx` (Zeile ~204 Entry-Raum-Select, ~210 Label, ~578)
- Modify: `frontend/src/tabs/world/RoomEditor.tsx` (`isGround`-Stellen: gleiches Verhalten für Flur — kein Löschen, kein 3D-Tab, Hinweistext)
- Modify: `frontend/src/tabs/world/PlanInspectorLevel.tsx` (Schalter bei `level === 0 && onMap3d`)
- Modify: `frontend/src/tabs/world/PlanOpeningStrip.tsx` (Prop `corridorName?: string`) und ihr Aufrufer (`grep -rn "PlanOpeningStrip" frontend/src` — dort den Flurnamen der Etage des Raums übergeben)
- Modify: `frontend/src/tabs/world/PlanRoomPicker.tsx`, `RoomLayoutEditor.tsx` (Zeilen ~652, ~678, ~682, ~686: Flure aus „platziert/unplatziert" ausnehmen)

**Interfaces:**
- `worldTypes.ts`:
  ```ts
  export const FLOOR_ROOM_PREFIX = '__floor__'
  export function floorRoomLevel(id: string | undefined): number | null
  export function isFloorRoom(id: string | undefined): boolean
  export function floorRoomLabel(room: { id?: string; name?: string }, t: (s: string) => string): string
  // name || (level 0 ? t('Hallway') : level -1 ? t('Corridor (basement)') : level < -1 ? t('Corridor (basement {n}}').replace('{n}', ..) : t('Corridor (floor {n})')...)
  export function roomLabel(room, t): string  // ONE helper: ground -> groundRoomLabel, floor -> floorRoomLabel, else name || id
  ```
  Alle drei Editor-Dateien benutzen fortan `roomLabel` statt der Inline-Ternäre (`WorldTab` 309, `LocationEditor` 210).

- [ ] **Step 1: `worldTypes.ts`-Helfer** implementieren; die Standardnamen müssen **denselben englischen Quelltext** wie `world.get_floor_name` tragen, damit `de.json` (Task 4) beide Seiten übersetzt.

- [ ] **Step 2: Baum/Editor**: `WorldTab` sortiert Flure nach der Grundfläche (`-2` Ground, `-1.5` Flure aufsteigend nach Level, `-1` Entry); Title „The corridor of this storey — the area no room of it takes up". `RoomEditor`: `const isReserved = isGround || isFloorRoom(room.id)` an allen `isGround`-Stellen, Hinweistext für den Flur: „The corridor of a storey is brought by the server. Name it, describe it — it has no layout of its own." `LocationEditor` Entry-Select: `(draft.rooms || []).filter((r) => !isFloorRoom(r.id) || floorRoomLevel(r.id) === 0)`.

- [ ] **Step 3: Opt-in-Schalter** in `PlanInspectorLevel.tsx` (nur `level === 0 && onMap3d`), nach dem Footprint-Block:

```tsx
      {level === 0 && onMap3d ? (
        <label className="ga-check" title={t('Doors without a target lead into the hallway; mark the front door with target "outside".')}>
          <input type="checkbox" checked={!!map3d?.ground_corridor}
            onChange={(e) => onMap3d('ground_corridor', e.target.checked ? true : undefined)} />
          {t('Ground floor has a hallway between the rooms')}
        </label>
      ) : null}
```

(Ob `onMap3d(key, undefined)` den Schlüssel entfernt, an `area_model`/`area_detail` derselben Datei ablesen und gleich machen.)

- [ ] **Step 4: `PlanOpeningStrip`**: Prop `corridorName?: string`; die Option `— none —` heißt bei gesetztem `corridorName` `→ {corridorName}`; Tooltip-Text: „Where a door/passage leads — another room, the storey's corridor (no target) or outside. Windows leave it empty." Aufrufer übergibt `corridorName = floorRoomLabel(<Flur-Raum der Etage des Raums>, t)`, wenn die Location einen Raum mit Id `__floor__<level>` hat.

- [ ] **Step 5: `PlanRoomPicker`/`RoomLayoutEditor`**: an den vier Zeilen `&& !isFloorRoom(r.id)` ergänzen; das Furnish-Ziel bleibt unverändert (Flure sind kein Ziel).

- [ ] **Step 6: Lint + Build** (baut `static/game_admin/assets/` neu)

Run: `npm run lint 2>&1 | tail -3 && npm run build 2>&1 | tail -3`

- [ ] **Step 7: Commit** (Quellen + gebaute Assets)

```bash
git add static/game_admin/assets static/game_admin/index.html static/game_admin/play.html
git commit -m "feat(admin): corridor rooms in the tree and editor, ground-floor hallway opt-in, door target shows the corridor

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- frontend/src/tabs/world static/game_admin
```

**Abnahme P2:** Avatar tritt im Keller aus dem Raum, Chip wechselt auf „Flur (Keller)"; Lift landet im Flur; NPC im Flur steht am Anker; Schalter auf Etage 0 sichtbar.

---

## Phase 3 — Hüllentür

### Task 13: Server — `map3d.hull_openings`, Konturschnitt, `doorways[]`-Eintrag

**Files:**
- Modify: `app/core/world_ops.py` (`_sanitize_map3d`: Liste `hull_openings`, jedes Element durch `_sanitize_opening` plus `level: int`, max. 8)
- Modify: `app/core/scene_recipe.py`: neue Funktion `_hull_doorways(map3d, storey, corridor_levels, default_door_prop_id)`, Aufruf in `compose_scene` direkt nach `_doorways` (`doorways.extend(...)`); `outside_doors` liest `d.get("outward_normal") or _door_outward(d)`; neuer Befund `hull_opening_without_corridor`
- Test: `scripts/smoke_floor_rooms.py` (Part 8)

**Interfaces:**
- gespeichert: `map3d.hull_openings: [{level, edge, at, width_m, height_m, sill_m, type, prop_id?, door_prop?, hinge?}]` — `edge` ist der **Kantenindex** des aufgelösten Etagengrundrisses (`_outline_world(map3d, level)`, Punkt i → i+1)
- `doorways[]`-Eintrag: `{level, at_world, along, type, width_m, height_m, base_y, rooms: ["__floor__<level>"], outside: True, outward_normal: [nx, nz], hull: True, _door_prop}`

- [ ] **Step 1: Part 8 Docstring + Checks**

```
Part 8 — the hull door (§ 6): cellar_fixture with map3d.ground_corridor true,
  rooms[] gaining __floor__0, eg's door given to "outside" (the front door of
  the room stays), and ONE hull opening {level 0, edge 0, at 0.5, 1.0 x 2.1,
  door}. Edge 0 runs (-5,-5) -> (5,-5): its midpoint is (0, -5), along [1, 0].
  A square listed counter-clockwise in map view has its outward normal on
  edge 0 pointing to -z: outward_normal [0, -1].
    hull doorway: at_world [0, -5], rooms ["__floor__0"], outside True, hull True
    the contour on level 0 along that edge splits into TWO full pieces of
    4.5 m (x -5..-0.5 and 0.5..5) plus one lintel and one leaf, the leaf 1.0 m
    wide from (-0.5, -5) to (0.5, -5)
    (eg's own outside door at x -2 also cuts this edge: its width 0.9 makes
     the western piece -5..-2.45 and -1.55..-0.5 — assert the FOUR full
     pieces on edge 0: lengths 2.55, 1.05, 4.5 in some order plus the second
     side of eg's cut; simpler: assert the leaf entries on level 0 are TWO,
     at x = -2 and x = 0)
  a hull opening on level 2 (no corridor there) -> ignored and reported as
    problems[] kind "hull_opening_without_corridor", level 2
  no_building_entrance is absent
```

Die Vorzeichen-Frage (wohin die Außennormale zeigt) ist im Docstring als Herleitung zu schreiben, nicht zu raten: `_contour_walls` bestimmt `ccw` per Shoelace und `nx = uz if ccw else -uz` — dieselbe Formel in `_hull_doorways` verwenden und das Ergebnis für dieses Quadrat von Hand angeben.

- [ ] **Step 2: Implementieren** — `_hull_doorways`:

```python
def _hull_doorways(map3d, storey, corridor_levels, default_door_prop_id):
    out, problems = [], []
    for op in (map3d or {}).get("hull_openings") or []:
        level = int(op.get("level") or 0)
        if level not in corridor_levels:
            problems.append({"kind": "hull_opening_without_corridor", "level": level,
                             "message": "A door on the building outline needs a corridor on its storey: enable the hallway on the ground floor, or remove the door."})
            continue
        pts = _outline_world(map3d, level)
        if len(pts) < 3:
            continue
        i = int(op.get("edge") or 0)
        if not (0 <= i < len(pts)):
            continue
        a, b = pts[i], pts[(i + 1) % len(pts)]
        frame = _edge_frame(a, b)
        if not frame:
            continue
        ux, uz, length = frame
        ccw = <shoelace of pts> > 0
        nx, nz = (uz if ccw else -uz), (-ux if ccw else ux)
        half = min(_num(op.get("width_m")), length) / 2
        t = min(max(_num(op.get("at")), 0.0), 1.0) * length
        t = min(max(t, half), length - half)          # clamp into the edge like a room door
        wall_h = _wall_height(storey)
        out.append({"level": level, "at_world": [_r(a[0] + ux * t), _r(a[1] + uz * t)],
                    "along": [_r(ux), _r(uz)], "type": str(op.get("type") or "door").lower(),
                    "width_m": _r(2 * half), "height_m": _r(min(_opening_height(op, wall_h), wall_h)),
                    "base_y": _r(storey_floor_y(level, storey)),
                    "rooms": [floor_room_id(level)], "outside": True, "hull": True,
                    "outward_normal": [_r(nx), _r(nz)],
                    "_door_prop": {"id": door_prop_id(op, default_door_prop_id),
                                   "hinge": "right" if str(op.get("hinge") or "").lower() == "right" else "left",
                                   "leaf": door_has_leaf(op)}})
    return out, problems
```

`_contour_hit(pts, at, normal)` muss einen Punkt **auf** der Kante treffen — prüfen (Toleranz), sonst für `hull: True`-Einträge den Schnitt direkt aus `(i, t)` setzen statt zu projizieren (dazu `edge`/`t` im Eintrag mitgeben und in `_contour_walls` bevorzugen). `compose_scene` strippt `_door_prop` bereits; `hull` und `outward_normal` bleiben im Payload.

- [ ] **Step 3: Smokes** (`smoke_floor_rooms.py`, `smoke_scene_recipe.py`)

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(scene): hull doors — an opening drawn on the storey outline cuts the shell and opens into the corridor

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- app/core/world_ops.py app/core/scene_recipe.py scripts/smoke_floor_rooms.py
```

---

### Task 14: Editor — Hüllentür zeichnen und bearbeiten

**Files:**
- Modify: `frontend/src/tabs/world/worldTypes.ts` (`Map3D.hull_openings?: HullOpening[]`, `HullOpening = RoomOpening & { level: number; edge: number }`)
- Create: `frontend/src/tabs/world/PlanHullOpeningStrip.tsx` (Breite/Höhe/Typ/Prop/Hinge wie `PlanOpeningStrip`, ohne `to`; Entfernen-Knopf)
- Modify: `frontend/src/tabs/world/PlanInspectorLevel.tsx` (Liste der Hüllentüren der Etage + Knopf „Door on the outline", nur wenn die Etage einen Flur hat: Etage 0 mit `ground_corridor` — andere Etagen bekommen den Knopf nicht, § 6)
- Modify: `frontend/src/tabs/world/PlanCanvas.tsx` + `PlanToolbar.tsx` (Werkzeugmodus `hull_opening`: Klick auf eine Konturkante → nächste Kante + Bruchteil; Zeichnen der Hüllentüren als Marker auf der Kontur — gleiche Optik wie Raumöffnungen)
- Modify: `frontend/src/tabs/world/planGeometry.ts` (reine Helfer `nearestOutlineEdge(points, p) -> {edge, at, dist}`)

- [ ] **Step 1: `nearestOutlineEdge`** rein implementieren und in `frontend/src/tabs/world/planGeometry.test`-Äquivalent prüfen — es gibt keine Jest-Suite; die Prüfung ist ein `node`-Einzeiler über die transpilierte Datei **oder** drei Handwerte im Kommentar: Quadrat (−5,−5)…(5,5), Punkt (0,−4.8) → `{edge: 0, at: 0.5, dist: 0.2}`; Punkt (4.9, 2) → `{edge: 1, at: 0.7, dist: 0.1}`; Punkt (−5.3, 0) → `{edge: 3, at: 0.5, dist: 0.3}`.

- [ ] **Step 2: Werkzeug + Streifen** bauen; Speichern läuft über den bestehenden `onMap3d('hull_openings', list)`-Pfad; der Server sanitisiert (Task 13).

- [ ] **Step 3: Kontur-Öffnungen im Admin-Grundriss sichtbar** — die Vorschau (`FloorPlanPreview`) liest `doorways[]` aus dem Rezept; Hüllentüren kommen dort ohne Zusatzarbeit an — **prüfen** und, falls sie nach `rooms[0]` gefiltert werden, `hull: true` durchlassen.

- [ ] **Step 4: Lint + Build + Commit** (Quellen + Assets, wie Task 12)

```bash
git commit -m "feat(admin): draw the front door on the building outline of a hallway storey

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- frontend/src/tabs/world static/game_admin
```

---

### Task 15: 3D-Client — Hüllentür begehen, Doku § A13c

**Files:**
- Modify: `client3d/src/game/doors.ts` / `client3d/src/game/enterLocation.ts` / `client3d/src/main.ts` (Türgatter Zeile ~1340: `doorwayLock(door.rooms, locks, here)` — ein Flur in `rooms[0]` ist ein gültiger Raum; das Angebot „Betreten" an einer Hüllentür führt per `/play/enter-room` in `__floor__0`)
- Modify: `docs/schnittstellen-3d.md`: `### A13c. Hüllentüren — neu 2026-09-09` nach § A13b; § B1 `doorways[]`-Felder `hull`, `outward_normal`; § A6 Verweis
- Test: `client3d/scripts/smoke_walk_math.mjs` — falls `doors.ts` eine reine Funktion für „welche Tür führt hinaus" hat, ein Check mit `rooms: ['__floor__0']`, `outside: true`

- [ ] **Step 1: Client prüfen und anpassen** — Türmarker/Schwellen kommen aus `doorways[]` (nichts herzuleiten); sicherstellen, dass kein Filter Einträge ohne Raumwand verwirft (z. B. Zuordnung „Tür → Raumgruppe" für die Schwellen-Optik: eine Hüllentür hängt an der Gebäudegruppe der Etage).

- [ ] **Step 2: Doku** § A13c (Felder, Sanitizer-Regeln, Schnittregel, Befund, Editor-Modus, Client liest nur).

- [ ] **Step 3: Build + Smoke + Commit**

```bash
npm run build -w client3d 2>&1 | tail -3 && node client3d/scripts/smoke_walk_math.mjs 2>&1 | tail -2
git commit -m "feat(client3d): hull doors are walkable thresholds into the hallway; docs § A13c

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- client3d/src docs/schnittstellen-3d.md client3d/scripts/smoke_walk_math.mjs
```

---

### Task 16: Abschluss — Smoke-Gesamtlauf, Lint, Doku-Ledger

- [ ] **Step 1: Alles laufen lassen**

Run: `for s in scripts/smoke_floor_rooms.py scripts/smoke_scene_recipe.py scripts/smoke_ground_room.py scripts/smoke_game_time_lint.py; do echo "== $s"; ./.venv/bin/python $s | tail -1; done; node client3d/scripts/smoke_walk_math.mjs | tail -1; npm run lint | tail -2; npm run build | tail -2; npm run build -w client3d | tail -2`

- [ ] **Step 2: `CLAUDE.md`** — im Absatz „Room/perception model" einen Satz: „The ground (`__ground__`) and the per-storey corridors (`__floor__<level>`, § A13b) are reserved rooms the server brings along; clients recognise them by `is_ground`/`is_floor`."

- [ ] **Step 3: `development_instructions/backend-status-3d.md`** (gitignored, nur lokal) — Ledger-Zeile „Etagen-Flur A13b/A13c gelandet <Datum>, Commits …".

- [ ] **Step 4: Commit** `CLAUDE.md` allein.
