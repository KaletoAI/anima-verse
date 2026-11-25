#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/animal_vectors.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_animal_vectors.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { loadVectors, resolveArgs } from '../../shared/test-vectors/vectors.mjs';
import { runAnimalVectors } from './animalVectorDispatch.mjs';
let passed=0, failed=0;
for (const name of ['animal_legs', 'animal_gait']) {
  const r = await runAnimalVectors(name);
  console.log(`${name}: ${r.passed} ok, ${r.failed} failed`);
  passed+=r.passed; failed+=r.failed;
}
console.log(`Task 34 vectors: ${passed} ok, ${failed} failed`);
process.exitCode=failed ? 1 : 0;

// Exercise the actual Figure adapter and update branch, including parent space.
const root = fileURLToPath(new URL('../../', import.meta.url));
const dir = await mkdtemp(join(root, 'client3d/scripts/.smoke-animal-'));
let integration = 0;
const near = (actual, expected) => {
  assert.ok(Math.abs(actual-expected) <= 1e-9, `${actual} != ${expected}`); integration++;
};
try {
  const bundle = await build({stdin: {contents: `export { Figure } from './client3d/src/scene/figures.ts';`,
    resolveDir: root, loader: 'ts'}, bundle: true, platform: 'node', format: 'esm',
    write: false, external: ['three', 'three/*']});
  const path = join(dir, 'figure.mjs');
  await writeFile(path, bundle.outputFiles[0].text);
  const { Figure } = await import(pathToFileURL(path));
  const file = loadVectors('animal_legs');
  const [data, box] = resolveArgs(file.cases.find(c => c.label === '[4a] quadruped Z long').args, file.fixtures);
  function makeFigure(withLegs) {
    const template = new THREE.Group();
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(box.min.x,box.min.y,box.min.z),
      new THREE.Vector3(box.max.x,box.max.y,box.max.z)]);
    template.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()));
    if (withLegs) {
      const bones = data.map(b => {const bone = new THREE.Bone(); bone.name=b.name; return bone;});
      data.forEach((b,i) => {
        bones[i].position.copy(b.position);
        if (b.parent !== null) bones[i].position.sub(data[b.parent].position);
        (b.parent === null ? template : bones[b.parent]).add(bones[i]);
      });
    }
    const f = new Figure({name:'task34',template,clips:[],scale:1,height:4,
      assignOnly:true,noClips:true,tier:'full',libraryFits:false});
    geometry.dispose();
    template.children[0].material.dispose();
    return f;
  }
  const f = makeFigure(true), inst=f.root.children[0];
  near(f.legs.length,4);
  f.currentKind='walk'; f.walkPhase=Math.PI/2; f.update(0);
  near(f.legs[0].bone.quaternion.angleTo(f.legs[0].bindQuat),.45);
  near(inst.position.y,.08); near(inst.scale.x,1);
  f.currentKind='run'; f.walkPhase=1; f.update(.5); near(f.walkPhase,6.5);
  f.currentKind='idle'; f.idlePhase=0; f.update(0);
  for (const leg of f.legs) near(leg.bone.quaternion.angleTo(leg.bindQuat),0);
  near(inst.position.y,0); near(inst.scale.x,1);
  const parent = f.legs[0].bone.parent;
  parent.rotation.y=Math.PI/2; f.root.updateMatrixWorld(true);
  // Same parent-frame operation as the adapter, tested on a rotated skeleton
  // by reconstructing a Figure so detection actually sees this parent frame.
  const rotated = new Figure({name:'task34-rotated',template:inst,clips:[],scale:1,height:4,
    assignOnly:true,noClips:true,tier:'full',libraryFits:false});
  const axis = rotated.legs[0].axis.clone().applyQuaternion(
    rotated.legs[0].bone.parent.getWorldQuaternion(new THREE.Quaternion()));
  near(axis.x,1); near(axis.y,0); near(axis.z,0);
  const empty=makeFigure(false);
  empty.currentKind='walk'; empty.walkPhase=1; empty.idlePhase=0; empty.update(.5);
  near(empty.walkPhase,1); near(empty.idlePhase,.8);
  console.log(`Task 34 Figure integration: ${integration} ok, 0 failed`);
} finally { await rm(dir,{recursive:true,force:true}); }
