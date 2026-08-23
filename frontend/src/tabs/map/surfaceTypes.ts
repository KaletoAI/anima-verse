/**
 * Shared types + small formatters of the surface-texture library (AV3D-13).
 * Split out of SurfaceTexturesTab so the container, the generator form, the
 * kind detail and the blend editor all read from one place.
 */
import type { SurfaceMaterialSpec } from '@anima/scene-render'
import { TERRAIN_TYPES } from '../world/worldTypes'

export type { SurfaceMaterialSpec }

export interface TexVersion {
  filename: string
  url: string
  size_m: number
  created_at: string
  source: string
  backend: string
  prompt: string
  negative: string
  /** The version that renders RIGHT NOW — season already resolved (E2c). */
  active: boolean
  /** Season slots this version is selected for: `''` is the seasonless
   *  default, every other entry a season name (lowercased). A kind with only
   *  the `''` slot behaves exactly as it did before seasons existed. */
  seasons: string[]
}

export interface TexGroup {
  /** The ID: file names, the terrain field, the client contract, every
   *  stored reference. Derived from the name when the kind is created and
   *  IMMUTABLE afterwards — it never reaches a prompt. */
  kind: string
  /** Free text with spaces — the only thing pickers show. */
  name?: string
  /** The one text that goes into the image prompt. Seeded when the kind is
   *  created; what stands here is what gets sent. */
  description?: string
  /** How the kind is LIT, not what it looks like — water is not recognised by
   *  its colour but by what it reflects and how it moves. Absent = matte. */
  material?: SurfaceMaterialSpec | null
  versions: TexVersion[]
}

/** The material classes and what each one starts at — mirrored from
 *  `_CLASS_FIELDS`/`_CLASS_DEFAULTS` on the server, which clamps and drops
 *  whatever does not belong to the class. Only the tint has no server-side
 *  default: it is optional there, so the UI supplies a sensible one per class
 *  when you switch. */
export const CLASS_DEFAULTS: Record<string, Record<string, number | string>> = {
  water: { tint: '#3f7fb8', map_strength: 0.75, wave_m: 1.6, speed: 0.25, flow_speed: 0.15,
           sky_mix: 0.55, roughness: 0.08 },
  ice: { tint: '#cfe6f2', map_strength: 0.6, wave_m: 4, speed: 0, flow_speed: 0,
         sky_mix: 0.7, roughness: 0.05 },
  gloss: { tint: '#ffffff', map_strength: 1, roughness: 0.25, metalness: 0.05 },
  glow: { tint: '#ffd08a', map_strength: 1, glow: 1 },
}

/** One dial: key, label, min, max, step. Metre values are marked as such in
 *  the label — they are the ones the 3 × 3 preview exists for. */
export type MaterialDial = [string, string, number, number, number]

export const CLASS_DIALS: Record<string, MaterialDial[]> = {
  water: [
    ['wave_m', 'Ripple length (m)', 0.2, 20, 0.1],
    ['speed', 'Ripple drift, still water (m/s)', 0, 2, 0.01],
    ['flow_speed', 'Current, flowing water (m/s)', 0, 2, 0.01],
    ['sky_mix', 'Sky reflection', 0, 1, 0.05],
    ['roughness', 'Roughness', 0, 1, 0.01],
    ['map_strength', 'Texture vs. tint', 0, 1, 0.05],
  ],
  ice: [
    ['wave_m', 'Surface scale (m)', 0.2, 20, 0.1],
    ['sky_mix', 'Sky reflection', 0, 1, 0.05],
    ['roughness', 'Roughness', 0, 1, 0.01],
    ['map_strength', 'Texture vs. tint', 0, 1, 0.05],
    ['speed', 'Drift (m/s)', 0, 2, 0.01],
    ['flow_speed', 'Drift on a current (m/s)', 0, 2, 0.01],
  ],
  gloss: [
    ['roughness', 'Roughness', 0, 1, 0.01],
    ['metalness', 'Metalness', 0, 1, 0.05],
    ['map_strength', 'Texture vs. tint', 0, 1, 0.05],
  ],
  glow: [
    ['glow', 'Glow strength', 0, 5, 0.1],
    ['map_strength', 'Texture vs. tint', 0, 1, 0.05],
  ],
}

/** What each class does, in one line — shown under the picker. */
export const CLASS_HINTS: Record<string, string> = {
  matte: 'Matte, like every other ground surface.',
  water: 'Moving ripples, low roughness and a sky reflection — the texture stays the base colour.',
  ice: 'The same surface standing still: reflective, with structure, but no flow.',
  gloss: 'Polished or wet — a tiled floor, cobbles after rain, a metal plate (turn metalness up).',
  glow: 'The texture EMITS: neon, lava, crystals. Stays bright when everything around it goes dark.',
}

export interface BackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
  /** false = this backend has no negative input (distilled / guidance-free
   *  model); the server folds the negations into the prompt, so the form
   *  hides the negative field. Resolved server-side from auto/yes/no. */
  supports_negative_prompt?: boolean
}

export interface BlendZone {
  kind: string
  until?: number
}

export interface Blend {
  toward: string
  zones: BlendZone[]
  noise?: number
}

/** Suggested kinds — open vocabulary, must match the tiles' terrain field. */
export const KNOWN_KINDS = Array.from(
  new Set([...TERRAIN_TYPES, 'gravel', 'dirt', 'snow']))

/** id of the shared kind <datalist> — rendered once by the container. */
export const KIND_DATALIST_ID = 'surface-kind-options'

/** An id read back as words ("dark_stone" → "dark stone"). Display only — an
 *  id never goes into a prompt, and the server owns the reverse direction
 *  (name → id) so the two cannot drift. */
export const unslugKind = (kind: string) =>
  (kind || '').replace(/[_-]+/g, ' ').trim()

/** What the Prompt Help must know before it "improves" a surface prompt: a
 *  tiling material has no scene, no camera and no light direction, so
 *  anything the assistant adds there comes back as a visible seam. */
export const SURFACE_PROMPT_CONTEXT =
  'This prompt renders a SEAMLESS TILEABLE surface texture seen straight from '
  + 'above: flat even lighting, no perspective, no vignette, no drop shadows, '
  + 'no horizon, no objects or subjects, no border. Keep it a material, not a scene.'

/** Compact "how was this made" label: backend for generated versions, an
 *  upload marker for uploads, em dash for legacy files without meta. */
export function madeWith(v: TexVersion, t: (en: string) => string): string {
  if (v.source === 'generated') return v.backend || t('generated')
  return v.source === 'uploaded' ? t('uploaded') : '—'
}

export function dateShort(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
