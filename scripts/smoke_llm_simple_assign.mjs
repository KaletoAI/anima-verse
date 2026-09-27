#!/usr/bin/env node
/**
 * Smoke check for the "LLM Models (Simple)" page of /admin/settings: a pick
 * there may change ONLY the primaries (order 1) of the one task group it is
 * made for, and must never cost the Advanced LLM Routing any data.
 *
 * Usage:  node scripts/smoke_llm_simple_assign.mjs
 *
 * Runs headless: settings.js touches `document` at the top level, so the two
 * pure functions `llmSimpleHolders` and `llmSimpleAssign` are cut out by
 * regex and run alone in a `node:vm` context (same trick as
 * scripts/smoke_admin_escape.mjs).
 *
 * Background (2026-09-27): the page used to rebuild ALL of llm_routing from
 * its five dropdowns — every order-1 assignment dropped, each group handed
 * whole to its most frequent model, entries matched by provider+model only
 * (names/temperatures ignored), then every entry that ran empty deleted.
 * Against a real world config that deleted 3 of 7 entries, including named
 * ones, before the user had changed anything.
 *
 * ============================================================================
 * FIXTURE AND EXPECTATIONS, DERIVED BY HAND
 * ============================================================================
 * Groups (fixture-level):  chat = chat_stream, thought
 *                          tool = intent, furnish, spell_detect
 *                          image = image_recognition   helper = translation
 *
 *   0 Chat   A/big   chat_stream:1 thought:1 intent:2   (max_concurrent 2)
 *   1 Tools  G/tool  intent:1 furnish:1                 (temperature 0.1)
 *   2 Image  G/tool  image_recognition:1
 *   3 Helper G/tool  spell_detect:1 translation:1
 *
 * A) tool -> G/tool. Primary holders of the tool group: Tools (2), Helper (1);
 *    both are G/tool, Tools holds more -> target = Tools. spell_detect leaves
 *    Helper. Result: 4 entries; Tools = intent:1 furnish:1 spell_detect:1 with
 *    temperature 0.1 and its name; Helper = translation:1; Chat, Image as-is.
 * B) chat -> G/tool. No G/tool entry holds a chat primary -> first enabled
 *    G/tool = Tools. Chat loses chat_stream/thought but KEEPS intent:2 and
 *    stays. Tools gains chat_stream:1 thought:1. 4 entries.
 * C) tool -> A/big. Target = Chat (first A/big). Chat already had intent:2,
 *    so Tools, which loses the intent primary, takes order 2 (chain length
 *    kept). Chat = chat_stream:1 thought:1 intent:1 furnish:1 spell_detect:1;
 *    Tools = intent:2; Helper = translation:1. 4 entries.
 * D) image -> none. Image keeps its entry with no tasks. 4 entries.
 * E) helper -> X/small (no such entry). One entry appended:
 *    {name 'Helper (small jobs)', temperature 0.5, X/small, enabled, translation:1};
 *    Helper = spell_detect:1. 5 entries.
 * F) Only a DISABLED D/m entry exists -> it is re-enabled and used, nothing
 *    appended.
 * G) The input list is never mutated.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const src = readFileSync(new URL('../static/admin/settings.js', import.meta.url), 'utf8');

function cut(name) {
    const start = src.indexOf('function ' + name + '(');
    assert.ok(start >= 0, name + ' not found in settings.js');
    // The function ends at the first line that is exactly "}".
    const end = src.indexOf('\n}\n', start);
    return src.slice(start, end + 2);
}

const ctx = {};
vm.createContext(ctx);
vm.runInContext(cut('llmSimpleHolders') + '\n' + cut('llmSimpleAssign')
    + '\nthis.holders = llmSimpleHolders; this.assign = llmSimpleAssign;', ctx);
const assign = (r, ids, p, m, n) => JSON.parse(JSON.stringify(ctx.assign(r, ids, p, m, n)));

const TOOL = ['intent', 'furnish', 'spell_detect'];
const CHAT = ['chat_stream', 'thought'];

function fixture() {
    return [
        { name: 'Chat', provider: 'A', model: 'big', max_concurrent: 2,
          tasks: [{ task: 'chat_stream', order: 1 }, { task: 'thought', order: 1 }, { task: 'intent', order: 2 }] },
        { name: 'Tools', provider: 'G', model: 'tool', temperature: 0.1,
          tasks: [{ task: 'intent', order: 1 }, { task: 'furnish', order: 1 }] },
        { name: 'Image', provider: 'G', model: 'tool',
          tasks: [{ task: 'image_recognition', order: 1 }] },
        { name: 'Helper', provider: 'G', model: 'tool',
          tasks: [{ task: 'spell_detect', order: 1 }, { task: 'translation', order: 1 }] },
    ];
}
const tasksOf = e => Object.fromEntries(e.tasks.map(t => [t.task, t.order]));

let n = 0;
function check(label, fn) { fn(); n++; console.log('ok  ' + label); }

check('A tool group stays on the entry that held most of it', () => {
    const f = fixture();
    const r = assign(f, TOOL, 'G', 'tool');
    assert.equal(r.length, 4);
    assert.deepEqual(r[0], f[0]);
    assert.equal(r[1].name, 'Tools');
    assert.equal(r[1].temperature, 0.1);
    assert.deepEqual(tasksOf(r[1]), { intent: 1, furnish: 1, spell_detect: 1 });
    assert.deepEqual(r[2], f[2]);
    assert.deepEqual(tasksOf(r[3]), { translation: 1 });
});

check('B switching chat keeps the old entry and its fallback', () => {
    const r = assign(fixture(), CHAT, 'G', 'tool');
    assert.equal(r.length, 4);
    assert.deepEqual(tasksOf(r[0]), { intent: 2 });
    assert.equal(r[0].max_concurrent, 2);
    assert.deepEqual(tasksOf(r[1]), { intent: 1, furnish: 1, chat_stream: 1, thought: 1 });
});

check('C a fallback on the target is handed to the displaced holder', () => {
    const r = assign(fixture(), TOOL, 'A', 'big');
    assert.equal(r.length, 4);
    assert.deepEqual(tasksOf(r[0]),
        { chat_stream: 1, thought: 1, intent: 1, furnish: 1, spell_detect: 1 });
    assert.deepEqual(tasksOf(r[1]), { intent: 2 });
    assert.deepEqual(tasksOf(r[3]), { translation: 1 });
});

check('D "none" clears primaries but deletes no entry', () => {
    const r = assign(fixture(), ['image_recognition'], '', '');
    assert.equal(r.length, 4);
    assert.equal(r[2].name, 'Image');
    assert.deepEqual(r[2].tasks, []);
});

check('E an unknown model gets one new entry', () => {
    const r = assign(fixture(), ['translation'], 'X', 'small',
        { name: 'Helper (small jobs)', temperature: 0.5 });
    assert.equal(r.length, 5);
    assert.deepEqual(r[4], { name: 'Helper (small jobs)', temperature: 0.5, provider: 'X',
        model: 'small', enabled: true, tasks: [{ task: 'translation', order: 1 }] });
    assert.deepEqual(tasksOf(r[3]), { spell_detect: 1 });
});

check('F a disabled match is re-enabled instead of duplicated', () => {
    const f = [...fixture(), { name: 'Off', provider: 'D', model: 'm', enabled: false, tasks: [] }];
    const r = assign(f, ['translation'], 'D', 'm');
    assert.equal(r.length, 5);
    assert.equal(r[4].enabled, true);
    assert.deepEqual(tasksOf(r[4]), { translation: 1 });
});

check('G the input is never mutated', () => {
    const f = fixture();
    const snap = JSON.stringify(f);
    ctx.assign(f, TOOL, 'A', 'big');
    ctx.assign(f, ['image_recognition'], '', '');
    assert.equal(JSON.stringify(f), snap);
});

console.log(`\n${n} checks passed`);
