#!/usr/bin/env node
/**
 * Check of Ruling A79's UI — "Refused images" in an own-mesh piece's dialog: the pure helpers of
 * `frontend/src/tabs/characters/refusedAttemptsModel.ts` and the wiring by source greps.
 *
 * Usage:  node scripts/check_a79_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_a64_ui.mjs); no server, no world. Exit 1 with the mismatch list,
 * 0 when every case holds. The server half is scripts/smoke_garment_use_undo.py.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND
 * ============================================================================
 * Fixture: Ylva's blouse as the panel carried it on 2026-11-15 — worn front/back and ghost back accepted, ghost
 * front NOT accepted with two stored attempts, both refused for the hem (attempt 1 reason "garment ends at another
 * height than the worn piece: |Δ| 0.1336 Hb > 0.02 Hb"), one passing attempt 3 (stored, not refused) — and the
 * worn front accepted with a refused attempt 2 beside it.
 * [1] refusedViews: only ghost front (worn front is accepted → its refused attempt is the grid's business), its
 *     attempts 1 and 2 (3 passed → not listed), each with the plan of use_runs["ghost"]["front"][n].
 * [2] reasonWords: the hem reason → text "It ends at another height than the worn piece", detail the whole reason;
 *     "skin left in the image: 0.0553 > 0.03" → "Skin of the body is left in the image"; an unknown "odd thing: 3"
 *     → "Odd thing" (first clause, capitalised).
 * [3] attemptUseLabel: plan follow_up {steps [cutout, mesh, fit], hub_jobs 3} →
 *     "Use this attempt · 0 hub jobs now, then 3 hub jobs (cut-outs, mesh)" (the fit is CPU — not named among hub
 *     steps); hub_jobs 1 → "… then 1 hub job (…)"; null → "… then cost unknown (…)"; no follow_up → "Use this attempt
 *     · 0 hub jobs now"; a blocked or in-use plan → "Use this attempt".
 * [4] Undo: state {step ghost, view front, attempt 1, passing false, available true, images [cutout front before
 *     false, ghost front before false], mesh_before true, refusal_before true} →
 *     headline "Accepted by you: Piece-only view · front, attempt 1", light yellow, lines
 *     ["Piece-only view · front: none before — the one there now goes", "Cut-out · front: none before — the one
 *     there now goes", "Mesh: the mesh from before comes back", "The refusal comes back (the Build shows the step as
 *     failed again)"]; passing → "Used by you: …"; available false → light grey; label "Undo — 0 hub jobs".
 * [5] imageRefusal: "ghost front refused — …" true, "worn back refused — …" true, "mesh refused" false, "" false.
 * [6] Wiring: the dialog renders GarmentRefusedAttempts with use_runs + use_undo and posts …/images/undo-use; the
 *     panel uses useEnlarge (images enlargeable) and StepLight; FieldFigure names the Details title for a refused
 *     image; no window.confirm/alert/prompt in the new files; de.json holds a key for every literal of [2]–[4] and
 *     the panel's own strings.
 */
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);
const fails = [];
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `\n      got  ${JSON.stringify(got)}\n      want ${JSON.stringify(want)}`}`);
  if (!ok) fails.push(label);
};

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'), join(ROOT, 'client3d/node_modules/esbuild')]) {
    try { return require_(cand); } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-a79-ui-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({ entryPoints: [join(ROOT, src)], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const src = (rel) => readFileSync(join(ROOT, rel), 'utf8');
const has = (label, text, needle) => eq(label, text.includes(needle), true);
const t = (s) => s;
const M = await loadBundled('frontend/src/tabs/characters/refusedAttemptsModel.ts');

// [1]
const HEM = 'garment ends at another height than the worn piece: |Δ| 0.1336 Hb > 0.02 Hb';
const refused = (n) => ({ attempt: n, url: `/a${n}.png`, created_at: null, gate: { ok: false, reasons: [HEM] } });
const plan = (n) => ({ passing: false, in_use: false, block: '', follow_up: { steps: ['cutout', 'mesh', 'fit'], hub_jobs: n, note: 'x' } });
const garment = { steps: {
  worn: { front: { accepted: true, attempts: [refused(2)] }, back: { accepted: true, attempts: [] } },
  ghost: { front: { accepted: false, attempts: [refused(1), refused(2), { attempt: 3, url: '/a3.png', gate: { ok: true } }] },
    back: { accepted: true, attempts: [] } },
} };
const useRuns = { ghost: { front: { 1: plan(3), 2: plan(3) } } };
const views = M.refusedViews(garment, useRuns);
eq('[1] views', views.map((v) => [v.step, v.view, v.attempts.map((a) => a.attempt)]), [['ghost', 'front', [1, 2]]]);
eq('[1] plan + reasons', [views[0].attempts[0].plan, views[0].attempts[0].reasons], [plan(3), [HEM]]);
eq('[1] none', M.refusedViews(null, null), []);

// [2]
eq('[2] hem', M.reasonWords(HEM, t), { text: 'It ends at another height than the worn piece', detail: HEM });
eq('[2] skin', M.reasonWords('skin left in the image: 0.0553 > 0.03', t).text, 'Skin of the body is left in the image');
eq('[2] unknown', M.reasonWords('odd thing: 3', t).text, 'Odd thing');

// [3]
eq('[3] 3 jobs', M.attemptUseLabel(plan(3), t), 'Use this attempt · 0 hub jobs now, then 3 hub jobs (cut-outs, mesh)');
eq('[3] 1 job', M.attemptUseLabel(plan(1), t), 'Use this attempt · 0 hub jobs now, then 1 hub job (cut-outs, mesh)');
eq('[3] unknown', M.attemptUseLabel(plan(null), t), 'Use this attempt · 0 hub jobs now, then cost unknown (cut-outs, mesh)');
eq('[3] no follow-up', M.attemptUseLabel({ ...plan(3), follow_up: null }, t), 'Use this attempt · 0 hub jobs now');
eq('[3] blocked / in use', [M.attemptUseLabel({ ...plan(3), block: 'b' }, t), M.attemptUseLabel({ ...plan(3), in_use: true }, t)],
  ['Use this attempt', 'Use this attempt']);

// [4]
const undo = { step: 'ghost', view: 'front', attempt: 1, at: null, passing: false, available: true, why_not: '',
  images: [{ step: 'cutout', view: 'front', before: false }, { step: 'ghost', view: 'front', before: false }],
  mesh_before: true, refusal_before: true };
eq('[4] headline', M.undoHeadline(undo, t), 'Accepted by you: Piece-only view · front, attempt 1');
eq('[4] passing', M.undoHeadline({ ...undo, passing: true }, t), 'Used by you: Piece-only view · front, attempt 1');
eq('[4] lights', [M.undoLight(undo), M.undoLight({ ...undo, available: false })], ['yellow', 'grey']);
eq('[4] lines', M.undoLines(undo, t), ['Piece-only view · front: none before — the one there now goes',
  'Cut-out · front: none before — the one there now goes', 'Mesh: the mesh from before comes back',
  'The refusal comes back (the Build shows the step as failed again)']);
eq('[4] label', M.undoLabel(t), 'Undo — 0 hub jobs');

// [5]
eq('[5] imageRefusal', ['ghost front refused — x', 'worn back refused — y', 'mesh refused', ''].map(M.imageRefusal),
  [true, true, false, false]);

// [6]
const dialog = src('frontend/src/tabs/characters/WardrobeGarment.tsx');
const panel = src('frontend/src/tabs/characters/GarmentRefusedAttempts.tsx');
const figure = src('frontend/src/tabs/characters/FieldFigure.tsx');
has('[6] dialog renders the panel', dialog, '<GarmentRefusedAttempts garment={garment} useRuns={info.use_runs} useUndo={info.use_undo}');
has('[6] dialog posts undo-use', dialog, '/images/undo-use`');
has('[6] panel: enlargeable', panel, 'useEnlarge()');
has('[6] panel: light', panel, '<StepLight');
has('[6] Figure: Details for a refused image', figure, "t('Details — use a refused image')");
eq('[6] no native dialogs', [panel, src('frontend/src/tabs/characters/refusedAttemptsModel.ts')]
  .some((s) => /window\.(confirm|alert|prompt)/.test(s)), false);
const de = JSON.parse(src('shared/languages/de.json')).translations;
const literal = (s) => [...s.matchAll(/t\('((?:[^'\\]|\\.)+)'\)/g)].map((m) => m[1].replace(/\\'/g, "'"));
const seen = new Set();
const rec = (k) => { seen.add(k); return k; };
M.attemptUseLabel(plan(3), rec); M.attemptUseLabel(plan(1), rec); M.attemptUseLabel(plan(null), rec);
M.undoLines(undo, rec); M.undoLines({ ...undo, images: [{ step: 'ghost', view: 'front', before: true }], mesh_before: false }, rec);
M.undoHeadline(undo, rec); M.undoHeadline({ ...undo, passing: true }, rec); M.undoLabel(rec);
const modelKeys = [...seen, ...M.REASON_WORDS.map(([, words]) => words), ...Object.values(M.VIEW_NAMES),
  ...Object.values(M.FOLLOW_WORDS)];
const figureDetails = figure.slice(figure.indexOf("row.state === 'failed' && imageRefusal(row.failure)") - 10,
  figure.indexOf("t('Details — use a refused image')") + 60);
eq('[6] de.json keys', [...new Set([...literal(panel), ...literal(figureDetails), ...modelKeys])]
  .filter((k) => !(k in de)), []);

if (fails.length) {
  console.log(`\nFAILED (${fails.length}): ${fails.join(', ')}`);
  process.exit(1);
}
console.log('\nall ok');
