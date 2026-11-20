import { neutralizeLook } from './materialLooks';
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
/** A214: the same environment for a figure's glossy pieces (`prepareGlossyPieces`); null before the engine set it. */
export function getModelEnvironment(): THREE.Texture | null {
  return modelEnv;
}

/** The GPU's maximum anisotropic filtering (`renderer.capabilities.getMaxAnisotropy()`), set by the engine; a
 *  figure's textures are filtered with it (`prepareFigureTextures`). 1 before the engine set it. */
let maxAnisotropy = 1;
export function setMaxAnisotropy(n: number) {
  maxAnisotropy = n;
}
export function getMaxAnisotropy(): number {
  return maxAnisotropy;
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
      const look = neutralizeLook(std.metalness, !!std.metalnessMap, !!modelEnv);
      std.metalness = look.metalness;
      if ('envMapIntensity' in look) {
        std.envMap = modelEnv;
        std.envMapIntensity = look.envMapIntensity!;
      }
    }
  });
}
