/**
 * FootwearAllowance — Ruling A82: the footwear piece's Width and Length allowance beside the shod preview, each on its
 * own: Auto or −10 … +20 % (`footwear_fit.ALLOWANCE_STEPS`; a negative step is tighter, A174), the millimetres beside the step (Length = that share of
 * the foot's length, all of it heel room; Width = that share of the shoe's ball width). Dragging previews the shoe
 * live in the viewer (`footwearAllowanceModel.ts`, the fit's rule); Save stores the settings only (POST
 * …/garments/{item}/footwear/allowance) — the fit becomes due and Re-fit / Run all / the Figure tab's Build applies it
 * on the CPU, 0 hub jobs. Auto: Width +0 (the fit widens the shoe to the foot already), Length +0 or, when the fit
 * at +0 is refused because the foot pokes out, the smallest step the checks accept — what Auto took on the shown fit
 * is named. Server: `garment_footwear.allowance_view`. While the shoe itself is refused at a source step (`blocked`:
 * no fit exists yet) the box names that step and its refusal above the sliders — the step can be accepted anyway in
 * the steps beside, and whatever is saved here applies to the first fit.
 *
 * "Adjust shoe" (2026-11-25, `footwear_fit.manual_matrix`): always available, on an accepted or a refused fit — the
 * shoe moved forward / up / outward (mm), turned (toe out, toe up, tilt in, degrees) and sized (percent) about the heel
 * end of its sole, per shoe and wearer (`garment_footwear.MANUAL_KEY`). The viewer beside previews it live (the same
 * map, `footwearAllowanceModel.ts` `previewMap`); every millimetre slider names its reference (the shoe's and the
 * foot's length). Save stores the allowance and the adjustment and then runs Re-fit on the CPU (0 hub jobs) where the
 * dialog offers it; the gates judge the adjusted shoe, and a refusal can still be accepted on the body.
 */
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { StepLight } from './StepRows'
import { FOOTWEAR_STEP_LABELS, WARN_STYLE } from './garmentStyle'
import { MANUAL_NONE, resolved, sameManual, stepText } from './footwearAllowanceModel'
import type { AllowanceName, AllowanceSetting, FootwearAllowanceView, ManualAdjust } from './footwearAllowanceModel'

const BOX: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', borderRadius: 6,
  border: '1px solid var(--border, #30363d)' }
const ROW: CSSProperties = { display: 'flex', alignItems: 'center', gap: 6 }

const HINTS: Record<AllowanceName, string> = {
  width: 'Makes the shoe wider across the foot by this share of its width at the ball. Auto adds nothing: the fit already widens a shoe to the foot.',
  length: 'Makes the shoe one size longer: all of it is room behind the heel, the toes keep their place. Auto takes the smallest step the checks accept when the foot pokes out of the shoe.',
}
/** A174: below 0 the shoe is tighter; the fit's checks still refuse a shoe the foot pokes out of. */
const NEGATIVE_HINT = 'Below 0 the shoe is tighter; the checks still refuse a shoe the foot pokes out of.'
const LABELS: Record<AllowanceName, string> = { width: 'Width', length: 'Length' }
const WHAT: Record<AllowanceName, string> = { width: 'across the ball', length: 'heel room' }
const ARIA: Record<AllowanceName, string> = { width: 'Width allowance', length: 'Length allowance' }

/** The adjustment sliders: [key, index, label, hint, unit]. */
const MANUAL_ROWS: Array<{ key: 'offset_mm' | 'rotate_deg'; i: number; label: string; hint: string }> = [
  { key: 'offset_mm', i: 0, label: 'Forward', hint: 'Moves the shoe toward the toes (+) or the heel (−) on the foot.' },
  { key: 'offset_mm', i: 1, label: 'Up', hint: 'Moves the shoe up (+) or down (−) on the foot; the figure then stands on the shoe again, so the foot sits deeper (+) or higher (−) in it.' },
  { key: 'offset_mm', i: 2, label: 'Outward', hint: 'Moves the shoe away from the other foot (+) or toward it (−); mirrored on the two shoes.' },
  { key: 'rotate_deg', i: 0, label: 'Toe out', hint: 'Turns the toe outward (+) or inward (−) about the heel.' },
  { key: 'rotate_deg', i: 1, label: 'Toe up', hint: 'Lifts the toe (+) or lowers it (−) about the heel; the checks refuse a sole that sinks into the floor.' },
  { key: 'rotate_deg', i: 2, label: 'Tilt in', hint: 'Leans the shoe over toward the other foot (+) or away (−).' },
]

export function FootwearAllowance({ character, itemId, view, draft, onDraft, manual = MANUAL_NONE, onManual, busy,
  onSaved, onRefit }: {
  character: string
  itemId: string
  view: FootwearAllowanceView
  /** The settings previewed (lifted: the viewer beside deforms by them). */
  draft: { width: AllowanceSetting; length: AllowanceSetting }
  onDraft: (d: { width: AllowanceSetting; length: AllowanceSetting }) => void
  /** The manual adjustment previewed (lifted like the allowance). */
  manual?: ManualAdjust
  onManual?: (m: ManualAdjust) => void
  busy: boolean
  onSaved: () => void
  /** Re-fit after a save (CPU, 0 hub jobs); absent where the dialog has no run of its own (the Figure tab's Build). */
  onRefit?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [saving, setSaving] = useState(false)
  const [savedNote, setSavedNote] = useState('')
  useEffect(() => { setSavedNote('') }, [itemId])
  const saved = view.settings
  const savedManual = view.manual ?? MANUAL_NONE
  const manualChanged = !sameManual(manual, savedManual)
  const limits = view.manual_limits ?? { offset_mm: 40, rotate_deg: 25, scale_pct: [-20, 25] }
  const change: Partial<Record<AllowanceName, AllowanceSetting>> = {}
  for (const name of ['width', 'length'] as AllowanceName[]) if (draft[name] !== saved[name]) change[name] = draft[name]
  const allowChanged = Object.keys(change).length > 0
  const changed = allowChanged || manualChanged
  const shoeMm = view.shoe_len_m != null ? view.shoe_len_m * 1000 : null
  const footMm = view.foot_len_m != null ? view.foot_len_m * 1000 : null
  const reference = [shoeMm != null ? `${t('shoe')} ${shoeMm.toFixed(0)} mm` : '',
    footMm != null ? `${t('foot')} ${footMm.toFixed(0)} mm` : ''].filter(Boolean).join(' · ')
  const setManualValue = (key: 'offset_mm' | 'rotate_deg', i: number, v: number) => {
    const next = { ...manual, [key]: manual[key].map((x, j) => (j === i ? v : x)) }
    onManual?.(next)
  }
  const settingText = (name: AllowanceName, s: AllowanceSetting) =>
    s === 'auto' ? t('Auto') : stepText(view, name, s)
  const autoTook = (name: AllowanceName): string => {
    const a = view.applied
    if (name === 'width') return t('Auto adds nothing — the fit already widens the shoe to the foot')
    if (!a) return t('Auto: decided at the next fit')
    return t('Auto took {step} on the shown shoe').replace('{step}', stepText(view, name, a.length_pct))
  }
  const save = async () => {
    if (!changed) return
    setSaving(true)
    try {
      const base = `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/footwear`
      let due = false
      if (allowChanged) due = (await apiPost<{ due: boolean }>(`${base}/allowance`, change)).due || due
      if (manualChanged) due = (await apiPost<{ due: boolean }>(`${base}/manual`, manual)).due || due
      const refit = due && !!onRefit
      const note = refit ? t('Re-fit started — local, 0 hub jobs')
        : due ? t('Fit due — Re-fit applies it, 0 hub jobs') : t('nothing becomes due')
      setSavedNote(note)
      toast(`${t('Saved')} · ${note}`, 'success')
      if (refit) onRefit?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
      onSaved()
    }
  }
  const row = (name: AllowanceName) => {
    const s = draft[name]
    const pct = resolved(view, name, s)
    const index = Math.max(0, view.steps.indexOf(pct))
    return (
      <div key={name} style={{ display: 'flex', flexDirection: 'column', gap: 2 }} title={`${t(HINTS[name])} ${t(NEGATIVE_HINT)}`}>
        <div style={ROW}>
          <span className="ga-hint" style={{ width: 48 }}>{t(LABELS[name])}</span>
          <button type="button" className={`ga-btn ga-btn-sm${s === 'auto' ? ' ga-btn-primary' : ''}`}
            aria-pressed={s === 'auto'} onClick={() => onDraft({ ...draft, [name]: 'auto' })}
            title={`${t(HINTS[name])} ${t(NEGATIVE_HINT)}`}>{t('Auto')}</button>
          <input type="range" min={0} max={view.steps.length - 1} step={1} value={index}
            style={{ flex: '1 1 0', minWidth: 60 }} aria-label={t(ARIA[name])}
            aria-valuetext={stepText(view, name, pct)} data-footwear-allowance={name}
            onChange={(e) => onDraft({ ...draft, [name]: view.steps[Number(e.target.value)] ?? 0 })} />
          <span style={{ minWidth: 112, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}
            data-footwear-allowance-value={name}>{stepText(view, name, pct)}</span>
        </div>
        <span className="ga-hint" style={{ paddingLeft: 54 }}>
          {s === 'auto' ? autoTook(name) : t(WHAT[name])}
        </span>
      </div>
    )
  }
  const manualRow = ({ key, i, label, hint }: typeof MANUAL_ROWS[number]) => {
    const bound = key === 'offset_mm' ? limits.offset_mm : limits.rotate_deg
    const v = manual[key][i]
    const unit = key === 'offset_mm' ? 'mm' : '°'
    return (
      <div key={`${key}${i}`} style={ROW} title={t(hint)}>
        <span className="ga-hint" style={{ width: 64 }}>{t(label)}</span>
        <input type="range" min={-bound} max={bound} step={key === 'offset_mm' ? 1 : 0.5} value={v}
          style={{ flex: '1 1 0', minWidth: 60 }} aria-label={t(label)} disabled={!onManual}
          data-footwear-manual={`${key}.${i}`}
          onChange={(e) => setManualValue(key, i, Number(e.target.value))} />
        <span style={{ minWidth: 64, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
          {`${v < 0 ? '−' : v > 0 ? '+' : ''}${Math.abs(v).toFixed(key === 'offset_mm' ? 0 : 1)} ${unit}`}
        </span>
      </div>
    )
  }
  const sizeRow = (
    <div style={ROW} title={t('Makes the whole shoe bigger (+) or smaller (−) about the heel end of its sole.')}>
      <span className="ga-hint" style={{ width: 64 }}>{t('Size')}</span>
      <input type="range" min={limits.scale_pct[0]} max={limits.scale_pct[1]} step={0.5} value={manual.scale_pct}
        style={{ flex: '1 1 0', minWidth: 60 }} aria-label={t('Size')} disabled={!onManual} data-footwear-manual="scale_pct"
        onChange={(e) => onManual?.({ ...manual, scale_pct: Number(e.target.value) })} />
      <span style={{ minWidth: 64, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
        {`${manual.scale_pct < 0 ? '−' : manual.scale_pct > 0 ? '+' : ''}${Math.abs(manual.scale_pct).toFixed(1)} %`}
        {shoeMm != null ? ` = ${(shoeMm * (1 + manual.scale_pct / 100)).toFixed(0)} mm` : ''}
      </span>
    </div>
  )
  const blockedStep = view.blocked ? t(FOOTWEAR_STEP_LABELS[view.blocked.step] || view.blocked.step) : ''
  return (
    <div role="group" aria-label={t('Adjust shoe')} style={BOX} data-footwear-allowance-box=""
      data-footwear-allowance-blocked={view.blocked?.step || undefined}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <strong>{t('Adjust shoe')}</strong>
        <span className="ga-hint" style={{ marginLeft: 'auto' }}>
          {t('Live in the viewer — the fit applies it on the body')}
        </span>
      </div>
      {view.blocked ? (
        <>
          <span style={WARN_STYLE}>
            {t('No fit yet: the shoe itself was refused at its “{step}” step. Accept that step anyway or regenerate it in the steps beside; what you save here applies to the first fit.')
              .replace('{step}', blockedStep)}
          </span>
          {view.blocked.error ? <span className="ga-hint">{view.blocked.error}</span> : null}
        </>
      ) : null}
      {row('width')}
      {row('length')}
      <span className="ga-hint" data-footwear-manual-reference="">
        {`${t('Position and turn, about the heel end of the sole')}${reference ? ` · ${t('Reference')}: ${reference}` : ''}`}
      </span>
      {MANUAL_ROWS.map(manualRow)}
      {sizeRow}
      {!sameManual(savedManual, MANUAL_NONE) || manualChanged ? (
        <div style={ROW}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={!onManual || sameManual(manual, MANUAL_NONE)}
            onClick={() => onManual?.(MANUAL_NONE)} title={t('Back to the fitted place and size — saved with Save')}>
            {t('Reset position and size')}
          </button>
        </div>
      ) : null}
      <div style={{ ...ROW, flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={!changed || saving || busy}
          onClick={() => { void save() }}
          title={onRefit ? t('Saves the settings for this piece and fits it again on the CPU (0 hub jobs)')
            : t('Saves the settings for this piece and runs nothing; the fit becomes due (0 hub jobs)')}>
          {changed ? `${t('Save')} · ${[...(Object.keys(change) as AllowanceName[])
            .map((n) => `${t(LABELS[n])} ${settingText(n, change[n] as AllowanceSetting)}`),
          ...(manualChanged ? [t('Position and size')] : [])].join(' · ')}` : t('Save')}
        </button>
        <span className="ga-hint">
          {`${t('Saved')}: ${t('Width')} ${settingText('width', saved.width)} · ${t('Length')} ${
            settingText('length', saved.length)}`}
        </span>
      </div>
      {view.due || savedNote ? (
        <span className="ga-hint" data-footwear-allowance-due="" style={ROW}>
          <StepLight light="yellow" />{savedNote || t('Fit due — Re-fit applies it, 0 hub jobs')}
        </span>
      ) : null}
    </div>
  )
}
