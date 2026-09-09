#!/usr/bin/env python3
"""Whole-payload smoke of the scene recipe against a REAL world (Block M5).

Picks the location with the most floor-plan data, composes the scene exactly
as ``GET /play/locations/{id}/scene`` does (same input loading) and diffs the
top-level keys against the contract § B1 — no missing and no surplus key. It
also spot-checks the invariants that cannot be seen in a fixture: every
primitive in world metres, every model spec complete for the ONE place()
routine, every marker/doorway resolved.

Usage:  ./.venv/bin/python scripts/smoke_scene_demo.py [world_dir]
        (default world_dir = worlds/demo)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Contract § B1 — the top-level key list of the scene payload, read off the
# spec block in docs/schnittstellen-3d.md § B1 (not off a run): the eighteen
# keys the composer ALWAYS answers with. ``exits`` used to be here and is
# gone — a location's ways out are ``doorways[]`` (the finished thresholds of
# plan-betreten-und-tueren.md § 4.1) and ``boundary_openings[]`` (§ B1 Nr. 13)
# now, and a "no missing key" check for a key nobody writes is a check that
# can only fail.
CONTRACT_KEYS = {
    "signature", "rooms", "boundary", "extent_m", "k", "storey_m", "levels",
    "style", "plates", "floor_plan", "walls", "extras", "stairs", "models",
    "figures", "markers", "doorways", "outdoor_rooms", "problems",
    # One anchor per storey corridor (§ 3.2) — always there, empty where a
    # location has no corridor room or no footprint to put one in.
    "corridors",
}
# Present only when the data calls for them: a location without a drawn
# boundary opening ships no ``boundary_openings``, and only an area location
# in detail mode ships ``area_detail``.
OPTIONAL_KEYS = {"boundary_openings", "area_detail"}
SPEC_KEYS = {"role", "id", "variants", "level", "fix_euler", "yaw_deg",
             "max_m", "measure", "anchor", "bottom_y"}

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    world = sys.argv[1] if len(sys.argv) > 1 else "worlds/demo"
    import app.core.paths as paths
    paths.init(world)
    try:
        from app.core import config
        config.load(paths.get_config_path())
    except Exception as e:
        print(f"[warn] config.load failed (continuing): {e}")

    from app.models.world import list_locations
    from app.core.scene_recipe import compose_scene, scene_inputs

    def score(loc):
        rooms = [r for r in (loc.get("rooms") or []) if r.get("layout")]
        return (len(rooms), len(((loc.get("map3d") or {}).get("outline") or [])))

    locations = list_locations()
    best = max(locations, key=score) if locations else None
    if not best or score(best)[0] == 0:
        print(f"[skip] {world} has no location with a room layout")
        return 0
    loc_id = best.get("id") or ""
    print(f"\nLocation: {best.get('name')} ({loc_id}) — "
          f"{score(best)[0]} rooms with layout")

    plan_width_m, building_meta, room_metas = scene_inputs(best, loc_id)
    print(f"  plan_width_m={plan_width_m} building_meta={bool(building_meta)} "
          f"room_metas={sorted(room_metas)}")
    sc = compose_scene(best, plan_width_m=plan_width_m,
                       building_meta=building_meta, room_metas=room_metas)

    print("\n[1] payload shape vs. contract § B1")
    check("no missing top-level key", not (CONTRACT_KEYS - set(sc)),
          str(sorted(CONTRACT_KEYS - set(sc))))
    check("no surplus top-level key",
          not (set(sc) - CONTRACT_KEYS - OPTIONAL_KEYS),
          str(sorted(set(sc) - CONTRACT_KEYS - OPTIONAL_KEYS)))
    check("signature is an md5", len(sc["signature"]) == 32)
    check("figures carry base height + the 0.12 constant",
          set(sc["figures"]) == {"base_height_m_world", "stand_clearance"}
          and sc["figures"]["stand_clearance"] == 0.12, str(sc["figures"]))

    print("\n[2] primitives")
    print(f"  {len(sc['plates'])} plates, {len(sc['walls'])} walls, "
          f"{len(sc['extras'])} extras, {len(sc['models'])} models, "
          f"{len(sc['markers'])} markers, {len(sc['doorways'])} doorways")
    check("plates carry level/outline/top_y/thickness",
          all({"level", "outline", "top_y", "thickness", "opacity_role"}
              <= set(p) for p in sc["plates"]))
    check("walls carry from/to/base_y/height/thickness/normal",
          all({"level", "from", "to", "base_y", "height", "thickness",
               "opacity_role", "outward_normal"} <= set(w)
              for w in sc["walls"]))
    # The scene frame is the LOCAL frame around the location's anchor pin and
    # ``extent_m`` is the width of its bounding box (§ B1 Nr. 2), so half of it
    # is the furthest any primitive of this location may reach from the origin.
    # The old bound here was the flat 5.0 of the 10 m grid tile — the tile is
    # gone since the seamless metre world (E4: extent_m = plan_width_m, k = 1),
    # and a location wider than 10 m failed a rule that no longer exists.
    limit = float(sc["extent_m"]) / 2.0
    coords = [c for w in sc["walls"] for c in (w["from"] + w["to"])]
    check("every wall coordinate is inside the location's own extent",
          all(abs(c) <= limit + 1e-6 for c in coords),
          f"max |c| = {max((abs(c) for c in coords), default=0)} of {limit}")
    check("no wall is taller than a storey",
          all(w["height"] <= sc["storey_m"] + 1e-6 for w in sc["walls"]))
    check("opacity roles are ground/upper only",
          {p["opacity_role"] for p in sc["plates"]}
          | {w["opacity_role"] for w in sc["walls"]} <= {"ground", "upper"})

    print("\n[3] placement specs")
    check("every spec has the full place() input",
          all(SPEC_KEYS <= set(m) for m in sc["models"]),
          str([sorted(SPEC_KEYS - set(m)) for m in sc["models"]
               if not SPEC_KEYS <= set(m)][:3]))
    # ONE scale law since v6 Nr. 3: every spec is a real width plus the axes
    # it is measured on. `scale_mode`/`box`/`tile_fit` do not exist any more.
    check("measures are the three contract ones",
          {m["measure"] for m in sc["models"]}
          <= {"yawed_xz", "xz", "xyz"},
          str({m["measure"] for m in sc["models"]}))
    check("every spec carries a positive real width, no per-axis leftovers",
          all(float(m.get("max_m") or 0) > 0
              and not {"box", "scale_mode", "scale_axes"} & set(m)
              for m in sc["models"]))
    check("a room is never diorama AND furnished at once",
          not ({m["room_id"] for m in sc["models"] if m["role"] == "room"}
               & {m["room_id"] for m in sc["models"] if m["role"] == "prop"}))
    check("markers are resolved to world coordinates",
          all({"room_id", "id", "group", "label", "capacity", "at_world",
               "slots", "y_world", "root_offset", "source"}
              <= set(m) and len(m["slots"]) == m["capacity"]
              for m in sc["markers"]))
    check("doorways are resolved to world coordinates",
          all({"level", "at_world", "along", "type", "width_m", "height_m",
               "base_y", "rooms", "outside"} <= set(d) for d in sc["doorways"]))

    print("\n[4] stability")
    again = compose_scene(best, plan_width_m=plan_width_m,
                          building_meta=building_meta, room_metas=room_metas)
    check("composing twice gives the same signature",
          again["signature"] == sc["signature"])
    check("...and the same primitive counts",
          (len(again["walls"]), len(again["plates"]), len(again["models"]))
          == (len(sc["walls"]), len(sc["plates"]), len(sc["models"])))

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
