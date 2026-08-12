#!/usr/bin/env python3
"""Smoke run for the outfit-COMBINATION batch (Block O).

Checks the arithmetic and the filter of app/core/outfit_batch.py against a
stubbed inventory — no world, no DB, no renderer. The point is the counting:
the real numbers reach seven digits, so a wrong product or a forgotten
"minus the empty combination" would be invisible in the UI but very visible
in the queue.

Usage:  ./.venv/bin/python scripts/smoke_outfit_combos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import outfit_batch as ob  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# Three slots with 2, 1 and 3 pieces — the fixture the task sheet names.
INVENTORY = {"inventory": [
    {"item_id": "shirt", "item_name": "Shirt", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["top"]}},
    {"item_id": "vest", "item_name": "Vest", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["top", "over"]}},
    {"item_id": "jeans", "item_name": "Jeans", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["bottom"]}},
    {"item_id": "boots", "item_name": "Boots", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["feet"]}},
    {"item_id": "shoes", "item_name": "Shoes", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["feet"]}},
    {"item_id": "socks", "item_name": "Socks", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["feet"]}},
    # Ignored: not an outfit piece, and a piece without a slot.
    {"item_id": "sword", "item_name": "Sword", "item_category": "tool"},
    {"item_id": "charm", "item_name": "Charm", "item_category": "outfit_piece",
     "outfit_piece": {"slots": []}},
]}


def stub(inventory=None, meshes=(), durations=None) -> None:
    """Replaces the three doors to the outside world."""
    data = INVENTORY if inventory is None else inventory
    import app.models.inventory as inv
    inv.get_character_inventory = lambda name, include_equipped=True: data
    ob._mesh_signatures = lambda name: set(meshes)
    ob._query_tasks = lambda sql, params=(): [
        {"duration_s": d} for d in (durations or [])]


def test_options() -> None:
    print("\n[1] combo_options")
    stub()
    opts = ob.combo_options("demo")
    check("only outfit pieces with a slot, grouped by the FIRST slot",
          sorted(opts) == ["bottom", "feet", "top"], str(sorted(opts)))
    check("the vest lands in 'top', not in 'over'",
          [p["item_id"] for p in opts["top"]] == ["shirt", "vest"],
          str([p["item_id"] for p in opts["top"]]))
    check("pieces sorted by name",
          [p["name"] for p in opts["feet"]] == ["Boots", "Shoes", "Socks"],
          str([p["name"] for p in opts["feet"]]))


def test_counting() -> None:
    print("\n[2] counting — arithmetic, never enumerated")
    stub()
    st = ob.combo_stats("demo")
    # top 2+empty = 3, bottom 1+empty = 2, feet 3+empty = 4 → 24, minus the
    # all-empty combination = 23.
    check("total = 3 · 2 · 4 − 1 = 23", st["total"] == 23, str(st["total"]))
    check("nothing cached → missing == total", st["missing"] == 23,
          str(st["missing"]))
    check("and the count is exact at this size", st["missing_exact"] is True)

    enumerated = list(ob._iter_combos(
        ob._resolve_filter(ob.combo_options("demo"), None)[0]))
    check("the lazy enumeration yields exactly as many",
          len(enumerated) == 23, str(len(enumerated)))
    check("no combination is empty", all(bool(p) for p in enumerated))
    check("every combination is unique",
          len({tuple(sorted(p.items())) for p in enumerated}) == 23)


def test_filter() -> None:
    print("\n[3] the filter reduces correctly")
    stub()
    # feet fixed to Boots (no empty), top only empty, bottom untouched.
    st = ob.combo_stats("demo", {"feet": ["boots"], "top": [None]})
    check("1 · 2 · 1 = 2 (nothing all-empty reachable → no −1)",
          st["total"] == 2, str(st["total"]))
    st2 = ob.combo_stats("demo", {"feet": ["boots", None]})
    check("feet 2 options → 3 · 2 · 2 − 1 = 11", st2["total"] == 11,
          str(st2["total"]))
    bad = ob.combo_stats("demo", {"feet": []})
    check("an empty slot list is an error, not a silent 'all'",
          bad["error"] != "" and bad["total"] == 0, bad["error"])
    unknown = ob.combo_stats("demo", {"feet": ["sandals"]})
    check("an unknown piece is rejected", unknown["error"] != "",
          unknown["error"])
    bad_slot = ob.combo_stats("demo", {"hat": ["boots"]})
    check("an unknown slot is rejected", bad_slot["error"] != "",
          bad_slot["error"])


def test_cache_skip() -> None:
    print("\n[4] cached combinations count as done")
    stub()
    all_sigs = [ob._signature(p) for p in ob._iter_combos(
        ob._resolve_filter(ob.combo_options("demo"), None)[0])]
    stub(meshes=all_sigs[:5])
    st = ob.combo_stats("demo")
    check("5 meshes present → 18 missing of 23", st["missing"] == 18,
          str(st["missing"]))
    forced = ob.combo_stats("demo", None, True)
    check("force ignores the cache: missing == total", forced["missing"] == 23,
          str(forced["missing"]))
    check("...and is exact by definition", forced["missing_exact"] is True)


def test_big() -> None:
    print("\n[5] big sets: exact count is dropped, not attempted")
    # 7 slots x 4 pieces each -> 5^7 - 1 = 78,124 combinations.
    big = {"inventory": [
        {"item_id": f"{slot}{i}", "item_name": f"{slot} {i}",
         "item_category": "outfit_piece", "outfit_piece": {"slots": [slot]}}
        for slot in ("top", "bottom", "feet", "head", "hands", "over", "under")
        for i in range(4)]}
    stub(inventory=big)
    st = ob.combo_stats("demo")
    check("total = 5^7 − 1 = 78124", st["total"] == 78124, str(st["total"]))
    check("above the 5000 cap the missing count is an upper bound",
          st["missing_exact"] is False and st["missing"] == st["total"],
          f"exact={st['missing_exact']} missing={st['missing']}")
    check("...and just under the cap it is exact again",
          ob.combo_stats("demo", {"under": ["under0"], "over": ["over0"],
                                  "hands": ["hands0"]})["missing_exact"] is True)


def test_estimate() -> None:
    print("\n[6] time estimate")
    stub(durations=[])
    check("no history → the fallback per combination",
          abs(ob.estimate_seconds_per_combo() - ob.FALLBACK_SECONDS_PER_COMBO) < 1e-6,
          str(ob.estimate_seconds_per_combo()))
    stub(durations=[100.0, 200.0, 300.0])
    per = ob.estimate_seconds_per_combo()
    check("average mesh duration + the T-pose allowance",
          abs(per - (200.0 + ob.TPOSE_SECONDS)) < 1e-6, str(per))
    st = ob.combo_stats("demo")
    check("estimated seconds = missing × per combination",
          abs(st["est_seconds"] - 23 * per) < 0.1,
          f"{st['est_seconds']} vs {23 * per}")


def test_label() -> None:
    print("\n[7] combination label")
    stub()
    names = {p["item_id"]: p["name"]
             for pieces in ob.combo_options("demo").values() for p in pieces}
    label = ob._combo_label({"top": "shirt", "feet": "boots"}, names)
    check("slots sorted, piece NAMES not ids",
          label == "feet: Boots · top: Shirt", label)


def main() -> int:
    test_options()
    test_counting()
    test_filter()
    test_cache_skip()
    test_big()
    test_estimate()
    test_label()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
