import type { Material, Object3D } from 'three'
import type { ScenePropWater } from './types'
import { surfaceMaterial } from './materials'

type THREE = typeof import('three')
// Module-owned looks survive placement teardown; only geometry belongs to mounts.
const materials = new WeakMap<THREE, Map<string, Material>>()

export function buildPropWater(T: THREE, block: ScenePropWater, lift: number): Object3D[] {
  let cache = materials.get(T)
  if (!cache) { cache = new Map(); materials.set(T, cache) }
  return block.regions.map((region) => {
    const key = `${region.tint}|${region.opacity}`
    let material = cache.get(key)
    if (!material) {
      material = surfaceMaterial(T, { material: { class: 'water', tint: region.tint },
        color: region.tint, transparent: true, opacity: region.opacity, depthWrite: false })
      cache.set(key, material)
    }
    const points = (ring: [number, number][]) => ring.map(([x, z]) => new T.Vector2(x, -z))
    const shape = new T.Shape(points(region.outline))
    for (const hole of region.holes ?? []) shape.holes.push(new T.Path(points(hole)))
    const geometry = new T.ShapeGeometry(shape)
    geometry.rotateX(-Math.PI / 2)
    const mesh = new T.Mesh(geometry, material)
    mesh.position.y = region.y + lift
    mesh.receiveShadow = true
    return mesh
  })
}
