#!/usr/bin/env node
/**
 * Check of Task UI5 for the 3D tab (the user's tab checklist; plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md)
 * — the pure helpers of `frontend/src/tabs/characters/model3dModel.ts` and the wiring by source greps.
 *
 * Usage:  node scripts/check_model3d_ui.mjs      (no server, no world; esbuild from the workspace bundles the module)
 *
 * Exit 1 with the mismatch list, 0 when every case holds.
 *
 * THE CASES, DERIVED BY HAND
 * [1] model3dHead({pending, hasModel, rigError, standIn, stale}) — first match wins:
 *       pending (even with nothing stored)          → blue "Building now"
 *       no model                                    → yellow "Not built yet"
 *       rig failed (also when stale and a stand-in) → red "Rig failed"
 *       a stand-in served (also when stale)         → yellow "Showing a stand-in"
 *       stale                                       → yellow "Outdated"
 *       none of these                               → green "Up to date"
 * [2] localAction("Analyze") → "Analyze — local, no hub job" (the cost words of a single step that runs on this server).
 * [3] hasExtensionSection(st) — the 3D tab's Extension bones sub-tab (and its Preview state), Ruling A66: only off
 *     the base-body pipeline and only with groups on the served model (on the pipeline both live in the Base body tab):
 *       pipeline {…}, groups [G]  → false;  pipeline null, groups [] → false;  pipeline null, groups [G] → true;
 *       {} (not loaded yet)       → false.
 * [4] Source greps: FieldModel3D renders the flow head (StepLight + model3dHead), FigureBuildButton on the pipeline,
 *     the viewer with `builtAt`, no "Build current outfit" (POST model3d/build-current is the Figure tab's Build,
 *     Ruling A13b — the head's Build is that one), no <details> (Advanced is a sub-tab), its parts portalled into
 *     Model3DDetails' targets; Model3DSidePanels has Model3DDetails with SubTabs, its Extension bones tab only through
 *     hasExtensionSection, no pipeline pointer ("Set on the base body") and no outfit-only line any more;
 *     the character template has the one `model3d_details` section instead of the three side sections;
 *     CollisionScales' two reset buttons have distinct labels ("Discard changes", "Reset to default").
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
  const dir = await mkdtemp(join(tmpdir(), 'check-model3d-ui-'));
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
const src = (p) => readFileSync(join(ROOT, p), 'utf8');

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/model3dModel.ts'));

// [1]
const none = { pending: false, hasModel: true, rigError: false, standIn: false, stale: false };
const head = (x) => { const h = m.model3dHead({ ...none, ...x }); return [h.light, h.words]; };
check('[1] pending', head({ pending: true, hasModel: false }), ['blue', 'Building now']);
check('[1] no model', head({ hasModel: false }), ['yellow', 'Not built yet']);
check('[1] rig failed', head({ rigError: true, standIn: true, stale: true }), ['red', 'Rig failed']);
check('[1] stand-in', head({ standIn: true, stale: true }), ['yellow', 'Showing a stand-in']);
check('[1] stale', head({ stale: true }), ['yellow', 'Outdated']);
check('[1] up to date', head({}), ['green', 'Up to date']);

// [2]
check('[2] local action', m.localAction('Analyze'), 'Analyze — local, no hub job');

// [3]
const G = { id: 'G' };
check('[3] extension section', [m.hasExtensionSection({ pipeline: { rerig_source: true }, extension_groups: [G] }),
  m.hasExtensionSection({ pipeline: null, extension_groups: [] }), m.hasExtensionSection({ pipeline: null, extension_groups: [G] }),
  m.hasExtensionSection({})], [false, false, true, false]);

// [4]
const fm = src('frontend/src/tabs/characters/FieldModel3D.tsx');
const side = src('frontend/src/tabs/characters/Model3DSidePanels.tsx');
const viewer = (fm.match(/<Model3DViewer[\s\S]*?\/>/) || [''])[0];
check('[4] FieldModel3D: flow head, the Build, Built <time>', [/<StepLight light=\{head\.light\}/.test(fm),
  /model3dHead\(/.test(fm), /<FigureBuildButton\b/.test(fm), /builtAt=\{model\.created_at\}/.test(viewer)],
  [true, true, true, true]);
check('[4] FieldModel3D: no duplicate Build, no <details>', [/build-current/.test(fm), /<details>/.test(fm)],
  [false, false]);
check('[4] FieldModel3D: parts in the panel', [/createPortal\(stepsPart, targets\.steps\)/.test(fm),
  /createPortal\(modelPart, targets\.model\)/.test(fm), /createPortal\(advancedPart, targets\.advanced\)/.test(fm)],
  [true, true, true]);
check('[4] Model3DDetails: sub-tabs, Extension bones off the pipeline only', [/export function Model3DDetails\b/.test(side),
  /<SubTabs\b/.test(side), /hasExtensionSection\(panel\.st\)/.test(side), /Set on the base body|outfitOnly/.test(side)],
[true, true, true, false]);
const tpl = JSON.parse(src('shared/templates/character/base-character.json'));
const specials = tpl.sections.filter((s) => s.column === 25 && s.special).map((s) => s.special);
check('[4] template: one details section', specials, ['model3d_details']);
const cs = src('frontend/src/tabs/characters/CollisionScales.tsx');
check('[4] CollisionScales: distinct reset labels', [/t\('Discard changes'\)/.test(cs), /t\('Reset to default'\)/.test(cs),
  /t\('Revert'\)/.test(cs)], [true, true, false]);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
