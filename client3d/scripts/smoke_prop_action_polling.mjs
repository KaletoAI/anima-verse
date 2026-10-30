/** Real HUD fetcher/spec and polling core, with a fake clock and counting HTTP boundary. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { loadHudRealm } from './load_hud_realm.mjs';
import { mainFunction } from './mainFunction.mjs';
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const url = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const apiUrl = url(compile(readFileSync(new URL('../../packages/player-ui/src/api.ts', import.meta.url), 'utf8')));
const actionsSource = readFileSync(process.argv[2] ?? new URL('../../packages/player-ui/src/propActions.ts', import.meta.url), 'utf8');
const actions = await import(url(compile(actionsSource).replace(/from ['"]\.\/api['"]/, `from '${apiUrl}'`)));
const hookSource = readFileSync(process.argv[3] ?? new URL('../../packages/player-ui/src/usePropActions.ts', import.meta.url), 'utf8');
const ast = ts.createSourceFile('usePropActions.ts', hookSource, ts.ScriptTarget.Latest, true);
let specCode, fetchCode;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'SPEC') specCode = node.initializer.getText(ast);
  if (ts.isCallExpression(node) && node.expression.getText(ast) === 'usePoll') fetchCode = node.arguments[1].getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
assert.ok(specCode && fetchCode);
const spec = new Function(compile(`return (${specCode});`))();
const fetcher = new Function(...Object.keys(actions), compile(`let lastLifecycle=null; return (${fetchCode});`))(...Object.values(actions));
const { createPollCore } = loadHudRealm().load('packages/player-ui/src/pollCore.ts');
const savedNow = Date.now, savedWindow = globalThis.window;
let now = savedNow() + 10000, offers = 0, state = 0;
Date.now = () => now;
globalThis.window = new EventTarget();
globalThis.CustomEvent ??= class extends Event { constructor(type, options) { super(type); this.detail = options?.detail; } };
globalThis.fetch = async path => {
  if (path.endsWith('/state')) state++; else offers++;
  return new Response(JSON.stringify(path.endsWith('/state') ? { incoming: [], outgoing: [], current: [], recent_results: [] } : []), { status: 200 });
};
const hub = { connected: () => false, generation: () => 0, onState: () => () => {}, onTopics: () => () => {} };
const core = createPollCore({ now: () => now, hidden: () => false, setTimeout: () => 0, clearTimeout() {} }, hub);
const unsubscribe = core.subscribe('play-prop-actions', fetcher, spec, () => {});
const otherPanel = core.subscribe('play-prop-actions', fetcher, spec, () => {});
for (let second = 0; second < 60; second++) {
  core.tick();
  if (second % 3 === 0) await Promise.all([actions.getPropActions(), actions.getPropActionState()]);
  await new Promise(resolve => setImmediate(resolve));
  now += 1000;
}
console.log(`POLL-MEASURE JS real HUD core + host 60s offers=${offers} state=${state}`);
unsubscribe(); otherPanel();
Date.now = savedNow; globalThis.window = savedWindow;
assert.equal(offers, 20, 'HUD panels and browser host share the worldmap request budget');
assert.equal(state, 20, 'HUD panels and browser host share the private-state request budget');

// The production browser timer must not turn a persistent seat or an NPC into a perpetual own burst.
let worldReads = 0;
const poll = await mainFunction('pollPropMotion', {
  propPreparation: { expire: () => false }, propStateUncertain: false, propStateEpoch: 0,
  propPollUntil: 0, propPollBusy: false, ownedPropRun: () => ({ status: 'active' }),
  lastMap: { characters: [{ name: 'npc', prop_action_entry: {} }] }, avatarName: 'avatar', manualPropRelease: false,
  pollCore: () => ({ refresh: async () => { worldReads++; } }),
});
for (let i = 0; i < 120; i++) poll();
assert.equal(worldReads, 0, 'seated ownership and NPC movement do not keep fast polling alive');
console.log('prop action polling: PASS (real HUD core, shared budget, persistent seat/NPC burst termination)');
