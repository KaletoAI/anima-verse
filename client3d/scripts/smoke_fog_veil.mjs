#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/fog_veil.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_fog_veil.mjs
 *         (transpiles `scene/fogVeilMath.ts`; bundles `scene/fogVeil.ts`,
 *          needs three)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const MATH_SRC = join(ROOT, 'client3d/src/scene/fogVeilMath.ts');
const VEIL_SRC = join(ROOT, 'client3d/src/scene/fogVeil.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

let passed = 0;
function vector(label, fns) {
  const result = vectorCase("fog_veil", label, fns);
  passed += result.passed; failed += result.failed;
}

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
vector("[1] fog_veil: (b) 0 → 0", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …63.999 → 0", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …64 → 1", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …100 → 1", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …900 → 14", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …950 → 14", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: (c) RED: −1 → −1, not 0", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …−64 → −1", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });
vector("[1] fog_veil: …−65 → −2", { fogCellOf: (...args) => M.fogCellOf(...vectorArgs(args)) });

// ── [2] fogParseCell ────────────────────────────────────────────────────────

console.log('\n[2] fogParseCell — two integers, or nothing');
vector("[2] fog_veil: (d) \"0,0\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …\"-1,2\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …\"14,1\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: (e) RED: \"3.5,1\" is dropped", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …RED: \"+3,1\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …RED: \" 3,1\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …RED: \"3,1,2\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …RED: \"3\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …RED: \"a,b\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });
vector("[2] fog_veil: …RED: \"\"", { fogParseCell: (...args) => M.fogParseCell(...vectorArgs(args)) });

// ── [3] fogGrid ─────────────────────────────────────────────────────────────

console.log('\n[3] fogGrid — bounding box + one cell of zeros on every side');
eq('(f) FOG_PAD_CELLS', M.FOG_PAD_CELLS, 1);
vector("[3] fog_veil: (g) [\"0,0\"]", { fogGrid: (...args) => M.fogGrid(...vectorArgs(args)) });
vector("[3] fog_veil: (h) [\"0,0\",\"2,1\"]", { fogGrid: (...args) => M.fogGrid(...vectorArgs(args)) });
vector("[3] fog_veil: (i) [\"-3,-3\"]", { fogGrid: (...args) => M.fogGrid(...vectorArgs(args)) });
vector("[3] fog_veil: (j) an unreadable key is skipped, not guessed at", { fogGrid: (...args) => M.fogGrid(...vectorArgs(args)) });
vector("[3] fog_veil: (k) the empty set has no box", { fogGrid: (...args) => M.fogGrid(...vectorArgs(args)) });
vector("[3] fog_veil: …and neither has one of nothing but noise", { fogGrid: (...args) => M.fogGrid(...vectorArgs(args)) });

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
vector("[6] fog_veil: (u) h = 0 → EXACTLY 0", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
vector("[6] fog_veil: …h = 20 → EXACTLY 0", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
vector("[6] fog_veil: …h = 26.25 → 0.15625", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
vector("[6] fog_veil: …h = 32.5 → 0.5", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
vector("[6] fog_veil: …h = 38.75 → 0.84375", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
vector("[6] fog_veil: …h = 45 → EXACTLY 1", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
vector("[6] fog_veil: …h = 200 → 1", { fogHeightAlpha: (...args) => M.fogHeightAlpha(...vectorArgs(args)) });
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
vector("[7] fog_veil: (z) h 32.5, explored 0 → 0.36", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: …h 32.5, explored 0.5 → 0.18", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: …h 32.5, explored 1 → 0", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: …h 45, explored 0 → 0.72", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: …h 45, explored 0.5 → 0.36", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: (aa) h 10 → 0 whatever the ground remembers", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: (ab) explored 2 is clamped, not subtracted", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });
vector("[7] fog_veil: …and explored −1 likewise", { fogVeilAlpha: (...args) => M.fogVeilAlpha(...vectorArgs(args)) });

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
