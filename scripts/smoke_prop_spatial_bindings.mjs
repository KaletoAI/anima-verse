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
  const source = await readFile(new URL('../frontend/src/tabs/props/spatialBindings.ts', import.meta.url), 'utf8');
  const file = join(dir, 'spatial.mjs');
  await writeFile(file, ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText);
  const { removeBoundMarker, bindingProblems, accessWorldPoint, accessLocalPoint } = await import(`file://${file}`);
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
