"""Standalone check: update_item strips spell-only fields on non-spell items.

Run: ./.venv/bin/python scripts/test_item_spell_strip.py
No server needed — uses a throwaway world in a temp dir.

Background (bug 2026-07-29): copying a spell item in the Items tab and turning
it into a consumable kept `incantation`/`spell_mode` in the item meta.
build_spell_catalog treats ANY inventory item with an incantation as a spell,
so the "Energy Drink" showed up as a spell in /play belongings. The contract
under test: spell metadata may only persist on items with category "spell".
"""
import sys
import tempfile

sys.path.insert(0, ".")

SPELL_FIELDS = {
    "incantation": "Lunoro Enercus",
    "spell_mode": "force",
    "success_chance": 100,
    "copy_on_give": True,
    "success_text": "it works",
    "fail_text": "it fizzles",
    "cast_activity": "channeling",
    "anchor_item_id": "item_anchor",
    "teleport_subject": "caster",
    "clone_item_id": "item_clone",
}


def check(name: str, cond: bool):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        sys.exit(1)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="anima_item_spell_check_")
    from app.core import paths, db
    paths.init(tmp)
    db.init_schema()

    from app.models.inventory import add_item, update_item, get_item

    # A real spell keeps its spell fields through an update.
    spell = add_item(name="Check Spell", category="spell", consumable=True)
    updated = update_item(spell["id"], dict(SPELL_FIELDS))
    check("spell keeps incantation", updated.get("incantation") == "Lunoro Enercus")
    check("spell keeps spell_mode", updated.get("spell_mode") == "force")

    # Re-categorizing the spell to consumable strips ALL spell fields.
    updated = update_item(spell["id"], {"category": "consumable"})
    for key in SPELL_FIELDS:
        check(f"recategorized item drops {key}", key not in updated)
    check("recategorized item persisted clean",
          "incantation" not in (get_item(spell["id"]) or {}))

    # Creating a consumable and pushing spell fields at it (the copy-flow
    # request shape: category != spell, extras present) must not persist them.
    drink = add_item(name="Check Drink", category="consumable", consumable=True)
    updated = update_item(drink["id"], dict(SPELL_FIELDS))
    for key in SPELL_FIELDS:
        check(f"consumable drops {key}", key not in updated)

    # Non-spell metadata that shares the extras channel stays untouched.
    updated = update_item(drink["id"], {"tracks_character": "demo"})
    check("consumable keeps tracks_character",
          updated.get("tracks_character") == "demo")

    print("OK")


if __name__ == "__main__":
    main()
