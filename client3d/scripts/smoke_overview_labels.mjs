#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/overview_labels.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_overview_labels.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

async function load(entry, name) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      entryPoints: [join(ROOT, entry)],
      bundle: true, platform: 'node', format: 'esm', write: false, outfile: join(dir, name),
    });
    const file = join(dir, name);
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const tags = await load('client3d/src/scene/nameTags.ts', 'tags.mjs');
const view = await load('client3d/src/game/openView.ts', 'view.mjs');

let extra = 0;
let extraCount = 7;
const constant = (label, ok) => {
  console.log(`${ok ? '  ok  ' : 'FAIL'} ${label}`);
  if (!ok) extra += 1;
};
constant('TAG_MAX_CAM_DIST is 55', tags.TAG_MAX_CAM_DIST === 55);
constant('TAG_ABOVE_HEAD_M is 0.45', tags.TAG_ABOVE_HEAD_M === 0.45);
constant('TAG_PORTRAIT_Y is -0.15', tags.TAG_PORTRAIT_Y === -0.15);
constant('LOCATION_LABEL_LIFT_M is 2.2', tags.LOCATION_LABEL_LIFT_M === 2.2);
constant('CLOSE_CAM_DIST is 60', view.CLOSE_CAM_DIST === 60);
constant('CLOSE_TARGET_FOOTPRINTS is 3', view.CLOSE_TARGET_FOOTPRINTS === 3);
constant('CLOSE_TARGET_MIN_M is 12', view.CLOSE_TARGET_MIN_M === 12);

const b0 = tags.tagBadges(null);
constant('tagBadges(null) is empty', b0.text === '' && b0.title === '' && b0.key === '\u0001');
constant('tagBadges([]) is empty', tags.tagBadges([]).key === '\u0001');
const b1 = tags.tagBadges([{ icon: '🔒', title: 'Private' }]);
constant('tagBadges one', b1.text === '🔒' && b1.title === 'Private');
const b2 = tags.tagBadges([{ icon: '🔒', title: 'A' }, { icon: '⭐', title: '' }]);
constant('tagBadges two, empty title dropped', b2.text === '🔒⭐' && b2.title === 'A');
constant('tagBadges key follows the title',
  tags.tagBadges([{ icon: '🔒', title: 'Private (state: X)' }]).key !== b1.key);
extraCount += 5;

const { passed, failed } = runVectors(loadVectors('overview_labels'), {
  tagVisible: tags.tagVisible,
  tagTravelling: tags.tagTravelling,
  tagName: tags.tagName,
  tagAnchorY: tags.tagAnchorY,
  locationLabelLift: tags.locationLabelLift,
  closeTargetDist: view.closeTargetDist,
  openViewShouldClose: view.openViewShouldClose,
});
console.log(failed + extra ? `\n${failed + extra} FAILED` : `\nall ok (${passed + extraCount})`);
process.exit(failed + extra ? 1 : 0);
