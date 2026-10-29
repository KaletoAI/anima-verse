#!/usr/bin/env node
/** Task 73: real Engine event handlers without WebGL, and Figure bridge resumption without a rig asset. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../..', import.meta.url));
const bundled = await build({
  stdin: { contents: `export { Engine } from './client3d/src/scene/engine.ts';
    export { Figure } from './client3d/src/scene/figures.ts';
    export * as walk from './client3d/src/game/walk.ts';
    export * as THREE from 'three';`, resolveDir: root, loader: 'ts' },
  bundle: true, write: false, platform: 'node', format: 'esm',
});
const { Engine, Figure, walk, THREE } = await import(
  `data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);

function camera() {
  const listeners = new Map();
  const el = { addEventListener: (name, fn) => listeners.set(name, fn), setPointerCapture() {} };
  globalThis.window = { addEventListener() {} };
  const engine = Object.assign(Object.create(Engine.prototype), {
    renderer: { domElement: el }, target: new THREE.Vector3(1, 2, 3), targetDist: 20,
    zoomCap: null, zoomFloor: null, follow: null, targetYaw: 0, pitchOffset: 0, firstPersonZoom: { active: false }, flyT: 0, pointerSeq: 0,
    orbitLast: {}, orbitStart: {},
    groundPoint: () => { throw new Error('drag must not raycast the ground'); },
  });
  const picked = [];
  engine.pickFigure = () => { picked.push('figure'); return false; };
  engine.pickLocation = () => { picked.push('location'); return 'hall'; };
  engine.onPick = id => picked.push(id);
  engine.bindInput(el);
  const emit = (name, x, y, button = 0) => listeners.get(name)({
    clientX: x, clientY: y, button, pointerId: 1, preventDefault() {},
  });
  emit('pointerdown', 100, 100);
  emit('pointermove', 104, 100);
  assert.equal(engine.targetYaw, -.02);
  assert.deepEqual(engine.target.toArray(), [1, 2, 3]);
  assert.equal(engine.flyT, 1);
  emit('pointerup', 104, 100);
  assert.deepEqual(picked, ['figure', 'location', 'hall']); // exactly 4 px still picks
  picked.length = 0;
  emit('pointerdown', 100, 100);
  emit('pointermove', 103, 104);
  emit('pointermove', 100, 100);
  emit('pointerup', 100, 100);
  assert.deepEqual(picked, []);
  assert.deepEqual(engine.target.toArray(), [1, 2, 3]);
  engine.pickFigure = () => { picked.push('object'); return true; };
  emit('pointerdown', 0, 0);
  emit('pointerup', 0, 0);
  assert.deepEqual(picked, ['object']); // figure/prop/vertical action consumes the click
  for (const button of [1, 2]) {
    emit('pointerdown', 0, 0, button);
    emit('pointermove', 10, 8, button);
    emit('pointerup', 10, 8, button);
  }
  assert.equal(engine.pitchOffset, 4);
  assert.deepEqual(picked, ['object']);
  // The follow camera uses exactly the same gesture and never pans its target.
  engine.follow = () => new THREE.Vector3();
  const beforeYaw = engine.targetYaw;
  const beforeTarget = engine.target.clone();
  emit('pointerdown', 0, 0);
  emit('pointermove', 5, 2);
  emit('pointerup', 5, 2);
  assert.ok(Math.abs(engine.targetYaw - (beforeYaw - .025)) < 1e-12);
  assert.deepEqual(engine.target, beforeTarget);
  assert.deepEqual(picked, ['object']);
  engine.follow = null;
  // Cursor zoom still uses the ground helper, independently of pointer dragging.
  engine.groundPoint = () => new THREE.Vector3(11, 0, 3);
  listeners.get('wheel')({ deltaY: -100, preventDefault() {} });
  assert.ok(engine.targetDist < 20 && engine.target.x > 1);
  console.log('controls camera: PASS (orbit, slop, no pan, pick chain, cursor zoom)');
}

function bridges() {
  walk.setMovementPoses(null);
  walk.setClipTransitions([
    { from: 'walk', to: 'idle', kind: 'stop', accel: 0 },
    { from: 'idle', to: 'walk', kind: 'start', accel: 0 },
    { from: 'sit', to: 'walk', kind: 'get-up', accel: 0 },
    { from: 'lie', to: 'walk', kind: 'get-up', accel: 0 },
  ]);
  const figure = new Figure({
    name: 'controls', template: new THREE.Group(), scale: 1, height: 1.7,
    clips: ['idle', 'walk', 'stop', 'start', 'sit', 'lie', 'get-up'].map(name =>
      new THREE.AnimationClip(name, 1, [])),
    tier: 'full', noClips: false, libraryFits: true,
  });
  // Enter walking directly; then install the stop/start rules again.
  walk.setClipTransitions([]);
  figure.play('walk');
  walk.setClipTransitions([
    { from: 'walk', to: 'idle', kind: 'stop', accel: 0 },
    { from: 'idle', to: 'walk', kind: 'start', accel: 0 },
    { from: 'sit', to: 'walk', kind: 'get-up', accel: 0 },
    { from: 'lie', to: 'walk', kind: 'get-up', accel: 0 },
  ]);
  figure.play('idle');
  assert.equal(figure.bridging, true);
  assert.equal(figure.bridgeFrom, 'walk');
  assert.equal(figure.cancelStopBridge('WALK'), true);
  assert.equal(figure.bridging, false);
  assert.equal(figure.bridgeFrom, null);
  assert.equal(figure.paceLimitFor('walk'), 1); // no held frame and no start-walk bridge
  figure.play('walk');
  assert.equal(figure.root.userData.clipKind, 'walk'); // crossfade actually happened
  assert.equal(figure.current.getClip().name, 'walk');
  assert.equal(figure.bridging, false);
  for (const from of ['sit', 'lie', 'idle']) {
    figure.play(from);
    figure.play('walk');
    assert.equal(figure.bridgeFrom, from);
    assert.equal(figure.cancelStopBridge('walk'), false);
    assert.equal(figure.paceLimitFor('walk'), 0);
    figure.cancelBridge();
    assert.equal(figure.bridgeFrom, null);
  }
  // Natural end and the safety deadline both use the same release path.
  figure.play('walk');
  figure.play('idle');
  figure.mixer.update(1.1);
  assert.equal(figure.bridgeFrom, null);
  figure.play('walk');
  figure.play('idle');
  figure.bridgeUntil = -1;
  assert.equal(figure.bridging, false);
  assert.equal(figure.bridgeFrom, null);
  console.log('controls bridges: PASS (stop resumes walking; seat/bed/start holds; release clears source)');
}

const only = process.argv[2];
if (!only || only === 'camera') camera();
if (!only || only === 'bridges') bridges();
