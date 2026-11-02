#!/usr/bin/env node
/** Hand-derived framing: 90° vertical FOV, aspect 2, z=-10 gives x edges ±20,
 * y edges ±10. Camera at y=3 over floor y=1 is 2 m high. Euclidean head
 * distance at (-20,3,-10) is sqrt(500). A 30° downward look has pitch -30°.
 * Catches inverted screen axes, behind-camera inclusion and wrong pitch/depth.
 * Usage: node client3d/scripts/smoke_photo_view.mjs
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const built = await build({ stdin: { contents: `export * from './client3d/src/game/photoView.ts'; export * as THREE from 'three';`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, write: false, platform: 'node', format: 'esm' });
const { photoView, cropPhotoView, THREE } = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const camera = new THREE.PerspectiveCamera(90, 2, 0.2, 100);
camera.position.set(0, 3, 0);
const subjects = [
  ['centre', [0, 3, -10]], ['left', [-20, 3, -10]], ['right', [20, 3, -10]],
  ['top', [0, 13, -10]], ['bottom', [0, -7, -10]], ['behind', [0, 3, 10]],
  ['outside', [21, 3, -10]], ['near', [0, 3, -0.1]], ['far', [0, 3, -101]],
].map(([name, head]) => ({ name, head }));
const view = photoView(camera, subjects, 1);
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
assert.deepEqual(view.visible.map(v => v.name), ['centre', 'left', 'right', 'top', 'bottom']);
close(view.visible[0].screen_x, .5); close(view.visible[0].screen_y, .5);
close(view.visible[1].screen_x, 0); close(view.visible[2].screen_x, 1);
close(view.visible[3].screen_y, 0); close(view.visible[4].screen_y, 1);
close(view.visible[1].depth_m, 22.360679774997898);
close(view.camera.height_m, 2); close(view.camera.fov_deg, 90);
camera.rotation.x = -Math.PI / 6;
close(photoView(camera, [], 1).camera.pitch_deg, -30);
close(photoView(camera, [], 4).camera.height_m, 0);
console.log('PASS photo view: frustum edges, axes, near/far/behind, depth, height and pitch');

// Crop hand numbers shared with native PhotoTests: central half of 90° gives
// 2 atan(.5)=53.13010235415598°. Upper third centre ray is atan(2/3)=33.690067525979785°.
assert.deepEqual(cropPhotoView(view,{x:0,y:0,width:1200,height:600},1200,600),view);
const cropped=cropPhotoView(view,{x:0,y:150,width:600,height:300},1200,600);
assert.deepEqual(cropped.visible.map(v=>v.name),['centre','left']);
close(cropped.visible[0].screen_x,1);close(cropped.visible[0].screen_y,.5);
close(cropped.visible[1].screen_x,0);close(cropped.visible[1].depth_m,22.360679774997898);
close(cropped.camera.fov_deg,53.13010235415598);close(cropped.camera.height_m,2);
close(cropPhotoView(view,{x:0,y:0,width:1200,height:200},1200,600).camera.pitch_deg,33.690067525979785);
const downView={...view,camera:{...view.camera,pitch_deg:-30}};
close(cropPhotoView(downView,{x:0,y:0,width:1200,height:200},1200,600).camera.pitch_deg,3.690067525979785);
// Off-axis centre (right half) at pitch 30°: asin(sin(30)/sqrt(2)) = 20.704811054635428°.
close(cropPhotoView({...view,camera:{...view.camera,pitch_deg:30}},
  {x:600,y:0,width:600,height:600},1200,600).camera.pitch_deg,20.704811054635428);
console.log('PASS photo crop: identity, edges, exclusion, normalization, FOV, centre ray pitch and preserved height/depth');
