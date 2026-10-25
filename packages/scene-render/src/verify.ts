/**
 * The verify core of the contract (§ B5a): arithmetic instead of screenshots.
 *
 * The scene recipe is the TARGET. After the build every object is measured
 * afresh in world coordinates and diffed against the spec it grew out of —
 * findings travel between sessions as NUMBERS (object, field, actual, target),
 * never as a picture.
 *
 * Only the core lives here: the tolerance, the diff row and the two measuring
 * routines. The REPORTS stay with the consumers and are meant to: the admin
 * shows an overlay with notes, the 3D client writes a console report including
 * skipped specs and clip remarks to `window.__sceneVerify`. Those are
 * different products of the same arithmetic.
 *
 * What the arithmetic CANNOT check: a hull clip discards fragments, not
 * geometry — the rendered bbox stays the unclipped one (§ B1). Both consumers
 * therefore note WHERE clipping happens instead of pretending to measure it.
 */
import type { Box3, Object3D, Vector3 } from 'three'
import type { SceneModelSpec } from './types'

/** Verify tolerance in world metres (§ B5a). */
export const VERIFY_EPS = 0.01

/** One measured-against-target number of the verify run. */
export interface VerifyRow {
  object: string
  field: string
  actual: number
  target: number
  delta: number
}

/** One check target of a primitive: field name, how to read it off the bbox,
 *  and the target from the payload. */
export interface PrimitiveTarget {
  field: string
  actual: (b: Box3) => number
  target: number
}

/**
 * Collects deviations. `active` false switches the measuring off without the
 * callers having to bracket their calls — only the consumers' `skip`-style
 * counts keep running then.
 *
 * `origin` is, in every measurement, the world position of the reference
 * point: the 3D client computes around the TILE CENTRE (the spec numbers are
 * stated relative to it), the admin preview stands in the origin and passes a
 * zero vector.
 */
export class SpecVerifier {
  rows: VerifyRow[] = []
  checked = 0

  constructor(readonly THREE: typeof import('three'),
              readonly active: boolean = true) {}

  check(object: string, field: string, actual: number, target: number): void {
    if (!this.active) return
    this.checked += 1
    const delta = actual - target
    if (Math.abs(delta) > VERIFY_EPS) {
      const r3 = (v: number) => Math.round(v * 1000) / 1000
      this.rows.push({ object, field, actual: r3(actual), target: r3(target),
                       delta: r3(delta) })
    }
  }

  /**
   * The measured WORLD box in the frame the spec numbers live in: shifted by
   * `origin` and, since E4, turned back by `frameYaw`.
   *
   * The 3D client's tile group carries the location's footprint rotation
   * (§ A1.1) — its children therefore stand turned in the world, while the
   * payload states them tile-locally. Subtracting the centre alone was enough
   * only while every tile stood at yaw 0.
   *
   * WHAT IS EXACT AND WHAT IS NOT. A box CENTRE is rotation-covariant, so
   * un-turning it recovers the tile-local centre to the last digit — and the
   * y range is untouched by a rotation about the up axis. The x/z EXTENTS of an
   * axis-aligned box are not: a diagonally turned frame legitimately inflates
   * them. No target of `plateTargets`/`wallTargets` reads an x/z extent, and
   * the one extent check in `placement` is gated on axis-parallel angles, the
   * frame yaw included.
   */
  private inFrame(box: Box3, origin: Vector3, frameYaw: number): Box3 {
    const b = inFrame(box, origin, frameYaw)
    return new this.THREE.Box3(
      new this.THREE.Vector3(b.min.x, b.min.y, b.min.z),
      new this.THREE.Vector3(b.max.x, b.max.y, b.max.z))
  }

  /** Check a primitive against its spec: measure the world bbox and diff the
   *  edges/centres the payload prescribes. `frameYaw` (radians) is the turn of
   *  the reference frame — the tile's footprint rotation in the 3D client, 0
   *  in the admin preview, which stands unturned in the origin. */
  primitive(mesh: Object3D, origin: Vector3, name: string,
            targets: PrimitiveTarget[], frameYaw = 0): void {
    if (!this.active) return
    // Update the PARENTS too — otherwise one measures a cold matrix.
    mesh.updateWorldMatrix(true, true)
    const box = this.inFrame(
      new this.THREE.Box3().setFromObject(mesh), origin, frameYaw)
    const result = primitiveRows(name, targets.map(t => ({
      field: t.field, actual: t.actual(box), target: t.target,
    })))
    this.checked += result.checked
    this.rows.push(...result.rows)
  }

  /** Check a placed model against its spec.
   *
   *  SIGN-BLIND BY CONSTRUCTION, and deliberately left that way by the E4 yaw
   *  flip (§ A1.1): every target here is invariant under the turning sense.
   *  `bottom_y` and the anchor are set AFTER the rotation (place() seats the
   *  object on them, whichever way it turned), and the `max_m` check
   *  only runs for axis-parallel yaw, where ±90° give the same axis-aligned
   *  box. The sign therefore has to be pinned somewhere else — that is what
   *  section 6 of `client3d/scripts/smoke_place_rotation.mjs` is for. */
  placement(obj: Object3D, spec: SceneModelSpec, origin: Vector3,
            frameYaw = 0, groundLift = 0): void {
    if (!this.active) return
    obj.updateWorldMatrix(true, true)
    const world = new this.THREE.Box3().setFromObject(obj)
    const result = placementRows(world, obj.getWorldPosition(new this.THREE.Vector3()),
      spec, origin, frameYaw, groundLift)
    this.checked += result.checked
    this.rows.push(...result.rows)
  }
}

/** Structural numbers only: these functions can run without Three. */
export interface VerifyPoint { x: number; y: number; z: number }
export interface VerifyBox { min: VerifyPoint; max: VerifyPoint }
export interface VerifyMeasurement { field: string; actual: number; target: number }
export interface VerifyResult { checked: number; rows: VerifyRow[] }
export function inFrame(box: VerifyBox, origin: VerifyPoint, frameYaw = 0): VerifyBox {
  const min = { x: box.min.x-origin.x, y: box.min.y-origin.y, z: box.min.z-origin.z }
  const max = { x: box.max.x-origin.x, y: box.max.y-origin.y, z: box.max.z-origin.z }
  if (!frameYaw) return { min, max }
  const empty=max.x<min.x||max.y<min.y||max.z<min.z
  const x=empty?0:(min.x+max.x)/2, y=empty?0:(min.y+max.y)/2, z=empty?0:(min.z+max.z)/2
  const hx=empty?0:(max.x-min.x)/2, hy=empty?0:(max.y-min.y)/2, hz=empty?0:(max.z-min.z)/2
  const lx=x*Math.cos(frameYaw)-z*Math.sin(frameYaw)
  const lz=x*Math.sin(frameYaw)+z*Math.cos(frameYaw)
  return { min: { x: lx-hx,y:y-hy,z:lz-hz }, max: { x:lx+hx,y:y+hy,z:lz+hz } }
}
export function primitiveRows(object: string, measurements: VerifyMeasurement[]): VerifyResult {
  const r3=(v:number)=>Math.round(v*1000)/1000
  return { checked: measurements.length, rows: measurements.filter(t=>Math.abs(t.actual-t.target)>VERIFY_EPS)
    .map(t=>({object,field:t.field,actual:r3(t.actual),target:r3(t.target),delta:r3(t.actual-t.target)})) }
}
export function placementRows(world: VerifyBox, position: VerifyPoint, spec: SceneModelSpec,
  origin: VerifyPoint, frameYaw = 0, groundLift = 0): VerifyResult {
  const empty=world.max.x<world.min.x||world.max.y<world.min.y||world.max.z<world.min.z
  const size=empty?{x:0,y:0,z:0}:{x:world.max.x-world.min.x,y:world.max.y-world.min.y,z:world.max.z-world.min.z}
  const box=inFrame(world,origin,frameYaw)
  const ms: VerifyMeasurement[]=[]
  const add=(field:string,actual:number,target:number)=>ms.push({field,actual,target})
  const axis=(v=0)=>Math.abs(((v%90)+90)%90)<=0.01
  const parallel=axis(spec.yaw_deg)&&axis(frameYaw*180/Math.PI)
  add('bottom_y',box.min.y,spec.bottom_y+groundLift)
  if(spec.measure==='fit'||!parallel) {
    const x=position.x-origin.x,z=position.z-origin.z
    add('anchor.x',x*Math.cos(frameYaw)-z*Math.sin(frameYaw),spec.anchor[0])
    add('anchor.z',x*Math.sin(frameYaw)+z*Math.cos(frameYaw),spec.anchor[1])
  } else {
    const boxEmpty=box.max.x<box.min.x||box.max.y<box.min.y||box.max.z<box.min.z
    add('anchor.x',boxEmpty?0:(box.min.x+box.max.x)/2,spec.anchor[0])
    add('anchor.z',boxEmpty?0:(box.min.z+box.max.z)/2,spec.anchor[1])
  }
  if(spec.measure==='fit') {
    if(spec.size_m&&parallel) {add('size_m.w',Math.max(size.x,size.z),spec.size_m[0]);add('size_m.h',size.y,spec.size_m[1])}
  } else if(parallel&&axis(spec.fix_euler?.x)&&axis(spec.fix_euler?.y)&&axis(spec.fix_euler?.z)&&spec.max_m) {
    add('max_m',spec.measure==='xyz'?Math.max(size.x,size.y,size.z):Math.max(size.x,size.z),spec.max_m)
  }
  return primitiveRows(`${spec.role}:${spec.id}`,ms)
}
