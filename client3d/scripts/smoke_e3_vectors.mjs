#!/usr/bin/env node
/** Run every E3 JSON case against production TypeScript, independently of the
 * source smokes' integration/mutation checks. Hand derivations live in each
 * JSON's single source smoke, not in this adapter runner. */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { e3Dispatch } from './e3VectorDispatch.mjs';
const dispatch = await e3Dispatch();
let passed = 0, failed = 0;
for (const area of ['terrain_lod', 'height_tiles', 'layer_ground', 'water', 'sky_light', 'backdrop', 'fog_veil']) {
  const result = runVectors(loadVectors(area), dispatch);
  passed += result.passed; failed += result.failed;
}
console.log(`${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
