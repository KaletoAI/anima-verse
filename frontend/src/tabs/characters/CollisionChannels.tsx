/**
 * CollisionChannels — the character's per-channel settings of the declared channels (cross-person collision, plan
 * Task 15; spec Part 6 "Where channel values are tuned"): per channel an offset in mm along the body frame (Side /
 * Up / Front, −50…50), a radius scale and a depth scale (0.5–2) and the funnel half-angle (Cone, °), stored as
 * `model3d_opts.collision_channels[<channel id>]`. The package manifest holds the defaults.
 *
 * - SAVE STORES ONLY (ruling R4, the user's rule "Save never executes"): `POST …/model3d/collision/channels`
 *   (`saveChannelOverrides`) — never the recompute. The collision step of the shown model then reads "Due" with
 *   its reason ("Channel settings changed — recompute to apply"); its light and words are written beside Save
 *   (`step`), with a link to the step's own button "Recompute collision capsules" (`onShowStep`; local, no hub
 *   job). Run all and the Figure tab's Build apply it too.
 * - LIVE: while a slider moves, `onPreview` hands the caller the shown payload with each changed channel replaced by
 *   its `previewChannel` draft (the same contract as CollisionScales); the viewer draws it on the figure.
 * - The declarations are listed one line each: placed at the reported opening / the declared offset, or the plain
 *   reason the shown model has none (covered, no opening, no base model yet). Details on mouse-over.
 * - More than one channel: one sub-tab per channel instead of a long column; the six fields sit in a 3-column grid.
 */
import { useEffect, useMemo, useState } from 'react'
import type { ChannelOverride, CollisionPayload } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { ModelStep } from './ModelSteps'
import { StepLight, SubTabs } from './StepRows'
import { LIGHT_COLOR } from './stepStyle'
import { CONE_MAX, CONE_MIN, OFFSET_MM_MAX, SCALE_MAX, SCALE_MIN, channelLabel, collisionStepLine, declarationDetail,
  declarationLine, overrideOf, overridesToSave, previewPayload, saveChannelOverrides, sameOverride } from './collisionChannelsModel'
import type { ChannelDeclaration, ChannelOverrides } from './collisionChannelsModel'

function Field({ label, shown, value, min, max, step, title, disabled, onChange }: {
  label: string; shown: string; value: number; min: number; max: number; step: number; title: string
  disabled: boolean; onChange: (value: number) => void
}) {
  return (
    <label className="ga-model3d-slider" title={title} style={{ gap: 0, fontSize: 10, minWidth: 0 }}>
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
        <span>{label}</span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{shown}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

const GRID3 = { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '2px 8px' } as const

export function CollisionChannels({ character, collision, overrides, declarations, disabled, onPreview, onSaved, step,
  onShowStep }: {
  character: string
  /** The shown model's capsule set with its channels (`model.collision`). */
  collision: CollisionPayload | null | undefined
  /** The stored overrides (`collision_channels`). */
  overrides?: ChannelOverrides | null
  /** `channel_declarations`: every declared channel with its placement on the shown model or the reason. */
  declarations: ChannelDeclaration[]
  disabled: boolean
  onPreview: (payload: CollisionPayload | null) => void
  onSaved: () => Promise<unknown> | void
  /** The shown model's collision step (`model.steps`), written beside Save. */
  step?: ModelStep | null
  /** Brings the step's own button ("Recompute collision capsules") into view. */
  onShowStep?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  // A poll brings new objects with the same values: the key, not the identity, decides whether the draft is replaced.
  const storedKey = `${JSON.stringify(overrides || {})}|${declarations.map(d => `${d.id}:${d.cone_deg}`).join(',')}`
  const stored = useMemo(() => Object.fromEntries(declarations.map(d => [d.id, overrideOf(overrides, d.id, d.cone_deg)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [storedKey])
  const [drafts, setDrafts] = useState<Record<string, ChannelOverride>>(stored)
  const [seenKey, setSeenKey] = useState(storedKey)
  if (seenKey !== storedKey) {
    // A reload with other stored values (or other declarations) replaces the draft.
    setSeenKey(storedKey)
    setDrafts(stored)
  }
  const [saving, setSaving] = useState(false)
  const [tab, setTab] = useState('')
  const current = declarations.find(d => d.id === tab) ?? declarations[0]
  const changed = declarations.some(d => drafts[d.id] && !sameOverride(drafts[d.id], stored[d.id]))

  useEffect(() => { onPreview(changed ? previewPayload(collision, drafts) : null) }, [changed, collision, drafts, onPreview])
  useEffect(() => () => onPreview(null), [onPreview])

  const save = async (next: Record<string, ChannelOverride>) => {
    setSaving(true)
    try {
      await saveChannelOverrides(apiPost, character, overridesToSave(overrides, declarations, next))
      toast(t('Saved — nothing recomputed yet'))
      await onSaved()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setSaving(false) }
  }

  const busy = disabled || saving
  const line = collisionStepLine(step)
  const draft = current ? drafts[current.id] ?? stored[current.id] : null
  const set = (patch: Partial<ChannelOverride>) => {
    if (!current || !draft) return
    setDrafts(previous => ({ ...previous, [current.id]: { ...draft, ...patch } }))
  }
  const setOffset = (axis: 0 | 1 | 2, value: number) => {
    if (!draft) return
    const offset = [...draft.offset_mm] as [number, number, number]
    offset[axis] = value
    set({ offset_mm: offset })
  }
  const mm = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(0)} mm`
  const placed = (collision?.channels ?? []).length
  const defaults = Object.fromEntries(declarations.map(d => [d.id, overrideOf(null, d.id, d.cone_deg)]))
  const atDefaults = declarations.every(d => sameOverride(stored[d.id], defaults[d.id]))

  return (
    <fieldset className="ga-fieldset ga-model3d-group"
      title={t('Per channel: where its opening sits and how wide, deep and open it is. Saving stores the values only — “Recompute collision capsules” applies them.')}>
      <legend>{t('Channels')}</legend>
      {!declarations.length ? (
        <div className="ga-hint">{t('No package declares a channel for this character.')}</div>
      ) : (
        <>
          <div className="ga-hint" style={{ fontSize: 10, margin: 0 }}>
            {t('{n} of {m} channels on this model').replace('{n}', String(placed)).replace('{m}', String(declarations.length))}
          </div>
          {declarations.map(d => {
            const row = declarationLine(d)
            return (
              <div key={d.id} title={declarationDetail(d)}
                style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, minWidth: 0 }}>
                <StepLight light={row.light} />
                <span style={{ fontWeight: 600 }}>{channelLabel(d.id)}</span>
                <span className="ga-hint" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t(row.text)}
                </span>
              </div>
            )
          })}
          {declarations.length > 1 ? (
            <SubTabs tabs={declarations.map(d => ({ id: d.id, label: channelLabel(d.id), title: d.id }))}
              value={current?.id ?? ''} onChange={setTab} />
          ) : null}
          {current && draft ? (
            <div style={GRID3} aria-label={t('Channel settings')}>
              <Field label={t('Side')} shown={mm(draft.offset_mm[0])} value={draft.offset_mm[0]} min={-OFFSET_MM_MAX}
                max={OFFSET_MM_MAX} step={1} disabled={busy} onChange={(v) => setOffset(0, v)}
                title={t('Moves the opening towards the figure’s left (+) or right (−), in millimetres — the wire on the figure moves with it')} />
              <Field label={t('Up')} shown={mm(draft.offset_mm[1])} value={draft.offset_mm[1]} min={-OFFSET_MM_MAX}
                max={OFFSET_MM_MAX} step={1} disabled={busy} onChange={(v) => setOffset(1, v)}
                title={t('Moves the opening up (+) or down (−) along the body, in millimetres')} />
              <Field label={t('Front')} shown={mm(draft.offset_mm[2])} value={draft.offset_mm[2]} min={-OFFSET_MM_MAX}
                max={OFFSET_MM_MAX} step={1} disabled={busy} onChange={(v) => setOffset(2, v)}
                title={t('Moves the opening forward (+) or back (−), in millimetres')} />
              <Field label={t('Radius')} shown={`×${draft.radius_scale.toFixed(2)}`} value={draft.radius_scale}
                min={SCALE_MIN} max={SCALE_MAX} step={0.05} disabled={busy} onChange={(v) => set({ radius_scale: v })}
                title={t('How wide the channel is, as a factor of the declared radius {r} cm').replace('{r}',
                  (current.radius * 100).toFixed(1))} />
              <Field label={t('Depth')} shown={`×${draft.depth_scale.toFixed(2)}`} value={draft.depth_scale}
                min={SCALE_MIN} max={SCALE_MAX} step={0.05} disabled={busy} onChange={(v) => set({ depth_scale: v })}
                title={t('How deep the channel is, as a factor of the declared depth {d} cm').replace('{d}',
                  (current.depth * 100).toFixed(1))} />
              <Field label={t('Cone')} shown={`${draft.cone_deg.toFixed(0)}°`} value={draft.cone_deg} min={CONE_MIN}
                max={CONE_MAX} step={1} disabled={busy} onChange={(v) => set({ cone_deg: v })}
                title={t('The half-angle of the entry funnel in front of the opening, in degrees')} />
            </div>
          ) : null}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 2 }}>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !changed}
              title={t('Stores the values only — nothing is recomputed, no jobs')}
              onClick={() => void save(drafts)}>{t('Save')}</button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !changed}
              title={t('Back to the saved values')} onClick={() => setDrafts(stored)}>{t('Discard changes')}</button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || atDefaults}
              title={t('Stores the declared values for every channel')}
              onClick={() => void save(defaults)}>{t('Reset to default')}</button>
          </div>
          <div className="ga-hint" style={{ fontSize: 10 }}>{t('Saving stores only — no jobs. What becomes due shows here.')}</div>
        </>
      )}
      {line ? (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 11 }} role="status">
          <StepLight light={line.light} />
          <span style={{ minWidth: 0 }}>
            <span style={{ color: LIGHT_COLOR[line.light] }}>{t('Collision capsules')} · {t(line.state)}</span>
            {line.state === 'Due' ? (
              <span className="ga-hint" style={{ display: 'block' }}>
                {t('Channel settings changed — recompute to apply')}
              </span>
            ) : null}
            {line.state === 'Due' && onShowStep ? (
              <button type="button" className="ga-btn ga-btn-sm" style={{ marginTop: 2 }} onClick={onShowStep}
                title={t('Shows the step’s own button — local, no hub job')}>
                {t('Go to “Recompute collision capsules”')}
              </button>
            ) : null}
          </span>
        </div>
      ) : null}
    </fieldset>
  )
}
