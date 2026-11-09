/**
 * Shared styles, chip specs and helpers of the garment step views
 * (GarmentSteps, FieldHair, WardrobeGarment) — kept out of the component
 * modules so fast refresh keeps working.
 */
import type { CSSProperties } from 'react'
import type { GateLimit, GateRecord } from './useGarment'

export const TILE_HEIGHT = 200

export const EMPTY_TILE: CSSProperties = {
  width: '100%',
  height: TILE_HEIGHT,
  borderRadius: 6,
  border: '1px solid var(--border, #30363d)',
  background: 'rgba(255, 255, 255, 0.04)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: 6,
  boxSizing: 'border-box',
}

export const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
export const WARN_STYLE: CSSProperties = { color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }
export const ROW: CSSProperties = { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }

/** The server's chip limits per step (`limits` of the info routes). */
export type GarmentLimits = Partial<Record<string, Record<string, GateLimit>>>

/** The body of POST /characters/{n}/garments/{item}/run. */
export interface GarmentRunBody { step?: string; view?: string; force?: boolean }

/** One chip: which number of a gate record, how it reads, how it scales.
 *  The limit itself always comes from the server. */
export interface ChipSpec {
  key: string
  label: string
  /** Multiplier for display (shares → %, metres → cm). */
  scale: number
  unit: string
  digits: number
  /** A boolean of the record that says whether this number is gated
   *  (false = reported only, e.g. `head_gated` of a piece worn on the head). */
  gatedKey?: string
}

export const MESH_CHIPS: ChipSpec[] = [
  { key: 'largest_component_share', label: 'Component share', scale: 100, unit: '%', digits: 1 },
]

export const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** A HairDeck fit attempt `{attempt, seed, ok, reasons, limits, metrics}`
 *  with its metrics lifted beside attempt/seed, so RecordNumbers lists them. */
export function flatFit(r: GateRecord | null | undefined): unknown {
  if (!r || typeof r.metrics !== 'object' || r.metrics === null) return r
  return { attempt: r.attempt, seed: r.seed, ...(r.metrics as object), reasons: r.reasons }
}
