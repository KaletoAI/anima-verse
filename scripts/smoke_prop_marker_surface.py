#!/usr/bin/env python3
"""Smoke: a marker names the SURFACE, and the migration moves nothing.

Usage:
    ./.venv/bin/python scripts/smoke_prop_marker_surface.py

Runs WITHOUT the server against a throwaway storage dir.

Until 2026-07-28 a prop marker said where the figure's ROOT goes. The seat
drop existed only in the 3D client and only for ROOM markers, so prop authors
baked one in by hand — every marker in the field carried a negative height.
Now the recipe ships ``root_offset`` with the marker, both renderers subtract
it, and the marker means "here is the seat".

The migration lifts the stored fractions by exactly that drop, so nothing on
screen moves. Worked through BY HAND for the fixture below — a bench like the
Wooden Sauna Bench:

    raw bbox      = [1.0, 0.29406, 0.32149]     (mesh units)
    dims          = 1.73 x 0.56 x 0.51 m
    scale s       = max(dims) / max(bbox) = 1.73 / 1.0        = 1.73
    per fraction  = bbox.y x s = 0.29406 x 1.73               = 0.50872 m
    drop (real)   = 0.314 x 1.70 m                            = 0.5338 m
    lift          = 0.5338 / 0.50872                          = 1.04933

    at.y  -0.63  ->  -0.63 + 1.04933                          =  0.41933
    height_m      = 0.41933 x 0.50872                         =  0.21332 m
    (before)      = -0.63    x 0.50872                        = -0.32048 m

    So the composed height rises by 0.5338 m — exactly the drop the renderers
    now take off again. Root position: unchanged.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILED: list[str] = []


def check(label: str, got, want, tol: float = 5e-4) -> None:
    ok = (abs(got - want) <= tol) if isinstance(want, float) else got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAILED.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-marker-"))
    from app.core import paths
    paths.init(tmp)
    from app.core import db
    db.init_schema()
    from app.core import props as ps
    from app.core.room_recipe import compose_prop_marker
    from app.core.scene_recipe import FIGURE_HEIGHT_M, FIGURE_ROOT_DROP

    BBOX = [1.0, 0.29406, 0.32149]
    DIMS = [1.73, 0.56, 0.51]
    ROT = {"x": 0, "y": 0, "z": 0}

    def height_of(at_y: float) -> float:
        """Composed marker height in real metres, straight from the recipe."""
        return compose_prop_marker(
            bbox=BBOX, rotation=ROT, dims=DIMS, frac=[0.5, at_y, 0.525],
            placement_yaw=0, placement_offset_y=0, facing=None)["height_m"]

    print("1. the composition is linear in the fraction")
    check("height(-0.63)", height_of(-0.63), -0.32048)
    check("height(0.41933)", height_of(0.41933), 0.21332)
    check("height(1.0) = the box top", height_of(1.0), 0.50872)

    print("\n2. the drop the renderers subtract")
    drop_real = FIGURE_ROOT_DROP["sit"] * FIGURE_HEIGHT_M
    check("sit drop in real metres", drop_real, 0.5338)
    check("kinds without an entry drop by nothing",
          FIGURE_ROOT_DROP.get("idle", 0.0), 0.0)
    # A lying clip authored ON A BED carries the whole body 0.6 x H above the
    # root — the biggest drop of all, and the reason a sleep marker had to be
    # dragged a metre under the mattress before this existed.
    check("sleep drops by the most", FIGURE_ROOT_DROP["sleep"], 0.631)
    check("laying lies at ground level", FIGURE_ROOT_DROP["laying"], 0.051)

    print("\n3. the migration lifts by exactly that — nothing moves")
    pid = "bench-smoke"
    d = paths.get_storage_dir() / "props" / pid
    d.mkdir(parents=True, exist_ok=True)
    ps._write_sidecar(pid, {
        "name": "Bench", "width_m": DIMS[0], "depth_m": DIMS[1],
        "height_m": DIMS[2], "bbox": BBOX, "rotation": ROT,
        "markers": [{"animation": "sit", "at": [0.5, -0.63, 0.525]},
                    {"animation": "idle", "at": [0.2, 0.0, 0.2]}],
    })
    before = height_of(-0.63)
    stats = ps.migrate_marker_surface_once()
    check("props touched", stats.get("props"), 1)
    check("markers lifted", stats.get("markers_lifted"), 1)

    markers = ps.read_sidecar(pid)["markers"]
    sit = next(m for m in markers if m["animation"] == "sit")
    idle = next(m for m in markers if m["animation"] == "idle")
    check("sit fraction lifted", sit["at"][1], 0.41933)
    check("a standing marker is untouched", idle["at"][1], 0.0)
    check("x/z untouched", [sit["at"][0], sit["at"][2]], [0.5, 0.525])

    after = height_of(sit["at"][1])
    # 1 mm: the stored fraction is rounded to 4 decimals and the composed
    # height to 3, so the round trip cannot be exact — it must be tight
    # enough that a real error cannot hide in it.
    check("surface rose by the drop", after - before, drop_real, 1.5e-3)
    check("ROOT stays where it was", after - drop_real, before, 1.5e-3)
    check("second run is a no-op", ps.migrate_marker_surface_once(), {})

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
