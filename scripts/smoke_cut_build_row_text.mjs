#!/usr/bin/env node
/**
 * Smoke: the figure row's line of a FAILED texture from cut says exactly what the next Build does
 * (frontend/src/tabs/characters/figureModel.ts, `templateCutLine` → `cutBuildFailedLine`; review 2026-11-21: the row
 * said "— Build retries it" while a manual Build could not retry a failed cut).
 *
 * Usage:  node scripts/smoke_cut_build_row_text.mjs      (no server; esbuild from the workspace bundles the module)
 *
 * THE CASES, DERIVED BY HAND (`CutBuild.retry` is `garment_cut_texture.build_state`'s):
 * [1] retry "cut", jobs 2, reason "Cutting the pattern failed: boom" → "Texture from cut failed: Cutting the pattern
 *     failed: boom — an automatic Build skips it; a click on Build cuts the pattern again, then makes the texture
 *     (+2 image jobs)".
 * [2] retry "jobs", jobs 1, reason "Front: coverage 0.79 < 0.97" → "… — an automatic Build skips it; a click on Build
 *     renders only the jobs that did not pass (+1 image jobs)".
 * [3] retry "jobs", jobs 0 → "… — an automatic Build skips it; a click on Build composes it again from the answers
 *     that passed (CPU, 0 image jobs)".
 * [4] retry "" (no item picture), reason "The item has no picture" → "Texture from cut failed: The item has no
 *     picture" — no promise of a retry. A row without `retry` (an old server) reads the same.
 * [5] templateCutLine of a template row with no ready drape and that `cut_build` → the same line as [1]; "due" with
 *     jobs 1 (a plain back: upscale 0, front 1, back 0) → "Texture: projection — the next Build makes the cut texture
 *     (+1 image jobs)".
 * [6] The old text "— Build retries it" is gone from the module.
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
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
  const dir = await mkdtemp(join(tmpdir(), 'smoke-cut-build-row-'));
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

const SRC = join(ROOT, 'frontend/src/tabs/characters/figureModel.ts');
const f = await loadBundled(SRC);
const b = (over) => ({ state: 'failed', reason: '', jobs: 0, estimate: false, step: '', ...over });

const cut = b({ retry: 'cut', jobs: 2, estimate: true, reason: 'Cutting the pattern failed: boom' });
const line1 = 'Texture from cut failed: Cutting the pattern failed: boom — an automatic Build skips it; a click on '
  + 'Build cuts the pattern again, then makes the texture (+2 image jobs)';
check('[1] a failed cut', f.cutBuildFailedLine(cut), line1);
check('[2] failed jobs', f.cutBuildFailedLine(b({ retry: 'jobs', jobs: 1, reason: 'Front: coverage 0.79 < 0.97' })),
  'Texture from cut failed: Front: coverage 0.79 < 0.97 — an automatic Build skips it; a click on Build renders '
  + 'only the jobs that did not pass (+1 image jobs)');
check('[3] nothing to render again', f.cutBuildFailedLine(b({ retry: 'jobs', jobs: 0, reason: 'Back: x' })),
  'Texture from cut failed: Back: x — an automatic Build skips it; a click on Build composes it again from the '
  + 'answers that passed (CPU, 0 image jobs)');
check('[4] nothing to re-run', f.cutBuildFailedLine(b({ retry: '', reason: 'The item has no picture' })),
  'Texture from cut failed: The item has no picture');
check('[4] an old row without retry', f.cutBuildFailedLine(b({ reason: 'The item has no picture' })),
  'Texture from cut failed: The item has no picture');
check('[5] templateCutLine, failed', f.templateCutLine({ state: 'missing', cut_build: cut }), line1);
check('[5] templateCutLine, due 1 (plain back)', f.templateCutLine({ state: 'missing', cut_build: b({ state: 'due', jobs: 1 }) }),
  'Texture: projection — the next Build makes the cut texture (+1 image jobs)');
check('[6] the old promise is gone', (await readFile(SRC, 'utf8')).includes('Build retries it'), false);

if (failures.length) {
  console.error(`FAILED (${failures.length}):\n  ` + failures.join('\n  '));
  process.exit(1);
}
console.log('ALL OK');
