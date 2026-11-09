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
