/**
 * Usage: node scripts/smoke_llm_routing_ui.mjs
 * Hand-derived expectations: assigning entry 1 to category chat appends it
 * after entry 0 for task a (orders 1,2), keeps its existing b assignment once,
 * gives empty c order 1, and leaves other-category d untouched. Repeating is
 * a no-op. A group with chains for every task says 'all assigned'; missing a
 * and b says '2 task(s) without LLM: Alpha, Beta'. A fallback to assigned a
 * counts as assigned. Groups start collapsed (nothing stored); a toggle
 * stores the OPENED category under rt-expanded. Overview index 1 is green with ← now, index 0 is muted
 * with (provider off), later index 2 is normal. Filtering alp returns Alpha
 * and Alpine; ArrowDown+Enter selects Alpha, typing custom+Enter or blur
 * commits the literal name. Escape closes the list without choosing a row.
 * Opening a field that holds 'Beta' lists all three names (3 options), not
 * just Beta; reload() while another element has focus keeps the list hidden.
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const routingSource = readFileSync('static/admin/settings-routing.js', 'utf8');
const stored = new Map();
const ctx = vm.createContext({console, localStorage: {getItem:k=>stored.get(k) || null, setItem:(k,v)=>stored.set(k,v)}});
vm.runInContext(routingSource, ctx);
vm.runInContext(`
let messages = [];
let CONFIG = {llm_routing: [{provider:'p',model:'old',tasks:[{task:'a',order:7}]}, {provider:'p',model:'new',tasks:[{task:'b',order:1}]}]};
RT_CATALOG = {tasks:[{id:'a',label:'Alpha',category:'chat'}, {id:'b',label:'Beta',category:'chat'}, {id:'c',category:'chat',gated_off:true}, {id:'d',category:'other'}]};
rtRerender = message => messages.push(message);
touchPath = () => {};
toast = message => messages.push(message);
rtGroupAssign('chat', '1');
`, ctx);
const read = code => vm.runInContext(code, ctx);
assert.equal(read('CONFIG.llm_routing[0].tasks[0].order'), 1);
assert.equal(read("CONFIG.llm_routing[1].tasks.find(t=>t.task==='a').order"), 2);
assert.equal(read("CONFIG.llm_routing[1].tasks.find(t=>t.task==='c').order"), 1);
assert.equal(read('CONFIG.llm_routing[1].tasks.length'), 3);
read("rtGroupAssign('chat','1')");
assert.equal(read('CONFIG.llm_routing[1].tasks.length'), 3);
assert.equal(read('messages.at(-1)'), 'Every task in this group already has this LLM.');
assert.equal(read("rtGroupSummary(RT_CATALOG.tasks.slice(0,2),buildTaskChains(CONFIG.llm_routing),'auto')"), 'all assigned');
assert.equal(read("rtGroupSummary(RT_CATALOG.tasks.slice(0,2),{},'auto')"), '2 task(s) without LLM: Alpha, Beta');
assert.equal(read("rtGroupSummary([{id:'a',label:'Alpha'},{id:'b',fallback:'a'}],{a:[{}]},'auto')"), 'all assigned');
read("function esc(s) { return String(s).replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])); }");
assert.match(read("rtOverviewChainRow({index:1,order:2,provider:'p',model:'m'}, {index:1,order:2})"), /rt-ok.*← now/);
assert.match(read("rtOverviewChainRow({index:0,order:1,skipped:'provider off'}, {index:1,order:2})"), /rt-muted.*\(provider off\)/);
assert.doesNotMatch(read("rtOverviewChainRow({index:2,order:3,skipped:'provider off'}, {index:1,order:2})"), /rt-muted|provider off|← now/);
const overview = read("rtOverviewBody({tasks:[{task:'a',label:'Alpha',category:'chat',via:'direct',resolved:{index:1,order:2,provider:'p',model:'m'},chain:[{index:0,order:1,provider:'off',model:'x',skipped:'provider off'},{index:1,order:2,provider:'p',model:'m'}]}]})");
assert.equal((overview.match(/p \/ m/g) || []).length, 1);
assert.match(overview, /← now/);
const fallbackOverview = read("rtOverviewBody({tasks:[{task:'child',label:'Child',via:'fallback',resolved:{index:1,order:2,provider:'p',model:'m',via_task:'parent'},chain:[{index:1,order:2,provider:'p',model:'m'}]}]})");
assert.match(fallbackOverview, /via parent: p \/ m/);
assert.doesNotMatch(fallbackOverview, /← now/);
assert.equal(read("rtReadExpanded().has('chat')"), false);
read("rtToggleCategory('chat')");
assert.equal(stored.get('rt-expanded'), '["chat"]');
assert.equal(read("rtReadExpanded().has('chat')"), true);
read("rtToggleCategory('chat')");
assert.equal(stored.get('rt-expanded'), '[]');
console.log('PASS group append, deduplication, summary, fallback, overview, collapse persistence');
// Render the actual Tasks page: collapsed groups hide cards; search expands
// matching groups without changing their saved collapsed preference.
ctx.document = {getElementById: () => null};
ctx.ensureModelCaps = async () => {};
ctx.capsKeyFor = (p,m) => p + '/' + m;
ctx.evaluateRoutingMatch = () => ({missing:[]});
ctx.renderRequirementBadges = () => '';
ctx.renderMatchBadges = () => '';
ctx.content = {innerHTML:''};
read(`
const PROVIDERS_CACHE = {}, MODEL_CAPS_CACHE = {};
CONFIG.providers = [{name:'p'}];
RT_TASK_STATE = {runtime_disabled:[],presets:{}};
loadLlmCatalog = async () => RT_CATALOG;
RT_CATALOG.tasks[0].requirements = {};
RT_CATALOG.tasks[1].requirements = {};
`);
await read('renderLlmRoutingTasksPage(content)');
assert.match(ctx.content.innerHTML, /aria-expanded="false"/);
assert.match(ctx.content.innerHTML, /all assigned/);
assert.doesNotMatch(ctx.content.innerHTML, /— a<\/span>/);
read("RT_FILTER.q = 'Alpha'");
await read('renderLlmRoutingTasksPage(content)');
assert.match(ctx.content.innerHTML, /aria-expanded="true"/);
assert.match(ctx.content.innerHTML, /— a<\/span>/);
assert.equal(stored.get('rt-expanded'), '[]');
read("RT_FILTER.q = ''; rtToggleCategory('chat')");
await read('renderLlmRoutingTasksPage(content)');
assert.match(ctx.content.innerHTML, /aria-expanded="true"/);
assert.match(ctx.content.innerHTML, /— a<\/span>/);
console.log('PASS groups start collapsed, opened ones are remembered, search expands');
const elements = {};
function element(value='') {
    return {value,hidden:true,children:[],attrs:{},events:{},innerHTML:'',textContent:'',
        setAttribute(k,v) {this.attrs[k]=v;}, removeAttribute(k) {delete this.attrs[k];},
        addEventListener(k,fn) {this.events[k]=fn;},
        set innerHTML(value) {this.markup=value; this.children=Array.from(value.matchAll(/role="option"/g),()=>({}));},
        get innerHTML() {return this.markup;}};
}
for (const id of ['model','model-list','model-status']) elements[id] = element();
const comboCtx = vm.createContext({document:{getElementById:id=>elements[id]}});
vm.runInContext(readFileSync('static/admin/model-combobox.js','utf8'), comboCtx);
assert.equal(vm.runInContext("ModelCombobox.filter(['Alpha','Beta','Alpine'],'alp').join(',')",comboCtx),'Alpha,Alpine');
const changes = [];
comboCtx.options = {loadModels:async()=>['Alpha','Beta','Alpine'],onChange:v=>changes.push(v)};
const picker = vm.runInContext("ModelCombobox.attach('model', options)",comboCtx);
await picker.open();
const input = elements.model;
input.value='alp'; input.events.input();
const key = k => input.events.keydown({key:k,preventDefault(){}});
key('ArrowDown'); key('Enter');
assert.equal(input.value,'Alpha'); assert.deepEqual(changes,['Alpha']);
input.value='custom'; input.events.input(); key('Enter');
assert.equal(changes.at(-1),'custom');
input.value='blur-name'; input.events.blur(); assert.equal(changes.at(-1),'blur-name');
await picker.open(); key('Escape'); assert.equal(elements['model-list'].hidden,true);
await picker.open();
input.value='Beta'; input.events.input();
elements['model-list'].children[0].onclick();
assert.equal(changes.at(-1), 'Beta');
await picker.open();
input.value='alp'; input.events.input(); key('ArrowUp'); key('Enter');
assert.equal(changes.at(-1), 'Alpine');
input.value='Beta'; await picker.open();
assert.equal(elements['model-list'].children.length, 3);
key('Escape'); comboCtx.document.activeElement = {};
await picker.reload(); assert.equal(elements['model-list'].hidden, true);
console.log('PASS combobox filter, keyboard and click selection, free text, blur, Escape, full list on open, quiet reload');
