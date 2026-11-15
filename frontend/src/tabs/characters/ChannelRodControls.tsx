/**
 * The TEST ROD's controls beside the model viewer (cross-person collision, plan Task 15; spec Part 6): a straight
 * stand-in chain the viewer pushes into one of the shown model's channels, so the radial guidance, the depth rule and
 * the skipped capsules show without a second figure (`guideRod` of @anima/scene-render, the rule the client runs).
 * A preview only — nothing is saved, nothing costs a job.
 *
 * - Channel: which channel the rod enters (one of the model's, `collision.channels`).
 * - Length / Radius (m), Links (count), Insertion (m: how far the rod's tip lies past the opening along the axis,
 *   negative = still in front of it), Tilt (° off the axis). Every slider applies live.
 * - The readout (`RodReadout`, read by the viewer each moment): the turn per link (°), the depth scale k, how far
 *   the tip's surface lies past the bottom (cm), the receiving body's capsules it skips and the weight w.
 * The rod's length is written on the rod in the viewer; the channel grid there has 1 cm cells.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { ROD_BUDGET_DEG, channelLabel, rodReadoutLines } from './collisionChannelsModel'
import type { RodReadout, RodSettings } from './collisionChannelsModel'

function Slider({ label, value, shown, min, max, step, title, onChange }: {
  label: string; value: number; shown: string; min: number; max: number; step: number; title: string
  onChange: (value: number) => void
}) {
  return (
    <label className="ga-model3d-slider" title={title} style={{ gap: 0, fontSize: 10, minWidth: 0 }}>
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
        <span>{label}</span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{shown}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

const GRID3 = { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '2px 8px' } as const

export function ChannelRodControls({ value, channels, onChange, readout }: {
  value: RodSettings
  /** The ids of the shown model's channels. */
  channels: string[]
  onChange: (next: RodSettings) => void
  readout: RodReadout | null
}) {
  const { t } = useI18n()
  const set = (patch: Partial<RodSettings>) => onChange({ ...value, ...patch })
  // Shown in cm like the rest of the UI (A102c); the settings stay in metres.
  const metres = (m: number) => `${m < 0 ? '−' : ''}${(Math.abs(m) * 100).toFixed(1)} cm`
  const lines = rodReadoutLines(readout, t)
  return (
    <div className="ga-fieldset ga-model3d-group" style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="ga-fieldset-title" style={{ margin: 0, fontSize: 11 }}>{t('Test rod')}</span>
      <label className="ga-model3d-slider" style={{ gap: 0, fontSize: 10 }} title={t('The channel the rod enters')}>
        <span>{t('Channel')}</span>
        <select className="ga-input" value={value.channel || channels[0] || ''} style={{ fontSize: 11, padding: '1px 2px' }}
          onChange={(e) => set({ channel: e.target.value })}>
          {channels.map(id => <option key={id} value={id}>{channelLabel(id)}</option>)}
        </select>
      </label>
      <div style={GRID3}>
        <Slider label={t('Length')} value={value.length} shown={metres(value.length)} min={0.03} max={0.4} step={0.005}
          title={t('The rod’s length in cm — written on the rod in the viewer')} onChange={(length) => set({ length })} />
        <Slider label={t('Radius')} value={value.radius} shown={metres(value.radius)} min={0.002} max={0.05} step={0.001}
          title={t('The radius of each link’s capsule, in cm')} onChange={(radius) => set({ radius })} />
        <Slider label={t('Links')} value={value.links} shown={String(value.links)} min={1} max={6} step={1}
          title={t('How many equal links the rod has')} onChange={(links) => set({ links })} />
        <Slider label={t('Insertion')} value={value.insertion} shown={metres(value.insertion)} min={-0.1} max={0.3}
          step={0.005} title={t('How far the rod’s tip lies past the opening along the rod, in cm (negative = in front of it); the rod always passes through the opening centre, the tilt pivots there')}
          onChange={(insertion) => set({ insertion })} />
        <Slider label={t('Tilt')} value={value.tiltDeg} shown={`${value.tiltDeg}°`} min={-45} max={45} step={1}
          title={t('How far the rod points off the channel axis, in degrees')} onChange={(tiltDeg) => set({ tiltDeg })} />
      </div>
      {lines.map((line, i) => <span key={i} className="ga-hint" style={{ fontSize: 10 }}>{line}</span>)}
      <span className="ga-hint" style={{ fontSize: 10 }}>
        {t('Guided with a swing budget of {n}° per link · preview only — nothing is saved · no jobs')
          .replace('{n}', String(ROD_BUDGET_DEG))}
      </span>
    </div>
  )
}
