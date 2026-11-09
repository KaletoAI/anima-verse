/**
 * CollisionScales — the character's collision-capsule radius scale per body
 * region (leg / arm / torso / head, 0.5–1.5), saved to
 * `POST /characters/{c}/model3d/collision/scales`. The server stores the
 * override (`model3d_opts.collision_scales`) and recomputes the capsule set of
 * every stored model — on the base-body pipeline the base body's set first,
 * then the sets the outfit models inherit from it.
 *
 * While a slider moves, `onPreview` hands the caller a PREVIEW payload: the
 * shown set with each radius scaled by draft ÷ fitted scale, for the viewer's
 * capsule overlay. It is only that — the saved set is fitted by the server
 * (the head capsule's crown end also moves with its radius there).
 */
import { useEffect, useMemo, useState } from 'react'
import type { CollisionPayload } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

const COLLISION_REGIONS = ['leg', 'arm', 'torso', 'head'] as const
type CollisionScaleMap = Record<(typeof COLLISION_REGIONS)[number], number>

const REGION_LABELS: Record<(typeof COLLISION_REGIONS)[number], string> = {
  leg: 'Legs', arm: 'Arms', torso: 'Torso', head: 'Head',
}
const DEFAULTS: CollisionScaleMap = { leg: 1, arm: 1, torso: 1, head: 1 }

const full = (scales?: Partial<Record<string, number>> | null): CollisionScaleMap =>
  Object.fromEntries(COLLISION_REGIONS.map(region => [region, scales?.[region] ?? 1])) as CollisionScaleMap

const same = (a: CollisionScaleMap, b: CollisionScaleMap) => COLLISION_REGIONS.every(region => Math.abs(a[region] - b[region]) < 1e-6)

/** The shown set with each radius scaled from its fitted scale to `draft`. */
function previewCollision(payload: CollisionPayload, draft: CollisionScaleMap): CollisionPayload {
  const fitted = full(payload.scales)
  return {
    ...payload,
    capsules: payload.capsules.map(capsule => {
      const region = capsule.region as keyof CollisionScaleMap
      const from = fitted[region] || 1
      return region in draft ? { ...capsule, r: capsule.r * draft[region] / from } : capsule
    }),
  }
}

export function CollisionScales({ character, collision, scales, disabled, onPreview, onSaved }: {
  character: string
  /** The shown model's capsule set (`model.collision`). */
  collision: CollisionPayload | null | undefined
  /** The stored override (`options.collision_scales`). */
  scales?: Partial<Record<string, number>> | null
  disabled: boolean
  onPreview: (payload: CollisionPayload | null) => void
  onSaved: () => Promise<unknown> | void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const stored = useMemo(() => full(scales), [scales])
  const [draft, setDraft] = useState<CollisionScaleMap>(stored)
  const [saving, setSaving] = useState(false)
  // A reload that brings the same stored values keeps the draft; new values replace it.
  const storedKey = COLLISION_REGIONS.map(region => stored[region]).join(',')
  const [seenKey, setSeenKey] = useState(storedKey)
  if (seenKey !== storedKey) {
    setSeenKey(storedKey)
    setDraft(stored)
  }
  const changed = !same(draft, stored)

  useEffect(() => {
    onPreview(changed && collision?.capsules?.length ? previewCollision(collision, draft) : null)
  }, [changed, collision, draft, onPreview])
  useEffect(() => () => onPreview(null), [onPreview])

  const save = async (next: CollisionScaleMap) => {
    setSaving(true)
    try {
      const result = await apiPost<{ models: Record<string, { ok: boolean; error?: string }> }>(
        `/characters/${encodeURIComponent(character)}/model3d/collision/scales`,
        { scales: Object.fromEntries(Object.entries(next).filter(([, value]) => value !== 1)) })
      const failed = Object.entries(result.models || {}).filter(([, model]) => !model.ok)
      if (failed.length) {
        toast(t('Saved — capsules of {n} model(s) could not be recomputed').replace('{n}', String(failed.length)), 'error')
      } else {
        toast(t('Saved — collision capsules recomputed'))
      }
      await onSaved()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setSaving(false) }
  }

  const count = collision?.capsules?.length ?? 0
  const busy = disabled || saving
  return (
    <fieldset className="ga-fieldset">
      <legend>{t('Collision capsules')}</legend>
      {collision?.error ? (
        <p className="ga-hint" role="alert">{t('Fitting failed')}: {collision.error}</p>
      ) : collision ? (
        <p className="ga-hint">
          {t('{n} capsules').replace('{n}', String(count))}
          {collision.source === 'base' ? ` · ${t('from the base model')}` : ''}
          {collision.skipped?.length
            ? ` · ${t('skipped')}: ${collision.skipped.map(entry => `${entry.id} (${entry.reason})`).join(', ')}` : ''}
        </p>
      ) : (
        <p className="ga-hint">{t('Not computed yet — the capsules are fitted when the model is loaded.')}</p>
      )}
      <p className="ga-hint">
        {t("Radius per body region. Saving recomputes the capsules of every stored model of this character; outfit models on the base body inherit the base body's set. The viewer shows them with “Collision capsules”.")}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '4px 8px', alignItems: 'center' }}>
        {COLLISION_REGIONS.map(region => (
          <label key={region} style={{ display: 'contents' }}>
            <span>{t(REGION_LABELS[region])}</span>
            <input type="range" min={0.5} max={1.5} step={0.05} value={draft[region]} disabled={busy}
              onChange={event => {
                const value = Math.round(Number(event.target.value) * 100) / 100
                setDraft(previous => ({ ...previous, [region]: value }))
              }} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>×{draft[region].toFixed(2)}</span>
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 6 }}>
        {changed ? <span className="ga-hint">{t('Unsaved changes')}</span> : null}
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !changed}
          onClick={() => void save(draft)}>{t('Save')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !changed}
          onClick={() => setDraft(stored)}>{t('Revert')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || same(stored, DEFAULTS)}
          onClick={() => void save(DEFAULTS)}>{t('Reset')}</button>
      </div>
    </fieldset>
  )
}
