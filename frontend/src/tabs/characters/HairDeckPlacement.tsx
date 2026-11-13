/**
 * HairDeckPlacement — the HairDeck hair placement block of the SELECTED
 * hairstyle in the Hairstyles tab (plan
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 14; the
 * Wardrobe's hair row had it since Task 9). Self-contained: it saves its own
 * values, so later placement controls land here and nowhere else.
 *
 * Fields: forward shift (shown in mm), forward tilt (°) and hair width (a
 * factor on the sides' reach beyond the head). Empty = automatic (width: 1).
 * Apply stores them (POST /characters/{n}/hair/placement {forward_m,
 * tilt_deg, width_scale, item_id}, null = automatic) and runs NOTHING (the
 * user's rule R3: settings independent of execution) — the fit is then stale
 * and the tab's Run all / Re-fit re-fits the hair from the stored HairDeck
 * result (no hub job). The drafts are keyed by the server values, so they
 * restart from them after a save.
 *
 * Hair motion (plan docs/superpowers/plans/2026-11-12-hairdeck-spring-chains.md
 * Task 7): the spring chains of the newest fit, Swing and Stiffness. Both post
 * to POST /characters/{n}/hair/motion {swing, stiffness, item_id}, saved only:
 * a changed Swing makes the fit stale (Swing is a fit input, Ruling H11 — off =
 * today's hair), Stiffness changes only the motion payload.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ROW, WARN_STYLE } from './garmentStyle'
import type { HairChains, HairMethod, HairPlacement } from './useGarment'

/** A placement draft field as a number; '' = automatic (null), NaN = invalid. */
function draftNumber(text: string, scale: number): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const n = Number(trimmed.replace(',', '.'))
  return Number.isFinite(n) ? n / scale : NaN
}

const draftText = (v: number | null, scale: number) => (v === null ? '' : String(Math.round(v * scale * 100) / 100))

export function HairDeckPlacement({ character, itemId, method, placement, chains, swingPending, busy, running,
  onSaved }: {
  character: string
  /** The hairstyle the values are saved on. */
  itemId: string
  /** The hairstyle's mode: only HairDeck hair has spring chains. */
  method: HairMethod
  placement: HairPlacement
  /** The spring chains and the Swing/Stiffness settings; absent on an older server. */
  chains?: HairChains
  /** The served fit was made with the other Swing setting (stale reason `swing_changed`). */
  swingPending: boolean
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
      await apiPost(`/characters/${enc}/hair/placement`, { forward_m, tilt_deg, width_scale, item_id: itemId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onSaved()
    }
  }
  // Swing / Stiffness: saved only — a changed Swing makes the fit stale (Run all / Re-fit applies it).
  const applyMotion = async (swing: boolean, stiffness: number | null) => {
    if (posting) return
    setPosting(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/hair/motion`, { swing, stiffness, item_id: itemId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onSaved()
    }
  }
  return (
    <>
      <PlacementForm
        key={`${placement.forward_m ?? ''}|${placement.tilt_deg ?? ''}|${placement.width_scale ?? ''}`}
        placement={placement}
        busy={busy || posting}
        running={running}
        onApply={(f, a, w) => { void apply(f, a, w) }}
      />
      {chains && method === 'hairdeck' ? (
        <>
          <div className="ga-fieldset-title">{t('Hair motion')}</div>
          <HairSwingForm
            key={`${chains.swing}|${chains.stiffness}`}
            chains={chains}
            busy={busy || posting}
            refitting={running && swingPending}
            swingPending={swingPending && !running}
            onApply={(swing, stiffness) => { void applyMotion(swing, stiffness) }}
          />
        </>
      ) : null}
    </>
  )
}

/** Swing (a checkbox, applied at once), Stiffness (a slider with Apply / Reset) and the chain count or the
 *  notice for a hairstyle without spring chains. */
export function HairSwingForm({ chains, busy, refitting, swingPending, onApply }: {
  chains: HairChains
  busy: boolean
  /** The refit for a changed Swing runs. */
  refitting: boolean
  /** The served hair still has the other Swing setting and no run is active. */
  swingPending: boolean
  /** stiffness null = 1 (as generated). */
  onApply: (swing: boolean, stiffness: number | null) => void
}) {
  const { t } = useI18n()
  const [lo, hi] = chains.limits
  const [stiffness, setStiffness] = useState(chains.stiffness)
  const none = chains.fitted && chains.count === 0
  return (
    <>
      <div className="ga-hint">
        {!chains.fitted
          ? t('Spring chains appear after the next fit')
          : chains.count
            ? t('{n} spring chains').replace('{n}', String(chains.count))
            : t('No spring chains in this hairstyle — hair moves with the head')}
      </div>
      <div style={ROW}>
        <label
          style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
          title={t('Off = the hair moves with the head exactly as today.')}
        >
          <input
            type="checkbox"
            checked={chains.swing}
            disabled={busy || (none && !chains.swing)}
            onChange={(e) => onApply(e.target.checked, chains.stiffness)}
          />
          <span>{t('Swing')}</span>
        </label>
        {refitting ? (
          <span className="ga-hint" style={WARN_STYLE}>{t('Fitting the hair…')}</span>
        ) : swingPending ? (
          <span className="ga-hint" style={WARN_STYLE}>{t('The Swing setting takes effect after the next fit')}</span>
        ) : null}
      </div>
      <div className="ga-hint">
        {t('Swing on: the hair swings with motion but can touch the shoulders more than today — in the worst measured pose up to 2.3 % of the hair dips into the body, against at most 0.2 % today. Off by default. Saving runs nothing — Run all or Re-fit then fits the hair with the new Swing setting (no hub job).')}
      </div>
      <div style={ROW}>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Stiffness (×)')}
          <input
            type="range"
            min={lo}
            max={hi}
            step={0.1}
            style={{ width: 140 }}
            value={stiffness}
            disabled={busy || none}
            onChange={(e) => setStiffness(Number(e.target.value))}
          />
          <span style={{ minWidth: 36 }}>{stiffness.toFixed(1)}×</span>
        </label>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || none || Math.abs(stiffness - chains.stiffness) < 1e-9}
          onClick={() => onApply(chains.swing, stiffness)}
        >
          {t('Apply')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || chains.stiffness === 1}
          onClick={() => onApply(chains.swing, null)}
        >
          {t('Reset')}
        </button>
      </div>
      <div className="ga-hint">
        {t('Higher stiffness springs back faster. Stiffness changes only the motion — nothing is re-fitted; it acts while Swing is on.')}
      </div>
    </>
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
        {t('Saving runs nothing. Run all or Re-fit then fits the hair with the new placement from the stored HairDeck result (no hub job).')}
      </div>
    </>
  )
}
