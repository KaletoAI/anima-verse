# Client execution — E2 navmesh: voxel against polygon bake

Purpose: decision 9 of plan `docs/superpowers/plans/2026-11-25-client-ausfuehrung-e2.md` (Task 5) — which of the two
bake modes of `World/NavBake.cs` stays. Measured with `--check navcompare` (`Check/NavCheck.cs`, `RunCompareAsync`),
which is not part of the full `--check`.

- Date: 2026-11-25
- Godot: 4.7.2.stable.mono.official.ed1daf0bf, headless
- Machine: x86_64, AMD RYZEN AI MAX+ 395, `nproc` 28
- Command: `$GODOT --headless --path native -- --check navcompare`
- Commit of the measured code: the voxel/polygon comparison of this task before the loser was deleted
  (base a0851d530 + the `navcompare` section; both modes still present).

## What each column is

- **ms** — median of five SYNCHRONOUS bakes (`NavigationServer2D.BakeFromSourceGeometryData` for polygon,
  `NavigationServer3D.BakeFromSourceGeometryData` for voxel), the stopwatch around the bake calls only, summed over the
  storeys of the location. Not "request to callback" of the async bake: that callback arrives with the navigation
  server's sync on the main thread and measures the frame clock (review W7).
- **polys** — `NavigationMesh.GetPolygonCount` summed over the storey meshes (threshold quads not counted).
- **edge_err** — nav world only: the largest |offset − 0.25| of the eleven N2 wall probes (closest point on the map
  against the exact eroded edge, README "Nav world", N2).
- **paths** — nav world only: N4–N7b of `--check nav` (the same code, `PathSectionsAsync`) passed (`ok`) or not.
- **thresholds_welded** — `RegionGetConnectionsCount` of the first threshold region (lowest doorway index) on the ready
  map; 0 when the location has no threshold.

The nav world uses its own frame (100, 0, 0), yaw 0, and the three hand boxes of the README table. `walk` and `embody`
(`scene_loc-hall.json`) and `storeys` (`scene_loc-tower.json`) are placed at (0, 0, 0), yaw 0, without furniture
boxes and without terrain (`groundAt` null): they are time and polygon probes, not path evidence.

## Raw lines (run 1)

```
[navcompare] fixture=nav mode=polygon ms=0.057 polys=12 edge_err=0.0016 paths=ok thresholds_welded=2
[navcompare] fixture=walk mode=polygon ms=0.01 polys=2 edge_err=- paths=- thresholds_welded=0
[navcompare] fixture=embody mode=polygon ms=0.036 polys=6 edge_err=- paths=- thresholds_welded=2
[navcompare] fixture=storeys mode=polygon ms=0.026 polys=10 edge_err=- paths=- thresholds_welded=0
[navcompare] fixture=nav mode=voxel ms=2.271 polys=40 edge_err=0.05 paths=fail thresholds_welded=2
[navcompare] fixture=walk mode=voxel ms=2.307 polys=4 edge_err=- paths=- thresholds_welded=0
[navcompare] fixture=embody mode=voxel ms=2.565 polys=21 edge_err=- paths=- thresholds_welded=2
[navcompare] fixture=storeys mode=voxel ms=3.415 polys=12 edge_err=- paths=- thresholds_welded=0
CHECK ok navcompare polygon[edge_err=0.0016 paths=ok] polygon[ms_total=0.128] voxel[edge_err=0.05 paths=fail] voxel[ms_total=10.558]
```

Run 2 (same build) gave the same polygon counts, edge errors, path results and welds; times within ±0.003 ms (polygon)
and ±0.05 ms (voxel): polygon 0.059 / 0.01 / 0.038 / 0.028 ms, voxel 2.257 / 2.323 / 2.565 / 3.461 ms.

Voxel's path failure (run 1 log): `nav N4 P1 through T0's corners` — the path has the corners (99.625, 0.1, 1.8) and
(100.375, 0.1, 1.8) and points at y 0.2 on a floor at y 0: the Recast mesh sits up to one cell height (0.1) above
the floor and its door corners are 0.025 off, so the corner point is ≥ 0.10 from (99.65, 0, 1.8) (tolerance 0.05).

## Table

| Fixture | Mode | ms (median of 5) | polys | edge_err | paths N4–N7 | thresholds_welded |
|---|---|---|---|---|---|---|
| nav (`loc-nav`) | polygon | 0.057 | 12 | 0.0016 | ok | 2 |
| nav (`loc-nav`) | voxel | 2.271 | 40 | 0.05 | fail (N4) | 2 |
| walk (`loc-hall`) | polygon | 0.010 | 2 | – | – | 0 |
| walk (`loc-hall`) | voxel | 2.307 | 4 | – | – | 0 |
| embody (`loc-hall`) | polygon | 0.036 | 6 | – | – | 2 |
| embody (`loc-hall`) | voxel | 2.565 | 21 | – | – | 2 |
| storeys (`loc-tower`) | polygon | 0.026 | 10 | – | – | 0 |
| storeys (`loc-tower`) | voxel | 3.415 | 12 | – | – | 0 |
| **sum of the four** | polygon | **0.128** | | | | |
| **sum of the four** | voxel | **10.558** | | | | |

## Decision (rule 9): polygon stays, voxel is deleted

Rule 9: the winner (a) passes every path section N4–N7 of `--check nav` and (b) has the smaller largest edge error;
only a tie within 0.01 m in (b) falls to the smaller sum of the bake times.

- (a) Polygon passes N4–N7b; voxel fails at N4 (see above). Voxel is out on (a) alone.
- (b) Edge error polygon 0.0016 m against voxel 0.05 m — a difference of 0.048 m, far beyond the 0.01 m tie band; the
  0.05 cell grid of the polygon bake hits the exact eroded edges, the 0.1 voxel cells do not.
- The time is not needed for the decision, and points the same way: 0.128 ms against 10.558 ms for the four
  locations (factor ≈ 80), with 2–4× fewer polygons.

So the polygon bake (2D baker on the storey outlines, lifted to the storey heights) stays; the voxel bake, its parameters
(cells 0.1 / 0.1, edge connection margin 0.25), its test cases and the mode switch (`NavBakeMode`,
`WorldBuilder.NavMode`) are deleted in the same task. `NavBakeParams.Current` replaces `For(mode)`;
`NavBakeParams.Version` is 2, so every fingerprint (cache key) changes with it. The README tolerances of N2/N4/N5/N9
stay as they are (a voxel winner would have needed them widened to the measured edge deviation + 0.05).
`--check navcompare` stays as the measurement of the winner for E7 (one line per fixture, `mode=polygon`).

## After the deletion (the winner alone)

```
[navcompare] fixture=nav mode=polygon ms=0.058 polys=12 edge_err=0.0016 paths=ok thresholds_welded=2
[navcompare] fixture=walk mode=polygon ms=0.01 polys=2 edge_err=- paths=- thresholds_welded=0
[navcompare] fixture=embody mode=polygon ms=0.038 polys=6 edge_err=- paths=- thresholds_welded=2
[navcompare] fixture=storeys mode=polygon ms=0.026 polys=10 edge_err=- paths=- thresholds_welded=0
CHECK ok navcompare fixtures=4 ms_total=0.132 edge_err=0.0016 paths=ok
```

Same polygon counts, edge error, path result and welds as the two-mode run; the fingerprint changed with
`NavBakeParams.Version` 2 (`--check nav` N0/N9 compare it against a freshly built source, so they still hold).

## Notes

- **`storeys/scene_loc-tower.json`** has its doors in continuous walls without a gap — decision 2 finds no adjacent gap
  there, so no threshold is made; the fixture is a time/polygon probe, not path evidence (`thresholds_welded` 0 there,
  as expected).
- **`walk/scene_loc-hall.json`** has only one wall (the south wall z −4); door D0 between `r-a` and `r-b` has no
  adjacent wall, so the two rooms are open floor and no threshold is made (`thresholds_welded` 0; the README's
  "without W5/W6, D0 has no adjacent wall → open floor" case). `embody/scene_loc-hall.json` has the walls, and its T0 is
  welded on both sides (2).
- For comparison: the review measured the synchronous 2D bake of the nav world at 0.1–0.8 ms; this run 0.057 ms.
- **300 ms threshold** (spec 8: a disk cache only from measured 300 ms on): the winner stays below it on every fixture
  by more than three orders of magnitude (largest 0.057 ms). Nothing to note for a disk cache; none is built in E2.
