/**
 * The ONE result block of Auto-align (Ruling A212 — the former Auto-align and pair-check results merged): the
 * contact and clearance lamps, per moving role whether the alignment range stopped it ("move it closer by hand"), the
 * five phases of the stroke before → after, and a collapsible detail table — before and after.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { hasInside, targetWordOf } from './contactWords'
import { LampDot } from './StatusLamp'
import type { AutoAlignResult, PhaseAlign } from './PlacePreview'

type Ok = Extract<AutoAlignResult, { ok: true }>
const CELL = { textAlign: 'right' as const, padding: '0 4px', whiteSpace: 'nowrap' as const }

/** Ruling A145: "Bend 28° of max 35°" with its lamp — yellow when the part was at its limit in some frame. */
export function BendLine({ bend }: { bend: { maxDeg: number; limitDeg: number; atLimit: number; frames: number; lamp: 'green' | 'yellow' } }) {
  const { t } = useI18n()
  return (
    <div data-testid="bend-readout" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <LampDot lamp={bend.lamp} title={bend.lamp === 'yellow'
        ? t('The attached part is at its bend limit in {n} of {m} frames: the rest of the way is the partner’s shift or turn.')
          .replace('{n}', String(bend.atLimit)).replace('{m}', String(bend.frames))
        : t('The attached part bends within its limit in every frame.')} />
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

/** The five phases of one contact: tip off the axis, depth along it, shaft angle — before → after. */
function PhaseTable({ phases, inside }: { phases: PhaseAlign[]; inside: boolean }) {
  const { t } = useI18n()
  const name = (p: number) => (p <= 0 ? t('Stroke start') : p >= 1 ? t('Stroke end') : p === 0.25 ? '¼' : p === 0.5 ? '½' : '¾')
  const pair = (a: number | undefined, b: number | undefined, unit: string) =>
    `${a === undefined ? '–' : (Math.round(a) || 0).toFixed(0)} → ${b === undefined ? '–' : (Math.round(b) || 0).toFixed(0)} ${unit}`
  return (
    <table data-testid="align-phases" style={{ borderCollapse: 'collapse' }}>
      <thead><tr><th style={{ textAlign: 'left' }}>{t('Phase')}</th>
        <th style={CELL} title={t('How far the tip is off the target’s axis.')}>{t('tip off axis')}</th>
        {inside ? <th style={CELL} title={t('How deep the tip is along the axis (+ = inside).')}>{t('depth')}</th> : null}
        <th style={CELL} title={t('The shaft against the axis.')}>{t('angle')}</th></tr></thead>
      <tbody>{phases.map((p) => (
        <tr key={p.phase}><td>{name(p.phase)}</td>
          <td style={CELL}>{pair(p.before?.tipMm, p.after?.tipMm, 'mm')}</td>
          {inside ? <td style={CELL}>{pair(p.before?.depthMm, p.after?.depthMm, 'mm')}</td> : null}
          <td style={CELL}>{pair(p.before?.axisDeg, p.after?.axisDeg, '°')}</td></tr>
      ))}</tbody>
    </table>
  )
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
          ? t('On the opening at the outermost frame and inside the channel at the deepest.')
          : r.lamp === 'yellow' ? t('Inside at the deepest frame, but off the axis or off the opening.')
            : t('Not inside the channel at the deepest frame.')} />
        <LampDot lamp={r.clearLamp} title={(r.clearLamp === 'green'
          ? t('Nothing else interpenetrates: only the attached part enters the other body, through the channel (at most 5 mm elsewhere).')
          : t('The bodies interpenetrate besides the channel by {mm} mm, deepest at {pair} (green at most 5 mm, yellow at most 20 mm).')
            .replace('{mm}', r.overlapAfterMm.toFixed(0)).replace('{pair}', r.clearWorst || '–'))} />
        <span>{t('{by} → {of}: {channel}').replace('{by}', r.by).replace('{of}', r.of)
          .replace('{channel}', r.target === 'channel' ? (r.channel.split(':').pop() || r.channel) : targetWordOf(t, r.target))}</span>
      </div>
      {r.movers.map((m) => {
        const v3 = (v: number[]) => v.map((x) => x.toFixed(1)).join(' / ')
        const limit = t('Auto-align moves {role} at most ±{r} cm forward/back and up/down, ±3 cm sideways and ±10° tilt/roll around the arrangement you set (the dials before the first click); what lies beyond is yours to set by hand.')
          .replace('{role}', m.role.toUpperCase()).replace('{r}', m.rangeCm.toFixed(0))
        return (
          <div key={m.role} data-testid="align-cap" data-lamp={m.lamp} title={limit}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <LampDot lamp={m.lamp} title={t('Within the alignment range')} />
              <span>{t('{role} moved by {a} cm (now {s} cm)').replace('{role}', m.role.toUpperCase()).replace('{a}', v3(m.adjustCm)).replace('{s}', v3(m.shiftCm))}
                {m.adjustDeg[0] || m.adjustDeg[1]
                  ? ` · ${t('tilt {a}° roll {b}°').replace('{a}', m.adjustDeg[0].toFixed(1)).replace('{b}', m.adjustDeg[1].toFixed(1))}` : ''}</span>
            </div>
            {m.capped && m.offCm > 0.5 ? (
              <div style={{ color: m.lamp === 'red' ? 'var(--danger, #f85149)' : 'var(--warning, #d29922)' }}>
                {t('The base arrangement is {x} cm off — move it closer by hand.').replace('{x}', m.offCm.toFixed(1))}</div>
            ) : null}
            {m.capped && m.offDeg > 1 ? (
              <div style={{ color: m.lamp === 'red' ? 'var(--danger, #f85149)' : 'var(--warning, #d29922)' }}>
                {t('The base arrangement is {x}° off in tilt/roll — turn it closer by hand.').replace('{x}', m.offDeg.toFixed(1))}</div>
            ) : null}
          </div>
        )
      })}
      {r.relations.map((x, i) => (
        <div key={i} style={{ marginTop: 2 }}>
          {r.relations.length > 1 ? <div style={{ opacity: 0.8 }}>{x.by} → {x.of} {targetWordOf(t, x.target)}</div> : null}
          <PhaseTable phases={x.phases} inside={hasInside(x.target)} />
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
        {t('Measured on the pair shown; another pair may need its own run. Save stores the sliders.')}
      </div>
    </div>
  )
}
