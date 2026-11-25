"""Smoke: the part-item routes (plan-anhaenger Task 6) — make-part, part-mesh, used-by, the delete guard, the figure
GET's ``part_options`` / ``host_mentions`` and the part image prompt.

Usage: ./.venv/bin/python scripts/smoke_accessory_parts_routes.py   (no server; a temp world and shared library; the
inventory and figure routers on a throwaway FastAPI app, ``require_admin`` overridden — the auth gate itself is
``smoke_auth_gate.py``'s: ``/inventory/items`` writes are on its admin write prefixes)

Expected, derived by hand:

[1] ``POST /inventory/items/item_belt/make-part {role: buckle}`` on the belt "Copper Belt" (text "copper belt") → 202
    ``{part_id, image: "queued"}``; the part exists, is a part (no slot), is named "Copper Belt Buckle"; the belt's
    ``buckle.item`` is it; the image thread (monkeypatched ``generate_item_image_sync``) ran exactly once, for the part;
    ``image_prompt`` == ``part_image_prompt("buckle", "copper belt")``; "demo", who owns the belt, does not own the
    part. ``role: charm`` 7 times → 6 × 202 then 400 (``MAX_CHARMS``). ``role: pendant`` on the belt → 400.
[2] ``DELETE`` of the buckle part → 409, ``used_by == [{item_id: item_belt, name: Copper Belt, role: buckle, shared:
    False}]``; ``GET …/used-by`` names the same. After unlinking (buckle None) → 200, and ``jewellery/<part>/`` (made
    by hand with a file in it) is gone.
[3] ``GET part-mesh`` of a part whose mesh is accepted → ``state: ready``; ``GET /inventory/items`` marks every part
    ``part: true`` (and nothing else). ``POST part-mesh`` on the belt (no part) → 400; on a part without an image → 400; on a part whose mesh is accepted →
    ``{status: ready}`` (nothing started — ``accessory_pendant.start`` monkeypatched to count, 0 calls); on a part
    with an image and no mesh → ``started`` (1 call). Earrings with a drop make their drop from their OWN image through
    the same route → ``started``.
[4] the old ``POST /characters/demo/figure/accessory/item_belt/pendant`` → 404 or 405.
[6] ``part_image_prompt``, strings by hand:
    ("buckle", "copper belt") → "a single belt buckle made of copper, on its own, no strap, no chain, front view,
    isolated product photo, plain white background" (no "copper belt");
    ("pendant", "gold necklace with gemstone") → "a single necklace pendant made of gold, on its own, …" (no
    "necklace with", no "gemstone");
    ("charm", "black leather belt") → "a single small charm, on its own, …";
    ("buckle", "") → without "made of".
[7] ``GET /characters/demo/figure/accessory/item_neck`` (necklace "gold necklace with gemstone" linking the part
    "a gemstone pendant"): ``parts[0].host_mentions`` True ("gemstone" in both); ``part_options`` names every part of
    the world (ids sorted) with ``{id, name, image_url, state}``.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_parts_routes_")
SHARED = Path(tempfile.mkdtemp(prefix="smoke_parts_routes_shared_"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_parts_routes_clips_")
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import db  # noqa: E402

db.init_schema()
import app.models.inventory as inv  # noqa: E402

inv._get_shared_dir = lambda: SHARED
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import accessory_parts as parts, accessory_pendant as ap, accessory_spec  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.routes import figure as figure_routes, inventory as inv_routes  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


IMAGE_CALLS, START_CALLS = [], []
inv_routes.generate_item_image_sync = lambda item_id, overrides=None, *a, **k: IMAGE_CALLS.append(item_id)
ap.start = lambda item_id: START_CALLS.append(item_id) or True

app = FastAPI()
app.include_router(inv_routes.router)
app.include_router(figure_routes.router)
app.dependency_overrides[require_admin] = lambda: {"role": "admin", "id": "admin"}
client = TestClient(app)


def piece(slots, jewellery):
    return {"slots": slots, "mesh_mode": "accessory", "jewellery": jewellery}


def image(item_id, data):
    d = inv._get_item_dir(item_id, create=True)
    (d / "image.png").write_bytes(data)
    inv.set_item_image(item_id, "image.png")


inv.add_item("Copper Belt", item_id="item_belt", category="outfit_piece", prompt_fragment="copper belt",
             outfit_piece=piece(["outer"], {"kind": "belt"}))
inv.add_item("Drop Earrings", item_id="item_ear", category="outfit_piece", prompt_fragment="drop earrings",
             outfit_piece=piece(["head"], {"kind": "earrings", "earring": {"style": "drop"}}))
image("item_ear", b"earring-image")
save_character_profile("demo", {"name": "demo"}, create_new=True)
inv._save_inventory("demo", {"inventory": [{"item_id": "item_belt", "quantity": 1}]})

print("[6] part_image_prompt")
TAIL = "on its own, no strap, no chain, front view, isolated product photo, plain white background"
check("[6] buckle", parts.part_image_prompt("buckle", "copper belt"), f"a single belt buckle made of copper, {TAIL}")
p = parts.part_image_prompt("pendant", "gold necklace with gemstone")
check("[6] pendant", p, f"a single necklace pendant made of gold, {TAIL}")
check("[6] pendant: no host words", ("necklace with" in p, "gemstone" in p), (False, False))
check("[6] charm", parts.part_image_prompt("charm", "black leather belt"), f"a single small charm, {TAIL}")
check("[6] empty", parts.part_image_prompt("buckle", ""), f"a single belt buckle, {TAIL}")

print("[1] make-part")
r = client.post("/inventory/items/item_belt/make-part", json={"role": "buckle"})
check("[1] 202", r.status_code, 202)
pid = r.json().get("part_id", "")
check("[1] body", r.json(), {"part_id": pid, "image": "queued"})
part = inv.get_item(pid) or {}
check("[1] a part, no slot", (parts.is_part(part), (part.get("outfit_piece") or {}).get("slots")), (True, []))
check("[1] name", part.get("name"), "Copper Belt Buckle")
check("[1] linked", (accessory_spec.of_item(inv.get_item("item_belt"))["buckle"] or {}).get("item"), pid)
check("[1] one image job, for the part", IMAGE_CALLS, [pid])
check("[1] image prompt", part.get("image_prompt"), parts.part_image_prompt("buckle", "copper belt"))
check("[1] not in demo's inventory", [e["item_id"] for e in inv._load_inventory("demo")["inventory"]], ["item_belt"])
codes = [client.post("/inventory/items/item_belt/make-part", json={"role": "charm"}).status_code for _ in range(7)]
check("[1] 6 charms then 400", codes, [202] * 6 + [400])
check("[1] pendant on a belt → 400",
      client.post("/inventory/items/item_belt/make-part", json={"role": "pendant"}).status_code, 400)

print("[2] the delete guard")
d = ap.item_dir(pid) / "0123456789ab"
d.mkdir(parents=True)
(d / "raw.glb").write_bytes(b"glb")
r = client.delete(f"/inventory/items/{pid}")
check("[2] 409", r.status_code, 409)
want = [{"item_id": "item_belt", "name": "Copper Belt", "role": "buckle", "shared": False}]
check("[2] used_by in the 409", r.json().get("used_by"), want)
check("[2] GET used-by", client.get(f"/inventory/items/{pid}/used-by").json(), {"used_by": want})
with inv.outfit_piece_lock("item_belt"):
    belt = inv.get_item("item_belt")
    raw = dict(belt["outfit_piece"]["jewellery"])
    raw["buckle"] = None
    inv.update_item("item_belt", {"outfit_piece": {**belt["outfit_piece"], "jewellery": raw}})
r = client.delete(f"/inventory/items/{pid}")
check("[2] 200 once unlinked", r.status_code, 200)
check("[2] mesh store gone", ap.item_dir(pid).exists(), False)

print("[3] part-mesh")
check("[3] no part → 400", client.post("/inventory/items/item_belt/part-mesh").status_code, 400)
r = client.post("/inventory/items/item_belt/make-part", json={"role": "buckle"})
pid = r.json()["part_id"]
check("[3] no image → 400", client.post(f"/inventory/items/{pid}/part-mesh").status_code, 400)
image(pid, b"buckle-image")
psig = ap.current_psig(pid)
d = ap.pendant_dir(pid, psig)
d.mkdir(parents=True)
(d / "raw.glb").write_bytes(b"glb")
(d / "record.json").write_text(json.dumps({"accepted": True, "psig": psig}))
START_CALLS.clear()
check("[3] GET state", client.get(f"/inventory/items/{pid}/part-mesh").json()["state"], "ready")
check("[3] list marks parts", [i["id"] for i in client.get("/inventory/items").json()["items"] if i.get("part")],
      sorted(i["id"] for i in inv.list_items() if parts.is_part(i)))
check("[3] ready", (client.post(f"/inventory/items/{pid}/part-mesh").json(), START_CALLS), ({"status": "ready"}, []))
image(pid, b"another-buckle-image")
check("[3] started", (client.post(f"/inventory/items/{pid}/part-mesh").json(), START_CALLS),
      ({"status": "started"}, [pid]))
START_CALLS.clear()
check("[3] earrings drop", (client.post("/inventory/items/item_ear/part-mesh").json(), START_CALLS),
      ({"status": "started"}, ["item_ear"]))

print("[4] the old route")
check("[4] gone", client.post("/characters/demo/figure/accessory/item_belt/pendant").status_code in (404, 405), True)

print("[7] figure GET")
inv.add_item("Gold Chain", item_id="item_neck", category="outfit_piece", prompt_fragment="gold necklace with gemstone",
             outfit_piece=piece(["neck"], {"kind": "necklace"}))
inv.add_item("Gem", item_id="item_gem", category="outfit_piece", prompt_fragment="a gemstone pendant",
             outfit_piece={"slots": [], "jewellery": {"kind": "charm"}})
with inv.outfit_piece_lock("item_neck"):
    neck = inv.get_item("item_neck")
    inv.update_item("item_neck", {"outfit_piece": {**neck["outfit_piece"],
                                                   "jewellery": {"kind": "necklace", "pendant": {"item": "item_gem"}}}})
body = client.get("/characters/demo/figure/accessory/item_neck").json()
check("[7] host_mentions", [r.get("host_mentions") for r in body.get("parts") or []], [True])
opts = body.get("part_options") or []
all_parts = sorted(i["id"] for i in inv.list_items() if parts.is_part(i))
check("[7] part_options ids", [o["id"] for o in opts], all_parts)
check("[7] part_options keys", sorted(opts[0]) if opts else [], ["id", "image_url", "name", "state"])

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
