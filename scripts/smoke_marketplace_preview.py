#!/usr/bin/env python3
"""Smoke run for the marketplace PREVIEW (plan-marketplace-props.md Teil D):
facts + thumbnail per pack type, the catalog's thumbnail URL and the
thumbnail route. Throwaway storage, no network. Expectations by hand:

[1] Prop "Chair" (category furniture, mount wall, 0.5 × 0.6 × 0.9 m, one
    variant, no mesh, no slots) with a 1000×500 source.png:
      facts == {"category": "furniture", "mount": "wall",
                "dims_m": [0.5, 0.6, 0.9], "variants": 1}
      (no tiers / tris / slots / seasons — nothing to say, so absent)
      thumbnail = WebP, longest edge 384 → 384×192.
[2] Location "Inn" with rooms A, B (+ the reserved ground room, not counted),
    no layouts (→ level 0 → 1 storey), gallery a.png (building-front),
    b.png (room A), c.png (untyped):
      image = a.png; facts == {"rooms": 2, "storeys": 1, "images": 3,
      "props": 0, "items": 0, "has_3d": False}.
    a.png's type removed → the NEWEST picture of the location itself
    (list_gallery_images order: by name, descending → c, b, a; b is room A's)
    = c.png; c.png assigned to room A as well → a.png, the only one left.
[3] Item "mug" (category consumable, image pic.png, no outfit piece):
      image = <item dir>/pic.png,
      facts == {"category": "consumable", "wearable": False}.
[4] Rule / states → no picture, no facts, no labels.
[5] Catalog annotation: a pack with a thumbnail gets
      thumbnail_url == preview_image == "/api/content/thumbnail?catalog_id=main
      &pack_id=prop-chair&asset=chair-1a2b3c4d.webp" (the asset makes the URL
      change with the content); a pack without one gets neither.
[6] Thumbnail route: first call downloads ONCE (capped at THUMB_MAX_BYTES)
    into .cache/content_thumbs/main/, the second is served from there (still
    one download); an asset name that is not a plain "<name>.webp"
    ("../x.webp") is a 404 without a download; an upstream 404 (swept asset)
    stays a 404, not a 502.
[7] The publish builder: entry facts == [1]'s facts, thumb_bytes present.
[8] Character "Mira" on template animal-default (identity section: species
    select, breed text, gender select, age number, birthday season_day,
    height number, personality text, presence text) with species "cat",
    breed "Tabby", gender "female", age 3, height 30 and a personality of
    60 characters, a profile picture, no outfits, no 3D model:
      facts == {"species": "cat", "breed": "Tabby", "gender": "female",
                "age": 3, "height": 30, "outfits": 0, "has_3d": False}
      (personality: text over 40 chars → no fact; birthday: not a fact type;
      the base template's name field sits in the merged identity section too,
      but its value IS the character's name — the pack title — so it is left out)
      labels == {"species": "Species", "breed": "Breed / Subspecies",
                 "gender": "Gender", "age": "Age", "height": "Height (cm)"}
      — the template's own labels; the builder stores them as fact_labels.
[9] make_thumbnail: None for no path, a missing file and a corrupt file.

Usage:  ./.venv/bin/python scripts/smoke_marketplace_preview.py
"""
import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="marketplace-preview-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="marketplace-preview-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from PIL import Image  # noqa: E402

from app.core import props  # noqa: E402
from app.core.content_io import make_thumbnail, pack_preview  # noqa: E402
from app.models.inventory import _get_item_dir, _save_items  # noqa: E402
from app.models.world import (add_location, get_gallery_dir,  # noqa: E402
                              set_gallery_image_room, set_gallery_image_type)

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def png(path: Path, size=(64, 64)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 80, 40)).save(path, "PNG")


print("\n[1] prop facts and thumbnail")
chair = props.create_prop(name="Chair", category="furniture", width_m=0.5,
                          depth_m=0.6, height_m=0.9, mount="wall")["id"]
png(props._prop_dir(chair) / "source.png", (1000, 500))
pv = pack_preview("prop", chair)
check("facts", pv["facts"], {"category": "furniture", "mount": "wall",
                             "dims_m": [0.5, 0.6, 0.9], "variants": 1})
check("image", pv["image"].name if pv["image"] else None, "source.png")
thumb = make_thumbnail(pv["image"])
with Image.open(io.BytesIO(thumb)) as im:
    check("thumbnail format", im.format, "WEBP")
    check("thumbnail size", im.size, (384, 192))

print("\n[2] location facts and picture choice")
inn = add_location("Inn", "An inn.", rooms=[{"name": "A"}, {"name": "B"}])
lid, room_a = inn["id"], inn["rooms"][0]["id"]
gd = get_gallery_dir(lid)
for n in ("a.png", "b.png", "c.png"):
    png(gd / n)
set_gallery_image_type(lid, "a.png", "building-front")
set_gallery_image_room(lid, "b.png", room_a)
lv = pack_preview("location", lid)
check("image", lv["image"].name if lv["image"] else None, "a.png")
check("facts", lv["facts"], {"rooms": 2, "storeys": 1, "images": 3, "props": 0,
                             "items": 0, "has_3d": False})
set_gallery_image_type(lid, "a.png", "")
check("without a front view: the newest own picture",
      pack_preview("location", lid)["image"].name, "c.png")
set_gallery_image_room(lid, "c.png", room_a)
check("c.png a room picture too: the only own one left",
      pack_preview("location", lid)["image"].name, "a.png")

print("\n[3] item")
_save_items([{"id": "mug", "name": "Mug", "category": "consumable",
              "image": "pic.png", "prompt_fragment": "a mug"}])
png(_get_item_dir("mug", create=True) / "pic.png")
iv = pack_preview("item", "mug")
check("image", iv["image"].name if iv["image"] else None, "pic.png")
check("facts", iv["facts"], {"category": "consumable", "wearable": False})

print("\n[4] types without a preview")
check("rule", pack_preview("rule", "x"), {"image": None, "facts": {}, "labels": {}})
check("states", pack_preview("states", ""), {"image": None, "facts": {}, "labels": {}})

print("\n[5] catalog annotation")
from app.routes import content_packs as cp  # noqa: E402
CAT = {"_id": "main", "name": "Main", "url": "https://github.com/o/r", "auth_token": ""}
out = cp._annotate({"packs": [
    {"id": "prop-chair", "thumbnail": {"asset": "chair-1a2b3c4d.webp",
                                       "download_url": "https://h/chair.webp"}},
    {"id": "rule-x"}]}, False, CAT)
want = ("/api/content/thumbnail?catalog_id=main&pack_id=prop-chair"
        "&asset=chair-1a2b3c4d.webp")
check("thumbnail_url", out["packs"][0].get("thumbnail_url"), want)
check("preview_image", out["packs"][0].get("preview_image"), want)
check("no thumbnail → no url", "thumbnail_url" in out["packs"][1], False)

print("\n[6] thumbnail route: one download, then the cache")
cp._list_catalogs = lambda: [CAT]
cp._write_cache("main", {"packs": [
    {"id": "prop-chair", "thumbnail": {"asset": "chair-1a2b3c4d.webp",
                                       "download_url": "https://h/chair.webp"}},
    {"id": "prop-evil", "thumbnail": {"asset": "../x.webp",
                                      "download_url": "https://h/x.webp"}},
    {"id": "prop-gone", "thumbnail": {"asset": "gone-00000000.webp",
                                      "download_url": "https://h/gone.webp"}}]})
downloads, caps = [], []


async def fake_download(url, headers, **kw):
    downloads.append(url)
    caps.append(kw.get("max_bytes"))
    if url == "https://h/gone.webp":
        import httpx
        rq = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("404", request=rq, response=httpx.Response(404, request=rq))
    tmp = STORAGE / ".cache" / "dl.part"
    tmp.write_bytes(thumb)
    return tmp


cp._download = fake_download
from starlette.requests import Request  # noqa: E402


def req():
    return Request({"type": "http", "method": "GET", "headers": [], "query_string": b""})


r1 = asyncio.run(cp.pack_thumbnail(req(), catalog_id="main", pack_id="prop-chair"))
r2 = asyncio.run(cp.pack_thumbnail(req(), catalog_id="main", pack_id="prop-chair"))
check("served", (r1.status_code, r2.status_code), (200, 200))
check("downloaded once", downloads, ["https://h/chair.webp"])
check("cached file", (STORAGE / ".cache" / "content_thumbs" / "main"
                      / "chair-1a2b3c4d.webp").is_file(), True)
try:
    asyncio.run(cp.pack_thumbnail(req(), catalog_id="main", pack_id="prop-evil"))
    check("unsafe asset name", "served", 404)
except cp.HTTPException as e:
    check("unsafe asset name", e.status_code, 404)
check("no download for it", len(downloads), 1)
check("download capped", caps, [cp.THUMB_MAX_BYTES])
try:
    asyncio.run(cp.pack_thumbnail(req(), catalog_id="main", pack_id="prop-gone"))
    check("swept upstream", "served", 404)
except cp.HTTPException as e:
    check("swept upstream", e.status_code, 404)

print("\n[7] the publish builder carries facts and thumbnail")
from app.core.marketplace_publish import build_upload  # noqa: E402
upload, warnings = build_upload("prop", chair, "Chair", "", [], max_pack_mb=500)
check("facts", upload.entry["facts"], pv["facts"])
check("thumbnail bytes", bool(upload.thumb_bytes), True)
check("no warnings for a small pack", warnings, [])

print("\n[8] character facts from its own template")
from app.models.character import (get_character_images_dir,  # noqa: E402
                                  save_character_profile)
save_character_profile("Mira", {
    "name": "Mira", "template": "animal-default", "species": "cat",
    "breed": "Tabby", "gender": "female", "age": 3, "height": 30,
    "character_personality": "x" * 60, "profile_image": "mira.png",
}, create_new=True)
png(get_character_images_dir("Mira") / "mira.png")
cv = pack_preview("character", "Mira")
check("facts", cv["facts"], {"species": "cat", "breed": "Tabby", "gender": "female",
                             "age": 3, "height": 30, "outfits": 0, "has_3d": False})
check("labels", cv["labels"], {"species": "Species", "breed": "Breed / Subspecies",
                               "gender": "Gender", "age": "Age",
                               "height": "Height (cm)"})
check("image", cv["image"].name if cv["image"] else None, "mira.png")
cu, _ = build_upload("character", "Mira", "Mira", "", [], max_pack_mb=500)
check("builder stores the labels", cu.entry.get("fact_labels"), cv["labels"])

print("\n[9] make_thumbnail without a usable picture")
bad = STORAGE / "corrupt.png"
bad.write_bytes(b"not a png")
check("no path", make_thumbnail(None), None)
check("missing file", make_thumbnail(STORAGE / "nope.png"), None)
check("corrupt file", make_thumbnail(bad), None)

print("\nall checks passed" if not FAILURES
      else f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
