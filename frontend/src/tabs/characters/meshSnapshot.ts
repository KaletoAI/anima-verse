/**
 * meshSnapshot — a still picture of a GLB for a small tile (Ruling A48a: the Mesh row's tiles), so a row of
 * tiles costs no live WebGL context each. ONE offscreen renderer is shared and kept; snapshots are made one after
 * the other and cached per URL (a versioned URL never changes its bytes). The model is shown straight on from the
 * front, framed on its box, lit like the viewer (`Model3DViewer`), metalness off; the loaded scene is disposed at
 * once.
 */
import type { Material, Mesh, Object3D, Texture, WebGLRenderer } from 'three'

const cache = new Map<string, Promise<string>>()
let queue: Promise<unknown> = Promise.resolve()
let renderer: WebGLRenderer | null = null

/** Release every GPU resource of a loaded scene (geometry, materials and their textures). */
function disposeScene(root: Object3D): void {
  root.traverse((o: Object3D) => {
    const mesh = o as Mesh
    mesh.geometry?.dispose?.()
    const mats = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).filter(Boolean) as Material[]
    for (const m of mats) {
      for (const value of Object.values(m)) {
        if (value && (value as Texture).isTexture) (value as Texture).dispose()
      }
      m.dispose()
    }
  })
}

async function render(url: string, width: number, height: number): Promise<string> {
  const THREE = await import('three')
  const { createGLTFLoader } = await import('../../lib/gltfLoader')
  const { zeroViewerMetalness } = await import('./modelTexture')
  const gltf = await createGLTFLoader().loadAsync(url)
  const object = gltf.scene
  try {
    zeroViewerMetalness(object)
    if (!renderer) {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
      renderer.setPixelRatio(2)
      renderer.toneMappingExposure = 1.2
    }
    renderer.setSize(width, height, false)
    const scene = new THREE.Scene()
    scene.add(new THREE.AmbientLight(0xffffff, 2.0))
    scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 3.0))
    const key = new THREE.DirectionalLight(0xffffff, 3.0)
    key.position.set(1, 2, 3)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0xffffff, 1.5)
    fill.position.set(-2, 1, 2)
    scene.add(fill)
    scene.add(object)
    const box = new THREE.Box3().setFromObject(object)
    const size = box.getSize(new THREE.Vector3())
    const centre = box.getCenter(new THREE.Vector3())
    const camera = new THREE.PerspectiveCamera(35, width / height, 0.01, 1000)
    const fov = (camera.fov * Math.PI) / 180
    const fitH = (size.y / 2) / Math.tan(fov / 2)
    const fitW = (size.x / 2) / (Math.tan(fov / 2) * camera.aspect)
    const dist = Math.max(fitH, fitW) * 1.12 + size.z / 2
    camera.position.set(centre.x, centre.y, centre.z + dist)
    camera.near = dist / 100
    camera.far = dist * 100
    camera.updateProjectionMatrix()
    camera.lookAt(centre)
    renderer.setClearColor(0x000000, 0)
    renderer.render(scene, camera)
    return renderer.domElement.toDataURL('image/png')
  } finally {
    disposeScene(object)
  }
}

/** A PNG data URL of the GLB at `url`, `width` × `height` CSS pixels (rendered at twice that). */
export function meshSnapshot(url: string, width: number, height: number): Promise<string> {
  const key = `${url}|${width}x${height}`
  let shot = cache.get(key)
  if (!shot) {
    shot = queue.then(() => render(url, width, height))
    queue = shot.catch(() => undefined)
    shot.catch(() => cache.delete(key))
    cache.set(key, shot)
  }
  return shot
}
