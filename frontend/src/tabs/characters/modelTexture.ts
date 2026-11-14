import type { Material, Mesh, MeshStandardMaterial, Object3D, Texture } from 'three'
import { inGarment } from '@anima/scene-render'

/**
 * Put a model's SEPARATE texture (the FBX route: model + texture PNG) into
 * the materials the loader made. A mesh inside a garment subtree (card hair,
 * § A3a: COLOR_0 vertex colours on a double-sided material, no UVs into this
 * texture) keeps its material untouched — a map and a white base colour there
 * would paint it with one texel of the body's skin.
 * Smoke: `scripts/smoke_client_vertex_colors.mjs`.
 */
export function applyViewerTexture(object: Object3D, tex: Texture): void {
  object.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh || inGarment(o)) return
    const mats: Material[] = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const m of mats) {
      const mat = m as MeshStandardMaterial
      mat.map = tex
      // A grey/tinted base colour would multiply into the texture.
      mat.color?.set(0xffffff)
      mat.needsUpdate = true
    }
  })
}

/**
 * Metalness 0 on every material that carries a metal-roughness map (AV3D-14:
 * a generated bake claims ~0.5 metalness over skin and cloth, and this viewer
 * has no env map). A material whose glTF `extras.explicit_metallic` is true —
 * a garment with a material preset that sets metal (Ruling A36,
 * `app/core/piece_material.py`; GLTFLoader puts extras into `userData`) —
 * keeps its metalness. Smoke: `scripts/smoke_piece_material.py`.
 */
export function zeroViewerMetalness(object: Object3D): void {
  object.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const mats: Material[] = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const m of mats) {
      const std = m as MeshStandardMaterial
      if (!std.isMeshStandardMaterial || std.userData?.explicit_metallic === true) continue
      if (std.metalnessMap) {
        std.metalness = 0
        std.needsUpdate = true
      }
    }
  })
}
