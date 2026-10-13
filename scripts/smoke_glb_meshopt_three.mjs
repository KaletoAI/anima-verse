#!/usr/bin/env node
/**
 * Usage: node scripts/smoke_glb_meshopt_three.mjs [original.glb compressed.glb]
 *
 * With no arguments, build a temporary puppet delivery copy via the runner.
 * Hand-derived expectations: a lossless copy has exactly the same loaded
 * meshes, attributes, morph attributes and indices, with identical typed-array
 * bytes and metadata. Each skin has the same ordered bone names, inverse bind
 * matrices and local transforms. Parser associations retain node/mesh indices.
 * Node stubs image decoding only: geometry/rig data is decoded by real three
 * and MeshoptDecoder. Every production GLTFLoader constructor must be confined
 * to the app's single factory, with MeshoptDecoder configured there.
 */
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';

globalThis.self = globalThis;
globalThis.createImageBitmap = async () => ({ width: 1, height: 1, close() {} });
globalThis.ProgressEvent = class { constructor(type, values) { Object.assign(this, { type }, values); } };

const root = resolve(import.meta.dirname, '..');
function checkFactories() {
  for (const [app, factory] of [['client3d', 'scene/gltfLoader.ts'], ['frontend', 'lib/gltfLoader.ts']]) {
    const path = join(root, app, 'src', factory);
    const source = readFileSync(path, 'utf8');
    assert.match(source, /setMeshoptDecoder\(MeshoptDecoder\)/);
    assert.match(source, /three\/examples\/jsm\/libs\/meshopt_decoder.module.js/);
    function walk(dir) {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const p = join(dir, entry.name);
        if (entry.isDirectory()) walk(p);
        else if (/\.tsx?$/.test(p) && p !== path) {
          assert.doesNotMatch(readFileSync(p, 'utf8'), /new GLTFLoader\s*\(/, p);
        }
      }
    }
    walk(join(root, app, 'src'));
  }
}
async function load(path) {
  const bytes = readFileSync(path);
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
  return loader.parseAsync(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '');
}
function arrays(a, b, label) {
  assert.equal(a.constructor.name, b.constructor.name, label);
  assert.equal(a.length, b.length, label);
  assert.deepEqual(Buffer.from(a.buffer, a.byteOffset, a.byteLength), Buffer.from(b.buffer, b.byteOffset, b.byteLength), label);
}
function attribute(a, b, label) {
  for (const k of ['itemSize', 'count', 'normalized']) assert.equal(a[k], b[k], `${label}/${k}`);
  arrays(a.isInterleavedBufferAttribute ? a.data.array : a.array, b.isInterleavedBufferAttribute ? b.data.array : b.array, label);
}
function meshes(gltf) {
  const out = [];
  gltf.scene.traverse(o => { if (o.isMesh) out.push(o); });
  return out;
}

let tmp;
try {
  checkFactories();
  let [original, compressed] = process.argv.slice(2);
  if (!original) {
    tmp = mkdtempSync(join(tmpdir(), 'smoke-three-meshopt-'));
    original = join(root, 'shared/models/rig/puppet.glb');
    const py = `import json,sys; from pathlib import Path; from app.blender import runner; r=runner.run('meshopt',inputs={'model':Path(sys.argv[1])},out_dir=Path(sys.argv[2])); assert r['ok'] and r['outputs'],r; print(r['outputs']['model'])`;
    const run = spawnSync(join(root, '.venv/bin/python'), ['-c', py, original, tmp], { cwd: root, env: { ...process.env, ALSOFT_DRIVERS: 'null' }, encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr + run.stdout);
    compressed = run.stdout.trim().split('\n').at(-1);
  }
  assert.ok(compressed, 'provide original and compressed paths together');
  const [a, b] = await Promise.all([load(original), load(compressed)]);
  const am = meshes(a), bm = meshes(b);
  assert.ok(am.length > 0);
  assert.equal(am.length, bm.length);
  for (let i = 0; i < am.length; i++) {
    const x = am[i], y = bm[i];
    assert.deepEqual(a.parser.associations.get(x), b.parser.associations.get(y));
    assert.deepEqual(Object.keys(x.geometry.attributes), Object.keys(y.geometry.attributes));
    for (const key of Object.keys(x.geometry.attributes)) attribute(x.geometry.attributes[key], y.geometry.attributes[key], `mesh ${i}/${key}`);
    assert.deepEqual(Object.keys(x.geometry.morphAttributes), Object.keys(y.geometry.morphAttributes));
    for (const key of Object.keys(x.geometry.morphAttributes)) {
      assert.equal(x.geometry.morphAttributes[key].length, y.geometry.morphAttributes[key].length);
      x.geometry.morphAttributes[key].forEach((v, j) => attribute(v, y.geometry.morphAttributes[key][j], `morph ${i}/${key}/${j}`));
    }
    assert.equal(Boolean(x.geometry.index), Boolean(y.geometry.index));
    if (x.geometry.index) attribute(x.geometry.index, y.geometry.index, `mesh ${i}/indices`);
    assert.equal(x.isSkinnedMesh, y.isSkinnedMesh);
    if (x.isSkinnedMesh) {
      assert.deepEqual(x.skeleton.bones.map(bone => bone.name), y.skeleton.bones.map(bone => bone.name));
      x.skeleton.bones.forEach((bone, j) => {
        assert.deepEqual(bone.matrix.toArray(), y.skeleton.bones[j].matrix.toArray());
        assert.deepEqual(x.skeleton.boneInverses[j].toArray(), y.skeleton.boneInverses[j].toArray());
      });
    }
  }
  console.log(`PASS: three decodes ${am.length} meshes with identical attributes, indices, bones and associations`);
} finally {
  if (tmp) rmSync(tmp, { recursive: true, force: true });
}
