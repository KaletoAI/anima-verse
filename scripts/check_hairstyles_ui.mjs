#!/usr/bin/env node
/**
 * Check: the pure helpers of the rebuilt Hairstyles tab (frontend/src/tabs/characters/hairstylesModel.ts,
 * Task UI4 of docs/superpowers/plans/2026-11-12-unified-worn-pieces.md) plus the source rules the tab must keep.
 *
 * Usage:  node scripts/check_hairstyles_ui.mjs      (no server; esbuild from the workspace bundles the module)
 *
 * THE CASES, DERIVED BY HAND
 * --------------------------
 * [1] jobsLabel: null → "cost unknown", 0 → "no hub job", 1 → "1 hub job", 9 → "9 hub jobs".
 * [2] hairStepRows, HairDeck hair, everything current (HUB_JOBS hair:hairdeck = {hairdeck 1, fit 0}):
 *       HairDeck green "Current", "Made <when> from the profile picture.", button
 *         "Regenerate — 1 hub job, then fit on the CPU" (enabled);
 *       Fit green "Current", "Fitted <when> on the current base model. 6 spring chains.", button
 *         "Re-fit — no hub job" (enabled).
 *     The same with the placement saved after the fit (stale_reasons [placement_changed], run.steps [fit]):
 *       Fit yellow "Due", "The placement setting changed after the fit in use (<when>) — Re-fit applies it
 *       (no hub job); that fit stays in use until then." — the HairDeck row stays green.
 *     The base model rebuilt (base_model_changed, body built at B): the reason names B in brackets.
 *     No profile picture, nothing made: HairDeck grey "Not made yet", its button disabled "Set a profile picture
 *       first"; Fit grey "Not fitted yet", "Waits for the HairDeck result.", its button disabled "Needs the
 *       HairDeck result first".
 *     A refused HairDeck: red "Refused", "<error> — Regenerate tries a new seed (1 hub job)."
 *     A temporary NPC (pipeline false): two grey rows "Not built", no button.
 *     HAAR: one grey row "Not built yet", no button. Hair in the body worn as the plain body's hair: one green
 *       row "Current", "… — built <when>.", no button (its flow is the Figure tab's Build).
 * [3] listLight / listReason: haar → grey; current + no due → green "Current"; current + due [fit] → yellow
 *     "Due: Fit"; stale → yellow with the server's reason; missing → grey.
 * [4] settingDue: placement with placement_changed and fit 0 jobs → "Saved, not applied — Re-fit applies it
 *     (no hub job)"; colour without colour_changed → null; stiffness → null (it acts on the motion at once).
 * [5] placementMap: pivot p = (0, 1.56, 0.03), fitted f0 = 6 mm, a0 = 4.5°, w0 = 1; dragged f1 = 16 mm,
 *     a1 = 34.5° (Δa = 30°: cos 0.8660254, sin 0.5), w1 = 1.5; mid plane cx = 0, half width h = 0.08.
 *       Q = (0, 1.66, 0.036): dy = 0.1, dz = 0.036 − 0.006 − 0.03 = 0 → y = 1.56 + 0.1·0.8660254 = 1.6466025,
 *         z = 0.03 + 0.1·0.5 + 0.016 = 0.096.
 *       x = ±0.1 (beyond h): ±(0.08 + 0.02·1.5) = ±0.11; x = 0.05 (inside h) stays 0.05.
 *     placementIdentity true for equal values, false for a 1 mm shift.
 * [6] placementRuler, pivot z 0.03, forward 14 mm: 1 rail + 16 ticks (−5 … +10 cm) + 4 cyan lines (the shift
 *     twice, 2 mm apart, and two end bars) = 21; the rail runs z −0.02 … 0.13; the tick at the pivot (cm 5) is
 *     12 mm long, cm 6 is 6 mm; the shift runs z 0.03 … 0.044. Forward 0 → 17 lines (no shift drawn).
 * [7] previewMotion, chain stiffness 0.4, per_stiffness 3.7, 0.8 … 6.0 Hz: factor 2 → 3.7·0.4·2 = 2.96 Hz,
 *     rev "hair-preview:2.00"; factor 5 → 7.4 clamped to 6 Hz; fit_swing false → undefined.
 * [8] hexToLinear: #ffffff → [1,1,1]; #000000 → [0,0,0]; #808080 → ((128/255 + 0.055)/1.055)^2.4 = 0.21586;
 *     "red" → null. colourTint(#808080 → #ffffff) = 1/0.21586 = 4.63 → clamped 4; (#ffffff → #808080) = 0.21586;
 *     same colour → null.
 * [9] wearButton: none → "Wear"; automatic 9 → "Wear · Build 9 hub jobs"; automatic 0 → "Wear · no hub job";
 *     manual 9 → "Wear · no job now", title "Nothing runs on the click; the Build you start then costs 9 hub jobs".
 * [10] Sources: no native dialog in the tab's files; HairDeckPlacement.tsx is gone (no legacy placement form);
 *     the tab names no other flow's run route (`/figure/build` only via FigureBuildLine, no `/model3d/`); every
 *     3D preview passes `builtAt`; the New-hairstyle dialog is a createPortal to document.body.
 */
import { existsSync, readFileSync } from 'node:fs';
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
  const dir = await mkdtemp(join(tmpdir(), 'check-hairstyles-ui-'));
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
const r7 = (v) => Math.round(v * 1e7) / 1e7;
const r5 = (v) => Math.round(v * 1e5) / 1e5;

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/hairstylesModel.ts'));
const when = (s) => (s ? `<${s}>` : '');

// [1]
check('[1] jobsLabel', [null, 0, 1, 9].map((n) => m.jobsLabel(n)),
  ['cost unknown', 'no hub job', '1 hub job', '9 hub jobs']);

// [2]
const hd = (over = {}) => ({ status: 'accepted', created_at: 'H', error: null, seed: 7, backend: 'hub', attempt: 1,
  images: { input: { url: '/x.png' } }, input_source: 'profile', chains: { count: 6, fitted: true, swing: true },
  ...over });
const garment = (over = {}) => ({ running_step: null, failed: null, stale_reasons: [], preview_built_at: 'F',
  steps: { fit: { status: 'accepted', created_at: 'F' } }, ...over });
const info = (over = {}) => ({ pipeline: true, method: 'hairdeck', equipped: true, body_built_at: 'B',
  run: { steps: [], hub_jobs: 0, note: '', refit: false }, step_jobs: { hairdeck: 1, fit: 0 }, garment: garment(),
  hairdeck: hd(), ...over });
const brief = (rows) => rows.map((r) => [r.id, r.light, r.state, r.reason, r.button && r.button.label,
  r.button && r.button.disabled]);

check('[2] current', brief(m.hairStepRows(info(), undefined, when)), [
  ['hairdeck', 'green', 'Current', 'Made <H> from the profile picture.', 'Regenerate — 1 hub job, then fit on the CPU', null],
  ['fit', 'green', 'Current', 'Fitted <F> on the current base model. 6 spring chains.', 'Re-fit — no hub job', null],
]);
const placed = info({ garment: garment({ stale_reasons: ['placement_changed'] }),
  run: { steps: ['fit'], hub_jobs: 0, note: '', refit: false } });
check('[2] placement saved after the fit', brief(m.hairStepRows(placed, undefined, when)).map((r) => r.slice(0, 4)), [
  ['hairdeck', 'green', 'Current', 'Made <H> from the profile picture.'],
  ['fit', 'yellow', 'Due', 'The placement setting changed after the fit in use (<F>) — Re-fit applies it (no hub job); '
    + 'that fit stays in use until then.'],
]);
const rebuilt = info({ garment: garment({ stale_reasons: ['base_model_changed'] }),
  run: { steps: ['fit'], hub_jobs: 0, note: '', refit: false } });
check('[2] base model rebuilt names when', m.hairStepRows(rebuilt, undefined, when)[1].reason,
  'The base model was rebuilt (<B>) after the fit in use (<F>) — Re-fit applies it (no hub job); '
  + 'that fit stays in use until then.');
const nothing = info({ garment: garment({ preview_built_at: null, steps: { fit: { status: 'missing', created_at: null } } }),
  hairdeck: hd({ status: 'missing', created_at: null, images: { input: null }, chains: null }),
  run: { steps: ['hairdeck', 'fit'], hub_jobs: 1, note: '', refit: false } });
check('[2] no profile picture', brief(m.hairStepRows(nothing, undefined, when)), [
  ['hairdeck', 'grey', 'Not made yet', 'No profile picture — set one in the Profile tab, then Run all makes the hair.',
    'Regenerate — 1 hub job, then fit on the CPU', 'Set a profile picture first'],
  ['fit', 'grey', 'Not fitted yet', 'Waits for the HairDeck result.', 'Re-fit — no hub job',
    'Needs the HairDeck result first'],
]);
const refused = info({ hairdeck: hd({ status: 'refused', error: 'No hair found' }) });
check('[2] refused', brief(m.hairStepRows(refused, undefined, when))[0].slice(1, 4),
  ['red', 'Refused', 'No hair found — Regenerate tries a new seed (1 hub job).']);
check('[2] temporary NPC', brief(m.hairStepRows(info({ pipeline: false }), undefined, when)).map((r) => r.slice(0, 3)
  .concat([r[4]])), [['hairdeck', 'grey', 'Not built', null], ['fit', 'grey', 'Not built', null]]);
check('[2] HAAR', brief(m.hairStepRows(info({ method: 'haar' }), undefined, when)).map((r) => [r[0], r[1], r[2], r[4]]),
  [['haar', 'grey', 'Not built yet', null]]);
check('[2] body, plain', brief(m.hairStepRows(info({ method: 'body', plain: true, base_prompts: { state: 'current' } }),
  undefined, when)), [['body', 'green', 'Current', 'The plain body was rendered with this hairstyle — built <B>.', null,
  null]]);

// [3]
check('[3] list lights', [m.listLight('current', 'haar'), m.listLight('current', 'hairdeck'),
  m.listLight('current', 'hairdeck', ['fit']), m.listLight('stale', 'hairdeck'), m.listLight('missing', 'body')],
['grey', 'green', 'yellow', 'yellow', 'grey']);
check('[3] list reasons', [m.listReason({ state: 'current' }), m.listReason({ state: 'current' }, ['fit']),
  m.listReason({ state: 'stale', reason: 'Fitted on an older body' }), m.listReason(null)],
['Current', 'Due: Fit', 'Fitted on an older body', '']);

// [4]
check('[4] settingDue', [m.settingDue('placement', placed), m.settingDue('colour', placed),
  m.settingDue('stiffness', placed)], ['Saved, not applied — Re-fit applies it (no hub job)', null, null]);

// [5]
const pivot = [0, 1.56, 0.03];
const fitted = { forward_m: 0.006, tilt_deg: 4.5, width_scale: 1 };
const map = m.placementMap(pivot, fitted, { forward_m: 0.016, tilt_deg: 34.5, width_scale: 1.5 }, 0, 0.08);
check('[5] turned and shifted', map([0, 1.66, 0.036]).map(r7), [0, 1.6466025, 0.096]);
check('[5] width beyond the head', [map([0.1, 1.56, 0.036])[0], map([-0.1, 1.56, 0.036])[0], map([0.05, 1.56, 0.036])[0]]
  .map(r7), [0.11, -0.11, 0.05]);
check('[5] identity', [m.placementIdentity(fitted, { ...fitted }),
  m.placementIdentity(fitted, { ...fitted, forward_m: 0.007 })], [true, false]);

// [6]
const ruler = m.placementRuler(pivot, 0.12, 1.6, 0.014);
check('[6] ruler lines', [ruler.length, ruler[0].points.map((p) => r7(p[2])), r7(ruler[6].points[0][1] - ruler[6].points[1][1]),
  r7(ruler[7].points[0][1] - ruler[7].points[1][1]), ruler[17].points.map((p) => r7(p[2])), ruler[17].color],
[21, [-0.02, 0.13], 0.012, 0.006, [0.03, 0.044], '#00e5ff']);
check('[6] no shift drawn at 0', m.placementRuler(pivot, 0.12, 1.6, 0).length, 17);

// [7]
const pm = { groups: { hair_c00: { bones: ['b0'], freq_hz: 1.48, zeta: 0.5 } }, chain_stiffness: { hair_c00: 0.4 },
  freq: { per_stiffness: 3.7, min_hz: 0.8, max_hz: 6 }, fit_swing: true };
const two = m.previewMotion(pm, 2);
check('[7] factor 2', [two.rev, two.groups.hair_c00.freq_hz, two.groups.hair_c00.bones], ['hair-preview:2.00', 2.96, ['b0']]);
check('[7] clamped', m.previewMotion(pm, 5).groups.hair_c00.freq_hz, 6);
check('[7] Swing off', m.previewMotion({ ...pm, fit_swing: false }, 1), undefined);

// [8]
check('[8] hexToLinear', [m.hexToLinear('#ffffff'), m.hexToLinear('#000000'), m.hexToLinear('#808080').map(r5),
  m.hexToLinear('red')], [[1, 1, 1], [0, 0, 0], [0.21586, 0.21586, 0.21586], null]);
check('[8] colourTint', [m.colourTint('#808080', '#ffffff'), m.colourTint('#ffffff', '#808080').map(r5),
  m.colourTint('#7a3b1e', '#7A3B1E')], [[4, 4, 4], [0.21586, 0.21586, 0.21586], null]);

// [9]
check('[9] wearButton', [m.wearButton(null).label, m.wearButton({ hub_jobs: 9, automatic: true }).label,
  m.wearButton({ hub_jobs: 0, automatic: true }).label, m.wearButton({ hub_jobs: 9, automatic: false }).label,
  m.wearButton({ hub_jobs: 9, automatic: false }).title],
['Wear', 'Wear · Build 9 hub jobs', 'Wear · no hub job', 'Wear · no job now',
  'Nothing runs on the click; the Build you start then costs 9 hub jobs']);

// [10]
const dir = join(ROOT, 'frontend/src/tabs/characters');
const tab = readFileSync(join(dir, 'FieldHairstyles.tsx'), 'utf8');
const live = readFileSync(join(dir, 'HairLiveControls.tsx'), 'utf8');
const parts = readFileSync(join(dir, 'HairstyleParts.tsx'), 'utf8');
const all = tab + live + parts;
check('[10] no native dialogs', /window\.(prompt|alert|confirm)\(/.test(all), false);
check('[10] no legacy placement form', existsSync(join(dir, 'HairDeckPlacement.tsx')), false);
check('[10] no other flow\'s run route', [/\/model3d\//.test(all), /figure\/build/.test(tab + live),
  /figure\/build/.test(parts)], [false, false, true]);
const viewers = tab.match(/<Model3DViewer\b[\s\S]*?\/>/g) || [];
check('[10] every 3D preview shows Built <time>', [viewers.length > 0, viewers.every((v) => /builtAt=/.test(v))],
  [true, true]);
check('[10] dialog through createPortal', /return createPortal\([\s\S]*?document\.body,\s*\)/.test(tab), true);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
