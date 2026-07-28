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

  /** Primitiv gegen seine Spec prüfen: Welt-BBox messen und die vom Payload
   *  vorgegebenen Kanten/Mitten diffen. */
  primitive(mesh: Object3D, origin: Vector3, name: string,
            targets: PrimitiveTarget[]): void {
    if (!this.active) return
    // Eltern MIT aktualisieren — sonst misst man eine kalte Matrix.
    mesh.updateWorldMatrix(true, true)
    const box = new this.THREE.Box3().setFromObject(mesh)
    box.min.sub(origin)
    box.max.sub(origin)
    for (const t of targets) this.check(name, t.field, t.actual(box), t.target)
  }

  /** Platziertes Modell gegen seine Spec prüfen. */
  placement(obj: Object3D, spec: SceneModelSpec, origin: Vector3): void {
    if (!this.active) return
    obj.updateWorldMatrix(true, true)
    const box = new this.THREE.Box3().setFromObject(obj)
    const size = box.getSize(new this.THREE.Vector3())
    const centre = box.getCenter(new this.THREE.Vector3())
    const name = `${spec.role}:${spec.id}`
    this.check(name, 'bottom_y', box.min.y - origin.y, spec.bottom_y)
    this.check(name, 'anchor.x', centre.x - origin.x, spec.anchor[0])
    this.check(name, 'anchor.z', centre.z - origin.z, spec.anchor[1])
    // Ausdehnungs-Prüfungen gelten nur, wenn NICHTS diagonal steht — die
    // Welt-BBox eines schräg gedrehten Meshes ist legitim größer als die
    // Zielbox. Das gilt für den Karten-Yaw wie für den Orientierungs-Fix:
    // seit die Objektgröße am 90°-gerundeten Fix gemessen wird (§ B2), ist
    // ein Fix von z.B. 110° genau so ein Fall.
    const axisParallel = (v?: number) =>
      Math.abs((((v || 0) % 90) + 90) % 90) <= 0.01
    if (!axisParallel(spec.yaw_deg) || !axisParallel(spec.fix_euler?.x)
        || !axisParallel(spec.fix_euler?.y) || !axisParallel(spec.fix_euler?.z)) return
    if (spec.max_m) {
      // Bei achsenparallelem Yaw ist die gedrehte Box die gefixte mit
      // getauschten Achsen — `yawed_xz` und `xz` messen hier dasselbe.
      this.check(name, 'max_m', spec.measure === 'xyz'
        ? Math.max(size.x, size.y, size.z) : Math.max(size.x, size.z),
      spec.max_m)
    }
  }
}
