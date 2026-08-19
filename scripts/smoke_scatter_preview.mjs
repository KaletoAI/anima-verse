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
 * Nothing in the path is keyed by the terrain KIND — an entry's seed carries
 * the AREA ID, so two areas of one kind draw two different streams
 * (`client3d/scripts/smoke_scatter_math.mjs`, sections C13 and K4 pin that).
 * What went wrong is the BUDGET: the preview drew area after area until it had
 * 4 000 SVG dots and then stopped, so the areas at the end of the list were
 * drawn with no scatter at all.
 *
 * THE REPORTING WORLD, measured off `GET /world/terrain-areas` (areas
 * bottom-to-top, `polygonArea` of the cleaned ring). `wanted` is what the
 * ground really carries, A · d / 100 with NO ceiling — see (D):
 *
 *   area          kind          m2            rows (d per 100 m2)   wanted
 *   ta_57f3df57   deep_forest   13 713 589    1, .1, 10, 10, 1, 1, 20  5 910 558
 *   ta_b3ef0bbd   deep_forest      841 443    1, 10, 1, 10, 20, 1        361 819
 *   ta_63926f52   forest            89 126    5, 6                         9 804
 *   ta_2a0854a6   grass                633    50                             317
 *
 * (the four rock areas and the second unplanted deep forest carry no
 * `meta.scatter` at all, so they never enter the budget)
 *
 * OLD RULE, first come first served over the OLD per-entry ceiling of 2 000:
 * entry 0 of ta_57f3df57 takes 2 000 dots, entry 1 takes the other 2 000 — the
 * budget is gone inside the FIRST wood, and ta_b3ef0bbd, the forest and the
 * grass get 0 dots between them. That is the report, to the dot.
 *
 * ============================================================================
 * (A) THE SHARE FORMULA
 * ============================================================================
 * Σ wanted = 5 910 558 + 361 819 + 9 804 + 317 = 6 282 498, far above the
 * 4 000-dot budget, so every entry keeps its share:
 *
 *     share_i = max(1, floor(wanted_i · 4 000 / 6 282 498))
 *
 *   d = 20  on the big wood: 2 742 718 · 4 000 / 6 282 498 = 1 746.27 -> 1 746
 *   d = 10  on the big wood: 1 371 359 · … =   873.13 ->   873   (twice)
 *   d = 1   on the big wood:   137 136 · … =    87.31 ->    87   (three times)
 *   d = 0.1 on the big wood:    13 714 · … =     8.73 ->     8
 *   d = 20  on the small one:  168 289 · … =   107.16 ->   107
 *   d = 10  on the small one:   84 144 · … =    53.58 ->    53   (twice)
 *   d = 1   on the small one:    8 414 · … =     5.36 ->     5   (three times)
 *   d = 6   on the forest:       5 348 · … =     3.41 ->     3
 *   d = 5   on the forest:       4 456 · … =     2.84 ->     2
 *   d = 50  on the grass:          317 · … =     0.20 ->     0 -> raised to 1
 *
 * (A1) per area that is 1 746 + 2·873 + 3·87 + 8 = 3 761 dots in the big deep
 *      forest, 107 + 2·53 + 3·5 = 228 in the small one, 5 in the forest and 1
 *      on the grass patch: 3 995 in total, inside the 4 000-dot budget, and
 *      EVERY one of the four areas is drawn.
 * (A2) THE PROPERTY THE PREVIEW EXISTS FOR — equal ground looks equal. Dots
 *      per 100 m2 of painted area:
 *        big   3 761 / 137 135.89 = 0.027425
 *        small   228 /   8 414.43 = 0.027096
 *      a ratio of 1.0121, against authored densities of 43.1 and 43.0 (1.0023)
 *      — the rest is the flooring of ten small integers. BEFORE the fix those
 *      two numbers were 0.029 and 0.
 * (A3) RED COUNTER-PROBE of the old rule, spelled out as a running budget over
 *      the counts the old preview could produce (min(wanted, 2 000)):
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
 * wanted = min(round(areaM2/100 · density), maxPoints).
 * (D1) 10 000 m2 at 3 per 100 m2 → round(100 · 3) = 300.
 * (D2)    900 m2 at 3 per 100 m2 → round(9 · 3)   =  27.
 * (D3) THE PREVIEW ASKS WITHOUT A CEILING (`Infinity`), because the ceiling is
 *      what made two equally authored woods look 14 times apart:
 *        13 713 589 m2 at 20 → round(137 135.89 · 20) = 2 742 718
 *           841 443 m2 at 20 → round(  8 414.43 · 20) =   168 289
 *      a ratio of 16.30, which IS the ratio of the two areas. Under the old
 *      default ceiling both were 2 000 — two areas 16.3 times apart reported
 *      as equally thick, which is what the preview must never say.
 * (D4) The standing default ceiling is still 2 000 and still applies to a
 *      caller that does not ask otherwise (the whole-area sampler's guard).
 * (D5) Below one prop is none: 10 m2 at 3 per 100 m2 → round(0.3) = 0.
 * (D6) Junk (NaN density, negative area, zero density) is 0, never NaN.
 * (D7) An explicit `maxPoints` overrides the standing ceiling: 10 000 m2 at
 *      3 with maxPoints 100 → 100. That is how the preview thins an entry to
 *      its share, and a lower ceiling yields the PREFIX of the same stream
 *      (pinned in `smoke_scatter_math.mjs`, C14), so a previewed dot is always
 *      a prop the sampler really places.
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

/** The rule that WAS there: sample in list order, at most 2 000 per entry,
 *  until the budget is gone. */
function firstComeFirstServed(wanted, budget) {
  let left = budget;
  return wanted.map((n) => {
    const take = Math.max(0, Math.min(Math.min(n, 2000), left));
    left -= take;
    return take;
  });
}

async function main() {
  const { scatterPreviewShares } = await loadBundled(SRC, 'scatterpreview-');
  const { scatterWantedCount, SCATTER_MAX_PER_ENTRY } =
    await loadBundled(SCATTER_SRC, 'scattercount-');

  console.log('(A) the reporting world — four areas, sixteen rows');
  /** area m2 + the authored densities, in the server's bottom-to-top order */
  const WORLD = [
    [13713589, [1.0, 0.1, 10, 10, 1, 1, 20]],
    [841443, [1, 10, 1, 10, 20, 1]],
    [89126, [5, 6]],
    [633, [50]],
  ];
  const wanted = WORLD.flatMap(([m2, rows]) =>
    rows.map((d) => scatterWantedCount(m2, d, Infinity)));
  check('A the four areas want 5 910 558 / 361 819 / 9 804 / 317 props',
    [wanted.slice(0, 7).reduce((s, n) => s + n, 0),
      wanted.slice(7, 13).reduce((s, n) => s + n, 0),
      wanted.slice(13, 15).reduce((s, n) => s + n, 0), wanted[15]],
    [5910558, 361819, 9804, 317]);
  check('A Σ wanted is 6 282 498', wanted.reduce((s, n) => s + n, 0), 6282498);
  const shares = scatterPreviewShares(wanted, 4000);
  check('A the big wood\'s rows keep 87 / 8 / 873 / 873 / 87 / 87 / 1 746 dots',
    shares.slice(0, 7), [87, 8, 873, 873, 87, 87, 1746]);
  check('A …the small wood\'s 5 / 53 / 5 / 53 / 107 / 5',
    shares.slice(7, 13), [5, 53, 5, 53, 107, 5]);
  check('A …the forest 2 / 3, the grass patch its floor of 1',
    shares.slice(13), [2, 3, 1]);
  const perArea = [shares.slice(0, 7), shares.slice(7, 13), shares.slice(13, 15),
    shares.slice(15)].map((g) => g.reduce((s, n) => s + n, 0));
  check('A1 per area that is 3 761 / 228 / 5 / 1 dots — every area drawn',
    perArea, [3761, 228, 5, 1]);
  check('A1 …3 995 in total, inside the 4 000-dot budget',
    shares.reduce((s, n) => s + n, 0), 3995);
  const dotDensity = (dots, m2) => Math.round((dots / (m2 / 100)) * 1e6) / 1e6;
  check('A2 the two deep forests are drawn at 0.027425 and 0.027096 dots/100 m2',
    [dotDensity(perArea[0], 13713589), dotDensity(perArea[1], 841443)],
    [0.027425, 0.027096]);
  check('A2 …a ratio of 1.0121 for ground authored 43.1 against 43.0',
    Math.round((dotDensity(perArea[0], 13713589)
      / dotDensity(perArea[1], 841443)) * 1e4) / 1e4, 1.0121);
  const old = firstComeFirstServed(wanted, 4000);
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
  check('D1 10 000 m2 at 3 per 100 m2 plants 300',
    scatterWantedCount(10000, 3), 300);
  check('D2 900 m2 at the same 3 plants 27',
    scatterWantedCount(900, 3), 27);
  check('D3 without a ceiling the two woods differ by their AREA ratio, 16.30',
    [scatterWantedCount(13713589, 20, Infinity),
      scatterWantedCount(841443, 20, Infinity),
      Math.round((13713589 / 841443) * 100) / 100],
    [2742718, 168289, 16.3]);
  check('D3 …while the old default ceiling reported both as equally thick',
    [scatterWantedCount(13713589, 20), scatterWantedCount(841443, 20)],
    [2000, 2000]);
  check('D4 that standing ceiling is still 2 000', SCATTER_MAX_PER_ENTRY, 2000);
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
