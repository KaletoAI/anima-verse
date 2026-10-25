#!/usr/bin/env node
/**
 * Smoke check for the labels over the world map and the overview auto-close of
 * the open view — client3d/src/scene/nameTags.ts and client3d/src/game/openView.ts.
 *
 * Usage:  node client3d/scripts/smoke_overview_labels.mjs
 *
 * Hand derivations (cases in shared/test-vectors/overview_labels.json, shared
 * with the native client's C# tests):
 * [V] tagVisible(camDist, hidden, ownFirstPerson) = !hidden && !own && camDist < 55:
 *     40 and 54.999 -> true; 55 is not < 55 -> false; 60 -> false; a hidden figure
 *     at 10 m -> false; the camera's own first-person body at 1 m -> false.
 * [T] tagTravelling(travel) = !!travel && !travel.starts_in_s: null -> false;
 *     starts_in_s 0 and null are falsy -> true; 12 is truthy (the start lies ahead)
 *     -> false; an empty object is truthy and has no starts_in_s -> true.
 * [N] tagName(name, travel): not under way -> the name as it is; under way ->
 *     "🚶" + (eta_hhmm truthy ? " " + eta_hhmm : "") + " " + name:
 *     {0, "14:30"} -> "🚶 14:30 Ada"; {eta "07:05"} -> "🚶 07:05 Ada";
 *     {12, "14:30"} -> "Ada"; eta null or "" (falsy) -> "🚶 Cleo Marsh".
 * [A] tagAnchorY(h) = h + 0.45 over a model, -0.15 for a portrait (null):
 *     1.6 -> 2.05; 1.8 -> 2.25; null -> -0.15.
 * [L] locationLabelLift(h) = h + 2.2 (the label above the place's ground datum):
 *     4 -> 6.2; 0.6 -> 2.8; 3 -> 5.2.
 * [D] closeTargetDist(w) = max(12, 3·w): 2 -> 6 < 12 -> 12; 4 -> 12; 10 -> 30;
 *     0 -> 12.
 * [C] openViewShouldClose(camDist, tx, tz, cx, cz, w) = camDist > 60 ||
 *     hypot(tx - cx, tz - cz) > closeTargetDist(w), both strict:
 *     centre (10, -5), width 10 -> limit 30. Camera exactly 60 -> stays;
 *     60.0001 -> closes. Target (28, 19): offset (18, 24) -> hypot 30 exactly
 *     (3-4-5 x 6) -> not > 30 -> stays. Target (28, 19.5): offset (18, 24.5) ->
 *     sqrt(324 + 600.25) = sqrt(924.25) = 30.4015... -> closes. Target (-15, -5):
 *     offset 25 <= 30 with camera 59 <= 60 -> stays. A 1 m shrine at the origin:
 *     3·1 = 3 < 12 -> limit 12; offset (12, 0) -> stays, (12.01, 0) -> closes.
 *     Width 8 at (-40, 100) -> limit max(12, 24) = 24; target (-40, 76) is 24 off
 *     -> stays; (-40, 75.5) is 24.5 off -> closes.
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

const { passed, failed } = runVectors(loadVectors('overview_labels'), {
  tagVisible: tags.tagVisible,
  tagTravelling: tags.tagTravelling,
  tagName: tags.tagName,
  tagAnchorY: tags.tagAnchorY,
  locationLabelLift: tags.locationLabelLift,
  closeTargetDist: view.closeTargetDist,
  openViewShouldClose: view.openViewShouldClose,
});
console.log(failed + extra ? `\n${failed + extra} FAILED` : `\nall ok (${passed + 7})`);
process.exit(failed + extra ? 1 : 0);
