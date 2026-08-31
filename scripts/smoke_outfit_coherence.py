#!/usr/bin/env python3
"""Smoke run for outfit coherence (Block CO).

Runs against a THROWAWAY storage directory with real items in the DB — the
tag normalisation is checked through the actual save path, the coherence rule
against the real ``covers`` machinery.

Usage:  ./.venv/bin/python scripts/smoke_outfit_coherence.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="outfit-coherence-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import outfit_coherence as oc  # noqa: E402
from app.models.inventory import add_item, get_item, update_item  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def piece(name: str, slots, types, covers=()) -> str:
    item = add_item(name=name, category="outfit_piece", prompt_fragment=name,
                    outfit_piece={"slots": list(slots),
                                  "covers": list(covers),
                                  "outfit_types": list(types)})
    return item["id"]


def types_of(item_id: str):
    return (get_item(item_id) or {}).get("outfit_piece", {}).get("outfit_types")


def test_normalisation() -> None:
    print("\n[1] tag normalisation")
    check("lowercase + trim", oc.normalize_outfit_types(["  Intimate "]) == ["intimate"],
          str(oc.normalize_outfit_types(["  Intimate "])))
    check("alias beach/pool → beach",
          oc.normalize_outfit_types(["beach/pool"]) == ["beach"])
    check("alias pool → beach", oc.normalize_outfit_types(["Pool"]) == ["beach"])
    check("alias elegant → formal",
          oc.normalize_outfit_types(["elegant"]) == ["formal"])
    check("an invented tag is dropped, not kept",
          oc.normalize_outfit_types(["steampunk"]) == [],
          str(oc.normalize_outfit_types(["steampunk"])))
    check("several tags survive, order kept, duplicates removed",
          oc.normalize_outfit_types(["sport", "casual", "SPORT"])
          == ["sport", "casual"],
          str(oc.normalize_outfit_types(["sport", "casual", "SPORT"])))
    check("the vocabulary has 8 entries",
          len(oc.CANONICAL_OUTFIT_TYPES) == 8,
          str(len(oc.CANONICAL_OUTFIT_TYPES)))

    print("\n[2] normalisation runs on the SAVE path")
    pid = piece("Party shirt", ["top"], ["Elegant", "steampunk", "clubwear"])
    check("create normalises and drops",
          types_of(pid) == ["formal", "clubwear"], str(types_of(pid)))
    update_item(pid, {"outfit_piece": {"slots": ["top"],
                                       "outfit_types": ["beach/pool", "nonsense"]}})
    check("update normalises too — no smuggling past the rule",
          types_of(pid) == ["beach"], str(types_of(pid)))


def test_coherence() -> None:
    print("\n[3] the coherence rule")
    shirt = piece("Business shirt", ["top"], ["business", "formal"])
    tie = piece("Tie", ["neck"], ["business"])
    trunks = piece("Swim trunks", ["bottom"], ["beach"])
    suit_pants = piece("Suit trousers", ["bottom"], ["business", "formal"],
                       covers=["underwear_bottom"])
    boxers = piece("Boxers", ["underwear_bottom"], ["intimate"])
    plain = piece("Plain tee", ["top"], [])

    check("shared tag → coherent",
          oc.is_coherent({"top": shirt, "neck": tie}))
    check("...and the shared tag is named",
          oc.common_types({"top": shirt, "neck": tie}) == {"business"},
          str(oc.common_types({"top": shirt, "neck": tie})))
    check("disjoint tags → NOT coherent",
          not oc.is_coherent({"top": shirt, "bottom": trunks}))
    check("an untagged piece is a wildcard",
          oc.is_coherent({"top": plain, "bottom": trunks}))
    check("nothing but untagged pieces is coherent",
          oc.is_coherent({"top": plain}))
    check("a single visible piece is coherent",
          oc.is_coherent({"bottom": trunks}))

    print("\n[4] visibility decides, not the raw set")
    covered = {"top": shirt, "bottom": suit_pants, "underwear_bottom": boxers}
    check("intimate boxers UNDER covering trousers do not spoil it",
          oc.is_coherent(covered),
          str(sorted(oc.common_types(covered))))
    # The underwear partition (commit 170826f): visible underwear does NOT
    # constrain visible outerwear — an intimate waistband showing above a
    # business shirt is underwear, not a style break. Only the tagged
    # NON-underwear pieces decide, so the shirt alone carries the verdict:
    # common = {business, formal} → coherent. (Before that rule this case
    # was expected to be incoherent; the expectation, not the rule, was
    # what changed.)
    peeking = {"top": shirt, "underwear_bottom": boxers}
    check("...and VISIBLE boxers still do not — the shirt alone decides",
          oc.is_coherent(peeking) and oc.common_types(peeking) == {"business", "formal"},
          str(sorted(oc.common_types(peeking))))
    check("an intimate-only set (underwear visible) is coherent",
          oc.is_coherent({"underwear_bottom": boxers}))


def test_matching_pieces() -> None:
    """``matching_pieces`` — the soft dressing preference (CO2).

    Every expectation below is derived by hand from the rule: the reference
    is what the WORN combination stands for (``common_types``); a candidate
    matches when it shares one of those tags, and an untagged candidate is a
    wildcard that always matches.
    """
    print("\n[4b] matching pieces for the dressing hint")
    shirt = piece("Oxford shirt", ["top"], ["business"])
    slacks = piece("Grey slacks", ["bottom"], ["business"])
    hoodie = piece("Grey hoodie", ["top"], ["casual"])
    neutral = piece("White socks", ["feet"], [])
    lace = piece("Lace bra", ["underwear_top"], ["intimate"])
    briefs = piece("Briefs", ["underwear_bottom"], ["intimate"])
    trunks2 = piece("Beach trunks", ["bottom"], ["beach"])
    covering = piece("Suit trousers", ["bottom"], ["business"],
                     covers=["underwear_bottom"])

    # worn = business shirt → reference {business}. slacks share it, the
    # untagged socks are a wildcard, the casual hoodie does not.
    m, o = oc.matching_pieces({"top": shirt}, [slacks, hoodie, neutral])
    check("shares a tag with what is worn → matching",
          m == [slacks, neutral] and o == [hoodie],
          f"m={len(m)} o={len(o)}")
    check("input order survives the split",
          oc.matching_pieces({"top": shirt}, [neutral, hoodie, slacks])[0]
          == [neutral, slacks])

    # Naked: nothing to match against → no preference at all, everything
    # lands in the second group and the caller renders one flat list.
    m, o = oc.matching_pieces({}, [slacks, hoodie])
    check("naked → no preference, everything equal",
          m == [] and o == [slacks, hoodie])
    m, o = oc.matching_pieces({"feet": neutral}, [slacks, hoodie])
    check("only untagged worn → also no preference", m == [] and o == [slacks, hoodie])

    # Underwear only: the intimate set IS the reference then.
    m, o = oc.matching_pieces({"underwear_bottom": briefs}, [lace, hoodie])
    check("underwear-only outfit steers towards underwear",
          m == [lace] and o == [hoodie])

    # ...but covered underwear never steers: trousers cover the briefs, so
    # the reference is {business} and the intimate bra is NOT preferred.
    m, o = oc.matching_pieces(
        {"top": shirt, "bottom": covering, "underwear_bottom": briefs},
        [slacks, lace])
    check("covered underwear does not pull intimate pieces in",
          m == [slacks] and o == [lace])

    # Already incoherent (business + beach share nothing): no common tag, so
    # the UNION takes over — the hint still points at something worn.
    m, o = oc.matching_pieces({"top": shirt, "bottom": trunks2},
                              [slacks, trunks2, hoodie])
    check("an incoherent outfit falls back to the union of its tags",
          m == [slacks, trunks2] and o == [hoodie],
          f"m={len(m)} o={len(o)}")


def test_wardrobe_listing() -> None:
    """The dressing hint's listing (CO2 consumer) — slot coverage and the
    neutral underwear group.

    Both expectations are derived by hand:

    * A character with 22 owned pieces, naked. The inventory comes back in
      acquisition order, so a plain "first 12" cut names 12 of the 18 tops
      and NEITHER trousers NOR shoes — useless exactly when the character has
      nothing on. The listing therefore reserves candidates per bare core
      slot, so trousers and shoes must be in the text.
    * Underwear is exempt from the coherence rule (commit 170826f), so it
      must be exempt from the style warning: an intimate bra belongs in the
      separate underwear group, never in "other styles" next to a business
      outfit.
    """
    print("\n[4c] the wardrobe listing of the dressing hint")
    from app.models.character import save_character_profile
    from app.models.inventory import add_to_inventory, equip_piece
    from app.core import thought_context as TC

    who = "demo_wardrobe"
    save_character_profile(who, {"character_name": who,
                                 "current_location": "loc_a"}, create_new=True)

    def owned(name, slots, types, covers=()):
        iid = piece(name, slots, types, covers)
        add_to_inventory(who, iid)
        return iid

    # 26 tops first, the one pair of trousers and the one pair of shoes last —
    # and named so that they also lose an alphabetical tie-break. A naive cut
    # of the inventory order must miss both, otherwise the case proves nothing;
    # the check below pins exactly that.
    for n in range(26):
        owned(f"Shirt {n}", ["top"], ["casual"])
    owned("Worn jeans", ["bottom"], ["casual"])
    owned("Zipped boots", ["feet"], ["casual"])
    owned("Lace bra", ["underwear_top"], ["intimate"])
    owned("Cotton briefs", ["underwear_bottom"], ["intimate"])

    from app.models.inventory import get_character_inventory
    order = [e["item_name"] for e
             in get_character_inventory(who, include_equipped=False)["inventory"]
             if e.get("item_category") == "outfit_piece"]
    naive = order[:12]
    check("the naive first-12 cut misses trousers AND shoes (the old bug)",
          "Worn jeans" not in naive and "Zipped boots" not in naive,
          ", ".join(naive[:3]) + " …")

    naked_line = TC._build_wardrobe_choices(who)
    check("naked with 30 pieces: the trousers are offered anyway",
          "Worn jeans" in naked_line, naked_line[:90])
    check("...and the boots too — the bare feet slot is reserved for",
          "Zipped boots" in naked_line)
    check("...and the cut is spoken, not silent",
          "more piece" in naked_line)
    check("underwear rides in its own group",
          "underwear goes with any style" in naked_line
          and "Lace bra" in naked_line)

    # Dressed: a business blazer decides the style, and one business piece is
    # in the wardrobe so the matching group is non-empty. The intimate bra
    # must NOT be pushed into the warned "other styles" group.
    owned("Pinstripe trousers", ["bottom"], ["business"])
    blazer = owned("Charcoal blazer", ["top"], ["business"])
    equip_piece(who, blazer, source="smoke")
    dressed = TC._build_wardrobe_choices(who)
    other_part = dressed.split("in other styles:")[1].split(".")[0] if "in other styles:" in dressed else ""
    check("a business outfit does not warn about the intimate bra",
          "Lace bra" not in other_part, other_part[:80])
    check("...the bra is offered neutrally instead",
          "Lace bra" in dressed and "underwear goes with any style" in dressed)
    check("the matching group still exists for the dressed case",
          "matching what you have on:" in dressed, dressed[:80])


def test_creation_default() -> None:
    print("\n[5] the documented fallback")
    check("DEFAULT_OUTFIT_TYPE is part of the vocabulary",
          oc.DEFAULT_OUTFIT_TYPE in oc.CANONICAL_OUTFIT_TYPES,
          oc.DEFAULT_OUTFIT_TYPE)
    from app.skills.outfit_creation_skill import _ensure_outfit_types
    check("an empty tag list falls back to the default",
          _ensure_outfit_types([], "Thing") == [oc.DEFAULT_OUTFIT_TYPE],
          str(_ensure_outfit_types([], "Thing")))
    check("a list of only invented tags does too",
          _ensure_outfit_types(["steampunk"], "Thing") == [oc.DEFAULT_OUTFIT_TYPE])
    check("usable tags are kept as they are",
          _ensure_outfit_types(["Sport", "casual"], "Thing") == ["sport", "casual"],
          str(_ensure_outfit_types(["Sport", "casual"], "Thing")))


def test_batch_filter() -> None:
    print("\n[6] the batch filter")
    from app.core import outfit_batch as ob
    top_b = piece("Blazer", ["top"], ["business"])
    top_c = piece("Hoodie", ["top"], ["casual"])
    bottom_b = piece("Slacks", ["bottom"], ["business"])
    inv = {"inventory": [
        {"item_id": top_b, "item_name": "Blazer", "item_category": "outfit_piece",
         "outfit_piece": {"slots": ["top"]}},
        {"item_id": top_c, "item_name": "Hoodie", "item_category": "outfit_piece",
         "outfit_piece": {"slots": ["top"]}},
        {"item_id": bottom_b, "item_name": "Slacks", "item_category": "outfit_piece",
         "outfit_piece": {"slots": ["bottom"]}},
    ]}
    import app.models.inventory as invmod
    invmod.get_character_inventory = lambda name, include_equipped=True: inv
    ob.mesh_signatures = lambda name: set()

    choices, err = ob._resolve_filter(ob.combo_options("demo"), None)
    check("no filter error", err == "", err)
    every = list(ob._iter_combos(choices))
    check("3 · 2 − 1 = 5 combinations in total", len(every) == 5, str(len(every)))
    coherent = list(ob._iter_combos(choices, coherent_only=True))
    # Dropped: Hoodie+Slacks (casual vs business). Everything else is either
    # a single piece or shares "business".
    check("the filter drops the one mismatched pair",
          len(coherent) == 4, str(len(coherent)))
    check("Hoodie + Slacks is exactly what went",
          {"top": top_c, "bottom": bottom_b} not in coherent
          and {"top": top_c, "bottom": bottom_b} in every)
    check("combo_stats counts the filtered set by enumeration",
          ob.combo_stats("demo", None, False, True)["total"] == 4,
          str(ob.combo_stats("demo", None, False, True)["total"]))
    check("...and the unfiltered one arithmetically",
          ob.combo_stats("demo", None, False, False)["total"] == 5,
          str(ob.combo_stats("demo", None, False, False)["total"]))
    check("an exact total is flagged as exact",
          ob.combo_stats("demo", None, False, True)["total_exact"] is True)


def main() -> int:
    test_normalisation()
    test_coherence()
    test_matching_pieces()
    test_wardrobe_listing()
    test_creation_default()
    test_batch_filter()
    print(f"\n{CHECKED} checks, {len(FAILURES)} failure(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
