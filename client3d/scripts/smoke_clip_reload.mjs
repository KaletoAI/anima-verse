/** Hand-derived reload expectations: two equal revisions swap no table;
 * three signals spaced 100 ms apart fetch once after 1000 ms of quiet.
 * A two-second bridge advanced by 0.25 s must retain its action and time.
 * URL v=2 must fetch new bytes, replacing only the future action binding.
 * No server, disk clip library or WebGL context is used.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const bundle = await build({ stdin: { contents: `export * from './client3d/src/scene/figures'; export * from './client3d/src/game/walk'; export * as THREE from 'three'; export {createSyncHub} from './packages/player-ui/src/syncHub';`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, write: false, platform: 'node', format: 'esm', define: {'import.meta.env.BASE_URL': '\"/\"'} });
const c = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
let revision = 'one', calls = 0;
let rules = [{from:'idle',to:'sit',kind:'old',accel:0}];
globalThis.fetch = async () => { calls++; return {ok:true, json:async()=>({revision,clips:[],transition_clips:rules})}; };
const lib = new c.FigureLibrary();
lib.settle();
assert.equal(await lib.reloadClips(), true);
rules = [{from:'idle',to:'sit',kind:'new',accel:0}];
assert.equal(await lib.reloadClips(), false);
assert.equal(c.clipTransition('idle','sit').kind, 'old');
console.log('PASS [same-revision]');
revision = 'two';
assert.equal(await lib.reloadClips(), true);
assert.equal(c.clipTransition('idle','sit').kind, 'new');
console.log('PASS [new-rule]');

const {THREE} = c;
const clip = name => new THREE.AnimationClip(name, 2, [new THREE.NumberKeyframeTrack('.rotation[x]', [0,2], [0,0.1])]);
const model = {name:'reload-smoke', template:new THREE.Group(), clips:[clip('idle'),clip('old'),clip('sit')], ownClips:[], scale:1,height:1.7,libraryFits:true};
lib.apiModels.set('demo', model);
const figure = lib.instantiate('demo');
c.setClipTransitions([{from:'idle',to:'sit',kind:'old',accel:0}]);
figure.play('sit');
const bridge = figure.transition;
assert.ok(bridge);
figure.mixer.update(0.25);
const time = bridge.time;
revision = 'three';
await lib.reloadClips();
figure.replaceClips([clip('idle'),clip('sit'),clip('new')]);
assert.equal(figure.transition, bridge);
assert.equal(bridge.time,time);
assert.ok(bridge.isRunning());
figure.play('sit');
assert.equal(figure.transition,bridge);
figure.mixer.update(2);
assert.equal(figure.transition,null);
console.log('PASS [mid-bridge]');

// Real timer scheduling with a fake listing transport; a blocked request lets
// pushes arrive while fetch is in flight, independently of the debounce timer.
let release;
let blocked = false;
const normalFetch = globalThis.fetch;
globalThis.fetch = async (...args) => {
  if (blocked) { blocked = false; await new Promise(r => {release = r;}); }
  return normalFetch(...args);
};
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const transport = {onmessage:null, onerror:null, onopen:null, readyState:1, addEventListener(){},close(){}};
const hub = c.createSyncHub({open:()=>transport,setTimeout:()=>null});
hub.onTopics(['clips'],()=>lib.requestClipReload());
const push = () => transport.onmessage({data:JSON.stringify({topics:['clips']})});
const before = calls;
push(); await sleep(100);
push(); await sleep(100);
push(); await sleep(1100);
assert.equal(calls-before,1);
blocked = true;
const inFlight = lib.reloadClips();
await sleep(0);
lib.requestClipReload(); lib.requestClipReload(); lib.requestClipReload();
release(); await inFlight; await sleep(1100);
assert.equal(calls-before,3);
console.log('PASS [debounce]');

const downloads = [];
let sources = [{kind:'dance',url:'/dance.fbx?v=1'}];
globalThis.fetch = async url => url === '/assets/animation-clips'
  ? {ok:true,json:async()=>({revision, clips:sources,transition_clips:[]})}
  : {ok:true,arrayBuffer:async()=>{downloads.push(url);return new ArrayBuffer(1);}};
lib.parseReloadClip = async () => clip('dance');
// Use the real lazy download and figure refresh path; fitting itself is
// orthogonal (covered by the existing figure/bridge numeric smokes).
lib.fitLibraryAsync = async () => ({extra:lib.clipsFor('demo'),fits:true});
revision = 'four'; await lib.reloadClips();
figure.play('dance'); await sleep(20);
assert.deepEqual(downloads,['/dance.fbx?v=1']);
figure.play('idle');
figure.play('dance');
const running = figure.current;
assert.equal(running.getClip().name,'dance');
sources = [{kind:'dance',url:'/dance.fbx?v=2'},{kind:'fresh',url:'/fresh.fbx?v=1'}];
revision = 'five'; await lib.reloadClips();
assert.equal(downloads.length,1); // registration is lazy
figure.play('dance'); await sleep(20);
assert.equal(figure.current,running);
assert.notEqual(figure.actions.get('dance'),running);
assert.deepEqual(downloads,['/dance.fbx?v=1','/dance.fbx?v=2','/fresh.fbx?v=1']);
assert.ok(figure.actions.has('fresh'));
figure.play('fresh'); figure.play('dance');
assert.notEqual(figure.current,running);
sources = []; revision = 'six'; await lib.reloadClips();
const removedRunning = figure.current;
figure.play('dance'); await sleep(20);
assert.equal(figure.current,removedRunning);
assert.equal(figure.actions.has('dance'),false);
figure.play('idle');
figure.dispose();
console.log('PASS [changed-url] (new and removed kinds included)');
console.log('PASS smoke_clip_reload: 5 cases');
