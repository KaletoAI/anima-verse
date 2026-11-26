# ambience

- Origin: the browser scene's deleted `smoke_ambience.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/AmbienceVectorTests.cs`
- Vectors: `shared/test-vectors/ambience.json`

## Derivation

```text
/**
 * Smoke check for the room ambience and the night clock — the browser scene's ambience.ts,
 * the browser scene's roomAt.ts, and the Engine's applyAmbience (inline below).
 *
 * Usage:  node smoke_ambience.mjs   (historical; the runner was deleted with the browser scene in E3)   (from the repo root)
 *
 * Hand derivations (cases in shared/test-vectors/ambience.json, shared with the
 * native client's C# tests). JSON wrappers: `stepAmbienceN(cur, target, dt, n)`
 * applies stepAmbience n times; `roomAtRects` takes the rectangles as a list of
 * [id, rect] pairs (main.ts hands it the Map); `worldToTile(tile, x, z)` with tile
 * {center: {x, z}, yaw} is tiles.ts' worldToTile.
 *
 * [A] ambienceTarget(a): daylight ?? 1; a tint "#rrggbb" → its three bytes / 255,
 *     kept sRGB (the engine converts); no tint → white. A4 #ffcf9a → (1,
 *     207/255 = 0.8117647058823529, 154/255 = 0.6039215686274509).
 * [E] stepAmbience(cur, target, dt): k = 1 − exp(−dt/τ), τ = .5; every channel
 *     moves cur + (target − cur)·k. E1 dt .5 → k = 1 − 1/e = 0.6321205588285577:
 *     daylight 1 + (.3 − 1)k = 0.5575156088200097 (= .3 + .7/e), tint g/b
 *     1 − k = 1/e = 0.36787944117144233. E2 dt 0 → k 0. E3 the gap shrinks by
 *     exp(−.25/.5) per step, 20 steps → exp(−10) = 4.539992976248485e-05:
 *     daylight 1 − .7·exp(−10) = 0.9999682200491663, g/b 1 − exp(−10) =
 *     0.9999546000702375. E4 four steps of .125 shrink by exp(−.25)⁴ = exp(−1),
 *     the same as one step of .5 (E1) — the easing is frame-rate independent.
 * [N] nightFactorAt(hour): h wrapped into 0..24, day = clamp(sin(((h − 6)/12)π), 0, 1),
 *     night = clamp(1 − 3·day, 0, 1). N1 12 → 0. N2 0 → sin(−π/2) → day 0 → 1.
 *     N3 6 → sin 0 → 1. N4 6.5 → 1 − 3·sin(π/24) = 1 − 3·0.13052619222005157 =
 *     0.6084214233398453. N5 6.8 → 1 − 3·sin(π/15) = 1 − 3·0.20791169081775934 =
 *     0.3762649275467215. N6 7 → 1 − 3·sin(π/12) = 1 − 3·0.25881904510252074 =
 *     0.22354286469243778. N7 8 → 1 − 1.5 → 0. N8 18 → sin π ≈ 1.2e-16 → 1.
 *     N9 25 → 1:00 → 1. N10 −12 → 12:00 → 0.
 * [R] roomRectOf(hull): the hull's bounding box, centre and size, each side at
 *     least .5. R1 (0..4) × (0..2) → (2, 1, 4, 2); R2 (0..3) × (0..0.2) →
 *     (1.5, .1, 3, .5); R3 empty → null.
 *     roomAtRects(rects, x, z): the smallest rect with |x − cx| ≤ w/2 and
 *     |z − cz| ≤ d/2, the first of equal areas. R4 closet 2×2 at (3, 3) inside
 *     the 10×10 hall: (3.5, 3.5) → closet. R5 (0, 0) → hall. R6 (5, 0) on the
 *     hall's edge → hall. R7 (6, 0) → null. R8 equal areas → the first.
 * [T] worldToTile(tile, x, z) (tiles.ts → scene-render worldToLocalXZ): the world point
 *     turned into the tile frame, (dx·c − dz·s, dx·s + dz·c) with d = p − centre,
 *     c/s = cos/sin(yaw) — the inverse of tileToWorld. T1 centre (10, 20), yaw π/2,
 *     (12, 20): d = (2, 0) → (0, 2) (and tileToWorld(0, 2) = (10 + 2, 20) back).
 *     T2 yaw 0: (4, 6) − (1, 2) = (3, 4). T3 yaw π/6, d = (1, 0) → (cos π/6, sin π/6)
 *     = (0.8660254037844387, 0.5).
 * [C] corridorAtOutline(corridors, x, z): the lowest corridor with level ≥ 0
 *     (the first of equal levels), outline ≥ 3 points, half-open ray cast
 *     (game/polygon.ts pointInPolygon). On the square (0,0) (10,0) (10,10)
 *     (0,10): C1 levels 1/0/−1 → level 0 'ground' at (5, 5). C2 (11, 5) → null.
 *     C3 only level −1 → null. C4 two points → null. C5 (0, 5): the edge
 *     (0,10)→(0,0) crosses at x = 0, 0 < 0 false; the edge (10,0)→(10,10) at
 *     x = 10, 0 < 10 → inside. C6 (10, 5): 10 < 0 and 10 < 10 both false → outside.
 */
```
