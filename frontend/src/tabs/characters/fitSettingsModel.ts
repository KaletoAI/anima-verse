/**
 * Ruling A47 — the fit settings of an own-mesh clothing piece (server: `garments.fit_settings_info`, saved by
 * POST /characters/{n}/garments/{item}/fit-settings): the sleeves per side, the width allowance, the depth allowance
 * (Ruling A68), the arm light.
 * Pure helpers (types, labels, the plain-words reasons composed through the translation layer).
 */
import type { Light } from './hairstylesModel'

export type SleeveChoice = 'auto' | 'generated' | 'wider' | 'fitted'
export type AllowanceChoice = 'auto' | 0 | 3 | 6 | 10
/** Ruling A68: room in front of and behind the trunk, percent of the torso's half depth (no Auto). */
export type DepthChoice = 0 | 3 | 6 | 10
export type SleeveSideKey = 'left' | 'right'

/** One rule of the Auto choice (`garment_fit.auto_sleeve`). */
export interface SleeveWhy {
  rule: 'offset' | 'room' | 'inside' | 'fits'
  cm?: number
  where?: 'upper arm' | 'forearm' | 'wrist' | string
  percent?: number
  room_cm?: number
}

/** One side of `report.transfer.sleeves` (`garment_fit.place_sleeves`). */
export interface SleeveSide {
  setting: SleeveChoice
  applied: Exclude<SleeveChoice, 'auto'>
  why: SleeveWhy[]
  reason: string
  numbers?: {
    offset_max_m: number; offset_where: string; clear_p50_m: number; inside_share: number
  } | null
  shift_max_m?: number
}

export interface ArmLight {
  state: 'green' | 'yellow' | 'red' | 'none'
  sides: Partial<Record<SleeveSideKey, 'green' | 'yellow' | 'red'>>
  worst_cm2: number
}

export interface AllowanceInfo {
  setting: AllowanceChoice
  trigger: Array<'deep_push_share' | 'torso_tight_share'>
  factor: number
  numbers?: { deep_push_share?: number | null; torso_tight_share?: number | null }
  attempts?: Array<{ scale: number; ok: boolean; improves?: boolean; clears?: boolean;
    deep_push_share?: number | null; torso_tight_share?: number | null }>
  inherited?: boolean
}

/** Ruling A68: the depth allowance the shown fit was made with (`report.depth`). */
export interface DepthInfo {
  setting: DepthChoice
  ease_mm: number
  half_depth_mm: number
  inherited?: boolean
}

export interface FitSettingsValues {
  sleeves_left: SleeveChoice
  sleeves_right: SleeveChoice
  allowance: AllowanceChoice
  depth: DepthChoice
}

export interface FitSettingsInfo {
  settings: FitSettingsValues
  /** Those of the shown fit (null: no fit yet). */
  recorded: FitSettingsValues | null
  /** A fit exists and was made with other settings: the next run refits it on the CPU. */
  due: boolean
  sleeves: Partial<Record<SleeveSideKey, SleeveSide>>
  allowance: AllowanceInfo | null
  depth?: DepthInfo | null
  arm_light: ArmLight | null
  numbers: {
    deep_push_share?: number | null; torso_tight_share?: number | null; sleeve_shards?: number | null
    sleeve_skin_left_cm2?: number | null; sleeve_skin_right_cm2?: number | null; scale?: number | null
    trunk_front_gap_p50_m?: number | null; trunk_back_gap_p50_m?: number | null
  }
  accepted: boolean
  built_at: string | null
  choices?: { sleeves: SleeveChoice[]; allowance: AllowanceChoice[]; depth?: DepthChoice[] }
  limits?: { red_cm2: number; deep: number; tight: number; tight_m: number; max_factor: number }
}

type T = (s: string) => string

export const SLEEVE_CHOICES: SleeveChoice[] = ['auto', 'generated', 'wider', 'fitted']
export const ALLOWANCE_CHOICES: AllowanceChoice[] = ['auto', 0, 3, 6, 10]
export const DEPTH_CHOICES: DepthChoice[] = [0, 3, 6, 10]

export const SLEEVE_LABELS: Record<SleeveChoice, string> = {
  auto: 'Auto', generated: 'As generated', wider: 'Wider', fitted: 'Fitted to the arm',
}
export const SLEEVE_HINTS: Record<SleeveChoice, string> = {
  auto: 'Fitted to the arm when the sleeve sits more than 2 cm off the arm, has less than 1.2 cm of room or lies more than 20 % inside the arm; else as generated',
  generated: 'The sleeve as the generator made it, re-centred on the arm',
  wider: 'As generated, then 20 % wider around the arm',
  fitted: 'Laid onto the arm with 12 mm of room; a third of its folds is kept, the texture stays',
}

export function allowanceLabel(choice: AllowanceChoice, t: T): string {
  return choice === 'auto' ? t('Auto') : `+${choice} %`
}

export const ALLOWANCE_HINT = 'Widens the piece about the body’s centre before the fit pushes it out: the sides, and front and back in proportion (where the piece lies inside the body, the push-out takes that back). Auto widens a fit that passes but lies tight — more than 8 % pushed out over 3 cm, or more than 18 % of the trunk closer than 1.5 cm — by the smallest step up to 8 % that passes every check. A fixed value fits exactly that much wider, with no automatic step.'

/** Ruling A68. */
export const DEPTH_HINT = 'Room in front of and behind the trunk, added after the fit pushes the piece out: the front and the back stand off by this share of the torso’s half depth. Sleeves, the collar and the neck opening keep their size. Auto never adds depth; the default is +0 %.'

export function depthLabel(choice: DepthChoice): string {
  return `+${choice} %`
}

const WHERE: Record<string, string> = { 'upper arm': 'upper arm', forearm: 'forearm', wrist: 'wrist' }

function cm(v: number | undefined): string {
  return v == null ? '–' : String(Math.round(v * 10) / 10)
}

/** One Auto rule in plain words (`garment_fit.sleeve_reason_text`'s words). */
export function whyText(w: SleeveWhy, t: T): string {
  if (w.rule === 'offset') {
    return t('the sleeve sits {cm} cm off the {where}').replace('{cm}', cm(w.cm))
      .replace('{where}', t(WHERE[w.where || ''] || String(w.where || '')))
  }
  if (w.rule === 'room') {
    return (w.cm ?? 0) <= 0.3 ? t('it is as thin as the arm')
      : t('it is only {cm} cm wider than the arm').replace('{cm}', cm(w.cm))
  }
  if (w.rule === 'inside') return t('{percent} % of it lies inside the arm').replace('{percent}', String(w.percent ?? 0))
  return t('the sleeve sits on the arm ({cm} cm off its centre, {room} cm of room)')
    .replace('{cm}', cm(w.cm)).replace('{room}', cm(w.room_cm))
}

/** "Auto → Fitted to the arm: the sleeve sits 8 cm off the forearm and it is as thin as the arm"; a fixed setting
 *  names itself ("Set: Wider"). */
export function sleeveReason(side: SleeveSide | undefined, t: T): string {
  if (!side) return t('No sleeve on this side')
  if (side.setting !== 'auto') return `${t('Set to')}: ${t(SLEEVE_LABELS[side.applied] || side.applied)}`
  const head = `${t('Auto')} → ${t(SLEEVE_LABELS[side.applied] || side.applied)}`
  const parts = (side.why || []).map((w) => whyText(w, t))
  return parts.length ? `${head}: ${parts.join(` ${t('and')} `)}` : head
}

/** The arm light's colour (grey without a measured sleeve). */
export function armLightColour(light: ArmLight | null | undefined): Light {
  return !light || light.state === 'none' ? 'grey' : light.state
}

/** The arm light in plain words: what is seen, where, what fixes it. */
export function armLightText(light: ArmLight | null | undefined, numbers: FitSettingsInfo['numbers'] | undefined,
  t: T): string {
  if (!light || light.state === 'none') return t('Arms: no sleeves measured')
  if (light.state === 'green') return t('Arms: no skin seen inside the sleeves')
  const sides = (['left', 'right'] as SleeveSideKey[])
    .map((s) => ({ s, v: numbers?.[`sleeve_skin_${s}_cm2` as const] }))
    .filter((x) => x.v != null && (x.v as number) >= 0.5)
    .map((x) => `${t(x.s === 'left' ? 'left' : 'right')} ${cm(x.v as number)} cm²`)
  const seen = t('Arms: skin seen inside the sleeves — {sides} (front + back)').replace('{sides}', sides.join(', '))
  return light.state === 'red'
    ? `${seen}. ${t('The sleeve is torn open or lies inside the arm; “Fitted to the arm” lays it onto the arm.')}`
    : seen
}

/** The arm light in a few words (the body switch, the fit row): the worst side only. */
export function armLightShort(light: ArmLight | null | undefined, t: T): string {
  if (!light || light.state === 'none') return ''
  if (light.state === 'green') return t('Arms: no skin seen')
  return t('Arms: {n} cm² of skin seen inside a sleeve').replace('{n}', cm(light.worst_cm2))
}

/** Ruling A50: a body's trunk coverage in words — "Trunk covered: front 82 % (source 85 %) · side 93 % (source
 *  92 %) · back 100 % (source 95 %)", the shares the outfit-body gate compares; '' without all three. */
export function trunkCoverText(torso: Partial<Record<'front' | 'side' | 'back', { fit: number; source: number }>>
  | null | undefined, t: T): string {
  const f = torso?.front, s = torso?.side, b = torso?.back
  if (!f || !s || !b) return ''
  const pct = (v: number) => `${Math.round(v * 100)} %`
  return t('Trunk covered: front {f} (source {fs}) · side {s} (source {ss}) · back {b} (source {bs})')
    .replace('{f}', pct(f.fit)).replace('{fs}', pct(f.source)).replace('{s}', pct(s.fit))
    .replace('{ss}', pct(s.source)).replace('{b}', pct(b.fit)).replace('{bs}', pct(b.source))
}

/** "Pushed out over 3 cm 2.7 % · Trunk closer than 1.5 cm 23 % · width +2 %". */
export function allowanceNumbers(info: FitSettingsInfo, t: T): string {
  const n = info.numbers || {}
  const pct = (v: number | null | undefined, d = 1) => (v == null ? '–' : `${(v * 100).toFixed(d)} %`)
  const scale = n.scale ?? info.allowance?.factor ?? 1
  const width = scale > 1.0001 ? t('width +{pct} %').replace('{pct}', String(Math.round((scale - 1) * 100)))
    : t('width as generated')
  const parts = [
    `${t('Pushed out over 3 cm')} ${pct(n.deep_push_share)}`,
    `${t('Trunk closer than 1.5 cm')} ${pct(n.torso_tight_share, 0)}`,
    width,
  ]
  const d = info.depth
  if (d && d.setting > 0) {
    parts.push(t('depth +{pct} % ({mm} mm)').replace('{pct}', String(d.setting)).replace('{mm}', d.ease_mm.toFixed(1)))
  }
  if (n.trunk_front_gap_p50_m != null && n.trunk_back_gap_p50_m != null) {
    parts.push(`${t('Gap front / back')} ${(n.trunk_front_gap_p50_m * 1000).toFixed(1)} / ${
      (n.trunk_back_gap_p50_m * 1000).toFixed(1)} mm`)
  }
  return parts.join(' · ')
}

/** Why Auto widened (or did not): the trigger and the step it took. */
export function allowanceReason(info: FitSettingsInfo, t: T): string {
  const a = info.allowance
  if (!a) return ''
  if (a.inherited) return t('On a body shape the width comes from the plain body’s fit')
  if (a.setting !== 'auto') return a.setting === 0 ? t('Set: no extra width') : t('Set: exactly this much wider')
  if (!a.trigger?.length) return t('Auto: the fit does not lie tight — not widened')
  const why = a.trigger.map((k) => (k === 'deep_push_share' ? t('more than 8 % pushed out over 3 cm')
    : t('more than 18 % of the trunk closer than 1.5 cm'))).join(` ${t('and')} `)
  return a.factor > 1.0001
    ? t('Auto: {why} — widened {pct} %').replace('{why}', why).replace('{pct}', String(Math.round((a.factor - 1) * 100)))
    : t('Auto: {why} — no wider step passed every check').replace('{why}', why)
}

/** Ruling A68: what the shown fit did in depth, in plain words (a fit made before A68 carries no depth: none). */
export function depthReason(info: FitSettingsInfo, t: T): string {
  const d = info.depth
  if (!d) return info.recorded ? t('Shown fit: no extra depth') : ''
  if (d.inherited) return t('On a body shape the depth comes from the plain body’s fit')
  return d.setting > 0
    ? t('Shown fit: {mm} mm more room in front and behind').replace('{mm}', d.ease_mm.toFixed(1))
    : t('Shown fit: no extra depth')
}
