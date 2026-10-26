#!/usr/bin/env node
/** Prop water, spec §§8–9. Usage: node client3d/scripts/smoke_prop_water.mjs
 * Hand derivations (all vector expectations written by hand):
 * [1] SPECS: pool outline [0..4]², hole [1..2]², y=1.5, bed=0,
 * threshold 1; tub [3..5]², y=2, bed=1.5, threshold 1.
 * (0.5,0.5) is pool only; (1.5,1.5) is in the hole -> null;
 * (3.5,3.5) overlaps and 2>1.5 selects tub; (6,6) is outside -> null.
 * (0,0) belongs to outline -> pool; (1,1.5) belongs to hole ring -> null.
 * Hits retain y, bed_y and swim_from_m from the winning region.
 * [2] Lift 3: pool y=1.5+3=4.5, bed=0+3=3; tub y=2+3=5,
 * bed=1.5+3=4.5. Depth remains 1.5 or 0.5 and threshold stays 1.
 * The original five points still give pool, null, tub, null, pool.
 * [3] Pool point containment: (0.5,0.5) true; hole (1.5,1.5)
 * false; outside (6,6) false, independent of heights.
 * [4] DRY is the built-scope word: walk_run, sinks {move:0,idle:0},
 * water null, written out because groundWaterLevel(10,'built')=null.
 * Prop water starts with swim, sinks {move:0.35,idle:1.3}, water=y.
 * wadeGate compares y-groundY >= threshold: with groundY=0,
 * 1.5-0=1.5>=1 swims (water 1.5); 0.5-0=0.5<1 wades
 * (walk_run, sinks 0/0, water null); 1-0=1>=1 swims (water 1).
 * Null region leaves DRY unchanged: no mirror means no gate.
 * Region groundY=0 overrides argument 0.01: depth 1-0=1>=1,
 * hence swim, sinks 0.35/1.3, water 1 (not depth 0.99).
 * [5] Built suppresses level 10 -> null; wilderness (a walk.ts scope)
 * retains 10; absent level null stays null in wilderness.
 * [6] Carry max(bed,mirror): max(0,1.5)=1.5; max(2,1.5)=2;
 * no region leaves bed 0.7 unchanged.
 * JSON adapter: waterRegionAt(specs,x,z,lift=0) wraps numeric lift
 * as () => lift; the C# consumer mirrors this adapter.
 * Local geometry: triangle (0,0),(2,0),(0,3) maps identically to XZ
 * with +Y normals, area 2*3/2=3 m²; pool area 4*4-1*1=15 m².
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build, transform } from 'esbuild';
import * as THREE from 'three';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

async function load(path) {
  const result = await build({ entryPoints: [path], bundle: true, write: false,
    platform: 'node', format: 'esm' });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const math = await load('client3d/src/scene/propWaterMath.ts');
const walk = await load('client3d/src/game/walk.ts');
const { buildPropWater } = await load('packages/scene-render/src/propWater.ts');
const vectors = loadVectors('prop_water');
const { failed } = runVectors(vectors, {
  waterRegionAt: (specs, x, z, lift = 0) => math.waterRegionAt(specs, x, z, () => lift),
  pointInRegion: math.pointInRegion,
  propWaterWord: walk.propWaterWord,
  propWaterCarry: walk.propWaterCarry,
  groundWaterLevel: walk.groundWaterLevel,
});
assert.equal(failed, 0, 'shared prop water vectors');
// Canvas pixels are the browser boundary; geometry and materials remain real Three.js.
globalThis.document = { createElement: () => ({ getContext: () => ({
  fillRect() {}, createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
  putImageData() {},
}) }) };
const region = { outline: [[0,0],[2,0],[0,3]], holes: [], y: 1.5,
  bed_y: 0, tint: '#3aa7c4', opacity: .55, swim_from_m: 1 };
const [mesh] = buildPropWater(THREE, { regions: [region] }, 3);
assert.equal(mesh.position.y, 4.5);
const pos = mesh.geometry.getAttribute('position');
const normal = mesh.geometry.getAttribute('normal');
for (let i = 0; i < normal.count; i++) assert.ok(normal.getY(i) > .999);
assert.ok(Array.from({length: pos.count}, (_, i) => [pos.getX(i), pos.getZ(i)])
  .some(([x,z]) => Math.abs(x) < 1e-6 && Math.abs(z - 3) < 1e-6));
const [twin] = buildPropWater(THREE, { regions: [region] }, 0);
assert.equal(mesh.material, twin.material, 'look cache shared across mounts');
assert.equal(mesh.material.depthWrite, false);
assert.equal(mesh.material.transparent, true);
assert.equal(mesh.material.opacity, .55);
let disposed = false;
mesh.material.addEventListener('dispose', () => { disposed = true; });
mesh.geometry.dispose();
assert.equal(disposed, false, 'mount geometry disposal preserves cached material');
twin.geometry.dispose();
const [holed] = buildPropWater(THREE, {regions: [{...region, ...vectors.fixtures.POOL}]}, 0);
const p = holed.geometry.getAttribute('position');
const idx = holed.geometry.index;
let area = 0;
for (let i = 0; i < idx.count; i += 3) {
  const a = new THREE.Vector3().fromBufferAttribute(p, idx.getX(i));
  const b = new THREE.Vector3().fromBufferAttribute(p, idx.getX(i+1));
  const c = new THREE.Vector3().fromBufferAttribute(p, idx.getX(i+2));
  area += b.sub(a).cross(c.sub(a)).length() / 2;
}
assert.ok(Math.abs(area - 15) < 1e-6);
holed.geometry.dispose();
// Run the placement's real relift funnel without network/model-loading setup.
const source = await readFile('client3d/src/scene/sceneRecipe.ts', 'utf8');
const start = source.indexOf('function reliftPlacement(');
const end = source.indexOf('\n/**', start);
const reliftCode = (await transform(source.slice(start, end), {loader: 'ts'})).code;
const { storeyGroundRelift } = await load('packages/scene-render/src/storeyGround.ts');
let terrainY = 7;
const owned = { geometries: new Set() };
const tags = new WeakMap();
const relift = new Function('THREE', 'buildPropWater', 'storeyGroundRelift',
  'tileToWorld', 'worldGroundSampler', 'ownedOf', 'ownedTag',
  `${reliftCode}; return reliftPlacement;`)(THREE, buildPropWater, storeyGroundRelift,
  (_tile, x, z) => ({x, z}), () => () => terrainY, () => owned, tags);
const tile = { center: {y: 4}, group: new THREE.Group() };
const rec = { spec: { role: 'prop', level: 0, anchor: [2,3], water: {regions: [region]} },
  layer: 'detail', lift: 0, object: new THREE.Group() };
assert.equal(relift(tile, rec), 3);
assert.equal(rec.waterMeshes[0].position.y, 4.5);
assert.equal(owned.geometries.size, 1);
terrainY = 9;
assert.equal(relift(tile, rec), 5);
assert.equal(rec.waterMeshes[0].position.y, 6.5);
assert.equal(owned.geometries.size, 1, 'relift reuses geometry');
const replacement = {...rec, object: new THREE.Group(), lift: 0};
assert.equal(relift(tile, replacement), 5);
assert.equal(rec.waterMeshes[0].position.y, 6.5, 'tier replacement does not apply lift twice');
const tag = tags.get(rec.waterMeshes[0]);
assert.deepEqual(tag.materials, [], 'cached materials excluded from mount ledger');
assert.deepEqual(tag.textures, []);
assert.ok(owned.geometries.has(tag.geometry));
// Layer teardown removes water nodes and frees only the owned geometry.
const dropStart = source.indexOf('function dropLayerModels(');
const dropEnd = source.indexOf('\nexport function unmountDetail', dropStart);
const dropCode = (await transform(source.slice(dropStart, dropEnd), {loader: 'ts'})).code;
let freed = 0;
tag.geometry.addEventListener('dispose', () => freed++);
const dropLayer = new Function('dropPlacementGhost', 'disposeSlotMaterials',
  'disposeSceneOwned', `${dropCode}; return dropLayerModels;`)(() => {}, () => {},
  () => { for (const geometry of owned.geometries) geometry.dispose(); });
tile.placedModels = [{...rec, object: null}];
const waterMesh = rec.waterMeshes[0];
dropLayer(tile, 'detail');
assert.equal(waterMesh.parent, null);
assert.equal(freed, 1);
assert.equal(disposed, false);
assert.equal(tile.placedModels.length, 0);
// World placements retain authored XZ; the live terrain adds only Y.
const { createWorldProps } = await load('client3d/src/scene/worldProps.ts');
let worldGround = 3;
const layer = createWorldProps(() => worldGround);
const row = {id: 'pool', prop_id: 'pool', x: 0, z: 0, variants: {},
  water: {regions: [region]} };
layer.sync([row], 'one');
assert.equal(layer.group.children.length, 1);
const worldMesh = layer.group.children[0];
assert.equal(worldMesh.position.y, 4.5);
assert.deepEqual(layer.waterAt(.1, .1), {y: 4.5, bed_y: 3, swim_from_m: 1});
worldGround = 5;
layer.redrape();
assert.equal(worldMesh.position.y, 6.5);
assert.deepEqual(layer.waterAt(.1, .1), {y: 6.5, bed_y: 5, swim_from_m: 1});
let worldFreed = 0, worldMaterialFreed = 0;
worldMesh.geometry.addEventListener('dispose', () => worldFreed++);
worldMesh.material.addEventListener('dispose', () => worldMaterialFreed++);
layer.tick(new THREE.Vector3(1000, 0, 1000));
assert.equal(worldMesh.visible, false);
layer.sync([], 'two');
assert.equal(worldFreed, 1);
assert.equal(worldMaterialFreed, 0);
assert.equal(layer.group.children.length, 0);
assert.equal(layer.waterAt(.1, .1), null);
layer.dispose();
console.log('PASS prop water vectors, built-scope wade/swim, carry, lift, geometry, holes and shared materials');
