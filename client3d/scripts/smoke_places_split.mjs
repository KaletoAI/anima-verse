#!/usr/bin/env node
/**
 * NEW (NEU): places.ts is absent on a241a8aa, so this fails there.
 * Hand-derived oracles, with no ground sampler (ground = 0):
 * F1 building: [[-5,-4],[5,-4],[5,4],[-5,4]], pin (10,20), yaw 0,
 * no style: center (10,0,20), area 10*8 = 80, width max(10,8) = 10,
 * yaw 0, isBuilding true, height 4, label-y 4+2.2 = 6.2.
 * F2 building L: [[0,0],[20,0],[20,10],[10,10],[10,20],[0,20]],
 * pin (-30,40), yaw 90: center (-30,0,40), area 20*10+10*10 = 300,
 * width max(20,20) = 20, yaw PI/2 = 1.5707963267948966,
 * height 4, label-y 6.2.
 * F3 area: map3d.area_model true, no boundary, plan_width_m 30, no forest:
 * boundary null, polygonArea(null) = 0, width 30, isArea true,
 * height 0.3, no label. All numeric comparisons use tolerance 1e-9.
 * REGRESSION: compare all three with buildTile from a241a8aa.
 * c: labels belong to the place anchor and are shared with its tile.
 * c2: ground 0 -> 3, delta 3, anchor-y 3, label world-y 3+4+2.2 = 9.2
 * even without a resident; a resident center must be an independent copy.
 * c3: occlusion still hides and restores the label after it leaves tile.group.
 * d: the building-tier callback also keeps the persistent label height current.
 * NEU: during loading, heights 8 then 12 replace the initial 4 immediately.
 * A pin stands on the place's ground datum (pinY, 63ac8572) — the ground is 3
 * from c2 on: created between steps it has y 3+8+3.5 = 14.5, then 3+12+3.5 = 18.5.
 * A stale resident must not move a replacement place's pin.
 * d: isolation toggle 16 still hides resident labels on the separate anchor.
 * d: text guards prevent knowledge paths silently reverting to residents,
 * which would lose distant labels or entry offers once A-T4 evicts residents.
 */
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, transformSync } from 'esbuild';
import * as THREE from 'three';
const ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)));
globalThis.document = { createElement: () => ({ style: {}, setAttribute() {}, remove() {} }) };
async function load(old = false) {
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = old ? `export * from '${src}/tiles';` :
      `export * from '${src}/places'; export { buildTile, setWorldGround, applyTileOcclusion } from '${src}/tiles';`;
    const oldSource = old ? (await promisify(execFile)('git', ['show', 'a241a8aa:client3d/src/scene/tiles.ts'], { cwd: ROOT, encoding: 'utf8' })).stdout : null;
    const plugins = old ? [{ name: 'old-tiles', setup(b) {
      b.onLoad({ filter: /scene\/tiles\.ts$/ }, () => ({
        contents: transformSync(oldSource, { loader: 'ts', format: 'esm' }).code,
        loader: 'js',
      }));
    } }] : [];
    const out = await build({ stdin: { contents: transformSync(entry, { loader: 'ts', format: 'esm' }).code, resolveDir: dir }, bundle: true, platform: 'node', format: 'esm', write: false, external: ['three', 'three/*'], plugins, tsconfig: join(ROOT, 'client3d/tsconfig.json') });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.outputFiles[0].text);
    return await import(file);
  } finally { await rm(dir, { recursive: true, force: true }); }
}
const current = await load();
const old = await load(true);
const fixtures = [
  { id: 'f1', name: 'F1', pos_x: 10, pos_z: 20, yaw_deg: 0, boundary: [[-5,-4],[5,-4],[5,4],[-5,4]], rooms: [] },
  { id: 'f2', name: 'F2', pos_x: -30, pos_z: 40, yaw_deg: 90, boundary: [[0,0],[20,0],[20,10],[10,10],[10,20],[0,20]], rooms: [] },
  { id: 'f3', name: 'F3', pos_x: 0, pos_z: 0, plan_width_m: 30, map3d: { area_model: true }, rooms: [] },
];
const expected = [[10,0,20,80,10,0,4,6.2], [-30,0,40,300,20,Math.PI/2,4,6.2], [0,0,0,0,30,0,0.3,undefined]];
const values = p => [...p.center.toArray(), p.area, p.width, p.yaw, p.height, p.labelObj?.position.y];
for (const [i, loc] of fixtures.entries()) {
  const p = current.buildPlace(loc), t = current.buildTile(p), before = old.buildTile(loc);
  for (const [j, v] of values(p).entries()) {
    if (v === undefined) assert.equal(v, expected[i][j]);
    else assert.ok(Math.abs(v - expected[i][j]) < 1e-9);
  }
  assert.deepEqual(values(p), values(before));
  for (const key of ['boundary', 'isBuilding', 'isArea', 'natureSite']) assert.deepEqual(p[key], before[key]);
  assert.equal(t.loc, p.loc); assert.equal(t.boundary, p.boundary);
  assert.deepEqual(p.anchor.position.toArray(), p.center.toArray());
  assert.equal(p.anchor.rotation.y, p.yaw);
  for (const key of ['loc', 'boundary', 'area', 'width', 'yaw', 'height', 'isBuilding', 'isArea', 'natureSite']) assert.deepEqual(t[key], p[key]);
  assert.equal(p.isArea, i === 2); assert.equal(p.isBuilding, i !== 2);
  assert.equal(t.labelObj, p.labelObj);
  if (p.labelObj) assert.equal(p.labelObj.parent, p.anchor);
  else assert.equal(t.labelObj, undefined);
  assert.notEqual(t.center, p.center);
  if (i === 2) assert.equal(p.boundary, null);
}
current.setWorldGround(() => 0);
const p = current.buildPlace(fixtures[0]);
current.setWorldGround(() => 3);
assert.equal(current.redatumPlace(p), 3);
assert.equal(p.anchor.position.y, 3);
assert.ok(Math.abs(p.labelObj.getWorldPosition(new THREE.Vector3()).y - 9.2) < 1e-9);
const residentTile = current.buildTile(p);
current.applyTileOcclusion(residentTile, true, 1);
assert.equal(p.labelObj.visible, false, 'occluded resident keeps its persistent label hidden');
current.applyTileOcclusion(residentTile, false, 1);
assert.equal(p.labelObj.visible, true, 'revealed resident shows its label again');
const main = (await readFile(join(ROOT, 'client3d/src/main.ts'), 'utf8')).replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
// Module paths and the existing boot-stage string are not identifiers.
assert.doesNotMatch(main.replace(/(['"`])[^'"`]*\1/g, ''), /\btiles\b/);
const reveal = main.slice(main.indexOf('async function revealBatch'), main.indexOf('function dropPlace'));
assert.match(reveal, /!places\.has\(/);
const offer = main.slice(main.indexOf('function updateEnterOffer'), main.indexOf('async function enterOfferedLocation'));
assert.match(offer, /places\.values\(\)/);
assert.match(main, /setSceneModelTier\(tile, 'building', b, \(\) => \{[\s\S]*?residency\.get\(tile\.loc\.id\)\?\.tile !== tile[\s\S]*?place\.height = tile\.height/);
// Exercise ensurePlace and the shared height binding used by the driver mount.
const start = main.indexOf('function shareTileHeight(');
const addAt = main.indexOf('function ensurePlace(');
const source = main.slice(start, main.indexOf('\n  }', addAt) + 4);
const testPlaces = new Map(), testResidency = new Map(), testPins = new Map();
// `placeLifecycles` is the per-place lifecycle token map ensurePlace stamps
// (A-T5 H5: an entry wait aborts when the place was removed or rediscovered).
const testLifecycles = new Map();
// shareTileHeight re-places a pin through the shared pinY (game/eventPins.ts,
// 63ac8572): the real function goes in, so the pin height below is the spec's.
const pinsSrc = await readFile(join(ROOT, 'client3d/src/game/eventPins.ts'), 'utf8');
const pinsModule = { exports: {} };
new Function('module', 'exports', transformSync(pinsSrc, { loader: 'ts', format: 'cjs' }).code)(
  pinsModule, pinsModule.exports);
const { pinY } = pinsModule.exports;
const bindings = new Function('buildPlace', 'footprintCentre', 'places', 'residency', 'eventPins', 'engine',
  'placeLifecycles', 'pinY',
  transformSync(source + '; return {ensurePlace, shareTileHeight};', { loader: 'ts' }).code)(
  current.buildPlace, () => true, testPlaces, testResidency, testPins,
  { scene: new THREE.Scene() }, testLifecycles, pinY);
const add = loc => {
  bindings.ensurePlace(loc);
  const place = testPlaces.get(loc.id);
  const tile = current.buildTile(place);
  bindings.shareTileHeight(tile, place);
  testResidency.set(loc.id, {tile});
};
add(fixtures[0]);
const loadingTile = testResidency.get('f1').tile;
loadingTile.height = 8;
assert.equal(testPlaces.get('f1').height, 8, 'shell height is visible before mount settles');
const eventPin = new THREE.Sprite();
eventPin.position.set(10, pinY(loadingTile.center.y, testPlaces.get('f1').height), 20);
testPins.set('f1', eventPin);
assert.equal(eventPin.position.y, 14.5);
loadingTile.height = 12;
assert.equal(testPlaces.get('f1').height, 12);
assert.deepEqual(eventPin.position.toArray(), [10, 18.5, 20]);
testPlaces.delete('f1');
add(fixtures[0]);
loadingTile.height = 20;
assert.equal(testPlaces.get('f1').height, 4);
assert.equal(eventPin.position.y, 18.5, 'stale resident cannot reposition the pin');
const drop = main.slice(main.indexOf('function dropPlace'), main.indexOf('function dropVanished'));
assert.match(drop, /places\.delete\(/); assert.match(drop, /driver\.drop\(/);
const debug = await readFile(join(ROOT, 'client3d/src/debug3d.ts'), 'utf8');
assert.match(debug, /if \(on\(16\)\)[\s\S]*?force\(tile\.group\)[\s\S]*?force\(tile\.labelObj\)/);
console.log('places split: F1-F3, old-code equality, labels, datum, loading heights, pins and text guards PASS');
