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
 * THE FIX, and what sections (E)-(I) pin: where the user LOOKS the preview
 * runs the very same cell sampler over the covered cells and draws the
 * client's own instances; beyond the budget the thinned sample stays, and SAYS
 * what fraction it is.
 *
 * ============================================================================
 * WHAT WENT WRONG THE SECOND TIME (reported 2026-08-20) — section (I)
 * ============================================================================
 * "My forest shows 17 dots on the map; the 3D client puts well over two
 * hundred trees in it." Counted end to end, BOTH were right, and neither
 * number was the world:
 *
 *   · the wood (`ta_63926f52`, 11 vertices, 89 646.28 m2, two rows at 5 per
 *     100 m2) really wants 8 964 trees, and the client really plants 8 576 of
 *     them — the authoring is one tree per 10 m2;
 *   · the preview drew 16 of those 8 964 (0.18 %), plus the grass patch's
 *     floor of one dot beside it: the seventeen that were counted.
 *
 * The cause was not the density and not the planting. The MODE was decided
 * ONCE FOR THE WHOLE SCREEN, and the same viewport held a 14.2 km2 deep forest
 * of 2 005 260 props. That sum is over any frame budget from any zoom, so the
 * wood was thinned at EVERY zoom — true density was UNREACHABLE for it at
 * every scale that still showed it whole.
 *
 * So the mode moved onto the AREA, and the thinning label with it.
 *
 * ============================================================================
 * (E) THE MODE SWITCH — per area, in the currency the sampler spends
 * ============================================================================
 * The cost of an area is counted, never sampled: per row, the visible
 * rectangle is clipped against the area's bounding box, the cells of what is
 * left are counted, and each carries the cell sampler's own wanted count
 *
 *     perCell = round(4096 / 100 · density)      (4 096 m2 = one 64 m cell)
 *
 * …and the mode hangs on `bound = min(wanted, windowDots)` — the whole shape's
 * true count against the window's estimate. Each is wrong alone: the estimate
 * charges every rim cell in full over a bounding box the polygon fills half of
 * (the reporting wood: 25 830 estimated against 8 576 drawn), while `wanted`
 * would call four cells of a 14 km2 forest two million.
 *
 * (E1) THE FIXTURE (also (F)'s): an area from (0,0) to (192,64) — three cells
 *      wide, one cell tall — with ONE row at 5 per 100 m2.
 *        perCell = round(40.96 · 5) = round(204.8) = 205
 *      A viewport rect of 0.5 .. 190 by 0.5 .. 60 falls in cells
 *      floor(0.5/64)=0 .. floor(190/64)=2 in x and 0 .. 0 in z, i.e. the three
 *      cells (0,0), (1,0), (2,0).
 *        windowDots = 3 · 205 = 615, cells = 3, wanted = 614
 *        bound = min(614, 615) = 614
 *      The badge anchor is the ring's mean: x = 96, z = 32.
 * (E2) A viewport that misses the area entirely (x from 1 000) costs NOTHING —
 *      the whole point of a windowed preview: windowDots 0, cells 0, bound 0.
 * (E3) The per-area budget is 12 000 dots, the band 0.8 / 1.2 around it, i.e.
 *      ON at or below 9 600 and OFF only above 14 400:
 *         9 600: off -> ON, on -> on
 *         9 601: off -> off (not yet), on -> ON (still)
 *        14 400: on -> on
 *        14 401: on -> OFF
 *      12 000 is deliberately above the ~9 000 props of a 9-hectare wood at
 *      ten per 100 m2 — a hand-painted forest is exactly the thing an author
 *      needs to see whole.
 * (E4) NO FLAPPING, which is what the band is for. A pan that walks
 *      9 500 -> 9 700 -> 9 500 -> 14 000 -> 9 700 from the true mode stays in
 *      it the whole way. The same walk from the thinned side enters it only on
 *      the first value under 9 600: 9 700 -> off, 14 000 -> off, then
 *      9 500 -> on and nothing after that leaves.
 * (E5) THE CELL LIMIT IS NOT HYSTERETIC in the same way, because it is not a
 *      comfort limit: past SCATTER_CELLS_MAX (4 096) the shared enumerator
 *      answers an EMPTY list, and a window over it would draw an area's
 *      scatter as nothing at all. So it is entered only under 4 096 · 0.8 =
 *      3 276.8 and left at the cap itself:
 *        3 276 cells: off -> ON        (bound 0, so the budget never bites)
 *        3 277 cells: off -> off, on -> on
 *        4 096 cells: on -> on
 *        4 097 cells: on -> OFF
 * (E6) A junk cost (NaN bound) is never true mode.
 * (E7) THE PROPERTY THE ROUND IS ABOUT: 614 beside 2 000 000 is still 614, so
 *      the small area keeps true density and only the monster is thinned. The
 *      RED COUNTER-PROBE is the rule this replaces — a global sum of
 *      2 000 614 thinned both, and the plan must not agree with it.
 * (E8) THE SUM GUARD is what the per-area cap cannot give. Four areas at
 *      5 000 / 4 000 / 5 000 / 6 000 each fit the 12 000 cap but sum to
 *      20 000, over the 16 000 total; the LARGEST goes first (6 000), which
 *      leaves 15 000 and stops there — three areas exact instead of none.
 *      A tie falls to the LATER paint order, so the answer never depends on
 *      `Array.prototype.sort` being stable.
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
 * The label it feeds is now PER AREA, at the area's centroid: since the mode
 * is an area's own business a picture is routinely MIXED — an exact wood
 * beside an approximated deep forest — and one number in a corner would be
 * wrong about the first and unattributable for the second. An area drawn
 * exactly carries no badge at all.
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
 *
 * ============================================================================
 * (I) THE REPORTING FOREST — the 2026-08-20 numbers, end to end
 * ============================================================================
 * The real `ta_63926f52` ring (all eleven vertices, off
 * `GET /world/terrain-areas`) beside a deep forest of the same order of size
 * carrying its real seven densities, and a small grass patch — so the mixed
 * picture the badges exist for is really built.
 *
 * (I1) SHOELACE over the eleven points: 89 646.28 m2. Per row
 *      round(896.4628 · 5) = 4 482, twice = 8 964 trees, i.e. one per 10 m2.
 *      The monster: 4 000 × 3 555 = 14 220 000 m2 at 1 / .1 / 3 / 3 / 1 / 1 / 5
 *      = 142 200 + 14 220 + 426 600 + 426 600 + 142 200 + 142 200 + 711 000 =
 *      2 005 020. The grass patch 600 m2 at 50 = 300.
 * (I2) THE OLD PICTURE. Σ wanted = 2 014 284, so every row kept its share and
 *      the wood's was floor(4 482 · 4 000 / 2 014 284) = floor(8.9014) = 8 per
 *      row — SIXTEEN dots, 0.18 % of 8 964. The grass patch's floor(0.5957)
 *      = 0 was raised to its floor of 1: the seventeenth dot that was counted.
 * (I3) AND IT WAS THE ONLY PICTURE. Over the wood's own bounding box —
 *      x −1 553.71…−1 078.65, z −1 072.33…−702.99, the widest viewport that
 *      still shows it whole — the cells are floor(−1553.71/64) = −25 …
 *      floor(−1078.65/64) = −17 (9 columns) by floor(−1072.33/64) = −17 …
 *      floor(−702.99/64) = −11 (7 rows) = 63 per row. The wood's two rows:
 *      126 cells, 63 · 205 · 2 = 25 830. The monster's seven, over the same
 *      box it covers: 441 cells, 63 · (41+4+123+123+41+41+205) = 63 · 578 =
 *      36 414. A global sum of 62 244 is over any budget, from this zoom and
 *      from every wider one.
 * (I4) THE BOUND UNLOCKS IT: min(8 964, 25 830) = 8 964, under the 9 600 it
 *      takes to switch on, so the wood draws EXACTLY while the monster's
 *      min(2 005 020, 36 414) = 36 414 keeps it thinned. The grass patch is
 *      off this screen and costs nothing at all.
 * (I5) THE MIXED VIEWPORT, −1 620…−1 070 by −1 220…−700, holds all three.
 *      The grass patch: one cell (floor(−1600/64) = floor(−1580/64) = −25,
 *      floor(−1200/64) = floor(−1170/64) = −19) at round(40.96 · 50) = 2 048,
 *      bound by its own 300. The monster now spans the viewport: 10 columns ×
 *      10 rows = 100 cells per row, 700 in all, 100 · 578 = 57 800. So TWO
 *      areas exact and the monster approximated — and the sum guard is not
 *      what decided it: 8 964 + 300 = 9 264, well under 16 000.
 * (I6) WHAT IS DRAWN NOW. Each cell draws its 205 candidates over 4 096 m2 and
 *      keeps the ones inside the ring, so one row is expected at
 *      205 · 89 646.28 / 4 096 = 4 486.7 and both at 8 973 — the authored
 *      8 964 to within the rounding of 204.8 to 205. Pinned as a ±5 % band
 *      around that hand-derived expectation, because an exact count of a
 *      seeded sample would be a recording. Against the 16 dots of before that
 *      is a factor above 250.
 * (I7) THE BADGE, on the one area that was approximated. Its rows keep
 *      floor(w · 4 000 / 2 005 020): 283, 28, 851, 851, 283, 283, 1 418 =
 *      3 997 dots of 2 005 020 props -> "0.20", hung on its centroid
 *      (x −2 000, z −4 890/4 = −1 222.5). The exact areas carry none.
 * (I8) `scatterThinnedDots` is `scatterThinnedByArea` without its badges,
 *      byte for byte — one sample, two readings of it. RED COUNTER-PROBE: the
 *      new picture is not the old 16 dots.
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
    scatterPreviewShares, scatterPreviewJobs, scatterAreaCosts,
    scatterAreaPlan, scatterWindowDots, scatterThinnedByArea,
    scatterThinnedDots, scatterThinnedPercentText,
    SCATTER_AREA_TRUE_MAX, SCATTER_TRUE_TOTAL,
    SCATTER_TRUE_ON, SCATTER_TRUE_OFF,
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

  console.log('\n(E) the mode switch — PER AREA, on what THAT area would cost');
  const jobs = scatterPreviewJobs(AREAS);
  check('E1 the covering area grows nothing, so there is ONE row to draw',
    [jobs.length, jobs[0]?.areaId, jobs[0]?.index, jobs[0]?.density,
      jobs[0]?.clearM, jobs[0]?.perCell, jobs[0]?.wanted],
    // wanted over the whole shape: 192 · 64 = 12 288 m2 at 5 per 100 m2 is
    // round(122.88 · 5) = round(614.4) = 614 props.
    [1, 'ta_pin', 0, 5, 0.4, 205, 614]);
  check('E1 one 64 m cell of ground at 5 per 100 m2 carries 205 candidates',
    scatterWantedCount(SCATTER_CELL_M * SCATTER_CELL_M, 5, 4000), 205);
  // The area's own cost, and the two numbers it is the smaller of: 3 cells of
  // 205 candidates is 615, the whole painted shape wants 614 -> bound 614.
  // The badge anchor is the mean of the ring: x (0+192+192+0)/4 = 96,
  // z (0+0+64+64)/4 = 32.
  check('E1 the three-cell viewport costs that ONE area 615 over 3 cells',
    scatterAreaCosts(jobs, RECT),
    [{ areaId: 'ta_pin', windowDots: 615, cells: 3, wanted: 614, bound: 614,
      cx: 96, cz: 32 }]);
  check('E2 a viewport that misses the painted ground costs nothing',
    scatterAreaCosts(jobs, { min_x: 1000, min_z: 1000, max_x: 1190,
      max_z: 1060 }),
    [{ areaId: 'ta_pin', windowDots: 0, cells: 0, wanted: 614, bound: 0,
      cx: 96, cz: 32 }]);
  check('E3 the per-area budget is 12 000 dots with a 0.8 / 1.2 band, the sum 16 000',
    [SCATTER_AREA_TRUE_MAX, SCATTER_TRUE_TOTAL, SCATTER_TRUE_ON,
      SCATTER_TRUE_OFF, SCATTER_AREA_TRUE_MAX * SCATTER_TRUE_ON,
      SCATTER_AREA_TRUE_MAX * SCATTER_TRUE_OFF],
    [12000, 16000, 0.8, 1.2, 9600, 14400]);
  /** one synthetic area cost, so the rule can be walked without a world */
  const costOf = (areaId, bound, cells = 3) => ({
    areaId, windowDots: bound, cells, wanted: bound, bound, cx: 0, cz: 0,
  });
  const modeAt = (on, bound, cells = 3) => scatterAreaPlan(
    [costOf('a', bound, cells)], new Set(on ? ['a'] : [])).trueIds.length === 1;
  check('E3 9 600 switches an area to true density, 9 601 does not',
    [modeAt(false, 9600), modeAt(false, 9601)], [true, false]);
  check('E3 …and once on it stays on to 14 400, off at 14 401',
    [modeAt(true, 9601), modeAt(true, 14400), modeAt(true, 14401)],
    [true, true, false]);
  const walk = (start, bounds) => {
    let on = start;
    return bounds.map((d) => { on = modeAt(on, d); return on; });
  };
  check('E4 a pan across the band never leaves the true mode',
    walk(true, [9500, 9700, 9500, 14000, 9700]),
    [true, true, true, true, true]);
  check('E4 …and from the thinned side it is entered on the first value under 9 600',
    walk(false, [9700, 14000, 9500, 9700, 14000]),
    [false, false, true, true, true]);
  check('E5 the cell cap is 4 096, entered under 3 276.8 and left at the cap',
    [SCATTER_CELLS_MAX, modeAt(false, 0, 3276), modeAt(false, 0, 3277),
      modeAt(true, 0, 3277), modeAt(true, 0, 4096), modeAt(true, 0, 4097)],
    [4096, true, false, true, true, false]);
  check('E6 a junk cost is never true mode',
    [modeAt(true, NaN), modeAt(false, NaN), modeAt(true, 100, NaN)],
    [false, false, false]);
  // (E7) THE PROPERTY THE WHOLE ROUND IS ABOUT: a neighbour cannot decide an
  // area's mode. 614 beside 2 000 000 is still 614.
  check('E7 a small area keeps true density beside a monster',
    scatterAreaPlan([costOf('small', 614), costOf('monster', 2000000)],
      new Set()),
    { trueIds: ['small'], thinnedIds: ['monster'] });
  // …and the RED COUNTER-PROBE of the rule this replaces: the OLD global rule
  // summed the screen (614 + 2 000 000 = 2 000 614, far over any budget) and
  // thinned EVERYTHING. The plan must not agree with that.
  differs('E7 …where the old global sum thinned both',
    scatterAreaPlan([costOf('small', 614), costOf('monster', 2000000)],
      new Set()).trueIds, []);
  // (E8) THE SUM GUARD — five areas that each fit do not fit together, and the
  // LARGEST goes first. 5 000 · 4 = 20 000 > 16 000; dropping one 5 000 leaves
  // 15 000, which fits, so exactly one is demoted and it is the biggest.
  check('E8 the sum guard demotes the largest area first, and stops when it fits',
    scatterAreaPlan([costOf('a', 5000), costOf('b', 4000), costOf('c', 5000),
      costOf('d', 6000)], new Set()),
    { trueIds: ['a', 'b', 'c'], thinnedIds: ['d'] });
  check('E8 …a tie is broken by the later paint order, never by sort stability',
    scatterAreaPlan([costOf('a', 9000), costOf('b', 9000)], new Set()),
    { trueIds: ['a'], thinnedIds: ['b'] });
  check('E8 …and a sum that fits demotes nobody',
    scatterAreaPlan([costOf('a', 8000), costOf('b', 8000)], new Set()).trueIds,
    ['a', 'b']);

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

  console.log('\n(I) THE REPORTING FOREST — 17 dots against 8 964 trees');
  /* ------------------------------------------------------------------ *
   * The area the 2026-08-20 report is about, straight off
   * `GET /world/terrain-areas`: `ta_63926f52`, kind `forest`, ELEVEN
   * vertices, two rows at 5 per 100 m2 (maple, oak). Beside it the deep
   * forest that decided the old global mode for it — its real seven
   * densities on a rectangle of the same order of size — and a small grass
   * patch, so the mixed picture the badges exist for is actually built.
   * ------------------------------------------------------------------ */
  const FOREST_RING = [
    [-1116.19, -911.29], [-1233.44, -850.68], [-1447.83, -733.25],
    [-1508.74, -702.99], [-1532.03, -746.21], [-1553.71, -841.95],
    [-1481.08, -973.55], [-1369.2, -1072.33], [-1243.64, -1023.13],
    [-1142.37, -990.96], [-1078.65, -930.75],
  ];
  /** SHOELACE, by hand over those eleven points: |Σ (x_i·z_{i+1} −
   *  x_{i+1}·z_i)| / 2 = 89 646.28 m2. The bounding box is
   *  x −1 553.71 … −1 078.65 (475.06 m) by z −1 072.33 … −702.99 (369.34 m),
   *  i.e. 175 449 m2 — the polygon fills barely half of it, which is the
   *  whole reason a box-and-full-cell estimate cannot be the judge. */
  const FOREST_M2 = 89646.28;
  /** the monster BELOW it in paint order (so it never occludes the wood, as
   *  in the world): 4 000 × 3 555 = 14 220 000 m2 with the deep forest's own
   *  seven densities */
  const MONSTER_RING = [[-4000, -3000], [0, -3000], [0, 555], [-4000, 555]];
  const MONSTER_D = [1, 0.1, 3, 3, 1, 1, 5];
  /** …and a 20 × 30 = 600 m2 grass patch at 50 per 100 m2, clear of the wood's
   *  bounding box (z −1 200 … −1 170 is above z −1 072.33) */
  const GRASS_RING = [[-1600, -1200], [-1580, -1200], [-1580, -1170],
    [-1600, -1170]];
  const WORLD_AREAS = [
    { id: 'ta_57f3df57', kind: 'deep_forest', polygon: MONSTER_RING,
      meta: { scatter: MONSTER_D.map((d) => ({ density_per_100m2: d })) } },
    { id: 'ta_63926f52', kind: 'forest', polygon: FOREST_RING,
      meta: { scatter: [{ density_per_100m2: 5 }, { density_per_100m2: 5 }] } },
    { id: 'ta_2a0854a6', kind: 'grass', polygon: GRASS_RING,
      meta: { scatter: [{ density_per_100m2: 50 }] } },
  ];
  const wj = scatterPreviewJobs(WORLD_AREAS);
  const wantedOf = (id) => wj.filter((j) => j.areaId === id)
    .reduce((sum, j) => sum + j.wanted, 0);
  // (I1) WHAT THE AUTHOR ASKED FOR. 89 646.28 / 100 = 896.4628, times 5 is
  // 4 482.314 -> 4 482 per row, twice: 8 964 trees. That is one tree per
  // 10 m2 of ground — a 3.16 m spacing — so "well over two hundred trees"
  // in a 3D client is the AUTHORING, not a defect in the planting.
  check('I1 the wood really wants 4 482 + 4 482 = 8 964 trees',
    [Math.round(scatterAreaCosts(wj, { min_x: -1e5, min_z: -1e5, max_x: 1e5,
      max_z: 1e5 })[1].wanted),
    scatterWantedCount(FOREST_M2, 5, Infinity), wantedOf('ta_63926f52')],
    [8964, 4482, 8964]);
  // …and the neighbours: 14 220 000 / 100 = 142 200 per unit density, so
  // 142 200 + 14 220 + 426 600 + 426 600 + 142 200 + 142 200 + 711 000 =
  // 2 005 020; the grass patch 600 / 100 · 50 = 300.
  check('I1 …beside 2 005 020 props of deep forest and 300 of grass',
    [wantedOf('ta_57f3df57'), wantedOf('ta_2a0854a6')], [2005020, 300]);
  // (I2) WHAT THE PREVIEW USED TO SHOW. Σ wanted = 2 005 020 + 8 964 + 300 =
  // 2 014 284, hopelessly over the 4 000-dot budget, so every row kept its
  // share — and the wood's is floor(4 482 · 4 000 / 2 014 284) =
  // floor(8.9014) = 8 dots per row, SIXTEEN for the whole forest. The grass
  // patch's floor(300 · 4 000 / 2 014 284) = floor(0.5957) = 0 is raised to
  // its floor of 1, and that seventeenth dot beside the wood is what a count
  // off the screen comes to.
  const oldShares = scatterPreviewShares(wj.map((j) => j.wanted), 4000);
  check('I2 the OLD global rule drew the forest as 8 + 8 = 16 dots',
    [oldShares[7], oldShares[8], oldShares[7] + oldShares[8]], [8, 8, 16]);
  check('I2 …the grass patch its floor of 1 — 17 dots in that corner of the map',
    [oldShares[9], oldShares[7] + oldShares[8] + oldShares[9]], [1, 17]);
  check('I2 …which is 0.18 % of the 8 964 trees that grow there',
    scatterThinnedPercentText(16, 8964), '0.18');
  // (I3) AND THAT WAS THE ONLY PICTURE AVAILABLE. The old mode was decided on
  // the SUM over the screen, and the monster alone costs more than any budget
  // from any zoom that still shows the wood whole: its bounding box covers the
  // wood's, so the same 63 columns × rows of cells carry all seven of its rows
  // at 41 + 4 + 123 + 123 + 41 + 41 + 205 = 578 candidates per cell.
  /** the wood's own bounding box, to the metre — the widest viewport that
   *  still shows the whole area and nothing more */
  const FOREST_RECT = { min_x: -1553.71, min_z: -1072.33,
    max_x: -1078.65, max_z: -702.99 };
  const wCosts = scatterAreaCosts(wj, FOREST_RECT);
  // cells: x floor(−1553.71/64) = −25 … floor(−1078.65/64) = −17 -> 9 columns,
  // z floor(−1072.33/64) = −17 … floor(−702.99/64) = −11 -> 7 rows = 63 cells
  // per row. The wood has two rows (126 cells, 63 · 205 · 2 = 25 830
  // candidates), the monster seven (441 cells, 63 · 578 = 36 414).
  check('I3 over that viewport the wood costs 25 830 and the monster 36 414',
    [wCosts[1].cells, wCosts[1].windowDots, wCosts[0].cells,
      wCosts[0].windowDots],
    [126, 25830, 441, 36414]);
  // (I4) THE BOUND IS THE SMALLER OF THE TWO, and that is what unlocks the
  // wood: 25 830 candidates is the box-and-full-cell estimate (the polygon
  // fills 51 % of its box), while the shape really carries 8 964 — under the
  // 9 600 it takes to switch on. The monster's own 36 414 is under its
  // 2 005 020, and over the cap either way.
  check('I4 the wood is judged by its 8 964, the monster by its 36 414',
    [wCosts[1].bound, wCosts[0].bound], [8964, 36414]);
  // The grass patch is OFF this screen (its box does not meet the viewport),
  // so it costs 0 and is trivially "true": true density over an empty window
  // enumerates nothing and draws nothing, which is the right picture of
  // ground nobody is looking at — and the cheapest one.
  check('I4 …so the wood draws EXACTLY and only the monster is thinned',
    scatterAreaPlan(wCosts, new Set()),
    { trueIds: ['ta_63926f52', 'ta_2a0854a6'], thinnedIds: ['ta_57f3df57'] });
  check('I4 …the off-screen grass patch costing nothing at all',
    [wCosts[2].cells, wCosts[2].windowDots, wCosts[2].bound], [0, 0, 0]);
  // (I5) THE MIXED PICTURE the badges exist for — a viewport holding the wood,
  // the grass patch and part of the monster.
  const MIX_RECT = { min_x: -1620, min_z: -1220, max_x: -1070, max_z: -700 };
  const mCosts = scatterAreaCosts(wj, MIX_RECT);
  const mPlan = scatterAreaPlan(mCosts, new Set());
  // the grass patch: one cell (x floor(−1600/64) = floor(−1580/64) = −25,
  // z floor(−1200/64) = floor(−1170/64) = −19) at round(40.96 · 50) = 2 048
  // candidates, against 300 props on the shape -> bound 300.
  check('I5 the grass patch costs one cell of 2 048 and is bound by its 300',
    [mCosts[2].cells, mCosts[2].windowDots, mCosts[2].bound], [1, 2048, 300]);
  // the monster now spans the whole viewport: x floor(−1620/64) = −26 …
  // floor(−1070/64) = −17 -> 10 columns, z floor(−1220/64) = −20 …
  // floor(−700/64) = −11 -> 10 rows, so 100 cells · 578 = 57 800.
  check('I5 the monster costs 57 800 over 700 cells',
    [mCosts[0].cells, mCosts[0].windowDots, mCosts[0].bound],
    [700, 57800, 57800]);
  check('I5 …two areas exact, the monster approximated',
    mPlan, { trueIds: ['ta_63926f52', 'ta_2a0854a6'],
      thinnedIds: ['ta_57f3df57'] });
  // …and the sum guard is not what decided it: 8 964 + 300 = 9 264, well
  // under the 16 000 the frame allows.
  check('I5 …the true areas sum to 9 264, inside the 16 000 total',
    mCosts[1].bound + mCosts[2].bound <= SCATTER_TRUE_TOTAL
      && mCosts[1].bound + mCosts[2].bound === 9264, true);
  // (I6) WHAT IS ACTUALLY DRAWN NOW. Every cell of the window draws its 205
  // candidates over 4 096 m2 and keeps the ones inside the ring, so the
  // expected count of one row is 205 · 89 646.28 / 4 096 = 4 486.7 and of both
  // 8 973 — the authored 8 964 to within the rounding of 204.8 to 205.
  // Pinned as a ±5 % band around that hand-derived expectation: an exact
  // count would be a recording, and the number is a seeded sample.
  const trueJobs = wj.filter((j) => mPlan.trueIds.includes(j.areaId));
  const thinJobs = wj.filter((j) => !mPlan.trueIds.includes(j.areaId));
  const exactDots = scatterWindowDots(trueJobs, MIX_RECT, []);
  const wood = exactDots.filter((d) => d.entry === 0 || d.entry === 1).length;
  const expectWood = Math.round((205 * FOREST_M2 * 2) / 4096);
  check('I6 the wood now draws its own trees, within 5 % of the expected 8 973',
    [expectWood, wood > expectWood * 0.95 && wood < expectWood * 1.05],
    [8973, true]);
  // THE HEADLINE, and the reason the round exists: 16 dots became thousands.
  check('I6 …which is more than 250 times the 16 dots of before',
    wood / 16 > 250, true);
  // (I7) THE BADGE, on the one area that was approximated. Its rows keep
  // floor(w · 4 000 / 2 005 020) each: 283, 28, 851, 851, 283, 283, 1 418 =
  // 3 997 dots of 2 005 020 props -> "0.20".
  const thin = scatterThinnedByArea(thinJobs, []);
  check('I7 the whole 4 000-dot budget now goes to the one thinned area',
    scatterPreviewShares(thinJobs.map((j) => j.wanted), 4000),
    [283, 28, 851, 851, 283, 283, 1418]);
  check('I7 one badge, on the monster, over its own centroid',
    [thin.badges.length, thin.badges[0].areaId, thin.badges[0].x,
      thin.badges[0].z, thin.badges[0].wanted],
    // mean of the four corners: x (−4000 + 0 + 0 − 4000)/4 = −2000,
    // z (−3000 − 3000 + 555 + 555)/4 = −4890/4 = −1222.5
    [1, 'ta_57f3df57', -2000, -1222.5, 2005020]);
  check('I7 …reading "~0.20% of 2005020"',
    [thin.badges[0].drawn, scatterThinnedPercentText(thin.badges[0].drawn,
      thin.badges[0].wanted)],
    [3997, '0.20']);
  // …and the wood gets NO badge: nothing about it was approximated.
  check('I7 the exact areas carry no badge at all',
    thin.badges.some((b) => b.areaId !== 'ta_57f3df57'), false);
  // (I8) the two halves are still ONE list of dots, and the plain overview is
  // still the badge-free view of the same sample.
  check('I8 scatterThinnedDots is scatterThinnedByArea without its badges',
    JSON.stringify(scatterThinnedDots(thinJobs, [])),
    JSON.stringify(thin.dots));
  // RED COUNTER-PROBE: under the OLD global rule this very viewport drew the
  // wood as 16 dots. The new picture must not agree with that.
  differs('I8 …and the new picture is not the old one',
    wood, 16);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
