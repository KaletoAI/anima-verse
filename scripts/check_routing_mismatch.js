/**
 * check_routing_mismatch.js — verifies the LLM-routing mismatch rule of the
 * admin settings UI (task A0.3, plan-llm-routing-review.md).
 *
 * Usage:
 *     node scripts/check_routing_mismatch.js
 *     (from the repo root; no server, no world DB, no network)
 *
 * What it does: extracts the pure block marked
 *     // >>> harness-extract:evaluateRoutingMatch  ...  // <<< harness-extract:...
 * out of static/admin/settings.js and runs it against SYNTHETIC capability
 * records. Nothing is imported from the running app, so the check states the
 * rule independently of the UI around it.
 *
 * The rule under test (brief, verbatim): warn ONLY when requirement === true
 * AND capability === false. capability null / entry missing / known:false =>
 * "capabilities unknown", never a warning. capability === true => nothing.
 *
 * Expected values, derived by hand from that rule:
 *   1. req tools,  caps {known:true, tools:false}      -> missing ["tools"], unknown false
 *   2. req tools,  caps {known:true, tools:true}       -> missing [],        unknown false
 *   3. req tools,  caps {known:false}                  -> missing [],        unknown true
 *   4. req tools,  caps {known:true, tools:null}       -> missing [],        unknown true
 *   5. req vision, caps {known:true, vision:false}     -> missing ["vision"],unknown false
 *   6. req neither, caps {known:true, both false}      -> missing [],        unknown false
 *   7. no profile at all (pose_embedding), caps null   -> missing [],        unknown false
 *   8. req tools+vision, caps {tools:false, vision:null}
 *      -> missing ["tools"], unknown false   (a real finding outranks the hint)
 *   9. req tools,  caps undefined (not looked up yet)  -> missing [],        unknown true
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = path.join(__dirname, '..', 'static', 'admin', 'settings.js');
const BEGIN = '// >>> harness-extract:evaluateRoutingMatch';
const END = '// <<< harness-extract:evaluateRoutingMatch';

const src = fs.readFileSync(SRC, 'utf8');
const a = src.indexOf(BEGIN);
const b = src.indexOf(END);
if (a < 0 || b < 0 || b < a) {
    console.error('FAIL: extraction markers not found in ' + SRC);
    process.exit(1);
}
const block = src.slice(a + BEGIN.length, b);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(block + '\n; this.evaluateRoutingMatch = evaluateRoutingMatch;'
    + ' this.CHECKABLE_REQUIREMENTS = CHECKABLE_REQUIREMENTS;', sandbox);
const evaluateRoutingMatch = sandbox.evaluateRoutingMatch;

// Requirement profiles in the shape app/core/llm_tasks.py delivers them.
const REQ_TOOLS = { tools: true, vision: false, json: false, min_context: 8192,
                    model_class: 'large', arch: 'dense', hallucination_risk: 'high',
                    creative: true, language_de: true, latency_sensitive: false };
const REQ_VISION = Object.assign({}, REQ_TOOLS, { tools: false, vision: true });
const REQ_NONE = Object.assign({}, REQ_TOOLS, { tools: false, vision: false });
const REQ_BOTH = Object.assign({}, REQ_TOOLS, { tools: true, vision: true });

const CASES = [
    ['tools required, model cannot do tools',
        REQ_TOOLS, { tools: false, vision: null, known: true }, ['tools'], false],
    ['tools required, model can do tools',
        REQ_TOOLS, { tools: true, vision: null, known: true }, [], false],
    ['tools required, model unknown (no capability entry)',
        REQ_TOOLS, { tools: null, vision: null, known: false }, [], true],
    ['tools required, entry exists but tool_calling null',
        REQ_TOOLS, { tools: null, vision: true, known: true }, [], true],
    ['vision required, model has no image input',
        REQ_VISION, { tools: true, vision: false, known: true }, ['vision'], false],
    ['no hard requirement, model can do neither',
        REQ_NONE, { tools: false, vision: false, known: true }, [], false],
    ['task without a requirement profile (pose_embedding)',
        null, null, [], false],
    ['tools+vision required, tools false / vision null',
        REQ_BOTH, { tools: false, vision: null, known: true }, ['tools'], false],
    ['tools required, capabilities not looked up yet',
        REQ_TOOLS, undefined, [], true],
];

let failed = 0;
for (const [name, req, caps, wantMissing, wantUnknown] of CASES) {
    const got = evaluateRoutingMatch(req, caps);
    const okMissing = JSON.stringify(got.missing) === JSON.stringify(wantMissing);
    const okUnknown = got.unknown === wantUnknown;
    const ok = okMissing && okUnknown;
    if (!ok) failed++;
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    console.log('        expected missing=' + JSON.stringify(wantMissing)
        + ' unknown=' + wantUnknown
        + '  |  got missing=' + JSON.stringify(got.missing)
        + ' unknown=' + got.unknown);
}

// The mapping must stay limited to the two automatically checkable keys —
// json / min_context and every soft criterion are display-only.
const mapped = Object.keys(sandbox.CHECKABLE_REQUIREMENTS).sort().join(',');
const mappedOk = mapped === 'tools,vision';
if (!mappedOk) failed++;
console.log((mappedOk ? 'PASS' : 'FAIL') + '  only tools/vision are checked automatically'
    + '  (got: ' + mapped + ')');

console.log('\n' + (failed ? failed + ' CASE(S) FAILED' : 'all ' + (CASES.length + 1) + ' checks passed'));
process.exit(failed ? 1 : 0);
