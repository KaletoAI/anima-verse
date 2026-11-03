/** Task 111: production HUD release -> confirmation -> spectator -> take control.
 * Also executes real browser-world arrival/control/report closures with no avatar.
 * Usage: timeout 600 node client3d/scripts/smoke_release_character.mjs
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mainFunction} from './mainFunction.mjs';
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const menu = read('../src/hud/GameMenu.tsx');
assert.ok(menu.includes("t('Release avatar')"), 'menu offers release');
assert.ok(menu.includes('ConfirmDialog'), 'release uses in-app confirmation');
assert.ok(menu.includes('Your avatar leaves the map; you stay signed in.'), 'explains signed-in spectator state');
const hud = read('../src/hud/Hud.tsx');
assert.ok(hud.includes("t('Spectating')") && hud.includes("t('Take control')"), 'spectator has visible state and return action');
const api = read('../src/api.ts');
assert.ok(api.includes('/account/release-character'), 'authenticated release API');
const arrival = await mainFunction('placeAvatarOnArrival', {avatarName:'', awaitArrivalMount:()=>{throw Error('no avatar must not mount arrival');}});
await arrival();
const report = await mainFunction('reportPosWithSeq', {avatarName:'', avatarChanging:false, npcs:{yawOf:()=>0}, positionYaw:x=>x});
await report(1,2,1);
const blockedReport = await mainFunction('reportPosWithSeq', {avatarName:'Traveller', avatarChanging:true, npcs:{yawOf:()=>0}, positionYaw:x=>x});
await blockedReport(1,2,1);
const control = await mainFunction('gameActions.takeControl', {avatarName:'', avatarChanging:false});
control();
const {buildSync}=await import('esbuild');
const cameraCode=buildSync({stdin:{resolveDir:new URL('../../',import.meta.url).pathname,contents:`
export {enterEmbodied} from './client3d/src/game/embody';
export {getGameState} from './client3d/src/hud/bus';
`},bundle:true,write:false,platform:'node',format:'cjs'}).outputFiles[0].text;
const cameraModule={exports:{}};new Function('module','exports',cameraCode)(cameraModule,cameraModule.exports);
const camera={follow:null,zoomCap:null,zoomFloor:null,firstPerson:false,flyTo(){throw Error('spectator must not follow');}};
cameraModule.exports.enterEmbodied({engine:camera,avatarPos:()=>null,avatarEye:()=>null});
assert.equal(cameraModule.exports.getGameState().mode,'overview');
assert.equal(camera.follow,null);assert.equal(camera.zoomCap,null);assert.equal(camera.firstPerson,false);
console.log('PASS spectator world arrival and no position reports; HUD confirmation and takeover wiring');

// Execute the production event closures with explicit state setters. This does
// not need a DOM, worker portal or socket, so it also runs in restricted sandboxes.
import ts from 'typescript';
const source=ts.createSourceFile('GameMenu.tsx',menu,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const handlers={};
function visit(node){
 if(ts.isVariableDeclaration(node)&&['release','takeOver'].includes(node.name.getText(source)))
   handlers[node.name.getText(source)]=node.initializer.getText(source);
 ts.forEachChild(node,visit);
}
visit(source);
let changing=false, marker=0, reloads=0, active='Traveller', error='', switching='', confirm=false, fail=false;
const calls=[];
const deps={
 setConfirmRelease:value=>{confirm=value;},setSwitching:value=>{switching=value;},setCharError:value=>{error=value;},
 gameActions:{avatarChanging:value=>{changing=value;calls.push(['suspend',value]);},markResume:()=>marker++},
 location:{reload:()=>{reloads++;calls.push(['reload',active]);}},
 releaseCharacter:async()=>{calls.push(['release']);assert.equal(changing,true);if(fail)throw Error('offline');active='';},
 switchCharacter:async name=>{assert.equal(changing,true);active=name;calls.push(['switch',name]);},
};
const compile=code=>new Function(...Object.keys(deps),ts.transpileModule('return ('+code+')',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText)(...Object.values(deps));
const release=compile(handlers.release),takeOver=compile(handlers.takeOver);
confirm=true;assert.equal(calls.length,0,'opening confirmation never writes');
confirm=false;assert.equal(active,'Traveller','cancel retains avatar');
confirm=true;fail=true;await release();
assert.equal(error,'offline');assert.equal(changing,false);assert.equal(reloads,0);assert.equal(switching,'');
fail=false;confirm=true;await release();
assert.equal(confirm,false);assert.equal(active,'');assert.equal(marker,1);assert.equal(reloads,1);
assert.deepEqual(calls.at(-1),['reload','']);
await takeOver('Traveller');
assert.equal(active,'Traveller');assert.equal(marker,2);assert.equal(reloads,2);
console.log('PASS production menu handlers: confirm/cancel/failure/release/spectator/take-control');

if (process.argv.includes('--chromium')) {
// Render the real shared HUD in Chromium. Only page navigation is replaced so
// the smoke can rebuild its React root on the next account snapshot.
const {build}=await import('esbuild');
const {spawnSync}=await import('node:child_process');
const {existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync}=await import('node:fs');
const {homedir, tmpdir}=await import('node:os');
const {join}=await import('node:path');
const cache=join(homedir(),'.cache/ms-playwright');
const chrome=(process.env.CHROME_BIN?[process.env.CHROME_BIN]:[
  ...(existsSync(cache)?readdirSync(cache).sort().reverse().map(d=>join(cache,d,'chrome-headless-shell-linux64/chrome-headless-shell')):[]),
  '/usr/bin/chromium','/usr/bin/google-chrome']).find(existsSync);
assert.ok(chrome,'Chromium required');
const dir=mkdtempSync(join(tmpdir(),'release-hud-'));
try {
  const rootDir=new URL('../../',import.meta.url).pathname;
  const script=(await build({stdin:{resolveDir:rootDir,loader:'tsx',contents:`
import React from 'react';
import {flushSync} from 'react-dom';
import {mountHud} from './client3d/src/hud/mount';
import {gameActions} from './client3d/src/hud/bus';
const check=(ok,label)=>{if(!ok)throw Error(label);};
(async()=>{try {
 localStorage.setItem('uiLang','en');
 let active='Traveller', releases=0, switches=0, markers=0, reloads=0, fail=false;
 const suspension=[];
 window.fetch=async(url,init={})=>{
  const path=String(url);
  if(path==='/account/characters')return new Response(JSON.stringify({characters:['Traveller','Resident'],active_character:active,default_character:'Traveller'}));
  if(path==='/account/release-character'){
   releases++;check(suspension.at(-1)===true,'writers suspended before release API');
   if(fail)return new Response('failure',{status:503});
   active='';return new Response(JSON.stringify({status:'success',active_character:''}));
  }
  if(path==='/account/switch-character'){
   switches++;active=JSON.parse(init.body).character_name;
   return new Response(JSON.stringify({status:'success',active_character:active}));
  }
  const body=path==='/play/scene'?{avatar:active,scene:[],rooms:[],present:[],present_detail:[]}:
   path==='/play/messages'?{conversations:[]}:path.includes('prop-actions')?{offers:[],executions:[]}:{};
  return new Response(JSON.stringify(body));
 };
 gameActions.avatarChanging=on=>suspension.push(on);
 gameActions.markResume=()=>markers++;
 const mount=()=>flushSync(()=>mountHud({avatar:active,username:'fixture',role:'user'}));
 window.__avatarReload=()=>{reloads++;mount();};
 const settle=()=>new Promise(resolve=>setTimeout(resolve,50));
 const buttons=()=>[...document.querySelectorAll('button')];
 const click=text=>{const button=buttons().find(b=>b.textContent.trim()===text);check(!!button,'button '+text);flushSync(()=>button.click());};
 mount();await settle();
 // Open the real rail menu, cancel first, then exercise a failed release.
 flushSync(()=>document.querySelector('[aria-label="Menu"]').click());await settle();
 click('Release avatar');check(!!document.querySelector('[role="dialog"]'),'confirmation opens');
 check(releases===0,'menu click does not release');
 click('Cancel');check(!document.querySelector('[role="dialog"]')&&releases===0,'cancel keeps control');
 fail=true;click('Release avatar');
 flushSync(()=>document.querySelector('[role="dialog"] .ga-btn-primary').click());await settle();
 check(active==='Traveller'&&suspension.at(-1)===false&&reloads===0,'failed release resumes controls');
 fail=false;click('Release avatar');
 check(document.querySelector('[role="dialog"]').textContent.includes('Your avatar leaves the map; you stay signed in.'),'consequence shown');
 flushSync(()=>document.querySelector('[role="dialog"] .ga-btn-primary').click());await settle();
 check(active===''&&reloads===1&&markers===1,'release rebuilds same session');
 check(document.body.textContent.includes('Spectating'),'released boot spectates');
 check(!document.querySelector('.hud-chat')&&!document.querySelector('[aria-label="Self"]'),'avatar panels hidden');
 click('Take control');await settle();click('Take over');await settle();
 check(active==='Traveller'&&switches===1&&reloads===2,'take control restores chosen avatar');
 check(!!document.querySelector('.hud-chat'),'composer returns');
 document.body.dataset.result='PASS';
} catch(e){document.body.dataset.result='FAIL';document.body.append(String(e.stack||e));}})();
`},plugins:[{name:'instrument-navigation',setup(b){b.onResolve({filter:/^\.\/sceneTile$/},()=>({path:rootDir+'client3d/src/hud/sceneTile.ts'}));b.onLoad({filter:/[/]GameMenu\.tsx$/},()=>({contents:menu.replaceAll('location.reload();','window.__avatarReload();'),loader:'tsx',resolveDir:rootDir+'client3d/src/hud'}));}}],
 bundle:true,write:false,format:'iife',platform:'browser',loader:{'.css':'empty'},
 nodePaths:[rootDir+'node_modules'],define:{'process.env.NODE_ENV':'"production"'}})).outputFiles[0].text;
  const html=join(dir,'smoke.html');
  writeFileSync(html,`<meta charset="utf-8"><body><div id="hud"></div><script>${script.replaceAll('</script','<\\/script')}</script>`);
  const result=spawnSync(chrome,['--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',`--user-data-dir=${dir}/profile`,'--dump-dom','--virtual-time-budget=3000',`file://${html}`],{encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024});
  assert.equal(result.status,0,JSON.stringify({error:result.error?.message,stderr:result.stderr}));
  assert.match(result.stdout,/data-result="PASS"/,result.stdout.replace(/<script>[\s\S]*?<\/script>/g,''));
  console.log('PASS real React HUD: menu/confirm/cancel/failure/release/spectator/take-control');
} finally {rmSync(dir,{recursive:true,force:true});}

}
