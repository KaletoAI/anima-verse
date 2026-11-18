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
 * - The mouth's "Open" slider (Ruling A203): a live preview of the body's `mouth_open` in the viewer, with the
 *   opening's height in millimetres; stored nowhere.
 * - A BUILT channel (the mouth, Ruling A203; `built`): its geometry is part of the body, so a saved offset, radius,
 *   depth or tilt makes the extension step due (the Build applies it, local); a note under the fields says so.
 * - The mouth's TEETH (Ruling A206): Teeth and Tongue on/off, the tooth colour (three shades) and the size, saved by
 *   the same Save (`saveTeeth`, `model3d_opts.mouth_teeth`) — stored only; the extension step becomes due and the
 *   Build applies it (local, 0 jobs). With teeth the readout beside Open names the free height between them.
 */
import { useEffect, useMemo, useState } from 'react'
import type { ChannelOverride, CollisionPayload } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { ModelStep } from './ModelSteps'
import { StepLight, SubTabs } from './StepRows'
import { LIGHT_COLOR } from './stepStyle'
import { CONE_MAX, TILT_MAX, CONE_MIN, OFFSET_MM_MAX, SCALE_MAX, SCALE_MIN, TEETH_DEFAULTS, TEETH_SHADES, TEETH_SIZE_MAX,
  TEETH_SIZE_MIN, channelLabel, collisionStepLine, declarationDetail, declarationLine, overrideOf, overridesToSave,
  previewPayload, saveChannelOverrides, sameOverride, sameTeeth, saveTeeth, teethOf } from './collisionChannelsModel'
import type { ChannelDeclaration, ChannelOverrides, TeethOptions } from './collisionChannelsModel'

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

function Check({ label, checked, title, disabled, onChange }: {
  label: string; checked: boolean; title: string; disabled: boolean; onChange: (value: boolean) => void
}) {
  return (
    <label title={title} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, minWidth: 0 }}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

export function CollisionChannels({ character, collision, overrides, declarations, disabled, onPreview, onSaved, step,
  onShowStep, mouthOpen = 0, onMouthOpen, teeth }: {
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
  /** Ruling A203: the viewer's mouth preview (0..1) and its setter; the "Open" slider shows for a built channel
   *  whose record carries `open_height`. A preview only — nothing is stored. */
  mouthOpen?: number
  onMouthOpen?: (value: number) => void
  /** Ruling A206: the stored teeth options (`mouth_teeth`); edited on the built mouth's tab. */
  teeth?: Partial<TeethOptions> | null
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  // A poll brings new objects with the same values: the key, not the identity, decides whether the draft is replaced.
  const teethKey = JSON.stringify(teeth || {})
  const storedKey = `${JSON.stringify(overrides || {})}|${declarations.map(d => `${d.id}:${d.cone_deg}`).join(',')}|${teethKey}`
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const storedTeeth = useMemo(() => teethOf(teeth), [teethKey])
  const [teethDraft, setTeethDraft] = useState<TeethOptions>(storedTeeth)
  const stored = useMemo(() => Object.fromEntries(declarations.map(d => [d.id, overrideOf(overrides, d.id, d.cone_deg)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [storedKey])
  const [drafts, setDrafts] = useState<Record<string, ChannelOverride>>(stored)
  const [seenKey, setSeenKey] = useState(storedKey)
  if (seenKey !== storedKey) {
    // A reload with other stored values (or other declarations) replaces the draft.
    setSeenKey(storedKey)
    setDrafts(stored)
    setTeethDraft(storedTeeth)
  }
  const [saving, setSaving] = useState(false)
  const [tab, setTab] = useState('')
  const current = declarations.find(d => d.id === tab) ?? declarations[0]
  const channelsChanged = declarations.some(d => drafts[d.id] && !sameOverride(drafts[d.id], stored[d.id]))
  const changed = channelsChanged || !sameTeeth(teethDraft, storedTeeth)

  useEffect(() => { onPreview(channelsChanged ? previewPayload(collision, drafts) : null) }, [channelsChanged, collision, drafts, onPreview])
  useEffect(() => () => onPreview(null), [onPreview])

  const save = async (next: Record<string, ChannelOverride>, nextTeeth: TeethOptions) => {
    setSaving(true)
    // Two stores: one that fails must not hide the other that went through — reload after either.
    let saved = false
    let failure: Error | null = null
    const attempt = async (run: () => Promise<unknown>) => {
      try { await run(); saved = true } catch (e) { failure = failure ?? (e as Error) }
    }
    try {
      if (declarations.some(d => next[d.id] && !sameOverride(next[d.id], stored[d.id])))
        await attempt(() => saveChannelOverrides(apiPost, character, overridesToSave(overrides, declarations, next)))
      if (!sameTeeth(nextTeeth, storedTeeth)) await attempt(() => saveTeeth(apiPost, character, nextTeeth))
      if (failure) toast(t('Error') + ': ' + (failure as Error).message, 'error')
      else toast(t('Saved — nothing recomputed yet'))
      if (saved) await onSaved()
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
  const record = (collision?.channels ?? []).find(c => c.id === current?.id)
  const openHeight = record?.open_height ?? 0
  const teethGap = record?.teeth_gap ?? 0
  // How the last Build's teeth step went (Ruling A206): a failure or left-out back teeth are said where the gap stands.
  const teethNote = record?.teeth?.status === 'failed'
    ? t('No teeth built: {reason}').replace('{reason}', record.teeth.reason)
    : (record?.teeth?.left_out ?? 0) > 0
      ? t('{n} back teeth left out: the mouth is too short for them').replace('{n}', String(record?.teeth?.left_out))
      : ''
  const setTeeth = (patch: Partial<TeethOptions>) => setTeethDraft(previous => ({ ...previous, ...patch }))
  const placed = (collision?.channels ?? []).length
  const defaults = Object.fromEntries(declarations.map(d => [d.id, overrideOf(null, d.id, d.cone_deg)]))
  const atDefaults = declarations.every(d => sameOverride(stored[d.id], defaults[d.id])) && sameTeeth(storedTeeth, TEETH_DEFAULTS)

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
              <Field label={t('Tilt')} shown={`${(draft.tilt_deg ?? 0).toFixed(0)}°`} value={draft.tilt_deg ?? 0}
                min={-TILT_MAX} max={TILT_MAX} step={1} disabled={busy} onChange={(v) => set({ tilt_deg: v })}
                title={t('Turns the channel’s direction toward the back (+) or the front (−), in degrees')} />
            </div>
          ) : null}
          {current?.built && onMouthOpen && openHeight > 0 ? (
            <div style={GRID3} aria-label={t('Mouth preview')}>
              <Field label={t('Open')} shown={`${Math.round(mouthOpen * 100)} % · ${(mouthOpen * openHeight * 1000).toFixed(0)} mm`}
                value={mouthOpen} min={0} max={1} step={0.01} disabled={false} onChange={onMouthOpen}
                title={t('Opens the mouth in the viewer: 0 = closed, 100 % = the jaw fully open ({mm} mm between the lips). A preview only — nothing is saved; in the world a part entering the mouth opens it.')
                  .replace('{mm}', (openHeight * 1000).toFixed(0))} />
              {teethNote ? (
                <div className="ga-hint" style={{ fontSize: 10, margin: 0, gridColumn: 'span 2', alignSelf: 'end',
                  color: record?.teeth?.status === 'failed' ? 'var(--ga-warn, #e0a040)' : undefined }}
                  title={t('From the last Build. A smaller size or a larger depth gives the teeth more room.')}>
                  {teethNote}
                </div>
              ) : teethGap > 0 ? (
                <div className="ga-hint" style={{ fontSize: 10, margin: 0, gridColumn: 'span 2', alignSelf: 'end' }}
                  title={t('The free height between the upper and lower front teeth with the mouth fully open: a part up to this thickness passes without touching them. Contact opens the mouth by it.')}>
                  {t('Between the teeth: {mm} mm at 100 %').replace('{mm}', (teethGap * 1000).toFixed(0))}
                </div>
              ) : null}
            </div>
          ) : null}
          {current?.built && current.id === 'mouth' ? (
            <div style={GRID3}>
              <Check label={t('Teeth')} checked={teethDraft.enabled} disabled={busy} onChange={(v) => setTeeth({ enabled: v })}
                title={t('Builds teeth and gums into the open mouth (upper row on the head, lower row on the jaw). Off: the open mouth shows only its dark inside.')} />
              <Check label={t('Tongue')} checked={teethDraft.tongue} disabled={busy || !teethDraft.enabled}
                onChange={(v) => setTeeth({ tongue: v })}
                title={t('A simple tongue on the floor of the mouth; an entering part pushes it down.')} />
              <label className="ga-model3d-slider" style={{ gap: 0, fontSize: 10, minWidth: 0 }}
                title={t('The colour of the teeth')}>
                <span>{t('Colour')}</span>
                <select value={teethDraft.shade} disabled={busy || !teethDraft.enabled}
                  onChange={(e) => setTeeth({ shade: Number(e.target.value) as TeethOptions['shade'] })}>
                  {TEETH_SHADES.map((name, i) => <option key={name} value={i}>{t(name)}</option>)}
                </select>
              </label>
              <Field label={t('Size')} shown={`×${teethDraft.size.toFixed(2)}`} value={teethDraft.size}
                min={TEETH_SIZE_MIN} max={TEETH_SIZE_MAX} step={0.05} disabled={busy || !teethDraft.enabled}
                onChange={(v) => setTeeth({ size: Math.round(v * 100) / 100 })}
                title={t('The teeth’s size as a factor of the size measured from the mouth’s width')} />
            </div>
          ) : null}
          {current?.built ? (
            <div className="ga-hint" style={{ fontSize: 10, margin: 0 }} role="note">
              {t('This channel is built into the body: the wire shows the new values at once, the opening and the teeth follow with the next Build (extension step, local, 0 jobs).')}
            </div>
          ) : null}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 2 }}>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !changed}
              title={t('Stores the values only — nothing is recomputed, no jobs')}
              onClick={() => void save(drafts, teethDraft)}>{t('Save')}</button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !changed}
              title={t('Back to the saved values')} onClick={() => { setDrafts(stored); setTeethDraft(storedTeeth) }}>{t('Discard changes')}</button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || atDefaults}
              title={t('Stores the declared values for every channel')}
              onClick={() => void save(defaults, TEETH_DEFAULTS)}>{t('Reset to default')}</button>
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
