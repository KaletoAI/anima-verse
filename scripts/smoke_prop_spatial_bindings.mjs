/** Spatial authoring consumer regressions; intentionally run by the controller. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const dir = await mkdtemp(join(tmpdir(), 'prop-spatial-'));
try {
  const canonicalSource = await readFile(new URL('../packages/scene-render/src/placeTransform.ts', import.meta.url), 'utf8');
  const canonicalFile = join(dir, 'placeTransform.mjs');
  const transpile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
  await writeFile(canonicalFile, transpile(canonicalSource));
  const source = await readFile(new URL('../frontend/src/tabs/props/spatialBindings.ts', import.meta.url), 'utf8');
  const file = join(dir, 'spatial.mjs');
  await writeFile(file, transpile(source).replace('../../../../packages/scene-render/src/placeTransform', './placeTransform.mjs'));
  const { removeBoundMarker, bindingProblems, accessWorldPoint, accessLocalPoint, propMetresPerUnit } = await import(`file://${file}`);
  const { placeTransform } = await import(`file://${canonicalFile}`);
  const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);
  const dimensions = { width_m: 2, depth_m: 1.5, height_m: 1 };
  const cases = [
    { bbox: [4, 4, 4], rotation: { y: 45 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { y: 45 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { x: 36, y: 127, z: -58 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { x: -45, y: -135, z: -223 }, expected: .5 },
    { bbox: [4, 2, 1], rotation: { x: 91, y: -271, z: 179 }, expected: .5 },
  ];
  for (const { bbox, rotation, expected } of cases) {
    const scale = propMetresPerUnit(bbox, dimensions, rotation);
    near(scale, expected);
    const placement = placeTransform({ role: 'prop', id: 'regression', variants: {}, level: 0,
      fix_euler: { x: 0, y: 0, z: 0, ...rotation }, yaw_deg: 0, measure: 'xyz',
      max_m: 2, anchor: [0, 0], bottom_y: 0 }, [{ min: [0, 0, 0], max: bbox }]);
    near(scale, placement.outerScale);
    const frame = { centreX: 4, centreZ: -3, groundY: -2, unitsPerMetre: 1 / scale };
    const access = { x: -4, z: 5, yaw: 90 };
    const rendered = accessWorldPoint(access, frame);
    near((rendered[0] - frame.centreX) * placement.outerScale, access.x);
    near((rendered[2] - frame.centreZ) * placement.outerScale, access.z);
    assert.equal(rendered[1], frame.groundY);
    assert.deepEqual(accessLocalPoint(rendered, frame), { x: access.x, z: access.z });
    // Slots and a reference figure use metres / scale in the raw-unit viewer.
    near((.6 / scale) * placement.outerScale, .6);
    near((1.75 / scale) * placement.outerScale, 1.75);
    // Raw marker readback remains a raw-box fraction, not an exact-rotation AABB fraction.
    near(.75 * bbox[0] * scale, .75 * bbox[0] * placement.outerScale);
  }
  near(propMetresPerUnit([4, 4, 4], dimensions, { y: 45 }), .5);
  assert.ok(Math.abs(propMetresPerUnit([4, 4, 4], dimensions, { y: 45 }) - .5 / Math.sqrt(2)) > .1);
  const marker = id => ({ id, group: 'seat', at: [.5, 0, .5], capacity: 2 });
  const binding = { action_id: 'pair', variant_uid: 'v', supported: true, marker_ids: ['a', 'b'], access_points: { actor: { x: 0, z: 2, yaw: 180 }, partner: { x: 1, z: 2, yaw: 180 } }, validation: 'local_valid' };
  const variant = { uid: 'v', markers: [marker('a'), marker('b'), marker('c')], action_bindings: [binding] };
  // Removing without a decision must never emit an orphaning patch.
  assert.throws(() => removeBoundMarker(variant, 'a'), Error);
  assert.deepEqual(removeBoundMarker(variant, 'a', { replaceWith: 'b' }).action_bindings[0].marker_ids, ['b']);
  assert.deepEqual(removeBoundMarker(variant, 'a', { removeBindings: true }).action_bindings, []);
  assert.throws(() => removeBoundMarker(variant, 'a', { replaceWith: 'missing' }), Error);
  assert.deepEqual(variant.action_bindings[0].marker_ids, ['a', 'b']);
  assert.equal(removeBoundMarker(variant, 'a', { replaceWith: 'c' }).action_bindings[0].validation, 'repair_required');
  const action = { participants: 2 };
  assert.deepEqual(bindingProblems(binding, action, variant.markers, { width_m: 2, depth_m: 2 }), []);
  assert.ok(bindingProblems({ ...binding, access_points: { actor: binding.access_points.actor } }, action, variant.markers, { width_m: 2, depth_m: 2 }).length > 0);
  assert.ok(bindingProblems(binding, action, [{ ...marker('a'), capacity: 1 }, marker('b')], { width_m: 2, depth_m: 2 }).length > 0);
  // Blank numeric edits stay invalid instead of turning into a plausible zero.
  assert.ok(bindingProblems({ ...binding, access_points: { ...binding.access_points, actor: { x: NaN, z: 2, yaw: 180 } } }, action, variant.markers, { width_m: 2, depth_m: 2 }).length > 0);
  assert.ok(bindingProblems({ ...binding, access_points: { ...binding.access_points, actor: { x: 0, z: 1.2, yaw: 180 } } }, action, variant.markers, { width_m: 2, depth_m: 2 }).length > 0);
  const frame = { centreX: 4, centreZ: -3, groundY: -2, unitsPerMetre: 2 };
  // Outside-box access is preserved, ground is fixed, and inverse picking agrees.
  assert.deepEqual(accessWorldPoint({ x: -4, z: 5, yaw: 90 }, frame), [-4, -2, 7]);
  assert.deepEqual(accessLocalPoint([-4, -2, 7], frame), { x: -4, z: 5 });
  console.log('PASS: explicit atomic marker reference repair, pair/access constraints and ground coordinates');
} finally { await rm(dir, { recursive: true, force: true }); }
