/**
 * FitSettings — Ruling A47: the fit settings of an own-mesh clothing piece beside its 3D preview in the piece
 * dialog (GarmentPieceDialog): the arm light of the shown fit (skin seen inside the sleeves, front + back), per side
 * "Sleeves: Auto | As generated | Wider | Fitted to the arm" with what Auto chose and why, "Width allowance: Auto |
 * +0 | +3 | +6 | +10 %" with the numbers it acts on and (Ruling A68) "Depth allowance: +0 | +3 | +6 | +10 %" — room
 * in front of and behind the trunk, no Auto. Each select SAVES on its own (POST
 * …/garments/{item}/fit-settings) and runs nothing; a fit made with other settings reads "Fit due — refits on the
 * CPU, 0 hub jobs" with its Re-fit beside it (the Figure tab: the next Build refits it).
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useClockSettings } from '../../lib/clockFormat'
import { RunButton } from './GarmentSteps'
import type { RunFeedback } from './useGarment'
import type { GarmentRunBody } from './garmentStyle'
import { StepLight } from './StepRows'
import { stampLabel } from './freshnessText'
import {
  ALLOWANCE_CHOICES, ALLOWANCE_HINT, DEPTH_CHOICES, DEPTH_HINT, SLEEVE_CHOICES, SLEEVE_HINTS, SLEEVE_LABELS,
  allowanceLabel, allowanceNumbers, allowanceReason, armLightColour, armLightText, depthLabel, depthReason,
  sleeveReason,
} from './fitSettingsModel'
import type {
  AllowanceChoice, DepthChoice, FitSettingsInfo, FitSettingsValues, SleeveChoice, SleeveSideKey,
} from './fitSettingsModel'

const PANEL: CSSProperties = {
  display: 'grid', gridTemplateColumns: 'auto minmax(150px, 190px) 1fr', gap: '4px 8px', alignItems: 'center',
  padding: '6px 8px', border: '1px solid var(--border, #30363d)', borderRadius: 6, fontSize: '0.85em',
}
const SPAN: CSSProperties = { gridColumn: '1 / -1', display: 'flex', gap: 8, alignItems: 'center' }
const REASON: CSSProperties = { minWidth: 0, overflowWrap: 'anywhere' }
const SELECT: CSSProperties = { width: '100%', padding: '1px 4px', fontSize: '1em' }

export function FitSettings({ character, itemId, info, busy, feedback, onRun, onSaved, noRunAll = false,
  numbersOf = '', refitOn = '' }: {
  character: string
  itemId: string
  info: FitSettingsInfo
  busy: boolean
  feedback?: RunFeedback
  onRun: (body: GarmentRunBody, slot?: string) => void
  /** After a save: poll the dialog again. */
  onSaved: () => void
  /** Opened from the Figure tab: no run buttons there (its Build refits). */
  noRunAll?: boolean
  /** Ruling A50: the body the shown numbers belong to ("Base body" while a body switch is shown; "" = unnamed). */
  numbersOf?: string
  /** Ruling A50: the body shape the Re-fit fits on ("" = the plain body); the button names it. */
  refitOn?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  useClockSettings()
  const [saving, setSaving] = useState<Partial<FitSettingsValues> | null>(null)
  const values: FitSettingsValues = { ...info.settings, ...(saving || {}) }

  const save = async (change: Partial<FitSettingsValues>) => {
    setSaving(change)
    try {
      const d = await apiPost<{ fit_settings: FitSettingsInfo }>(
        `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/fit-settings`, change)
      toast(`${t('Saved')} · ${d.fit_settings.due ? t('Fit due — refits on the CPU, 0 hub jobs')
        : t('nothing becomes due')}`, 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(null)
      onSaved()
    }
  }

  const sleeveRow = (side: SleeveSideKey) => {
    const key = side === 'left' ? 'sleeves_left' : 'sleeves_right'
    const report = info.sleeves?.[side]
    const value = values[key]
    const autoTo = value === 'auto' && report?.applied ? ` (→ ${t(SLEEVE_LABELS[report.applied])})` : ''
    return (
      <>
        <label htmlFor={`fit-sleeve-${side}`}>{t(side === 'left' ? 'Left sleeve' : 'Right sleeve')}</label>
        <select id={`fit-sleeve-${side}`} className="ga-input" style={SELECT} value={value} disabled={busy || saving !== null}
          title={t(SLEEVE_HINTS[value])}
          onChange={(e) => { void save({ [key]: e.target.value as SleeveChoice }) }}>
          {SLEEVE_CHOICES.map((c) => (
            <option key={c} value={c} title={t(SLEEVE_HINTS[c])}>
              {t(SLEEVE_LABELS[c])}{c === value ? autoTo : ''}
            </option>
          ))}
        </select>
        <span className="ga-hint" style={REASON}
          title={report?.numbers ? `${t('Offset from the arm')} ${(report.numbers.offset_max_m * 100).toFixed(1)} cm · ${
            t('Room around the arm')} ${(report.numbers.clear_p50_m * 100).toFixed(1)} cm · ${t('Inside the arm')} ${
            Math.round(report.numbers.inside_share * 100)} %` : undefined}>
          {!info.recorded ? t('Decided at the first fit')
            : `${info.recorded[key] !== value ? `${t('Shown fit')}: ` : ''}${sleeveReason(report, t)}`}
        </span>
      </>
    )
  }

  const light = info.arm_light
  const built = stampLabel(info.built_at)
  return (
    <div style={PANEL} role="group" aria-label={t('Fit settings')}>
      <div style={SPAN}>
        <StepLight light={armLightColour(light)} />
        <span style={{ ...REASON, flex: '1 1 0' }}
          title={t('Measured on the shown fit: skin of the arm visible through the sleeve outline, front and back view; green none, yellow below 30 cm², red from 30 cm²')}>
          {numbersOf ? `${numbersOf}: ` : ''}{armLightText(light, info.numbers, t)}
        </span>
        {built ? <span className="ga-hint">{t('Built')} {built}</span> : null}
      </div>
      {sleeveRow('left')}
      {sleeveRow('right')}
      <label htmlFor="fit-allowance">{t('Width allowance')}</label>
      <select id="fit-allowance" className="ga-input" style={SELECT} value={String(values.allowance)}
        disabled={busy || saving !== null} title={t(ALLOWANCE_HINT)}
        onChange={(e) => {
          const raw = e.target.value
          void save({ allowance: (raw === 'auto' ? 'auto' : Number(raw)) as AllowanceChoice })
        }}>
        {ALLOWANCE_CHOICES.map((c) => (
          <option key={String(c)} value={String(c)}>{allowanceLabel(c, t)}</option>
        ))}
      </select>
      <span className="ga-hint" style={REASON} title={t(ALLOWANCE_HINT)}>
        {info.recorded ? allowanceReason(info, t) : t('Decided at the first fit')}
      </span>
      <label htmlFor="fit-depth">{t('Depth allowance')}</label>
      <select id="fit-depth" className="ga-input" style={SELECT} value={String(values.depth ?? 0)}
        disabled={busy || saving !== null} title={t(DEPTH_HINT)}
        onChange={(e) => { void save({ depth: Number(e.target.value) as DepthChoice }) }}>
        {DEPTH_CHOICES.map((c) => (
          <option key={c} value={String(c)}>{depthLabel(c, info.depth?.half_depth_mm)}</option>
        ))}
      </select>
      <span className="ga-hint" style={REASON} title={t(DEPTH_HINT)}>
        {info.recorded ? depthReason(info, t) : t('Auto never adds depth')}
      </span>
      {info.recorded ? (
        <div style={SPAN} className="ga-hint" title={t(ALLOWANCE_HINT)}>
          {numbersOf ? `${numbersOf}: ` : ''}{allowanceNumbers(info, t)}
        </div>
      ) : null}
      {info.due ? (
        <div style={SPAN}>
          <StepLight light="yellow" />
          <span>{t('Fit due — refits on the CPU, 0 hub jobs')}</span>
          {noRunAll ? <span className="ga-hint">{t('The next Build refits it.')}</span> : (
            <RunButton feedback={feedback} slot="fitsettings" disabled={busy}
              title={t('Fits the piece again with these settings on the CPU — 0 hub jobs; the shown fit stays in use until then')}
              label={refitOn ? `${t('Re-fit (0 hub jobs)')} · ${refitOn}` : t('Re-fit (0 hub jobs)')}
              onClick={() => onRun({ step: 'fit', force: true }, 'fitsettings')} />
          )}
        </div>
      ) : (
        <div style={SPAN} className="ga-hint">{t('Each setting saves on its own and runs nothing.')}</div>
      )}
    </div>
  )
}
