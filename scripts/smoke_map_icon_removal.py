#!/usr/bin/env python3
"""Smoke run for the map-icon removal (plan-rueckbau-2d-karte.md, Paket 1).

Hand-derived expectations:
  * A world with ONE location whose gallery holds three files — a.png typed
    "map_2d", b.png typed "map" (legacy isometric), c.png typed "day" — and
    whose record carries map_image_2d="a.png", map_rotation_2d=90,
    image_prompt_map_2d="icon", image_prompt_map="iso".
    All three files carry the FULL sidecar set the render path writes, put
    there through the real writers (save_gallery_prompt / set_gallery_image_meta
    / set_gallery_image_room), so every structure the migration touches is
    non-empty and a wrong section key cannot pass unnoticed.
  * After migrate_map_images_once(): a.png and b.png are GONE from disk and
    from every sidecar — prompts.json holds only c.png, gallery_meta.json's
    image_types / image_metas / rooms hold only c.png (the section key is
    "rooms", the very one set_gallery_image_room writes) — c.png stays typed
    "day" with its prompt, meta and room intact; the five legacy keys are
    gone from the location dict; the return value is
    {"images_deleted": 2, "fields_stripped": 5}.
  * A second run changes nothing: {"images_deleted": 0, "fields_stripped": 0}.
  * world_ops.assign_gallery_image_type refuses "map_2d" and "map"
    with HTTP 400; "day" and "building-front" pass.
  * PRAGMA table_info(locations) lists NO column image_prompt_map after
    db.init_schema() ran on a DB that still had it.
Runs against a THROWAWAY storage directory — it never touches a real world.

Usage: ./.venv/bin/python scripts/smoke_map_icon_removal.py
"""
import sys, tempfile
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
tmp = Path(tempfile.mkdtemp(prefix="smoke_mapicon_"))
from app.core import paths
paths.init(str(tmp))
from app.core import db
# Simulate a pre-migration schema: create the old column, then init.
conn = db.get_connection()
db.init_schema()
cols = {r[1] for r in conn.execute("PRAGMA table_info(locations)")}
if "image_prompt_map" not in cols:
    conn.execute("ALTER TABLE locations ADD COLUMN image_prompt_map TEXT DEFAULT ''")
    conn.execute("DELETE FROM schema_meta WHERE key='map_icons_removed_v1'")
    conn.commit()
    db.init_schema()
cols = {r[1] for r in conn.execute("PRAGMA table_info(locations)")}
FAILS = []
def check(label, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + " " + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok: FAILS.append(label)
check("image_prompt_map column dropped", "image_prompt_map" in cols, False)

from app.models.world import (add_location, _load_world_data, _save_world_data,
                              get_gallery_dir, set_gallery_image_type,
                              get_gallery_image_types, migrate_map_images_once,
                              get_location_by_id, save_gallery_prompt,
                              get_all_gallery_prompts, set_gallery_image_meta,
                              get_gallery_image_metas, set_gallery_image_room,
                              get_gallery_image_rooms)
loc = add_location("Bay", "a bay", rooms=[{"name": "Shore", "description": ""}])
lid = loc["id"]
gdir = get_gallery_dir(lid); gdir.mkdir(parents=True, exist_ok=True)
for fn in ("a.png", "b.png", "c.png"):
    (gdir / fn).write_bytes(b"\x89PNG")
set_gallery_image_type(lid, "a.png", "map_2d")
set_gallery_image_type(lid, "b.png", "map")
set_gallery_image_type(lid, "c.png", "day")
# The full sidecar set the render path writes, through the real writers — the
# migration has to reach all three, and the survivor proves it reaches no more.
room_id = loc["rooms"][0]["id"]
for fn in ("a.png", "b.png", "c.png"):
    save_gallery_prompt(lid, fn, f"{fn} prompt")
    set_gallery_image_meta(lid, fn, {"backend": "x", "backend_type": "http",
                                     "model": "", "loras": []})
    set_gallery_image_room(lid, fn, room_id)
data = _load_world_data()
for l in data["locations"]:
    if l["id"] == lid:
        l.update({"map_image_2d": "a.png", "map_rotation_2d": 90,
                  "image_prompt_map_2d": "icon", "image_prompt_map": "iso",
                  "map_image": "b.png"})
_save_world_data(data)

r1 = migrate_map_images_once()
check("first run counts", r1, {"images_deleted": 2, "fields_stripped": 5})
check("a.png deleted", (gdir / "a.png").exists(), False)
check("b.png deleted", (gdir / "b.png").exists(), False)
check("c.png kept", (gdir / "c.png").exists(), True)
check("types after", get_gallery_image_types(lid), {"c.png": "day"})
check("prompts after", get_all_gallery_prompts(lid), {"c.png": "c.png prompt"})
check("image_metas after", sorted(get_gallery_image_metas(lid)), ["c.png"])
check("rooms after", get_gallery_image_rooms(lid), {"c.png": room_id})
after = get_location_by_id(lid)
check("legacy keys gone", [k for k in ("map_image_2d", "map_rotation_2d",
      "image_prompt_map_2d", "image_prompt_map", "map_image") if k in after], [])
r2 = migrate_map_images_once()
check("second run is a no-op", r2, {"images_deleted": 0, "fields_stripped": 0})

from fastapi import HTTPException
from app.core import world_ops
def rejects(t):
    try:
        world_ops.assign_gallery_image_type(lid, "c.png", t)
        return False
    except HTTPException as e:
        return e.status_code == 400
check("map_2d rejected", rejects("map_2d"), True)
check("map rejected", rejects("map"), True)
check("day accepted", rejects("day"), False)
check("building-front accepted", rejects("building-front"), False)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
