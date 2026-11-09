#!/usr/bin/env python3
"""Own-mesh outfit pieces, task 1: the item flag and the worn-garment set.

Usage:
    ./.venv/bin/python scripts/smoke_garment_set.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no private pack, no server. Every expectation is
derived by hand below from the rules of plan
2026-11-09-base-body-phase5-mesh-items (Global Constraints, task 1).

Fixture: ``Demo`` (template human-roleplay, on the base-body pipeline) holds
and wears ``dress`` (slots top+bottom, flagged ``own_mesh``) and ``shoes``
(slot feet, NOT flagged), holds but does not wear ``cape`` (slot outer,
flagged), and wears a hair garment (category garment, kind hair, owner Demo)
through ``equipped_mesh_pieces``. ``coat`` (slot outer, flagged) is held by
nobody. ``Offline`` is a human off the pipeline wearing the dress; ``Pet``
uses the animal template with ``model_pipeline: base_body`` (an animal is
never on the pipeline). ``Other`` owns a second hair garment.

[1] Flag storage. add_item stores ``outfit_piece.own_mesh`` as a bool:
    True for dress/cape/coat, False for shoes (key absent on create). An
    update of an unrelated field (name) keeps True; an update that sends an
    ``outfit_piece`` WITHOUT the key keeps the stored value (True); an
    explicit ``own_mesh: false`` stores False and ``true`` stores True again.
[2] 2D invariance. Flipping the dress flag off and on again changes neither
    outfit_signature(Demo's pieces), render_outfit()["full"] nor
    inventory._render_relevant_fields(dress) — and therefore never calls
    invalidate_variants_for_item.
[3] worn_garments(Demo) = sorted({hair, dress}): the dress occupies top AND
    bottom but appears once, shoes are unflagged. With pieces={"feet": shoes}
    only the hair stays. Offline wearing the dress -> []; Pet (animal) with
    pieces={"top": dress} -> []. held_clothing(Demo) = sorted({cape, dress})
    (coat is held by nobody, shoes unflagged); holds(Demo, cape) True,
    holds(Demo, hair) True (worn mesh piece, not in the inventory),
    holds(Demo, coat) False. garment_kind_of: dress "clothing", shoes None,
    hair "hair", a garment of kind "wings" None.
[4] Gates. garments._item(Demo, dress) -> (item, "clothing"); shoes
    (unflagged) and coat (flagged, not held) -> ValueError; the hair item of
    Demo -> (item, "hair"); Other's hair -> ValueError (the owner rule stays).
    garment_store._garment_kind(dress) and garment_mesh._kind(dress) ->
    "clothing", shoes -> ValueError. garment_images._kind_module(dress) ->
    the module garment_clothing (task 2 added the clothing image chain),
    shoes -> ValueError "is no garment item".
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, contains=""):
    """``fn()`` raises ``exc`` whose message contains ``contains``."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        ok = isinstance(e, exc) and contains in str(e)
        check(label, "raised" if ok else f"{type(e).__name__}: {e}", "raised")
        return
    check(label, "no error", "raised")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-set-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, model_refs, garment_assembly
        from app.core.outfit_renderer import render_outfit
        from app.models import inventory
        from app.models.character import save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: True
        purged = []
        expression_regen.invalidate_variants_for_item = lambda item_id: purged.append(item_id) or 0

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}
        for name in ("Demo", "Offline", "Other"):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)),
                                                           create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        check("pipeline Other", base_body.set_pipeline("Other", True), True)
        check("create Pet", save_character_profile("Pet", {"template": "animal-default", "gender": "female",
                                                           "model_pipeline": "base_body"}, create_new=True), True)

        def piece(name, slots, own_mesh=None):
            op = {"slots": slots, "outfit_types": ["casual"]}
            if own_mesh is not None:
                op["own_mesh"] = own_mesh
            return inventory.add_item(name=name, category="outfit_piece",
                                      prompt_fragment=f"a plain {name}", outfit_piece=op)["id"]

        dress = piece("dress", ["top", "bottom"], True)
        shoes = piece("shoes", ["feet"])
        cape = piece("cape", ["outer"], True)
        coat = piece("coat", ["outer"], True)
        for item in (dress, shoes, cape):
            check(f"inventory {item}", inventory.add_to_inventory("Demo", item), True)
        for item in (dress, shoes):
            check(f"equip {item}", inventory.equip_piece("Demo", item, source="smoke")["status"], "ok")
        check("inventory Offline dress", inventory.add_to_inventory("Offline", dress), True)
        check("equip Offline dress", inventory.equip_piece("Offline", dress, source="smoke")["status"], "ok")

        hair_spec = {"kind": "hair", "slot": "hair", "body_slot": "hair"}
        hair = inventory.add_item(name="Hair", category="garment", owner="Demo", garment=hair_spec,
                                  transferable=False, portable=False)["id"]
        other_hair = inventory.add_item(name="Hair", category="garment", owner="Other", garment=hair_spec,
                                        transferable=False, portable=False)["id"]
        wings = inventory.add_item(name="Wings", category="garment", owner="Demo",
                                   garment={"kind": "wings", "slot": "wings", "body_slot": "wings"})["id"]
        check("equip hair", inventory.equip_mesh_piece("Demo", hair), True)

        def own(item_id):
            return (inventory.get_item(item_id).get("outfit_piece") or {}).get("own_mesh")

        print("[1] flag storage")
        check("dress create", own(dress), True)
        check("shoes create (absent -> False)", own(shoes), False)
        inventory.update_item(dress, {"name": "summer dress"})
        check("unrelated update keeps", own(dress), True)
        inventory.update_item(dress, {"outfit_piece": {"slots": ["top", "bottom"], "outfit_types": ["casual"]}})
        check("outfit_piece without key keeps", own(dress), True)
        check("slots still there", inventory.get_item(dress)["outfit_piece"]["slots"], ["top", "bottom"])
        inventory.update_item(dress, {"outfit_piece": {"slots": ["top", "bottom"], "own_mesh": False}})
        check("explicit false", own(dress), False)
        inventory.update_item(dress, {"outfit_piece": {"slots": ["top", "bottom"], "own_mesh": True}})
        check("explicit true", own(dress), True)

        print("[2] 2D invariance")
        pieces = inventory.get_equipped_pieces("Demo")
        items = inventory.get_equipped_items("Demo")
        check("Demo wears dress twice + shoes", sorted(pieces.items()),
              [("bottom", dress), ("feet", shoes), ("top", dress)])

        def twod():
            return (model_refs.outfit_signature(pieces, items, "Demo"),
                    render_outfit(character_name="Demo")["full"],
                    inventory._render_relevant_fields(inventory.get_item(dress)))

        purged.clear()
        on = twod()
        check("full text non-empty", bool(on[1]), True)
        inventory.update_item(dress, {"outfit_piece": {"slots": ["top", "bottom"], "own_mesh": False}})
        off = twod()
        check("flag off: signature", off[0], on[0])
        check("flag off: render_outfit full", off[1], on[1])
        check("flag off: render-relevant fields", off[2], on[2])
        inventory.update_item(dress, {"outfit_piece": {"slots": ["top", "bottom"], "own_mesh": True}})
        check("flag on again", twod(), on)
        check("no render purge on a flip", purged, [])

        print("[3] worn and held garments")
        from app.core import garment_set
        check("kind dress", garment_set.garment_kind_of(inventory.get_item(dress)), "clothing")
        check("kind shoes", garment_set.garment_kind_of(inventory.get_item(shoes)), None)
        check("kind hair", garment_set.garment_kind_of(inventory.get_item(hair)), "hair")
        check("kind wings", garment_set.garment_kind_of(inventory.get_item(wings)), None)
        check("kind None", garment_set.garment_kind_of(None), None)
        check("worn Demo", garment_set.worn_garments("Demo"), sorted([hair, dress]))
        check("worn Demo, pieces override", garment_set.worn_garments("Demo", pieces={"feet": shoes}), [hair])
        check("worn Offline", garment_set.worn_garments("Offline"), [])
        check("worn Pet", garment_set.worn_garments("Pet", pieces={"top": dress}), [])
        check("held Demo", garment_set.held_clothing("Demo"), sorted([cape, dress]))
        check("held Other", garment_set.held_clothing("Other"), [])
        check("holds cape", garment_set.holds("Demo", cape), True)
        check("holds hair", garment_set.holds("Demo", hair), True)
        check("holds coat", garment_set.holds("Demo", coat), False)

        print("[4] gates")
        from app.core import garments, garment_store, garment_images, garment_mesh
        got = garments._item("Demo", dress)
        check("_item dress", (got[0]["id"], got[1]), (dress, "clothing"))
        raises("_item shoes", lambda: garments._item("Demo", shoes), ValueError)
        raises("_item coat not held", lambda: garments._item("Demo", coat), ValueError, "not a garment of Demo")
        got = garments._item("Demo", hair)
        check("_item hair", (got[0]["id"], got[1]), (hair, "hair"))
        raises("_item foreign hair", lambda: garments._item("Demo", other_hair), ValueError,
               "not a garment of Demo")
        check("_garment_kind dress", garment_store._garment_kind(dress), "clothing")
        raises("_garment_kind shoes", lambda: garment_store._garment_kind(shoes), ValueError)
        check("mesh _kind dress", garment_mesh._kind(dress), "clothing")
        raises("mesh _kind shoes", lambda: garment_mesh._kind(shoes), ValueError)
        check("_kind_module dress", garment_images._kind_module(dress).__name__, "app.core.garment_clothing")
        raises("_kind_module shoes", lambda: garment_images._kind_module(shoes), ValueError,
               "is no garment item")

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
