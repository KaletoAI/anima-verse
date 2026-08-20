#!/usr/bin/env node
/**
 * Smoke run for the map editor's SCATTER PREVIEW — its two modes, the
 * hysteresis between them and the budget each of them spends. Everything under
 * "the scatter preview" in `frontend/src/tabs/map/mapMath.ts`, over the count
 * rule and the cell raster of the shared sampler
 * (`packages/scene-render/src/scatter.ts`).
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
 *
 * ############################################################################
 * WHAT WENT WRONG THE SECOND TIME (reported 2026-08-20)
 * ############################################################################
 * "The preview and the 3D client disagree hard — the client shows far more."
 *
 * Both halves above were about the RATIO between two areas, and both are still
 * right. What neither of them fixed is the ABSOLUTE density: the client plants
 * the authored number per 100 m2 through the 64 m cell raster
 * (`scatterCellInstances`), while the preview drew a 4 000-dot sample of the
 * whole world. On the reporting world that is 3 995 dots for 6 282 498 props —
 * 0.06 % of what grows, with nothing on the screen saying so.
 *
 * THE FIX, and what sections (E)-(H) pin: where the user LOOKS (zoomed in far
 * enough that one screen fits a frame budget) the preview runs the very same
 * cell sampler over the covered cells and draws the client's own instances;
 * beyond that budget the thinned overview stays, and SAYS what fraction it is.
 *
 * ============================================================================
 * (E) THE MODE SWITCH — cost in the currency the sampler spends
 * ============================================================================
 * The cost of one screen is counted, never sampled: per row, the visible
 * rectangle is clipped against the area's bounding box, the cells of what is
 * left are counted, and each carries the cell sampler's own wanted count
 *
 *     perCell = round(4096 / 100 · density)      (4 096 m2 = one 64 m cell)
 *
 * (E1) THE FIXTURE (also (F)'s): an area from (0,0) to (192,64) — three cells
 *      wide, one cell tall — with ONE row at 5 per 100 m2.
 *        perCell = round(40.96 · 5) = round(204.8) = 205
 *      A viewport rect of 0.5 .. 190 by 0.5 .. 60 falls in cells
 *      floor(0.5/64)=0 .. floor(190/64)=2 in x and 0 .. 0 in z, i.e. the three
 *      cells (0,0), (1,0), (2,0).
 *        cost = { dots: 3 · 205 = 615, cells: 3 }
 * (E2) A viewport that misses the area entirely (x from 1 000) costs NOTHING —
 *      the whole point of a windowed preview: { dots: 0, cells: 0 }.
 * (E3) The budget is 8 000 dots, the band 0.8 / 1.2 around it, i.e. ON at or
 *      below 6 400 and OFF only above 9 600:
 *        6 400 dots: off -> ON, on -> on
 *        6 401 dots: off -> off (not yet), on -> ON (still)
 *        9 600 dots: on -> on, off -> off
 *        9 601 dots: on -> OFF
 * (E4) NO FLAPPING, which is what the band is for. A pan that walks
 *      6 300 -> 6 500 -> 6 300 -> 9 000 -> 6 500 from the true mode stays in
 *      it the whole way: [true, true, true, true, true]. The same walk from
 *      the overview enters it only on the first value that is under 6 400:
 *      [true, true, true, true, true] — 6 300 switches it on and nothing
 *      after that leaves. Starting at 9 000 instead: 9 000 -> off, then
 *      6 500 -> still off (over 6 400), then 6 300 -> on.
 * (E5) THE CELL LIMIT IS NOT HYSTERETIC in the same way, because it is not a
 *      comfort limit: past SCATTER_CELLS_MAX (4 096) the shared enumerator
 *      answers an EMPTY list, and a window over it would draw an area's
 *      scatter as nothing at all. So it is entered only under 4 096 · 0.8 =
 *      3 276.8 and left at the cap itself:
 *        3 276 cells: off -> ON        (dots 0, so the budget never bites)
 *        3 277 cells: off -> off, on -> on
 *        4 096 cells: on -> on
 *        4 097 cells: on -> OFF
 * (E6) A junk cost (NaN dots) is never true mode.
 *
 * ============================================================================
 * (F) THE 1:1 PIN — the preview's dots ARE the client's instances
 * ============================================================================
 * The claim of § B5a form: for the same cell, the same area and the same
 * inputs, the preview's job builder produces the byte-identical instance list
 * a direct `scatterCellInstances` call does. Not "looks similar" — the same
 * objects, in the same order, with the same keys.
 *
 * THE FIXTURE, on top of (E1)'s area (id `ta_pin`, one row at 5 per 100 m2,
 * no model and no height):
 *   · a second area painted ON TOP of it, x 150..192, with no scatter of its
 *     own — the OCCLUDER: ground that is covered grows nothing, so the props
 *     of the third cell east of x = 150 are subtracted.
 *   · a placed location's footprint, the square 70..110 by 10..50, which the
 *     props of the second cell keep clear of.
 *   · the entry names no model and no height, so it is a tuft: 0.8 m tall,
 *     and a prop is assumed to be as wide as it is tall, hence
 *     clearM = 0.8 · 0.5 = 0.40 m (`scatterClearM`). The direct call is given
 *     that 0.40 as a literal — if the builder ever estimates differently, the
 *     lists stop matching, which is the point of pinning it.
 * (F1) Cell (0,0) has NO footprint and NO occluder over it, and it lies whole
 *      inside the area, so its 205 candidates are all accepted: 205 dots, the
 *      authored density to the dot (205 / 40.96 = 5.005 per 100 m2 against an
 *      authored 5 — the rounding of 204.8, nothing else).
 * (F2) Cell (1,0) carries the footprint, cell (2,0) the occluder, so both draw
 *      FEWER than 205 — a preview that ignored either would show 205 there
 *      too, and this is the red counter-probe that says the exclusions really
 *      ran.
 * (F3) THE PIN: `scatterWindowDots` over the three cells === the concatenation
 *      of three direct `scatterCellInstances` calls with
 *      `scatterCellSeed('ta_pin', 0, cx, 0)`, byte for byte (JSON).
 * (F4) …and no instance carries a `variant` key on EITHER side: the map
 *      editor reads no variant maps (`readScatter` whitelists three fields),
 *      so a mix would itself be a mismatch with what the builder asks for.
 * (F5) The order is the raster's own: row-major cells, x inner — so the first
 *      dot of the list lies in cell (0,0) and the last in cell (2,0).
 *
 * ============================================================================
 * (G) THE THINNED LABEL — what the overview admits to
 * ============================================================================
 * `drawn / Σ wanted`, in percent, with the precision following the size (whole
 * percent from 10 up, one decimal from 1, two below, `<0.01` under a hundredth
 * of a percent).
 * (G1) THE REPORTING WORLD, straight out of (A1): 3 995 dots of 6 282 498
 *      props = 0.0635% -> "0.06". The label the map now carries.
 * (G2) 500 of 1 000 = 50% -> "50";  105 of 1 000 = 10.5% -> "11" (rounded, at
 *      or above ten a decimal says nothing);  99 of 1 000 = 9.9% -> "9.9";
 *      12 of 1 000 = 1.2% -> "1.2";  1 of 10 000 = 0.01% -> "0.01";
 *      1 of 1 000 000 = 0.0001% -> "<0.01".
 * (G3) Everything drawn is "100": 614 of 614 -> "100".
 * (G4) Nothing grown or nothing drawn is "0", never NaN or "Infinity".
 *
 * ============================================================================
 * (H) DETERMINISM — the same world twice is the same picture
 * ============================================================================
 * (H1) Two independent runs of the whole path (jobs built again from the raw
 *      areas, dots sampled again) are byte-identical. A preview that redraws
 *      differently on a pan would be indistinguishable from random to an
 *      author comparing two forests.
 * (H2) …and the window is a SLICE of one world, not a picture of a walk: the
 *      dots of cell (1,0) come out the same whether the viewport covered one
 *      cell or all three.
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
  const {
    scatterPreviewShares, scatterPreviewJobs, scatterWindowCost,
    scatterTrueModeNext, scatterWindowDots, scatterThinnedPercentText,
    SCATTER_TRUE_BUDGET, SCATTER_TRUE_ON, SCATTER_TRUE_OFF,
  } = await loadBundled(SRC, 'scatterpreview-');
  const {
    scatterWantedCount, SCATTER_MAX_PER_ENTRY, scatterCellInstances,
    scatterCellSeed, SCATTER_CELL_M, SCATTER_CELLS_MAX,
  } = await loadBundled(SCATTER_SRC, 'scattercount-');

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

  /* ------------------------------------------------------------------ *
   * The fixture of (E) and (F): three cells of painted ground, one row,
   * one occluding area on top of it and one footprint in the middle.
   * ------------------------------------------------------------------ */
  const AREA_RING = [[0, 0], [192, 0], [192, 64], [0, 64]];
  /** painted OVER the first one, x 150..192 — it grows nothing itself and is
   *  therefore only ever an occluder (see `scatterPreviewJobs`) */
  const COVER_RING = [[150, 0], [192, 0], [192, 64], [150, 64]];
  const AREAS = [
    { id: 'ta_pin', kind: 'forest', polygon: AREA_RING,
      meta: { scatter: [{ density_per_100m2: 5 }] } },
    { id: 'ta_cover', kind: 'water', polygon: COVER_RING, meta: {} },
  ];
  /** a placed location's drawn outline, 70..110 by 10..50 (world metres) */
  const FOOTPRINTS = [{ points: [[70, 10], [110, 10], [110, 50], [70, 50]] }];
  /** 0.5 .. 190 by 0.5 .. 60 -> the cells (0,0), (1,0), (2,0) */
  const RECT = { min_x: 0.5, min_z: 0.5, max_x: 190, max_z: 60 };
  /** the tuft's clearance, by hand: 0.8 m tall, as wide as it is tall,
   *  half of that kept clear -> 0.40 m */
  const CLEAR_M = 0.4;
  const cellDirect = (cx, cz) => scatterCellInstances({
    ring: AREA_RING,
    cx,
    cz,
    densityPer100m2: 5,
    seed: scatterCellSeed('ta_pin', 0, cx, cz),
    footprints: FOOTPRINTS,
    clearM: CLEAR_M,
    occluders: [COVER_RING],
  }).map((p) => ({ x: p.x, z: p.z, entry: 0 }));

  console.log('\n(E) the mode switch — what one screen would cost');
  const jobs = scatterPreviewJobs(AREAS);
  check('E1 the covering area grows nothing, so there is ONE row to draw',
    [jobs.length, jobs[0]?.areaId, jobs[0]?.index, jobs[0]?.density,
      jobs[0]?.clearM, jobs[0]?.perCell, jobs[0]?.wanted],
    // wanted over the whole shape: 192 · 64 = 12 288 m2 at 5 per 100 m2 is
    // round(122.88 · 5) = round(614.4) = 614 props.
    [1, 'ta_pin', 0, 5, 0.4, 205, 614]);
  check('E1 one 64 m cell of ground at 5 per 100 m2 carries 205 candidates',
    scatterWantedCount(SCATTER_CELL_M * SCATTER_CELL_M, 5, 4000), 205);
  check('E1 the three-cell viewport costs 615 instances over 3 cells',
    scatterWindowCost(jobs, RECT), { dots: 615, cells: 3 });
  check('E2 a viewport that misses the painted ground costs nothing',
    scatterWindowCost(jobs, { min_x: 1000, min_z: 1000, max_x: 1190,
      max_z: 1060 }), { dots: 0, cells: 0 });
  check('E3 the budget is 8 000 dots with a 0.8 / 1.2 band',
    [SCATTER_TRUE_BUDGET, SCATTER_TRUE_ON, SCATTER_TRUE_OFF,
      SCATTER_TRUE_BUDGET * SCATTER_TRUE_ON, SCATTER_TRUE_BUDGET * SCATTER_TRUE_OFF],
    [8000, 0.8, 1.2, 6400, 9600]);
  const modeAt = (on, dots, cells = 3) => scatterTrueModeNext(on, { dots, cells });
  check('E3 6 400 switches true density ON, 6 401 does not',
    [modeAt(false, 6400), modeAt(false, 6401)], [true, false]);
  check('E3 …and once on it stays on to 9 600, off at 9 601',
    [modeAt(true, 6401), modeAt(true, 9600), modeAt(true, 9601)],
    [true, true, false]);
  const walk = (start, costs) => {
    let on = start;
    return costs.map((d) => { on = modeAt(on, d); return on; });
  };
  check('E4 a pan across the band never leaves the true mode',
    walk(true, [6300, 6500, 6300, 9000, 6500]),
    [true, true, true, true, true]);
  check('E4 …and from the overview it is entered on the first value under 6 400',
    walk(false, [6500, 9000, 6300, 6500, 9000]),
    [false, false, true, true, true]);
  check('E5 the cell cap is 4 096, entered under 3 276.8 and left at the cap',
    [SCATTER_CELLS_MAX, modeAt(false, 0, 3276), modeAt(false, 0, 3277),
      modeAt(true, 0, 3277), modeAt(true, 0, 4096), modeAt(true, 0, 4097)],
    [4096, true, false, true, true, false]);
  check('E6 a junk cost is never true mode',
    [modeAt(true, NaN), modeAt(false, NaN), modeAt(true, 100, NaN)],
    [false, false, false]);

  console.log('\n(F) the 1:1 pin — the preview draws the client\'s instances');
  const dots = scatterWindowDots(jobs, RECT, FOOTPRINTS);
  const inCell = (cx) => dots.filter((d) => d.x >= cx * 64 && d.x < (cx + 1) * 64);
  check('F1 the untouched cell draws its full 205 — the authored density',
    [inCell(0).length,
      Math.round((inCell(0).length / ((64 * 64) / 100)) * 1000) / 1000],
    [205, 5.005]);
  check('F2 the footprint and the covering area SUBTRACT from the other two',
    [inCell(1).length < 205, inCell(2).length < 205,
      inCell(1).length > 0, inCell(2).length > 0],
    [true, true, true, true]);
  // …and WHERE the two exclusions bit, as predicates that can be read off the
  // fixture: nothing stands on the footprint (nor within its 0.40 m clearance
  // of it) and nothing stands on ground the covering area hides.
  check('F2 no dot stands on the footprint or in its 0.40 m clearance',
    dots.filter((d) => d.x > 69.6 && d.x < 110.4 && d.z > 10 && d.z < 50).length,
    0);
  check('F2 no dot stands on the ground the covering area hides (x > 150)',
    dots.filter((d) => d.x > 150).length, 0);
  check('F2 …and the window is 615 candidates minus exactly those',
    [dots.length < 615, dots.length === inCell(0).length + inCell(1).length
      + inCell(2).length], [true, true]);
  const direct = [...cellDirect(0, 0), ...cellDirect(1, 0), ...cellDirect(2, 0)];
  check('F3 every dot is the very instance the cell sampler answers, byte for byte',
    JSON.stringify(dots), JSON.stringify(direct));
  check('F4 no instance carries a variant key on either side',
    [dots.some((d) => 'variant' in d),
      direct.some((d) => 'variant' in d),
      Object.keys(dots[0]).sort()],
    [false, false, ['entry', 'x', 'z']]);
  check('F5 the raster order is row-major, x inner',
    [dots[0].x < 64, dots[dots.length - 1].x >= 128], [true, true]);
  // RED COUNTER-PROBE: without the footprint the same window is a DIFFERENT
  // picture — otherwise (F3) would be pinning an exclusion that never ran.
  differs('F2 …a run without the footprint really does differ',
    scatterWindowDots(jobs, RECT, []), dots);

  console.log('\n(G) the label of the thinned overview');
  check('G1 the reporting world: 3 995 dots of 6 282 498 props is "0.06"',
    scatterThinnedPercentText(3995, 6282498), '0.06');
  check('G2 the precision follows the size',
    [scatterThinnedPercentText(500, 1000), scatterThinnedPercentText(105, 1000),
      scatterThinnedPercentText(99, 1000), scatterThinnedPercentText(12, 1000),
      scatterThinnedPercentText(1, 10000), scatterThinnedPercentText(1, 1000000)],
    ['50', '11', '9.9', '1.2', '0.01', '<0.01']);
  check('G3 everything drawn is 100', scatterThinnedPercentText(614, 614), '100');
  check('G4 nothing grown or nothing drawn is 0, never NaN',
    [scatterThinnedPercentText(0, 1000), scatterThinnedPercentText(10, 0),
      scatterThinnedPercentText(NaN, 10), scatterThinnedPercentText(10, NaN)],
    ['0', '0', '0', '0']);

  console.log('\n(H) determinism');
  const again = scatterWindowDots(scatterPreviewJobs(AREAS), RECT, FOOTPRINTS);
  check('H1 the whole path run twice is the same picture',
    JSON.stringify(again), JSON.stringify(dots));
  const oneCell = scatterWindowDots(jobs,
    { min_x: 70, min_z: 10, max_x: 100, max_z: 40 }, FOOTPRINTS);
  check('H2 a one-cell viewport draws that cell exactly as the wide one did',
    JSON.stringify(oneCell), JSON.stringify(cellDirect(1, 0)));

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
