/**
 * Shared types + small formatters of the surface-texture library (AV3D-13).
 * Split out of SurfaceTexturesTab so the container, the generator form, the
 * kind detail and the blend editor all read from one place.
 */
import { TERRAIN_TYPES } from '../world/worldTypes'

export interface TexVersion {
  filename: string
  url: string
  size_m: number
  created_at: string
  source: string
  backend: string
  prompt: string
  negative: string
  active: boolean
}

export interface TexGroup {
  kind: string
  versions: TexVersion[]
}

export interface BackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
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
