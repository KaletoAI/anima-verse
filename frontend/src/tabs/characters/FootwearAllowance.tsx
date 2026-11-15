/**
 * FootwearAllowance — Ruling A82: the footwear piece's Width and Length allowance beside the shod preview, each on its
 * own: Auto or +0 … +20 % (`footwear_fit.ALLOWANCE_STEPS`), the millimetres beside the step (Length = that share of
 * the foot's length, all of it heel room; Width = that share of the shoe's ball width). Dragging previews the shoe
 * live in the viewer (`footwearAllowance.ts`, the fit's rule); Save stores the settings only (POST
 * …/garments/{item}/footwear/allowance) — the fit becomes due and Re-fit / Run all / the Figure tab's Build applies it
 * on the CPU, 0 hub jobs. Auto: Width +0 (the fit widens the shoe to the foot already), Length +0 or, when the fit
 * at +0 is refused because the foot pokes out, the smallest step the checks accept — what Auto took on the shown fit
 * is named. Server: `garment_footwear.allowance_view`.
 */
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { StepLight } from './StepRows'
import { resolved, stepText } from './footwearAllowance'
import type { AllowanceName, AllowanceSetting, FootwearAllowanceView } from './footwearAllowance'

const BOX: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', borderRadius: 6,
  border: '1px solid var(--border, #30363d)' }
const ROW: CSSProperties = { display: 'flex', alignItems: 'center', gap: 6 }

const HINTS: Record<AllowanceName, string> = {
  width: 'Makes the shoe wider across the foot by this share of its width at the ball. Auto adds nothing: the fit already widens a shoe to the foot.',
  length: 'Makes the shoe one size longer: all of it is room behind the heel, the toes keep their place. Auto takes the smallest step the checks accept when the foot pokes out of the shoe.',
}
const LABELS: Record<AllowanceName, string> = { width: 'Width', length: 'Length' }
const WHAT: Record<AllowanceName, string> = { width: 'across the ball', length: 'heel room' }
const ARIA: Record<AllowanceName, string> = { width: 'Width allowance', length: 'Length allowance' }

export function FootwearAllowance({ character, itemId, view, draft, onDraft, busy, onSaved }: {
  character: string
  itemId: string
  view: FootwearAllowanceView
  /** The settings previewed (lifted: the viewer beside deforms by them). */
  draft: { width: AllowanceSetting; length: AllowanceSetting }
  onDraft: (d: { width: AllowanceSetting; length: AllowanceSetting }) => void
  busy: boolean
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [saving, setSaving] = useState(false)
  const [savedNote, setSavedNote] = useState('')
  useEffect(() => { setSavedNote('') }, [itemId])
  const saved = view.settings
  const change: Partial<Record<AllowanceName, AllowanceSetting>> = {}
  for (const name of ['width', 'length'] as AllowanceName[]) if (draft[name] !== saved[name]) change[name] = draft[name]
  const changed = Object.keys(change).length > 0
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
      const d = await apiPost<{ due: boolean }>(
        `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/footwear/allowance`, change)
      const note = d.due ? t('Fit due — Re-fit applies it, 0 hub jobs') : t('nothing becomes due')
      setSavedNote(note)
      toast(`${t('Saved')} · ${note}`, 'success')
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
      <div key={name} style={{ display: 'flex', flexDirection: 'column', gap: 2 }} title={t(HINTS[name])}>
        <div style={ROW}>
          <span className="ga-hint" style={{ width: 48 }}>{t(LABELS[name])}</span>
          <button type="button" className={`ga-btn ga-btn-sm${s === 'auto' ? ' ga-btn-primary' : ''}`}
            aria-pressed={s === 'auto'} onClick={() => onDraft({ ...draft, [name]: 'auto' })}
            title={t(HINTS[name])}>{t('Auto')}</button>
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
  return (
    <div role="group" aria-label={t('Shoe allowance')} style={BOX} data-footwear-allowance-box="">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <strong>{t('Shoe allowance')}</strong>
        <span className="ga-hint" style={{ marginLeft: 'auto' }}>
          {t('Live in the viewer — the fit applies it on the body')}
        </span>
      </div>
      {row('width')}
      {row('length')}
      <div style={{ ...ROW, flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={!changed || saving || busy}
          onClick={() => { void save() }}
          title={t('Saves the allowance for this piece and runs nothing; the fit becomes due (0 hub jobs)')}>
          {changed ? `${t('Save')} · ${(Object.keys(change) as AllowanceName[])
            .map((n) => `${t(LABELS[n])} ${settingText(n, change[n] as AllowanceSetting)}`).join(' · ')}` : t('Save')}
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
