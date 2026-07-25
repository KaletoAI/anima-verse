import * as THREE from 'three';

// Material-Behandlung für alle Server-GLBs (Gebäude, Raum-Dioramen, Props).
// Geometrie steht nicht mehr hier: seit dem Szenen-Rezept (Vertrag Teil B)
// kommen Maßstab, Orientierung und Erdung fertig als Spec vom Server und
// laufen durch die eine place()-Routine in sceneRecipe.ts. Übrig bleibt, was
// rein die Darstellung betrifft.

/** Neutrale Environment-Map für Modelle mit echter Metal-Roughness-Textur
 *  (AV3D-14) — ohne sie rendern metallische Pixel schwarz. */
let modelEnv: THREE.Texture | null = null;
export function setModelEnvironment(tex: THREE.Texture) {
  modelEnv = tex;
}

/** Generierte GLBs lassen metallicFactor oft unbelegt — der glTF-Default ist
 *  1.0 (voll metallisch), und ohne Environment-Map rendert das fast schwarz.
 *  Gemeint ist kein Metall: neutralisieren. Liefert das GLB dagegen eine
 *  echte Metal-Roughness-Textur (AV3D-14), bleibt sie unangetastet — dann
 *  bekommt das Material die neutrale Environment-Map, damit Metall-Pixel
 *  reflektieren. Gilt für Gebäude-/Raum-Modelle UND Prop-GLBs. */
export function neutralizeGltfMaterials(root: THREE.Object3D) {
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const std = m as THREE.MeshStandardMaterial;
      if (!std.isMeshStandardMaterial) continue;
      if (std.metalnessMap) {
        if (modelEnv) {
          std.envMap = modelEnv;
          std.envMapIntensity = 0.7;
        }
      } else if (std.metalness > 0.5) {
        std.metalness = 0;
      }
    }
  });
}
