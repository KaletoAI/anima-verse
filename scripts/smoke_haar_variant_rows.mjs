#!/usr/bin/env node
/**
 * Smoke: the HAAR parts of the Hairstyles tab's pure model (frontend/src/tabs/characters/hairstylesModel.ts,
 * figureModel.ts) — strand-hair plan 2026-11-13, Task 14 (spec § 6.3.4).
 *
 * Usage:  node scripts/smoke_haar_variant_rows.mjs      (no server; esbuild from the workspace bundles the modules)
 *
 * THE CASES, DERIVED BY HAND
 * --------------------------
 * [1] haarVariantRows: seeds [{seed 1, passed true, served false}, {seed 2, passed true, served true, in_use true},
 *     {seed 3, passed false, reasons ['inside the head …']}] → lights ['ok', 'ok', 'bad'], served marks seed 2 only,
 *     row 3's reason == 'inside the head …', row 1's 'Passed every check.'; tile URLs as given ('' for none);
 *     a seed not fitted yet (passed null) → light 'wait'. Seed 1's numbers (mouse-over) with metrics
 *     {tip_p50_rel_shoulder_cm −12.34, eye_cards 0, flyaway_tip_share 0.0495} → 3 lines in the fixed order
 *     "Tips vs. shoulder (median): −12.3 cm" ("-12.3"), "Cards over the eyes: 0", "Flyaway tips: 5.0 %".
 * [2] variantAction: seed 2 (served, in use) → "In use"; in use after another pick was saved (neither served nor
 *     picked: the preview still shows it until the Re-fit) → "In use"; seed 1 → button "Use this — no hub job, CPU refit";
 *     picked but not in use → "Picked — Re-fit applies it (no hub job)"; served but not in use (a better seed after a
 *     run) → "Best — Re-fit applies it (no hub job)".
 * [3] hairStepRows for HAAR (HUB_JOBS hair:haar = {haar 3, fit 0}): the 'haar' row's button label ==
 *     'HAAR strands · 3 hub jobs'; the fit row's == 'Fit · no hub job'.
 *     Seeds stored (step accepted, 3 seeds, made at H), fit accepted (F), nothing due → haar green "Current"
 *     "3 variants made <H> from the hairstyle text."; fit green "Current" "Fitted <F> on the current base model.
 *     Variant 2 in use.".
 *     No backend routed, nothing stored → haar red "No backend", reason "No backend for occasion hair_strands —
 *     /admin/settings → Media Generation → Routing — nothing is spent until one is set.", its button disabled
 *     "No backend routed"; fit grey "Not fitted yet" "Waits for the HAAR strands.", button disabled "Needs the HAAR
 *     strands first".
 *     A pick saved (stale seed_changed, run.steps [fit]) → fit yellow "Due" "Another variant was picked after the fit
 *     in use (<F>) — Re-fit applies it (no hub job); that fit stays in use until then."
 *     The text changed (stale haar_changed, the new ssig has no seeds, run.steps [haar, fit]) → haar yellow "Due",
 *     "The hairstyle text changed after the hair in use was made (<F>) — Run all makes 3 new variants (3 hub
 *     jobs)."
 * [4] Run all (hairstyleActions 'haar'): run {steps [haar, fit], hub_jobs 3} → "Run all · 3 hub jobs"; {steps [fit],
 *     0} → "Run all · no hub job"; {steps [], 0} → "Everything is current" (disabled).
 *     haarRunCost: {steps [haar, fit], hub_jobs 3, cpu_fits 3} → "3 hub jobs (~30–55 s each) + 3 CPU fits (~25 s
 *     each)"; {steps [fit], hub_jobs 0, cpu_fits 2} → "2 CPU fits (~25 s each), no hub job"; {steps [fit], cpu_fits 1}
 *     → "1 CPU fit (~25 s each), no hub job"; nothing due → "".
 * [5] New hairstyle: hairModeDisabled('haar', ['hairdeck', 'haar', 'body']) → null (HAAR enabled);
 *     newHairstyleDisabled('a bun', 'haar', the same) → null; HAIR_MODE_HINTS.haar names the 3 hub jobs and the
 *     licence "CC BY-NC 4.0".
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'smoke-haar-variant-rows-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({ entryPoints: [src], outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`);
  else console.log(`ok  ${label}`);
}

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/hairstylesModel.ts'));
const f = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/figureModel.ts'));
const when = (s) => (s ? `<${s}>` : '');

// [1]
const seed = (over) => ({ seed: 1, passed: true, reasons: [], metrics: {}, tile_url: null, served: false,
  picked: false, in_use: false, ...over });
const panel = (seeds, over = {}) => ({ ssig: 'abc', status: 'passed', seeds, next_seeds: [4, 5, 6], jobs: 3,
  picked: null, served: 2, in_use: 2, route: { routed: true, backend: 'HAAR' }, ...over });
const p1 = panel([
  seed({ seed: 1, tile_url: '/t/1.png', metrics: { tip_p50_rel_shoulder_cm: -12.34, eye_cards: 0, flyaway_tip_share: 0.0495 } }),
  seed({ seed: 2, served: true, in_use: true, tile_url: '/t/2.png' }),
  seed({ seed: 3, passed: false, reasons: ['inside the head …'] }),
]);
const rows = m.haarVariantRows(p1);
check('[1] lights', rows.map((r) => r.light), ['ok', 'ok', 'bad']);
check('[1] served', rows.filter((r) => r.served).map((r) => r.seed), [2]);
check('[1] reasons', [rows[2].reason, rows[0].reason], ['inside the head …', 'Passed every check.']);
check('[1] tiles', rows.map((r) => r.tileUrl), ['/t/1.png', '/t/2.png', '']);
check('[1] not fitted', m.haarVariantRows(panel([seed({ passed: null })]))[0].light, 'wait');
check('[1] numbers', rows[0].numbers.split('\n'),
  ['Tips vs. shoulder (median): -12.3 cm', 'Cards over the eyes: 0', 'Flyaway tips: 5.0 %']);

// [2]
check('[2] actions', [m.variantAction(rows[1]), m.variantAction(rows[0])],
  [{ label: 'In use', button: false }, { label: 'Use this — no hub job, CPU refit', button: true }]);
check('[2] in use, another pick saved', m.variantAction({ ...rows[1], served: false }).label, 'In use');
check('[2] picked, not in use', m.variantAction({ ...rows[0], picked: true, served: true }).label,
  'Picked — Re-fit applies it (no hub job)');
check('[2] best, not in use', m.variantAction({ ...rows[0], served: true }).label,
  'Best — Re-fit applies it (no hub job)');

// [3]
const garment = (over = {}) => ({ running_step: null, failed: null, stale_reasons: [], preview_built_at: 'F',
  steps: { fit: { status: 'accepted', created_at: 'F' },
    haar: { status: 'accepted', seeds: [1, 2, 3], failed: {}, created_at: 'H' } }, ...over });
const info = (over = {}) => ({ pipeline: true, method: 'haar', equipped: true, body_built_at: 'B',
  run: { steps: [], hub_jobs: 0, note: '', refit: false }, step_jobs: { haar: 3, fit: 0 }, garment: garment(),
  hairdeck: null, haar: p1, ...over });
const brief = (r) => r.map((x) => [x.id, x.light, x.state, x.reason, x.button && x.button.label,
  x.button && x.button.disabled]);
check('[3] current', brief(m.hairStepRows(info(), undefined, when)), [
  ['haar', 'green', 'Current', '3 variants made <H> from the hairstyle text.', 'HAAR strands · 3 hub jobs', null],
  ['fit', 'green', 'Current', 'Fitted <F> on the current base model. Variant 2 in use.', 'Fit · no hub job', null],
]);
const noRoute = 'No backend for occasion hair_strands — /admin/settings → Media Generation → Routing';
const empty = info({ haar: panel([], { route: { routed: false, backend: null }, in_use: null, served: null }),
  garment: garment({ preview_built_at: null, steps: { fit: { status: 'missing', created_at: null },
    haar: { status: 'missing', seeds: [], failed: {}, created_at: null } } }),
  run: { steps: ['haar', 'fit'], hub_jobs: 3, note: '', refit: false, cpu_fits: 3 } });
check('[3] no backend', brief(m.hairStepRows(empty, undefined, when)), [
  ['haar', 'red', 'No backend', `${noRoute} — nothing is spent until one is set.`, 'HAAR strands · 3 hub jobs',
    'No backend routed'],
  ['fit', 'grey', 'Not fitted yet', 'Waits for the HAAR strands.', 'Fit · no hub job', 'Needs the HAAR strands first'],
]);
const picked = info({ garment: garment({ stale_reasons: ['seed_changed'] }),
  run: { steps: ['fit'], hub_jobs: 0, note: '', refit: false, cpu_fits: 1 } });
check('[3] pick saved', brief(m.hairStepRows(picked, undefined, when))[1].slice(1, 4), ['yellow', 'Due',
  'Another variant was picked after the fit in use (<F>) — Re-fit applies it (no hub job); that fit stays in use until then.']);
const retext = info({ garment: garment({ stale_reasons: ['haar_changed'], steps: { fit: { status: 'missing', created_at: null },
  haar: { status: 'missing', seeds: [], failed: {}, created_at: null } } }), haar: panel([]),
run: { steps: ['haar', 'fit'], hub_jobs: 3, note: '', refit: false, cpu_fits: 3 } });
check('[3] text changed', brief(m.hairStepRows(retext, undefined, when))[0].slice(1, 4), ['yellow', 'Due',
  'The hairstyle text changed after the hair in use was made (<F>) — Run all makes 3 new variants (3 hub jobs).']);

// [4]
const run = (steps, hubJobs, cpuFits) => ({ steps, hub_jobs: hubJobs, note: '', refit: false, cpu_fits: cpuFits });
check('[4] Run all', [f.hairstyleActions('haar', run(['haar', 'fit'], 3, 3)).runAll,
  f.hairstyleActions('haar', run(['fit'], 0, 1)).runAll, f.hairstyleActions('haar', run([], 0)).runAll],
[{ label: 'Run all · 3 hub jobs', disabled: false }, { label: 'Run all · no hub job', disabled: false },
  { label: 'Everything is current', disabled: true }]);
check('[4] cost line', [m.haarRunCost(run(['haar', 'fit'], 3, 3)), m.haarRunCost(run(['fit'], 0, 2)),
  m.haarRunCost(run(['fit'], 0, 1)), m.haarRunCost(run([], 0))],
['3 hub jobs (~30–55 s each) + 3 CPU fits (~25 s each)', '2 CPU fits (~25 s each), no hub job',
  '1 CPU fit (~25 s each), no hub job', '']);

// [5]
const built = ['hairdeck', 'haar', 'body'];
check('[5] HAAR enabled', [f.hairModeDisabled('haar', built), f.newHairstyleDisabled('a bun', 'haar', built)],
  [null, null]);
check('[5] hint', [/3 hub jobs/.test(f.HAIR_MODE_HINTS.haar), /CC BY-NC 4\.0/.test(f.HAIR_MODE_HINTS.haar)],
  [true, true]);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const x of failures) console.error(`  ${x}`);
  process.exit(1);
}
console.log('\nALL OK');
