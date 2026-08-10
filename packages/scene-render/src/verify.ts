/**
 * Verify-Kern des Vertrags (§ B5a): Rechnen statt Screenshots.
 *
 * Das Szenen-Rezept ist das SOLL. Nach dem Aufbau wird jedes Objekt neu in
 * Weltkoordinaten vermessen und gegen die Spec gediffrt, aus der es entstanden
 * ist — Befunde reisen als ZAHLEN zwischen den Sessions (Objekt, Feld, Ist,
 * Soll), nie als Bild.
 *
 * Hier steht nur der Kern: die Toleranz, die Diff-Zeile und die beiden
 * Messroutinen. Die BERICHTE bleiben bei den Konsumenten und sollen es auch:
 * der Admin zeigt ein Overlay mit Notizen, der 3D-Client schreibt einen
 * console-Report samt übersprungenen Specs und Clip-Vermerken nach
 * `window.__sceneVerify`. Das sind verschiedene Produkte derselben Rechnung.
 *
 * Was die Arithmetik NICHT prüfen kann: ein Hüllen-Clip verwirft Fragmente,
 * keine Geometrie — die gerenderte BBox bleibt die ungeclippte (§ B1). Beide
 * Konsumenten vermerken deshalb, WO geclippt wird, statt so zu tun, als
 * würden sie es messen.
 */
import type { Box3, Object3D, Vector3 } from 'three'
import type { SceneModelSpec } from './types'

/** Verify-Toleranz in Welt-Metern (§ B5a). */
export const VERIFY_EPS = 0.01

/** Eine gemessene-gegen-vorgegebene Zahl des Verify-Laufs. */
export interface VerifyRow {
  object: string
  field: string
  actual: number
  target: number
  delta: number
}

/** Ein Prüfziel eines Primitivs: Feldname, wie es aus der BBox zu lesen ist,
 *  und das Soll aus dem Payload. */
export interface PrimitiveTarget {
  field: string
  actual: (b: Box3) => number
  target: number
}

/**
 * Sammelt Abweichungen. `active` false schaltet die Messung ab, ohne dass die
 * Aufrufer ihre Aufrufe einklammern müssen — nur `skip`-artige Zählungen der
 * Konsumenten laufen dann noch.
 *
 * `origin` ist bei jeder Messung die Weltposition des Bezugspunkts: der
 * 3D-Client rechnet um das KACHELZENTRUM (die Spec-Zahlen gelten relativ
 * dazu), die Admin-Vorschau steht im Ursprung und übergibt einen Nullvektor.
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

  /** Primitiv gegen seine Spec prüfen: Welt-BBox messen und die vom Payload
   *  vorgegebenen Kanten/Mitten diffen. `frameYaw` (Radiant) ist die Drehung
   *  des Bezugsrahmens — die Fußabdruck-Drehung der Kachel im 3D-Client, 0 in
   *  der Admin-Vorschau, die im Ursprung ungedreht steht. */
  primitive(mesh: Object3D, origin: Vector3, name: string,
            targets: PrimitiveTarget[], frameYaw = 0): void {
    if (!this.active) return
    // Eltern MIT aktualisieren — sonst misst man eine kalte Matrix.
    mesh.updateWorldMatrix(true, true)
    const box = this.inFrame(
      new this.THREE.Box3().setFromObject(mesh), origin, frameYaw)
    for (const t of targets) this.check(name, t.field, t.actual(box), t.target)
  }

  /** Platziertes Modell gegen seine Spec prüfen.
   *
   *  SIGN-BLIND BY CONSTRUCTION, and deliberately left that way by the E4 yaw
   *  flip (§ A1.1): every target here is invariant under the turning sense.
   *  `bottom_y` and the anchor are set AFTER the rotation (place() shifts the
   *  result's box onto them, whichever way it turned), and the `max_m` check
   *  only runs for axis-parallel yaw, where ±90° give the same axis-aligned
   *  box. The sign therefore has to be pinned somewhere else — that is what
   *  section 6 of `client3d/scripts/smoke_place_rotation.mjs` is for. */
  placement(obj: Object3D, spec: SceneModelSpec, origin: Vector3,
            frameYaw = 0): void {
    if (!this.active) return
    obj.updateWorldMatrix(true, true)
    const world = new this.THREE.Box3().setFromObject(obj)
    const size = world.getSize(new this.THREE.Vector3())
    const box = this.inFrame(world, origin, frameYaw)
    const centre = box.getCenter(new this.THREE.Vector3())
    const name = `${spec.role}:${spec.id}`
    this.check(name, 'bottom_y', box.min.y, spec.bottom_y)
    this.check(name, 'anchor.x', centre.x, spec.anchor[0])
    this.check(name, 'anchor.z', centre.z, spec.anchor[1])
    // Ausdehnungs-Prüfungen gelten nur, wenn NICHTS diagonal steht — die
    // Welt-BBox eines schräg gedrehten Meshes ist legitim größer als die
    // Zielbox. Das gilt für den Karten-Yaw wie für den Orientierungs-Fix:
    // seit die Objektgröße am 90°-gerundeten Fix gemessen wird (§ B2), ist
    // ein Fix von z.B. 110° genau so ein Fall. Seit E4 zählt der Rahmen-Yaw
    // der Kachel genauso mit: eine schräg gestellte Location bläht die
    // achsparallele Hülle ihrer Modelle ebenso auf.
    const axisParallel = (v?: number) =>
      Math.abs((((v || 0) % 90) + 90) % 90) <= 0.01
    if (!axisParallel(spec.yaw_deg) || !axisParallel(spec.fix_euler?.x)
        || !axisParallel(spec.fix_euler?.y) || !axisParallel(spec.fix_euler?.z)
        || !axisParallel((frameYaw * 180) / Math.PI)) return
    if (spec.max_m) {
      // Bei achsenparallelem Yaw ist die gedrehte Box die gefixte mit
      // getauschten Achsen — `yawed_xz` und `xz` messen hier dasselbe.
      this.check(name, 'max_m', spec.measure === 'xyz'
        ? Math.max(size.x, size.y, size.z) : Math.max(size.x, size.z),
      spec.max_m)
    }
  }
}
