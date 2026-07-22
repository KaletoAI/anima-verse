import * as THREE from 'three';

// Platzierungskette für Einzel-Props (backend-note-room-recipe.md, 2b):
// REAL-SIZE-Regel — eine Platzierung skaliert NIE auf ein Zielrechteck,
// sondern uniform auf die reale Objektgröße. Verifiziert gegen das
// Zahlenbeispiel in Abschnitt 2d der Note.

export interface PropDims { width_m: number; depth_m: number; height_m: number }

export interface PlacePropOpts {
  /** Orientierungs-Fix in Grad (Euler 'XYZ', wie Raum-Modelle) — VOR dem Messen */
  fix?: { x?: number; y?: number; z?: number };
  /** reale Maße des Objekts in Metern (nach Fix: x=width, y=height, z=depth) */
  dims: PropDims;
  /** Welt-Meter pro Real-Meter (8 / plan_width_m) */
  k: number;
  /** Grad, dreht im Uhrzeigersinn in der Draufsicht (wie map3d.rotation) */
  yaw: number;
  /** Höhen-Feinjustierung in realen Metern (offset_y) */
  offsetY: number;
  /** Zielpunkt des XZ-Zentrums im Koordinatensystem der Ziel-Gruppe */
  at: { x: number; z: number };
  /** Oberkante des Etagenbodens (gleiches Koordinatensystem) */
  floorY: number;
}

/** Kette pro Placement: Fix anwenden -> BBox des GEFIXTEN Meshes messen ->
 *  uniform s = max(dims) x k / maxExtent -> rotation.y = -yaw -> Ergebnis-BBox
 *  messen, Unterkante auf floorY + offset_y x k, XZ-Zentrum auf at.
 *  Liefert eine Hülle um `model`; der Aufrufer hängt sie in eine Gruppe OHNE
 *  eigene Transformation (die Erdung misst im Eltern-Koordinatensystem). */
export function placeProp(model: THREE.Object3D, opts: PlacePropOpts): THREE.Group {
  const rad = THREE.MathUtils.degToRad;
  const g = new THREE.Group();
  model.rotation.set(rad(opts.fix?.x ?? 0), rad(opts.fix?.y ?? 0), rad(opts.fix?.z ?? 0), 'XYZ');
  g.add(model);
  g.updateMatrixWorld(true);
  const fixed = new THREE.Box3().setFromObject(g);
  const ext = fixed.getSize(new THREE.Vector3());
  const maxExtent = Math.max(ext.x, ext.y, ext.z, 1e-3);
  const s = (Math.max(opts.dims.width_m, opts.dims.depth_m, opts.dims.height_m) * opts.k) / maxExtent;
  g.scale.setScalar(s);
  g.rotation.y = -rad(opts.yaw);
  // Erdung an der ROTIERTEN Box (wie applyRoomModel): nach Fix + Yaw wandert
  // min.y — ohne Neumessung schwingt das Objekt unter den Boden
  g.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(g);
  const c = box.getCenter(new THREE.Vector3());
  g.position.x += opts.at.x - c.x;
  g.position.z += opts.at.z - c.z;
  g.position.y += opts.floorY + opts.offsetY * opts.k - box.min.y;
  g.updateMatrixWorld(true);
  return g;
}
