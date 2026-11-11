#!/usr/bin/env python3
"""Smoke: the item-ownership routes count every stored character, dormant
and pooled ones included.

Usage:  ./.venv/bin/python scripts/smoke_item_ownership_dormant.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM.

WHY: Game-Admin → Items → "Owned by nobody" is filtered by
``GET /inventory/ownership``. That map was built from the ROSTER
(``list_available_characters()``), which leaves out a dormant linked body
(``status='dormant'``) and a pooled temp NPC. A dormant body's items were
therefore listed as owned by nobody, and one was deleted by hand
(2026-11-11). Owning an item does not depend on standing in the world.

FIXTURE
    Characters Tilda (present, status ""), Glut (status "dormant"), Pia
    (status "pooled"). World items "ember", "boots", "coin", "stone".
    Inventories: Tilda ember; Glut boots; Pia coin. "stone" in nobody's.

WHAT FOLLOWS BY HAND
[O1] get_ownership_map_route()["ownership"]: ember -> ["Tilda"],
     boots -> ["Glut"], coin -> ["Pia"], no key for stone.
[O2] get_item_owners_route(boots)["owners"] names exactly Glut, quantity 1.
[O3] get_item_owners_route(stone)["owners"] == [].

On 4c92aee0 [O1] boots/coin and [O2] fail (no key / empty owners).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="item-ownership-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.models import character as ch  # noqa: E402
from app.models import inventory as inv  # noqa: E402
from app.routes.inventory import get_item_owners_route, get_ownership_map_route  # noqa: E402

FAILS = 0


def check(label, actual, expected):
    global FAILS
    ok = actual == expected
    FAILS += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))


for name in ("Tilda", "Glut", "Pia"):
    assert ch.save_character_profile(name, {"character_name": name, "template": "human-roleplay"},
                                     create_new=True), name
with db.transaction() as conn:
    conn.execute("UPDATE characters SET status='dormant' WHERE name='Glut'")
    conn.execute("UPDATE characters SET status='pooled' WHERE name='Pia'")

ids = {}
for label in ("ember", "boots", "coin", "stone"):
    ids[label] = inv.add_item(label, item_id=f"item_smoke_{label}")["id"]
for owner, label in (("Tilda", "ember"), ("Glut", "boots"), ("Pia", "coin")):
    assert inv.add_to_inventory(owner, ids[label]), (owner, label)

print("[O1] ownership map")
own = get_ownership_map_route()["ownership"]
check("ember", own.get(ids["ember"]), ["Tilda"])
check("boots (dormant owner)", own.get(ids["boots"]), ["Glut"])
check("coin (pooled owner)", own.get(ids["coin"]), ["Pia"])
check("stone has no key", ids["stone"] in own, False)

print("[O2] owners of boots")
owners = get_item_owners_route(ids["boots"])["owners"]
check("owner names", [o["character"] for o in owners], ["Glut"])
check("quantity", [o["quantity"] for o in owners], [1])

print("[O3] owners of stone")
check("owners", get_item_owners_route(ids["stone"])["owners"], [])

print("ALL OK" if not FAILS else f"{FAILS} FAILURE(S)")
sys.exit(1 if FAILS else 0)
