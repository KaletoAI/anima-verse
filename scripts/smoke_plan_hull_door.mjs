/**
 * Smoke run for the HULL DOOR of the floor-plan editor — the pure arithmetic
 * behind the "Door on the outline" tool (§ 6 of the storey-corridor spec):
 * a click becomes a contour edge plus a fraction along it, and a spot another
 * door already holds is refused.
 *
 * Usage:  node scripts/smoke_plan_hull_door.mjs
 *         (bundles the module with esbuild — a Vite dependency, already
 *          installed; no bundler config, no jsdom, no server)
 *
 * There is no frontend test runner in this repo, so the check is what a check
 * here can be: the PURE math, every number derived BY HAND below and never
 * recorded from the current output. The React wiring (the toolbar mode, the
 * glyph on the contour, the strip) is deliberately not covered — that is a
 * rendering question and this file could only record it.
 *
 * ---------------------------------------------------------------------------
 * THE FIXTURE — the square [[-5,-5],[5,-5],[5,5],[-5,5]]
 * ---------------------------------------------------------------------------
 * Stored open and clockwise in map view (x east, z south, § A1.1), so its four
 * directed edges are
 *
 *     edge 0: (-5,-5) → ( 5,-5)     the z = -5 side, running east
 *     edge 1: ( 5,-5) → ( 5, 5)     the x = +5 side, running south
 *     edge 2: ( 5, 5) → (-5, 5)     the z = +5 side, running west
 *     edge 3: (-5, 5) → (-5,-5)     the x = -5 side, running north
 *
 * each 10 m long, so ONE unit of `at` is 10 m and 0.1 of it is one metre.
 *
 * ---------------------------------------------------------------------------
 * [1] `nearestOutlineEdge(outline, p)` — the click
 * ---------------------------------------------------------------------------
 * The foot of the perpendicular onto every edge, clamped to the segment; the
 * nearest one wins, `at` is its fraction and `dist` the metres to the point.
 *
 *   (0, -4.8)  the foot on edge 0 is (0, -5):  at = (0 − (−5))/10 = 0.5
 *              and dist = |−4.8 − (−5)| = 0.2               (inside the square)
 *              → { edge: 0, at: 0.5, dist: 0.2 }
 *   (4.9, 2)   the foot on edge 1 is (5, 2):   at = (2 − (−5))/10 = 0.7
 *              and dist = |4.9 − 5| = 0.1
 *              → { edge: 1, at: 0.7, dist: 0.1 }
 *   (-5.3, 0)  the foot on edge 3 is (-5, 0):  edge 3 runs (−5,5) → (−5,−5),
 *              so at = (0 − 5)/(−10) = 0.5, and dist = |−5.3 − (−5)| = 0.3
 *              → { edge: 3, at: 0.5, dist: 0.3 }            (outside the square)
 *
 * The three are the brief's hand values, and they are also the comment block
 * above the function itself. Two more, to pin the edges the three leave open:
 *
 *   (0, 4.7)   foot (0, 5) on edge 2, which runs east → west, so
 *              at = (0 − 5)/(−10) = 0.5, dist = 0.3
 *   (9, -9)    beyond the corner (5,−5): the foot CLAMPS to that corner on
 *              both edge 0 (at 1) and edge 1 (at 0), and both are
 *              √(4² + 4²) = 5.6569 away. The loop keeps the FIRST of two
 *              equal distances (`<`, not `<=`), so edge 0 at 1 wins.
 *   an EMPTY outline has no edge to be near at all: the loop never runs and
 *              the seed answer stands → { edge: 0, at: 0.5, dist: Infinity }
 *   a ONE-POINT outline still has an edge — the auto-closing ring makes it the
 *              degenerate 0 → 0 segment. A zero-length edge has no fraction, so
 *              `at` is the 0.5 fallback and the foot IS the point:
 *              (3,4) against [[0,0]] → { edge: 0, at: 0.5, dist: 5 }
 *              (hand-corrected: the first draft of this file expected Infinity
 *              here, which reads the ring as if it had no edge at all)
 *
 * ---------------------------------------------------------------------------
 * [2] `hullDoorConflict(outline, edge, at, doors)` — the refusal
 * ---------------------------------------------------------------------------
 * Every door that already leads outside on this storey is projected onto the
 * contour with the same routine; one landing on the SAME edge closer than
 * `HULL_DOOR_MIN_GAP_M` = 1.0 m along it blocks the new door, and its index is
 * the answer (−1 = the spot is free). The gap is measured between the two
 * CENTRES, in metres: |Δat| · edge length.
 *
 *   a room's front door at (−2, −5)  → edge 0, at 0.3
 *     new door at edge 0, at 0.5     |0.5 − 0.3| · 10 = 2.0 m   → free  (−1)
 *     new door at edge 0, at 0.25    |0.25 − 0.3| · 10 = 0.5 m  → blocked (0)
 *     new door at edge 0, at 0.4     exactly 1.0 m, and the rule is a STRICT
 *                                    "closer than"                → free  (−1)
 *     new door at edge 0, at 0.39    0.9 m                        → blocked (0)
 *     new door at edge 2, at 0.3     another edge entirely        → free  (−1)
 *   two doors, (−2,−5) and (4.9, 2)  → edge 0 at 0.3, edge 1 at 0.7
 *     new door at edge 1, at 0.72    |0.72 − 0.7| · 10 = 0.2 m  → blocked (1)
 *                                    the INDEX in `doors`, not in the outline
 *   no doors at all                                              → free  (−1)
 *   a degenerate outline (2 points)  nothing to project onto     → free  (−1)
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));

async function loadModule() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'hulldoor-smoke-'));
  try {
    const file = join(dir, 'entry.mjs');
    await esbuild.build({
      stdin: {
        contents: "export { nearestOutlineEdge, nearestPolygonEdge,"
          + " hullDoorConflict, HULL_DOOR_MIN_GAP_M, HULL_OPENING_MAX } from"
          + " './frontend/src/tabs/world/planGeometry'",
        resolveDir: ROOT,
        loader: 'ts',
      },
      outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
function compare(a, b, eps) {
  if (typeof b === 'number') {
    return typeof a === 'number'
      && (a === b || Math.abs(a - b) <= eps);
  }
  if (Array.isArray(b)) {
    return Array.isArray(a) && a.length === b.length
      && b.every((v, i) => compare(a[i], v, eps));
  }
  if (b && typeof b === 'object') {
    const keys = Object.keys(b);
    if (!a || typeof a !== 'object') return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

const {
  nearestOutlineEdge, nearestPolygonEdge, hullDoorConflict,
  HULL_DOOR_MIN_GAP_M, HULL_OPENING_MAX,
} = await loadModule();

/** The square of the derivation above. */
const SQ = [[-5, -5], [5, -5], [5, 5], [-5, 5]];

console.log('[1] nearestOutlineEdge — the click becomes (edge, at, dist)');
check('(0, -4.8) -> edge 0 at 0.5, 0.2 m away',
  nearestOutlineEdge(SQ, [0, -4.8]), { edge: 0, at: 0.5, dist: 0.2 });
check('(4.9, 2) -> edge 1 at 0.7, 0.1 m away',
  nearestOutlineEdge(SQ, [4.9, 2]), { edge: 1, at: 0.7, dist: 0.1 });
check('(-5.3, 0) -> edge 3 at 0.5, 0.3 m away',
  nearestOutlineEdge(SQ, [-5.3, 0]), { edge: 3, at: 0.5, dist: 0.3 });
check('(0, 4.7) -> edge 2 at 0.5 (it runs east->west), 0.3 m away',
  nearestOutlineEdge(SQ, [0, 4.7]), { edge: 2, at: 0.5, dist: 0.3 });
check('(9, -9) -> the corner, first of two equal distances: edge 0 at 1',
  nearestOutlineEdge(SQ, [9, -9]), { edge: 0, at: 1, dist: 5.6569 }, 1e-4);
check('an EMPTY outline is Infinity away',
  nearestOutlineEdge([], [3, 4]), { edge: 0, at: 0.5, dist: Infinity });
check('a one-point outline is the degenerate self-edge, 5 m away',
  nearestOutlineEdge([[0, 0]], [3, 4]), { edge: 0, at: 0.5, dist: 5 });
check('nearestPolygonEdge is the same answer without the distance',
  nearestPolygonEdge(SQ, [4.9, 2]), { edge: 1, at: 0.7 });

console.log('[2] hullDoorConflict — a door already stands there');
check('the gap is one metre', HULL_DOOR_MIN_GAP_M, 1.0);
check('the cap is eight doors', HULL_OPENING_MAX, 8);
const ONE = [[-2, -5]];
check('2.0 m along the edge is free',
  hullDoorConflict(SQ, 0, 0.5, ONE), -1);
check('0.5 m along the edge is blocked by door 0',
  hullDoorConflict(SQ, 0, 0.25, ONE), 0);
check('exactly 1.0 m is free (the rule is "closer than")',
  hullDoorConflict(SQ, 0, 0.4, ONE), -1);
check('0.9 m is blocked',
  hullDoorConflict(SQ, 0, 0.39, ONE), 0);
check('the same fraction on ANOTHER edge is free',
  hullDoorConflict(SQ, 2, 0.3, ONE), -1);
const TWO = [[-2, -5], [4.9, 2]];
check('the answer is the index in `doors`, not in the outline',
  hullDoorConflict(SQ, 1, 0.72, TWO), 1);
check('no doors at all is free', hullDoorConflict(SQ, 0, 0.3, []), -1);
check('a degenerate outline refuses nothing',
  hullDoorConflict([[0, 0], [1, 0]], 0, 0.5, ONE), -1);

console.log(`\n${passed} checks passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
