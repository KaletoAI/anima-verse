/** Test-only Task 33 adapters: numeric input, production solver, numeric output.
 * No live configuration, server, DOM, model assets or historical git revisions.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { build } from 'esbuild';
import * as THREE from 'three';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const root = fileURLToPath(new URL('../../', import.meta.url));
let loaded;
async function modules() {
  return loaded ??= (async () => {
    const dir = await mkdtemp(join(root, 'client3d/scripts/.smoke-secondary-vectors-'));
    try {
      const result = await build({stdin: {contents: `export * from '${root}packages/scene-render/src/secondaryMotion.ts'`, resolveDir: root, loader: 'ts'},
        bundle: true, platform: 'node', format: 'esm', write: false, external: ['three', 'three/*'], logLevel: 'error'});
      const file = join(dir, 'solver.mjs');
      await writeFile(file, result.outputFiles[0].text);
      return await import(`file://${file}`);
    } finally { await rm(dir, {recursive: true, force: true}); }
  })();
}
function chainValue(m, data) {
  const root = new THREE.Group();
  const bones = data.bones.map(b => {
    const bone = new THREE.Bone(); bone.name = b.name;
    new THREE.Matrix4().fromArray(b.matrix).decompose(bone.position, bone.quaternion, bone.scale);
    return bone;
  });
  data.bones.forEach((b, i) => (b.parent === null ? root : bones[b.parent]).add(bones[i]));
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.positions, 3));
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(data.indices, 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(data.weights, 4));
  const mesh = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial());
  root.add(mesh); root.updateMatrixWorld(true); mesh.bind(new THREE.Skeleton(bones));
  const solver = m.createSecondaryMotion(THREE, root, data.payload);
  try {
    for (let i = 0; i < data.frames; i++) solver.update(data.dt);
    root.updateMatrixWorld(true);
    const vertex = i => mesh.applyBoneTransform(i, new THREE.Vector3().fromBufferAttribute(geometry.getAttribute('position'), i)).applyMatrix4(mesh.matrixWorld);
    return {
      matrices: bones.map(b => b.matrixWorld.toArray()),
      samples: data.pairs.map(([a,b]) => ({halfWidth: vertex(a).distanceTo(vertex(b))/2,
        distance: vertex(a).add(vertex(b)).multiplyScalar(.5).length()})),
    };
  } finally { solver.dispose(); geometry.dispose(); mesh.material.dispose(); }
}
export async function secondaryVectorDispatch() {
  const m = await modules();
  return {
    stepSecondaryParticle: (p,v,target,targetVelocity,params,h) => {
      const result = m.stepSecondaryParticle(...[p,v,target,targetVelocity].map(a => new THREE.Vector3(...a)),params,h);
      return {p: result.p.toArray(), v: result.v.toArray()};
    },
    softMotionAngle: m.softMotionAngle,
    blendMotionParams: (from,to,elapsed) => m.blendMotionParams(from,to,elapsed),
    secondaryChain: data => chainValue(m,data),
  };
}
export async function runSecondaryVectors(name) {
  return runVectors(loadVectors(name), await secondaryVectorDispatch());
}
