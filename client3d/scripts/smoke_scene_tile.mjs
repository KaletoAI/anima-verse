/** Hand-derived: encode each URL value; avatar wins duplicate Ava; names sort
 * Ava,Bo,Kira independently of payload order. Room/roster changes invalidate
 * renders; pending beats cooldown, which beats a cached signature. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const result = await build({ entryPoints: ['client3d/src/hud/sceneTile.ts'], bundle: true, write: false, format: 'esm', platform: 'browser' });
const { backgroundUrl, exprUrl, tileFigures, sceneKey, tileHidden, renderOutcome, renderedSig, TILE_COLLAPSE_BELOW_PX } = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'));
const s = { avatar:'Ava', location_id:'loc 1', location_name:'Inn', room_id:'r1', room_name:'Hall', present_detail:[{name:'Kira',avatar_url:'',expr_version:'k1'},{name:'Ava',avatar_url:'',expr_version:'a9'},{name:'Bo',avatar_url:''}], avatar_expr_version:'a1', bg_id:'day 1.png', bg_version:'v7', travel:null };
assert.equal(backgroundUrl(s), '/world/locations/loc%201/background?room=r1&file=day%201.png&v=v7');
assert.equal(exprUrl('Kira','k1'), '/characters/Kira/outfit-expression?fallback=default&v=k1');
assert.equal(exprUrl('Bo'), '/characters/Bo/outfit-expression?fallback=default');
assert.deepEqual(tileFigures(s), [{name:'Ava',version:'a1',isAvatar:true},{name:'Kira',version:'k1',isAvatar:false},{name:'Bo',version:'',isAvatar:false}]);
assert.equal(sceneKey(s), 'loc 1/r1|Ava,Bo,Kira');
assert.equal(sceneKey({...s,present_detail:[...s.present_detail].reverse()}), sceneKey(s));
assert.notEqual(sceneKey({...s,room_id:'r2'}), sceneKey(s));
assert.notEqual(sceneKey({...s,present_detail:s.present_detail.slice(0,2)}), sceneKey(s));
assert.equal(tileHidden(s), false);
for (const patch of [{bg_id:''},{location_id:''},{travel:{arrived:false}}]) assert.equal(tileHidden({...s,...patch}), true);
assert.equal(tileHidden({...s,travel:{arrived:true}}), false);
for (const cached of [false,true]) assert.deepEqual(renderOutcome({ok:true,sig:'ab12cd34',cached}), {kind:'show',sig:'ab12cd34'});
assert.deepEqual(renderOutcome({ok:true,sig:'x',cooldown:true,cached:true}), {kind:'cooldown'});
assert.deepEqual(renderOutcome({ok:true,sig:'x',pending:true,cooldown:true}), {kind:'pending'});
assert.deepEqual(renderOutcome({ok:true,sig:''}), {kind:'empty'});
assert.equal(renderedSig({key:'K',sig:'s1'},'K'), 's1');
assert.equal(renderedSig({key:'K',sig:'s1'},'K2'), null);
assert.equal(renderedSig(null,'K'), null);
assert.equal(TILE_COLLAPSE_BELOW_PX, 1200);
assert.deepEqual(tileFigures({...s,avatar:'',present_detail:[]}), []);
console.log('PASS smoke_scene_tile');
