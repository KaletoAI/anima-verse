/**
 * The PARTNER PROBE's controls beside the model viewer (cross-person collision, plan Task 8): a stand-in partner
 * body made of capsules that the admin moves against the shown figure, to see how hair and extension chains react
 * without a second character in the world. A preview only — nothing is saved, nothing costs a job.
 *
 * - Source: "This body, mirrored" (the shown model's own capsules in its bind pose, x → −x) or "Another character"
 *   (that character's served model, `GET /characters/{c}/model3d/collision/bind-pose`, admin only).
 * - Where it stands: x / z in metres in the figure's frame (the figure faces +z and stands on y 0 at the origin), the
 *   yaw in degrees (0 = facing the same way as the figure; placed behind it, the probe then faces it). Every slider
 *   applies live.
 * - Sweep: back and forth along the probe's facing (`probeSweepOffset`), speed in m/s, span in metres.
 * - The readout: the partner capsules that pushed an extension or hair chain in the last moment (`probe:<id>`),
 *   from `SecondaryMotion.contactTips()`. The hair meshes' push runs on the GPU and reports nothing.
 */
import { useEffect, useState } from 'react'
import type { ProbeSourceCapsule } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiGet } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import type { CharacterRef } from '../../lib/refs'

export interface PartnerProbeSettings {
  source: 'self' | 'other'
  /** The other character (source `other`). */
  character: string
  /** Metres in the figure's frame. */
  x: number
  z: number
  /** Degrees about the vertical axis. */
  yaw: number
  sweep: boolean
  /** m/s */
  speed: number
  /** metres either way */
  span: number
}

function Slider({ label, value, shown, min, max, step, title, onChange }: {
  label: string; value: number; shown: string; min: number; max: number; step: number; title: string
  onChange: (value: number) => void
}) {
  return (
    <label className="ga-model3d-slider" title={title} style={{ gap: 0, fontSize: 10, minWidth: 0 }}>
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
        <span>{label}</span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{shown}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

const GRID2 = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px' } as const

export function PartnerProbeControls({ value, onChange, onOtherCapsules, contacts }: {
  value: PartnerProbeSettings
  onChange: (next: PartnerProbeSettings) => void
  /** The other character's bind-pose set once loaded; null while none is loaded (or it has none). */
  onOtherCapsules: (capsules: ProbeSourceCapsule[] | null) => void
  /** `probe:<capsule id>` of every partner capsule that pushed a chain in the last moment. */
  contacts: string[]
}) {
  const { t } = useI18n()
  const [characters, setCharacters] = useState<CharacterRef[] | null>(null)
  const [otherState, setOtherState] = useState<{ state: 'idle' | 'loading' | 'ready' | 'none' | 'error'; n?: number
    error?: string }>({ state: 'idle' })
  const set = (patch: Partial<PartnerProbeSettings>) => onChange({ ...value, ...patch })

  useEffect(() => {
    if (value.source !== 'other' || characters) return
    let live = true
    loadCharacters().then(list => { if (live) setCharacters(list) }).catch(() => { if (live) setCharacters([]) })
    return () => { live = false }
  }, [value.source, characters])

  useEffect(() => {
    if (value.source !== 'other' || !value.character) {
      onOtherCapsules(null)
      setOtherState({ state: 'idle' })
      return
    }
    let live = true
    setOtherState({ state: 'loading' })
    onOtherCapsules(null)
    apiGet<{ signature: string; capsules: ProbeSourceCapsule[] }>(
      `/characters/${encodeURIComponent(value.character)}/model3d/collision/bind-pose`)
      .then(data => {
        if (!live) return
        const capsules = data.capsules || []
        onOtherCapsules(capsules.length ? capsules : null)
        setOtherState(capsules.length ? { state: 'ready', n: capsules.length } : { state: 'none' })
      })
      .catch((e: Error) => {
        if (!live) return
        onOtherCapsules(null)
        setOtherState(e instanceof ApiError && e.status === 404 ? { state: 'none' } : { state: 'error', error: e.message })
      })
    return () => { live = false }
  }, [value.source, value.character, onOtherCapsules])

  const metres = (m: number) => `${m >= 0 ? '' : '−'}${Math.abs(m).toFixed(2)} m`
  return (
    <div className="ga-fieldset ga-model3d-group" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="ga-fieldset-title" style={{ margin: 0, fontSize: 11 }}>{t('Partner probe')}</span>
      <label className="ga-model3d-slider" style={{ gap: 0, fontSize: 10 }}
        title={t('The body the probe is made of: the shown body mirrored, or the collision capsules of another character’s model')}>
        <span>{t('Source')}</span>
        <select className="ga-input" value={value.source} style={{ fontSize: 11, padding: '1px 2px' }}
          onChange={(e) => set({ source: e.target.value === 'other' ? 'other' : 'self' })}>
          <option value="self">{t('This body, mirrored')}</option>
          <option value="other">{t('Another character')}</option>
        </select>
      </label>
      {value.source === 'other' ? (
        <label className="ga-model3d-slider" style={{ gap: 0, fontSize: 10 }}>
          <span>{t('Character')}</span>
          <select className="ga-input" value={value.character} style={{ fontSize: 11, padding: '1px 2px' }}
            onChange={(e) => set({ character: e.target.value })}>
            <option value="">{characters ? t('Pick a character') : t('Loading…')}</option>
            {(characters || []).map(c => <option key={c.name} value={c.name}>{c.display_name || c.name}</option>)}
          </select>
          <span className="ga-hint" style={{ fontSize: 10 }}>
            {otherState.state === 'loading' ? t('Loading…')
              : otherState.state === 'ready' ? t('{n} capsules of the served model').replace('{n}', String(otherState.n))
                : otherState.state === 'none' ? t('This character’s model has no collision capsules — the probe is hidden.')
                  : otherState.state === 'error' ? `${t('Error')}: ${otherState.error}`
                    : t('Pick a character — the probe stays hidden until then.')}
          </span>
        </label>
      ) : null}
      <div style={GRID2}>
        <Slider label="x" value={value.x} shown={metres(value.x)} min={-1} max={1} step={0.01}
          title={t('Sideways from the figure, in metres (the blue grid has 10 cm cells)')}
          onChange={(x) => set({ x })} />
        <Slider label="z" value={value.z} shown={metres(value.z)} min={-1} max={1} step={0.01}
          title={t('In front of (+) or behind (−) the figure, in metres (the blue grid has 10 cm cells)')}
          onChange={(z) => set({ z })} />
      </div>
      <span className="ga-hint" style={{ fontSize: 10 }}>{t('x / z read against the blue grid — 10 cm cells')}</span>
      <Slider label={t('Yaw')} value={value.yaw} shown={`${value.yaw}°`} min={-180} max={180} step={5}
        title={t('Which way the probe faces: 0° the same way as the figure, 180° the opposite way')}
        onChange={(yaw) => set({ yaw })} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <button type="button" className={`ga-btn ga-btn-sm${value.sweep ? ' ga-btn-primary' : ''}`}
          aria-pressed={value.sweep} onClick={() => set({ sweep: !value.sweep })}
          title={t('Moves the probe back and forth along the way it faces')}>
          {t('Sweep')}
        </button>
        <span className="ga-hint" style={{ fontSize: 10 }}>{value.sweep
          ? t('±{m} at {s} m/s').replace('{m}', metres(value.span)).replace('{s}', value.speed.toFixed(2))
          : t('Off — the probe stands still')}</span>
      </div>
      {value.sweep ? (
        <div style={GRID2}>
          <Slider label={t('Speed')} value={value.speed} shown={`${value.speed.toFixed(2)} m/s`} min={0.05} max={1}
            step={0.05} title={t('How fast the probe moves, in metres per second')} onChange={(speed) => set({ speed })} />
          <Slider label={t('Span')} value={value.span} shown={metres(value.span)} min={0.02} max={0.5} step={0.01}
            title={t('How far the probe moves either way, in metres')} onChange={(span) => set({ span })} />
        </div>
      ) : null}
      <span className="ga-hint" style={{ fontSize: 10 }}
        title={t('Partner capsules that pushed an extension or hair chain just now. The hair mesh is pushed on the graphics card and is not listed.')}>
        {contacts.length
          ? t('Pushing: {list}').replace('{list}', contacts.join(', '))
          : t('No chain touches the probe')}
      </span>
      <span className="ga-hint" style={{ fontSize: 10 }}>{t('Preview only — nothing is saved · no jobs')}</span>
    </div>
  )
}
