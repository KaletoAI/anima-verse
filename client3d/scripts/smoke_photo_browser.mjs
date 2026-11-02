#!/usr/bin/env node
/** Real Chromium/WebGL: JPEG pixels and size, transient HUD/portal hiding,
 * and the real engine/controller capture hand-off. No server or world needed.
 * Usage: node client3d/scripts/smoke_photo_browser.mjs (CHROME_BIN optional).
 */
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
const cache=join(homedir(),'.cache/ms-playwright');
const candidates=process.env.CHROME_BIN?[process.env.CHROME_BIN]:[
  ...(existsSync(cache)?readdirSync(cache).sort().reverse().map(dir=>join(cache,dir,'chrome-headless-shell-linux64/chrome-headless-shell')):[]),
  '/usr/bin/chromium','/usr/bin/google-chrome'];
const chrome=candidates.find(existsSync); assert.ok(chrome,'Chromium required');
const script=buildSync({stdin:{resolveDir:process.cwd(),contents:`
import * as THREE from 'three';
import {flushSync} from 'react-dom';
import {Engine} from './client3d/src/scene/engine';
import {createPhotoMode} from './client3d/src/game/photoMode';
import {mountPhotoHint} from './client3d/src/hud/photoMode';
import {photoView} from './client3d/src/game/photoView';
const check=(ok,label)=>{if(!ok)throw Error(label);};
(async()=>{try {
  const engine=new Engine(document.getElementById('app'),{antialias:false,shadows:false});
  engine.renderer.setAnimationLoop(null);
  engine.renderer.setPixelRatio(1);engine.renderer.setSize(2400,1200,false);
  engine.scene.background=new THREE.Color(0xe02040);
  const original=engine.camera;
  const update=mountPhotoHint().update;
  let handedOff, failure;
  const complete=new Promise(resolve=>handedOff=resolve);
  const controller=createPhotoMode({engine,view:()=>photoView(engine.camera,[],0),
    hideHud:()=>{document.body.classList.add('photo-mode');return()=>document.body.classList.remove('photo-mode');},
    hint:state=>flushSync(()=>update(state)),error:error=>{failure=error;handedOff();},
    upload:async(jpeg,view)=>{
      check(!engine.photoMode && engine.camera===original,'camera restored before upload');
      check(getComputedStyle(document.getElementById('hud')).visibility==='visible','HUD restored before upload');
      check(jpeg.type==='image/jpeg' && jpeg.size>0,'nonempty JPEG');
      const image=await createImageBitmap(jpeg);
      check(image.width===2048 && image.height===1024,'JPEG downscale');
      const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
      const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
      const pixel=ctx.getImageData(1024,512,1,1).data;
      check(Math.abs(pixel[0]-224)<5 && Math.abs(pixel[1]-32)<5 && Math.abs(pixel[2]-64)<5,'capture contains rendered pixels, not cleared buffer: '+pixel);
      check(view.camera.fov_deg===45,'view accompanies JPEG');image.close();handedOff();
    }});
  window.addEventListener('keydown',event=>controller.keydown(event,false),true);
  const key=(target,key)=>target.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
  const input=document.createElement('textarea');document.getElementById('hud').append(input);input.focus();
  key(input,'F2');check(!engine.photoMode,'F2 ignored while typing');input.blur();
  key(window,'F2');check(engine.photoMode,'F2 enters');
  const modal=document.createElement('div');modal.textContent='late portal';document.body.append(modal);
  for(const node of [document.getElementById('hud'),document.getElementById('frame'),modal])
    check(getComputedStyle(node).visibility==='hidden','HUD, iframe and late portals hidden');
  check(getComputedStyle(engine.labelRenderer.domElement).display==='none','CSS labels hidden');
  // React 18 roots commit asynchronously: let the hint island render before looking for it.
  const settle=()=>new Promise(resolve=>setTimeout(resolve,50));
  await settle();check(!!document.querySelector('.photo-mode-hint'),'hint visible before shot');
  key(window,' ');await settle();check(!document.querySelector('.photo-mode-hint'),'hint removed during capture');
  engine.frame();await complete;if(failure)throw failure;
  key(window,'F2');key(window,'Escape');check(engine.camera===original,'Escape restores');
  document.body.dataset.result='PASS';
} catch(error) {document.body.dataset.result='FAIL';document.body.append(String(error.stack));}})();
`},bundle:true,jsx:'automatic',loader:{'.css':'empty'},format:'iife',write:false,define:{'process.env.NODE_ENV':'"production"'}}).outputFiles[0].text;
const dir=mkdtempSync(join(tmpdir(),'task94-browser-'));
try {
 const html=join(dir,'smoke.html');
 writeFileSync(html,`<meta charset="utf-8"><style>${readFileSync('client3d/src/style.css','utf8')}</style><body><div id="app" style="width:800px;height:600px"></div><div id="hud"></div><iframe id="frame"></iframe><script>${script.replaceAll('</script','<\\/script')}</script>`);
 const result=spawnSync(chrome,['--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader',`--user-data-dir=${dir}/profile`,'--dump-dom','--virtual-time-budget=5000',`file://${html}?lang=en`],{encoding:'utf8',timeout:30000,maxBuffer:8*1024*1024});
 assert.equal(result.status,0,JSON.stringify({error:result.error?.message,stderr:result.stderr}));
 assert.match(result.stdout,/data-result="PASS"/,result.stdout.replace(/<script>[\s\S]*?<\/script>/g,''));
} finally {rmSync(dir,{recursive:true,force:true});}
console.log('PASS photo browser: real WebGL JPEG pixels/size, HUD/iframe/portal/labels, typing, capture and restoration');
