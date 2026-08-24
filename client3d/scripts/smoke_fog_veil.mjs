#!/usr/bin/env node
/**
 * Smoke check for the EXPLORATION VEIL — the haze over ground the avatar has
 * never walked (`plan-fog-schleier-v2.md`, § A12).
 *
 * Usage:  node client3d/scripts/smoke_fog_veil.mjs
 *         (transpiles `scene/fogVeilMath.ts`; bundles `scene/fogVeil.ts`,
 *          needs three)
 *
 * Same discipline as `smoke_natural_ground.mjs` and `smoke_scene_recipe.py`:
 * EVERY expected number below is derived BY HAND in this header, from the
 * definition, and never recorded from an implementation run (§ B5a — numbers,
 * never screenshots). A check that only pins today's output proves nothing.
 *
 * ============================================================================
 * THE SUBJECT
 * ============================================================================
 * `scene/fogVeilMath.ts` is the arithmetic: which 64 m cell a metre lies in,
 * where that cell lands in the data texture, how soft its edge is and how much
 * haze a camera height is worth. `scene/fogVeil.ts` is how those numbers reach
 * the GPU: one data texture, seven uniforms, one shader patch on the ground
 * material.
 *
 * Four things can break silently, and all four are checked here without a GPU:
 *  - the RASTER drifting away from the server's. The cells arrive as `"cx,cz"`
 *    keys out of `GET /play/explored` and are the server's own
 *    `EXPLORED_CELL_M` = 64 m, anchored at the world origin. A client that
 *    rounded instead of flooring would veil the wrong half of the world across
 *    the origin — section [1] is the twin of `app/core/exploration.cell_of`.
 *  - the TEXEL MAPPING slipping by half a cell. Texel centres have to sit on
 *    CELL centres, or the soft edge lands inside a cell instead of on its
 *    boundary (sections [4]/[5]).
 *  - the patch ASSIGNING instead of chaining `onBeforeCompile` — the mistake
 *    this repo learned the hard way with the water shader; the mutant of [9d]
 *    measures it.
 *  - the HEIGHT RAMP losing an end: a veil that never quite reaches 0 fogs the
 *    embodied mode (section [6] pins both ends exactly, not "almost").
 *
 * ============================================================================
 * [1] fogCellOf — floor division, the server's twin
 * ============================================================================
 * `cx = floor(x / 64)`; cell (cx, cz) covers [cx·64, (cx+1)·64).
 *      0     -> 0            (the cell starts at its own left edge)
 *     63.999 -> 0
 *     64     -> 1
 *    100     -> 1            (100/64 = 1.5625)
 *    900     -> 14           (900/64 = 14.0625 — the cell of the smoke world
 *                             `scripts/smoke_fog_worldmap.py` [8] measures in)
 *    950     -> 14           (950/64 = 14.84375)
 *     -1     -> -1           (-0.015625 floors to -1, NOT to 0: that is what
 *                             makes the raster continuous across the origin
 *                             instead of doubling the width of the cell that
 *                             straddles it)
 *    -64     -> -1
 *    -65     -> -2           (-1.015625)
 *
 * ============================================================================
 * [2] fogParseCell — two integers, or nothing
 * ============================================================================
 *   "0,0"     -> [0, 0]
 *   "-1,2"    -> [-1, 2]
 *   "14,1"    -> [14, 1]
 *   "3.5,1"   -> null      (Number() would take it and veil a place between
 *                           two cells)
 *   "+3,1"    -> null
 *   " 3,1"    -> null      (whole-string match, no trimming: the server never
 *                           writes a space, so a space is a payload this
 *                           client does not understand)
 *   "3,1,2"   -> null
 *   "3"       -> null
 *   "a,b"     -> null
 *   ""        -> null
 *
 * ============================================================================
 * [3] fogGrid — the bounding box, grown by ONE cell on every side
 * ============================================================================
 * The ring of zeros is what the clamp-to-edge sampler needs: without it an
 * explored cell at the border of the box would smear its 1 over everything
 * outside the box.
 *   ["0,0"]           -> cx0 -1, cz0 -1, cols 3, rows 3
 *                        (1 cell + 1 on each side = 3, both axes)
 *   ["0,0", "2,1"]    -> x: 0…2 = 3 cells + 2 = 5, cx0 = -1
 *                        z: 0…1 = 2 cells + 2 = 4, cz0 = -1
 *   ["-3,-3"]         -> cx0 -4, cz0 -4, cols 3, rows 3
 *   ["0,0", "nope"]   -> as ["0,0"]: an unreadable key is SKIPPED, never
 *                        guessed at — one NaN would stretch the grid over the
 *                        whole world
 *   []                -> null   (no box; the caller answers with the neutral
 *                                one-texel texture, i.e. a world nobody has
 *                                walked)
 *   ["nope"]          -> null
 *
 * ============================================================================
 * [4] fogTexUv — texel CENTRES sit on CELL CENTRES
 * ============================================================================
 * Grid of ["0,0"]: cx0 = cz0 = -1, cols = rows = 3. Texel i covers
 * [i/3, (i+1)/3] and its centre is (i+0.5)/3.
 *   world (32, 32)   = centre of cell (0,0)   -> u = (0.5+1)/3 = 0.5
 *                                                 = centre of texel 1 ✓
 *   world (-32, -32) = centre of cell (-1,-1) -> u = (-0.5+1)/3 = 1/6
 *                                                 = centre of texel 0 ✓
 *   world (96, 96)   = centre of cell (1,1)   -> u = (1.5+1)/3 = 5/6
 *                                                 = centre of texel 2 ✓
 *   world (0, 0)     = CORNER of cell (0,0)   -> u = 1/3 = the left EDGE of
 *                                                 texel 1
 * There is no half-texel term anywhere in the mapping: the half texel is
 * already the cell's own half.
 *
 * ============================================================================
 * [5] THE SOFT EDGE IS THE LINEAR FILTER — 32 m, half a cell
 * ============================================================================
 * Sampled bilinearly, the value between the centre of an explored cell (1) and
 * the centre of its unexplored neighbour (0) falls linearly over the 64 m
 * between them. Hand-derived along z = 32 (the row of centres) on the grid of
 * ["0,0"], whose only 1 is texel (1,1):
 *
 *     x =   0 m (boundary cell −1|0)  -> 0.5
 *     x =  16 m                       -> 0.75
 *     x =  32 m (cell 0 centre)       -> 1
 *     x =  48 m                       -> 0.75
 *     x =  64 m (boundary cell 0|1)   -> 0.5
 *     x =  80 m                       -> 0.25
 *     x =  96 m (cell 1 centre)       -> 0
 *     x = 128 m (cell 2 centre)       -> 0
 *
 * Read the ramp as the veil sees it: the haze is (1 − value), so it is half
 * strength exactly ON the cell boundary and reaches full strength one cell
 * centre later — i.e. it blends over FOG_BLEND_M = 32 m into each of the two
 * cells. No blur pass, no second texture, no geometry.
 *
 * The sampler used here is a REIMPLEMENTATION of GL_LINEAR + CLAMP_TO_EDGE
 * (texel coordinate `u·cols − 0.5`, mix by the fraction), not a call into the
 * module: the point is that the module's UV mapping lands where a GPU would
 * read it, and asking the module both questions would prove nothing.
 *
 * ============================================================================
 * [6] fogHeightAlpha — the ramp, both ends EXACT
 * ============================================================================
 * smoothstep between FOG_CLEAR_H_M = 20 and FOG_FULL_H_M = 45 (span 25):
 * `t = clamp((h−20)/25, 0, 1)`, `s = t²(3−2t)`.
 *     h =  0    -> t = 0     -> 0            (below the clear height: EXACTLY
 *     h = 20    -> t = 0     -> 0             0, so an embodied player pays
 *                                             nothing at all)
 *     h = 26.25 -> t = 0.25  -> 0.15625      (0.0625·2.5)
 *     h = 32.5  -> t = 0.5   -> 0.5          (0.25·2)
 *     h = 38.75 -> t = 0.75  -> 0.84375      (0.5625·1.5)
 *     h = 45    -> t = 1     -> 1
 *     h = 200   -> t = 1     -> 1
 * and it is monotone in between (checked over 0…60 in 0.25 m steps).
 *
 * WHERE THE TWO ENDS COME FROM — the engine's own zoom tiers, so the veil has
 * no scale of its own. `Engine.update` puts the camera at
 * `dist · sin(pitch)` above its target, with
 * `pitch = lerp(18°, 62°, sqrt((dist − 0.8) / 149.2))`:
 *
 *   dist 34 m = EMBODY_MAX_DIST, the embodied zoom wall
 *     zoomK = 33.2/149.2 = 0.22252, sqrt = 0.47172,
 *     pitch = 18 + 44·0.47172 = 38.756°, sin = 0.62607
 *     -> height 21.29 m.  FOG_CLEAR_H_M = 20 <= 21.29, so everything the
 *        embodied mode can reach is veil-free.
 *   dist 60 m = CLOSE_CAM_DIST, where the open detail view closes
 *     zoomK = 59.2/149.2 = 0.39678, sqrt = 0.62991,
 *     pitch = 18 + 44·0.62991 = 45.716°, sin = 0.71606
 *     -> height 42.96 m.  FOG_FULL_H_M = 45 >= 42.96, so full haze is an
 *        overview state and nothing else.
 *
 * ============================================================================
 * [7] fogVeilAlpha — the product, and what it clamps
 * ============================================================================
 * `FOG_ALPHA_MAX · (1 − explored) · fogHeightAlpha(h)`, with FOG_ALPHA_MAX
 * = 0.72 ("haze, not black" — at 0.72 the land keeps its silhouette).
 *     (h 32.5, e 0)   -> 0.72 · 1   · 0.5 = 0.36
 *     (h 32.5, e 0.5) -> 0.72 · 0.5 · 0.5 = 0.18
 *     (h 32.5, e 1)   -> 0
 *     (h 45,   e 0)   -> 0.72
 *     (h 45,   e 0.5) -> 0.36
 *     (h 10,   e 0)   -> 0            (below the clear height, whatever the
 *                                      ground remembers)
 *     (h 45,   e 2)   -> 0            (a value above 1 is clamped, not
 *                                      subtracted)
 *     (h 45,   e −1)  -> 0.72         (…and below 0 likewise)
 *
 * ============================================================================
 * [8] THE CELLS TEXTURE — what `setFogVeilCells` really uploads
 * ============================================================================
 * `setFogVeilCells(["0,0"])` on the grid of [3]: a 3×3 byte grid, and the ONLY
 * 255 is the texel of cell (0,0) at index `j·cols + i` = `1·3 + 1` = 4:
 *     [0, 0, 0,
 *      0, 255, 0,
 *      0, 0, 0]
 * The geometry uniform says where it lies: (cx0, cz0, cols, rows) =
 * (−1, −1, 3, 3). An empty set uploads the shared NEUTRAL texel (one zero,
 * geometry (0,0,1,1)) — with clamp-to-edge the whole world then samples that
 * zero, which is exactly "nobody has walked anywhere yet".
 *
 * ============================================================================
 * [9] THE PATCH — uniforms, chain, key, anchors, neutrality
 * ============================================================================
 * (a) all seven uniforms bound, the varying declared once, the body inserted
 *     BEFORE `#include <opaque_fragment>` (the anchor the water's sky fresnel
 *     uses: the LIT colour, after every albedo stage);
 * (b) the cache key composes — `ground-hole+fog-veil`, and `fog-veil` alone on
 *     a material without a key of its own;
 * (c) a three version WITHOUT the anchors leaves the shader untouched as a
 *     WHOLE (matte beats broken: a fragment side alone would read a varying
 *     nobody wrote);
 * (d) RED: a mutant that ASSIGNS `onBeforeCompile` instead of chaining loses
 *     the predecessor's uniform. Without this the whole section would pass on
 *     a patch that silently deletes the basement hole;
 * (e) the crossfade: after a new set `uFogMix` is 0, `tickFogVeil(0.3)` with
 *     FOG_FADE_S = 0.6 puts it at 0.5, a second one at 1 — and only THEN do
 *     both samplers point at the same texture (the old one has to stay alive
 *     while it is still being shown);
 * (f) neutrality: below the clear height, with the veil switched off
 *     (isolation toggle 20) or in the admin's unfiltered view, `uFogAlpha` is
 *     EXACTLY 0 and the shader reads no texture at all.
 *
 * ============================================================================
 * [10] THE WIRING — the veil is on the open world's ground
 * ============================================================================
 * A string check on `scene/ground.ts`: `applyFogVeil` is imported and applied
 * at THE ground material site — the CDLOD terrain's own material, which since
 * Wasser v2 K-A E5 is the only one this file builds (the water mirror was the
 * second, and the water is the terrain itself now). It is the very list
 * `applyNaturalGround` is on. Props, scatter and location tiles are
 * deliberately NOT on it (plan § 4).
 *
 * THE WATER-CLASS EXCEPTION WENT WITH THE MIRROR. It existed because a painted
 * lake got a rippled material of its own here and the veil would have fought
 * that shader for the `opaque_fragment` anchor; the terrain's one material is
 * never a water material, so the check below is that no such branch is left.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const MATH_SRC = join(ROOT, 'client3d/src/scene/fogVeilMath.ts');
const VEIL_SRC = join(ROOT, 'client3d/src/scene/fogVeil.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

let passed = 0;
let failed = 0;

function eq(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) { passed += 1; console.log(`  ok   ${label}: ${g}`); return; }
  failed += 1;
  console.log(`  FAIL ${label}: got ${g}, want ${w}`);
}

/** Floating point: the ramp is smoothstep arithmetic, so 1e-12 is generous. */
function near(label, got, want, tol = 1e-12) {
  if (Number.isFinite(got) && Math.abs(got - want) <= tol) {
    passed += 1;
    console.log(`  ok   ${label}: ${got}`);
    return;
  }
  failed += 1;
  console.log(`  FAIL ${label}: got ${got}, want ${want} ±${tol}`);
}

/** The math module has no runtime import (see its header), so a plain
 *  transpile loads it — the rule of `smoke_scatter_math.mjs`. Should someone
 *  add one, this fails loudly, and that is the alarm. */
async function loadMath() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'fogveil-'));
  try {
    const source = await readFile(MATH_SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * Bundle the veil module and import it. `external: ['three']` keeps node's own
 * three the only one in play (the trick of `smoke_surface_patch.mjs`), and the
 * temp directory lives inside `client3d/` so that `three` resolves the way it
 * does for the app.
 *
 * `mutate` rewrites the BUILT text before the import — that is how [9d] gets
 * its mutant without a second copy of the patch lying around to rot.
 */
async function loadVeil(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-fog-'));
  try {
    const entry = 'export { applyFogVeil, setFogVeilCells, setFogVeilCameraHeight,\n'
      + '  setFogVeilDebugOff, setFogVeilFogged, setFogVeilSky, tickFogVeil,\n'
      + `  releaseFogVeil, FOG_VEIL_CACHE_KEY } from '${VEIL_SRC}';\n`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'fogVeil.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    if (mutate && source === text) {
      throw new Error('the mutant changed nothing — the counter-check would be vacuous');
    }
    const file = join(dir, 'fogVeil.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** [9d]'s mutant: the patch ASSIGNS instead of chaining, so the predecessor in
 *  the slot is never called. */
function assignInsteadOfChain(text) {
  const chained = /prev\.call\(mat, shader, renderer\);(\s*)shader\.uniforms\.uFogCellsA =/;
  if (!chained.test(text)) throw new Error('the fog-veil patch no longer chains here');
  return text.replace(chained, 'shader.uniforms.uFogCellsA =');
}

/** A stub of three's standard shader — both anchors as `#include` LINES,
 *  because `onBeforeCompile` sees the shader BEFORE three resolves them. */
function stubShader() {
  return {
    uniforms: {},
    vertexShader: 'void main() {\n#include <project_vertex>\n}\n',
    fragmentShader: 'void main() {\n#include <map_fragment>\n'
      + '#include <opaque_fragment>\n}\n',
  };
}

/** A material with a predecessor already in the `onBeforeCompile` slot and a
 *  cache key of its own — what `scene/ground.ts` really hands over
 *  (`patchHole` has run). The predecessor writes a uniform of its own, which
 *  is how [9d] can see whether it was called. */
function stubMaterial(withPrev = true) {
  const mat = {
    onBeforeCompile: withPrev
      ? (shader) => { shader.uniforms.uPrevRan = { value: 1 }; }
      : () => {},
  };
  if (withPrev) mat.customProgramCacheKey = () => 'ground-hole';
  return mat;
}

/** GL_LINEAR + CLAMP_TO_EDGE, by hand — see the header of [5]. */
function sampleLinear(data, cols, rows, u, v) {
  const tx = u * cols - 0.5;
  const ty = v * rows - 0.5;
  const i0 = Math.floor(tx);
  const j0 = Math.floor(ty);
  const fx = tx - i0;
  const fy = ty - j0;
  const at = (i, j) => {
    const ci = Math.min(Math.max(i, 0), cols - 1);
    const cj = Math.min(Math.max(j, 0), rows - 1);
    return data[cj * cols + ci] / 255;
  };
  const top = at(i0, j0) * (1 - fx) + at(i0 + 1, j0) * fx;
  const bot = at(i0, j0 + 1) * (1 - fx) + at(i0 + 1, j0 + 1) * fx;
  return top * (1 - fy) + bot * fy;
}

const M = await loadMath();

// ── [1] fogCellOf ───────────────────────────────────────────────────────────

console.log('[1] fogCellOf — floor division, the server’s twin');
eq('(a) FOG_CELL_M is the server’s 64 m', M.FOG_CELL_M, 64);
eq('(b) 0 → 0', M.fogCellOf(0), 0);
eq('…63.999 → 0', M.fogCellOf(63.999), 0);
eq('…64 → 1', M.fogCellOf(64), 1);
eq('…100 → 1', M.fogCellOf(100), 1);
eq('…900 → 14', M.fogCellOf(900), 14);
eq('…950 → 14', M.fogCellOf(950), 14);
eq('(c) RED: −1 → −1, not 0', M.fogCellOf(-1), -1);
eq('…−64 → −1', M.fogCellOf(-64), -1);
eq('…−65 → −2', M.fogCellOf(-65), -2);

// ── [2] fogParseCell ────────────────────────────────────────────────────────

console.log('\n[2] fogParseCell — two integers, or nothing');
eq('(d) "0,0"', M.fogParseCell('0,0'), [0, 0]);
eq('…"-1,2"', M.fogParseCell('-1,2'), [-1, 2]);
eq('…"14,1"', M.fogParseCell('14,1'), [14, 1]);
eq('(e) RED: "3.5,1" is dropped', M.fogParseCell('3.5,1'), null);
eq('…RED: "+3,1"', M.fogParseCell('+3,1'), null);
eq('…RED: " 3,1"', M.fogParseCell(' 3,1'), null);
eq('…RED: "3,1,2"', M.fogParseCell('3,1,2'), null);
eq('…RED: "3"', M.fogParseCell('3'), null);
eq('…RED: "a,b"', M.fogParseCell('a,b'), null);
eq('…RED: ""', M.fogParseCell(''), null);

// ── [3] fogGrid ─────────────────────────────────────────────────────────────

console.log('\n[3] fogGrid — bounding box + one cell of zeros on every side');
eq('(f) FOG_PAD_CELLS', M.FOG_PAD_CELLS, 1);
eq('(g) ["0,0"]', M.fogGrid(['0,0']), { cx0: -1, cz0: -1, cols: 3, rows: 3 });
eq('(h) ["0,0","2,1"]', M.fogGrid(['0,0', '2,1']),
   { cx0: -1, cz0: -1, cols: 5, rows: 4 });
eq('(i) ["-3,-3"]', M.fogGrid(['-3,-3']),
   { cx0: -4, cz0: -4, cols: 3, rows: 3 });
eq('(j) an unreadable key is skipped, not guessed at',
   M.fogGrid(['0,0', 'nope']), { cx0: -1, cz0: -1, cols: 3, rows: 3 });
eq('(k) the empty set has no box', M.fogGrid([]), null);
eq('…and neither has one of nothing but noise', M.fogGrid(['nope']), null);

// ── [4] fogTexUv ────────────────────────────────────────────────────────────

console.log('\n[4] fogTexUv — texel centres sit on CELL centres');
const g1 = M.fogGrid(['0,0']);
near('(l) centre of cell (0,0) → centre of texel 1', M.fogTexUv(32, 32, g1)[0], 0.5);
near('…and on v as well', M.fogTexUv(32, 32, g1)[1], 0.5);
near('(m) centre of cell (−1,−1) → centre of texel 0',
     M.fogTexUv(-32, -32, g1)[0], 1 / 6);
near('(n) centre of cell (1,1) → centre of texel 2',
     M.fogTexUv(96, 96, g1)[0], 5 / 6);
near('(o) the CORNER of cell (0,0) → the left edge of texel 1',
     M.fogTexUv(0, 0, g1)[0], 1 / 3);
eq('(p) fogTexIndex: cell (0,0) is texel 1·3+1', M.fogTexIndex(0, 0, g1), 4);
eq('…cell (−1,−1) is texel 0', M.fogTexIndex(-1, -1, g1), 0);
eq('…cell (1,1) is the last one', M.fogTexIndex(1, 1, g1), 8);
eq('…a cell outside the grid is −1', M.fogTexIndex(9, 9, g1), -1);

// ── [5] the soft edge ───────────────────────────────────────────────────────

console.log('\n[5] the soft edge IS the linear filter — 32 m, half a cell');
eq('(q) FOG_BLEND_M is half a cell', M.FOG_BLEND_M, 32);
{
  const data = new Uint8Array(9);
  data[M.fogTexIndex(0, 0, g1)] = 255;
  const seenAt = (x) => {
    const [u, v] = M.fogTexUv(x, 32, g1);
    return sampleLinear(data, g1.cols, g1.rows, u, v);
  };
  near('(r) x = 0 m (boundary −1|0) → 0.5', seenAt(0), 0.5);
  near('…x = 16 m → 0.75', seenAt(16), 0.75);
  near('…x = 32 m (cell centre) → 1', seenAt(32), 1);
  near('…x = 48 m → 0.75', seenAt(48), 0.75);
  near('…x = 64 m (boundary 0|1) → 0.5', seenAt(64), 0.5);
  near('…x = 80 m → 0.25', seenAt(80), 0.25);
  near('…x = 96 m (neighbour centre) → 0', seenAt(96), 0);
  near('…x = 128 m (one cell further) → 0', seenAt(128), 0);
  // The statement of the section, said as one number: the ramp is over by
  // FOG_BLEND_M metres past the boundary, in BOTH directions.
  near('(s) the ramp is exhausted 32 m past the boundary',
       seenAt(64 + M.FOG_BLEND_M), 0);
  near('…and full 32 m before it', seenAt(64 - M.FOG_BLEND_M), 1);
}

// ── [6] fogHeightAlpha ──────────────────────────────────────────────────────

console.log('\n[6] fogHeightAlpha — smoothstep, both ends exact');
eq('(t) FOG_CLEAR_H_M', M.FOG_CLEAR_H_M, 20);
eq('…FOG_FULL_H_M', M.FOG_FULL_H_M, 45);
eq('(u) h = 0 → EXACTLY 0', M.fogHeightAlpha(0), 0);
eq('…h = 20 → EXACTLY 0', M.fogHeightAlpha(20), 0);
near('…h = 26.25 → 0.15625', M.fogHeightAlpha(26.25), 0.15625);
near('…h = 32.5 → 0.5', M.fogHeightAlpha(32.5), 0.5);
near('…h = 38.75 → 0.84375', M.fogHeightAlpha(38.75), 0.84375);
eq('…h = 45 → EXACTLY 1', M.fogHeightAlpha(45), 1);
eq('…h = 200 → 1', M.fogHeightAlpha(200), 1);
{
  let bad = 0;
  let prev = -1;
  for (let h = 0; h <= 60; h += 0.25) {
    const v = M.fogHeightAlpha(h);
    if (v < prev - 1e-15 || v < 0 || v > 1) bad += 1;
    prev = v;
  }
  eq('(v) monotone and inside 0…1 over 0…60 m (241 samples), failures', bad, 0);
}
{
  // The two ends against the engine's own zoom tiers — see the header of [6].
  const camHeight = (dist) => {
    const zoomK = Math.min(Math.max((dist - 0.8) / (150 - 0.8), 0), 1);
    const pitch = 18 + (62 - 18) * Math.sqrt(zoomK);
    return dist * Math.sin(pitch * Math.PI / 180);
  };
  near('(w) the embodied zoom wall (34 m) is 21.29 m up', camHeight(34), 21.29, 0.01);
  eq('…and the veil is already gone there', M.FOG_CLEAR_H_M <= camHeight(34), true);
  near('(x) the overview threshold (60 m) is 42.96 m up', camHeight(60), 42.96, 0.01);
  eq('…and full haze starts only past it', M.FOG_FULL_H_M >= camHeight(60), true);
}

// ── [7] fogVeilAlpha ────────────────────────────────────────────────────────

console.log('\n[7] fogVeilAlpha — the product');
eq('(y) FOG_ALPHA_MAX ("haze, not black")', M.FOG_ALPHA_MAX, 0.72);
near('(z) h 32.5, explored 0 → 0.36', M.fogVeilAlpha(32.5, 0), 0.36);
near('…h 32.5, explored 0.5 → 0.18', M.fogVeilAlpha(32.5, 0.5), 0.18);
eq('…h 32.5, explored 1 → 0', M.fogVeilAlpha(32.5, 1), 0);
near('…h 45, explored 0 → 0.72', M.fogVeilAlpha(45, 0), 0.72);
near('…h 45, explored 0.5 → 0.36', M.fogVeilAlpha(45, 0.5), 0.36);
eq('(aa) h 10 → 0 whatever the ground remembers', M.fogVeilAlpha(10, 0), 0);
eq('(ab) explored 2 is clamped, not subtracted', M.fogVeilAlpha(45, 2), 0);
near('…and explored −1 likewise', M.fogVeilAlpha(45, -1), 0.72);

// ── [8]/[9] the module on the GPU side ──────────────────────────────────────

const V = await loadVeil();

console.log('\n[8] the cells texture — what setFogVeilCells uploads');
{
  const mat = stubMaterial();
  V.applyFogVeil(mat);
  const shader = stubShader();
  mat.onBeforeCompile(shader, null);
  V.setFogVeilCells(['0,0']);
  const tex = shader.uniforms.uFogCellsB.value;
  eq('(ac) 3 × 3 texels', [tex.image.width, tex.image.height], [3, 3]);
  eq('(ad) and the ONLY 255 is the texel of cell (0,0)',
     [...tex.image.data], [0, 0, 0, 0, 255, 0, 0, 0, 0]);
  const geom = shader.uniforms.uFogGeomB.value;
  eq('(ae) the geometry says where it lies: cx0, cz0, cols, rows',
     [geom.x, geom.y, geom.z, geom.w], [-1, -1, 3, 3]);
  V.setFogVeilCells([]);
  const empty = shader.uniforms.uFogCellsB.value;
  eq('(af) an empty memory is the one neutral zero texel',
     [empty.image.width, empty.image.height, [...empty.image.data][0]], [1, 1, 0]);
  V.releaseFogVeil();
}

console.log('\n[9] the shader patch');
{
  const mat = stubMaterial();
  V.applyFogVeil(mat);
  const shader = stubShader();
  mat.onBeforeCompile(shader, null);
  eq('(ag) the predecessor in the slot RAN (chained, not assigned)',
     !!shader.uniforms.uPrevRan, true);
  const want = ['uFogCellsA', 'uFogCellsB', 'uFogGeomA', 'uFogGeomB',
                'uFogMix', 'uFogAlpha', 'uFogColor'];
  eq('(ah) all seven uniforms bound',
     want.filter((u) => !(u in shader.uniforms)), []);
  eq('(ai) the world position is declared once',
     (shader.vertexShader.match(/varying vec2 vFogWorld;/g) || []).length, 1);
  eq('…and written after project_vertex',
     shader.vertexShader.includes('vFogWorld = ( modelMatrix'), true);
  eq('(aj) the haze MIXES towards the haze colour, it does not multiply',
     shader.fragmentShader.includes('outgoingLight = mix( outgoingLight, uFogColor,'),
     true);
  eq('…guarded, so nothing is read below the clear height',
     shader.fragmentShader.includes('if ( uFogAlpha > 0.0 )'), true);
  eq('…and the two grids are crossfaded',
     shader.fragmentShader.includes('uFogMix )'), true);
  const body = shader.fragmentShader.indexOf('outgoingLight = mix( outgoingLight');
  const anchor = shader.fragmentShader.indexOf('#include <opaque_fragment>');
  eq('(ak) the body stands BEFORE the anchor, on the lit colour',
     body >= 0 && anchor > body, true);
  eq('(al) the cell size is printed from the shared constant',
     shader.fragmentShader.includes('p / 64.0'), true);
  eq('(am) the key composes', mat.customProgramCacheKey(),
     `ground-hole+${V.FOG_VEIL_CACHE_KEY}`);
  const plain = stubMaterial(false);
  V.applyFogVeil(plain);
  eq('…and is the bare key without a predecessor',
     plain.customProgramCacheKey(), V.FOG_VEIL_CACHE_KEY);
  // Applying twice is still ONE patch (the WeakSet) — a second varying
  // declaration would not compile.
  V.applyFogVeil(mat);
  const twice = stubShader();
  mat.onBeforeCompile(twice, null);
  eq('(an) applying twice declares the varying once',
     (twice.vertexShader.match(/varying vec2 vFogWorld;/g) || []).length, 1);
}
{
  // (c): a three version without the anchors leaves the shader untouched as a
  // whole — never the fragment half alone.
  const mat = stubMaterial();
  V.applyFogVeil(mat);
  const shader = stubShader();
  shader.vertexShader = 'void main() {}\n';
  mat.onBeforeCompile(shader, null);
  eq('(ao) no vertex anchor → the fragment side is not patched either',
     shader.fragmentShader.includes('uFogColor'), false);
  eq('…and the uniforms are still bound (they cost nothing)',
     'uFogAlpha' in shader.uniforms, true);
}
{
  // (e) the crossfade.
  const mat = stubMaterial();
  V.applyFogVeil(mat);
  const shader = stubShader();
  mat.onBeforeCompile(shader, null);
  V.setFogVeilCells(['0,0']);
  eq('(ap) a new memory starts the fade at 0', shader.uniforms.uFogMix.value, 0);
  V.tickFogVeil(0.3);
  near('…half a FOG_FADE_S later it is 0.5', shader.uniforms.uFogMix.value, 0.5);
  eq('…and the OLD grid is still bound while it is shown',
     shader.uniforms.uFogCellsA.value === shader.uniforms.uFogCellsB.value, false);
  V.tickFogVeil(0.3);
  eq('(aq) after FOG_FADE_S the fade is over', shader.uniforms.uFogMix.value, 1);
  eq('…and both samplers point at the new grid',
     shader.uniforms.uFogCellsA.value === shader.uniforms.uFogCellsB.value, true);
  V.tickFogVeil(1);
  eq('…a tick on a settled veil changes nothing',
     shader.uniforms.uFogMix.value, 1);

  // (f) neutrality.
  V.setFogVeilFogged(true);
  V.setFogVeilDebugOff(false);
  V.setFogVeilCameraHeight(10);
  eq('(ar) below the clear height the alpha is EXACTLY 0',
     shader.uniforms.uFogAlpha.value, 0);
  V.setFogVeilCameraHeight(45);
  near('…at the full height it is FOG_ALPHA_MAX',
       shader.uniforms.uFogAlpha.value, 0.72);
  V.setFogVeilDebugOff(true);
  eq('(as) isolation toggle 20 switches it off',
     shader.uniforms.uFogAlpha.value, 0);
  V.setFogVeilDebugOff(false);
  near('…and switching it back restores what the CAMERA says now',
       shader.uniforms.uFogAlpha.value, 0.72);
  V.setFogVeilFogged(false);
  eq('(at) the admin’s unfiltered view gets no veil',
     shader.uniforms.uFogAlpha.value, 0);
  V.setFogVeilFogged(true);
  V.releaseFogVeil();
}
{
  // (d) RED: the mutant that assigns instead of chaining.
  const mutant = await loadVeil(assignInsteadOfChain);
  const mat = stubMaterial();
  mutant.applyFogVeil(mat);
  const shader = stubShader();
  mat.onBeforeCompile(shader, null);
  eq('(au) RED: assigning instead of chaining loses the predecessor',
     'uPrevRan' in shader.uniforms, false);
  eq('…while the veil itself still patches (so the mutant is the CHAIN alone)',
     'uFogAlpha' in shader.uniforms, true);
}

// ── [10] the wiring ─────────────────────────────────────────────────────────

console.log('\n[10] the veil is on the open world’s ground, and on nothing else');
{
  const ground = await readFile(GROUND_SRC, 'utf8');
  eq('(av) ground.ts imports the patch',
     /import \{ applyFogVeil \} from '\.\/fogVeil';/.test(ground), true);
  eq('(aw) …and applies it at THE ground material site — the one that is left',
     (ground.match(/applyFogVeil\(mat\);/g) || []).length, 1);
  eq('(ax) RED: and no water-class branch stands beside it any more',
     /isWaterClass/.test(ground), false);
}

console.log(`\n${passed + failed} checks, ${failed} failure(s)`);
process.exit(failed ? 1 : 0);
