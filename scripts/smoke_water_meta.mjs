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
 *
 * SINCE W4a A DRAWN RIVER FLOWS ALONG ITS OWN LINE ([13]…[15]), and the admin
 * is the THIRD implementation of one function: `heightfield.water_level_at`,
 * `client3d/src/scene/waterPlaneMath.ts` and `mapMath.waterLevelAt` must
 * answer the same number, or the preview draws a river the bake did not carve.
 * The hairpin below is the server smoke's own case
 * (`scripts/smoke_height_bake.py` [8k]) with its numbers re-derived here by
 * hand — including the RED counter-check that the straight axis of W1 gets the
 * middle of a bend wrong, which is the whole reason the axis became a
 * polyline.
 *
 * AND SINCE 2026-08-23 AN AREA MAY SAY HOW FAST IT RUNS ([16],
 * `meta.flow_speed_m_s`). It is an OVERRIDE of the surface KIND's `flow_speed`
 * dial, so it is read with that dial's own range and CLAMPED — 5 m/s is "as
 * fast as this goes", not the 3 m/s a wrapped bearing would make of it. The
 * renderers never receive the metres per second: `waterFlowFactor`
 * (`@anima/scene-render`, pinned here because the admin's number and the
 * renderer's factor must be one number) turns it into the RATIO against the
 * kind, which travels as the LENGTH of the per-vertex flow attribute so the
 * shader can multiply its kind-wide `uFlowSpeed` by it. Two consequences are
 * checked by hand: no override is EXACTLY 1 (the unit tangent every water has
 * carried since W4a, i.e. nothing already built moves differently), and an
 * authored 0 is floored to 1e-3 — a zero-length vector is what the shader
 * spells "lake", and a lake drifts at 0.25 m/s, which is FASTER than the
 * standstill the author asked for.
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
  flowArrowsAlong, flowAxisPoints, waterFlowAt, waterLevelAt,
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
const { HEIGHT_MAX_M } = await readConsts(TOOLS_SRC, ['HEIGHT_MAX_M']);
const {
  FLOW_SPEED_MIN_M_S, FLOW_SPEED_MAX_M_S, FLOW_SPEED_DEFAULT_M_S,
} = await readConsts(TYPES_SRC, [
  'FLOW_SPEED_MIN_M_S', 'FLOW_SPEED_MAX_M_S', 'FLOW_SPEED_DEFAULT_M_S',
]);
// The RENDER side of the same number, from the package both renderers share:
// `waterFlowFactor` turns the area's metres per second into the factor the
// shader multiplies its kind's `uFlowSpeed` by. `materials.ts` carries only
// `import type`, so the single-file transform above reaches it.
const { waterFlowFactor, WATER_FLOW_FACTOR_MIN, WATER_FLOW_SPEED_DEFAULT_M_S,
  WATER_FLOW_SPEED_MAX_M_S } = await loadModule(
  join(ROOT, 'packages/scene-render/src/materials.ts'), 'ts', 'watermat-');

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

console.log('[7] the profile — nine numbers AND the axis, or nothing');
const PROFILE = {
  level_up: 7.4, level_down: 2.6, flow_dir_deg: 270,
  axis_x: 50, axis_z: -30, dir_x: -1, dir_z: 0, s_min: -30, s_max: 30,
  axis: [[80, -30, -30, 7.4], [20, -30, 30, 2.6]],
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
// THE AXIS IS ONE OF THE REQUIRED FIELDS SINCE W4a. The knots ARE the mirror;
// the nine numbers are its shadow on one plane. Rebuilding the axis from them
// would flatten every meander back onto the straight chord the polyline exists
// to replace — so no axis is no profile, exactly like a missing level.
check('a profile without an axis is no profile',
  readWaterProfile({ water_profile: { ...PROFILE, axis: undefined } }), null);
check('an empty axis is no profile either',
  readWaterProfile({ water_profile: { ...PROFILE, axis: [] } }), null);
check('a knot short of a number takes the whole profile with it',
  readWaterProfile({ water_profile: { ...PROFILE, axis: [[80, -30, -30]] } }),
  null);
check('an unreadable knot level is not 0 m',
  readWaterProfile({ water_profile: {
    ...PROFILE, axis: [[80, -30, -30, null], [20, -30, 30, 2.6]] } }), null);
check('an axis that is not a list is no axis',
  readWaterProfile({ water_profile: { ...PROFILE, axis: 3 } }), null);
check('one knot is a legitimate axis — that is what still water is',
  readWaterProfile({ water_profile: {
    ...PROFILE, axis: [[50, -30, 0, 7.4]] } })?.axis, [[50, -30, 0, 7.4]]);

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

// THE LEVEL FIELD IS TYPED, NOT SWEPT (user request 2026-08-23), and with the
// slider goes the ±10 m window that used to close around a level already set.
// That window was a SLIDER resolution, not a rule about water: as the clamp of
// a typed field it would have swallowed the very edit the field is for — a lake
// moved from 2 m to 40 m would have committed 12. The range is the world's:
//   any level, set or not -> [-HEIGHT_MAX_M, +HEIGHT_MAX_M] = [-50, 50]
const levelRange = () => [-HEIGHT_MAX_M, HEIGHT_MAX_M];
check('an unset level reaches every height a world has',
  levelRange(), [-50, 50]);
check('...and so does a level that is already set',
  levelRange(12), [-50, 50]);
// RED: the window that stood here would have clamped a retype to its own edge.
check('RED: the old ±10 m window would have refused 40 m on a 2 m lake',
  Math.min(Math.max(40, 2 - 10), 2 + 10), 12);
// …and the three metre fields say so themselves: no track, same clamps.
const toolsSrc = await readFile(TOOLS_SRC, 'utf8');
// Four fields, not three: the level, the depth, the shore ramp — and the flow
// speed of [16], which is typed for the same reason.
check('every metre/second field of the water panel carries no slider',
  (toolsSrc.match(/^\s+slider=\{false\}$/gm) || []).length, 4);
check('RED: and the window constant is gone with the track',
  /WATER_LEVEL_SPAN_M\s*=/.test(toolsSrc), false);

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

console.log('[13] W4a — a drawn river flows along its OWN line');
// THE TWO WORDS AND NOTHING ELSE (`terrain._sanitize_water`). A third word is
// not a third state: it is the same "still" an absent key is, so it loses the
// key here exactly as it does on the server.
check('forward survives', readWater({ flow_along: 'forward' }),
  { flow_along: 'forward' });
check('reverse survives', readWater({ flow_along: 'reverse' }),
  { flow_along: 'reverse' });
check('the word is trimmed and lower-cased, like the sanitizer does',
  readWater({ flow_along: ' Reverse ' }), { flow_along: 'reverse' });
check('a third word is not a third state', readWater({ flow_along: 'sideways' }),
  {});
check('an empty string is not a direction', readWater({ flow_along: '' }), {});
check('and neither is a number', readWater({ flow_along: 1 }), {});
check('a bearing and a line can both be stored — the reader keeps both, the '
  + 'BAKE lets the line win',
  readWater({ flow_along: 'forward', flow_dir_deg: 90 }),
  { flow_dir_deg: 90, flow_along: 'forward' });

// THE HAIRPIN OF `scripts/smoke_height_bake.py` [8k], number for number — the
// same three knots the server derives from a drawn line, so the admin twin and
// the bake answer one function. Arc lengths by hand:
//   A(150,300) -> B(249,280):  |(99, −20)| = √(9801 + 400) = √10201 = 101
//   B(249,280) -> C(201,260):  |(−48, −20)| = √(2304 + 400) = √2704 = 52
// so s = 0 / 101 / 153, and the cross-section medians are 10 / 8 / 6 m.
const HAIRPIN = {
  level_up: 10, level_down: 6, flow_dir_deg: null,
  axis_x: 150, axis_z: 300, dir_x: 0, dir_z: 0, s_min: 0, s_max: 153,
  axis: [[150, 300, 0, 10], [249, 280, 101, 8], [201, 260, 153, 6]],
};
near('the middle knot reads its OWN level, not the mean of the ends',
  waterLevelAt(HAIRPIN, 249, 280), 8);
// THE RED COUNTER-CHECK: the straight W1 chord A→C is |(51, −40)| = √4201 =
// 64.815 m long, and B projects onto it at (99·51 + (−20)(−40))/64.815 =
// 5849/64.815 = 90.24 m — PAST the downstream end. A single tilted plane
// therefore answers 6.0 in the middle of the bend: it cannot fall along a
// meander at all, which is the whole reason the axis became a polyline.
const CHORD_LEN = Math.hypot(51, 40);
const CHORD = { ...HAIRPIN,
  axis: [[150, 300, 0, 10], [201, 260, CHORD_LEN, 6]] };
near('the straight chord of W1 gets it wrong — 6.0, the downstream clamp',
  waterLevelAt(CHORD, 249, 280), 6);
// The leg midpoints: s = 50.5 -> 10 + (8 − 10)·(50.5/101) = 9.0
//                   s = 127  ->  8 + (6 −  8)·(26/52)    = 7.0
near('halfway down the first leg is halfway between 10 and 8',
  waterLevelAt(HAIRPIN, 199.5, 290), 9);
near('halfway down the second leg is halfway between 8 and 6',
  waterLevelAt(HAIRPIN, 225, 270), 7);
// The clamps. 50 m upstream of A the foot is A itself (the first segment's
// projection is negative and clamps to its start), so the level is the one the
// cross-section at A was measured for — never extrapolated past it.
near('upstream of the source the level clamps to the first knot',
  waterLevelAt(HAIRPIN, 100, 300), 10);
near('...and past the mouth to the last one',
  waterLevelAt(HAIRPIN, 201, 240), 6);
// Still water is ONE knot and the same function, not a branch beside it.
const LAKE = { ...HAIRPIN, axis: [[10, 20, 0, 4.5]] };
near('one knot answers its level everywhere', [
  waterLevelAt(LAKE, 10, 20), waterLevelAt(LAKE, -900, 900),
], [4.5, 4.5]);

console.log('[14] the tangent the arrows and the ripples share');
// The unit direction of the NEAREST segment: (99, −20)/101 on the first leg,
// (−48, −20)/52 on the second. A point beside a bend reads the leg it is
// beside, not the chord of the whole river.
near('the first leg', waterFlowAt(HAIRPIN, 199.5, 290),
  [99 / 101, -20 / 101]);
near('the second leg', waterFlowAt(HAIRPIN, 225, 270), [-48 / 52, -20 / 52]);
// Exactly ON the middle knot both legs are equally near, and the EARLIER one
// wins — `nearestOnPolyline` compares with `<`, never `<=`, and so does the
// server's own loop.
near('an exact tie on a knot goes to the segment already flowed',
  waterFlowAt(HAIRPIN, 249, 280), [99 / 101, -20 / 101]);
check('still water has no downstream at all', waterFlowAt(LAKE, 10, 20), [0, 0]);
check('and neither has nothing', waterFlowAt(null, 0, 0), [0, 0]);

console.log('[15] the axis the map draws its arrows along');
const LINE = [[150, 300], [249, 280], [201, 260]];
check('forward is the order the points were drawn',
  flowAxisPoints(LINE, 'forward'), LINE);
check('reverse is the same line read from the far end',
  flowAxisPoints(LINE, 'reverse'), [[201, 260], [249, 280], [150, 300]]);
check('no word, no flow', flowAxisPoints(LINE, undefined), null);
check('a third word is no flow either', flowAxisPoints(LINE, 'sideways'), null);
check('one point is not a direction',
  flowAxisPoints([[150, 300]], 'forward'), null);
check('and neither is no line at all', flowAxisPoints(null, 'forward'), null);
// ONE ARROW PER SEGMENT, by hand. First leg: 101 m long, half of it is 50.5 m
// (inside the 4…60 m clamp), centred on the midpoint (199.5, 290); the half
// length 25.25 m along (99, −20)/101 is exactly (24.75, −5), because
// 25.25 = 101/4:
//   from = (199.5 − 24.75, 290 + 5) = (174.75, 295)
//   to   = (199.5 + 24.75, 290 − 5) = (224.25, 285)
// Second leg: 52 m long, half of it is 26 m, half-length 13 m along
// (−48, −20)/52 = (−12/13, −5/13) is exactly (−12, −5):
//   from = (225 + 12, 270 + 5) = (237, 275)   to = (213, 265)
const along = flowArrowsAlong(flowAxisPoints(LINE, 'forward'));
check('a three-knot line gets two arrows, one per segment', along.length, 2);
near('the first follows the first leg',
  [...along[0].from, ...along[0].to], [174.75, 295, 224.25, 285]);
near('the second follows the second leg, around the bend',
  [...along[1].from, ...along[1].to], [237, 275, 213, 265]);
// Against the line: the same two segments, every arrow turned end for end.
const against = flowArrowsAlong(flowAxisPoints(LINE, 'reverse'));
near('reversing the line reverses every arrow on it',
  [...against[0].from, ...against[0].to, ...against[1].from, ...against[1].to],
  [213, 265, 237, 275, 224.25, 285, 174.75, 295]);
// The barbs of the second leg: len/4 = 6.5 m back from the tip, len·0.15 =
// 3.9 m out along the perpendicular (−dz, dx) = (5/13, −12/13):
//   tip (213, 265) − (−12/13, −5/13)·6.5 = (219, 267.5)
//   ± (5/13, −12/13)·3.9 = ±(1.5, −3.6)  ->  (220.5, 263.9) and (217.5, 271.1)
near('its head sits back from the tip, one barb each side',
  [...along[1].barbs[0], ...along[1].barbs[1]],
  [220.5, 263.9, 217.5, 271.1]);
// A segment shorter than the 4 m minimum keeps its arrow INSIDE itself: the
// clamp raises 1.5 m to 4 m, and the segment length caps it back to 3 m. An
// arrow sticking out over the neighbouring knot would point at water that
// flows the other way.
const kink = flowArrowsAlong([[0, 0], [3, 0]]);
near('a short kink gets an arrow that still fits between its two knots',
  Math.hypot(kink[0].to[0] - kink[0].from[0],
    kink[0].to[1] - kink[0].from[1]), 3);
// The same two clamps the polygon arrow has, per segment.
const longLeg = flowArrowsAlong([[0, 0], [400, 0]]);
near('a long reach is capped at 60 m',
  Math.hypot(longLeg[0].to[0] - longLeg[0].from[0],
    longLeg[0].to[1] - longLeg[0].from[1]), 60);
check('a collapsed segment has no direction and gets no arrow',
  flowArrowsAlong([[5, 5], [5, 5]]).length, 0);
check('a line of one point has no segment to draw on',
  flowArrowsAlong([[5, 5]]).length, 0);

console.log('[16] the AREA’s own flow speed — read, clamped, and the factor '
  + 'it becomes');
// `meta.flow_speed_m_s` (finding 2026-08-23 no. 2) is an OVERRIDE of the
// SURFACE KIND's `flow_speed` dial, so it takes that dial's range and is
// CLAMPED like the two widths — a speed is not an angle, and 5 m/s means "as
// fast as this goes", not 5 − 2 the way a bearing wraps.
check('the speed field takes the kind dial’s own range',
  [FLOW_SPEED_MIN_M_S, FLOW_SPEED_MAX_M_S], [0, 2]);
check('...and the panel quotes the kind default the renderer uses',
  FLOW_SPEED_DEFAULT_M_S, WATER_FLOW_SPEED_DEFAULT_M_S);
check('the raised default is 0.15 m/s, not the 0.08 that read as standing',
  WATER_FLOW_SPEED_DEFAULT_M_S, 0.15);
check('a plain speed is read', readWater({ flow_speed_m_s: 0.4 }),
  { flow_speed_m_s: 0.4 });
check('0 m/s is an authored standstill, not "unset"',
  readWater({ flow_speed_m_s: 0 }), { flow_speed_m_s: 0 });
check('a numeric string is a number (JSON round trips)',
  readWater({ flow_speed_m_s: '1.25' }), { flow_speed_m_s: 1.25 });
check('too fast clamps to the dial’s top',
  readWater({ flow_speed_m_s: 9 }), { flow_speed_m_s: 2 });
check('a negative speed clamps to a standstill',
  readWater({ flow_speed_m_s: -4 }), { flow_speed_m_s: 0 });
for (const junk of [null, '', '   ', NaN, Infinity, [], {}, 'fast']) {
  check(`junk is no override (${JSON.stringify(junk)})`,
    readWater({ flow_speed_m_s: junk }), {});
}

// THE FACTOR, hand-derived. The shader multiplies the KIND's `uFlowSpeed` by
// the LENGTH of the flow attribute, so the length an area sends is
// `area m/s ÷ kind m/s` — and the product is the area's own metres per second
// again, whatever the kind is dialled to:
//   0.30 over the default 0.15 -> 2      -> 0.15 · 2    = 0.30 m/s
//   0.03 over the default 0.15 -> 0.2    -> 0.15 · 0.2  = 0.03 m/s
//   0.60 over a kind at 0.40   -> 1.5    -> 0.40 · 1.5  = 0.60 m/s
check('twice the kind’s speed is a factor of 2',
  waterFlowFactor(0.3, WATER_FLOW_SPEED_DEFAULT_M_S), 2);
check('...a fifth of it a factor of 0.2',
  Math.round(waterFlowFactor(0.03, WATER_FLOW_SPEED_DEFAULT_M_S) * 1e12) / 1e12,
  0.2);
near('...and the kind it is measured against is the kind, not the default',
  waterFlowFactor(0.6, 0.4), 1.5, 1e-12);
for (const [area, kind] of [[0.3, 0.15], [0.03, 0.15], [0.6, 0.4], [2, 0.15]]) {
  near(`kind ${kind} m/s × factor = the authored ${area} m/s`,
    kind * waterFlowFactor(area, kind), area, 1e-12);
}
// ABSENT IS EXACTLY 1 — the unit tangent of W4a, i.e. every water built before
// this field existed keeps the attribute it always had, bit for bit.
check('no override is a factor of exactly 1',
  waterFlowFactor(undefined, WATER_FLOW_SPEED_DEFAULT_M_S), 1);
for (const junk of [null, '', '   ', NaN, Infinity, [], {}, 'fast', true]) {
  check(`...and so is junk (${JSON.stringify(junk)})`,
    waterFlowFactor(junk, WATER_FLOW_SPEED_DEFAULT_M_S), 1);
}
// A KIND THAT DOES NOT FLOW CANNOT BE MADE TO: `uFlowSpeed` is 0 there (ice),
// and 0 × anything is 0 — so the ratio would be a division by zero pretending
// to mean something. 1 is returned instead.
check('a kind standing at 0 m/s answers 1, not infinity',
  waterFlowFactor(0.5, 0), 1);
check('...and a missing kind speed falls back to the default',
  waterFlowFactor(0.3, undefined), 2);
// THE FLOOR. The shader reads a flow shorter than 1e-4 as STILL — a lake, which
// drifts at `uSpeed` (0.25 m/s), i.e. FASTER. An authored 0 must therefore not
// arrive as a zero-length vector: it is floored to 1e-3, ten times that
// threshold, which on the default kind is 0.15 mm/s — one 1.6 m wavelength in
// about three hours, a river standing still while staying a river.
check('a river dialled to 0 is floored above the still threshold',
  waterFlowFactor(0, WATER_FLOW_SPEED_DEFAULT_M_S), WATER_FLOW_FACTOR_MIN);
check('...and that floor is ten times the shader’s 1e-4', WATER_FLOW_FACTOR_MIN,
  1e-3);
check('RED: an unfloored 0 would have been read as a lake at 0.25 m/s',
  0 < 1e-4, true);
near('the floored current is 0.15 mm/s',
  WATER_FLOW_SPEED_DEFAULT_M_S * WATER_FLOW_FACTOR_MIN, 0.00015, 1e-9);
check('the render ceiling is the panel’s ceiling',
  WATER_FLOW_SPEED_MAX_M_S, FLOW_SPEED_MAX_M_S);
check('...so a hand-written 99 m/s cannot outrun the dial',
  waterFlowFactor(99, WATER_FLOW_SPEED_DEFAULT_M_S),
  waterFlowFactor(WATER_FLOW_SPEED_MAX_M_S, WATER_FLOW_SPEED_DEFAULT_M_S));

// …and the panel offers the field, on flowing water only: a lake reads the
// still-water dial, where this number would change nothing.
check('the panel has a flow-speed field',
  /label=\{t\('Flow speed \(m\/s\)'\)\}/.test(toolsSrc), true);
check('...shown only where the water flows',
  /\{flowing \? \(/.test(toolsSrc), true);
check('...and "flowing" is the bake’s own rule: a line says so, a polygon '
  + 'carries a bearing',
  /const flowing = hasLine \? !!water\.flow_along : flow !== undefined/
    .test(toolsSrc), true);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
