/**
 * TEXTURE SLOTS of a placed prop (§ B2 v5) — the picture in the frame, the
 * look of the pane.
 *
 * A slot IS a material of the model: whoever models the prop names the
 * fillable surface (`picture`, `sign`, `glass`, or anything behind the `slot_`
 * prefix), the server reads those names off the GLB and the placement says
 * what goes in. The payload states the finished answer as
 * `models[].slots = {"<slot name>": {image} | {preset}}`, and the SLOT NAME is
 * the material name without its `slot_` prefix — the prefix is `detect_slots`'
 * marker for "this surface is fillable", not part of the slot's name, so the
 * material `slot_picture_1` is the slot `picture_1`. This routine is the one
 * place that WRITES it onto a mesh, and both renderers call it — the 3D client
 * and the admin floor-plan preview.
 *
 * THE ONE RULE THAT MAKES IT CORRECT: clone the material for THIS placement
 * before touching it. The GLB loader keeps one `THREE.Group` per URL and hands
 * it to every placement, and `Object3D.clone()` copies nodes while SHARING
 * material instances — writing straight onto a matched material would hang the
 * hall's poster in the kitchen too. Same reason `applyDepthCut` clones, and
 * the check that guards it is `scripts/smoke_slot_materials.mjs` [2].
 *
 * `three` is a parameter, never an import (package rule), and the texture
 * LOADER is one too: the client has its own loading policy and the preview
 * another, while "sRGB, not flipped, on `map`" is the same everywhere and
 * belongs here.
 *
 * The returned array is every clone this call made. The caller keeps it and
 * hands it to `disposeSlotMaterials` when the placement goes away — a texture
 * per placement is real memory, and nothing else in the scene knows these
 * objects exist.
 */
import type { Material, Mesh, Object3D, Texture } from 'three'
import type { SceneSlotValues } from './types'

/** THE LOOKS a `material` slot can be set to — the list's home is here,
 *  because a preset that no renderer draws is not a preset. `app/core/props.py`
 *  mirrors it as `SLOT_PRESETS` so the storage layer can refuse an unknown
 *  one; change both or neither. */
export const MATERIAL_PRESETS = ['glass'] as const
export type MaterialPreset = (typeof MATERIAL_PRESETS)[number]

/** What "glass" MEANS, numerically. One declaration for both renderers, for
 *  the same reason the surface kinds live in `materials.ts`: the pane of a
 *  door must not be milkier in the preview than in the client.
 *
 *  `transmission` is only written onto a material that already has the field
 *  (i.e. a `MeshPhysicalMaterial`) — `MeshStandardMaterial` ignores it, and a
 *  stray property would claim a refraction nobody renders. */
export const GLASS_PRESET = {
  opacity: 0.3,
  roughness: 0.06,
  metalness: 0,
  transmission: 0.85,
}

/** How a renderer turns a payload URL into a texture. `TextureLoader.load` in
 *  both apps today — the routine only ever sets what it gets. `onError` is the
 *  loader's own error callback: a picture that never arrives must not leave the
 *  surface white, so this routine puts the material back the way it found it. */
export type SlotTextureLoader = (url: string, onError?: () => void) => Texture

/** A material as this routine has to see it: three's own types split `map`
 *  and the PBR dials across several classes, and the routine deliberately
 *  writes only what a material actually has. */
type SlotMaterial = Material & {
  name: string
  map?: Texture | null
  color?: { set: (hex: number) => void; getHex?: () => number }
  opacity?: number
  roughness?: number
  metalness?: number
  transmission?: number
  transparent?: boolean
  side?: unknown
  needsUpdate?: boolean
}

/** WHICH SLOT a material is. `props.detect_slots` reads `slot_picture_1` off
 *  the GLB and stores the slot as `picture_1`; the recipe keys `slots` by that
 *  stored name, so the renderer has to take the prefix off again or a split
 *  picture prop — whose materials ALWAYS carry it — matches nothing.
 *
 *  ONE leading `slot_` goes, and the rest is trimmed again for the same reason
 *  the server does it: `slot_ picture_1` is a modeller's typo, not a slot whose
 *  name starts with a space. A bare `picture` is its own slot name and passes
 *  through untouched. */
const slotNameOf = (raw: string | undefined): string => {
  const key = (raw || '').trim().toLowerCase()
  return key.startsWith('slot_') ? key.slice(5).trim() : key
}

/**
 * Fill the slots of an already placed group.
 *
 * `slots` is the spec's own map, so the keys are SLOT names — that is the
 * material name with its `slot_` prefix taken off, exactly as
 * `props.detect_slots` took it off when it read the model. Matching is
 * case-insensitive and trimmed on both sides (the server stores names
 * lower-cased, an exporter may not). A slot the mesh does not name is simply
 * not there — a prop whose model was regenerated without its frame keeps
 * standing, it just holds no picture.
 *
 * Call it BEFORE `applyDepthCut` / `applyClipOutline`: those clone every
 * material they traverse, so a slot written first rides into their clones for
 * free, while a slot written afterwards would have to be written again after
 * every one of them.
 */
export function applySlotMaterials(
  THREE: typeof import('three'),
  root: Object3D,
  slots: SceneSlotValues | undefined,
  loadTexture: SlotTextureLoader,
): Material[] {
  const wanted = new Map<string, { image?: string; preset?: string }>()
  for (const [name, value] of Object.entries(slots || {})) {
    const key = (name || '').trim().toLowerCase()
    if (key && value) wanted.set(key, value)
  }
  if (!wanted.size) return []

  const clones: Material[] = []
  const fill = (src: Material): Material => {
    const cur = src as SlotMaterial
    const value = wanted.get(slotNameOf(cur.name))
    if (!value) return src
    const image = (value.image || '').trim()
    const preset = (value.preset || '').trim().toLowerCase()
    const isPreset = (MATERIAL_PRESETS as readonly string[]).includes(preset)
    if (!image && !isPreset) return src
    const mat = src.clone() as SlotMaterial
    if (image) {
      // A picture that never arrives (deleted from the gallery, a 404 out of
      // the cache) would otherwise leave the surface WHITE — the neutralised
      // tint below with no map on it. So the loader's error hands the
      // material back exactly as the mesh modelled it.
      const tint = cur.color?.getHex?.() ?? 0xffffff
      const tex = loadTexture(image, () => {
        mat.map = null
        mat.color?.set(tint)
        mat.needsUpdate = true
      })
      // sRGB because a picture is authored in sRGB, `flipY = false` because
      // glTF UVs run the other way than three's image default — the same two
      // lines the character FBX textures need (`client3d/scene/figures.ts`).
      tex.colorSpace = THREE.SRGBColorSpace
      tex.flipY = false
      mat.map = tex
      // The base colour of a frame material tints whatever is put on it; a
      // grey placeholder surface would darken every picture hung on it.
      mat.color?.set(0xffffff)
    } else {
      // The only preset today. Kept as an `if` rather than a lookup table so
      // the next one has to declare what IT writes instead of inheriting a
      // shape that happened to fit glass.
      mat.transparent = true
      mat.opacity = GLASS_PRESET.opacity
      mat.roughness = GLASS_PRESET.roughness
      mat.metalness = GLASS_PRESET.metalness
      if ('transmission' in mat) mat.transmission = GLASS_PRESET.transmission
      // A pane is a plane: single-sided it disappears the moment one walks
      // round the door.
      mat.side = THREE.DoubleSide
    }
    mat.userData = { ...mat.userData, __slotClone: true }
    mat.needsUpdate = true
    clones.push(mat as Material)
    return mat as Material
  }

  root.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(fill)
      : fill(mesh.material)
  })
  return clones
}

/** Free what `applySlotMaterials` created — the clones AND the textures it
 *  loaded for them (unlike the cut/clip clones, whose maps belong to the
 *  loader cache, a slot texture is this placement's own). */
export function disposeSlotMaterials(mats: Material[] | undefined): void {
  for (const m of mats || []) {
    (m as SlotMaterial).map?.dispose?.()
    m.dispose?.()
  }
}
