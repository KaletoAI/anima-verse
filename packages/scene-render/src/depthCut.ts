/**
 * The DEPTH CUT of a placed prop (§ B2 addendum 2026-08-23) — half a table
 * against a wall, out of the one table in the library.
 *
 * The plane is the SERVER's (`scene_recipe.depth_cut_plane`): the payload
 * carries `cut_plane` as `{normal, constant}` in its own world metres, with
 * three.js' own convention — a fragment is KEPT where `n·p + c >= 0`. Neither
 * renderer decides where the cut runs; both build the same `THREE.Plane` out
 * of the same two numbers (§ B5: geometry exists once).
 *
 * THE ONE THING A RENDERER MUST DO is lift the plane into the frame its
 * renderer clips in. `Material.clippingPlanes` is evaluated in WORLD space,
 * while the scene payload speaks the location's own metres — the 3D client
 * hangs that frame under a tile group with the location's pin and yaw on it.
 * So the plane is transformed by the parent chain the object hangs in, which
 * is why this runs AFTER the object has been mounted, exactly like
 * `applyClipOutline`. A later re-lift is harmless: it moves the object in Y
 * only, and this plane's normal has no Y component.
 *
 * Clipping planes rather than the polygon discard of `clip.ts`: one half space
 * is precisely what a plane is, and the hardware does it for free. The cut
 * face stays OPEN — this is a clipping plane, not CSG — so the materials go
 * double-sided, the same accepted trade-off as the hull clip.
 *
 * Materials are CLONED before they are touched: the source shares them with
 * the model cache, and a patched cache material would keep cutting every other
 * placement of the same prop. `disposeCutMaterials` frees the clones again.
 */
import type { Material, Mesh, Object3D } from 'three'
import type { SceneCutPlane } from './types'

/** Build the payload's cut plane in WORLD space for an object that is already
 *  hanging where it belongs. Returns null when the placement is uncut. */
export function cutPlaneFor(THREE: typeof import('three'), obj: Object3D,
                            cut: SceneCutPlane | undefined) {
  if (!cut || !cut.normal) return null
  const n = new THREE.Vector3(cut.normal[0], cut.normal[1], cut.normal[2])
  if (n.lengthSq() < 1e-9) return null
  const plane = new THREE.Plane(n.normalize(), cut.constant)
  const parent = obj.parent
  if (parent) {
    parent.updateMatrixWorld(true)
    plane.applyMatrix4(parent.matrixWorld)
  }
  return plane
}

/**
 * Cut a placed prop along the payload's plane. The object must already sit in
 * its parent (see the header) — call it right after `parent.add(placed)`.
 *
 * The caller has to switch its renderer to per-material clipping ONCE
 * (`renderer.localClippingEnabled = true`); without it three ignores
 * `Material.clippingPlanes` and the prop simply shows up whole.
 */
export function applyDepthCut(THREE: typeof import('three'), obj: Object3D,
                              cut: SceneCutPlane | undefined): void {
  const plane = cutPlaneFor(THREE, obj, cut)
  if (!plane) return
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const cutOne = (src: Material): Material => {
      const mat = src.clone()
      mat.side = THREE.DoubleSide
      mat.clippingPlanes = [plane]
      mat.clipShadows = true
      mat.userData = { ...mat.userData, __cutClone: true }
      mat.needsUpdate = true
      return mat
    }
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(cutOne)
      : cutOne(mesh.material)
  })
}

/** Free the material clones of `applyDepthCut` (their textures are shared with
 *  the model cache and are deliberately left alone). */
export function disposeCutMaterials(obj: Object3D): void {
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const m of mats) if (m?.userData?.__cutClone) m.dispose?.()
  })
}
