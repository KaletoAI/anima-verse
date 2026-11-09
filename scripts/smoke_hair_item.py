#!/usr/bin/env python3
"""Hair as its own mesh, task 1: the mesh-only slot and the hair item.

Usage:
    ./.venv/bin/python scripts/smoke_hair_item.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package plus ONE fixture package — no real world, no private pack, no server.
Every expectation is derived by hand below from the human manifest, the
fixture and the rules of plan 2026-11-09-base-body-phase4-hair (R2, R3).

Fixture character ``Demo`` (template human-roleplay, female, 30, 168 cm, on
the base-body pipeline): hair slot {length: medium, color: blonde},
character_appearance "slender, wavy hair with a side parting, green eyes",
two equipped outfit pieces (top "blouse", bottom "jeans"). ``Pet`` uses the
animal template (humanoid: false). ``Bald`` is a pipeline human with no hair
slot values and no hair word in its appearance. Fixture package
``fixture_mesh`` (apply_to human-roleplay) declares the slot ``mark`` with a
non-string ``mesh_item: 5``.

[1] Loader. The human ``hair`` slot carries ``mesh_item: "hair"``; the other
    human slots carry ""; ``mark`` declared 5 (not a string) -> dropped -> "".
[2] mesh_item_slots(Demo) = {"hair": <hair slot>} (only the human hair slot
    declares one; ``mark``'s was dropped). Pet: the human package does not
    apply to the animal template -> {}.
[3] slot_fragment(Demo, "hair") = the ``always`` fragment "{length} {color}
    hair" -> ("medium blonde hair", ""); with mesh_input=True the second part
    is the front ``values`` line for "medium": "hair tucked back behind the
    shoulders, the chest and collarbones free of hair". Unknown slot ->
    ("", "").
[4] hair_description(Demo) = fragment + every comma/sentence clause of the
    appearance matching \\bhair\\b: clauses "slender" / "wavy hair with a side
    parting" / "green eyes" -> only the middle one:
        "medium blonde hair, wavy hair with a side parting"
    An appearance clause equal to the fragment (case-insensitive) is not
    repeated: "Medium blonde hair. wavy hair with a side parting" gives the
    same text. Hair slot empty but a hair clause present -> the clause alone
    (R3: "no hair text AT ALL means no hair item"). A clause that denies hair
    ("bald head with no hair": no/without/bald/hairless) or still holds a
    {placeholder} is not hair text -> "".
[5] hair_behind_shoulders: medium -> True (the values table has "medium");
    short -> False (no entry).
[6] ensure_hair_item(Demo): creates ONE item {name "Hair", category
    "garment", owner "Demo", garment {kind hair, slot hair, body_slot hair},
    prompt_fragment = [4]}; a second call returns the same id and creates
    nothing; equipped_mesh_pieces == {"hair": id}, stored in
    character_state.meta (state key, not profile_json); the inventory
    listing is identical before/after; ``_notify_outfit_changed`` is never
    called; ``garment_assembly.schedule`` is called once (the first equip
    only — the second call changes nothing).
[7] 2D invariance: outfit_signature, current_outfit_state()[2],
    render_outfit()["full"], base_body.dress_text(front),
    expression_regen._equipped_signature are byte-identical before/after.
[8] equip_piece(Demo, hair_id) is refused (the hair item is no outfit piece
    and not in the inventory); equip_mesh_piece refuses an outfit piece, a
    garment whose slot ("wings") is not among Demo's mesh-item slots, an
    unknown id and a hair garment owned by another character (ValueError). A changed slot (short) re-run of ensure_hair_item keeps the
    id and refreshes prompt_fragment to "short blonde hair, wavy hair with a
    side parting" without purging any outfit render
    (invalidate_variants_for_item never called). unequip_mesh_piece(Demo,
    "hair") -> True and {}; ensure finds the item again by owner + kind.
[9] Pet -> ValueError "Hair as its own mesh is for humanoid …", profile
    unchanged, no item created. Bald -> ValueError "No hair set …", no item
    created. Offline (a human off the pipeline) -> ValueError "Offline is not
    on the base-body pipeline".
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


def raises(label, fn, exc, prefix=""):
    """``fn()`` raises ``exc`` whose message starts with ``prefix``."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        got = f"{type(e).__name__}: {e}"
        check(label, got if not (isinstance(e, exc) and str(e).startswith(prefix)) else "raised",
              "raised")
        return
    check(label, "no error", "raised")


FIXTURE = {
    "name": "fixture_mesh",
    "apply_to": ["human-roleplay"],
    "body_slots": [{
        "id": "mark",
        "attributes": {"shade": {"type": "select", "options": ["faint", "bold"]}},
        "prompt": {"always": "{shade} mark"},
        "mesh_item": 5,
    }],
}

DESCRIPTION = "medium blonde hair, wavy hair with a side parting"
MEDIUM_LINE = "hair tucked back behind the shoulders, the chest and collarbones free of hair"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-item-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human,fixture_mesh"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        (plugins / "fixture_mesh").mkdir(parents=True)
        (plugins / "fixture_mesh" / "plugin.yaml").write_text(json.dumps(FIXTURE))
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, body_slots, expression_regen, model_refs
        from app.core.outfit_renderer import render_outfit
        from app.models import inventory
        from app.models.character import get_character_profile, save_character_profile

        # No debounced reference renders in a smoke: equipping the fixture
        # pieces must not start timers.
        model_refs.schedule_outfit_render = lambda *a, **k: None

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair with a side parting, green eyes",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        check("create Pet", save_character_profile("Pet", {"template": "animal-default", "gender": "female",
                                                           "model_pipeline": "base_body"}, create_new=True), True)
        bald = json.loads(json.dumps(human))
        bald["body_slots"].pop("hair")
        bald["character_appearance"] = "slender, green eyes"
        check("create Bald", save_character_profile("Bald", bald, create_new=True), True)
        check("pipeline Bald", base_body.set_pipeline("Bald", True), True)
        check("create Offline", save_character_profile("Offline", json.loads(json.dumps(human)),
                                                       create_new=True), True)

        blouse = inventory.add_item(name="blouse", category="outfit_piece",
                                    prompt_fragment="a white linen blouse",
                                    outfit_piece={"slots": ["top"], "outfit_types": ["casual"]})["id"]
        jeans = inventory.add_item(name="jeans", category="outfit_piece", prompt_fragment="blue jeans",
                                   outfit_piece={"slots": ["bottom"], "outfit_types": ["casual"]})["id"]
        for item in (blouse, jeans):
            check(f"inventory {item}", inventory.add_to_inventory("Demo", item), True)
            check(f"equip {item}", inventory.equip_piece("Demo", item, source="smoke")["status"], "ok")

        print("[1] loader")
        stored = get_character_profile("Demo")
        specs = {s.id: s for s in body_slots.slots_for_character("Demo", profile=stored)}
        check("hair mesh_item", specs["hair"].mesh_item, "hair")
        check("other human slots", sorted({specs[s].mesh_item for s in ("eyes", "skin", "build")}), [""])
        check("non-string dropped", specs["mark"].mesh_item, "")

        print("[2] mesh_item_slots")
        slots = body_slots.mesh_item_slots("Demo", profile=stored)
        check("Demo kinds", sorted(slots), ["hair"])
        check("Demo slot", slots["hair"].id, "hair")
        check("stored-profile path", sorted(body_slots.mesh_item_slots("Demo")), ["hair"])
        check("Pet", body_slots.mesh_item_slots("Pet"), {})

        print("[3] slot_fragment")
        check("always", body_slots.slot_fragment("Demo", "hair", profile=stored), ("medium blonde hair", ""))
        check("mesh input", body_slots.slot_fragment("Demo", "hair", profile=stored, mesh_input=True),
              ("medium blonde hair", MEDIUM_LINE))
        check("unknown slot", body_slots.slot_fragment("Demo", "nope", profile=stored), ("", ""))
        # The refactor keeps prompt_fragments' own output: general carries the
        # same always text, exposed the mesh line.
        frags = body_slots.prompt_fragments("Demo", profile=stored, mesh_input=True)
        check("prompt_fragments general", "medium blonde hair" in frags["general"], True)
        check("prompt_fragments exposed", MEDIUM_LINE in frags["exposed"], True)

        print("[4] hair_description")
        from app.core import garment_hair
        check("description", garment_hair.hair_description("Demo", profile=stored), DESCRIPTION)
        check("stored-profile path", garment_hair.hair_description("Demo"), DESCRIPTION)
        dup = dict(stored, character_appearance="Medium blonde hair. wavy hair with a side parting")
        check("dedup", garment_hair.hair_description("Demo", profile=dup), DESCRIPTION)
        no_slot = json.loads(json.dumps(stored))
        no_slot["body_slots"].pop("hair")
        check("clause only", garment_hair.hair_description("Demo", profile=no_slot),
              "wavy hair with a side parting")
        denied = dict(no_slot, character_appearance="slender, bald head with no hair, {mood} hair glow")
        check("denial and placeholder clauses dropped", garment_hair.hair_description("Demo", profile=denied), "")

        print("[5] hair_behind_shoulders")
        check("medium", garment_hair.hair_behind_shoulders("Demo", profile=stored), True)
        short = json.loads(json.dumps(stored))
        short["body_slots"]["hair"]["length"] = "short"
        check("short", garment_hair.hair_behind_shoulders("Demo", profile=short), False)

        print("[6] ensure_hair_item")
        pieces = inventory.get_equipped_pieces("Demo")
        items = inventory.get_equipped_items("Demo")

        def twod():
            p = inventory.get_equipped_pieces("Demo")
            i = inventory.get_equipped_items("Demo")
            return {
                "outfit_signature": model_refs.outfit_signature(p, i, "Demo"),
                "current_outfit_state": model_refs.current_outfit_state("Demo")[2],
                "render_full": render_outfit(character_name="Demo")["full"],
                "dress_text": base_body.dress_text("Demo", "front", pieces=p, items=i),
                "equipped_signature": expression_regen._equipped_signature(p, i),
                "equipped_ids": inventory.get_equipped_item_ids("Demo"),
            }

        before = twod()
        check("fixture worn", sorted(pieces.values()), sorted([blouse, jeans]))
        check("fixture full text non-empty", bool(before["render_full"]), True)
        inventory_before = inventory.get_character_inventory("Demo")
        items_before = len(inventory.list_items())

        notified, scheduled, purged = [], [], []
        real_notify = inventory._notify_outfit_changed
        inventory._notify_outfit_changed = lambda *a, **k: notified.append(a)
        from app.core import garment_assembly
        garment_assembly.schedule = lambda name, signature=None: scheduled.append(name) or True
        expression_regen.invalidate_variants_for_item = lambda item_id: purged.append(item_id) or 0
        try:
            hair_id = garment_hair.ensure_hair_item("Demo")
            check("second call same id", garment_hair.ensure_hair_item("Demo"), hair_id)
            check("one item created", len(inventory.list_items()), items_before + 1)
            item = inventory.get_item(hair_id)
            check("name", item.get("name"), "Hair")
            check("category", item.get("category"), "garment")
            check("owner", item.get("owner"), "Demo")
            check("garment", item.get("garment"), {"kind": "hair", "slot": "hair", "body_slot": "hair"})
            check("prompt_fragment", item.get("prompt_fragment"), DESCRIPTION)
            check("equipped_mesh_pieces", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hair_id})
            row = db.get_connection().execute(
                "SELECT meta FROM character_state WHERE character_name=?", ("Demo",)).fetchone()
            check("state meta key", json.loads(row[0] or "{}").get("equipped_mesh_pieces"), {"hair": hair_id})
            check("inventory unchanged", inventory.get_character_inventory("Demo"), inventory_before)
            check("no outfit notification", notified, [])
            check("assembly scheduled once", scheduled, ["Demo"])

            print("[7] 2D invariance")
            after = twod()
            for key in before:
                check(key, after[key], before[key])

            print("[8] refusals and refresh")
            check("equip_piece refused", inventory.equip_piece("Demo", hair_id)["status"], "error")
            raises("equip outfit piece as mesh", lambda: inventory.equip_mesh_piece("Demo", blouse), ValueError)
            wings = inventory.add_item(name="Wings", category="garment", owner="Demo",
                                       garment={"kind": "wings", "slot": "wings", "body_slot": "wings"})["id"]
            raises("garment slot not declared", lambda: inventory.equip_mesh_piece("Demo", wings), ValueError)
            raises("unknown item", lambda: inventory.equip_mesh_piece("Demo", "item_missing"), ValueError)
            foreign = inventory.add_item(name="Other hair", category="garment", owner="Bald",
                                         garment={"kind": "hair", "slot": "hair", "body_slot": "hair"})["id"]
            raises("foreign owner", lambda: inventory.equip_mesh_piece("Demo", foreign), ValueError)
            check("still equipped", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hair_id})

            from app.core.body_slots import set_slot_value
            check("set short", set_slot_value("Demo", "hair", "length", "short"), True)
            check("refresh same id", garment_hair.ensure_hair_item("Demo"), hair_id)
            check("refreshed fragment", inventory.get_item(hair_id).get("prompt_fragment"),
                  "short blonde hair, wavy hair with a side parting")
            check("no outfit render purge", purged, [])

            check("unequip", inventory.unequip_mesh_piece("Demo", "hair"), True)
            check("unequipped", inventory.get_equipped_mesh_pieces("Demo"), {})
            check("found by owner", garment_hair.ensure_hair_item("Demo"), hair_id)
            check("re-equipped", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hair_id})
            check("still one hair item of Demo", sum(1 for it in inventory.list_items()
                                                    if (it.get("garment") or {}).get("kind") == "hair"
                                                    and it.get("owner") == "Demo"), 1)
            check("still no outfit notification", notified, [])

            print("[9] refused characters")
            items_now = len(inventory.list_items())
            pet_before = get_character_profile("Pet")
            raises("Pet", lambda: garment_hair.ensure_hair_item("Pet"), ValueError, "Hair as its own mesh is for humanoid")
            check("Pet profile unchanged", get_character_profile("Pet"), pet_before)
            raises("Bald", lambda: garment_hair.ensure_hair_item("Bald"), ValueError, "No hair set")
            check("Bald no mesh pieces", inventory.get_equipped_mesh_pieces("Bald"), {})
            raises("Offline", lambda: garment_hair.ensure_hair_item("Offline"), ValueError,
                   "Offline is not on the base-body pipeline")
            check("no item created", len(inventory.list_items()), items_now)
        finally:
            inventory._notify_outfit_changed = real_notify

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
