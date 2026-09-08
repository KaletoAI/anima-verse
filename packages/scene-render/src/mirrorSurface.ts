/**
 * MIRROR PANES (preset `mirror`, plan-spiegelflaechen.md) — a slot material
 * becomes a planar reflector on ITS OWN faces.
 *
 * Part 1 is pure arithmetic, so a smoke can pin it without WebGL: the plane a
 * pane is measured from, and the per-frame budget. Part 2 is what needs a GPU
 * — the mirror material, the reflection pass hooked onto the mesh, and the
 * lifecycle of both.
 *
 * THE PLANE IS MEASURED HERE, ONCE. The server's area detection reports a
 * centroid and a normal on the model sidecar, but the payload carries only
 * `{preset: "mirror"}`: the pane's plane is a property of the mesh in front of
 * the renderer, both renderers call this one routine, and a value measured in
 * one place cannot drift between them. `scripts/smoke_mirror_plane.mjs` pins
 * the arithmetic with hand-derived numbers and can cross-check a local prop
 * against its sidecar (§ B5a — numbers, never screenshots).
 *
 * EXPECTED NOISE: a mirror pane that also goes through `applyDepthCut` gets
 * its material cloned, and `UniformsUtils.clone` refuses to copy a render
 * target's texture — three logs `UniformsUtils: Textures of render targets
 * cannot be cloned` once per clone and leaves the copy's `tDiffuse` at null.
 * That warning is expected and harmless here: `renderMirror` writes the render
 * target back onto whatever material is actually being drawn, every draw.
 */

import type { BufferGeometry, Camera, IUniform, Material, Matrix3, Matrix4,
  Mesh, Object3D, OrthographicCamera, PerspectiveCamera, Plane, Scene,
  ShaderMaterial, Vector3, Vector4, WebGLRenderer,
  WebGLRenderTarget } from 'three'

/** How much the faces of one group have to agree on their side before the
 *  group counts as a plane: |Σ face vectors| / Σ |face vectors|. 1 is a flat
 *  group, 0 is one that cancels itself out.
 *
 *  0.9 is measured, not guessed: the two panes of a local wall-mirror prop
 *  score 1.0000, while the 134 slivers of a door-glass prop (0.006 m²) score
 *  0.7384 and put their normal 87° off the same prop's sidecar. The threshold
 *  has to sit between those two, and near the flat end — a pane a renderer can
 *  mirror is FLAT, not merely more coherent than noise. */
const FACE_COHERENCE_MIN = 0.9

export interface MirrorPlane {
  /** Area-weighted centroid of the faces, in the geometry's own space. */
  point: [number, number, number]
  /** Unit normal by the faces' winding (right-hand rule). The render hook
   *  flips it towards the camera per frame, so the sign only has to be
   *  consistent, not "outward". */
  normal: [number, number, number]
}

/** The raw sums a set of faces produces. Measured ONCE, because the mirror
 *  needs the same numbers twice: to build the plane, and to say why there is
 *  none when there is none. */
interface FaceMoments {
  /** Σ (b-a)×(c-a) — each face's normal, scaled by twice its area. */
  sum: [number, number, number]
  /** Σ face centroid · |(b-a)×(c-a)|. */
  moment: [number, number, number]
  /** Σ |(b-a)×(c-a)| — twice the total area. */
  weight: number
  /** |Σ (b-a)×(c-a)|. */
  len: number
  /** How many faces had any area at all. */
  faces: number
}

/** Walk the faces of `ranges` and add them up. `ranges` are `[start, count]`
 *  pairs in three's `geometry.groups` convention — INDEX units when `index` is
 *  given, VERTEX units otherwise; a `count` past the end is clamped (three
 *  itself stores `Infinity` for "the rest"). */
function faceMoments(
  positions: ArrayLike<number>,
  index: ArrayLike<number> | null,
  ranges: ReadonlyArray<readonly [number, number]>,
): FaceMoments {
  const total = index ? index.length : Math.floor(positions.length / 3)
  const vert = (i: number): [number, number, number] => {
    const v = index ? index[i] : i
    return [positions[v * 3], positions[v * 3 + 1], positions[v * 3 + 2]]
  }
  let nx = 0, ny = 0, nz = 0          // sum of (b-a)×(c-a) = 2·area·normal
  let cx = 0, cy = 0, cz = 0          // sum of centroid·(2·area)
  let weight = 0
  let faces = 0
  for (const [start, count] of ranges) {
    const s = Math.max(0, Math.floor(start))
    const end = Math.min(total, s + Math.max(0, Math.floor(count)))
    for (let i = s; i + 2 < end; i += 3) {
      const a = vert(i), b = vert(i + 1), c = vert(i + 2)
      const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]
      const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]
      const fx = uy * vz - uz * vy
      const fy = uz * vx - ux * vz
      const fz = ux * vy - uy * vx
      const twiceArea = Math.sqrt(fx * fx + fy * fy + fz * fz)
      if (twiceArea <= 0) continue
      nx += fx; ny += fy; nz += fz
      cx += (a[0] + b[0] + c[0]) / 3 * twiceArea
      cy += (a[1] + b[1] + c[1]) / 3 * twiceArea
      cz += (a[2] + b[2] + c[2]) / 3 * twiceArea
      weight += twiceArea
      faces += 1
    }
  }
  return {
    sum: [nx, ny, nz],
    moment: [cx, cy, cz],
    weight,
    len: Math.sqrt(nx * nx + ny * ny + nz * nz),
    faces,
  }
}

/** A plane, or the one sentence that says why there is none. `why` is empty
 *  exactly when `plane` is set — the mirror puts it straight into a warning,
 *  so it has to read as an explanation, not as an error code. */
interface FaceMeasurement {
  plane: MirrorPlane | null
  why: string
}

/**
 * The plane through a set of triangles, WITH the reason when there is none.
 *
 * Three ways a group fails to be a plane, and each is a different sentence:
 *
 *  - NO AREA. Every face is degenerate (three identical points, a collapsed
 *    strip). Nothing to measure at all.
 *  - CANCELLING FACES. The face vectors sum to zero: the classic shape is a
 *    pane modelled as two opposite skins inside ONE material group.
 *  - NO COHERENT PLANE. `len / weight` under `FACE_COHERENCE_MIN` — the faces
 *    point in too many directions to call any of them "the" plane. Sliver
 *    noise lands here.
 *
 * A vertex index past the end of `positions` reads `undefined` and poisons
 * every sum with NaN; a NaN plane is not a plane either, so that is its own
 * reason rather than a mirror pointing at nothing.
 */
function measureFaces(
  positions: ArrayLike<number>,
  index: ArrayLike<number> | null,
  ranges: ReadonlyArray<readonly [number, number]>,
): FaceMeasurement {
  const m = faceMoments(positions, index, ranges)
  const fail = (why: string): FaceMeasurement => ({ plane: null, why })
  if (!Number.isFinite(m.len) || !Number.isFinite(m.weight)
      || !m.moment.every((v) => Number.isFinite(v))) {
    return fail('a vertex index reaches past the position buffer')
  }
  if (!m.faces || m.weight <= 1e-12) {
    return fail('no face of the group has any area')
  }
  if (m.len <= 1e-12) {
    return fail(`its ${m.faces} faces cancel out exactly `
      + '(two opposite skins in one material group)')
  }
  const ratio = m.len / m.weight
  if (ratio < FACE_COHERENCE_MIN) {
    return fail(`its ${m.faces} faces have no coherent plane `
      + `(ratio ${ratio.toFixed(4)} < ${FACE_COHERENCE_MIN}, `
      + `${(m.weight / 2).toFixed(6)} m² of surface)`)
  }
  return {
    plane: {
      point: [m.moment[0] / m.weight, m.moment[1] / m.weight,
              m.moment[2] / m.weight],
      normal: [m.sum[0] / m.len, m.sum[1] / m.len, m.sum[2] / m.len],
    },
    why: '',
  }
}

/**
 * The plane through a set of triangles. `ranges` are `[start, count]` pairs in
 * three's `geometry.groups` convention — INDEX units when `index` is given,
 * VERTEX units otherwise; a `count` past the end is clamped (three itself
 * stores `Infinity` for "the rest"). Returns `null` when the faces have no
 * measurable plane; `measureFaces` above enumerates the three ways that
 * happens and is what `attachMirror` uses, because it also wants to SAY which
 * one it hit.
 *
 * THE COHERENCE RULE, because it is the surprising one: with
 * `len` = |Σ (b-a)×(c-a)| and `weight` = Σ |(b-a)×(c-a)|, the ratio
 * `len / weight` is 1 for a flat group and 0 for one whose face vectors cancel
 * exactly; under `FACE_COHERENCE_MIN` the group has no side worth mirroring.
 * That is the shape of a real defect — a pane modelled as TWO opposite skins
 * in one material group averages to no normal at all, and a group that is
 * mostly sliver noise points nowhere. Both would render a reflection off a
 * plane nobody can see, and better no mirror than a wrong one: a door-glass
 * prop whose 134 slivers (0.006 m²) score 0.7384 puts its measured normal 87°
 * off its own sidecar, while a real wall mirror's panes score 1.0000.
 */
export function planeOfFaces(
  positions: ArrayLike<number>,
  index: ArrayLike<number> | null,
  ranges: ReadonlyArray<readonly [number, number]>,
): MirrorPlane | null {
  return measureFaces(positions, index, ranges).plane
}

/**
 * How many reflections a frame may render, across every mirror of the app.
 *
 * The frame is `renderer.info.render.frame`, and every reflection IS a nested
 * `renderer.render`, which bumps that counter by one before the next hook of
 * the same top-level frame runs. So "the same frame" is `frame === expected`
 * where `expected` is the last frame seen plus the nested renders granted
 * since; anything else is a new frame and resets the count.
 */
export class MirrorBudget {
  private used = 0
  private expected = Number.NaN
  constructor(private readonly maxPerFrame: number) {}

  allow(frame: number): boolean {
    if (frame !== this.expected) this.used = 0
    this.expected = frame
    if (this.used >= this.maxPerFrame) return false
    this.used += 1
    this.expected = frame + 1
    return true
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * Part 2: the material, the render hook and the mesh's lifecycle.
 *
 * The camera/oblique-clip arithmetic below is three's
 * `examples/jsm/objects/Reflector.js` (MIT), reduced to a per-MATERIAL hook on
 * a mesh the app did not model itself: Reflector owns its own plane geometry
 * and mirrors "my local +z", while a slot pane is one material group of a
 * prop's GLB, so the plane is the measured value of part 1.
 * ───────────────────────────────────────────────────────────────────────── */

/** The app's view policy for mirrors — cost, not look. */
export interface MirrorOptions {
  /** Edge of the square render target in pixels (default 512). */
  textureSize?: number
  /** Reflections rendered per frame across ALL mirrors (default unlimited).
   *  A mirror over budget keeps its last texture. */
  maxPerFrame?: number
  /** Beyond this camera distance in metres a mirror keeps its last texture
   *  (default unlimited). */
  maxDistanceM?: number
}

/** What "mirror" MEANS, for both renderers: a neutral silver overlay on the
 *  reflection and the near-plane bias that keeps the pane's own frame from
 *  bleeding into the reflection. */
export const MIRROR_PRESET = {
  tint: 0x777777,
  textureSize: 512,
  clipBias: 0.003,
} as const

/** Reflector.js's shader with the clipping-plane chunks added, so a mirror
 *  prop under `applyDepthCut` is cut like the rest of its mesh (needs
 *  `clipping: true` on the material and `renderer.localClippingEnabled`). */
const MIRROR_VERTEX = /* glsl */ `
uniform mat4 textureMatrix;
varying vec4 vUv;
#include <common>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
  vUv = textureMatrix * vec4(position, 1.0);
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPosition;
  #include <logdepthbuf_vertex>
  #include <clipping_planes_vertex>
}`

const MIRROR_FRAGMENT = /* glsl */ `
uniform vec3 color;
uniform sampler2D tDiffuse;
varying vec4 vUv;
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
float blendOverlay(float base, float blend) {
  return (base < 0.5 ? (2.0 * base * blend) : (1.0 - 2.0 * (1.0 - base) * (1.0 - blend)));
}
vec3 blendOverlay(vec3 base, vec3 blend) {
  return vec3(blendOverlay(base.r, blend.r), blendOverlay(base.g, blend.g), blendOverlay(base.b, blend.b));
}
void main() {
  #include <clipping_planes_fragment>
  #include <logdepthbuf_fragment>
  vec4 base = texture2DProj(tDiffuse, vUv);
  gl_FragColor = vec4(blendOverlay(base.rgb, color), 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`

/** The shader's uniform template. Cloned per pane (as Reflector.js does), so
 *  no two mirrors ever share a uniform object. */
const MIRROR_UNIFORMS: { [name: string]: IUniform } = {
  color: { value: null },
  tDiffuse: { value: null },
  textureMatrix: { value: null },
}

/** Everything one mirror pane owns: its plane in the mesh's space, its render
 *  target, and the reflection cameras (one per camera that ever looked at it,
 *  as Reflector.js does). */
interface MirrorState {
  mesh: Mesh
  slot: string
  plane: MirrorPlane
  rt: WebGLRenderTarget
  budget: MirrorBudget
  maxPerFrame: number
  maxDistanceM: number
  cameras: WeakMap<Camera, Camera>
  textureMatrix: Matrix4
  material: Material
}

/** The states of a mesh, by slot name — the hook finds its state through the
 *  MATERIAL it is handed (`userData.__mirror`), because a depth cut clones
 *  the material after this routine and a clone must still find its target. */
const meshStates = new WeakMap<Object3D, Map<string, MirrorState>>()
/** The original `onBeforeRender` of every mesh this module hooked. */
const originalHooks = new WeakMap<Object3D, Mesh['onBeforeRender']>()
/** The material → state link `disposeMirror` needs. */
const stateOfMaterial = new WeakMap<Material, MirrorState>()

/** One recursion guard for the whole page: while a mirror pass renders the
 *  scene, no mirror — not even one in another placement — starts its own
 *  pass. It keeps its last texture instead, which is the one-bounce
 *  reflection and costs nothing. */
let inMirrorPass = false

/** The vectors and matrices `renderMirror` works in. three's classes are a
 *  PARAMETER of this package, so they cannot be module constants — they are
 *  built on the first reflection instead, and only from inside `renderMirror`,
 *  so `attachMirror`'s constructor path stays the short list a smoke can stub.
 *  ONE set serves every mirror on the page: the recursion guard above means no
 *  two panes are ever mid-pass at the same time, and each pass writes every
 *  slot it reads before it reads it. */
interface MirrorScratch {
  mirrorPos: Vector3
  normal: Vector3
  cameraPos: Vector3
  view: Vector3
  lookAt: Vector3
  target: Vector3
  rotation: Matrix4
  normalMatrix: Matrix3
  clipPlane: Plane
  clip: Vector4
  q: Vector4
}
let scratch: MirrorScratch | null = null

function mirrorScratch(THREE: typeof import('three')): MirrorScratch {
  if (!scratch) {
    scratch = {
      mirrorPos: new THREE.Vector3(),
      normal: new THREE.Vector3(),
      cameraPos: new THREE.Vector3(),
      view: new THREE.Vector3(),
      lookAt: new THREE.Vector3(),
      target: new THREE.Vector3(),
      rotation: new THREE.Matrix4(),
      normalMatrix: new THREE.Matrix3(),
      clipPlane: new THREE.Plane(),
      clip: new THREE.Vector4(),
      q: new THREE.Vector4(),
    }
  }
  return scratch
}

type GroupRange = readonly [number, number]

/** The index/vertex ranges of ONE material of a mesh (three's groups). */
function rangesOf(geometry: BufferGeometry, materialIndex: number | null): GroupRange[] {
  const total = geometry.index ? geometry.index.count : geometry.attributes.position.count
  if (materialIndex === null) return [[0, total]]
  const own = (geometry.groups || []).filter((g) => g.materialIndex === materialIndex)
  return own.map((g) => [g.start, g.count] as const)
}

/**
 * Make ONE material of `mesh` a mirror. Measures the plane from that
 * material's faces; returns the new material (already on the mesh) or `null`
 * when nothing can be measured — then the mesh is left exactly as it was.
 *
 * `materialIndex` is the position in `mesh.material` when that is an array,
 * `null` for a single material.
 *
 * A pane that CANNOT be measured says so once, on the console, naming the slot
 * and the reason. Silence would be the worst answer available: the author
 * picked `mirror` in the admin and would see a plain pane with nothing
 * anywhere to say the model is the problem, not the setting.
 */
export function attachMirror(
  THREE: typeof import('three'),
  mesh: Mesh,
  src: Material,
  materialIndex: number | null,
  slot: string,
  opts: MirrorOptions = {},
): Material | null {
  const geometry = mesh.geometry
  const pos = geometry?.attributes?.position
  if (!pos) {
    console.warn(`mirror slot "${slot}": the mesh carries no position `
      + 'attribute — left as modelled')
    return null
  }
  const measured = measureFaces(pos.array as ArrayLike<number>,
    geometry.index ? (geometry.index.array as ArrayLike<number>) : null,
    rangesOf(geometry, materialIndex))
  const plane = measured.plane
  if (!plane) {
    console.warn(`mirror slot "${slot}": ${measured.why} — left as modelled`)
    return null
  }

  // Attaching the SAME slot of the SAME mesh again (a re-applied placement)
  // has to free the pane that is already there, or its render target leaks and
  // the mesh's hook bookkeeping counts a state no material points at any more.
  const previous = meshStates.get(mesh)?.get(slot)
  if (previous) disposeMirror(previous.material)

  const size = Math.max(16, Math.floor(opts.textureSize ?? MIRROR_PRESET.textureSize))
  const maxPerFrame = opts.maxPerFrame ?? Number.POSITIVE_INFINITY
  const rt = new THREE.WebGLRenderTarget(size, size, { samples: 4, type: THREE.HalfFloatType })
  const textureMatrix = new THREE.Matrix4()
  const material = new THREE.ShaderMaterial({
    name: 'MirrorSurface',
    uniforms: THREE.UniformsUtils.clone(MIRROR_UNIFORMS),
    vertexShader: MIRROR_VERTEX,
    fragmentShader: MIRROR_FRAGMENT,
    clipping: true,
    // Both sides of a pane mirror — `renderMirror` turns the normal towards
    // the camera every frame, and a single-skin pane would otherwise vanish
    // the moment one walks round it.
    side: THREE.DoubleSide,
  })
  material.uniforms.color.value = new THREE.Color(MIRROR_PRESET.tint)
  material.uniforms.tDiffuse.value = rt.texture
  material.uniforms.textureMatrix.value = textureMatrix
  material.userData = { ...(src.userData || {}), __slotClone: true, __mirror: slot }
  material.needsUpdate = true

  const state: MirrorState = {
    mesh, slot, plane, rt, textureMatrix, material,
    budget: new MirrorBudget(maxPerFrame),
    maxPerFrame,
    maxDistanceM: opts.maxDistanceM ?? Number.POSITIVE_INFINITY,
    cameras: new WeakMap(),
  }
  stateOfMaterial.set(material, state)
  let states = meshStates.get(mesh)
  if (!states) {
    states = new Map()
    meshStates.set(mesh, states)
    const prev = mesh.onBeforeRender
    originalHooks.set(mesh, prev)
    mesh.onBeforeRender = function (this: Mesh, renderer, scene, camera, geom, mat, group) {
      prev.call(this, renderer, scene, camera, geom, mat, group)
      renderMirror(THREE, this, renderer, scene, camera, mat)
    }
  }
  states.set(slot, state)

  if (Array.isArray(mesh.material) && materialIndex !== null) mesh.material[materialIndex] = material
  else mesh.material = material
  return material
}

/** Reflector.js's per-frame work, on a mesh whose plane is a stored value
 *  instead of "my local +z". Runs for EVERY material the mesh draws; only the
 *  ones marked `__mirror` do anything. */
function renderMirror(THREE: typeof import('three'), mesh: Mesh, renderer: WebGLRenderer,
                      scene: Scene, camera: Camera, material: Material): void {
  const slot = (material as Material & { userData: { __mirror?: string } }).userData?.__mirror
  if (!slot || inMirrorPass) return
  const state = meshStates.get(mesh)?.get(slot)
  if (!state) return
  const uniforms = (material as ShaderMaterial).uniforms
  if (!uniforms?.tDiffuse || !uniforms.textureMatrix) return
  // WHY THIS IS REWRITTEN ON EVERY DRAW, not just set once in `attachMirror`:
  // `applyDepthCut` CLONES the material it is given, and `UniformsUtils.clone`
  // flatly refuses to copy a render target's texture — three logs
  // "UniformsUtils: Textures of render targets cannot be cloned" and leaves
  // the clone's `tDiffuse` at null, which would draw a cut mirror black. (The
  // clone also gets its own copy of the Matrix4, so the texture matrix would
  // freeze at whatever it held when the cut was made.) Writing both onto
  // whatever material is ACTUALLY being drawn repairs the clone every frame.
  uniforms.tDiffuse.value = state.rt.texture
  uniforms.textureMatrix.value = state.textureMatrix

  const { mirrorPos, normal, cameraPos, view, lookAt, target, rotation,
          normalMatrix, clipPlane, clip, q } = mirrorScratch(THREE)
  mirrorPos.set(...state.plane.point).applyMatrix4(mesh.matrixWorld)
  normal.set(...state.plane.normal)
    .applyMatrix3(normalMatrix.getNormalMatrix(mesh.matrixWorld)).normalize()
  cameraPos.setFromMatrixPosition(camera.matrixWorld)
  view.subVectors(mirrorPos, cameraPos)
  // Both sides of a pane mirror: the normal always faces the camera.
  if (view.dot(normal) > 0) normal.negate()
  if (view.length() > state.maxDistanceM) return
  if (!state.budget.allow(renderer.info.render.frame)) return

  let reflectionCamera = state.cameras.get(camera)
  if (!reflectionCamera) {
    reflectionCamera = camera.clone()
    state.cameras.set(camera, reflectionCamera)
  }
  rotation.extractRotation(camera.matrixWorld)
  view.reflect(normal).negate().add(mirrorPos)
  lookAt.set(0, 0, -1).applyMatrix4(rotation).add(cameraPos)
  target.subVectors(mirrorPos, lookAt).reflect(normal).negate().add(mirrorPos)
  reflectionCamera.position.copy(view)
  reflectionCamera.up.set(0, 1, 0).applyMatrix4(rotation).reflect(normal)
  reflectionCamera.lookAt(target)
  ;(reflectionCamera as PerspectiveCamera).far = (camera as PerspectiveCamera).far
  reflectionCamera.updateMatrixWorld()
  reflectionCamera.projectionMatrix.copy(camera.projectionMatrix)

  state.textureMatrix.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1)
    .multiply(reflectionCamera.projectionMatrix)
    .multiply(reflectionCamera.matrixWorldInverse)
    .multiply(mesh.matrixWorld)

  // Oblique near plane (Lengyel), verbatim from Reflector.js.
  clipPlane.setFromNormalAndCoplanarPoint(normal, mirrorPos)
    .applyMatrix4(reflectionCamera.matrixWorldInverse)
  clip.set(clipPlane.normal.x, clipPlane.normal.y, clipPlane.normal.z,
           clipPlane.constant)
  const proj = reflectionCamera.projectionMatrix
  const ortho = (reflectionCamera as OrthographicCamera).isOrthographicCamera === true
  q.x = (Math.sign(clip.x) + proj.elements[8]) / proj.elements[0]
  q.y = (Math.sign(clip.y) + proj.elements[9]) / proj.elements[5]
  if (ortho) { q.z = -(camera as OrthographicCamera).far; q.w = 1 }
  else { q.z = -1; q.w = (1 + proj.elements[10]) / proj.elements[14] }
  clip.multiplyScalar(2 / clip.dot(q))
  proj.elements[2] = clip.x
  proj.elements[6] = clip.y
  if (ortho) { proj.elements[10] = clip.z - MIRROR_PRESET.clipBias; proj.elements[14] = clip.w - 1 }
  else { proj.elements[10] = clip.z + 1 - MIRROR_PRESET.clipBias; proj.elements[14] = clip.w }

  // The pass. The whole mesh hides (a pane cannot see its own frame from
  // behind its plane anyway), shadows and XR are frozen like Reflector does.
  inMirrorPass = true
  const wasVisible = mesh.visible
  mesh.visible = false
  const prevTarget = renderer.getRenderTarget()
  const prevXr = renderer.xr.enabled
  const prevShadow = renderer.shadowMap.autoUpdate
  renderer.xr.enabled = false
  renderer.shadowMap.autoUpdate = false
  renderer.setRenderTarget(state.rt)
  renderer.state.buffers.depth.setMask(true)
  if (renderer.autoClear === false) renderer.clear()
  try {
    renderer.render(scene, reflectionCamera)
  } finally {
    renderer.xr.enabled = prevXr
    renderer.shadowMap.autoUpdate = prevShadow
    renderer.setRenderTarget(prevTarget)
    const viewport = (camera as Camera & { viewport?: Vector4 }).viewport
    if (viewport !== undefined) renderer.state.viewport(viewport)
    mesh.visible = wasVisible
    inMirrorPass = false
  }
}

/** What a live mirror material is made of, for anyone who has to CHECK it
 *  rather than draw it: the plane the pane was measured to have, and the cost
 *  policy that reached the state. */
export interface MirrorInfo {
  /** A copy — writing to it cannot move the pane. */
  plane: MirrorPlane
  maxPerFrame: number
  maxDistanceM: number
}

/** Read back what `attachMirror` measured and stored for a material.
 *  `undefined` for anything that is not a live mirror (a picture clone, a
 *  glass clone, a pane already disposed). This is how
 *  `scripts/smoke_slot_materials.mjs` [9] can tell WHICH material group was
 *  measured — without it a mirror on the wrong faces looks like a mirror on
 *  the right ones. */
export function mirrorPlaneOf(mat: Material): MirrorInfo | undefined {
  const state = stateOfMaterial.get(mat)
  if (!state) return undefined
  const { point, normal } = state.plane
  return {
    plane: {
      point: [point[0], point[1], point[2]],
      normal: [normal[0], normal[1], normal[2]],
    },
    maxPerFrame: state.maxPerFrame,
    maxDistanceM: state.maxDistanceM,
  }
}

/** Free one mirror's render target and material and unhook the mesh once its
 *  last mirror is gone. Safe on any material — a non-mirror is ignored, so
 *  `disposeSlotMaterials` can call it on every clone it holds. */
export function disposeMirror(mat: Material): void {
  const state = stateOfMaterial.get(mat)
  if (!state) return
  stateOfMaterial.delete(mat)
  state.rt.dispose()
  mat.dispose?.()
  const states = meshStates.get(state.mesh)
  states?.delete(state.slot)
  if (states && states.size === 0) {
    meshStates.delete(state.mesh)
    const prev = originalHooks.get(state.mesh)
    if (prev) state.mesh.onBeforeRender = prev
    originalHooks.delete(state.mesh)
  }
}
