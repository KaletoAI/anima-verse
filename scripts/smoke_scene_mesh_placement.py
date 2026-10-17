#!/usr/bin/env python3
"""Check scene-frame meshes against the building placement law by hand.

Usage: ./.venv/bin/python scripts/smoke_scene_mesh_placement.py

Boundary (-4,-2)..(16,10) has bbox centre (6,4). Mesh bounds
(0,0.5,0)..(10,7,8) have XZ centre (5,4), width max(10,8)=10,
and bottom 0.5. Offsets are (5-6,4-4)=(-1,0), y=0.5.
The building law restores anchor (6-1,4+0)=(5,4), bottom 0+0.5,
and width 10 (unit scale). A pin-centred boundary (-10,-10)..(10,10)
instead needs offsets (5,4). With no drawn boundary the fallback square
is also pin-centred, including with an explicit plan width of 30 m.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.scene_recipe import (
    _building_model, derive_scalars, scene_mesh_placement,
)


def main():
    loc = {"id": "placement-demo", "map3d": {
        "boundary": [[-4, -2], [16, -2], [16, 10], [-4, 10]],
    }}
    p = scene_mesh_placement(loc, [0, 0.5, 0], [10, 7.0, 8])
    assert p == {"width_m": 10.0, "offset_x": -1.0,
                 "offset_z": 0.0, "offset_y": 0.5}, p
    extent, _, _ = derive_scalars(loc["map3d"], 0.0)
    spec = _building_model(loc, loc["map3d"], {**p, "walk_y": 0}, extent)
    assert spec["anchor"] == [5.0, 4.0], spec
    assert spec["bottom_y"] == 0.5 and spec["max_m"] == 10.0, spec
    for map3d in ({"boundary": [[-10, -10], [10, -10],
                               [10, 10], [-10, 10]]}, {}):
        p = scene_mesh_placement({"map3d": map3d}, [0, 0.5, 0],
                                 [10, 7.0, 8], plan_width_m=30.0)
        assert p == {"width_m": 10.0, "offset_x": 5.0,
                     "offset_z": 4.0, "offset_y": 0.5}, p
    print("All scene mesh placement checks passed.")


if __name__ == "__main__":
    main()
