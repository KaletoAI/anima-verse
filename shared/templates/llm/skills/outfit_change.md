---
name: ChangeOutfit
action_hint: Character changes/puts on/takes off clothes (e.g. gets dressed because not alone anymore)
---
Puts on and takes off outfit pieces the character ALREADY owns — it never invents clothing (that is CreateOutfit's job). NAME the pieces: JSON {"equip": ["piece-id-or-name", ...], "unequip_slots": ["outer", ...], "unequip_items": ["item-id", ...]} OR a plain comma-separated list of piece names. An empty input changes nothing, so always say what goes on or comes off, and only ever name pieces from the inventory. Prefer pieces that go with what is already worn; mix styles only when the situation calls for it.
