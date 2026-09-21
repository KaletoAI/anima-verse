/**
 * check_routing_model.js — the pure chain functions of the task-centric
 * LLM routing editor (plan-llm-routing-ui.md, Task 3).
 *
 * Usage:  node scripts/check_routing_model.js     (repo root; no server)
 *
 * Extracts the block // >>> harness-extract:routingModel … // <<< … out of
 * static/admin/settings-routing.js and runs it on synthetic routing lists.
 *
 * Routing fixture R0 (index: provider/model, enabled, tasks):
 *   0: A/m0 on   chat_stream@1, intent@2
 *   1: B/m1 on   intent@1, consolidation@1
 *   2: A/m2 OFF  chat_stream@2, translation@1
 *   3: A/m3 on   (no tasks)
 *
 * Expected, derived by hand:
 *  1. buildTaskChains(R0).intent = [{entry:1, order:1}, {entry:0, order:2}]
 *     (sorted by order); chat_stream = [{entry:0,order:1},{entry:2,order:2}]
 *     — disabled entries ARE listed (the UI strikes them through).
 *  2. assignTask(R0, "intent", 3) appends {task:"intent", order:3} to entry 3
 *     (max existing order 2 + 1); returns true. Assigning again returns false
 *     and changes nothing.
 *  3. assignTask(R0, "roof_design", 3) → order 1 (nothing existed).
 *  4. unassignTask(R0, "intent", 1) removes it from entry 1 and renumbers:
 *     chain becomes [{entry:0, order:1}, {entry:3, order:2}] (after check 2).
 *  5. moveTask(R0, "intent", 3, -1) swaps → [{entry:3,order:1},{entry:0,order:2}];
 *     moveTask at the top with -1 is a no-op returning false.
 *  6. renumberTask on a chain with orders [5, 5, 9] (indices 0,1,2 tie broken
 *     by entry index) → [1, 2, 3].
 *  7. unknownAssignments(R0, new Set(["chat_stream","intent","consolidation"]))
 *     → [{entry:2, task:"translation"}] (order of appearance).
 *  8. entriesLosingLastAssignment(R0_original, 1) → ["consolidation"]
 *     (intent still has entry 0; consolidation only lives on entry 1).
 *
 * Lane pools — one `max_concurrent` per provider+model. Fixture P0:
 *   0: G/gem  on   lanes 3   "Tools"
 *   1: G/gem  on   (none)    "Image"      → counts as 1
 *   2: G/big  on   lanes 2   "Chat"
 *   3: G/gem  OFF  lanes 8   "Helper"
 *   4: G/     on   lanes 5   (no model → in no pool)
 *   5: H/gem  on   lanes 4   (other provider → other pool)
 *  9. poolKeyOf: 0 → "G/gem", 4 → "" ; poolSiblings(P0, 0) = [1, 3]
 *     (same provider AND model, disabled ones included, never itself);
 *     poolSiblings(P0, 2) = [] ; poolSiblings(P0, 4) = [] ; poolSiblings(P0, 5) = [].
 * 10. lanesInForce mirrors the server (llm_lanes.lane_count_in): the highest
 *     value among the ENABLED entries → G/gem = max(3, 1) = 3, the disabled 8
 *     does not count — for entry 0, 1 AND 3. Entry 2 → 2. A pool of disabled
 *     entries only (flip 0 and 1 off) shows what it would come up with: 8.
 * 11. normalizePoolLanes(P0) writes 3 into entries 0, 1, 3 and reports
 *     [{pool:"G/gem", lanes:3}]; entries 2, 4, 5 keep 2, 5, 4. A second run
 *     reports [] (nothing disagrees any more).
 * 12. setPoolLanes(P0, 1, 2) → touched [1, 0, 3], all three hold 2, entry 5
 *     still 4. A value below 1 or NaN becomes 1.
 * 13. adoptPoolLanes: entry 2 switches its model to "gem" → takes the pool's 3
 *     (from its SIBLINGS, its own 2 does not vote) and returns true; an entry
 *     alone in its pool returns false and keeps its number.
 */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const SRC = path.join(__dirname, '..', 'static', 'admin', 'settings-routing.js');
const BEGIN = '// >>> harness-extract:routingModel', END = '// <<< harness-extract:routingModel';
const src = fs.readFileSync(SRC, 'utf8');
const a = src.indexOf(BEGIN), b = src.indexOf(END);
if (a < 0 || b < 0 || b < a) { console.error('FAIL: markers not found'); process.exit(1); }
const sb = {}; vm.createContext(sb);
vm.runInContext(src.slice(a + BEGIN.length, b) + '\n;' +
  ['buildTaskChains','assignTask','unassignTask','moveTask','renumberTask','unknownAssignments','entriesLosingLastAssignment',
   'poolKeyOf','poolSiblings','lanesInForce','setPoolLanes','adoptPoolLanes','normalizePoolLanes']
    .map(n => `this.${n} = ${n};`).join(''), sb);
const fixture = () => JSON.parse(JSON.stringify([
  { provider: 'A', model: 'm0', enabled: true,  tasks: [{task:'chat_stream',order:1},{task:'intent',order:2}] },
  { provider: 'B', model: 'm1', enabled: true,  tasks: [{task:'intent',order:1},{task:'consolidation',order:1}] },
  { provider: 'A', model: 'm2', enabled: false, tasks: [{task:'chat_stream',order:2},{task:'translation',order:1}] },
  { provider: 'A', model: 'm3', enabled: true,  tasks: [] },
]));
let fails = 0;
const eq = (x, y) => JSON.stringify(x) === JSON.stringify(y);
const check = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) fails++; };

let R = fixture();
let ch = sb.buildTaskChains(R);
check(eq(ch.intent, [{entry:1,order:1},{entry:0,order:2}]), '1. intent chain sorted by order');
check(eq(ch.chat_stream, [{entry:0,order:1},{entry:2,order:2}]), '1. disabled entries listed');
check(sb.assignTask(R, 'intent', 3) === true && eq(R[3].tasks, [{task:'intent',order:3}]), '2. assign appends at max+1');
check(sb.assignTask(R, 'intent', 3) === false && R[3].tasks.length === 1, '2. double assign is a no-op');
sb.assignTask(R, 'roof_design', 3);
check(R[3].tasks[1].order === 1, '3. first assignment gets order 1');
sb.unassignTask(R, 'intent', 1);
check(eq(sb.buildTaskChains(R).intent, [{entry:0,order:1},{entry:3,order:2}]), '4. unassign renumbers');
check(sb.moveTask(R, 'intent', 3, -1) === true && eq(sb.buildTaskChains(R).intent, [{entry:3,order:1},{entry:0,order:2}]), '5. move up');
check(sb.moveTask(R, 'intent', 3, -1) === false, '5. move past top is no-op');
let R6 = [{tasks:[{task:'x',order:5}]},{tasks:[{task:'x',order:5}]},{tasks:[{task:'x',order:9}]}];
sb.renumberTask(R6, 'x');
check(eq(R6.map(e => e.tasks[0].order), [1,2,3]), '6. renumber ties by entry index');
check(eq(sb.unknownAssignments(fixture(), new Set(['chat_stream','intent','consolidation'])), [{entry:2,task:'translation'}]), '7. unknown assignments');
check(eq(sb.entriesLosingLastAssignment(fixture(), 1), ['consolidation']), '8. tasks losing their last assignment');

const pools = () => JSON.parse(JSON.stringify([
  { name: 'Tools',  provider: 'G', model: 'gem', enabled: true,  max_concurrent: 3 },
  { name: 'Image',  provider: 'G', model: 'gem', enabled: true },
  { name: 'Chat',   provider: 'G', model: 'big', enabled: true,  max_concurrent: 2 },
  { name: 'Helper', provider: 'G', model: 'gem', enabled: false, max_concurrent: 8 },
  { name: 'Blank',  provider: 'G', model: '',    enabled: true,  max_concurrent: 5 },
  { name: 'Other',  provider: 'H', model: 'gem', enabled: true,  max_concurrent: 4 },
]));
const lanes = P => P.map(e => e.max_concurrent === undefined ? null : e.max_concurrent);
let P = pools();
check(sb.poolKeyOf(P[0]) === 'G/gem' && sb.poolKeyOf(P[4]) === '', '9. pool key needs provider AND model');
check(eq(sb.poolSiblings(P, 0), [1, 3]), '9. siblings: same provider+model, disabled included, not itself');
check(eq([2, 4, 5].map(i => sb.poolSiblings(P, i)), [[], [], []]), '9. other model / no model / other provider are alone');
check(eq([0, 1, 3, 2].map(i => sb.lanesInForce(P, i)), [3, 3, 3, 2]), '10. in force = highest ENABLED value of the pool');
let Poff = pools(); Poff[0].enabled = false; Poff[1].enabled = false;
check(sb.lanesInForce(Poff, 0) === 8, '10. a pool of disabled entries shows its highest value');
check(eq(sb.normalizePoolLanes(P), [{pool:'G/gem',lanes:3}]) && eq(lanes(P), [3, 3, 2, 3, 5, 4]), '11. normalize writes the value in force into the pool only');
check(eq(sb.normalizePoolLanes(P), []), '11. second normalize finds nothing');
P = pools();
check(eq(sb.setPoolLanes(P, 1, 2), [1, 0, 3]) && eq(lanes(P), [2, 2, 2, 2, 5, 4]), '12. set writes through to every sibling');
sb.setPoolLanes(P, 0, 0); const low = P[0].max_concurrent; sb.setPoolLanes(P, 0, 'x');
check(low === 1 && P[3].max_concurrent === 1, '12. below 1 / NaN becomes 1');
P = pools(); P[2].model = 'gem';
check(sb.adoptPoolLanes(P, 2) === true && P[2].max_concurrent === 3, '13. joining a pool takes the siblings\' number');
check(sb.adoptPoolLanes(P, 5) === false && P[5].max_concurrent === 4, '13. alone in its pool keeps its own');
console.log(); if (fails) { console.log(fails + ' check(s) failed'); process.exit(1); } console.log('all checks passed');
