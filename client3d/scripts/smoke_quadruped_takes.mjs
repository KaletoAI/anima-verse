#!/usr/bin/env node
/** §4.1/§4.5 hand expectations: five exact take names, exact binding for
 * each catalog kind, sit LoopOnce with clamp and walk LoopRepeat. Unknown
 * flags retain the generic repeat default. FBX has no bone tails: this
 * round trip checks takes and playback, never reconstructed bone tails.
 * Usage: node client3d/scripts/smoke_quadruped_takes.mjs [FBX path]
 * QUADRUPED_FBX is also accepted; file round trip skips when absent.
 */
import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import * as THREE from 'three';
import { FBXLoader } from 'three/addons/loaders/FBXLoader.js';
import { build } from 'esbuild';
const root = resolve(import.meta.dirname, '../..');
const temp = await mkdtemp(join(root, 'client3d/scripts/.smoke-p4-'));
try {
  const result = await build({ stdin: { contents:
    `export { Figure, applyEmbeddedClipLoops } from '${root}/client3d/src/scene/figures';\n` +
    `export { resolveClipKind } from '${root}/client3d/src/scene/clipCoverage';`,
    resolveDir: root, loader: 'ts' }, bundle: true, platform: 'node', format: 'esm',
    write: false, external: ['three', 'three/*'] });
  const module = join(temp, 'client.mjs');await writeFile(module, result.outputFiles[0].text);
  const { Figure, applyEmbeddedClipLoops, resolveClipKind } = await import(pathToFileURL(module));
  const expected = ['idle','walk','run','sit','sit-ground'];
  let template = new THREE.Group();
  let clips = expected.map(name => new THREE.AnimationClip(name, 1, []));
  const path = process.argv[2] || process.env.QUADRUPED_FBX;
  if (path && existsSync(path)) {
    const bytes = await readFile(path);
    // Texture is delivered separately by the client; suppress the browser
    // image load while still using the client's actual FBX parser.
    const load = THREE.TextureLoader.prototype.load;
    THREE.TextureLoader.prototype.load = () => new THREE.Texture();
    const warn = console.warn;
    const weightWarnings = [];
    console.warn = (...args) => {
      if (args.map(String).join(' ').includes('more than 4 skinning weights')) weightWarnings.push(args);
      warn(...args);
    };
    try { template = new FBXLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),''); }
    finally { THREE.TextureLoader.prototype.load = load; console.warn = warn; }
    assert.equal(weightWarnings.length, 0, 'FBXLoader discarded skinning weights beyond four');
    console.log('FBXLoader excess-weight warnings:', weightWarnings.length);
    clips = template.animations;
    console.log('FBXLoader take names:', JSON.stringify(clips.map(c => c.name)));
    assert.deepEqual(clips.map(c => c.name).sort(), [...expected].sort());
  } else console.log('SKIP FBX round trip: provide FBX argument or QUADRUPED_FBX');
  applyEmbeddedClipLoops(clips, { sit: { loop: false }, 'sit-ground': { loop: false }, walk: { loop: true } });
  for (const kind of expected) assert.equal(resolveClipKind(kind, clips.map(c => c.name)),kind);
  const figure = new Figure({ name:'p4',template,clips,scale:1,height:1,assignOnly:true,
    noClips:false,tier:'full',libraryFits:false });
  for (const kind of expected) {
    figure.play(kind);
    const action = figure.actions.get(kind);
    assert.ok(action, `missing exact binding: ${kind}`);
    if (kind === 'sit' || kind === 'sit-ground') { assert.equal(action.loop,THREE.LoopOnce);assert.equal(action.clampWhenFinished,true); }
    if (kind === 'walk') assert.equal(action.loop,THREE.LoopRepeat);
  }
  console.log('PASS exact take binding and generic loop flags');
} finally { await rm(temp,{recursive:true,force:true}); }
