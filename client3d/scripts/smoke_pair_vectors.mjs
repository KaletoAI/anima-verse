#!/usr/bin/env node
/** Run Task 32 shared vectors without live configuration, model files or a server.
 * Each JSON source smoke contains its hand derivations.
 * Usage: timeout 300 node client3d/scripts/smoke_pair_vectors.mjs
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
let passed = 0;
let failed = 0;
for (const name of ['pair_clip_phase', 'pair_clip_geometry', 'pair_height', 'figure_normalisation']) {
  const result = await runPairVectors(name);
  console.log(`${name}: ${result.passed} ok, ${result.failed} failed`);
  passed += result.passed; failed += result.failed;
}
console.log(`Task 32 vectors: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
