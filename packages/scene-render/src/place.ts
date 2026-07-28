/**
 * place() — DIE Platzierungs-Routine des Vertrags (§ B2), einmal für beide
 * Renderer. Sie lag doppelt vor: `placeModelSpec` in der Admin-Vorschau und
 * `placeSpec` im 3D-Client, Zeile für Zeile dieselbe Rechnung.
 *
 * Reine Geometrie: Quelle übernehmen, Orientierungs-Fix anwenden, messen,
 * UNIFORM auf `max_m` skalieren, Yaw als ELTERN-Rotation (nie in einen Euler
 * kombiniert — ein x/z-Fix würde mitkippen), dann die Ergebnis-BBox auf
 * `bottom_y`/`anchor` setzen und, wenn die Spec es verlangt, auf die
 * Raumhülle beschneiden. Keine Szenen-Verdrahtung, kein Verify — das machen
 * die Aufrufer.
 *
 * Rückgabe: eine Hülle um `source`. Der Aufrufer hängt sie in eine Gruppe
 * OHNE eigene Transformation (die Erdung misst im Eltern-Koordinatensystem,
 * und die Spec-Zahlen gelten um das Kachelzentrum).
 *
 * THREE kommt als Parameter statt als Import: die Admin-Seite lädt three
 * verzögert nach, ein statischer Import würde die Bibliothek in ihr
 * Haupt-Bundle ziehen. Der Client reicht schlicht sein importiertes Modul
 * durch.
 */
import type { Group, Object3D } from 'three'
import { applyClipOutline } from './clip'
import type { SceneModelSpec } from './types'

export interface PlaceOptions {
  /** Quelle vor dem Platzieren klonen. Default true — die Admin-Vorschau
   *  platziert dasselbe gecachte Objekt mehrfach. Der 3D-Client übergibt das
   *  Objekt zur Übernahme und setzt deshalb false. */
  clone?: boolean
  /** `spec.clip_outline` gleich mit anwenden. Default true. Der 3D-Client
   *  clippt selbst, nachdem er das Modell eingehängt hat, und setzt false. */
  clip?: boolean
}

export function placeModelSpec(THREE: typeof import('three'),
                               source: Object3D,
                               spec: SceneModelSpec,
                               opts: PlaceOptions = {}): Group {
  const { clone = true, clip = true } = opts
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180

  const fix = new THREE.Group()
  fix.add(clone ? source.clone(true) : source)

  // Wie GROSS ein Objekt ist, darf nicht davon abhängen, wie es GEDREHT ist.
  // Die achsparallele Hülle einer gedrehten Kiste ist größer als die Kiste —
  // beim Nixenstand wuchs sie durch den Fix 0/110/357 von 1,000 auf 1,306 und
  // das Modell wurde dadurch 23 % kleiner (User-Befund 2026-07-28). Für
  // OBJEKTGRÖSSEN (`xz`/`xyz`) wird deshalb mit einem auf 90° gerundeten Fix
  // gemessen: die Achsen-Zuordnung zählt, der Feinwinkel nicht.
  const snap = (v?: number) => Math.round((v || 0) / 90) * 90
  fix.rotation.set(deg(snap(spec.fix_euler?.x)), deg(snap(spec.fix_euler?.y)),
                   deg(snap(spec.fix_euler?.z)))
  fix.updateMatrixWorld(true)
  const sObj = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3())

  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y),
                   deg(spec.fix_euler?.z))
  const yawG = new THREE.Group()
  yawG.add(fix)
  yawG.rotation.y = -deg(spec.yaw_deg)
  yawG.updateMatrixWorld(true)
  // Das Gebäude füllt seinen Rahmen NACH der Drehung — dort ist die gedrehte
  // Hülle genau die richtige Messung (ein schräg gestelltes Haus soll auf sein
  // Grundstück passen), deshalb bleibt `yawed_xz` bei sYaw.
  const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3())

  // EIN Maßstabsgesetz, EIN Faktor auf alle drei Achsen (2026-07-28): die
  // Spec sagt, WORAUF gemessen wird, und der Rest ist eine Division. Nichts
  // wird mehr in einer Dimension gestaucht — die alten Modi (tile_fit mit
  // eigenem Y-Ziel, fit_box, scale_axes) sind ersatzlos weg, und mit ihnen
  // die Möglichkeit, dass zwei Renderer sich in der Höhe unterscheiden.
  const outer = new THREE.Group()
  outer.add(yawG)
  const extent = (spec.measure === 'yawed_xz' ? Math.max(sYaw.x, sYaw.z)
    : spec.measure === 'xz' ? Math.max(sObj.x, sObj.z)
      : Math.max(sObj.x, sObj.y, sObj.z)) || 1
  outer.scale.setScalar((spec.max_m || 1) / extent)
  outer.updateMatrixWorld(true)
  const bOut = new THREE.Box3().setFromObject(outer)
  const cOut = bOut.getCenter(new THREE.Vector3())
  outer.position.set(spec.anchor[0] - cOut.x,
                     spec.bottom_y - bOut.min.y,
                     spec.anchor[1] - cOut.z)
  // Hüllen-Clip ZULETZT: der Shader vergleicht Weltpositionen, das Modell muss
  // also erst dort sitzen, wo es hingehört (§ B1).
  if (clip && spec.clip_outline?.length) {
    applyClipOutline(THREE, outer, spec.clip_outline)
  }
  return outer
}
