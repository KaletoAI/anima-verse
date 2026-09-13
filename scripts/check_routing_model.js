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
  ['buildTaskChains','assignTask','unassignTask','moveTask','renumberTask','unknownAssignments','entriesLosingLastAssignment']
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
console.log(); if (fails) { console.log(fails + ' check(s) failed'); process.exit(1); } console.log('all checks passed');
