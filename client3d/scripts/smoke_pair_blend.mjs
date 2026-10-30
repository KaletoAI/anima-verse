#!/usr/bin/env node
/** Hand derivations for pair_blend.json: u=clamp(realSeconds/.4,0,1),
 * weight=u*u*(3-2*u). At 0,.1,.2,.3,.4 seconds u=0,.25,.5,.75,1,
 * so weights=0,.15625,.5,.84375,1. Clamp negative/late times to 0/1.
 * From (1,2,3) to (5,6,-1), add (4,4,-4)*weight; yaw 0->2 adds
 * 2*weight. A moving endpoint (9,4,7) at half yields (5,3,5).
 * Equal positions stay (1,2,3); only yaw changes. Shortest yaw from
 * 3pi/4 to -3pi/4 travels +pi/2: halfway pi; reversed halfway -pi.
 * A full turn has zero shortest delta. These numbers are hand-derived,
 * independent of world rate and clip timing (including a frozen world).
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const {passed, failed} = await runPairVectors('pair_blend');
console.log(`pair_blend: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
