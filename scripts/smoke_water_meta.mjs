/**
 * smoke_water_meta.mjs — the reader of a water area's three numbers.
 *
 * Usage: node scripts/smoke_water_meta.mjs
 *
 * WHAT IS PINNED HERE, and why it is worth a check of its own (plan
 * "Ein Boden" § 2 G4): a water area carries `water_level`, `water_depth_m` and
 * `shore_ramp_m` in the terrain area's FREE-FORM `meta`. Free-form means the
 * editor gets whatever the server, a world-dev apply or an older world wrote
 * there, and `mapTypes.readWater` is the one place that turns it into numbers.
 *
 * The trap is JavaScript's own coercion, and it is not hypothetical:
 *
 *     Number(null) === 0        Number('') === 0        Number([]) === 0
 *
 * so a naive `Number(meta.water_depth_m)` reads a MISSING key as "0 m deep" —
 * a lake with no bed at all — and a missing level as "sea level", which under
 * the bake means a mountain lake dropping to y = 0 the first time somebody
 * opens its chip. "The server decides" (absent key, the rim median for the
 * level) and "0" are different answers, and only one of them may be inferred
 * from junk. Every expectation below is derived from that rule by hand, not
 * recorded from the current output.
 *
 * The ranges the editor offers are checked against the same contract:
 * depth 0.2…20 m, shore ramp 0…20 m, and the level slider sweeping the full
 * world height range while nothing is set and ±10 m once something is.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const TYPES_SRC = join(ROOT, 'frontend/src/tabs/map/mapTypes.ts');
const TOOLS_SRC = join(ROOT, 'frontend/src/tabs/map/TerrainTools.tsx');

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

/**
 * The exported CONSTANTS of a component file, read out of its source.
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

const { readWater } = await loadModule(TYPES_SRC, 'ts', 'watermeta-');
const {
  WATER_KIND, WATER_DEPTH_DEFAULT_M, SHORE_RAMP_DEFAULT_M,
  WATER_DEPTH_MIN_M, WATER_DEPTH_MAX_M, SHORE_RAMP_MAX_M,
  WATER_LEVEL_SPAN_M, HEIGHT_MAX_M,
} = await readConsts(TOOLS_SRC, [
  'WATER_KIND', 'WATER_DEPTH_DEFAULT_M', 'SHORE_RAMP_DEFAULT_M',
  'WATER_DEPTH_MIN_M', 'WATER_DEPTH_MAX_M', 'SHORE_RAMP_MAX_M',
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

console.log('[3] real numbers survive, including the honest zeroes');
check('a level of 0 IS sea level, not "unset"',
  readWater({ water_level: 0 }), { water_level: 0 });
check('a shore ramp of 0 IS a wall at the shore',
  readWater({ shore_ramp_m: 0 }), { shore_ramp_m: 0 });
check('a negative level is a lake below sea level',
  readWater({ water_level: -3.5 }), { water_level: -3.5 });
check('a numeric string is a number (JSON round trips)',
  readWater({ water_depth_m: '2.5' }), { water_depth_m: 2.5 });
check('all three at once, foreign keys dropped',
  readWater({
    water_level: 12.25, water_depth_m: 4, shore_ramp_m: 6,
    scatter: [{ density_per_100m2: 1 }],
  }),
  { water_level: 12.25, water_depth_m: 4, shore_ramp_m: 6 });

console.log('[4] the knob ranges the chip offers');
check('the bake stamps a mirror under exactly one kind', WATER_KIND, 'water');
check('depth sweeps 0.2…20 m',
  [WATER_DEPTH_MIN_M, WATER_DEPTH_MAX_M], [0.2, 20]);
check('the default depth is inside that range',
  WATER_DEPTH_DEFAULT_M >= WATER_DEPTH_MIN_M
  && WATER_DEPTH_DEFAULT_M <= WATER_DEPTH_MAX_M, true);
check('the shore ramp starts at a wall and ends at 20 m',
  [0, SHORE_RAMP_MAX_M], [0, 20]);
check('the default shore ramp is inside that range',
  SHORE_RAMP_DEFAULT_M >= 0 && SHORE_RAMP_DEFAULT_M <= SHORE_RAMP_MAX_M, true);

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

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
