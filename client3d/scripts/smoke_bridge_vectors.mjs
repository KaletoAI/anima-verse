#!/usr/bin/env node
/** Run every Task 31 hand vector without live config, model files or a server.
 * Derivations belong to each JSON file's single canonical source smoke.
 * Usage: timeout 300 node client3d/scripts/smoke_bridge_vectors.mjs
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
let passed = 0;
let failed = 0;
for (const name of ['foot_lock', 'leg_pin', 'bridge_lift', 'bridge_travel',
  'bridge_heading', 'stand_settle', 'foot_lock_measure', 'stairs']) {
  const result = await runBridgeVectors(name);
  console.log(`${name}: ${result.passed} ok, ${result.failed} failed`);
  passed += result.passed; failed += result.failed;
}
console.log(`Task 31 vectors: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
