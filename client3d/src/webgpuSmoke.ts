/**
 * webgpu-smoke.html — the BOOT PROBE of the renderer switch: the real `Engine`
 * (both backends, `?webgpu=1` picks WebGPU) with a synthetic stand-in for every
 * building block of the open world, no world server and no login needed. It
 * exists so the WebGPU path can be exercised in a headless Chrome (SwiftShader
 * WebGPU adapter) and by hand in a browser tab, and it reports NUMBERS: the
 * active backend, every console error/warning, draw calls, triangles, GPU
 * time — as JSON in `document.title`, `window.__smoke` and a `<pre>`.
 *
 * Building blocks (mirroring the client): ground plate through the surface
 * factory (matte + water), an InstancedMesh with instanceColor + alphaTest
 * (undergrowth), a SkinnedMesh with an AnimationMixer (figures), an R16F
 * DataTexture (natural-ground height field), a Sprite (name plates), a
 * LineDashed route, linear fog, a shadow-casting sun, and a RenderTarget bake
 * inside the frame (impostors). Whatever three refuses shows up in the error
 * list — that is the point.
 *
 *   ?webgpu=1     WebGPU (else WebGL)
 *   &frames=90    frames to render before reporting (default 90)
 */
import * as THREE from 'three';
import { Engine } from './scene/engine';
import { requestedBackend, gpuFrameMs } from './render/backend';
import { setSurfaceBackend, surfaceMaterialFor } from './render/surface';
import { setSurfaceTextures } from './scene/tiles';

const params = new URLSearchParams(location.search);
const FRAMES = parseInt(params.get('frames') || '90', 10) || 90;

const errors: string[] = [];
const warnings: string[] = [];
const origError = console.error.bind(console);
const origWarn = console.warn.bind(console);
console.error = (...a: unknown[]) => { errors.push(a.map(String).join(' ').slice(0, 300)); origError(...a); };
console.warn = (...a: unknown[]) => { warnings.push(a.map(String).join(' ').slice(0, 300)); origWarn(...a); };
window.addEventListener('error', (e) => errors.push('window: ' + String(e.message).slice(0, 300)));
window.addEventListener('unhandledrejection', (e) => errors.push('rejection: ' + String(e.reason).slice(0, 300)));

function report(obj: Record<string, unknown>): void {
  const json = JSON.stringify(obj);
  document.title = json;
  (window as unknown as { __smoke: unknown }).__smoke = obj;
  const pre = document.createElement('pre');
  pre.id = 'smoke';
  pre.style.cssText = 'position:fixed;left:4px;top:4px;background:rgba(0,0,0,.8);color:#9f9;'
    + 'font:11px monospace;padding:6px;white-space:pre-wrap;max-width:60vw;z-index:9';
  pre.textContent = JSON.stringify(obj, null, 1);
  document.body.appendChild(pre);
  console.info('WEBGPU-SMOKE ' + json);
}

async function main(): Promise<void> {
  const app = document.getElementById('app')!;
  const backend = requestedBackend(location.search);
  const engine = await Engine.create(app, backend);
  setSurfaceBackend(engine.active);
  setSurfaceTextures([]);
  const scene = engine.scene;
  engine.target.set(0, 0, 0);
  engine.dist = engine.targetDist = 30;
  engine.setGameHour(11);

  // 1) ground: matte plate + water plate through the factory (WebGPU -> TSL water)
  const plateGeo = new THREE.PlaneGeometry(40, 40, 8, 8).rotateX(-Math.PI / 2);
  const matte = new THREE.Mesh(plateGeo, surfaceMaterialFor(THREE, { material: { class: 'matte' }, color: 0x6a8f4e }));
  matte.receiveShadow = true;
  scene.add(matte);
  const waterGeo = new THREE.PlaneGeometry(12, 12, 4, 4).rotateX(-Math.PI / 2);
  const waterMat = surfaceMaterialFor(THREE, {
    material: { class: 'water', wave_m: 1.6, speed: 0.3, tint: '#3f7fb8' }, color: 0x3f7fb8,
  });
  const water = new THREE.Mesh(waterGeo, waterMat);
  water.position.set(8, 0.02, 8);
  scene.add(water);

  // 2) undergrowth: InstancedMesh + instanceColor + alphaTest (a cut-out card)
  const cardGeo = new THREE.PlaneGeometry(0.4, 0.6).translate(0, 0.3, 0);
  const cardTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 32;
    const x = c.getContext('2d')!; x.clearRect(0, 0, 32, 32);
    x.fillStyle = '#4c9a3f'; x.beginPath(); x.ellipse(16, 20, 10, 12, 0, 0, Math.PI * 2); x.fill();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const cardMat = new THREE.MeshStandardMaterial({ map: cardTex, alphaTest: 0.5, side: THREE.DoubleSide });
  const inst = new THREE.InstancedMesh(cardGeo, cardMat, 400);
  const m4 = new THREE.Matrix4(), col = new THREE.Color();
  for (let i = 0; i < 400; i++) {
    m4.makeRotationY(Math.random() * Math.PI).setPosition(-15 + Math.random() * 20, 0, -15 + Math.random() * 20);
    inst.setMatrixAt(i, m4);
    inst.setColorAt(i, col.setHSL(0.28 + Math.random() * 0.06, 0.5, 0.35 + Math.random() * 0.2));
  }
  inst.instanceMatrix.needsUpdate = true;
  if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  inst.castShadow = true;
  scene.add(inst);

  // 3) a skinned figure: two bones, a mixer swinging the upper bone
  const bodyGeo = new THREE.CylinderGeometry(0.3, 0.3, 1.8, 8, 4).translate(0, 0.9, 0);
  const pos = bodyGeo.attributes.position;
  const skinIdx = new Uint16Array(pos.count * 4), skinW = new Float32Array(pos.count * 4);
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i);
    const w = THREE.MathUtils.clamp((y - 0.6) / 0.6, 0, 1);
    skinIdx[i * 4] = 0; skinIdx[i * 4 + 1] = 1;
    skinW[i * 4] = 1 - w; skinW[i * 4 + 1] = w;
  }
  bodyGeo.setAttribute('skinIndex', new THREE.BufferAttribute(skinIdx, 4));
  bodyGeo.setAttribute('skinWeight', new THREE.BufferAttribute(skinW, 4));
  const root = new THREE.Bone(); const upper = new THREE.Bone(); upper.position.y = 0.9; root.add(upper);
  const skinned = new THREE.SkinnedMesh(bodyGeo, new THREE.MeshStandardMaterial({ color: 0xc08060 }));
  skinned.add(root); skinned.bind(new THREE.Skeleton([root, upper]));
  skinned.castShadow = true; skinned.frustumCulled = false;
  skinned.position.set(-4, 0, 2);
  scene.add(skinned);
  const clip = new THREE.AnimationClip('sway', 2, [
    new THREE.QuaternionKeyframeTrack('.bones[1].quaternion', [0, 1, 2],
      [...new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -0.4).toArray(),
       ...new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), 0.4).toArray(),
       ...new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -0.4).toArray()]),
  ]);
  upper.name = 'upper'; root.name = 'root';
  const mixer = new THREE.AnimationMixer(skinned);
  mixer.clipAction(clip).play();

  // 4) an R16F data texture (as the natural-ground height field is uploaded)
  const hf = new Uint16Array(16 * 16);
  for (let i = 0; i < hf.length; i++) hf[i] = THREE.DataUtils.toHalfFloat(Math.sin(i * 0.3));
  const r16 = new THREE.DataTexture(hf, 16, 16, THREE.RedFormat, THREE.HalfFloatType);
  r16.minFilter = r16.magFilter = THREE.LinearFilter; r16.needsUpdate = true;
  const r16Probe = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial({ map: r16 }));
  r16Probe.position.set(-8, 1, -8);
  scene.add(r16Probe);

  // 5) sprite + dashed line + a building box that casts a shadow
  const spriteTex = (() => {
    const c = document.createElement('canvas'); c.width = 64; c.height = 32;
    const x = c.getContext('2d')!; x.fillStyle = '#fff'; x.fillRect(0, 0, 64, 32);
    x.fillStyle = '#000'; x.font = '20px sans-serif'; x.fillText('NPC', 6, 24);
    return new THREE.CanvasTexture(c);
  })();
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: spriteTex, depthTest: true }));
  sprite.position.set(-4, 2.4, 2); sprite.scale.set(2, 1, 1);
  scene.add(sprite);
  const lineGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-4, 0.05, 2), new THREE.Vector3(0, 0.05, 6), new THREE.Vector3(6, 0.05, 6)]);
  const line = new THREE.Line(lineGeo, new THREE.LineDashedMaterial({ color: 0xffff00, dashSize: 0.5, gapSize: 0.25 }));
  line.computeLineDistances();
  scene.add(line);
  const box = new THREE.Mesh(new THREE.BoxGeometry(4, 3, 4).translate(0, 1.5, 0),
    new THREE.MeshStandardMaterial({ color: 0xa08060 }));
  box.position.set(4, 0, -6); box.castShadow = box.receiveShadow = true;
  scene.add(box);

  // 6) a render-target bake INSIDE the frame (as the impostor bake does)
  const bakeTarget = new THREE.WebGLRenderTarget(128, 128, {
    minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter,
    generateMipmaps: true, depthBuffer: true,
  });
  const bakeScene = new THREE.Scene();
  bakeScene.add(new THREE.AmbientLight(0xffffff, 2));
  bakeScene.add(new THREE.Mesh(new THREE.SphereGeometry(0.5), new THREE.MeshStandardMaterial({ color: 0xff8040 })));
  const bakeCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10); bakeCam.position.z = 3;
  const baked = new THREE.Mesh(new THREE.PlaneGeometry(2, 2),
    new THREE.MeshBasicMaterial({ map: bakeTarget.texture, alphaTest: 0.5, transparent: false }));
  baked.position.set(-8, 1, 4);
  scene.add(baked);
  let bakes = 0;

  let frames = 0;
  const gpuSamples: number[] = [];
  const cpuSamples: number[] = [];
  const canResolve = 'resolveTimestampsAsync' in engine.renderer;
  engine.addFrameHook((dt) => {
    mixer.update(dt);
    frames++;
    if (frames === 5 || frames === 30) {
      const gl = engine.renderer;
      const prevTarget = gl.getRenderTarget();
      const prevClear = new THREE.Color(); gl.getClearColor(prevClear); const prevAlpha = gl.getClearAlpha();
      gl.setRenderTarget(bakeTarget); gl.setClearColor(0x000000, 0); gl.clear(true, true, false);
      gl.render(bakeScene, bakeCam);
      gl.setRenderTarget(prevTarget as THREE.WebGLRenderTarget | null); gl.setClearColor(prevClear, prevAlpha);
      bakes++;
    }
    if (frames > 10) {
      cpuSamples.push(engine.lastFrameCpuMs);
      const g = gpuFrameMs(engine.renderer); if (g !== null) gpuSamples.push(g);
      if (canResolve) void (engine.renderer as unknown as { resolveTimestampsAsync(): Promise<number> }).resolveTimestampsAsync();
    }
    if (frames === FRAMES) {
      const info = engine.renderer.info;
      const med = (a: number[]) => a.length ? [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)] : null;
      report({
        requested: backend, active: engine.active, frames,
        drawCalls: engine.lastDrawCalls, triangles: engine.lastTriangles,
        geometries: info.memory.geometries, textures: info.memory.textures,
        cpuMsMedian: med(cpuSamples), gpuMsMedian: med(gpuSamples), bakes,
        waterIsNode: (waterMat as { isNodeMaterial?: boolean }).isNodeMaterial === true,
        errors, warnings,
      });
    }
  });
}

main().catch((e) => {
  errors.push('boot: ' + String(e && (e.stack || e)).slice(0, 400));
  report({ requested: requestedBackend(location.search), active: 'none', errors, warnings });
});
