/**
 * HairDeckPlacement — the HairDeck hair placement block (moved out of the
 * Hair tab into the Wardrobe's hair row, plan
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 9; ruling 5).
 * Self-contained: it saves its own values and asks for the re-fit, so later
 * placement controls land here and nowhere else.
 *
 * Fields: forward shift (shown in mm), forward tilt (°) and hair width (a
 * factor on the sides' reach beyond the head). Empty = automatic (width: 1).
 * Apply stores them (POST /characters/{n}/hair/placement {forward_m,
 * tilt_deg, width_scale}, null = automatic), then re-fits the hair from the
 * stored HairDeck result (POST /characters/{n}/garments/{item}/run {} — only
 * the fit runs, HairDeck does not run again). The drafts are keyed by the
 * server values, so they restart from them after a save.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ROW, WARN_STYLE } from './garmentStyle'
import type { HairMethod, HairPlacement } from './useGarment'

/** A placement draft field as a number; '' = automatic (null), NaN = invalid. */
function draftNumber(text: string, scale: number): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const n = Number(trimmed.replace(',', '.'))
  return Number.isFinite(n) ? n / scale : NaN
}

const draftText = (v: number | null, scale: number) => (v === null ? '' : String(Math.round(v * scale * 100) / 100))

export function HairDeckPlacement({ character, itemId, method, placement, busy, running, onSaved }: {
  character: string
  /** The hair item (the re-fit runs its chain); '' = none yet — only saved. */
  itemId: string
  /** The hair method in effect: only HairDeck hair is re-fitted. */
  method: HairMethod
  placement: HairPlacement
  /** Another hair action is in flight. */
  busy: boolean
  /** A hair run is active: the placement waits for it. */
  running: boolean
  /** After a save (or a failed one): the caller reloads its hair info. */
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [posting, setPosting] = useState(false)
  const apply = async (forward_m: number | null, tilt_deg: number | null, width_scale: number | null) => {
    if (posting) return
    setPosting(true)
    const enc = encodeURIComponent(character)
    try {
      await apiPost(`/characters/${enc}/hair/placement`, { forward_m, tilt_deg, width_scale })
      if (itemId && method === 'hairdeck') {
        await apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onSaved()
    }
  }
  return (
    <PlacementForm
      key={`${placement.forward_m ?? ''}|${placement.tilt_deg ?? ''}|${placement.width_scale ?? ''}`}
      placement={placement}
      busy={busy || posting}
      running={running}
      onApply={(f, a, w) => { void apply(f, a, w) }}
    />
  )
}

function PlacementForm({ placement, busy, running, onApply }: {
  placement: HairPlacement
  busy: boolean
  running: boolean
  onApply: (forward_m: number | null, tilt_deg: number | null, width_scale: number | null) => void
}) {
  const { t } = useI18n()
  const [forward, setForward] = useState(draftText(placement.forward_m, 1000))
  const [tilt, setTilt] = useState(draftText(placement.tilt_deg, 1))
  const [width, setWidth] = useState(draftText(placement.width_scale, 1))
  const f = draftNumber(forward, 1000)
  const a = draftNumber(tilt, 1)
  const w = draftNumber(width, 1)
  const [wLo, wHi] = placement.limits.width_scale
  const valid = (v: number | null, limit: number) => v === null || (!Number.isNaN(v) && Math.abs(v) <= limit)
  const ok = valid(f, placement.limits.forward_m) && valid(a, placement.limits.tilt_deg)
    && (w === null || (!Number.isNaN(w) && w >= wLo && w <= wHi))
  const same = f === placement.forward_m && a === placement.tilt_deg && w === placement.width_scale
  const manual = placement.forward_m !== null || placement.tilt_deg !== null || placement.width_scale !== null
  const fitted = placement.fitted
  const src = (s: string | null | undefined) => (s === 'manual' ? t('Manual') : t('Automatic'))
  return (
    <>
      <div style={ROW}>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Forward shift (mm)')}
          <input
            className="ga-input"
            type="number"
            step="1"
            style={{ width: 90 }}
            value={forward}
            placeholder={t('Auto')}
            disabled={busy}
            onChange={(e) => setForward(e.target.value)}
          />
        </label>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Forward tilt (°)')}
          <input
            className="ga-input"
            type="number"
            step="0.5"
            style={{ width: 90 }}
            value={tilt}
            placeholder={t('Auto')}
            disabled={busy}
            onChange={(e) => setTilt(e.target.value)}
          />
        </label>
        <label
          className="ga-hint"
          style={{ display: 'flex', gap: 6, alignItems: 'center' }}
          title={t('Scales how far the hair reaches out beyond the sides of the head; 1 = as generated.')}
        >
          {t('Hair width (×)')}
          <input
            className="ga-input"
            type="number"
            step="0.05"
            min={wLo}
            max={wHi}
            style={{ width: 90 }}
            value={width}
            placeholder="1"
            disabled={busy}
            onChange={(e) => setWidth(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !ok || same}
          title={!ok ? t('Value out of range') : undefined}
          onClick={() => onApply(f, a, w)}
        >
          {t('Apply')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !manual}
          onClick={() => onApply(null, null, null)}
        >
          {t('Reset to automatic')}
        </button>
        {running ? <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span> : null}
      </div>
      {!ok ? <div className="ga-hint" style={WARN_STYLE}>{t('Value out of range')}</div> : null}
      {fitted && fitted.forward_m !== null && fitted.tilt_deg !== null ? (
        <div className="ga-hint">
          {t('Last fit')}: {t('Forward shift')} {(fitted.forward_m * 1000).toFixed(1)} mm ({src(fitted.forward_source)})
          {' · '}{t('Forward tilt')} {fitted.tilt_deg.toFixed(1)}° ({src(fitted.tilt_source)})
          {typeof fitted.width_scale === 'number' ? ` · ${t('Hair width')} ${fitted.width_scale.toFixed(2)}×` : ''}
          {fitted.hairline_y !== null
            ? ` · ${t('Hairline')} ${fitted.hairline_y.toFixed(3)} m`
              + (fitted.hairline_target_y !== null ? ` (${t('target')} ${fitted.hairline_target_y.toFixed(3)} m)` : '')
            : ''}
        </div>
      ) : null}
      <div className="ga-hint">
        {t('Empty = automatic: a small forward shift and the tilt that brings the front hairline down to the brow line.')}
        {' '}
        {t('Hair width below 1 brings the sides closer to the head; the hairline stays.')}
        {' '}
        {t('A placement change re-fits the hair from the stored HairDeck result — HairDeck does not run again.')}
      </div>
    </>
  )
}
