"""Smoke: a host item brings its part items and their accepted meshes along on export and import (plan-anhaenger
Task 9, design G) — ``content_io`` single-item, bundle and embedded (character/location) paths, the move routes.

Usage: ./.venv/bin/python scripts/smoke_item_export_parts.py   (no server; a temp world and shared library; the
inventory router on a throwaway FastAPI app with ``require_admin`` overridden)

The world: part "item_p" (no slot, kind charm) with image bytes A and an accepted mesh under
``jewellery/item_p/<psig(A)>/{raw.glb, record.json, cutout.png}``; the belt "item_belt" (slot outer) links it as its
buckle. ``accessory_pendant.start`` is monkeypatched to count — every check below expects 0 calls (no hub job).

Expected, derived by hand:

[1] ``export_item_to_zip("item_belt")``: ``db/items.json`` ids == ["item_belt", "item_p"] (host first),
    ``manifest.parts == ["item_p"]``, ``files/item_p/image.png`` and ``jewellery_files/item_p/<psig(A)>/raw.glb``,
    ``record.json``, ``cutout.png`` are in the ZIP.
[2] import into a world without either (both deleted, the store removed) → both exist, ``pendant_state(item_p)`` is
    ``ready`` with ``psig(A)``, 0 jobs.
[3] import into a world whose "item_p" is a DIFFERENT part (image bytes B) and no belt → the part arrives as
    "item_p_2" (``_next_free_item_id``), the belt's ``buckle.item == "item_p_2"``, item_p_2's mesh is ready (its image
    is A, the psig in the path matches); "item_p" keeps image B and has no mesh.
[4] import with the SAME image (item_p has A again, belt and item_p_2 gone) → no new item: the item ids after are the
    ids before plus "item_belt" only; ``buckle.item == "item_p"``.
[5] a ZIP whose extra row is not named in ``manifest.parts`` → ValueError; one whose extra row is named there but is
    no part (slot "outer", kind belt) → ValueError; through ``POST /inventory/items/import`` → 400.
[6] ``export_items_to_bundle_zip(["item_belt"])``: rows ids == ["item_belt", "item_p"], ``manifest.parts ==
    ["item_p"]``, the mesh under ``jewellery_files/item_p/``. Importing it (overwrite) after the store was removed →
    ``pendant_state(item_p)`` ready again, 0 jobs.
[7] ``embed_world_items(zf, ["item_belt"])`` → embedded ids ["item_belt", "item_p"] and the mesh files; after
    deleting both and the store, ``restore_embedded_items`` → both created, the mesh ready.
[8] ``pack_preview("item", "item_belt")["facts"]`` == {category: outfit_piece, wearable: True, parts: 1}.
[9] ``POST move-to-shared`` of the belt → the belt AND its world part are shared; ``POST move-to-world`` of the part
    → 409 whose ``used_by`` names item_belt (shared); of the belt → 200 (a world belt may link a shared part).
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_export_parts_")
SHARED = Path(tempfile.mkdtemp(prefix="smoke_export_parts_shared_"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_export_parts_clips_")
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import db  # noqa: E402

db.init_schema()
import app.models.inventory as inv  # noqa: E402

inv._get_shared_dir = lambda: SHARED
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import accessory_pendant as ap, accessory_spec, content_io  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.routes import inventory as inv_routes  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


START = []
ap.start = lambda item_id: START.append(item_id) or True
app = FastAPI()
app.include_router(inv_routes.router)
app.dependency_overrides[require_admin] = lambda: {"role": "admin", "id": "admin"}
client = TestClient(app)

A, B = b"image-bytes-A", b"image-bytes-B"
PSIG_A = ap.psig_for(hashlib.sha256(A).hexdigest())


def image(item_id, data):
    d = inv._get_item_dir(item_id, create=True)
    (d / "image.png").write_bytes(data)
    inv.set_item_image(item_id, "image.png")


def mesh(item_id):
    d = ap.pendant_dir(item_id, ap.current_psig(item_id))
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.glb").write_bytes(b"glb")
    (d / "cutout.png").write_bytes(b"cut")
    (d / "record.json").write_text(json.dumps({"accepted": True, "psig": ap.current_psig(item_id)}))


def make_part(item_id="item_p", data=A, with_mesh=True):
    inv.add_item("Oak Buckle", item_id=item_id, category="outfit_piece", prompt_fragment="a copper oak-leaf buckle",
                 outfit_piece={"slots": [], "mesh_mode": "accessory", "jewellery": {"kind": "charm"}})
    image(item_id, data)
    if with_mesh:
        mesh(item_id)


BELT_PIECE = {"slots": ["outer"], "mesh_mode": "accessory", "jewellery": {"kind": "belt", "buckle": {"item": "item_p"}}}


def make_belt():
    inv.add_item("Copper Belt", item_id="item_belt", category="outfit_piece", prompt_fragment="copper belt",
                 outfit_piece=BELT_PIECE)


def gone(*ids):
    for iid in ids:
        inv.delete_item(iid)
        shutil.rmtree(ap.root() / iid, ignore_errors=True)
        shutil.rmtree(inv._get_item_dir(iid), ignore_errors=True)


def buckle_of(item_id):
    return (accessory_spec.of_item(inv.get_item(item_id))["buckle"] or {}).get("item")


def ids():
    return sorted(i["id"] for i in inv.list_items())


make_part()
make_belt()

print("[1] export")
blob = content_io.export_item_to_zip("item_belt")
zf = zipfile.ZipFile(io.BytesIO(blob))
rows = json.loads(zf.read("db/items.json"))
manifest = json.loads(zf.read("manifest.json"))
check("[1] rows", [r["id"] for r in rows], ["item_belt", "item_p"])
check("[1] manifest.parts", manifest.get("parts"), ["item_p"])
names = set(zf.namelist())
check("[1] files", sorted(n for n in names if n.startswith(("files/item_p/", "jewellery_files/"))),
      sorted(["files/item_p/image.png"] + [f"jewellery_files/item_p/{PSIG_A}/{f}"
                                          for f in ("cutout.png", "raw.glb", "record.json")]))

print("[2] import into an empty world")
gone("item_belt", "item_p")
r = content_io.import_item_from_zip(blob)
check("[2] both there", ids(), ["item_belt", "item_p"])
check("[2] mesh ready", (ap.pendant_state("item_p")["state"], ap.pendant_state("item_p")["psig"]), ("ready", PSIG_A))
check("[2] 0 jobs", START, [])

print("[3] a different item_p exists")
gone("item_belt", "item_p")
make_part(data=B, with_mesh=False)
content_io.import_item_from_zip(blob)
check("[3] renamed part", ids(), ["item_belt", "item_p", "item_p_2"])
check("[3] link remapped", buckle_of("item_belt"), "item_p_2")
check("[3] item_p_2 mesh", ap.pendant_state("item_p_2")["state"], "ready")
check("[3] item_p kept", (Path(inv.get_item_image_path("item_p")).read_bytes(), ap.pendant_state("item_p")["state"]),
      (B, "missing"))

print("[4] the same item_p exists")
gone("item_belt", "item_p_2")
image("item_p", A)
before = ids()
content_io.import_item_from_zip(blob)
check("[4] no new part", ids(), sorted(before + ["item_belt"]))
check("[4] link kept", buckle_of("item_belt"), "item_p")


def rezip(rows_, manifest_):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in zf.namelist():
            if n not in ("db/items.json", "manifest.json"):
                z.writestr(n, zf.read(n))
        z.writestr("db/items.json", json.dumps(rows_))
        z.writestr("manifest.json", json.dumps(manifest_))
    return out.getvalue()


print("[5] extra rows that are no part")
gone("item_belt")
extra = {"id": "item_x", "name": "X", "category": "outfit_piece", "outfit_piece": {"slots": ["outer"]}}
bad1 = rezip(rows + [extra], manifest)
bad2 = rezip(rows + [{**extra, "outfit_piece": {"slots": ["outer"], "jewellery": {"kind": "belt"}}}],
             {**manifest, "parts": ["item_p", "item_x"]})
for name, z in (("not in manifest.parts", bad1), ("no part", bad2)):
    try:
        content_io.import_item_from_zip(z)
        check(f"[5] {name}", "imported", "ValueError")
    except ValueError:
        check(f"[5] {name}", "ValueError", "ValueError")
r = client.post("/inventory/items/import", files={"file": ("x.zip", bad2, "application/zip")})
check("[5] route 400", r.status_code, 400)
check("[5] nothing written", "item_x" in ids(), False)
make_belt()

print("[6] bundle")
bundle = content_io.export_items_to_bundle_zip(["item_belt"])
bz = zipfile.ZipFile(io.BytesIO(bundle))
check("[6] rows", [r["id"] for r in json.loads(bz.read("db/items.json"))], ["item_belt", "item_p"])
check("[6] manifest.parts", json.loads(bz.read("manifest.json")).get("parts"), ["item_p"])
check("[6] mesh in bundle", f"jewellery_files/item_p/{PSIG_A}/raw.glb" in bz.namelist(), True)
shutil.rmtree(ap.root() / "item_p")
content_io.import_bundle_from_zip(bundle, overwrite=True)
check("[6] mesh back", ap.pendant_state("item_p")["state"], "ready")
check("[6] 0 jobs", START, [])

print("[7] embedded (character / location export)")
out = io.BytesIO()
with zipfile.ZipFile(out, "w") as z:
    emb = content_io.embed_world_items(z, ["item_belt"])
check("[7] embedded", emb, ["item_belt", "item_p"])
ez = zipfile.ZipFile(io.BytesIO(out.getvalue()))
check("[7] mesh embedded", f"jewellery_files/item_p/{PSIG_A}/raw.glb" in ez.namelist(), True)
gone("item_belt", "item_p")
check("[7] restored", sorted(content_io.restore_embedded_items(ez)), ["item_belt", "item_p"])
check("[7] mesh ready", ap.pendant_state("item_p")["state"], "ready")

print("[8] preview")
check("[8] facts", content_io.pack_preview("item", "item_belt")["facts"],
      {"category": "outfit_piece", "wearable": True, "parts": 1})

print("[9] move routes")
r = client.post("/inventory/items/item_belt/move-to-shared", json={})
check("[9] to shared", r.status_code, 200)
check("[9] both shared", (inv.is_shared_item("item_belt"), inv.is_shared_item("item_p")), (True, True))
r = client.post("/inventory/items/item_p/move-to-world", json={})
check("[9] part to world 409", r.status_code, 409)
check("[9] used_by", [(u["item_id"], u["shared"]) for u in (r.json().get("used_by") or [])], [("item_belt", True)])
check("[9] part still shared", inv.is_shared_item("item_p"), True)
check("[9] belt to world", client.post("/inventory/items/item_belt/move-to-world", json={}).status_code, 200)
check("[9] 0 jobs", START, [])

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
