# prop_action_motion

- Origin: `client3d/scripts/smoke_prop_action_motion.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/PropActionMotionVectorTests.cs`
- Vectors: `shared/test-vectors/prop_action_motion.json`
- E3 Task 5: the `localApproachPoint` cases ([1], [4]) went with the native NPC approach path they tested.

## Derivation

```text
/**
 * Hand derivations for prop_action_motion.json (metres, seconds, compass degrees).
 * No expected value is sampled from production. Run:
 *   node client3d/scripts/smoke_prop_action_motion.mjs
 *
 * [2] Entry fraction = clamp((elapsed + max(age,0)*max(rate,0))/duration,0,1).
 * Original (elapsed,duration,rate,age) values: (2,4,1,0),(1,4,1,1),
 * (1,8,2,1.5),(1,4,0,50),(3,4,1,20),(2,4,1,0) give
 * .5,.5,.5,.25,1,.5. Multiply measured clip durations 2,2,4,2,2,2 ->
 * 1,1,2,.5,2,1 seconds. Heights 200/140/100 cm do not scale this clock.
 * [3] Original support cases: support = anchor + root_offset;
 * correction = support - root_offset - access = anchor - access.
 * Stool .527-.398 = .129; hips 1->.5 at 1,.75,.5 give factors 0,.5,1,
 * hence lifts 0,.0645,.129. Bed .49-.002=.488; hips 1->.2 at .6 gives
 * .5*.488=.244. Upper storey 3.527-.398-3=.129 -> half .0645.
 * Hips .4 overshoots .5 -> clamp to .129. Flat hips cannot realize .129
 * (null/unsupported); .398-.398=0 needs no correction (0/supported).
 * [5] Negative age/rate hold 1/4=.25; elapsed -2 clamps to 0;
 * (1+1.5*2)/4=1 exactly at the end.
 * [6] Ascending hips 0->2 at 1: .5*.4=.2. Hips 1.2 before descent
 * clamps 0. Access 1, anchor .5 -> -.5 correction, half -> -.25.
 * Span .0000005 < 1e-6 is flat: .129 lift unsupported; correction
 * .0000005 < 1e-6 with flat span returns 0 (the measured-support tolerance).
 * Span exactly .000001 is measured: 0->.000001 at .0000005 gives
 * .5*.2=.1 lift. Flat hips with correction exactly .000001 cannot count
 * as zero correction and return null (both tolerance checks are strict <).
 * [7] Identity joins kind|start|access x,y,z,yaw|anchor x,y,z,yaw.
 * Base is sit-down|5|0,0,0,90|1,0.4,0,90. Elapsed poll changes nothing;
 * changing start to 6, access Y to 3, anchor X to 2 or kind to lie-down
 * changes only that token. These are public clip origins, not execution IDs.
 * [8] Two meshes at (0,0) share room/variant, only chair-1 matches entry
 * placement chair-1/variant-1. Blocked semantic offers still expose slot
 * (1,0,2) as XZ (1,2); free=0 does not hide the reason. Stale variant,
 * wrong room, null mounted object or moved anchor each yields no pick.
 * [9] Gate starts with no withdrawn journeys. Cancel blocks immediately,
 * calls HTTP once and withdraws only after resolution. Reject releases pending
 * with no withdrawal; retry can succeed. Concurrent callers share the SAME
 * promise and only the first journey is withdrawn. Null/empty journeys never
 * enter the withdrawn set. Traces list pending, call count and probe booleans
 * after each operation; settle also records resolved/rejected.
 * [10] Begin retains pause until matching changed AND subsequent adopt.
 * Missing/other correlation cannot release it; completing one of two leaves
 * the other. Begin at 100 expires at 100+10000=10100, not 10099. Expire
 * marks complete once, stays pending, repeats false, then adopt releases.
 * [11] Drain waits for every actual position promise: finishing first of two
 * leaves both waiters false; finishing the queued final write resolves both.
 * Idle wait resolves on the next microtask; a later write blocks a new waiter.
 * [12] Choices preserve Core verdicts. Solo yields one enabled/reason row
 * without a partner; blocked solo keeps claimed. Pair returns the authored
 * fixture-npc busy / fixture-other enabled rows in that order, without picking
 * either. An empty pair list yields one disabled partner_required row.
 *
 * [16] B1 Own answer playback consumes real elapsed seconds, departure first,
 * then each positive-pace segment. Null legs consume no time; null overall
 * holds at the first walked point. Entry holds access for its real duration;
 * direct entry and completed bridges end exactly on the server body anchor.
 * The shared vectors enumerate corners, height, yaw, departure and freezing.
 *
 * Adapters call production exports and normalize Three/Promise results only.
 * Async traces resolve before passing their actual result through runVectors;
 * the common loader, fixture resolver, comparator and failure accounting apply.
 * The original 27 inline lifecycle/pick assertions below remain as regressions.
 */
```
