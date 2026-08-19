#!/usr/bin/env python3
"""Smoke run for a prop's MODEL VARIANTS (E2.3, § B2-Nachtrag).

No world, no DB, no server: a throwaway props directory in /tmp gets prop
records and GLB stubs written through the real store, and the store plus the
scene composer are asked what they answer. Every expected value is derived BY
HAND from the contract (docs/schnittstellen-3d.md, "Nachtrag 2026-08-19 (§ B2)"),
never from what the code currently prints:

  - a prop without the variant key has exactly ONE variant, the primary one,
    and every unqualified read still resolves to it;
  - generating APPENDS: the first mesh fills the existing empty slot, the
    second one a fresh variant, and at the cap the last variant takes it;
  - the cap is on ACTIVE variants and comes from
    `image_generation.prop_variant_max` (default 4);
  - `variants == model_variants[0]` on every placement spec — the primary
    variant contract that keeps unchanged consumers rendering;
  - the primary variant keeps its bare URL, a further one carries
    `?variant=<i>&tier=<t>` (ONE `?`, then `&`) — and `<i>` is the variant's
    OWN store index, not its position, so switching variant 1 off must leave
    the second payload entry pointing at `?variant=2`;
  - the scatter formula is `(scatter_seed + instance) mod count`. HAND
    CALCULATION with 3 active variants and scatter_seed 7, instances 0…5:

        (7 + 0) mod 3 = 7 mod 3  = 1
        (7 + 1) mod 3 = 8 mod 3  = 2
        (7 + 2) mod 3 = 9 mod 3  = 0
        (7 + 3) mod 3 = 10 mod 3 = 1
        (7 + 4) mod 3 = 11 mod 3 = 2
        (7 + 5) mod 3 = 12 mod 3 = 0

    → 1, 2, 0, 1, 2, 0.

Usage:  ./.venv/bin/python scripts/smoke_prop_variants.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-variants-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402
from app.core.model_store import write_sidecar  # noqa: E402
from app.core.scene_recipe import _prop_models  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def put_mesh(prop_id: str, variant, tier: str = "full") -> str:
    """A stored GLB stub in ONE variant's gallery, selected for ``tier``.

    Deliberately NOT through the generation chain: this smoke is about the
    variant bookkeeping, and a GPU job has no place in it. The bytes are a
    stub, so nothing here may measure them (the store only measures the
    PRIMARY variant, and a stub simply yields no bbox)."""
    g = store.model_gallery(prop_id, variant)
    assert g is not None
    p = g.new_path()
    p.write_bytes(b"glTF-stub")
    write_sidecar(p, {"created_at": "2026-08-19T10:00:00+00:00",
                      "source": "upload", "format": "glb", "tier": tier})
    g.select(p.name, tier)
    return p.name


def placement(prop_id: str, **extra) -> dict:
    """A room-recipe placement of one prop, as `_prop_models` receives it."""
    prop = store.get_prop(prop_id) or {}
    entry = {
        "prop_id": prop_id,
        "at": [1.0, 2.0],
        "yaw": 0.0,
        "offset_y": 0.0,
        "has_model": bool(prop.get("has_model")),
        "dims": {"width_m": prop.get("width_m", 1.0),
                 "depth_m": prop.get("depth_m", 1.0),
                 "height_m": prop.get("height_m", 1.0)},
        "model_tiers": prop.get("model_tiers") or [],
        "variant_tiers": prop.get("variant_tiers") or [],
    }
    entry.update(extra)
    return entry


def spec_of(prop_id: str, **extra) -> dict:
    """The finished placement spec the payload carries for one placement."""
    recipe = {"room_id": "r1", "level": 0, "always_visible": True,
              "placements": [placement(prop_id, **extra)]}
    return _prop_models(recipe, 0.0)[0]


def main() -> int:
    print("\n[1] a prop without the key has ONE variant — the primary one")
    pine = store.create_prop(name="Pine")["id"]
    vs = store.list_variants(pine)
    check("exactly one variant", len(vs) == 1, str(vs))
    check("it is stem 'model' — the historic file name", vs[0]["stem"] == "model")
    check("it is active and primary", vs[0]["active"] and vs[0]["primary"])
    check("primary_variant() is 0", store.primary_variant(pine) == 0)
    check("no mesh yet, so no tiers", vs[0]["tiers"] == [], str(vs[0]["tiers"]))

    print("\n[2] generating APPENDS: empty slot first, then fresh variants")
    check("the first target is the EXISTING empty slot 0",
          store.target_variant(pine) == 0, str(store.target_variant(pine)))
    put_mesh(pine, 0)
    check("...and slot 0 now carries the mesh",
          store.model_tiers(pine, 0) == ["full"], str(store.model_tiers(pine, 0)))
    nxt = store.target_variant(pine)
    check("the NEXT target is a freshly appended variant 1", nxt == 1, str(nxt))
    put_mesh(pine, 1)
    put_mesh(pine, store.target_variant(pine))
    check("three variants exist", len(store.list_variants(pine)) == 3,
          str([v["stem"] for v in store.list_variants(pine)]))
    check("their stems are model / model-v2 / model-v3",
          [v["stem"] for v in store.list_variants(pine)]
          == ["model", "model-v2", "model-v3"],
          str([v["stem"] for v in store.list_variants(pine)]))
    check("...and every stem has its OWN file, none shared",
          len({store.model_path(pine, variant=i).name for i in range(3)}) == 3)

    print("\n[3] the cap is on ACTIVE variants (config default 4)")
    check("variant_max() is 4", store.variant_max() == 4, str(store.variant_max()))
    put_mesh(pine, store.target_variant(pine))          # fills variant 3
    check("four variants now", len(store.list_variants(pine)) == 4)
    at_cap = store.target_variant(pine)
    check("at the cap the target is the LAST variant, not a fifth one",
          at_cap == 3, str(at_cap))
    check("add_variant() refuses at the cap", store.add_variant(pine) == -1)
    check("...and no fifth variant was written",
          len(store.list_variants(pine)) == 4)
    check("switching one off frees a slot again",
          store.set_variant_active(pine, 3, False)
          and store.add_variant(pine) == 4)
    check("...leaving 5 records but only 4 active",
          len(store.list_variants(pine)) == 5
          and sum(1 for v in store.list_variants(pine) if v["active"]) == 4)
    store.delete_variant(pine, 4)
    store.set_variant_active(pine, 3, True)

    print("\n[4] the last active variant cannot be switched off or deleted")
    stool = store.create_prop(name="Stool")["id"]
    put_mesh(stool, 0)
    check("switching the only variant off is refused",
          not store.set_variant_active(stool, 0, False))
    check("deleting the only variant is refused",
          not store.delete_variant(stool, 0))
    check("...and it is still there with its mesh",
          store.model_tiers(stool, 0) == ["full"])

    print("\n[5] payload: variants == model_variants[0], primary URL unchanged")
    fern = store.create_prop(name="Fern")["id"]
    put_mesh(fern, 0)
    put_mesh(fern, 0, tier="low")
    put_mesh(fern, store.target_variant(fern))
    check("the record lists tiers per active variant, with its store index",
          (store.get_prop(fern) or {}).get("variant_tiers")
          == [{"variant": 0, "tiers": ["full", "low"]},
              {"variant": 1, "tiers": ["full"]}],
          str((store.get_prop(fern) or {}).get("variant_tiers")))
    spec = spec_of(fern)
    check("model_variants has one map per active variant",
          len(spec.get("model_variants") or []) == 2,
          str(spec.get("model_variants")))
    check("variants IS model_variants[0] (the primary variant contract)",
          spec["variants"] == spec["model_variants"][0], str(spec["variants"]))
    check("the primary variant keeps the BARE url + ?tier=",
          spec["variants"] == {"full": f"/assets/props/{fern}/model?tier=full",
                               "low": f"/assets/props/{fern}/model?tier=low"},
          str(spec["variants"]))
    check("a further variant carries ?variant=<i>&tier=<t> — one '?', then '&'",
          spec["model_variants"][1]
          == {"full": f"/assets/props/{fern}/model?variant=1&tier=full"},
          str(spec["model_variants"][1]))
    check("an unqualified placement shows the primary variant",
          spec.get("variant") == 0, str(spec.get("variant")))

    print("\n[6] a ONE-variant prop's spec is unchanged — no new fields")
    one = spec_of(stool)
    check("no model_variants field", "model_variants" not in one, str(one.keys()))
    check("no variant field", "variant" not in one)
    check("variants is the plain tier map",
          one["variants"] == {"full": f"/assets/props/{stool}/model?tier=full"},
          str(one["variants"]))

    print("\n[7] the scatter formula — hand calculation in the docstring")
    expected = [1, 2, 0, 1, 2, 0]
    got = [store.scatter_variant_index(7, i, 3) for i in range(6)]
    check("seed 7, 3 variants, instances 0..5 -> 1,2,0,1,2,0",
          got == expected, f"{got} vs {expected}")
    check("count 0 (a prop with no mesh) answers 0, never a division",
          store.scatter_variant_index(7, 3, 0) == 0)
    check("count 1 always answers 0",
          [store.scatter_variant_index(7, i, 1) for i in range(4)] == [0, 0, 0, 0])
    # …and the resolved index reaches the spec: three variants, seed 7.
    put_mesh(fern, store.target_variant(fern))          # fern now has 3
    check("fern has three active variants now",
          len((store.get_prop(fern) or {}).get("variant_tiers") or []) == 3)
    scattered = [spec_of(fern, scattered=True,
                         variant=store.scatter_variant_index(7, i, 3))["variant"]
                 for i in range(6)]
    check("the spec carries exactly those indices", scattered == expected,
          f"{scattered} vs {expected}")
    check("an out-of-range index WRAPS instead of dropping the placement",
          spec_of(fern, variant=5)["variant"] == 2,
          str(spec_of(fern, variant=5)["variant"]))

    print("\n[8] switching a variant off removes it from the payload")
    store.set_variant_active(fern, 1, False)
    off = spec_of(fern)
    check("two variants left in the payload",
          len(off["model_variants"]) == 2, str(off["model_variants"]))
    check("...and the primary one is untouched",
          off["variants"] == spec["variants"], str(off["variants"]))
    check("the remaining second map is variant 2's url",
          off["model_variants"][1]
          == {"full": f"/assets/props/{fern}/model?variant=2&tier=full"},
          str(off["model_variants"][1]))

    print("\n[9] deleting a variant takes its files, not its neighbour's")
    keep = store.model_path(fern, variant=2)
    check("variant 1's file exists before the delete",
          store.model_path(fern, variant=1) is not None)
    gone = store.model_path(fern, variant=1)
    check("delete_variant succeeds", store.delete_variant(fern, 1))
    check("...its file is gone", not gone.exists())
    check("...the neighbour's file is untouched", keep.exists())
    check("...and the list is two records long",
          [v["stem"] for v in store.list_variants(fern)] == ["model", "model-v3"],
          str([v["stem"] for v in store.list_variants(fern)]))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(WORLD, ignore_errors=True)
