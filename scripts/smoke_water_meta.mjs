/**
 * smoke_water_meta.mjs — what the admin UI reads and draws about WATER.
 *
 * Usage: node scripts/smoke_water_meta.mjs
 *
 * WHAT IS PINNED HERE, and why it is worth a check of its own (§ A16.3 plus
 * the addendum "Ein Wasser-Gesetz — W1"): a water area carries its mirror, its
 * two shape numbers, its FLOW DIRECTION and its BED in the terrain area's
 * FREE-FORM `meta`. Free-form means the editor gets whatever the server, a
 * world-dev apply or an older world wrote there, and `mapTypes.readWater` /
 * `readWaterProfile` are the one place that turn it into numbers.
 *
 * The trap is JavaScript's own coercion, and it is not hypothetical:
 *
 *     Number(null) === 0        Number('') === 0        Number([]) === 0
 *
 * so a naive `Number(meta.water_depth_m)` reads a MISSING key as "0 m deep" —
 * a lake with no bed at all — and a missing level as "sea level", which under
 * the bake means a mountain lake dropping to y = 0 the first time somebody
 * opens its chip. "The kind decides" (absent key) and "0" are different
 * answers, and only one of them may be inferred from junk. Every expectation
 * below is derived from the contract by hand, not recorded from the current
 * output.
 *
 * THE ONE PREDICATE is checked here too (`isWaterKind`): since W1 nothing in
 * this editor may ask a kind's NAME or a texture's material class — only
 * `meta.water` on the terrain type. A world whose river kind is called
 * `lagoon` must behave exactly like one whose kind is called `water`, and the
 * kind called `water` WITHOUT the flag must behave like dry ground.
 *
 * AND THE FLOW ARROW, by hand from the contract's yaw mapping (§ A1.1):
 * `dir = (sin θ, cos θ)`, so 0° runs toward +z and 90° toward +x. An arrow
 * drawn any other way would point where the water does not go, which is the
 * single thing the preview exists to rule out. Its axis runs through the
 * polygon's AREA centroid — the very point `heightfield.WaterProfile` builds
 * its axis around — and not through the mean of the vertices, which a densely
 * pointed bank would drag off the water.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const TYPES_SRC = join(ROOT, 'frontend/src/tabs/map/mapTypes.ts');
const MATH_SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');
const TOOLS_SRC = join(ROOT, 'frontend/src/tabs/map/TerrainTools.tsx');
const WORLD_SRC = join(ROOT, 'frontend/src/tabs/world/worldTypes.ts');

/** One TS file, type-stripped and imported. `mapTypes.ts` carries only
 *  `import type`, so a single-file transform is enough — the
 *  `smoke_height_math.mjs` recipe. */
async function loadModule(src, loader, prefix) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), prefix));
  try {
    const source = await readFile(src, 'utf8');
    const out = esbuild.transformSync(source, { loader, format: 'esm' });
    const file = join(dir, 'mod.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Bundled and imported — `mapMath` pulls in the workspace package
 *  `@anima/scene-render`, which esbuild resolves and inlines. The
 *  `smoke_scatter_preview.mjs` recipe. */
async function loadBundled(src, prefix) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), prefix));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * The exported CONSTANTS of a source file, read out of its text.
 *
 * `TerrainTools.tsx` cannot be imported here: it pulls in React and the i18n
 * provider, and a smoke that needs a rendering runtime to state a range is a
 * smoke nobody runs. Reading the `export const NAME = <number>` lines is the
 * whole point anyway — the numbers, checked against the contract by hand.
 * A name the file stops exporting comes back `undefined` and fails loudly.
 */
async function readConsts(src, names) {
  const source = await readFile(src, 'utf8');
  const out = {};
  for (const name of names) {
    const m = source.match(
      new RegExp(`^export const ${name} = ('[^']*'|-?[0-9.]+)$`, 'm'));
    if (!m) continue;
    out[name] = m[1].startsWith("'")
      ? m[1].slice(1, -1)
      : Number(m[1]);
  }
  return out;
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

/** Two numbers agree to the millimetre — the server rounds its own water
 *  numbers to three decimals, so anything finer is noise either way. */
function near(label, actual, expected, tol = 1e-3) {
  const a = Array.isArray(actual) ? actual : [actual];
  const e = Array.isArray(expected) ? expected : [expected];
  const ok = a.length === e.length
    && a.every((v, i) => Math.abs(v - e[i]) <= tol);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(e)}`
      + `\n       actual   ${JSON.stringify(a)}`);
  }
}

const {
  readWater, readWaterProfile, isWaterKind, waterKindDefaults,
} = await loadModule(TYPES_SRC, 'ts', 'watermeta-');
const {
  polygonCentroid, flowDirection, flowArrow, flowCompass,
} = await loadBundled(MATH_SRC, 'watermath-');
const { readMapWater } = await loadModule(WORLD_SRC, 'ts', 'waterref-');
const {
  WATER_DEPTH_DEFAULT_M, SHORE_RAMP_DEFAULT_M, WATER_DEPTH_MIN_M,
  WATER_DEPTH_MAX_M, SHORE_RAMP_MIN_M, SHORE_RAMP_MAX_M,
  FLOW_DIR_MIN_DEG, FLOW_DIR_MAX_DEG,
} = await readConsts(TYPES_SRC, [
  'WATER_DEPTH_DEFAULT_M', 'SHORE_RAMP_DEFAULT_M', 'WATER_DEPTH_MIN_M',
  'WATER_DEPTH_MAX_M', 'SHORE_RAMP_MIN_M', 'SHORE_RAMP_MAX_M',
  'FLOW_DIR_MIN_DEG', 'FLOW_DIR_MAX_DEG',
]);
const { WATER_LEVEL_SPAN_M, HEIGHT_MAX_M } = await readConsts(TOOLS_SRC, [
  'WATER_LEVEL_SPAN_M', 'HEIGHT_MAX_M',
]);

console.log('[1] nothing stored means nothing read');
check('no meta at all', readWater(undefined), {});
check('an empty meta', readWater({}), {});
check('a meta with other keys only',
  readWater({ scatter: [], stroke: { points: [], width_m: 4 } }), {});

console.log('[2] the coercion trap — 0 is never inferred');
check('null is not 0 m deep', readWater({ water_depth_m: null }), {});
check('an empty string is not sea level', readWater({ water_level: '' }), {});
check('...nor is a blank one', readWater({ water_level: '   ' }), {});
check('an empty array is not a shore ramp',
  readWater({ shore_ramp_m: [] }), {});
check('an object is not a depth', readWater({ water_depth_m: {} }), {});
check('a word is not a level', readWater({ water_level: 'auto' }), {});
check('NaN is not a level', readWater({ water_level: NaN }), {});
check('...and neither is infinity', readWater({ water_level: Infinity }), {});
check('an empty bed kind is no bed', readWater({ bed_kind: '  ' }), {});
check('a bed kind that is not a string is no bed',
  readWater({ bed_kind: 7 }), {});

console.log('[3] real numbers survive, including the honest zeroes');
check('a level of 0 IS sea level, not "unset"',
  readWater({ water_level: 0 }), { water_level: 0 });
check('a shore ramp of 0 IS a wall at the shore',
  readWater({ shore_ramp_m: 0 }), { shore_ramp_m: 0 });
check('a negative level is a lake below sea level',
  readWater({ water_level: -3.5 }), { water_level: -3.5 });
check('a numeric string is a number (JSON round trips)',
  readWater({ water_depth_m: '2.5' }), { water_depth_m: 2.5 });
check('everything at once, foreign keys dropped',
  readWater({
    water_level: 12.25, water_depth_m: 4, shore_ramp_m: 6,
    water_level_up: 7.4, water_level_down: 2.6, flow_dir_deg: 270,
    bed_kind: ' sand ',
    scatter: [{ density_per_100m2: 1 }],
  }),
  {
    water_level: 12.25, water_level_up: 7.4, water_level_down: 2.6,
    flow_dir_deg: 270, water_depth_m: 4, shore_ramp_m: 6, bed_kind: 'sand',
  });

console.log('[4] the flow bearing is WRAPPED, never clamped');
// `heightfield.sanitize_flow_dir`: a bearing is an angle, so 370° is 10° and
// −90° is 270°. Clamping would turn a slip of the wrist into a river flowing
// the wrong way along its own axis — the one error nobody would spot in a
// blue polygon.
check('370° is 10°', readWater({ flow_dir_deg: 370 }), { flow_dir_deg: 10 });
check('−90° is 270°', readWater({ flow_dir_deg: -90 }), { flow_dir_deg: 270 });
check('720° is 0°', readWater({ flow_dir_deg: 720 }), { flow_dir_deg: 0 });
check('0° survives as a bearing, not as "unset"',
  readWater({ flow_dir_deg: 0 }), { flow_dir_deg: 0 });

console.log('[5] THE ONE PREDICATE — the flag, never the name');
check('the flag makes any kind water',
  isWaterKind({ kind: 'lagoon', meta: { water: true } }), true);
check('a kind CALLED water without the flag is dry ground',
  isWaterKind({ kind: 'water', meta: {} }), false);
check('...and so is one with no meta at all',
  isWaterKind({ kind: 'water' }), false);
check('an unknown kind is not water', isWaterKind(undefined), false);
check('a falsy flag is not water',
  isWaterKind({ kind: 'water', meta: { water: false } }), false);

console.log('[6] the KIND defaults, and the AREA overriding them');
check('a kind that says nothing gives the module defaults',
  waterKindDefaults({ kind: 'water', meta: { water: true } }),
  { depthM: WATER_DEPTH_DEFAULT_M, rampM: SHORE_RAMP_DEFAULT_M });
check('a kind that says something gives that',
  waterKindDefaults({ kind: 'river',
    meta: { water: true, water_depth_m: 6, shore_ramp_m: 0 } }),
  { depthM: 6, rampM: 0 });
check('a shore ramp of 0 on the kind is a VALUE, not "unset"',
  waterKindDefaults({ kind: 'pool', meta: { water: true, shore_ramp_m: 0 } })
    .rampM, 0);
check('an unreadable kind default falls back, it does not become 0',
  waterKindDefaults({ kind: 'x', meta: { water_depth_m: null } }).depthM,
  WATER_DEPTH_DEFAULT_M);
// The AREA's own numbers are the ones `readWater` hands back; the panel puts
// the kind's number in the PLACEHOLDER. The two readers are separate on
// purpose — an area with no key must show the kind's number, not store it.
check('an area that overrides the kind reads its own number',
  readWater({ water_depth_m: 1.5 }).water_depth_m, 1.5);
check('an area that overrides nothing reads no number at all',
  readWater({}).water_depth_m, undefined);

console.log('[7] the profile — nine numbers or nothing');
const PROFILE = {
  level_up: 7.4, level_down: 2.6, flow_dir_deg: 270,
  axis_x: 50, axis_z: -30, dir_x: -1, dir_z: 0, s_min: -30, s_max: 30,
};
check('the payload example of the addendum, verbatim',
  readWaterProfile({ water_profile: PROFILE }),
  { ...PROFILE, flow_dir_deg: 270 });
check('a profile missing one number is no profile',
  readWaterProfile({ water_profile: { ...PROFILE, s_max: undefined } }), null);
check('still water carries a null bearing, not a missing key',
  readWaterProfile({ water_profile: { ...PROFILE, flow_dir_deg: null } })
    ?.flow_dir_deg, null);
check('no profile key at all', readWaterProfile({}), null);
check('a profile that is not an object', readWaterProfile({ water_profile: 3 }),
  null);

console.log('[8] the yaw convention — 0° to +z, 90° to +x (§ A1.1)');
// `heightfield.flow_direction`, by hand: (sin θ, cos θ), rounded so the
// cardinals come out exactly axis-aligned.
check('0° flows toward +z (south on this map)', flowDirection(0), [0, 1]);
check('90° flows toward +x (east)', flowDirection(90), [1, 0]);
check('180° flows toward −z (north)', flowDirection(180), [0, -1]);
check('270° flows toward −x (west)', flowDirection(270), [-1, 0]);
near('45° is the diagonal', flowDirection(45),
  [Math.SQRT1_2, Math.SQRT1_2]);
check('and the readback names the same four', [
  flowCompass(0), flowCompass(90), flowCompass(180), flowCompass(270),
], ['S', 'E', 'N', 'W']);
check('45° reads SE — between south and east, as the vector says',
  flowCompass(45), 'SE');

console.log('[9] the AREA centroid, not the mean of the vertices');
// A 100 × 20 m rectangle: both formulas agree, so it pins the arithmetic.
const RECT = [[0, 0], [100, 0], [100, 20], [0, 20]];
near('a rectangle has its centre where anyone would put it',
  polygonCentroid(RECT), [50, 10]);
// The same rectangle with FOUR extra points along the bottom bank. The vertex
// mean is dragged to z = 20/8 = 2.5; the area centroid does not move at all —
// which is the whole reason the server uses this formula and so does the
// preview.
const DENSE = [[0, 0], [25, 0], [50, 0], [75, 0], [100, 0],
  [100, 20], [50, 20], [0, 20]];
const vertexMean = DENSE.reduce((acc, [x, z]) => [acc[0] + x / DENSE.length,
  acc[1] + z / DENSE.length], [0, 0]);
near('the vertex mean is dragged onto the dense bank', vertexMean, [50, 7.5]);
near('the area centroid stays in the middle of the water',
  polygonCentroid(DENSE), [50, 10]);
// A degenerate ring (all points on one line) has no centroid: the vertex mean
// answers, because a marker roughly in place beats no marker at all.
near('a collinear ring falls back to the vertex mean',
  polygonCentroid([[0, 0], [10, 0], [20, 0]]), [10, 0]);

console.log('[10] the flow arrow, by hand');
// The 100 × 20 rectangle, flowing east (90°). Its extent along that axis is
// 100 m, the arrow takes half of it (50 m) and is centred on [50, 10]:
//   from = [50 − 25, 10] = [25, 10]      to = [50 + 25, 10] = [75, 10]
// The barbs sit len/4 = 12.5 m back from the tip and len·0.15 = 7.5 m out to
// either side, along the perpendicular (−dz, dx) = (0, 1):
//   [75 − 12.5, 10 ± 7.5] = [62.5, 17.5] and [62.5, 2.5]
const east = flowArrow(RECT, 90);
near('it starts a quarter-span upstream of the centroid', east.from, [25, 10]);
near('...and points a quarter-span downstream', east.to, [75, 10]);
near('the barbs sit back from the tip, one each side',
  [...east.barbs[0], ...east.barbs[1]], [62.5, 17.5, 62.5, 2.5]);
// The SAME rectangle flowing north (180°): the extent along that axis is only
// 20 m, so half of it is 10 m and the arrow runs from z = 15 to z = 5 —
// upstream is the HIGHER z, because 180° points toward −z.
const north = flowArrow(RECT, 180);
near('a cross-wise flow uses the cross-wise extent',
  [...north.from, ...north.to], [50, 15, 50, 5]);
check('still water gets no arrow at all', flowArrow(RECT, undefined), null);
check('and neither does a shape that is not a polygon',
  flowArrow([[0, 0], [1, 1]], 90), null);
// The clamps: a brook 2 m across would get a 1 m arrow, a 400 m river a 200 m
// one. Neither reads — the first is a dot, the second leaves the water at the
// bends — so the length is held between 4 m and 60 m.
const tiny = flowArrow([[0, 0], [2, 0], [2, 2], [0, 2]], 90);
near('a tiny pond still gets a legible 4 m arrow',
  Math.hypot(tiny.to[0] - tiny.from[0], tiny.to[1] - tiny.from[1]), 4);
const huge = flowArrow([[0, 0], [400, 0], [400, 50], [0, 50]], 90);
near('a long river is capped at 60 m',
  Math.hypot(huge.to[0] - huge.from[0], huge.to[1] - huge.from[1]), 60);

console.log('[11] the knob ranges the panels offer');
check('depth sweeps 0.2…20 m',
  [WATER_DEPTH_MIN_M, WATER_DEPTH_MAX_M], [0.2, 20]);
check('the default depth is inside that range',
  WATER_DEPTH_DEFAULT_M >= WATER_DEPTH_MIN_M
  && WATER_DEPTH_DEFAULT_M <= WATER_DEPTH_MAX_M, true);
check('the shore ramp starts at a wall and ends at 20 m',
  [SHORE_RAMP_MIN_M, SHORE_RAMP_MAX_M], [0, 20]);
check('the default shore ramp is inside that range',
  SHORE_RAMP_DEFAULT_M >= SHORE_RAMP_MIN_M
  && SHORE_RAMP_DEFAULT_M <= SHORE_RAMP_MAX_M, true);
check('the bearing sweeps a whole turn',
  [FLOW_DIR_MIN_DEG, FLOW_DIR_MAX_DEG], [0, 360]);

// The level knob, by hand from the rule in `WaterFields`:
//   unset  -> [-HEIGHT_MAX_M, +HEIGHT_MAX_M]              = [-50, 50]
//   set 12 -> [12 - 10, 12 + 10] clamped to ±50           = [2, 22]
//   set 45 -> [45 - 10, min(50, 45 + 10)]                 = [35, 50]
const levelRange = (level) => (level === undefined
  ? [-HEIGHT_MAX_M, HEIGHT_MAX_M]
  : [Math.max(-HEIGHT_MAX_M, level - WATER_LEVEL_SPAN_M),
    Math.min(HEIGHT_MAX_M, level + WATER_LEVEL_SPAN_M)]);
check('an unset level reaches every height a world has',
  levelRange(undefined), [-50, 50]);
check('a set level is trimmed ±10 m around itself',
  levelRange(12), [2, 22]);
check('...and never past the world clamp',
  levelRange(45), [35, 50]);

console.log('[12] the floor plan says WHERE the water is, never how deep');
// W1 § 6: a room lying on painted water carries a REFERENCE and nothing more.
// The plan panel shows it as a line and offers no dial, because the room owns
// no mirror — the area does.
check('the addendum example, verbatim',
  readMapWater({ room_id: 'pond', polygon_world: [], floor_kind: 'sand',
    closed: false, map_water: { area_id: 'ta_pool', kind: 'water' } }),
  { area_id: 'ta_pool', kind: 'water' });
check('a room that is not on water says nothing',
  readMapWater({ room_id: 'hall', polygon_world: [], floor_kind: 'floor',
    closed: true }), null);
check('an older server that never sends the field says nothing',
  readMapWater(undefined), null);
check('half a reference is no reference',
  readMapWater({ map_water: { area_id: 'ta_pool' } }), null);
check('...in either direction',
  readMapWater({ map_water: { kind: 'water' } }), null);
check('and neither is a blank one',
  readMapWater({ map_water: { area_id: '  ', kind: 'water' } }), null);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
