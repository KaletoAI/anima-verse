#!/usr/bin/env python3
"""Smoke: pure item placement module (surface pick, floor fallback, rotation, no overlap).

Usage:
    ./.venv/bin/python scripts/smoke_item_placement.py

Runs without the server. Pure checks [a]-[e], [g] use hand-built RoomGeo dicts;
check [f] initialises a temporary storage dir via paths.init() before importing
any world-DB module.

Hand-derived expectations (4 x 3 m rectangle [[0,0],[4,0],[4,3],[0,3]],
table T at [1,1] 1.2 x 0.8 m surface_y=0.75, shelf S at [3,2.5] 0.8 x 0.4 m
surface_y=None):
[a] compute_anchor("key", 0.1, geo, []):
    r = 0.05; T is the only surface candidate, hw = 0.6 - (0.05 + 0.05) = 0.5,
    hd = 0.4 - (0.05 + 0.05) = 0.3. Result has on == "T", y == 0.75,
    |x - 1| <= 0.5 and |z - 1| <= 0.3.
[b] Calling compute_anchor("key", 0.1, geo, []) twice returns identical dicts.
[c] Placing ten items "i0".."i9" of size 0.3 (r = 0.15) sequentially, each
    seeing all previous anchors as occupied spots (r = 0.15):
    - all 10 receive an anchor;
    - pairwise centre distances are all >= 0.3 - 1e-9;
    - T's inner half-extents are hw = 0.6 - 0.2 = 0.4 and hd = 0.4 - 0.2 = 0.2
      (0.8 x 0.4 m area), so only a few 0.3 m items fit on T and every anchor
      on T satisfies y == 0.75, |x - 1| <= 0.4, |z - 1| <= 0.2;
    - the remaining items fall back to the floor with on == "", y == 0.0,
      inside the outline, edge distance in [0.2, 1.0], and distance to both
      T and S rectangles >= 0.15 + 0.1 = 0.25.
[d] T with a child covering its full top ([1,1], yaw 0, 1.2 x 0.8):
    every grid point on T overlaps the child -> item falls back to floor
    (on == "", y == 0.0).
[e] T rotated by yaw = 90 (local +x width runs along -z, local +z depth runs
    along +x): the accepted point for "key" (size 0.1) has on == "T", y == 0.75,
    and transformed into T's local frame (dx = -(z - 1), dz = x - 1) satisfies
    |dx| <= 0.5 and |dz| <= 0.3.
[f] room_geometry(loc, room_id) for a room without a layout (created in a temp
    world via upsert_location) returns None.
[g] Geometry with T too small (width_m = 0.15, hw = 0.075 - 0.175 < 0 for
    size 0.25) and a 0.3 x 0.3 outline (max edge distance 0.15 < r + 0.05 =
    0.175) returns None.
"""

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.item_placement import (
    _circle_hits_rect,
    _edge_distance,
    _to_local,
    compute_anchor,
    room_geometry,
)
from app.core.world_geometry import point_in_polygon

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    status = "OK  " if ok else "FAIL"
    suffix = f": {detail}" if detail else ""
    print(f"  {status} {label}{suffix}")
    if not ok:
        FAILURES.append(label)


def _base_geo():
    return {
        "outline": [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]],
        "props": [
            {
                "id": "T",
                "at": [1.0, 1.0],
                "yaw": 0.0,
                "width_m": 1.2,
                "depth_m": 0.8,
                "surface_y": 0.75,
                "children": [],
            },
            {
                "id": "S",
                "at": [3.0, 2.5],
                "yaw": 0.0,
                "width_m": 0.8,
                "depth_m": 0.4,
                "surface_y": None,
                "children": [],
            },
        ],
    }


def main() -> int:
    eps = 1e-9

    # [a] Key on table T
    print("[a] Key (0.1 m) lands on table T within shrunk top")
    geo = _base_geo()
    a = compute_anchor("key", 0.1, geo, [])
    check("[a] anchor not None", a is not None, repr(a))
    if a is not None:
        x, z = a["at"]
        check("[a] on == 'T'", a["on"] == "T", repr(a["on"]))
        check("[a] y == 0.75", a["y"] == 0.75, repr(a["y"]))
        check("[a] |x - 1| <= 0.5", abs(x - 1.0) <= 0.5 + eps, f"x={x}")
        check("[a] |z - 1| <= 0.3", abs(z - 1.0) <= 0.3 + eps, f"z={z}")

    # [b] Determinism
    print("[b] Determinism: identical result on repeated call")
    a2 = compute_anchor("key", 0.1, geo, [])
    check("[b] identical dicts", a == a2, f"{a!r} vs {a2!r}")

    # [c] Ten items of size 0.3 placed sequentially
    print("[c] Ten items i0..i9 (0.3 m) placed sequentially without overlap")
    occupied = []
    anchors = []
    for k in range(10):
        res = compute_anchor(f"i{k}", 0.3, geo, occupied)
        anchors.append(res)
        if res is not None:
            occupied.append({"at": res["at"], "r": 0.15})

    check("[c] all 10 placed", all(x is not None for x in anchors), f"{sum(x is not None for x in anchors)}/10")
    valid_anchors = [x for x in anchors if x is not None]

    min_pair = math.inf
    for i in range(len(valid_anchors)):
        for j in range(i + 1, len(valid_anchors)):
            d = math.hypot(
                valid_anchors[i]["at"][0] - valid_anchors[j]["at"][0],
                valid_anchors[i]["at"][1] - valid_anchors[j]["at"][1],
            )
            if d < min_pair:
                min_pair = d
    check("[c] pairwise distance >= 0.3", min_pair >= 0.3 - eps, f"min={min_pair:.6f}")

    on_table = [x for x in valid_anchors if x["on"] == "T"]
    on_floor = [x for x in valid_anchors if x["on"] == ""]
    check("[c] some on T and some on floor", len(on_table) > 0 and len(on_floor) > 0,
          f"table={len(on_table)}, floor={len(on_floor)}")

    table_ok = all(
        x["y"] == 0.75
        and abs(x["at"][0] - 1.0) <= 0.4 + eps
        and abs(x["at"][1] - 1.0) <= 0.2 + eps
        for x in on_table
    )
    check("[c] table anchors inside 0.8x0.4 inner area at y=0.75", table_ok, repr(on_table))

    prop_t, prop_s = geo["props"][0], geo["props"][1]
    floor_ok = True
    floor_err = ""
    for x in on_floor:
        px, pz = x["at"]
        d_edge = _edge_distance(px, pz, geo["outline"])
        inside = point_in_polygon(px, pz, geo["outline"])
        hits_t = _circle_hits_rect(px, pz, 0.15, prop_t, 0.1)
        hits_s = _circle_hits_rect(px, pz, 0.15, prop_s, 0.1)
        if not (x["y"] == 0.0 and inside and 0.2 - eps <= d_edge <= 1.0 + eps and not hits_t and not hits_s):
            floor_ok = False
            floor_err = f"anchor={x}, inside={inside}, d_edge={d_edge}, hits_t={hits_t}, hits_s={hits_s}"
            break
    check("[c] floor anchors valid, near wall, clear of T and S", floor_ok, floor_err or f"{len(on_floor)} ok")

    # [d] Full-coverage child on T -> floor
    print("[d] Child covering all of T forces floor fallback")
    geo_blocked = _base_geo()
    geo_blocked["props"][0]["children"] = [
        {"at": [1.0, 1.0], "yaw": 0.0, "width_m": 1.2, "depth_m": 0.8}
    ]
    d_res = compute_anchor("key", 0.1, geo_blocked, [])
    check("[d] anchor not None", d_res is not None, repr(d_res))
    if d_res is not None:
        check("[d] on == ''", d_res["on"] == "", repr(d_res["on"]))
        check("[d] y == 0.0", d_res["y"] == 0.0, repr(d_res["y"]))

    # [e] Rotated table T (yaw = 90)
    print("[e] Rotated table T (yaw = 90) local-frame bounds")
    geo_rot = _base_geo()
    geo_rot["props"][0]["yaw"] = 90.0
    e_res = compute_anchor("key", 0.1, geo_rot, [])
    check("[e] anchor not None", e_res is not None, repr(e_res))
    if e_res is not None:
        ex, ez = e_res["at"]
        dx, dz = _to_local(1.0, 1.0, 90.0, ex, ez)
        # Hand-derived transpose at yaw=90: dx = -(z - 1), dz = x - 1
        check("[e] on == 'T'", e_res["on"] == "T", repr(e_res["on"]))
        check("[e] y == 0.75", e_res["y"] == 0.75, repr(e_res["y"]))
        check("[e] |dx| <= 0.5", abs(dx) <= 0.5 + eps, f"dx={dx:.4f} (expected -(z-1)={-(ez-1.0):.4f})")
        check("[e] |dz| <= 0.3", abs(dz) <= 0.3 + eps, f"dz={dz:.4f} (expected x-1={ex-1.0:.4f})")

    # [f] room_geometry of a room without a layout -> None
    print("[f] room_geometry of a room without a layout returns None")
    with tempfile.TemporaryDirectory(prefix="item-placement-") as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.models.world import upsert_location

        loc = {
            "id": "loc_no_layout",
            "name": "Bare Place",
            "rooms": [
                {"id": "room_bare", "name": "Bare Room", "items": []},
            ],
        }
        saved = upsert_location(loc, sync_world=False)
        check("[f] upsert_location succeeded", saved is True, repr(saved))
        rg = room_geometry(loc, "room_bare")
        check("[f] room_geometry is None", rg is None, repr(rg))

    # [g] Tiny table + tiny room -> None
    print("[g] Tiny table (0.15 m) and tiny outline (0.3 x 0.3 m) -> None")
    geo_tiny = {
        "outline": [[0.0, 0.0], [0.3, 0.0], [0.3, 0.3], [0.0, 0.3]],
        "props": [
            {
                "id": "T",
                "at": [0.15, 0.15],
                "yaw": 0.0,
                "width_m": 0.15,
                "depth_m": 0.15,
                "surface_y": 0.75,
                "children": [],
            },
        ],
    }
    g_res = compute_anchor("key", 0.25, geo_tiny, [])
    check("[g] compute_anchor returns None", g_res is None, repr(g_res))

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
