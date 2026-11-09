import * as THREE from 'three';
import { inGarment } from '@anima/scene-render';

// The material steps a loaded character model goes through before it is
// cloned into figures (`figures.ts`: manifest models and server models alike).
// Kept out of the class so a smoke can run the very same steps on a GLB
// fixture (`scripts/smoke_client_vertex_colors.mjs`).
//
// What must survive them: a garment mesh (card hair, § A3a) carries its
// colour as COLOR_0 vertex colours on a double-sided material with no
// texture. GLTFLoader sets `vertexColors` and `side` from the file; nothing
// here may replace or reset that material.

/**
 * Put a model's SEPARATE texture (the FBX route: model + texture PNG) on its
 * meshes as fresh standard materials. A mesh inside a garment subtree keeps
 * its own material — it has no UVs into that texture, and its look is its
 * vertex colours.
 */
export function applyFigureTexture(template: THREE.Object3D, tex: THREE.Texture): void {
  template.traverse((o) => {
    if (!(o as THREE.Mesh).isMesh || inGarment(o)) return;
    (o as THREE.Mesh).material = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.85, metalness: 0 });
  });
}

/**
 * Characters are DIELECTRICS: metalness forced to 0 (AV3D-14).
 * Since Rosi the gateway embeds a metal-roughness texture for humanoids
 * too, whose B channel claims ~0.5 metalness over the whole body —
 * physically nonsense on skin and cloth; on top of that `metallicFactor`
 * is often unset, and the glTF default is 1.0. Uncorrected, the body
 * renders wrong without an env map (Rosi turned greenish).
 * Deliberately NO env-map solution as for buildings/props: a half-metallic
 * body is wrong with an env map as well. metalness = 0 zeroes the
 * metalnessMap multiplicatively; the ROUGHNESS from the G channel of the
 * same texture stays active and is wanted — which is why `roughness` is
 * NOT touched. The material object stays the same one, so everything else
 * the loader set (vertex colours, side) stays as well.
 *
 * Returns one log line per standard material.
 */
export function zeroFigureMetalness(template: THREE.Object3D): string[] {
  const matLog: string[] = [];
  template.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const std = m as THREE.MeshStandardMaterial;
      if (!std.isMeshStandardMaterial) continue;
      const before = std.metalness;
      const mr = std.metalnessMap ? 'MR map' : 'no MR map';
      if (before !== 0) {
        std.metalness = 0;
        std.needsUpdate = true;
      }
      matLog.push(`metalness ${before}->${std.metalness} (${mr}, roughness ${std.roughness}`
        + `${std.roughnessMap ? ' + map' : ''})`);
    }
  });
  return matLog;
}
