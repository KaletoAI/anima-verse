/**
 * impostors — THE WOOD BEYOND THE CULL LINE.
 *
 * The object LOD ends the scattered MESHES at the player's cull distance
 * (120 m by default, `scene/scatterLod.ts`), and until now it ended the wood
 * with them: a forest 130 m away was bare ground and grew itself out of
 * nothing as one walked in. This module draws that missing half — every
 * scatter entry that HAS a model is drawn as instanced billboard quads from
 * the cull line out to `IMPOSTOR_FAR_M`, at the very positions its meshes
 * would stand at.
 *
 * A RENDER STAGE, NOT AN ASSET. Nothing is authored, nothing is fetched and
 * nothing is stored: the texture of a billboard is BAKED at runtime, once per
 * prop URL, by rendering the entry's own low mesh into a small offscreen
 * target. So a world gains distant woods without a single new file, and a prop
 * somebody adds tomorrow brings its own impostor along.
 *
 * WHAT LIVES WHERE
 *  - the window, the thinning, the yaw and the quad's size and height are
 *    ARITHMETIC and live in `scene/scatterLod.ts`, import-free and checked by
 *    hand in `client3d/scripts/smoke_impostors.mjs`;
 *  - what is HERE is the GPU half: the bake, its cache, and the instanced mesh
 *    the entries draw through. It decides no geometry.
 *  - WHERE the billboards stand is decided by neither: `scene/ground.ts` bins
 *    the entry's own instance positions into this stage on the same LOD tick
 *    that bins the meshes.
 *
 * ONE RENDERER, THE APP'S OWN. The bake borrows the live `WebGLRenderer`
 * (`setImpostorRenderer`, wired in `main.ts`) for a handful of offscreen
 * passes. A second renderer would mean a second WebGL context, a second copy
 * of every texture and program the props already uploaded, and a browser limit
 * of ~16 contexts to trip over — for a job that costs one draw call per prop
 * per SESSION.
 *
 * THE CAMERA CORRIDOR DOES NOT TOUCH THIS, deliberately and without a patch:
 * `applyOcclusionFade` thins out what stands between the camera and the
 * avatar, and its gate closes at 25 m (`OCC_GATE_M`, and it has already faded
 * to nothing at 20 m). Every billboard here is by construction more than
 * 120 m away, so the corridor could not reach one — patching the material
 * would add a varying, a program and four uniforms to buy a discard that can
 * never fire.
 */
import * as THREE from 'three';
import { loadGlb } from './propAssets';
import { IMPOSTOR_ELEV_RAD, impostorBakeVerdict, impostorFrame } from './scatterLod';
import type { ImpostorBakeAttempt, ImpostorFrame } from './scatterLod';

/** Edge length of one baked impostor texture, in pixels.
 *
 *  128 is chosen against the WINDOW, not against taste: a 8 m tree at the near
 *  edge of the stage (120 m) covers about 90 px of a 1080 p screen at the
 *  client's 45° vertical FOV, and less than a third of that over most of the
 *  window. A 128² texture is therefore at or above screen resolution
 *  everywhere it is used, and a whole world of props costs 64 KB each. */
export const IMPOSTOR_TEX_PX = 128;

/** How many baked props are kept. Small on purpose: a world shows a handful of
 *  scatter props at once, and the entries that need one are exactly those
 *  standing in the distance right now. The cache is an LRU (Map insertion
 *  order = last used, see `takeCached`), so a walk across a world of different
 *  woods re-bakes rather than growing without bound.
 *
 *  IT IS A CAP ON THE UNUSED, never on what is on screen: a bake that a
 *  billboard mesh is drawing with is HELD (`acquireImpostor`) and cannot be
 *  evicted however old it is. A cache that dropped a texture out from under a
 *  live material would show a wood of black rectangles, and the number here
 *  would be the only reason. */
export const IMPOSTOR_CACHE_MAX = 16;

/** What one baked prop is: the texture and the FRAME it was rendered in — the
 *  two ratios `impostorQuad` needs to turn an entry's target height into a
 *  quad. */
export interface ImpostorBake {
  texture: THREE.Texture;
  frame: ImpostorFrame;
}

/** One row of the cache. `refs` counts the billboard meshes drawing with it —
 *  two areas scattering the same tree hold the same bake twice — and `target`
 *  is what has to be disposed to free the texture. */
interface CacheEntry {
  bake: ImpostorBake | null;
  target: THREE.WebGLRenderTarget | null;
  refs: number;
}

/** The app's renderer, handed in once at boot (`main.ts`). Null before that
 *  and in every context without a canvas — the bake then simply answers
 *  nothing and the stage stays empty, which is exactly today's picture. A tick
 *  that runs in that window LEARNS NOTHING and remembers nothing (see `bake`):
 *  the props it asked about are asked again once the renderer is there. */
let renderer: THREE.WebGLRenderer | null = null;

/** Wire the ONE renderer of the app into the bake. Called once, from `main.ts`
 *  beside `setPropLoadFocus` — see the file header for why there is no second
 *  renderer here. */
export function setImpostorRenderer(r: THREE.WebGLRenderer): void {
  renderer = r;
}

/** Baked props by URL, in "last used" order. A row whose `bake` is `null`
 *  marks a prop that CANNOT be baked (no mesh in the file, an empty or
 *  degenerate box) — remembered so the tick does not queue the same hopeless
 *  job every second. A prop whose file merely did not ARRIVE gets no row at
 *  all; see `impostorBakeVerdict`. */
const cache = new Map<string, CacheEntry>();
/** Bakes in flight, so two entries scattering the same tree share one pass. */
const inFlight = new Map<string, Promise<void>>();

/** Read the cache AND mark the row as used (Map delete + set moves it to the
 *  back, which is what makes the eviction below an LRU). */
function takeCached(url: string): CacheEntry | undefined {
  const held = cache.get(url);
  if (!held) return undefined;
  cache.delete(url);
  cache.set(url, held);
  return held;
}

/** Drop the least recently used bakes until the cache is back under its cap.
 *
 *  A HELD BAKE IS NEVER DROPPED, whatever its age: `refs` counts the billboard
 *  meshes drawing with its texture, and disposing one of those out from under
 *  a live material is the one failure this cache could cause. When everything
 *  in it is held the pass simply stops and the cache stands over its cap until
 *  a wood is left behind — a bounded overshoot, and the alternative is a
 *  visible defect.
 *
 *  A refusal (`bake: null`) costs no GPU memory but is evicted just the same:
 *  it is a memory of a failure, and a fresh attempt after a walk across the
 *  world is cheaper than a list that never forgets. */
function evict(): void {
  while (cache.size > IMPOSTOR_CACHE_MAX) {
    let victim: string | null = null;
    for (const [url, entry] of cache) {
      if (entry.refs <= 0) { victim = url; break; }
    }
    if (victim === null) return;   // everything in the cache is on screen
    const held = cache.get(victim);
    cache.delete(victim);
    held?.target?.dispose();
  }
}

/**
 * CLAIM the bake of one prop URL, or `null` while there is none.
 *
 * SYNCHRONOUS ON PURPOSE, and that is the whole shape of the feature: the LOD
 * tick asks per entry per second, gets `null` the first time and DRAWS NOTHING
 * — no placeholder, no grey quad, no stand-in that would have to be sized and
 * then swapped. The first answer starts the pass in the background; a second
 * later the same question answers a texture and the wood appears at once.
 *
 * EVERY NON-NULL ANSWER IS A CLAIM, and the caller owes exactly one
 * `releaseImpostor` for it (`scene/ground.ts` claims when it builds an
 * entry's billboard mesh and releases when it tears it down). That is what
 * keeps the LRU from freeing a texture a live material is drawing with — see
 * `evict`. Asking twice claims twice.
 *
 * `near` goes into the GLB download queue exactly as the scatter's own mounts
 * do, so the wood being walked towards is fetched before the one across the
 * map.
 */
export function acquireImpostor(url: string,
                                near?: THREE.Vector3): ImpostorBake | null {
  if (!url) return null;
  const held = takeCached(url);
  if (held) {
    if (held.bake) held.refs += 1;
    return held.bake;
  }
  if (!inFlight.has(url)) {
    inFlight.set(url, bake(url, near).finally(() => { inFlight.delete(url); }));
  }
  return null;
}

/** Give a claimed bake back. The texture is NOT freed here — it stays in the
 *  cache for the next area that scatters the same prop, and only the eviction
 *  above ever disposes one. An unknown URL is silently fine: a release without
 *  a claim can only mean the row was a refusal. */
export function releaseImpostor(url: string): void {
  const held = cache.get(url);
  if (!held) return;
  held.refs = Math.max(0, held.refs - 1);
  evict();
}

/**
 * Render one prop into a render target — the offscreen pass.
 *
 * THE LOADED FILE IS READ, NEVER CHANGED. `loadGlb` caches it, so the very
 * object the scatter takes its geometry from is what arrives here: its
 * materials are left exactly as they are (patching one would set every placed
 * copy of that prop in every scene alight), it is hung into a scene of ours
 * for the length of one render and taken straight back out. The scene sits at
 * the origin with no transform of its own, so nothing measured through the
 * object's world matrix moves while it is in there.
 *
 * The pass never throws, and WHAT IT REMEMBERS OF A FAILURE is decided by
 * `impostorBakeVerdict` and not here: only a prop that cannot be baked at all
 * becomes a refusal (`bake: null`, so the tick stops asking). A download that
 * did not arrive and a tick that ran before the renderer was wired in leave the
 * cache UNTOUCHED — the entry keeps the picture it has for now (nothing beyond
 * the cull line) and the next contact with the window tries again, because a
 * backend that restarts for ten seconds must not cost a wood its billboards for
 * the rest of the session.
 */
async function bake(url: string, near?: THREE.Vector3): Promise<void> {
  const gl = renderer;
  let attempt: ImpostorBakeAttempt = 'no-renderer';
  let baked: CacheEntry | null = null;
  if (gl) {
    let obj: THREE.Object3D | null = null;
    try {
      obj = await loadGlb(url, near);
    } catch {
      obj = null;   // it answers null itself; a throw is the same accident
    }
    if (!obj) {
      // `loadGlb` has already retried three times with backoff before it says
      // this, so it is the backend that went away, not a broken prop.
      attempt = 'load-failed';
    } else {
      try {
        baked = render(gl, obj);
        attempt = baked ? 'baked' : 'unbakeable';
      } catch {
        // The file is HERE and measuring or drawing it still failed — that is a
        // property of this model, so it stays a refusal rather than a job the
        // tick re-queues every second for the rest of the session.
        attempt = 'unbakeable';
      }
    }
  }
  const verdict = impostorBakeVerdict(attempt);
  if (verdict === 'retry') return;
  cache.set(url, verdict === 'store' && baked
    ? baked
    : { bake: null, target: null, refs: 0 });
  evict();
}

/** The lights the bake sees — the world's own midday, roughly
 *  (`scene/engine.ts`).
 *
 *  A BAKED TEXTURE CANNOT FOLLOW THE TIME OF DAY, and this is the honest place
 *  to say so: the billboards keep their midday lighting while the meshes
 *  around them go orange at dusk. It costs nothing visible — the stage begins
 *  at 120 m, where the fog has already taken most of the colour, and the sky
 *  tint of the fog applies to the quads like everything else. Re-baking a
 *  whole world of props on every hour of game time would not. */
function bakeLights(scene: THREE.Scene): void {
  scene.add(new THREE.HemisphereLight(0xdfeeff, 0x8a9a78, 1.5));
  const sun = new THREE.DirectionalLight(0xfff2d8, 2.0);
  // From the camera's side and a little above it, so the silhouette is lit
  // rather than rimmed — a back-lit bake would read as a black cut-out.
  sun.position.set(0.6, 1.4, 1);
  scene.add(sun);
}

/**
 * The pass itself: measure the prop, frame it, render it, hand back the
 * texture.
 *
 * The FRAME is `impostorFrame` and nothing here — the same arithmetic
 * `impostorQuad` uses on the other side, which is what makes the tree's foot
 * land on the ground. What this function adds is only how a frame becomes a
 * camera: an ORTHOGRAPHIC one (a perspective bake would put its own vanishing
 * point into a texture that is then seen from everywhere), raised by
 * `IMPOSTOR_ELEV_RAD`, looking at the frame's centre.
 *
 * The renderer's clear colour, its alpha and its current target are saved and
 * put back: this runs inside the app's own frame loop, and a pass that left
 * the target set would draw the next frame of the world into a 128² texture.
 */
function render(gl: THREE.WebGLRenderer, obj: THREE.Object3D): CacheEntry | null {
  const box = new THREE.Box3().setFromObject(obj);
  if (box.isEmpty()) return null;
  const heightM = box.max.y - box.min.y;
  // From the model ORIGIN, not from the box centre — see `impostorFrame`.
  const radiusM = Math.max(Math.abs(box.min.x), Math.abs(box.max.x),
                           Math.abs(box.min.z), Math.abs(box.max.z));
  const frame = impostorFrame(heightM, radiusM);
  if (!frame) return null;
  const halfH = (frame.spanH * heightM) / 2;
  const halfW = halfH * frame.aspect;

  const scene = new THREE.Scene();
  bakeLights(scene);
  const centreY = (box.min.y + box.max.y) / 2;
  const cam = new THREE.OrthographicCamera(-halfW, halfW, halfH, -halfH, 0.01, 1);
  // Far enough away that the whole prop is in front of the near plane whatever
  // its depth — an orthographic camera does not care how far it stands, only
  // that the box lies between near and far.
  const dist = heightM + radiusM * 2 + 10;
  cam.position.set(0,
                   centreY + Math.sin(IMPOSTOR_ELEV_RAD) * dist,
                   Math.cos(IMPOSTOR_ELEV_RAD) * dist);
  cam.far = dist * 2;
  cam.updateProjectionMatrix();
  cam.lookAt(0, centreY, 0);

  const target = new THREE.WebGLRenderTarget(IMPOSTOR_TEX_PX, IMPOSTOR_TEX_PX, {
    minFilter: THREE.LinearMipmapLinearFilter,
    magFilter: THREE.LinearFilter,
    generateMipmaps: true,
    depthBuffer: true,
  });
  // The pass writes what the screen would show, so the texture holds sRGB and
  // says so — a basic material sampling it then decodes and re-encodes exactly
  // once, and the billboard has the colours the mesh had.
  target.texture.colorSpace = THREE.SRGBColorSpace;

  const prevTarget = gl.getRenderTarget();
  const prevClear = new THREE.Color();
  gl.getClearColor(prevClear);
  const prevAlpha = gl.getClearAlpha();
  const parent = obj.parent;
  try {
    scene.add(obj);
    gl.setRenderTarget(target);
    gl.setClearColor(0x000000, 0);
    gl.clear(true, true, false);
    gl.render(scene, cam);
  } finally {
    // The object goes back where it came from — which is nowhere, today: the
    // scatter only ever reads geometry out of the cached file. Restoring the
    // parent rather than assuming `null` keeps that an accident of the caller
    // instead of a rule this file relies on.
    scene.remove(obj);
    if (parent) parent.add(obj);
    gl.setRenderTarget(prevTarget);
    gl.setClearColor(prevClear, prevAlpha);
  }
  return { bake: { texture: target.texture, frame }, target, refs: 0 };
}

/**
 * The ONE quad geometry of the whole stage: a unit square in the XY plane,
 * centred on its own origin and facing +Z.
 *
 * Module-level and shared by every impostor mesh in the world, because it is
 * the same two triangles every time — the instance matrix carries the size
 * (scale), the facing (yaw about Y) and the place. Never disposed: it is four
 * vertices, and disposing it would break every mesh still holding it.
 */
const QUAD = new THREE.PlaneGeometry(1, 1);

/**
 * What every billboard mesh of this stage is called — the ONE mark that tells
 * the far half of the scatter apart from the near one.
 *
 * The performance readout counts the two stages separately (`scatterCosts` in
 * `game/perfstats.ts`), and it is handed a flat list of drawables
 * (`ground.debugParts().scatter`) in which a billboard and a prop mesh are both
 * an `InstancedMesh`. A NAME rather than a geometry test: a prop whose low mesh
 * happens to be two triangles is still a prop, and a marker that can be read
 * off the object costs the counter nothing.
 */
export const IMPOSTOR_MESH_NAME = 'scatter-impostor';

/**
 * The instanced mesh one scatter entry draws its billboards through.
 *
 * `count` is the entry's FULL instance count: the buffer is allocated once at
 * build size and never grows, the same discipline the two mesh tiers follow —
 * a realloc inside the LOD tick would be a fresh vertex-buffer upload for a
 * camera that walked a metre.
 *
 * The material is this mesh's OWN (the texture is not — that belongs to the
 * bake cache and is shared by every entry scattering the prop):
 *  - `alphaTest` instead of `transparent`, so the quads write depth and need
 *    no sorting at all. A wood of a thousand transparent quads would be sorted
 *    every frame and would still show the seams where two of them cross.
 *  - `MeshBasicMaterial`, because the light is already IN the texture — a lit
 *    material would light the picture of a lit tree twice.
 *  - `fog: true` (three's default, named here because it is the point): the
 *    stage lives in the distance-haze band, and that haze is what makes its far edge
 *    invisible.
 *  - `side: FrontSide` — the quad turns to the camera, so its back is never
 *    seen. Doubling the faces would double the fill for nothing.
 */
export function createImpostorMesh(bake: ImpostorBake, count: number,
): THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material> {
  const material = new THREE.MeshBasicMaterial({
    map: bake.texture,
    alphaTest: 0.5,
    transparent: false,
    fog: true,
    side: THREE.FrontSide,
    toneMapped: false,
  });
  const mesh: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>
    = new THREE.InstancedMesh(QUAD, material, count);
  // The stage's own mark — see `IMPOSTOR_MESH_NAME`.
  mesh.name = IMPOSTOR_MESH_NAME;
  mesh.castShadow = false;
  mesh.receiveShadow = false;
  mesh.frustumCulled = true;
  // Nothing until the first binning — the buffer holds no meaningful matrix
  // yet, exactly as for the mesh tiers.
  mesh.count = 0;
  mesh.visible = false;
  return mesh;
}

/** Free what a mesh of this stage owns: its material. NOT the texture (the
 *  bake cache owns it and other entries may still draw with it) and not the
 *  shared quad geometry. */
export function disposeImpostorMesh(
  mesh: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>,
): void {
  mesh.material.dispose();
  mesh.dispose();
}
