/**
 * place() — DIE Platzierungs-Routine des Vertrags (§ B2), einmal für beide
 * Renderer. Sie lag doppelt vor: `placeModelSpec` in der Admin-Vorschau und
 * `placeSpec` im 3D-Client, Zeile für Zeile dieselbe Rechnung.
 *
 * Reine Geometrie: Quelle übernehmen, Orientierungs-Fix anwenden, messen, je
 * `scale_mode` skalieren, Yaw als ELTERN-Rotation (nie in einen Euler
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

/** Die EINE Geometriezahl, die clientseitig bleibt: Vertrag § B2 legt die
 *  0,96-Einpass-Marge in die place()-Routine des Konsumenten (fit_box-Fallback). */
export const FIT_BOX_MARGIN = 0.96

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
  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y),
                   deg(spec.fix_euler?.z))
  fix.updateMatrixWorld(true)
  const sFix = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3())

  const yawG = new THREE.Group()
  yawG.add(fix)
  yawG.rotation.y = -deg(spec.yaw_deg)
  yawG.updateMatrixWorld(true)
  const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3())

  const outer = new THREE.Group()
  outer.add(yawG)
  if (spec.scale_axes) {
    // Server-vermessenes Mesh: die Faktoren kommen fertig (§ B4).
    outer.scale.set(spec.scale_axes.xz, spec.scale_axes.y, spec.scale_axes.xz)
  } else if (spec.scale_mode === 'tile_fit') {
    // Gebäude füllen ihre Kachel je ACHSE, gemessen an der GEDREHTEN Box:
    // der Fußabdruck folgt dem Grundriss, die Höhe ihren deklarierten Metern.
    const kxz = (spec.box?.xz || 1) / (Math.max(sYaw.x, sYaw.z) || 1)
    const ky = spec.box?.y ? spec.box.y / (sYaw.y || 1) : kxz
    outer.scale.set(kxz, ky, kxz)
  } else if (spec.scale_mode === 'real_size') {
    // EIN Maßstabsgesetz: reale Meter über der größten gemessenen Ausdehnung.
    // measure_axes 'xz' ignoriert die Höhe (Dioramen, § B2a).
    const maxExtent = (spec.measure_axes === 'xz'
      ? Math.max(sFix.x, sFix.z)
      : Math.max(sFix.x, sFix.y, sFix.z)) || 1
    outer.scale.setScalar((spec.max_m || 1) / maxExtent)
  } else {
    // fit_box-Fallback: den UNROTIERTEN Fußabdruck in die Zielbox einpassen.
    outer.scale.setScalar(Math.min((spec.box?.w || 1) / (sFix.x || 1),
                                   (spec.box?.d || 1) / (sFix.z || 1))
                          * FIT_BOX_MARGIN)
  }
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
