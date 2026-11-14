/**
 * TipSmoothingPanel — the tip smoothing of the Base body tab (Ruling A43), the row between the mesh repair and the
 * tip panels in the column beside the base model's preview. Before a tip part builds its stub, the extension rebuild
 * levels the source bump onto the surface around it (Ruling A53) and gives the moved skin the surface's own normals
 * (Ruling A34);
 * it runs inside "Extension bones (local)", so this row only makes it visible:
 *
 * - a status light with the reason (`tipSmoothingLine`: "Applied 01:12 — max shift 4.5 mm, inverted normals 22 → 0",
 *   "Not applied to this model yet — rebuilds the extension bones (local, no hub job)", why nothing was smoothed);
 *   the numbers per part in its tooltip;
 * - "Built <time>" of the record;
 * - "Smooth again (local, no hub job)" — the extension rebuild of the base model (POST
 *   …/model3d/extension-tip/apply, the tip panels' Rebuild), also when it is current (rule R2).
 *
 * A tip part switched off whose declaration leaves a neutral surface (Ruling A44, `when_off: neutralise`) shares the
 * row: "Smoothed — part is off" (Ruling A53: the mesh only, the texture stays), its tip height and source bump before →
 * after in the tooltip.
 *
 * It has no settings of its own: the region is the tip part's (from its marker radius and stub size), so nothing
 * is saved here. Hidden when the base model carries neither a switched-on tip part nor a neutralised one
 * (`plain_body.tip_smoothing` null).
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useClockSettings } from '../../lib/clockFormat'
import { stampLabel } from './freshnessText'
import { TIP_SMOOTH_AGAIN_LABEL, tipSmoothingDetail, tipSmoothingDot, tipSmoothingLine } from './baseBodyModel'
import type { TipSmoothingState } from './baseBodyModel'

export function TipSmoothingPanel({ character, signature, state, disabled, onStarted }: {
  character: string
  /** The base model (its signature): the extension rebuild acts on it. */
  signature: string
  state: TipSmoothingState
  disabled: boolean
  onStarted: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  useClockSettings()   // re-render when the clock settings change
  // "01:12", or "12 Nov 01:12" when that is not today (the 3D previews' "Built" caption).
  const time = (iso: string) => stampLabel(iso) || iso

  const smooth = async () => {
    setBusy(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/model3d/extension-tip/apply`, { signature })
      toast(t('Tip smoothing started'), 'success')
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }

  const detail = tipSmoothingDetail(state, t).join('\n')
  const help = t('Before a tip part is built, the bump the mesher modelled there is levelled onto the surface around it and the moved skin gets the surface’s own normals, so no bump, fold or dark spot stays under it. A tip part that is switched off is levelled the same way; only the mesh changes, the texture stays as it is. It runs inside the extension bones rebuild — on this computer, no hub job. No settings of its own: the region comes from the tip part.')
  return (
    // minWidth 0: a fieldset is min-content wide by default; the reason wraps instead of widening the side column.
    <fieldset className="ga-fieldset ga-model3d-group" title={help} style={{ minWidth: 0 }}>
      <legend>{t('Tip smoothing (local)')}</legend>
      <div className="ga-model3d-status-row" title={detail || undefined}
        role={state.light === 'error' ? 'alert' : undefined}>
        <span className={`ga-model3d-status-dot ga-model3d-status-${tipSmoothingDot(state.light)}`} />
        <span className="ga-model3d-status-text" style={{ whiteSpace: 'normal' }}>
          {state.running ? t('Rebuilding the extension bones…') : tipSmoothingLine(state, t, time)}
        </span>
      </div>
      {state.record?.at ? (
        <div className="ga-hint">{t('Built')} {time(state.record.at)}</div>
      ) : null}
      {state.last?.error ? <div className="ga-hint" role="alert">{state.last.error}</div> : null}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={disabled || busy || state.running}
          title={t('Rebuilds the extension bones of the base model, which smooths the tips again — on this computer, no hub job. Fitted outfit pieces refit afterwards when the base changes.')}
          onClick={() => void smooth()}>{t(TIP_SMOOTH_AGAIN_LABEL)}</button>
      </div>
    </fieldset>
  )
}
