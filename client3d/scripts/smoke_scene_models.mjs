#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/scene_models.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_scene_models.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../..');
export async function modelFunctions() {
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-models-'));
  try {
    const result = await build({ stdin: { contents: `
      export { pickModelVariant, pickVariant } from './packages/scene-render/src/types';
      export { leafPivot } from './packages/scene-render/src/leafPivot';
      export * from './packages/scene-render/src/storeyGround';
      export * from './packages/scene-render/src/surface';
      export * from './packages/scene-render/src/clipMath';
      export { cutPlaneData } from './packages/scene-render/src/depthCutMath';
      export { surfaceFinish } from './packages/scene-render/src/materials';
      export * from './client3d/src/scene/materialLooks';
      export { markerLiftPoint } from './client3d/src/game/placement';
      export { slotFor } from './packages/scene-render/src/placeSlot';
      export { glyphRows, glyphParameters } from './client3d/src/scene/placeGlyphs';
      export { Vector3 } from 'three';
    `, resolveDir: ROOT, loader: 'ts' }, bundle: true, platform: 'node', format: 'esm', write: false });
    const file = join(dir, 'models.mjs');
    await writeFile(file, result.outputFiles[0].text);
    const m = await import(`file://${file}`);
    const sample = n => n === null || n === undefined ? undefined : () => n;
    return { ...m,
      markerLiftPointInvalidAnchor: at => m.markerLiftPoint(at, { x: NaN, z: 2 }),
      variantMatchesPlain: (s,tier) => m.pickModelVariant(s,tier) === m.pickVariant(s.variants,tier),
      variantContained: (s,tier) => m.pickModelVariant(s,tier) !== s.variants.low,
      variantScatter: (s, indices) => indices.map(variant => m.pickModelVariant({ ...s, variant }, 'full')),
      variantCounts: (s, indices) => [0,1,2].map(v => indices.map(variant => m.pickModelVariant({ ...s, variant }, 'full')).filter(url => url === m.pickModelVariant({ ...s, variant: v }, 'full')).length),
      storeyGroundLift: (level,x,z,datum,s) => m.storeyGroundLift(level,x,z,datum,sample(s)),
      storeyGroundRelift: (applied,level,x,z,datum,s) => m.storeyGroundRelift(applied,level,x,z,datum,sample(s)),
      tileDatumStep: (applied,x,z,s) => m.tileDatumStep(applied,x,z,sample(s)),
      slotFor: (slots,slot) => m.slotFor({ slots: slots.map(p => new m.Vector3(...p)) },slot)?.toArray() ?? null,
      buildGlyphs: (entries,offers,skip='',rooms=[]) => m.glyphRows(entries ? new Map(Object.entries(entries).map(([id,e]) => [id,{ ...e, slots:e.slots.map(([x,y,z]) => ({x,y,z})) }])) : undefined, offers, skip, new Set(rooms)),
      cutPlaneFor: m.cutPlaneData,
    };
  } finally { await rm(dir, { recursive: true, force: true }); }
}
export async function runModelVectors(filter = () => true) {
  const vectors = loadVectors('scene_models');
  return runVectors({ ...vectors, cases: vectors.cases.filter(filter) }, await modelFunctions());
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { passed, failed } = await runModelVectors();
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
}
