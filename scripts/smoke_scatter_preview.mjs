#!/usr/bin/env node
/**
 * Smoke run for the map editor's SCATTER PREVIEW BUDGET —
 * `scatterPreviewShares` in `frontend/src/tabs/map/mapMath.ts`, over the count
 * rule of the shared sampler (`scatterWantedCount`,
 * `packages/scene-render/src/scatter.ts`).
 *
 * Usage:  node scripts/smoke_scatter_preview.mjs
 *
 * Same discipline as `scripts/smoke_stroke_styles.mjs`: every expected number
 * is derived BY HAND below and never recorded from the current output.
 *
 * ============================================================================
 * WHAT WENT WRONG (reported 2026-08-19)
 * ============================================================================
 * "The scatter preview shows up in only ONE of my two Deep-Forest areas."
 *
 * Nothing in the path is keyed by the terrain KIND — the seed of an entry is
 * `terrain:scatter:<AREA ID>:<index>`, so two areas of one kind draw two
 * different streams (section D pins that). What went wrong is the BUDGET: the
 * preview drew area after area until it had 4 000 SVG dots and then stopped,
 * so the areas at the end of the list were drawn with no scatter at all.
 *
 * THE REPORTING WORLD, measured off `GET /world/terrain-areas` (areas
 * bottom-to-top, `polygonArea` of the cleaned ring, `SCATTER_MAX_PER_ENTRY`
 * = 2 000 per entry):
 *
 *   area          kind          m2            entries   plants
 *   ta_57f3df57   deep_forest   13 713 589    7         7 · 2 000 = 14 000
 *   ta_b3ef0bbd   deep_forest      841 443    6         6 · 2 000 = 12 000
 *   ta_63926f52   forest            89 126    2         2 · 2 000 =  4 000
 *   ta_2a0854a6   grass                633    1         round(6.33 · 50) = 317
 *
 * (the four rock areas and the second unplanted deep forest carry no
 * `meta.scatter` at all, so they never enter the budget)
 *
 * OLD RULE, first come first served: entry 0 of ta_57f3df57 takes 2 000 dots,
 * entry 1 takes the other 2 000 — the budget is gone inside the FIRST wood,
 * and ta_b3ef0bbd, the forest and the grass get 0 dots between them. That is
 * the report, to the dot.
 *
 * ============================================================================
 * (A) THE SHARE FORMULA
 * ============================================================================
 * Σ wanted = 14 000 + 12 000 + 4 000 + 317 = 30 317, above the 4 000 budget,
 * so every entry keeps its share:
 *
 *     share_i = max(1, floor(wanted_i · 4 000 / 30 317))
 *
 *   a 2 000-entry: floor(2 000 · 4 000 / 30 317) = floor(263.878…) = 263
 *   the 317-entry: floor(  317 · 4 000 / 30 317) = floor( 41.824…) =  41
 *
 * (A1) so the drawn total is 15 · 263 + 41 = 3 945 + 41 = 3 986 ≤ 4 000, and
 *      EVERY one of the four areas is drawn: 7·263 = 1 841 dots in the big
 *      deep forest, 6·263 = 1 578 in the small one, 2·263 = 526 in the
 *      forest, 41 in the grass.
 * (A2) the ratio the preview exists to show survives: the two deep forests
 *      plant 14 000 : 12 000 and are drawn 1 841 : 1 578, both 1.1666… — a
 *      wood with more props still gets more dots.
 * (A3) RED COUNTER-PROBE of the old rule, spelled out as a running budget:
 *      first-come-first-served gives [2000, 2000, 0, 0, …] — the second deep
 *      forest at 0. The share rule must NOT agree with it.
 *
 * ============================================================================
 * (B) THE BUDGET FITS — nothing is thinned that does not have to be
 * ============================================================================
 * (B1) Σ wanted ≤ budget hands every count back UNCHANGED: [300, 27] with
 *      budget 4 000 stays [300, 27]. A small world's preview is the world.
 * (B2) exactly at the budget is still "fits": [2 000, 2 000] at 4 000 stays.
 * (B3) one over is not: [2 001, 2 000] at 4 000 gives
 *      floor(2 001 · 4 000 / 4 001) = floor(2 000.499…) = 2 000 and
 *      floor(2 000 · 4 000 / 4 001) = floor(1 999.500…) = 1 999.
 *
 * ============================================================================
 * (C) NOBODY IS LEFT BLANK — the max(1, …)
 * ============================================================================
 * (C1) A tiny patch beside a huge wood: wanted [4 000 000, 3], budget 4 000.
 *      Σ = 4 000 003. The patch's share is
 *      floor(3 · 4 000 / 4 000 003) = floor(0.00299…) = 0 → raised to 1.
 *      The wood gets floor(4 000 000 · 4 000/4 000 003) = floor(3 999.997) =
 *      3 999. Total 4 000 — and the patch is VISIBLE, which is the whole
 *      point: "does this area scatter at all" has to be answerable by looking.
 * (C2) An entry that plants nothing keeps 0 — the floor of one is for entries
 *      that DO grow something, not a dot for empty ground: [0, 3] at budget 1
 *      gives [0, 1].
 * (C3) The overshoot is bounded by one dot per starved entry: 10 entries of 1
 *      against one of 10 000, budget 100 → the big one gets
 *      floor(10 000 · 100 / 10 010) = floor(99.900…) = 99, each small one
 *      floor(1 · 100 / 10 010) = 0 → 1. Total 99 + 10 = 109, i.e. 9 over a
 *      100-dot budget. Nine SVG nodes against a limit that exists to stop
 *      tens of thousands.
 *
 * ============================================================================
 * (D) THE COUNT RULE ITSELF — `scatterWantedCount`
 * ============================================================================
 * wanted = min(round(areaM2/100 · density), 2 000).
 * (D1) 10 000 m2 at 3 per 100 m2 → round(100 · 3) = 300.
 * (D2)    900 m2 at 3 per 100 m2 → round(9 · 3)   =  27.
 * (D3) The reporting world's big wood, 13 713 589 m2 at 20 per 100 m2 →
 *      round(137 135.89 · 20) = 2 742 718, CAPPED to 2 000.
 * (D4) …and its small wood, 841 443 m2 at the same 20 → round(8 414.43 · 20)
 *      = 168 289, capped to 2 000 as well. TWO EQUAL COUNTS ON AREAS THAT
 *      DIFFER BY A FACTOR OF 16.3 — this is the second defect of the report
 *      (the 3D client shows the small wood far denser), and the case is here
 *      so the number is on the record: effective density 2 000/(A/100) is
 *      0.0146 vs 0.2377 per 100 m2, a factor 16.3, from settings that are
 *      identical. The count rule is right, the CEILING is what is not
 *      scale-free; fixing that is not this file's subject.
 * (D5) Below one prop is none: 10 m2 at 3 per 100 m2 → round(0.3) = 0.
 * (D6) Junk (NaN density, negative area, zero density) is 0, never NaN.
 * (D7) An explicit `maxPoints` overrides the standing ceiling: 10 000 m2 at
 *      3 with maxPoints 100 → 100.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');
const SCATTER_SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');

/** Bundled and imported — `mapMath` pulls in the workspace package
 *  `@anima/scene-render`, which esbuild resolves and inlines. */
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
/** A red counter-probe: the two answers must NOT agree. */
function differs(label, a, b) {
  const ok = JSON.stringify(a) !== JSON.stringify(b);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       both are ${JSON.stringify(a)}`
      + ' — the check proves nothing');
  }
}

/** The rule that WAS there: sample in list order until the budget is gone. */
function firstComeFirstServed(wanted, budget) {
  let left = budget;
  return wanted.map((n) => {
    const take = Math.max(0, Math.min(n, left));
    left -= take;
    return take;
  });
}

async function main() {
  const { scatterPreviewShares } = await loadBundled(SRC, 'scatterpreview-');
  const { scatterWantedCount, SCATTER_MAX_PER_ENTRY } =
    await loadBundled(SCATTER_SRC, 'scattercount-');

  console.log('(A) the reporting world — 15 entries of 2 000 plus one of 317');
  // 7 entries on the big deep forest, 6 on the small one, 2 on the forest,
  // 1 on the grass patch — in the server's bottom-to-top order.
  const world = [
    ...Array(7).fill(2000), ...Array(6).fill(2000), ...Array(2).fill(2000), 317,
  ];
  const shares = scatterPreviewShares(world, 4000);
  check('A the 2 000-entries keep 263 dots each, the 317-entry 41',
    shares, [...Array(15).fill(263), 41]);
  check('A1 the drawn total is 3 986, inside the 4 000-dot budget',
    shares.reduce((s, n) => s + n, 0), 3986);
  check('A1 the SECOND deep forest is drawn — 6 · 263 = 1 578 dots',
    shares.slice(7, 13).reduce((s, n) => s + n, 0), 1578);
  check('A1 …the first one 7 · 263 = 1 841, the forest 526, the grass 41',
    [shares.slice(0, 7).reduce((s, n) => s + n, 0),
      shares.slice(13, 15).reduce((s, n) => s + n, 0), shares[15]],
    [1841, 526, 41]);
  check('A2 the 14 000 : 12 000 the world plants stays 1 841 : 1 578',
    1841 / 1578, 14000 / 12000);
  const old = firstComeFirstServed(world, 4000);
  check('A3 the OLD rule really did leave the second wood at 0',
    [old.slice(0, 7).reduce((s, n) => s + n, 0),
      old.slice(7, 13).reduce((s, n) => s + n, 0),
      old.slice(13).reduce((s, n) => s + n, 0)],
    [4000, 0, 0]);
  differs('A3 …and the share rule does not agree with it', shares, old);

  console.log('\n(B) a budget that fits changes nothing');
  check('B1 [300, 27] under a 4 000 budget is drawn whole',
    scatterPreviewShares([300, 27], 4000), [300, 27]);
  check('B2 exactly at the budget still fits',
    scatterPreviewShares([2000, 2000], 4000), [2000, 2000]);
  check('B3 one over is thinned to 2 000 / 1 999',
    scatterPreviewShares([2001, 2000], 4000), [2000, 1999]);

  console.log('\n(C) nobody who grows something is left blank');
  check('C1 a 3-prop patch beside a 4 000 000-prop wood still gets its dot',
    scatterPreviewShares([4000000, 3], 4000), [3999, 1]);
  check('C2 an entry that plants nothing keeps 0',
    scatterPreviewShares([0, 3], 1), [0, 1]);
  const many = scatterPreviewShares([10000, ...Array(10).fill(1)], 100);
  check('C3 ten starved entries cost ten dots over the budget',
    [many[0], many.slice(1).reduce((s, n) => s + n, 0),
      many.reduce((s, n) => s + n, 0)],
    [99, 10, 109]);

  console.log('\n(D) the count rule the budget is built on');
  check('D0 the per-entry ceiling is 2 000', SCATTER_MAX_PER_ENTRY, 2000);
  check('D1 10 000 m2 at 3 per 100 m2 plants 300',
    scatterWantedCount(10000, 3), 300);
  check('D2 900 m2 at the same 3 plants 27',
    scatterWantedCount(900, 3), 27);
  check('D3 13 713 589 m2 at 20 wants 2 742 718 and is capped to 2 000',
    [Math.round((13713589 / 100) * 20), scatterWantedCount(13713589, 20)],
    [2742718, 2000]);
  check('D4 841 443 m2 at 20 wants 168 289 and is capped to the SAME 2 000',
    [Math.round((841443 / 100) * 20), scatterWantedCount(841443, 20)],
    [168289, 2000]);
  check('D4 …so 16.3 times the ground gets 16.3 times thinner, in numbers',
    [(2000 / (13713589 / 100)).toFixed(4), (2000 / (841443 / 100)).toFixed(4)],
    ['0.0146', '0.2377']);
  check('D5 below one prop is none', scatterWantedCount(10, 3), 0);
  check('D6 junk is 0, never NaN',
    [scatterWantedCount(10000, NaN), scatterWantedCount(-5, 3),
      scatterWantedCount(10000, 0), scatterWantedCount(NaN, 3)],
    [0, 0, 0, 0]);
  check('D7 an explicit ceiling overrides the standing one',
    scatterWantedCount(10000, 3, 100), 100);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
