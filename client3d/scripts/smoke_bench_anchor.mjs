/**
 * Usage: node client3d/scripts/smoke_bench_anchor.mjs
 *
 * Bench anchor selection (`client3d/src/bench/benchAnchor.ts`): position from
 * the WORLDMAP rows, `&goto=` → avatar location → origin.
 *
 * Fixture (worldmap rows, in this order) and height rule h(x,z) = 0.5x - 0.25z:
 *   harbor  "Old Market"   (10, -4)   h = 5 + 1  = 6
 *   market  "Harbor Gate"  (30,  8)   h = 15 - 2 = 13
 *   shed    ""             (undefined, 5)  -> unplaced; nameOf gives "Fisher Shed"
 *   tower   null           (20, 40)   h = 10 - 10 = 0; nameOf gives "Lighthouse"
 *   reef    "Reef"         (NaN, 3)   -> unplaced (non-finite)
 *
 * Hand-derived expectations:
 *   goto=MARKET   id "market" matches exactly (case-insensitive), so it beats
 *                 the EARLIER row "Old Market" whose name only contains it -> [30,13,8].
 *   goto=harbor g no id is "harbor g"; name substring of "Harbor Gate" -> [30,13,8].
 *   goto=old MAR  name substring, case-insensitive, of "Old Market" -> [10,6,-4].
 *   goto=light    row has no name; the nameOf fallback "Lighthouse" matches -> [20,0,40].
 *   goto=shed / goto=fisher / goto=reef / goto=nowhere -> throw (unplaced or unknown).
 *   no goto, current "harbor" -> [10,6,-4]; current "shed" (pos_x undefined) -> origin;
 *   no goto, no current -> {pos:[0,0,0], locationId:null, heightSource:'world origin'}.
 *   goto="" (a bare `&goto=`) counts as no goto -> avatar location.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const built = await build({entryPoints:['client3d/src/bench/benchAnchor.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {pickBenchAnchor} = await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));

const rows = [
  {id:'harbor', name:'Old Market', pos_x:10, pos_z:-4},
  {id:'market', name:'Harbor Gate', pos_x:30, pos_z:8},
  {id:'shed', name:'', pos_x:undefined, pos_z:5},
  {id:'tower', name:null, pos_x:20, pos_z:40},
  {id:'reef', name:'Reef', pos_x:NaN, pos_z:3},
];
const names = {shed:'Fisher Shed', tower:'Lighthouse'};
const HS = 'test height';
let heightCalls = 0;
const pick = (goto, currentId) => pickBenchAnchor({goto, rows, currentId, heightSource:HS,
  nameOf: id => names[id], heightAt: (x, z) => { heightCalls++; return 0.5*x - 0.25*z; }});

assert.deepEqual(pick('MARKET'), {pos:[30,13,8], locationId:'market', heightSource:HS});
assert.deepEqual(pick('harbor g'), {pos:[30,13,8], locationId:'market', heightSource:HS});
assert.deepEqual(pick('old MAR'), {pos:[10,6,-4], locationId:'harbor', heightSource:HS});
assert.deepEqual(pick('light'), {pos:[20,0,40], locationId:'tower', heightSource:HS});
for (const goto of ['shed', 'fisher', 'reef', 'nowhere']) {
  assert.throws(() => pick(goto), /Bench goto location is unknown or unplaced/, goto);
}
assert.deepEqual(pick(null, 'harbor'), {pos:[10,6,-4], locationId:'harbor', heightSource:HS});
assert.deepEqual(pick('', 'harbor'), {pos:[10,6,-4], locationId:'harbor', heightSource:HS});
heightCalls = 0;
const origin = {pos:[0,0,0], locationId:null, heightSource:'world origin'};
assert.deepEqual(pick(null, 'shed'), origin);
assert.deepEqual(pick(undefined, undefined), origin);
assert.deepEqual(pickBenchAnchor({rows:[], heightAt:() => 99, heightSource:HS}), origin);
assert.equal(heightCalls, 0, 'origin must not sample the height field');
console.log('PASS smoke_bench_anchor');
