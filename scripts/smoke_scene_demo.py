#!/usr/bin/env python3
"""Whole-payload smoke of the scene recipe against a REAL world (Block M5).

Picks the location with the most floor-plan data, composes the scene exactly
as ``GET /play/locations/{id}/scene`` does (same input loading) and diffs the
top-level keys against the contract § B1 — no missing and no surplus key. It
also spot-checks the invariants that cannot be seen in a fixture: every
primitive in world metres, every model spec complete for the ONE place()
routine, every marker/exit resolved.

Usage:  ./.venv/bin/python scripts/smoke_scene_demo.py [world_dir]
        (default world_dir = worlds/demo)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Contract § B1 — the complete top-level key list of the scene payload.
CONTRACT_KEYS = {
    "signature", "rooms", "k", "storey_m", "levels", "style",
    "plates", "walls", "extras", "models",
    "figures", "markers", "exits", "outdoor_rooms",
}
SPEC_KEYS = {"role", "id", "url", "level", "fix_euler", "yaw_deg",
             "scale_mode", "anchor", "bottom_y"}

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
    from app.routes.play import _scene_inputs
    from app.core.scene_recipe import compose_scene

    def score(loc):
        rooms = [r for r in (loc.get("rooms") or []) if r.get("layout")]
        return (len(rooms), len(((loc.get("map3d") or {}).get("outline") or [])))

    locations = [l for l in list_locations()
                 if not (l.get("template_location_id") or "").strip()]
    best = max(locations, key=score) if locations else None
    if not best or score(best)[0] == 0:
        print(f"[skip] {world} has no location with a room layout")
        return 0
    loc_id = best.get("id") or ""
    print(f"\nLocation: {best.get('name')} ({loc_id}) — "
          f"{score(best)[0]} rooms with layout")

    plan_width_m, building_meta, room_metas = _scene_inputs(best, loc_id)
    print(f"  plan_width_m={plan_width_m} building_meta={bool(building_meta)} "
          f"room_metas={sorted(room_metas)}")
    sc = compose_scene(best, plan_width_m=plan_width_m,
                       building_meta=building_meta, room_metas=room_metas)

    print("\n[1] payload shape vs. contract § B1")
    check("no missing top-level key", not (CONTRACT_KEYS - set(sc)),
          str(sorted(CONTRACT_KEYS - set(sc))))
    check("no surplus top-level key", not (set(sc) - CONTRACT_KEYS),
          str(sorted(set(sc) - CONTRACT_KEYS)))
    check("signature is an md5", len(sc["signature"]) == 32)
    check("figures carry base height + the 0.12 constant",
          set(sc["figures"]) == {"base_height_m_world", "stand_clearance"}
          and sc["figures"]["stand_clearance"] == 0.12, str(sc["figures"]))

    print("\n[2] primitives")
    print(f"  {len(sc['plates'])} plates, {len(sc['walls'])} walls, "
          f"{len(sc['extras'])} extras, {len(sc['models'])} models, "
          f"{len(sc['markers'])} markers, {len(sc['exits'])} exits")
    check("plates carry level/outline/top_y/thickness",
          all({"level", "outline", "top_y", "thickness", "opacity_role"}
              <= set(p) for p in sc["plates"]))
    check("walls carry from/to/base_y/height/thickness/normal",
          all({"level", "from", "to", "base_y", "height", "thickness",
               "opacity_role", "outward_normal"} <= set(w)
              for w in sc["walls"]))
    coords = [c for w in sc["walls"] for c in (w["from"] + w["to"])]
    check("every wall coordinate is inside the 10 m tile",
          all(abs(c) <= 5.0 for c in coords),
          f"max |c| = {max((abs(c) for c in coords), default=0)}")
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
    check("scale modes are the three contract ones",
          {m["scale_mode"] for m in sc["models"]}
          <= {"fit_box", "real_size", "tile_fit"},
          str({m["scale_mode"] for m in sc["models"]}))
    check("real_size specs carry max_m, fit_box/tile_fit carry box",
          all(("max_m" in m) if m["scale_mode"] == "real_size" else ("box" in m)
              for m in sc["models"]))
    check("a room is never diorama AND furnished at once",
          not ({m["room_id"] for m in sc["models"] if m["role"] == "room"}
               & {m["room_id"] for m in sc["models"] if m["role"] == "prop"}))
    check("markers are resolved to world coordinates",
          all({"room_id", "at_world", "y_world", "animation", "source"}
              <= set(m) for m in sc["markers"]))
    check("exits are resolved to world coordinates",
          all({"room_id", "at_world"} <= set(e) for e in sc["exits"]))

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
