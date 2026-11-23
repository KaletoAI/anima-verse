/**
 * The ONE result block of Auto-align (Ruling A212, procedure of 2026-11-20): the key-frame and clearance lamps, per
 * moving role what it wrote (partner shift, tilt/roll, the clip's root angle) and which cap or slider range stopped it,
 * the deepest and the shallowest frame after the run, and a collapsible detail table — before and after.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { hasInside, targetWordOf } from './contactWords'
import { LampDot } from './StatusLamp'
import { type AlignBound, type KeyReason } from '@anima/scene-render'
import { noteText } from './alignStatus'
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
        {inside ? <th style={CELL} title={t('How deep the root joint of the part is along the axis (− = in front of the opening); in brackets where Auto-align aims it: just outside, or further out when the bottom stops the tip.')}>{t('root depth')}</th> : null}
        {inside ? <th style={CELL} title={t('Where the shaft line crosses the opening plane, off the axis.')}>{t('off at opening')}</th> : null}
        <th style={CELL} title={t('How far the tip is off the target’s axis.')}>{t('tip off axis')}</th>
        <th style={CELL} title={t('How far the root joint of the part is off the target’s axis line.')}>{t('root off axis')}</th>
        <th style={CELL} title={t('The rigid shaft (root joint to tip) against the axis.')}>{t('shaft')}</th>
        <th style={CELL} title={t('What the render-time bend still turns the part by at this frame, within the state’s limit.')}>{t('bend needed')}</th></tr></thead>
      <tbody>{rows.map(([key, label, r, rb]) => (
        <tr key={key} data-key={key}><td>{label}</td>
          {inside ? <td style={CELL} title={was(rb?.depthMm, 'mm')}>{mm(r.depthMm)}</td> : null}
          {inside ? <td style={{ ...CELL, color: key === 'deep' && !r.rootOutside ? 'var(--danger, #f85149)' : undefined }}
            title={was(rb?.rootDepthMm, 'mm')}>
            {mm(r.rootDepthMm)}{key === 'deep' ? ` (${(Math.round(r.rootTargetMm) || 0).toFixed(0)})` : ''}</td> : null}
          {inside ? <td style={CELL} title={was(rb?.openOffMm, 'mm')}>{mm(r.openOffMm)}</td> : null}
          <td style={CELL} title={was(rb?.tipOffMm, 'mm')}>{mm(r.tipOffMm)}</td>
          <td style={CELL} title={was(rb?.rootOffMm, 'mm')}>{mm(r.rootOffMm)}</td>
          <td style={CELL} title={was(rb?.shaftDeg, '°')}>{r.shaftDeg.toFixed(1)}°</td>
          <td style={CELL}>{r.bendDeg === null ? '–' : `${r.bendDeg.toFixed(1)}°${r.bendAtLimit ? ` (${t('limit')})` : ''}`}</td></tr>
      ))}</tbody>
    </table>
  )
}

/** Why the contact lamp is not green (`keyReasons`), in words. */
function reasonWord(t: (s: string) => string, r: KeyReason): string {
  switch (r) {
    case 'caps': return t('a cap or slider range stopped it')
    case 'shallower': return t('the deepest frame ended shallower than before')
    case 'root_inside': return t('the visible root of the part is inside the opening')
    case 'tip_outside': return t('the tip is not inside at the deepest frame')
    case 'past_bottom': return t('the tip is past the bottom at the deepest frame')
    case 'off_axis': return t('the shaft is more than 3 mm off the axis')
  }
}

/** The names of the unknowns that hit their cap or slider range. */
/** The gap of [min, max] furthest from the surface (mm), as a word. */
function gapWord(g: [number, number] | null): string {
  return g ? (Math.abs(g[0]) > Math.abs(g[1]) ? g[0] : g[1]).toFixed(0) : '–'
}
function boundWord(t: (s: string) => string, b: AlignBound, rangeCm: number, turnDeg: number): string {
  switch (b) {
    case 'side': return t('sideways (±{r} cm)').replace('{r}', rangeCm.toFixed(0))
    case 'up': return t('up/down (±{r} cm)').replace('{r}', rangeCm.toFixed(0))
    case 'forward': return t('forward/back (±{r} cm)').replace('{r}', rangeCm.toFixed(0))
    case 'tilt': return t('tilt (±{d}°)').replace('{d}', turnDeg.toFixed(0))
    case 'roll': return t('roll (±{d}°)').replace('{d}', turnDeg.toFixed(0))
    case 'turn': return t('yaw (±{d}°)').replace('{d}', turnDeg.toFixed(0))
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
          ? t('At the deepest and the shallowest frame the shaft runs within 3 mm of the axis through the opening; at the deepest the root is outside and the tip inside.')
          : r.lamp === 'yellow' ? t('At both key frames within 10 mm of the axis, the root outside and the tip inside at the deepest.')
            : t('More than 10 mm off the axis, the root or the tip on the wrong side of the opening, or a cap or slider range was hit.')} />
        <LampDot lamp={r.clearLamp} title={(r.clearLamp === 'green'
          ? t('Nothing else interpenetrates: only the attached part enters the other body, through the channel (at most 5 mm elsewhere).')
          : t('The bodies interpenetrate besides the channel by {mm} mm, deepest at {pair} (green at most 5 mm, yellow at most 20 mm).')
            .replace('{mm}', r.overlapAfterMm.toFixed(0)).replace('{pair}', r.clearWorst || '–'))} />
        <span>{t('{by} → {of}: {channel}').replace('{by}', r.by).replace('{of}', r.of)
          .replace('{channel}', r.target === 'channel' ? (r.channel.split(':').pop() || r.channel) : targetWordOf(t, r.target))}</span>
        {r.movers.length === 1 ? (
          <span data-testid="align-moved" style={{ opacity: 0.8 }}>· {(r.movers[0].mover === 'receiver'
            ? t('{role} moved (receiving role)') : t('{role} moved (part role)')).replace('{role}', r.movers[0].role.toUpperCase())}
            {r.relations[0]?.alternative ? ` — ${t('the automatic alternative: the part’s role was blocked')}` : ''}</span>
        ) : null}
      </div>
      {r.relations.filter((x) => !x.applied && x.discard).map((x, i) => (
        <div key={i} data-testid="align-discarded" style={{ color: 'var(--danger, #f85149)' }}>
          {(x.discard === 'overlap' && x.collide
            ? t('Not applied — {role} would go into place {who}: {pair} {mm} mm deep (the clip starts at {start} mm, allowed {allow} mm). The dials stay as they were.')
              .replace('{who}', x.collide.with).replace('{pair}', x.collide.worst).replace('{mm}', x.collide.afterMm.toFixed(0))
              .replace('{start}', x.collide.startMm.toFixed(0)).replace('{allow}', x.collide.allowMm.toFixed(0))
            : x.discard === 'support'
              ? t('Not applied — {role} would float above or sink into its seat or bed: {mm} mm off its surface (it starts at {start} mm; allowed −5 to +10 mm). The dials stay as they were.')
                .replace('{mm}', gapWord(x.support.afterMm)).replace('{start}', gapWord(x.support.beforeMm))
              : t('Not applied — {role} would end further off the axis than it starts. The dials stay as they were.'))
            .replace('{role}', x.moved.toUpperCase())}
        </div>
      ))}
      {r.relations.filter((x) => x.unchanged).map((x, i) => (
        <div key={i} data-testid="align-unchanged" style={{ color: 'var(--success, #3fb950)' }}>
          {t('Unchanged — {role} already fits: nothing to gain (less than 5 mm). The dials stay as they were.').replace('{role}', x.moved.toUpperCase())}
        </div>
      ))}
      {r.relations.filter((x) => x.rootPull?.stuck).map((x, i) => (
        <div key={i} data-testid="align-root-stuck" style={{ color: 'var(--danger, #f85149)' }}>
          {(x.rootPull!.stuck!.why === 'overlap'
            ? t('The visible root stays {mm} mm inside the opening: pulling {role} back further would go into place {who}.')
              .replace('{who}', x.rootPull!.stuck!.with || '–')
            : x.rootPull!.stuck!.why === 'support'
              ? t('The visible root stays {mm} mm inside the opening: pulling {role} back further would take it off its surface.')
              : t('The visible root stays {mm} mm inside the opening: pulling {role} back further is beyond its range cap.'))
            .replace('{mm}', (x.rendered?.after.visMm ?? 0).toFixed(0)).replace('{role}', x.moved.toUpperCase())}
        </div>
      ))}
      {r.relations.filter((x) => x.rootPull && x.rootPull.mm >= 0.5).map((x, i) => (
        <div key={i} data-testid="align-root-pulled">
          {t('Pulled {role} back {mm} mm along the axis so that the visible root is outside on every rendered frame.')
            .replace('{role}', x.moved.toUpperCase()).replace('{mm}', x.rootPull!.mm.toFixed(0))}
        </div>
      ))}
      {r.relations.filter((x) => x.notes.some((n) => n.code !== 'no_change')).map((x, i) => (
        <div key={i} data-testid="align-notes" data-notes={x.notes.map((n) => n.code).join(' ')} style={{ color: 'var(--text-muted, #8b949e)' }}>
          {t('Note')}: {x.notes.filter((n) => n.code !== 'no_change').map((n) => noteText(t, n)).join('; ')}
        </div>
      ))}
      {r.relations.filter((x) => x.rendered).map((x, i) => (
        <div key={i} data-testid="align-rendered-root"
          style={x.rendered!.after.visMm > 0 ? { color: 'var(--danger, #f85149)' } : undefined}
          title={t('Where the part’s mesh meets the body (the body-side end of its first capsule, with its radius), along the axis through the opening, at the frame of the loop as rendered where it is deepest; negative = outside.')}>
          {t('Visible root at its deepest rendered frame: {after} mm (before {before} mm; negative = outside)')
            .replace('{after}', x.rendered!.after.visMm.toFixed(0)).replace('{before}', x.rendered!.before.visMm.toFixed(0))}
        </div>
      ))}
      {r.relations.map((x, i) => (
        <div key={i} data-testid="align-support" data-support={JSON.stringify(x.support)}
          title={t('The moved role’s lowest support capsule over the surface of its place, over the loop (the frame furthest from it). A role on its feet, or one carried more than 50 mm above its surface by the other person, keeps its own posture instead.')}>
          {x.support.mode === 'surface'
            ? t('{role} on its surface: {before} mm → {after} mm (allowed −5 to +10 mm)').replace('{role}', x.moved.toUpperCase())
              .replace('{before}', gapWord(x.support.beforeMm)).replace('{after}', gapWord(x.support.afterMm))
            : x.support.mode === 'band' ? t('{role} is carried (on its feet or by the other person): its own posture holds it.').replace('{role}', x.moved.toUpperCase())
              : ''}
          {x.support.others.filter((o) => o.mm && (o.mm[0] < -5 || o.mm[0] > 10) && o.mm[0] < 50).map((o) => (
            <span key={o.letter} style={{ color: 'var(--warning, #d29922)' }}>
              {' · '}{t('place {p} ({role}, not moved) starts {mm} mm off its surface').replace('{p}', o.letter).replace('{role}', o.role.toUpperCase())
                .replace('{mm}', o.mm![0].toFixed(0))}</span>
          ))}
        </div>
      ))}
      {r.relations[0]?.clear.length ? (
        <table data-testid="align-clear" style={{ borderCollapse: 'collapse' }}
          title={t('The moved role against every other person over the loop: the deepest capsule overlap at the start, the allowance (the start, at least 5 mm) and after. The attached part inside its channel does not count.')}>
          <thead><tr><th style={{ textAlign: 'left' }}>{t('Overlap with')}</th><th style={CELL}>{t('start')}</th>
            <th style={CELL}>{t('allowed')}</th><th style={CELL}>{t('after')}</th><th style={{ textAlign: 'left' }}>{t('deepest pair')}</th></tr></thead>
          <tbody>{r.relations[0].clear.map((c) => (
            <tr key={c.with}><td>{t('place {p}').replace('{p}', c.with)}</td><td style={CELL}>{c.startMm.toFixed(0)} mm</td>
              <td style={CELL}>{c.allowMm.toFixed(0)} mm</td>
              <td style={{ ...CELL, color: c.afterMm > c.allowMm + 0.5 ? 'var(--danger, #f85149)' : undefined }}>{c.afterMm.toFixed(0)} mm</td>
              <td>{c.worst || '–'}</td></tr>
          ))}</tbody>
        </table>
      ) : null}
      {r.reasons.length ? (
        <div data-testid="align-reasons" style={{ color: r.lamp === 'red' ? 'var(--danger, #f85149)' : 'var(--warning, #d29922)' }}>
          {t('Contact lamp {lamp}: {why}.').replace('{lamp}', r.lamp === 'red' ? t('red') : r.lamp === 'yellow' ? t('yellow') : t('green'))
            .replace('{why}', r.reasons.map((x) => reasonWord(t, x)).join('; '))}</div>
      ) : null}
      {r.rootShared.length ? (
        <div data-testid="align-root-shared" style={{ color: 'var(--warning, #d29922)' }}>
          {t('The root angle is one per clip: it also turns the part of {rels}.').replace('{rels}', r.rootShared.join(', '))}</div>
      ) : null}
      {r.movers.map((m) => {
        const v3 = (v: number[]) => v.map((x) => x.toFixed(1)).join(' / ')
        const limit = t('Auto-align moves {role} at most ±{r} cm in every direction and turns it at most ±{d}° in tilt, roll and yaw around the arrangement you set (the dials before the first click), and sets the root angle within its sliders; what lies beyond is yours to set by hand.')
          .replace('{role}', m.role.toUpperCase()).replace('{r}', m.rangeCm.toFixed(0)).replace('{d}', m.turnRangeDeg.toFixed(0))
        return (
          <div key={m.role} data-testid="align-cap" data-lamp={m.lamp} title={limit}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <LampDot lamp={m.lamp} title={t('Within the alignment range')} />
              <span>{t('{role} moved by {a} cm (now {s} cm)').replace('{role}', m.role.toUpperCase()).replace('{a}', v3(m.adjustCm)).replace('{s}', v3(m.shiftCm))}
                {m.adjustDeg.some((v) => v !== 0)
                  ? ` · ${t('turned tilt {a}° roll {b}° yaw {c}° (now {n}°)').replace('{a}', m.adjustDeg[0].toFixed(1)).replace('{b}', m.adjustDeg[1].toFixed(1))
                    .replace('{c}', m.adjustDeg[2].toFixed(1)).replace('{n}', v3(m.turnDeg))}` : ''}</span>
            </div>
            {m.rootAngle ? (
              <div data-testid="align-root">{t('Root angle pitch {p}° yaw {y}° (was {p0}° / {y0}°) — written to the root-angle dials.')
                .replace('{p}', m.rootAngle.pitchDeg.toFixed(1)).replace('{y}', m.rootAngle.yawDeg.toFixed(1))
                .replace('{p0}', (m.rootBefore?.pitchDeg ?? 0).toFixed(1)).replace('{y0}', (m.rootBefore?.yawDeg ?? 0).toFixed(1))}</div>
            ) : null}
            {m.hits.length ? (
              <div style={{ color: 'var(--danger, #f85149)' }}>
                {t('Stopped by: {names} — move it closer by hand.').replace('{names}', m.hits.map((b) => boundWord(t, b, m.rangeCm, m.turnRangeDeg)).join(', '))}</div>
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
      {r.pivotCm ? (
        <div data-testid="align-pivot" title={t('Figures of other heights than 1.70 m are scaled about this point in the game, each by its own height ratio, so the contact stays where it is. Measured at the deepest frame; Save stores it.')}>
          {t('Contact pivot: side {x} cm, forward {z} cm').replace('{x}', r.pivotCm[0].toFixed(1)).replace('{z}', r.pivotCm[1].toFixed(1))}</div>
      ) : null}
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
        {t('Measured on two 1.70 m figures; in the game every figure is scaled about the contact pivot by its own height. Save stores the role dials, the root angle and the contact pivot.')}
      </div>
    </div>
  )
}
