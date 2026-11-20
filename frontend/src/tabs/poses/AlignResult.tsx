/**
 * The ONE result block of Auto-align (Ruling A212, procedure of 2026-11-20): the key-frame and clearance lamps, per
 * moving role what it wrote (partner shift, tilt/roll, the clip's root angle) and which cap or slider range stopped it,
 * the deepest and the shallowest frame after the run, and a collapsible detail table — before and after.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { hasInside, targetWordOf } from './contactWords'
import { LampDot } from './StatusLamp'
import type { AlignBound } from '@anima/scene-render'
import type { AutoAlignResult, KeyAlign } from './PlacePreview'

type Ok = Extract<AutoAlignResult, { ok: true }>
const CELL = { textAlign: 'right' as const, padding: '0 4px', whiteSpace: 'nowrap' as const }

/** Ruling A145: "Bend 8° of max 15°" — what the bend does in all on the aligned samples (Auto-align itself is rigid),
 *  with its lamp: yellow when the limit cut the turn in some frame. */
export function BendLine({ bend }: { bend: { maxDeg: number; limitDeg: number; atLimit: number; frames: number; lamp: 'green' | 'yellow' } }) {
  const { t } = useI18n()
  return (
    <div data-testid="bend-readout" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <LampDot lamp={bend.lamp} title={bend.lamp === 'yellow'
        ? t('After Auto-align the attached part reaches its bend limit in {n} of {m} frames: the rest stays as the contact’s error.')
          .replace('{n}', String(bend.atLimit)).replace('{m}', String(bend.frames))
        : t('After Auto-align the attached part bends within its limit in every frame.')} />
      <span>{t('Bend {deg}° of max {max}°').replace('{deg}', bend.maxDeg.toFixed(0)).replace('{max}', bend.limitDeg.toFixed(0))}</span>
    </div>
  )
}

/** Ruling A150: "Support gap 4 mm" — how far the moving figure's support left the surface it rests on (+ float,
 *  − sink against its own clip posture); yellow when the posture held the solve back. */
export function PostureLine({ gapMm, sinkMm, limited, heightMm }: { gapMm: number; sinkMm: number; limited: boolean; heightMm?: number | null }) {
  const { t } = useI18n()
  return (
    <div data-testid="posture-readout" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <LampDot lamp={limited ? 'yellow' : 'green'} title={limited
        ? t('Posture limit: the partner would have to float or sink to reach the contact; it stays supported and the rest is left as the contact’s error.')
        : t('The partner stays supported: it neither floats nor sinks against its own pose.')} />
      <span>{t('Support gap {gap} mm, sunk {sink} mm').replace('{gap}', gapMm.toFixed(0)).replace('{sink}', sinkMm.toFixed(0))}</span>
      {heightMm !== undefined && heightMm !== null ? (
        <span style={{ opacity: 0.7 }} title={t('The lowest supporting capsule above the surface of its place (a shin capsule ends at the ankle).')}>
          · {t('{mm} mm above the surface').replace('{mm}', heightMm.toFixed(0))}</span>
      ) : null}
    </div>
  )
}

/** Ruling A212 (procedure of 2026-11-20): the two key frames of one contact after Auto-align — the tip's depth
 *  (+ = inside), whether the root is outside, the tip and the root off the axis, the rigid shaft against the axis and
 *  the bend the part still needs there (the state's limit; "limit" when it cuts). Before-values in the cell titles. */
function KeyTable({ keys, inside }: { keys: KeyAlign; inside: boolean }) {
  const { t } = useI18n()
  const a = keys.after, b = keys.before
  if (!a) return null
  const mm = (v: number | undefined) => (v === undefined ? '–' : `${(Math.round(v) || 0).toFixed(0)} mm`)
  const was = (v: number | undefined, unit: string) => (v === undefined ? '' : t('before: {v}').replace('{v}', `${v.toFixed(1)} ${unit}`))
  const rows = [['deep', t('deepest'), a.deep, b?.deep], ['shallow', t('shallowest'), a.shallow, b?.shallow]] as const
  return (
    <table data-testid="align-keys" style={{ borderCollapse: 'collapse' }}>
      <thead><tr><th style={{ textAlign: 'left' }}>{t('Frame')}</th>
        {inside ? <th style={CELL} title={t('How deep the tip is along the axis (+ = inside).')}>{t('depth')}</th> : null}
        {inside ? <th style={CELL} title={t('Whether the root joint of the part lies in front of the opening.')}>{t('root outside')}</th> : null}
        <th style={CELL} title={t('How far the tip is off the target’s axis.')}>{t('tip off axis')}</th>
        <th style={CELL} title={t('How far the root joint of the part is off the target’s axis line.')}>{t('root off axis')}</th>
        <th style={CELL} title={t('The rigid shaft (root joint to tip) against the axis.')}>{t('shaft')}</th>
        <th style={CELL} title={t('What the render-time bend still turns the part by at this frame, within the state’s limit.')}>{t('bend needed')}</th></tr></thead>
      <tbody>{rows.map(([key, label, r, rb]) => (
        <tr key={key} data-key={key}><td>{label}</td>
          {inside ? <td style={CELL} title={was(rb?.depthMm, 'mm')}>{mm(r.depthMm)}</td> : null}
          {inside ? <td style={{ ...CELL, color: key === 'deep' && !r.rootOutside ? 'var(--danger, #f85149)' : undefined }}>
            {r.rootOutside ? t('yes') : t('no')}</td> : null}
          <td style={CELL} title={was(rb?.tipOffMm, 'mm')}>{mm(r.tipOffMm)}</td>
          <td style={CELL} title={was(rb?.rootOffMm, 'mm')}>{mm(r.rootOffMm)}</td>
          <td style={CELL} title={was(rb?.shaftDeg, '°')}>{r.shaftDeg.toFixed(1)}°</td>
          <td style={CELL}>{r.bendDeg === null ? '–' : `${r.bendDeg.toFixed(1)}°${r.bendAtLimit ? ` (${t('limit')})` : ''}`}</td></tr>
      ))}</tbody>
    </table>
  )
}

/** The names of the unknowns that hit their cap or slider range. */
function boundWord(t: (s: string) => string, b: AlignBound, rangeCm: number): string {
  switch (b) {
    case 'side': return t('side (±3 cm)')
    case 'up': return t('up/down (±{r} cm)').replace('{r}', rangeCm.toFixed(0))
    case 'forward': return t('forward/back (±{r} cm)').replace('{r}', rangeCm.toFixed(0))
    case 'tilt': return t('tilt (±10°)')
    case 'roll': return t('roll (±10°)')
    case 'pitch': return t('root pitch (±60°)')
    case 'yaw': return t('root yaw (±30°)')
  }
}

export function AlignResultBlock({ result }: { result: AutoAlignResult }) {
  const { t } = useI18n()
  if (!result.ok) {
    return <div data-testid="align-auto-result" data-result={JSON.stringify(result)} style={{ fontSize: 11 }}>
      <span style={{ color: 'var(--danger, #f85149)' }}>{result.reason}</span></div>
  }
  const r: Ok = result
  const inside = hasInside(r.target)
  return (
    <div data-testid="align-auto-result" data-result={JSON.stringify(r)} style={{ fontSize: 11, lineHeight: 1.35 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <LampDot lamp={r.lamp} title={r.lamp === 'green'
          ? t('At the deepest and the shallowest frame the root joint and the tip lie within 3 mm of the axis; at the deepest the root is outside and the tip inside.')
          : r.lamp === 'yellow' ? t('At both key frames within 10 mm of the axis, the root outside and the tip inside at the deepest.')
            : t('More than 10 mm off the axis, the root or the tip on the wrong side of the opening, or a cap or slider range was hit.')} />
        <LampDot lamp={r.clearLamp} title={(r.clearLamp === 'green'
          ? t('Nothing else interpenetrates: only the attached part enters the other body, through the channel (at most 5 mm elsewhere).')
          : t('The bodies interpenetrate besides the channel by {mm} mm, deepest at {pair} (green at most 5 mm, yellow at most 20 mm).')
            .replace('{mm}', r.overlapAfterMm.toFixed(0)).replace('{pair}', r.clearWorst || '–'))} />
        <span>{t('{by} → {of}: {channel}').replace('{by}', r.by).replace('{of}', r.of)
          .replace('{channel}', r.target === 'channel' ? (r.channel.split(':').pop() || r.channel) : targetWordOf(t, r.target))}</span>
      </div>
      {r.movers.map((m) => {
        const v3 = (v: number[]) => v.map((x) => x.toFixed(1)).join(' / ')
        const limit = t('Auto-align moves {role} at most ±{r} cm forward/back and up/down, ±3 cm sideways and ±10° tilt/roll around the arrangement you set (the dials before the first click), and sets the root angle within its sliders; what lies beyond is yours to set by hand.')
          .replace('{role}', m.role.toUpperCase()).replace('{r}', m.rangeCm.toFixed(0))
        return (
          <div key={m.role} data-testid="align-cap" data-lamp={m.lamp} title={limit}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <LampDot lamp={m.lamp} title={t('Within the alignment range')} />
              <span>{t('{role} moved by {a} cm (now {s} cm)').replace('{role}', m.role.toUpperCase()).replace('{a}', v3(m.adjustCm)).replace('{s}', v3(m.shiftCm))}
                {m.adjustDeg[0] || m.adjustDeg[1]
                  ? ` · ${t('tilt {a}° roll {b}°').replace('{a}', m.adjustDeg[0].toFixed(1)).replace('{b}', m.adjustDeg[1].toFixed(1))}` : ''}</span>
            </div>
            {m.rootAngle ? (
              <div data-testid="align-root">{t('Root angle pitch {p}° yaw {y}° (was {p0}° / {y0}°) — written to the root-angle dials.')
                .replace('{p}', m.rootAngle.pitchDeg.toFixed(1)).replace('{y}', m.rootAngle.yawDeg.toFixed(1))
                .replace('{p0}', (m.rootBefore?.pitchDeg ?? 0).toFixed(1)).replace('{y0}', (m.rootBefore?.yawDeg ?? 0).toFixed(1))}</div>
            ) : null}
            {m.hits.length ? (
              <div style={{ color: 'var(--danger, #f85149)' }}>
                {t('Stopped by: {names} — move it closer by hand.').replace('{names}', m.hits.map((b) => boundWord(t, b, m.rangeCm)).join(', '))}</div>
            ) : null}
            <div style={{ opacity: 0.7 }}>{(m.converged ? t('Converged after {n} passes.') : t('Not converged after {n} passes.'))
              .replace('{n}', String(m.passes.length))}</div>
          </div>
        )
      })}
      {r.relations.map((x, i) => (
        <div key={i} style={{ marginTop: 2 }}>
          {r.relations.length > 1 ? <div style={{ opacity: 0.8 }}>{x.by} → {x.of} {targetWordOf(t, x.target)}</div> : null}
          <KeyTable keys={x.keys} inside={hasInside(x.target)} />
        </div>
      ))}
      <details data-testid="align-details">
        <summary>{t('Details')}</summary>
        <table style={{ borderCollapse: 'collapse' }}>
          <thead><tr><th /><th style={CELL}>{t('before')}</th><th style={CELL}>{t('after')}</th></tr></thead>
          <tbody>
            {([
              [inside ? t('Tip to opening at the outermost frame') : t('Tip to target at the outermost frame'), r.before.entryMm, r.after.entryMm, 'mm'],
              ...(inside ? [[t('Depth at the deepest frame'), r.before.depthMm, r.after.depthMm, 'mm'] as const] : []),
              [t('Off the axis, worst frame'), r.before.maxLateralMm, r.after.maxLateralMm, 'mm'],
              [t('Shaft against the axis at the outermost frame'), r.before.axisDeg, r.after.axisDeg, '°'],
              [t('Interpenetration besides the channel'), r.overlapBeforeMm, r.overlapAfterMm, 'mm'],
            ] as const).map(([label, a, b, unit]) => (
              <tr key={label}><td>{label}</td>
                <td style={CELL}>{a.toFixed(0)} {unit}</td>
                <td style={CELL}>{b.toFixed(0)} {unit}</td></tr>
            ))}
          </tbody>
        </table>
        {r.bend ? <BendLine bend={r.bend} /> : null}
        {r.posture ? <PostureLine gapMm={r.posture.gapMm} sinkMm={r.posture.sinkMm}
          limited={r.posture.limited} heightMm={r.posture.heightMm} /> : null}
        {r.limitReason === 'posture' ? (
          <div data-testid="align-limit-reason" style={{ color: 'var(--warning, #d29922)' }}>
            {t('Contact lamp {lamp}: posture limit — the partner stays supported instead of floating.')
              .replace('{lamp}', r.lamp === 'red' ? t('red') : t('yellow'))}</div>
        ) : null}
        {r.clearWorst ? (
          <div className="ga-form-hint" style={{ margin: 0 }}>
            {t('Deepest besides the channel: {pair}').replace('{pair}', r.clearWorst)}</div>
        ) : null}
        {r.relations.length > 1 ? (
          <table data-testid="align-auto-relations" style={{ borderCollapse: 'collapse' }}>
            <thead><tr><th style={{ textAlign: 'left' }}>{t('Contact')}</th><th /><th>{t('to target')}</th><th>{t('depth')}</th>
              <th>{t('off axis')}</th><th>{t('shift')}</th></tr></thead>
            <tbody>{r.relations.map((x, i) => (
              <tr key={i}><td>{x.by} → {x.of} {targetWordOf(t, x.target)}</td>
                <td><LampDot lamp={x.lamp} title={t('Contact')} /></td>
                <td style={CELL}>{x.before.entryMm.toFixed(0)} → {x.after.entryMm.toFixed(0)} mm</td>
                <td style={CELL}>{hasInside(x.target) ? `${x.after.depthMm.toFixed(0)} mm` : '–'}</td>
                <td style={CELL}>{x.before.maxLateralMm.toFixed(0)} → {x.after.maxLateralMm.toFixed(0)} mm</td>
                <td style={CELL}>{x.part.toUpperCase()} {x.shiftCm.map((v) => v.toFixed(1)).join(' / ')} cm</td></tr>
            ))}</tbody>
          </table>
        ) : null}
      </details>
      <div className="ga-form-hint" style={{ margin: 0 }}>
        {t('Measured on the pair shown; another pair may need its own run. Save stores the partner dials; the root angle is saved with “Save root angle”.')}
      </div>
    </div>
  )
}
