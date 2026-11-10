/**
 * CollisionScales — the character's collision-capsule radius scale per body
 * region (leg / arm / torso / head, and the extension regions chest /
 * attached part, 0.5–1.5), saved to
 * `POST /characters/{c}/model3d/collision/scales`. The server stores the
 * override (`model3d_opts.collision_scales`) and recomputes the capsule set of
 * every stored model — on the base-body pipeline the base body's set first,
 * then the sets the outfit models inherit from it.
 *
 * Rendered compact next to the viewer — in the Base body tab on the
 * pipeline (the column right of the checklist), in the 3D tab's side
 * toolbar off it — so the capsules move with the slider.
 * While a slider moves, `onPreview` hands the caller a PREVIEW payload: the
 * shown set with each radius scaled by draft ÷ fitted scale, for the viewer's
 * capsule overlay. It is only that — the saved set is fitted by the server
 * (the head capsule's crown end also moves with its radius there).
 *
 * The extension regions (capsules on the spring-driven extension bones,
 * `app/core/collision.py` `EXTENSION_CAPSULES`) get a slider only where the
 * shown set has such capsules or a stored scale differs from 1 — a body
 * without the group has nothing to scale there.
 */
import { useEffect, useMemo, useState } from 'react'
import type { CollisionPayload } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

const COLLISION_REGIONS = ['leg', 'arm', 'torso', 'head', 'chest', 'attached_part'] as const
type CollisionScaleMap = Record<(typeof COLLISION_REGIONS)[number], number>
/** Regions shown only where the set has capsules in them (module docstring). */
const EXTENSION_REGIONS: ReadonlySet<string> = new Set(['chest', 'attached_part'])

const REGION_LABELS: Record<(typeof COLLISION_REGIONS)[number], string> = {
  leg: 'Legs', arm: 'Arms', torso: 'Torso', head: 'Head', chest: 'Chest', attached_part: 'Attached part',
}
const DEFAULTS: CollisionScaleMap = { leg: 1, arm: 1, torso: 1, head: 1, chest: 1, attached_part: 1 }

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
  const present = new Set((collision?.capsules ?? []).map(capsule => capsule.region))
  const shown = COLLISION_REGIONS.filter(region => !EXTENSION_REGIONS.has(region) || present.has(region)
    || stored[region] !== 1 || draft[region] !== 1)
  const busy = disabled || saving
  const help = t("Radius per body region. Saving recomputes the capsules of every stored model of this character; outfit models on the base body inherit the base body's set. The viewer shows them with “Collision capsules”.")
  const stateText = collision?.error ? `${t('Fitting failed')}: ${collision.error}`
    : collision ? [
      t('{n} capsules').replace('{n}', String(count)),
      collision.source === 'base' ? t('from the base model') : '',
      collision.skipped?.length ? `${t('skipped')}: ${collision.skipped.map(entry => `${entry.id} (${entry.reason})`).join(', ')}` : '',
    ].filter(Boolean).join(' · ')
    : t('Not computed yet — the capsules are fitted when the model is loaded.')
  // Compact on purpose: it sits in the viewer's side toolbar, so the
  // capsules (shown while a draft differs) move with the slider.
  return (
    <fieldset className="ga-fieldset ga-model3d-group" title={help}>
      <legend>{t('Collision capsules')}</legend>
      <div className="ga-hint" role={collision?.error ? 'alert' : undefined} title={stateText}
        style={{ fontSize: 10, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {stateText}
      </div>
      <div className="ga-collision-grid">
        {shown.map(region => (
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
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !changed}
          title={changed ? t('Unsaved changes') : undefined}
          onClick={() => void save(draft)}>{t('Save')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !changed}
          onClick={() => setDraft(stored)}>{t('Revert')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || same(stored, DEFAULTS)}
          onClick={() => void save(DEFAULTS)}>{t('Reset')}</button>
      </div>
    </fieldset>
  )
}
