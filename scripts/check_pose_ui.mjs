#!/usr/bin/env node
/**
 * Check of Task UI5 for the Pose tab (the user's tab checklist; plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md)
 * — the pure helpers of `frontend/src/tabs/characters/poseModel.ts` and the wiring by source greps.
 *
 * Usage:  node scripts/check_pose_ui.mjs      (no server, no world; esbuild from the workspace bundles the module)
 *
 * Exit 1 with the mismatch list, 0 when every case holds.
 *
 * THE CASES, DERIVED BY HAND
 * [1] viewRow(info, draft, running) — one dressed view as a step:
 *       running (whatever is stored)                        → blue "Rendering", no reason
 *       nothing stored                                      → yellow "Not rendered yet"
 *       view current, draft current                         → green "Current", no reason
 *       view current, draft stale {reason "R", action "A"}  → yellow "Outdated", reason "R", mouse-over "R\nA"
 *       view stale "V", draft stale "D"                     → the view's reason first: "V"
 *       view current with warning "W"                       → yellow "Kept with a warning", reason "W"
 *       view stale "V" (no action) with warning "W"         → yellow "Outdated", reason "V", mouse-over "V\nW"
 *       view stale without a reason                         → reason "Made from older data"
 * [2] outfitRow(outfit, staleText, proofLine):
 *       running → blue "Building now" (its warnings not shown while it runs); failed "boom" → red "Failed", "boom";
 *       stale → yellow "Outdated", the staleText "S"; missing → yellow "Not built yet", "The Build makes it";
 *       ready → green "Ready", the proofLine "P" as reason and mouse-over; ready with warnings [w1, w2] → yellow
 *       "Ready — with warnings", reason "w1", mouse-over "w1\nw2".
 * [3] poseHead(lights, buildRunning):
 *       ([green, green], false) → green "Up to date"; ([green, yellow], false) → yellow "1 step due";
 *       ([yellow, yellow, green], false) → yellow "2 steps due"; ([yellow, red], false) → red "A step failed";
 *       ([red], true) → blue "Building now" (a running Build wins); ([green, blue], false) → blue; ([grey], false) →
 *       green "Up to date" (grey is nothing to do); ([], false) → green.
 * [4] renderAllLabel(views) — off the pipeline the main view plus every switched-on extra view:
 *       0 → "Render all views — 1 image job"; 2 → "Render all views — 3 image jobs"; -1 (nonsense) → "… — 1 image job".
 * [5] Source greps: FieldPose renders FigureBuildButton (the Figure tab's Build, Ruling A13b — no model3d/generate,
 *     no "Rebuild outfit model"), StepRowView, SubTabs and the viewer with `builtAt` and without `sideToolbar`;
 *     FieldModelRefs has the `steps` layout (no `stack` layout left), labels each view's Regenerate with
 *     singleAction('view', 1, t) and keeps the face view's switch on the pipeline next to the link to the Base
 *     body tab; BaseBodyOutfitStatus.tsx is gone (folded into FieldPose).
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
  const dir = await mkdtemp(join(tmpdir(), 'check-pose-ui-'));
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

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/poseModel.ts'));

// [1]
const cur = { state: 'current' };
const tile = (freshness = cur, extra = {}) => ({ filename: 'f.png', freshness, ...extra });
const vr = (info, draft, running = false) => { const r = m.viewRow(info, draft, running); return [r.light, r.state, r.reason]; };
check('[1] running', vr(tile(), tile(), true), ['blue', 'Rendering', '']);
check('[1] nothing stored', vr(null, null), ['yellow', 'Not rendered yet', '']);
check('[1] current', vr(tile(), tile()), ['green', 'Current', '']);
const draftStale = m.viewRow(tile(), tile({ state: 'stale', reason: 'R', action: 'A' }), false);
check('[1] draft stale', [draftStale.light, draftStale.state, draftStale.reason, draftStale.detail],
  ['yellow', 'Outdated', 'R', 'R\nA']);
check('[1] the view first', vr(tile({ state: 'stale', reason: 'V' }), tile({ state: 'stale', reason: 'D' }))[2], 'V');
check('[1] warning', vr(tile(cur, { warning: 'W' }), null), ['yellow', 'Kept with a warning', 'W']);
check('[1] stale + warning', m.viewRow(tile({ state: 'stale', reason: 'V' }, { warning: 'W' }), null, false).detail, 'V\nW');
check('[1] stale without a reason', vr(tile({ state: 'stale' }), null)[2], 'Made from older data');

// [2]
const o = (status, extra = {}) => ({ status, error: '', warnings: [], ...extra });
const or = (x) => { const r = m.outfitRow(x, 'S', 'P'); return [r.light, r.state, r.reason, r.detail]; };
check('[2] running', or(o('running', { warnings: ['w'] })), ['blue', 'Building now', '', '']);
check('[2] failed', or(o('failed', { error: 'boom' })), ['red', 'Failed', 'boom', 'boom']);
check('[2] stale', or(o('stale')).slice(0, 3), ['yellow', 'Outdated', 'S']);
check('[2] missing', or(o('missing')).slice(0, 3), ['yellow', 'Not built yet', 'The Build makes it']);
check('[2] ready', or(o('ready')), ['green', 'Ready', 'P', 'P']);
check('[2] ready with warnings', or(o('ready', { warnings: ['w1', 'w2'] })), ['yellow', 'Ready — with warnings', 'w1', 'w1\nw2']);

// [3]
const ph = (l, run = false) => { const h = m.poseHead(l, run); return [h.light, h.words]; };
check('[3] up to date', ph(['green', 'green']), ['green', 'Up to date']);
check('[3] 1 due', ph(['green', 'yellow']), ['yellow', '1 step due']);
check('[3] 2 due', ph(['yellow', 'yellow', 'green']), ['yellow', '2 steps due']);
check('[3] failed', ph(['yellow', 'red']), ['red', 'A step failed']);
check('[3] a Build runs', ph(['red'], true), ['blue', 'Building now']);
check('[3] a row runs', ph(['green', 'blue'])[0], 'blue');
check('[3] grey / empty', [ph(['grey']), ph([])], [['green', 'Up to date'], ['green', 'Up to date']]);

// [4]
check('[4] render all', [m.renderAllLabel(0), m.renderAllLabel(2), m.renderAllLabel(-1)],
  ['Render all views — 1 image job', 'Render all views — 3 image jobs', 'Render all views — 1 image job']);

// [5]
const pose = src('frontend/src/tabs/characters/FieldPose.tsx');
const refs = src('frontend/src/tabs/characters/FieldModelRefs.tsx');
const viewer = (pose.match(/<Model3DViewer[\s\S]*?\/>/) || [''])[0];
check('[5] FieldPose: the Build, rows, sub-tabs', [/<FigureBuildButton\b/.test(pose), /model3d\/generate/.test(pose),
  /Rebuild outfit model/.test(pose), /<StepRowView\b/.test(pose), /<SubTabs\b/.test(pose)], [true, false, false, true, true]);
check('[5] FieldPose viewer: builtAt, no side toolbar', [/builtAt=\{model\.created_at\}/.test(viewer),
  /sideToolbar/.test(viewer)], [true, false]);
check('[5] FieldModelRefs: steps layout, no stack layout', [/layout === 'steps'/.test(refs), /'stack'/.test(refs)],
  [true, false]);
check('[5] FieldModelRefs: Regenerate names its cost', /\{singleAction\('view', 1, t\)\}/.test(refs), true);
check('[5] face view on the pipeline: link + its switch', [/onClick=\{onOpenBaseBody\}/.test(refs),
  /setView\('face', e\.target\.checked\)/.test(refs)], [true, true]);
check('[5] BaseBodyOutfitStatus folded into FieldPose',
  existsSync(join(ROOT, 'frontend/src/tabs/characters/BaseBodyOutfitStatus.tsx')), false);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
