/** Task 34: plain bone positions/topology and numeric gait arguments only. */
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
export async function animalVectorDispatch() {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const result = await build({stdin: {contents: `export * from './packages/scene-render/src/proceduralGait.ts';`,
    resolveDir: root, loader: 'ts'}, bundle: true, platform: 'node', format: 'esm', write: false});
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
export async function runAnimalVectors(name) {
  return runVectors(loadVectors(name), await animalVectorDispatch());
}
