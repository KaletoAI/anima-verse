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
    const b = box.clone()
    b.min.sub(origin)
    b.max.sub(origin)
    if (!frameYaw) return b
    const c = b.getCenter(new this.THREE.Vector3())
    const h = b.getSize(new this.THREE.Vector3()).multiplyScalar(0.5)
    // Inverse of § A1.1 (x = lx·cos + lz·sin, z = −lx·sin + lz·cos).
    const cos = Math.cos(frameYaw)
    const sin = Math.sin(frameYaw)
    const lx = c.x * cos - c.z * sin
    const lz = c.x * sin + c.z * cos
    b.min.set(lx - h.x, c.y - h.y, lz - h.z)
    b.max.set(lx + h.x, c.y + h.y, lz + h.z)
    return b
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
    for (const t of targets) this.check(name, t.field, t.actual(box), t.target)
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
    const size = world.getSize(new this.THREE.Vector3())
    const box = this.inFrame(world, origin, frameYaw)
    const centre = box.getCenter(new this.THREE.Vector3())
    const name = `${spec.role}:${spec.id}`
    // `groundLift` is the storey-0 terrain lift of § A16.9
    // (`storeyGroundLift`) — the ONLY sanctioned difference between the
    // composed `bottom_y` and the drawn one. It is added to the TARGET rather
    // than subtracted from the measurement on purpose: the row a verify report
    // prints then names the height the object is meant to have at ITS point,
    // which is the number a reader can check against the height field.
    this.check(name, 'bottom_y', box.min.y, spec.bottom_y + groundLift)
    const axisParallel = (v?: number) =>
      Math.abs((((v || 0) % 90) + 90) % 90) <= 0.01
    // A FITTED model (v5, door props) hangs on its HINGE EDGE, so its bbox
    // centre is half an opening away from the anchor by design. What is
    // checked is the hanging point itself — the same measurement the diagonal
    // case below uses, and for the same reason.
    if (spec.measure === 'fit') {
      const p = obj.getWorldPosition(new this.THREE.Vector3()).sub(origin)
      const cos = Math.cos(frameYaw)
      const sin = Math.sin(frameYaw)
      this.check(name, 'anchor.x', p.x * cos - p.z * sin, spec.anchor[0])
      this.check(name, 'anchor.z', p.x * sin + p.z * cos, spec.anchor[1])
      // …and the opening is the ruler: the width lies on whichever horizontal
      // axis the yaw put it on, the height is the height.
      if (spec.size_m && axisParallel(spec.yaw_deg)
          && axisParallel((frameYaw * 180) / Math.PI)) {
        this.check(name, 'size_m.w', Math.max(size.x, size.z), spec.size_m[0])
        this.check(name, 'size_m.h', size.y, spec.size_m[1])
      }
      return
    }
    if (axisParallel(spec.yaw_deg) && axisParallel((frameYaw * 180) / Math.PI)) {
      // Axis-parallel, the world bbox centre IS the seating point — the
      // sharper measurement, because it checks the GEOMETRY, not the
      // transform.
      this.check(name, 'anchor.x', centre.x, spec.anchor[0])
      this.check(name, 'anchor.z', centre.z, spec.anchor[1])
    } else {
      // Diagonally no longer: since the § B2 revision (2026-08-20) the object
      // sits on its box BEFORE the yaw, and the hull of the diagonally turned
      // mesh has a different centre (sectional sofa at 45°: 0.50 m off —
      // exactly the difference that used to separate a prop marker from its
      // prop). What is checked here is therefore the hanging point itself,
      // which `place()` sets on the anchor: the world position of the placed
      // group, turned back into the frame the spec numbers live in.
      const p = obj.getWorldPosition(new this.THREE.Vector3()).sub(origin)
      const cos = Math.cos(frameYaw)
      const sin = Math.sin(frameYaw)
      this.check(name, 'anchor.x', p.x * cos - p.z * sin, spec.anchor[0])
      this.check(name, 'anchor.z', p.x * sin + p.z * cos, spec.anchor[1])
    }
    // Extent checks only apply when NOTHING stands diagonally — the world
    // bbox of a diagonally turned mesh is legitimately larger than the target
    // box. That holds for the map yaw as for the orientation fix: since the
    // object size is measured at the 90°-rounded fix (§ B2), a fix of e.g.
    // 110° is exactly such a case. Since E4 the tile's frame yaw counts the
    // same way: a location set at an angle inflates the axis-aligned hull of
    // its models just as much.
    if (!axisParallel(spec.yaw_deg) || !axisParallel(spec.fix_euler?.x)
        || !axisParallel(spec.fix_euler?.y) || !axisParallel(spec.fix_euler?.z)
        || !axisParallel((frameYaw * 180) / Math.PI)) return
    if (spec.max_m) {
      // With an axis-parallel yaw the turned box is the fixed one with
      // swapped axes — `yawed_xz` and `xz` measure the same thing here.
      this.check(name, 'max_m', spec.measure === 'xyz'
        ? Math.max(size.x, size.y, size.z) : Math.max(size.x, size.z),
      spec.max_m)
    }
  }
}
