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
  engine.scene.background=new THREE.Color(0x000000);
  const original=engine.camera;
  // Paint real WebGL quadrants at native 2400x1200, top-left red, top-right
  // green, bottom-left blue, bottom-right yellow. Cropping each quarter must
  // yield 1200x600 (no upscale); a full shot downscales to 2048x1024.
  const render=engine.renderer.render.bind(engine.renderer);
  let renders=0;
  engine.renderer.render=(scene,camera)=>{
    render(scene,camera);renders++;
    engine.renderer.setScissorTest(true);
    for(const [x,y,color] of [[0,600,0xff0000],[1200,600,0x00ff00],[0,0,0x0000ff],[1200,0,0xffff00]]) {
      engine.renderer.setScissor(x,y,1200,600);engine.renderer.setClearColor(color);engine.renderer.clear();
    }
    engine.renderer.setScissorTest(false);
  };
  let encoded=null;const toBlob=HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob=function(...args){if(args[1]==='image/jpeg')encoded=this;return toBlob.apply(this,args);};
  const update=mountPhotoHint().update;
  let handedOff,failure,expected,complete;
  const controller=createPhotoMode({engine,view:()=>photoView(engine.camera,[],0),
    hideHud:()=>{document.body.classList.add('photo-mode');return()=>document.body.classList.remove('photo-mode');},
    hint:state=>flushSync(()=>update(state)),error:error=>{failure=error;handedOff();},
    upload:async(jpeg,view)=>{
      check(!engine.photoMode && engine.camera===original,'camera restored before upload');
      check(getComputedStyle(document.getElementById('hud')).visibility==='visible','HUD restored before upload');
      check(jpeg.type==='image/jpeg' && jpeg.size>0,'nonempty JPEG');
      // Headless Chromium under --virtual-time-budget never settles a JPEG decode
      // (createImageBitmap / img.decode hang), so the crop is read from the very
      // 2D canvas the JPEG was encoded from (recorded at toBlob) — exact pixels.
      const canvas=encoded;
      check(!!canvas && canvas.width===expected.width && canvas.height===expected.height,'encoded crop '+(canvas&&canvas.width)+'x'+(canvas&&canvas.height));
      const image={close(){}};
      const ctx=canvas.getContext('2d');
      for(const [x,y,color] of expected.pixels) {
        const pixel=ctx.getImageData(x,y,1,1).data;
        check(color.every((channel,i)=>Math.abs(pixel[i]-channel)<6),'crop pixel '+pixel+' expected '+color);
      }
      check(Math.abs(view.camera.fov_deg-expected.fov)<1e-9,'crop view accompanies JPEG');image.close();handedOff();
    }});
  window.addEventListener('keydown',event=>controller.keydown(event,false),true);
  const key=(target,key)=>target.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
  const settle=()=>new Promise(resolve=>setTimeout(resolve,50));
  const input=document.createElement('textarea');document.getElementById('hud').append(input);input.focus();
  key(input,'F2');check(!engine.photoMode,'F2 ignored while typing');input.blur();
  const modal=document.createElement('div');modal.textContent='late portal';document.body.append(modal);
  const begin=async()=>{
    complete=new Promise(resolve=>handedOff=resolve);failure=null;
    key(window,'F2');check(engine.photoMode,'F2 enters');
    for(const node of [document.getElementById('hud'),document.getElementById('frame'),modal])
      check(getComputedStyle(node).visibility==='hidden','HUD, iframe and late portals hidden');
    check(getComputedStyle(engine.labelRenderer.domElement).display==='none','CSS labels hidden');
    await settle();check(!!document.querySelector('.photo-mode-hint'),'flight hint visible');
    key(window,' ');engine.frame();await settle();
    check(!!document.querySelector('[data-photo-selection]'),'Space opens selection');
    check(document.querySelector('.photo-mode-hint').textContent.includes('Drag to select'),'selection hint');
  };
  const end=async()=>{await complete;if(failure)throw failure;await settle();check(!document.querySelector('[data-photo-selection]'),'selection removed');};
  const pointer=(node,type,x,y)=>node.dispatchEvent(new PointerEvent(type,{pointerId:1,pointerType:'mouse',isPrimary:true,button:0,buttons:type==='pointerup'?0:1,clientX:x,clientY:y,bubbles:true}));
  const colors=[[255,0,0],[0,255,0],[0,0,255],[255,255,0]];
  for(let i=0;i<4;i++) {
    expected={width:1200,height:600,fov:2*Math.atan(Math.tan(Math.PI/8)*.5)*180/Math.PI,pixels:[[600,300,colors[i]]]};
    await begin();
    const selection=document.querySelector('[data-photo-selection]');const box=selection.getBoundingClientRect();
    const x=box.left+(i%2)*box.width/2,y=box.top+Math.floor(i/2)*box.height/2;
    const before=engine.camera.quaternion.clone(),count=renders;
    pointer(selection,'pointerdown',x,y);pointer(selection,'pointermove',x+box.width/2,y+box.height/2);
    await settle();check(selection.textContent.includes('1200 × 600 px'),'live native size');
    // The world and camera may change behind the copied selection; capture must
    // still use its frozen pixels and view. The engine must skip new renders.
    engine.scene.background=new THREE.Color(0xffffff);engine.frame();
    check(renders===count && engine.camera.quaternion.equals(before),'frozen frame and mouse look off');
    pointer(selection,'pointerup',x+box.width/2,y+box.height/2);await end();
  }
  expected={width:2048,height:1024,fov:45,pixels:[[512,256,colors[0]],[1536,256,colors[1]],[512,768,colors[2]],[1536,768,colors[3]]]};
  for(const size of [0,10]) {
    await begin();const selection=document.querySelector('[data-photo-selection]');
    pointer(selection,'pointerdown',100,100);pointer(selection,'pointerup',100+size,100+size);await end();
  }
  await begin();key(window,' ');await end();
  await begin();key(window,'Escape');await settle();
  check(engine.photoMode && !document.querySelector('[data-photo-selection]'),'Esc selection returns to flying');
  key(window,'Escape');check(engine.camera===original,'second Escape restores');
  document.body.dataset.result='PASS';
} catch(error) {document.body.dataset.result='FAIL';document.body.append(String(error.stack));}})();
`},bundle:true,jsx:'automatic',loader:{'.css':'empty'},format:'iife',write:false,define:{'process.env.NODE_ENV':'"production"'}}).outputFiles[0].text;
const dir=mkdtempSync(join(tmpdir(),'task106-browser-'));
try {
 const html=join(dir,'smoke.html');
 writeFileSync(html,`<meta charset="utf-8"><style>${readFileSync('client3d/src/style.css','utf8')}</style><body><div id="app" style="width:800px;height:600px"></div><div id="hud"></div><iframe id="frame"></iframe><script>${script.replaceAll('</script','<\\/script')}</script>`);
 const result=spawnSync(chrome,['--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader',`--user-data-dir=${dir}/profile`,'--dump-dom','--virtual-time-budget=60000',`file://${html}?lang=en`],{encoding:'utf8',timeout:30000,maxBuffer:8*1024*1024});
 assert.equal(result.status,0,JSON.stringify({error:result.error?.message,stderr:result.stderr}));
 assert.match(result.stdout,/data-result="PASS"/,result.stdout.replace(/<script>[\s\S]*?<\/script>/g,''));
} finally {rmSync(dir,{recursive:true,force:true});}
console.log('PASS photo browser: real WebGL frozen quadrant crop pixels, native size/downscale, live size, click/small drag/full, view and restoration');
