/**
 * MeshRepairPanel — the base mesh repair of the Base body tab (Ruling A34). The base body is one closed skin; the
 * repair fills every hole of the stored base mesh on the CPU (a hole the rigger left where it dropped faces), with
 * a fair patch whose UVs and skin weights come from the rim. It runs on its own in every base rebuild and in the
 * Build; this panel shows its result and redoes it:
 *
 * - a status light with the reason (`meshRepairLine`: "3 holes filled, largest 0.2 cm", "Closed — no hole",
 *   "1 hole left open (6.2 cm)" — the why in its tooltip —, "Switched off");
 * - "Repair again" (POST …/base-body/mesh-repair): local, no hub job — the repair with the saved settings, then
 *   the extension bones on the repaired mesh; the outfits fitted on the base refit after it;
 * - the settings (on/off, the largest hole to fill), saved on their own (POST …/model3d/options `mesh_repair`)
 *   without running anything; a saved change shows "not applied yet" until Repair again or Run all applies it.
 *
 * Compact on purpose: it sits in the column beside the base model's preview, under the collision sliders.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime } from '../../lib/clockFormat'
import { MAX_HOLE_RANGE, meshRepairBody, meshRepairDot, meshRepairInvalid, meshRepairLine } from './baseBodyModel'
import type { MeshRepairSettings, MeshRepairState } from './baseBodyModel'

const sameSettings = (a: MeshRepairSettings, b: MeshRepairSettings) =>
  a.enabled === b.enabled && Math.abs(a.max_hole_cm - b.max_hole_cm) < 1e-9

export function MeshRepairPanel({ character, state, disabled, onSaved, onStarted }: {
  character: string
  state: MeshRepairState
  disabled: boolean
  onSaved: () => Promise<unknown> | void
  onStarted: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const stored = state.settings
  const [draft, setDraft] = useState<MeshRepairSettings>(stored)
  const [busy, setBusy] = useState(false)
  // A reload that brings other stored values replaces the draft.
  const storedKey = `${stored.enabled}:${stored.max_hole_cm}`
  const [seenKey, setSeenKey] = useState(storedKey)
  if (seenKey !== storedKey) {
    setSeenKey(storedKey)
    setDraft(stored)
  }
  const changed = !sameSettings(draft, stored)
  const invalid = meshRepairInvalid(draft)
  const locked = disabled || busy || state.running

  const save = async () => {
    setBusy(true)
    try {
      await apiPost(`/characters/${enc}/model3d/options`, { mesh_repair: meshRepairBody(draft) })
      toast(t('Saved — Repair again applies it'))
      await onSaved()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }

  const repair = async () => {
    setBusy(true)
    try {
      await apiPost(`/characters/${enc}/base-body/mesh-repair`, {})
      toast(t('Mesh repair started'), 'success')
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }

  const record = state.record
  const detail = [
    record?.holes !== undefined ? t('{n} open loop(s) found').replace('{n}', String(record.holes)) : '',
    ...(record?.unfilled ?? []).map((u) => `${u.size_cm !== null ? `${u.size_cm.toFixed(1)} cm` : '?'}: ${u.reason}`),
    record?.at ? `${t('Repaired')} ${formatDateTime(record.at, clockSettings())}` : '',
  ].filter(Boolean).join('\n')
  const help = t('The base body is one closed surface. The repair fills every hole of the base mesh on the CPU with a smooth patch whose texture and skin weights come from the hole’s rim. It runs in every base rebuild and in the Build.')
  return (
    <fieldset className="ga-fieldset ga-model3d-group" title={help}>
      <legend>{t('Mesh repair')}</legend>
      <div className="ga-model3d-status-row" title={detail || undefined}
        role={state.light === 'error' ? 'alert' : undefined}>
        <span className={`ga-model3d-status-dot ga-model3d-status-${meshRepairDot(state.light)}`} />
        <span className="ga-model3d-status-text">{state.running ? t('Repairing…') : meshRepairLine(state, t)}</span>
      </div>
      {state.last?.error ? <div className="ga-hint" role="alert">{state.last.error}</div> : null}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={draft.enabled} disabled={locked}
            onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))} />
          <span>{t('Fill holes')}</span>
        </label>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}
          title={t('A larger hole is a missing body part — it stays open and the status says so.')}>
          <span>{t('Largest hole')}</span>
          <input type="number" min={MAX_HOLE_RANGE[0]} max={MAX_HOLE_RANGE[1]} step={0.5} style={{ width: 56 }}
            value={draft.max_hole_cm} disabled={locked || !draft.enabled}
            onChange={(e) => setDraft((d) => ({ ...d, max_hole_cm: Number(e.target.value) }))} />
          <span>cm</span>
        </label>
      </div>
      {invalid ? <div className="ga-hint" role="alert">{t(invalid)}</div> : null}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={locked || !changed || !!invalid}
          title={t('Saves the settings without running anything')}
          onClick={() => void save()}>{t('Save')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={locked || !changed}
          onClick={() => setDraft(stored)}>{t('Revert')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={locked || changed}
          title={changed ? t('Save or revert the settings first') : t('Repairs the base mesh again with the saved settings, then rebuilds its extension bones — on this computer, no hub job. Fitted outfit pieces refit afterwards.')}
          onClick={() => void repair()}>{t('Repair again (local, no hub job)')}</button>
      </div>
      {state.due && !changed ? <div className="ga-hint">{t('Settings saved, not applied yet — Repair again or Run all applies them (local, no hub job).')}</div> : null}
    </fieldset>
  )
}
