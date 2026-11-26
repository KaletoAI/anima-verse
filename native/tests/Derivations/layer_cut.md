# layer_cut

- Origin: the browser scene's deleted `smoke_layer_cut.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/LayerGroundVectorTests.cs`
- Vectors: `shared/test-vectors/layer_ground.json`

## Derivation

```text
/**
 * Smoke check for the LAYER CUT of the ground ("Ein Boden" E3, § G3) — the
 * arithmetic the terrain material composites its material with, and the proof
 * that the three ladders it replaces are really gone.
 *
 * Usage:  node smoke_layer_cut.mjs   (historical; the runner was deleted with the browser scene in E3)
 *         (transpiles `@anima/scene-render` `layerCut.ts`; needs esbuild)
 *
 * The server half is `scripts/smoke_terrain_layers.py` — the BAKE. This is the
 * READING: the same bytes, the same quantisation, the same blend, on the client
 * side. Every number below is derived by hand in this docstring (§ B5a).
 *
 * ===========================================================================
 * [1] THE CUT — `layerWeight(sd, blendM, fw)`
 * ===========================================================================
 * How much of layer A a fragment shows. Two cases.
 *
 * (a) A SOFT TRANSITION of width `b`, centred on the line:
 *     `smoothstep(−b/2, +b/2, sd)`, i.e. `t = clamp((sd + b/2)/b, 0, 1)` and
 *     `3t² − 2t³`. HALF THE WIDTH LIES ON EACH SIDE, so a "1.5 m blend" really
 *     is 1.5 m of ground and not three. At b = 1.5, by hand:
 *
 *         sd = −0.75  ->  t = 0     -> 0
 *         sd = −0.375 ->  t = 0.25  -> 3·0.0625 − 2·0.015625 = 0.15625
 *         sd =  0     ->  t = 0.5   -> 0.5             (exactly, always)
 *         sd = +0.375 ->  t = 0.75  -> 0.84375
 *         sd = +0.75  ->  t = 1     -> 1
 *         sd = ±20    ->  clamped   -> 1 / 0
 *
 *     The three middle numbers are the very ones the old alpha fringe was
 *     pinned on (`ngEdgeAlpha`, 0.15625 / 0.5 / 0.84375) — the LOOK is
 *     unchanged, only its mechanism is.
 *
 * (b) A HARD CUT, `b = 0`, ANALYTICALLY ANTI-ALIASED: `clamp(sd/fw + 0.5,
 *     0, 1)` where `fw` is one pixel measured in WORLD METRES —
 *     `max(length(dFdx(world)), length(dFdy(world)))`, never `fwidth(sd)`
 *     (finding round 2026-08-21, [5] below).
 *     That is a step ONE PIXEL wide wherever the camera stands. By hand with
 *     fw = 0.1 m (a pixel a decimetre across, i.e. standing on the ground):
 *
 *         sd = −0.05 -> 0      sd = −0.025 -> 0.25     sd = 0    -> 0.5
 *         sd = +0.025 -> 0.75  sd = +0.05  -> 1        sd = ±1   -> 1 / 0
 *
 *     and with fw = 4 m (a pixel four metres across, i.e. from far away) the
 *     same sd = 1 m reads 0.75 instead of 1 — the two grounds are AVERAGED at
 *     that distance rather than shimmering between them. A bare `step()` would
 *     stair-step along every diagonal; a fixed-width smoothstep would blur the
 *     near edge and still alias the far one.
 *
 * ===========================================================================
 * [2] THE NOISE PUSH — an organic border, and a hard cut that stays hard
 * ===========================================================================
 * `lcPushedSd` adds `(noise·2 − 1) · cap` to the distance, with
 * `cap = min(0.5, b/2)`:
 *
 *     b = 1.5 -> cap = min(0.5, 0.75) = 0.5   the full push, today's fringe
 *     b = 0.6 -> cap = min(0.5, 0.30) = 0.3   never more than half the blend
 *     b = 0   -> cap = 0                      THE HARD CUT DOES NOT MOVE
 *
 * The cap is what makes a room floor end on the metre it was drawn on while a
 * meadow finds its own way. The noise itself is the fract-sin value noise of
 * `naturalGround.ts`, unchanged, so the two look the same.
 *
 * ===========================================================================
 * [3] THE MASK, READ — a hand-built window, decoded texel by texel
 * ===========================================================================
 * One tile, 4 m across, at the world origin, with `id_step 1`, `sd_step 0.5`,
 * band 8, zero 128, 15.875 codes per metre — the server's own format numbers.
 * A single boundary at x = 2, layer 1 to the east (painted later, so A = 1) and
 * layer 0 to the west (B = 0). Every id texel therefore carries (1, 0); the
 * sd texel at centre `0.5m + 0.25` carries its signed distance to x = 2:
 *
 *     m = 0..3  centres 0.25 0.75 1.25 1.75  ->  −1.75 −1.25 −0.75 −0.25
 *     m = 4..7  centres 2.25 2.75 3.25 3.75  ->  +0.25 +0.75 +1.25 +1.75
 *
 * quantised as `round(sd·15.875) + 128`, i.e. codes 100, 108, 116, 124, 132,
 * 140, 148, 156. `layerPairAt` must read (1, 0) anywhere in the tile,
 * `layerSdAt` the value of the texel a point falls in, and `topLayerAt` — the
 * undergrowth gate — must answer 0 west of the line and 1 east of it.
 *
 * OUTSIDE THE WINDOW everything answers bare ground, which is what an unloaded
 * tile draws.
 *
 * ===========================================================================
 * [4b] TWO BOUNDARIES IN ONE NEIGHBOURHOOD — where the sign stops meaning
 * ===========================================================================
 * The sign of an sd texel says "on A's side of MY pair", so two texels signed
 * against two different pairs are two numbers on two scales. A hardware LINEAR
 * fetch reaches half a texel past the id texel and mixes exactly those — which
 * drew a strip of the kitchen's rubber a metre and a half inside the living
 * room of "Haus von Kai", along the whole medial axis of the west wall and the
 * kitchen line. The fixture below is that neighbourhood, decoded out of the
 * running world and moved to the origin: the filtered fetch answers +0.47 where
 * the reading of the fragment's OWN id texel answers −1.26.
 *
 * ===========================================================================
 * [4] A UNIFORM TILE, AND A MISSING ONE
 * ===========================================================================
 * A tile the bake answered `{"uniform": 2}` for fills its whole square with the
 * pair (2, 2) and keeps the neutral distance (code 255 = +8 m), which composites
 * to "layer 2, whole". A tile the batch never brought stays at the neutral fill,
 * i.e. bare ground — the same statement an unindexed tile makes.
 *
 * ===========================================================================
 * [5] THE GLSL — one string, and what has to be in it
 * ===========================================================================
 * Not read for its arithmetic (the smoke reimplements that above, so a check
 * that read the string could only prove the string equals itself), but for the
 * things a compiler would refuse or a driver would answer wrongly:
 *  - `usampler2D` + `texelFetch` for the id, because an INTEGER texture cannot
 *    be filtered at all — NEAREST is enforced by the format rather than by a
 *    sampler setting;
 *  - `sampler2DArray` for the surfaces, one slice per layer, sampled with an
 *    EXPLICIT gradient (`textureGrad`): every layer scales the world position
 *    by its own metres-per-tile, so the uv JUMPS at a boundary and an implicit
 *    derivative would ask for the coarsest mip — a blurred line along every
 *    edge in the world. The two masks are read with `texelFetch`, which asks
 *    for no derivative and no filter at all: the id because an integer texture
 *    cannot be filtered, the distance because the four texels the bake signed
 *    together are the only ones that may be mixed ([4b]);
 *  - `fwidth` OUTSIDE any branch that differs across a quad (a derivative taken
 *    in non-uniform control flow is undefined in GLSL ES);
 *  - the per-layer array sized by a compile-time constant.
 *
 * ===========================================================================
 * [6] THE RED COUNTER-PROBES — the ladders are GONE
 * ===========================================================================
 * The whole point of E3 is a deletion, and a deletion is the one thing a
 * positive check cannot measure. So the sources are read for the names of the
 * three crutches that used to hold the drape stack apart:
 * `AREA_RENDER_ORDER_BASE`, `AREA_POLYGON_OFFSET`, `AREA_OFFSET_MAX`,
 * `AREA_Y_STEP_M`, `AREA_Y_MAX_M`, plus the fringe machinery
 * (`ngRefineEdgeBand`, `NG_EDGE_BAND_M`, `aEdgeDist`) and the dead `gridPlate`.
 * None of them may appear as CODE anywhere in the client or the shared package.
 *
 * And the scene-graph builder must not stack: `rebuildAreas` may set no
 * `renderOrder`, no `polygonOffset` and — since E4 — no `position.y` at all.
 * The last one it had was `WATER_DRAPE_LIFT_M`, the two centimetres that kept
 * the water drape off its own bed; the drape became a mirror MESH in E4 and the
 * terrain's own water shading in Wasser v2 K-A, so `rebuildAreas` builds no
 * ground surface at all any more — the constant is checked to be gone from
 * the code like the ladders are.
 *
 * ===========================================================================
 * [7b] WATER WEARS ITS BED, AND THE SERVER SAYS WHICH (W1 § 5)
 * ===========================================================================
 * A water layer is a full layer — the mask has to answer "here is water" for
 * the undergrowth gate and every point query — but what it PAINTS is the ground
 * underneath, because the water is a SHADING of that very pixel
 * (`scene/waterShade.ts`) and painting the lake twice made the two fight each
 * other.
 *
 * WHO DECIDES THAT MOVED. Until W1 this client decided it: `setLayerTable`
 * substituted layer 0's image (`layer.water ? bare : layer`) for every water
 * row, which flattened an authored gravel bed back to the world's default kind
 * and was a renderer inventing ground. Now the server ships it — `surface` on a
 * water row IS the bed's, `bed_kind` names the kind it came from, and
 * `edge_blend_m` is the bed's too wherever a bed was authored. So the client's
 * whole job is to render the surface the table names, and the three checks
 * below are: the substitution is gone, the kind fallback asks the bed, and the
 * bed is part of the key that rebuilds the slice array.
 *
 * THE KEY IS A COUNTING ARGUMENT, not taste. The server keys a layer by
 * `(kind, edge_blend_m, bed_kind)`, so two ponds of one kind on two beds are
 * two rows with two images. A client whose `layerKey` left `bed_kind` out would
 * see one string for both worlds and keep yesterday's slice array standing.

 *
 * Shared-vector companion hand derivations (also retained at their original sites):
 * Companion: smoke_natural_ground.mjs

 * Smoke check for the NATURAL GROUND — the three-stage shader patch that makes
 * the open world's ground stop looking like wallpaper, and the arithmetic that
 * steers it (§ B5a: strings and numbers, never screenshots).
 *
 * Usage:  node smoke_natural_ground.mjs   (historical; the runner was deleted with the browser scene in E3)
 *         (bundles the client's naturalGround + ground modules; needs three)
 *
 * ===========================================================================
 * WHAT IS UNDER TEST
 * ===========================================================================
 * the browser scene's `naturalGround.ts` patches the OPEN-WORLD ground material
 * (the CDLOD terrain of `scene/ground.ts`, and the one water drape left beside
 * it) with three stages:
 *   (1) ANTI-TILE   the ground texture sampled a second time at 0.23× the
 *                   scale, shifted half a UV, blended by value noise over
 *                   world metres — one image, two periods, no visible repeat.
 *   (2) COLOUR      brightness and saturation modulated by ±8 % over a ~25 m
 *                   noise. Never hue. The ONE stage a single-coloured kind
 *                   gets as well, which is why it stands outside `USE_MAP`.
 *   (3) HEIGHT AO   four taps in a 3 m ring out of the world's own heightfield
 *                   against the fragment's own height: lower than its
 *                   surroundings darkens by up to 12 %, higher brightens by up
 *                   to 6 %.
 * THERE WAS A FOURTH — a painted area fading out over the last 1.5 m of itself
 * — and it is gone with "Ein Boden" E3: a ground boundary is a CUT in the one
 * terrain surface now, its width the layer's own `edge_blend_m`, and it is
 * checked in `smoke_layer_cut.mjs`. Everything left here reads nothing but the
 * fragment's own world position, so the patch takes no arguments and every
 * ground compiles to one program.
 * The amplitudes live in `naturalGroundMath.ts` and the GLSL is PRINTED out of
 * them, so a hand check on the function and a string check on the composed
 * shader measure one number rather than two copies of it.
 *
 * Four things can silently break, and all four are checked here without a GPU:
 *  - the patch is the SECOND writer of `onBeforeCompile` on every ground
 *    material (`patchHole` is already in the slot). An ASSIGNMENT would throw
 *    the basement hole away — the rule this repo learned the hard way with the
 *    water shader (`smoke_surface_patch.mjs`), measured by the mutant of [8a].
 *  - WATER is not a case any more. It used to be a mesh with a shader of its
 *    own, which this patch stepped aside for; since Wasser v2 K-A E5 a water
 *    pixel IS a pixel of this very ground and is shaded as water after it
 *    (`scene/waterShade.ts`). Section [6] is the RED probe on that.
 *  - a FLAT world must be EXACTLY neutral, not almost. The switch is the
 *    shared `uNgStrength` uniform at 0 plus the shader's own guard — the same
 *    shape the view corridor uses for an unembodied client.
 *  - the AO SIGN. Turned around, the ditches light up and the ridges go grey;
 *    it looks deliberate and it is the exact opposite of ground. Two mutants
 *    in [8b]/[8c], one on the pure function and one on the emitted GLSL.
 *
 * The patches are handed a STUB SHADER whose vertex/fragment strings carry the
 * real `#include` anchors of three's `meshphysical` shader, and the resulting
 * strings are read.
 *
 * THE ANCHORS (both `#include` LINES, because `onBeforeCompile` sees the shader
 * BEFORE three resolves its includes):
 *   vertex   `#include <project_vertex>`   the fragment's world position
 *   fragment `#include <map_fragment>`     where the texture lands in
 *                                          `diffuseColor` — everything the
 *                                          patch does modifies what is already
 *                                          there, so it goes AFTER it
 *
 * ---------------------------------------------------------------------------
 * [1] THE PATCH ALONE — every line, the four uniforms, the key
 * ---------------------------------------------------------------------------
 * The three stages in the composed fragment shader, the world position in the
 * vertex shader, the anti-tile stage inside `#ifdef USE_MAP` (a single-coloured
 * kind has no repeat to break) and the AO inside `if ( uNgStrength > 0.0 )`.
 * The key is the constant `natural-ground`: every number is either a GLSL
 * literal or a shared uniform, so all ground materials of a world compile to
 * ONE program.
 *
 * ---------------------------------------------------------------------------
 * [2] THE CHAIN — basement hole and natural ground on ONE material
 * ---------------------------------------------------------------------------
 * That is the real composition of `materialFor`. Every hole line AND every
 * natural-ground line must be in the composed shader, both uniform families
 * bound, and the key must be `ground-hole+natural-ground` — the two in the
 * order they were applied. Patching twice is still one patch (the WeakSet), or
 * the shader would declare `vNgWorld` and `ngNoise` twice and not compile.
 *
 * ---------------------------------------------------------------------------
 * [3] THE SHARED UNIFORMS — one upload reaches every ground material
 * ---------------------------------------------------------------------------
 * The `surfaceTimeUniform` pattern: two materials hand the SAME four objects
 * into their shaders, and one call to `setNaturalGroundField` shows up in both.
 * Without it a world with two hundred painted areas would hold two hundred
 * copies of the height texture.
 *
 * ---------------------------------------------------------------------------
 * [4] THE HEIGHT TEXTURE — what `setNaturalGroundField` uploads
 * ---------------------------------------------------------------------------
 * A 3×3 field of a single 4 m hill, and the four numbers the shader addresses
 * it with: R16F, linearly filtered, clamped at the edge, `uNgField` =
 * (origin_x, origin_z, step, 0), `uNgFieldSize` = (cols, rows). Half float
 * rather than full because WebGL2 filters R16F in core; the round trip of 4.0
 * and 22.5 must come back exact, which pins the packing.
 * NEUTRALITY, three ways, all of them the same promise: a world nobody has
 * shaped (every support point at the same height), a field that never arrived
 * (`null`), and a field too small to have an interior all answer strength 0 —
 * and the shader's guard then reads nothing at all.
 *
 * ---------------------------------------------------------------------------
 * [5] THE ARITHMETIC — `naturalGroundMath`, by hand
 * ---------------------------------------------------------------------------
 * With span 2 m, down 12 % and up 6 %:
 *   surroundings level with the fragment      ->  0        (flat is neutral)
 *   surroundings 1 m higher   -> t = 0.5      -> -0.06     (a shallow hollow)
 *   surroundings 2 m higher   -> t = 1        -> -0.12     (fully spent)
 *   surroundings 8 m higher   -> t clamped 1  -> -0.12     (a valley is not
 *                                                           four hollows)
 *   surroundings 1 m lower    -> t = -0.5     -> +0.03
 *   surroundings 2 m lower    -> t = -1       -> +0.06     (half the darkening)
 * The field UV is on TEXEL CENTRES: support point i lies at the centre of texel
 * i, so its coordinate is (i + 0.5)/cols. For a 21×21 field at origin (−100,
 * −100) and 10 m step: x = −100 -> 0.5/21, x = +100 -> 20.5/21, x = −105 -> 0
 * (the outer edge, still inside), x = −110 -> outside and therefore neutral.
 * Getting that half wrong shifts the whole shading by half a support cell.
 * The colour factors: noise 1 -> 1.08, noise 0 -> 0.92, noise 0.5 -> 1 exactly.
 * The second UV: (1, 1) -> (0.73, 0.73), (0, 0) -> (0.5, 0.5).
 *
 * ---------------------------------------------------------------------------
 * [6] THE PATCH GOES ON THE ONE GROUND MATERIAL, AND WATER IS NO EXCEPTION
 * ---------------------------------------------------------------------------
 * Until Wasser v2 K-A E5 a painted lake was a MESH with a rippled material of
 * its own, and this patch had to step aside for it (`isWaterClass`, applied in
 * the deleted `materialFor`): a second sample of the water texture and a relief
 * shading on top would have fought the ripple, the fresnel and the roughness
 * mask. There is no such material any more — the one ground material this
 * client builds is the terrain's, made WITHOUT a surface spec at all
 * (`material: null`, so it can never be a water surface), and a water pixel is
 * a pixel of that very ground, shaded as water afterwards
 * (`scene/waterShade.ts`). The section is therefore a RED one: the guard is
 * gone from the tree, the composition it guarded exists nowhere, and the patch
 * still lands on a plain ground material exactly as it did.
 *
 * ---------------------------------------------------------------------------
 * [7] THE WIRING, pinned by reading the source
 * ---------------------------------------------------------------------------
 * A patch is worth nothing where nobody applies it. `rebuildBase` is a closure
 * over fetched payloads and cannot be called from here, so its lines are pinned
 * against the source text: the hole first, then the veil and the natural
 * ground, the field handed over in `applyHeight` and given back in `dispose`.
 * It is applied EXACTLY ONCE in the file since Wasser v2 K-A E5 — the terrain's
 * material is the only ground material left — and nowhere else: the admin
 * preview and the shared package must not import any of this (view polish is
 * not geometry, § B2).
 *
 * ---------------------------------------------------------------------------
 * [8] THE RED COUNTER-CHECKS — five mutants, five losses
 * ---------------------------------------------------------------------------
 * (a) ASSIGNMENT INSTEAD OF CHAIN. The bundle is rebuilt with the line that
 *     calls the previous callback deleted. Fed a material that already carries
 *     the basement hole, the mutant's shader contains NOT ONE hole line while
 *     every natural-ground line is still there — so the probe measures the loss
 *     of the chain, not a broken module.
 * (b) THE AO SIGN, in the pure function: `-down·t` becomes `+down·t`, and the
 *     hollow that the truth darkens comes out BRIGHTER.
 * (c) THE AO SIGN, in the emitted GLSL: both minus signs of the shade line are
 *     dropped. The mutant's shader loses the line the truth carries — which is
 *     what makes the string check in [1] a check on the sign rather than on the
 *     presence of a substring.
 * (d) THE FLAT WORLD. The neutrality test drops out of `setNaturalGroundField`,
 *     so a world nobody has shaped is shaded against its own zero — the mutant
 *     answers strength 1 for the very field the truth answers 0 for.
 * (e) THE HALF TEXEL. `+ 0.5` drops out of the world -> UV mapping, which puts
 *     every support point on a texel CORNER and slides the whole shading half
 *     a support cell. This is the mutant the mapping was made a function for:
 *     while the line stood twice, one copy could lose it and every string
 *     check still found the other.
 * (f) AN UNPRINTABLE CONSTANT (7.005 m). The module must refuse to LOAD;
 *     without the assert `toFixed` would round it to 7.01 and the shader would
 *     spend a different number than the maths does.
 *
 * THREE MUTANTS LEFT WITH E3, and they left with their subject: the band
 * refinement, the fringe line and the render-order ladder of the transparent
 * drapes. What replaced them is checked in `smoke_layer_cut.mjs`, including the
 * counter-probes that the ladders are really GONE.

 *
 * [20] Shared natural-ground and cut cases:
 * A zero blend has no push: sd.25 stays.25. At world(-10,-46), the
 * noise input is(-10/2+5,-46/2+23)=(0,0), so sin0=0 and hash0=0.
 * Push=(2*0-1)*min(.5,blend/2): blend1.5 ->-.5, blend.6 ->-.3.
 * Uniform layer2 in tileM1, idStep1, sdStep.5 makes one id pair[2,2],
 * four distance bytes255, origin0, idSize1,sdSize2. Decode is
 * (255-128)/15.875=8. Pair[2,2] picks layer2 even at x=-1: texel
 * address clamps, and equality returns the uniform layer before an sd test.
 * Detail uv(1,1)=1*.23+.5=(.73,.73). Tint factors are
 * 1+.08*(2n-1): n1=>1.08,n0=>.92,n.5=>1. AO t=(mean-own)/2,
 * clamped[-1,1]; +1 m=>t.5=>-.12*.5=-.06; +8=>-.12;
 * -1=>-.06*(-.5)=.03; -8=>.06. Texture centre at world0 on a2x2
 * step2 grid is((0/2+.5)/2,(0/2+.5)/2)=(.25,.25), inside.
 * The constants case pins the declared noise(.5 m,2 m), detail(.23,.5),
 * mix(7 m,.5), tint(25 m,.08), AO(3 m,2 m,.12,.06) contracts.
 */
```

## Inline derivations

Comment blocks of the browser scene's deleted `smoke_layer_cut.mjs` after its opening docstring that contain a mark a case label
cites, in file order; line numbers refer to the smoke at a56065e6f003.

Line 425 (cites [1]):

```text
// --- [1] the cut ------------------------------------------------------------
```

Line 464 (cites [3]):

```text
// --- [3] the mask, read -----------------------------------------------------
```

Line 514 (cites [4]):

```text
// --- [4] a uniform tile, and a missing one ----------------------------------
```

Line 614 (cites [5]):

```text
// --- [5] the GLSL -----------------------------------------------------------
```
