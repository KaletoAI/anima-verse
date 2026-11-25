# shadow_snap

- Origin: `client3d/scripts/smoke_shadow_snap.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/SkyLightVectorTests.cs`
- Vectors: `shared/test-vectors/sky_light.json`

## Derivation

```text
/**
 * Smoke check for the SHADOW CAMERA'S TEXEL GRID —
 * `client3d/src/scene/shadowSnap.ts`, used by `scene/engine.ts`.
 *
 * Usage:  node client3d/scripts/smoke_shadow_snap.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * WHY THIS FILE EXISTS. The sun of this client is not a world light: its
 * orthographic shadow frustum follows the camera target, so 140 m of shadow map
 * can serve a world of kilometres. Until 2026-08-21 it followed CONTINUOUSLY —
 * and a shadow map is a raster. Slide a raster by a third of a texel and every
 * depth sample lands on a different piece of ground: the shadow edge of a
 * figure, a fence or a roof crawls along its own outline on every frame the
 * camera pans ("shadow swimming"). The fix is the standard one — quantise the
 * frustum's centre to the light's own texel grid.
 *
 * ============================================================================
 * [1] ONE TEXEL
 * ============================================================================
 * The frustum is `SHADOW_HALF_M` = 70 m to each side over `SHADOW_MAP_PX` =
 * 2 048 texels:
 *     140 / 2048 = 0.068359375 m — 6.8 cm of ground per shadow texel.
 * Both numbers are powers of two times a small integer, so the quotient is an
 * exact binary fraction and nothing here rounds twice.
 *
 * ============================================================================
 * [2] THE LIGHT'S BASIS, at the sun `engine.ts` really hangs at 18:00
 * ============================================================================
 * There `sunAngle = π`, so the light stands at
 *     offset = (cos π · 60, max(0.08, sin π) · 80, 25) = (−60, 6.4, 25)
 * over its target. Its HORIZONTAL part (−60, 25) has length exactly 65 (a
 * 5-12-13 triangle scaled by 5), which makes the whole basis hand-derivable:
 *
 *   z = offset / |offset|, |offset| = √(3600 + 40.96 + 625) = √4265.96
 *                                   = 65.31431696…
 *     = (−0.918633…, 0.097987…, 0.382763…)
 *   x = normalize( up × z ) with up = (0, 1, 0); up × z = (z_z, 0, −z_x),
 *       whose length is the cosine of the elevation — so the normalisation
 *       cancels the 65.3143 and leaves the HORIZONTAL perpendicular exactly:
 *       x = (25, 0, 60) / 65 = (5/13, 0, 12/13) = (0.384615…, 0, 0.923076…)
 *   y = z × x, a unit vector perpendicular to both.
 *
 * (a) the texel size, (b) the basis, (c) that the three axes are unit-length,
 *     mutually perpendicular and right-handed.
 *
 * AND ONE LOAD-BEARING CONSEQUENCE: three puts the shadow camera AT THE LIGHT
 * and points it at the target (`LightShadow.updateMatrices`), so the frustum's
 * u/v origin is the light's, not the target's. The offset is parallel to z and
 * hence has neither u nor v — the two share one texel coordinate, which is why
 * moving both by the same world vector is the whole of the snap.
 *
 * ============================================================================
 * [3] A PAN SMALLER THAN A TEXEL DOES NOT MOVE THE RASTER
 * ============================================================================
 * That is the whole property. Start the target at the origin: its light-space
 * u = v = 0, already a whole multiple, so the snapped centre IS the origin.
 * Now walk the target 0.4 texels along the light's own u axis (0.02734375 m in
 * light space, i.e. 0.02734375 m of world travel along `x`): u/texel = 0.4,
 * `round(0.4)` = 0, so the shift is −0.4 texels and the snapped centre is the
 * origin AGAIN, to the last bit. The same holds for 0.49 texels; at 0.51 the
 * centre jumps by exactly one whole texel and never by a part of one.
 *
 * (d) 0.4 and 0.49 texels of travel: the snapped centre does not move at all.
 * (e) 0.51 texels: it moves by exactly one texel — 0.068359375 m, in light
 *     space, along u.
 * (f) A WORLD WALK. Moving the target 1 m along +x moves u by 1 · (5/13) =
 *     0.3846153846 m, which is
 *         (5/13) / (140/2048) = 10240 / 1820 = 5.6263736…  texels.
 *     So over a 1 m pan sampled at 1 cm the snapped centre takes the whole-
 *     texel indices round(5.6263736 · δ) for δ = 0…1, i.e. 0, 1, 2, 3, 4, 5, 6
 *     — SEVEN distinct positions instead of 101, and each of them is a whole
 *     texel apart from the one before it.
 * (g) EVERY snapped centre has whole-texel light-space coordinates, over 4 000
 *     arbitrary targets and four sun angles — that is the invariant itself.
 * (h) THE SHIFT IS PERPENDICULAR TO THE LIGHT: `dot(centre − target, z) = 0`,
 *     so the near/far range along the light axis is untouched (depth is
 *     quantised in a texel's VALUE, not in its position; the bias owns that
 *     end), and the displacement stays under half a texel per axis, i.e.
 *     √2 · 0.0341796875 = 0.04833 m — nothing a 140 m frustum notices.
 * (i) RED COUNTER-PROBE: the target UNSNAPPED (what the engine did before)
 *     lands on a whole texel only when it happens to; over the same 4 000
 *     targets the worst residual is essentially half a texel, i.e. the raster
 *     really was sliding by arbitrary fractions.
 * (j) A LIGHT STRAIGHT OVERHEAD is not a division by zero: `up × z`
 *     degenerates, the +Z reference takes over, and the basis stays finite and
 *     orthonormal.
 *
 * [20] Clock and fog extraction cases (sky_light.json):
 * Hour wraps modulo24: -12 becomes12. sunAngle=(h-6)*pi/12;
 * h0=>-pi/2=-1.5707963267948966,h6=>0,h12=>pi/2.
 * Day=max(0,sin(angle)) gives0,0,1. Intensities(.25+2day,
 * .35+1.2day,.15+.4day) are(.25,.35,.15) at night/dawn,
 * (2.25,1.55,.55) at noon. At day0 the sun is moon0x9fb4e0
 * (decimal10466528), sky0x1a2340(decimal1712960). At day1:
 * sun0xfff2d8(decimal16773848), sky0x9fc7e8(decimal10471400).
 * Interpolated dawn: h=6+12*asin(.25)/pi=6.965167479061995,
 * angle=.25268025514207865,day=.25. Sun smoothstep(.05,.45,.25)
 * is.5. Sky blend=(.35-.25)/.2=.5. Convert sRGB channel c to linear
 * by c/12.92 below.04045, otherwise((c+.055)/1.055)^2.4, interpolate,
 * then inverse transfer and round*255. Warm/noon midpoint gives linear
 * (1,.661038377022,.409776816987), bytes(255,212,171)=0xffd4ab
 * (decimal16766123). Day/dusk midpoint gives linear(.576828157005,
 * .447134019279,.465862037608), bytes(200,178,182)=0xc8b2b6
 * (decimal13152950). Intensities are(.75,.65,.25).
 * nightFactorAt cross-reference (ambience.json's source derives the full
 * clock): clamp(1-3day) is1 at midnight,0 at noon.
 * Fog uses view-space depth, not radius: t=clamp((depth-220)/300).
 * Depths0/220=>0,295=>.25,370=>.5,445=>.75,520/800=>1.
 * 3t^2-2t^3 gives0,.15625,.5,.84375,1 at those positions.
 * For light offset(0,0,1), basis axes are the identity. A shadow texel
 * is140/2048=.068359375. Target xy.02 is.2925714 texels, rounds0;
 * xy(.04,-.04) is(+.5851429,-.5851429), rounds(+1,-1), giving
 * (+.068359375,-.068359375). Depth z7 never moves.
 */
```

## Inline derivations

Comment blocks of `client3d/scripts/smoke_shadow_snap.mjs` after its opening docstring that contain a mark a case label
cites, in file order; line numbers refer to the smoke at a56065e6f003.

Line 187 (cites [1]):

```text
// ── [1] one texel ───────────────────────────────────────────────────────────
```

Line 194 (cites [2]):

```text
// ── [2] the light basis ─────────────────────────────────────────────────────
```
