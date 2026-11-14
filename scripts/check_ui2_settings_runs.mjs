#!/usr/bin/env node
/**
 * Check of Task UI2 (docs/superpowers/plans/2026-11-12-unified-worn-pieces.md; the user's rules R1 "Run all skips
 * what is current", R2 "a single step redoes, its cost shown, disabled with the reason when its inputs are
 * missing", R3 "a setting is saved on its own, nothing runs; the step then shows as due") — the frontend half:
 * the pure helpers of `frontend/src/tabs/characters/baseBodyModel.ts` and the wiring by source greps.
 *
 * Usage:  node scripts/check_ui2_settings_runs.mjs
 *
 * Self-bundling via esbuild (like scripts/check_base_body_ui.mjs); no server, no world. Exit 1 with the mismatch
 * list, 0 when every case holds. The server halves: scripts/smoke_face_settings_due.py (gap 1),
 * scripts/smoke_expression_regenerate_stored.py (gap 2), scripts/smoke_extension_tip_save_due.py (gap 3).
 *
 * THE CASES, DERIVED BY HAND
 * [1] Gap 1 — faceDueLine(plan): kind face_retexture with face_due "changed" and 2 hub jobs → "Face values changed —
 *     not applied yet (2 hub jobs)"; 1 job → "… (1 hub job)"; face_due "missing" → null; another kind → null; no
 *     plan → null. runAllWhat('face_retexture', t, 'changed') starts "Face values changed — not applied yet";
 *     with 'missing' → "Adds the missing face retexture to the base model". FieldBaseBody hands
 *     faceDueLine(info.run_all, t) to FaceSettings, which shows it with "Run all applies them".
 * [2] Gap 3 — runAllWhat('extension_rig') → "Tip settings saved, not built yet: rebuilds the extension bones of the
 *     base model"; runAllStep('extension') → "Extension bones (local)". ExtensionTipPanel: Save posts
 *     …/model3d/extension-tip (no /apply in that call); a separate Rebuild posts …/model3d/extension-tip/apply and is
 *     labelled TIP_REBUILD_LABEL "Rebuild (local, no hub job)"; no "Apply" button text is left; the due state shows
 *     TIP_DUE_NOTE — since Ruling A53 as the panel's yellow light over a green record, else in the state line.
 * [3] Gap 2 — ExpressionsTab posts …/expressions/{file}/regenerate, its button is disabled by `!e.regenerate?.ok`
 *     and the caption under it comes from regenerateCaption (the job count or the server's reason).
 * [4] Sweep — the footwear width cap is saved only: WardrobeGarment's onWidthCap posts …/footwear/width-cap and
 *     starts no run (no `start(` inside it).
 */
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild',
                      join(ROOT, 'frontend/node_modules/esbuild'),
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
  const dir = await mkdtemp(join(tmpdir(), 'check-ui2-'));
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

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`);
  else console.log(`ok  ${label}`);
}
const src = (rel) => {
  try { return readFileSync(join(ROOT, rel), 'utf8'); } catch { return ''; }
};

const m = await loadBundled('frontend/src/tabs/characters/baseBodyModel.ts');
const ra = (o) => ({ kind: '', steps: [], hub_jobs: 0, note: '', face_due: '', running: false, last: null, ...o });

// [1]
check('[1] changed, 2 jobs', m.faceDueLine(ra({ kind: 'face_retexture', face_due: 'changed', hub_jobs: 2 })),
  'Face values changed — not applied yet (2 hub jobs)');
check('[1] changed, 1 job', m.faceDueLine(ra({ kind: 'face_retexture', face_due: 'changed', hub_jobs: 1 })),
  'Face values changed — not applied yet (1 hub job)');
check('[1] missing', m.faceDueLine(ra({ kind: 'face_retexture', face_due: 'missing', hub_jobs: 2 })), null);
check('[1] other kind', m.faceDueLine(ra({ kind: 'plain_body', hub_jobs: 4 })), null);
check('[1] no plan', m.faceDueLine(null), null);
check('[1] what: changed', m.runAllWhat('face_retexture', undefined, 'changed').startsWith('Face values changed — not applied yet'),
  true);
check('[1] what: missing', m.runAllWhat('face_retexture', undefined, 'missing'), 'Adds the missing face retexture to the base model');
const baseBody = src('frontend/src/tabs/characters/FieldBaseBody.tsx');
check('[1] Base body tab hands the line to FaceSettings', /dueLine=\{faceDueLine\(info\.run_all, t\)\}/.test(baseBody), true);
check('[1] the header passes face_due', /runAllWhat\(runAll\.kind, t, runAll\.face_due\)/.test(baseBody), true);
const faceSettings = src('frontend/src/tabs/characters/FaceSettings.tsx');
check('[1] FaceSettings shows it', /\{dueLine \? <div[^>]*>\{dueLine\} — \{t\('Run all applies them'\)\}/.test(faceSettings), true);

// [2]
check('[2] what: extension', m.runAllWhat('extension_rig'),
  'Tip settings saved, not built yet: rebuilds the extension bones of the base model');
check('[2] step: extension', m.runAllStep('extension'), 'Extension bones (local)');
check('[2] labels', [m.TIP_REBUILD_LABEL, m.TIP_DUE_NOTE],
  ['Rebuild (local, no hub job)', 'Saved — not built yet. Rebuild (local, no hub job) or Run all builds it.']);
const tip = src('frontend/src/tabs/characters/ExtensionTipPanel.tsx');
const sendFn = (tip.split('const send = async')[1] || '').split('\n  }\n')[0];
const rebuildFn = (tip.split('const rebuild = async')[1] || '').split('\n  }\n')[0];
check('[2] Save posts the settings only', [/model3d\/extension-tip`/.test(sendFn), /extension-tip\/apply/.test(sendFn)],
  [true, false]);
check('[2] Rebuild posts /apply', /model3d\/extension-tip\/apply`/.test(rebuildFn), true);
check('[2] buttons', [/>\{t\('Save'\)\}<\/button>/.test(tip), /\{t\(TIP_REBUILD_LABEL\)\}/.test(tip),
  /\{t\('Apply'\)\}/.test(tip)], [true, true, false]);
// Ruling A53: over a green record the due state is the panel's light (yellow, TIP_DUE_NOTE), else the state line.
check('[2] due state shown', [/panel\.due && !dueLight \? t\(TIP_DUE_NOTE\)/.test(tip),
  /light: 'yellow' as const, state: TIP_DUE_NOTE/.test(tip)], [true, true]);

// [3]
const expressions = src('frontend/src/tabs/characters/ExpressionsTab.tsx');
check('[3] posts regenerate', /\/expressions\/\$\{encodeURIComponent\(f\)\}\/regenerate`/.test(expressions), true);
check('[3] disabled without a plan', /disabled=\{!e\.regenerate\?\.ok \|\| !!regenerating\[e\.file\]\}/.test(expressions), true);
check('[3] caption', /\{regenerateCaption\(e\.regenerate, !!e\.is_base, t\)\}/.test(expressions), true);

// [4]
const garment = src('frontend/src/tabs/characters/WardrobeGarment.tsx');
const capFn = (garment.split('const onWidthCap = async')[1] || '').split('\n  }\n')[0];
check('[4] width cap saved only', [/footwear\/width-cap`/.test(capFn), /\bstart\(/.test(capFn)], [true, false]);

if (failures.length) {
  console.error('\nFAILED:\n' + failures.join('\n'));
  process.exit(1);
}
console.log('\nALL OK');
