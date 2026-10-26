#!/usr/bin/env node
/** Task 33 vectors only. No models, live config, DOM or historical git sources.
 * Hand derivations: smoke_secondary_motion.mjs docstring.
 * Usage: timeout 300 node client3d/scripts/smoke_secondary_vectors.mjs
 */
import { runSecondaryVectors } from './secondaryVectorDispatch.mjs';
let passed = 0, failed = 0;
for (const name of ['secondary_particle', 'secondary_angle', 'secondary_params', 'secondary_chain']) {
  const result = await runSecondaryVectors(name);
  console.log(`${name}: ${result.passed} ok, ${result.failed} failed`);
  passed += result.passed; failed += result.failed;
}
console.log(`Task 33 vectors: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
