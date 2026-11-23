/**
 * "ALIGN ALL" IN TWO STAGES (owner 2026-11-22) — the table of stage 1 and the controls of stage 2.
 *
 * Stage 1 measures every pair and group clip listed, relation by relation (Auto-align with `each`: the relations of a
 * clip one after the other, each on the previous one's result, the mover 'auto' unless the row names one), and sorts
 * each contact relation into a bucket (scene-render `alignBucket`): "would improve", "blocked" (discarded for an
 * overlap or for ending worse than its start, held by a cap or the posture, or nothing to gain) and "geometry mismatch"
 * (the shaft more than `ALIGN_MISMATCH_DEG` off the axis at the deepest frame); a clip that gave no relation to measure
 * (no prop has a place for it, no persons were filled in, or the persons carry no part a channel accepts) is "not
 * measured", with the reason. Nothing is written in stage 1. Stage 2 applies and saves only the rows the user
 * leaves ticked (only "would improve" rows can be ticked); a blocked row may get another mover and be measured again.
 * The clip's one root angle is solved by the first relation that carries the part and kept by the others — the
 * "root" column says which.
 *
 * Owner decisions 2026-11-23: the moved role may TURN (tilt, roll, yaw within the clip's rotation range — the "turn"
 * column), must stay ON its surface (THE SUPPORT, ABSOLUTE — the "support" column, the moved role's gap over its
 * surface before → after), and a result counts only with THE MINIMUM GAIN (5 mm less axis error or depth error; else
 * "nothing to gain"). Stage 2 also records the status of every row of the table in its clip's sidecar
 * (`alignStatus.ts`) — a saved row as improved / aligned, the others as blocked / mismatch / not measurable.
 */
import { ALIGN_GAIN_MM, ALIGN_MISMATCH_DEG, type AlignBucket } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import type { AlignMoverChoice, RelationAlign } from './PlacePreview'

/** One contact relation of one clip in "Align all". */
export interface AlignAllRow {
  kind: string; set: string
  /** The relation's key (`RelationAlign.key`; '' for a clip that gave no relation) and its label (B → A (mouth)). */
  key: string; label: string
  bucket: AlignBucket | 'unmeasured'
  /** The measured relation (null: the clip gave none — `reason` says why). */
  rel: RelationAlign | null
  reason: string
  /** How long opening the clip took (seconds, "Align all"'s wait for its scene and figures). */
  waitS?: number
  /** Why the clip gave no relation (for its status). */
  code?: 'no_place' | 'no_part' | 'no_pair'
  /** The mover the next re-measure uses, whether the row is ticked for stage 2, and what stage 2 did with it. */
  choice: AlignMoverChoice; tick: boolean; outcome: string
}

const BUCKETS: readonly (AlignBucket | 'unmeasured')[] = ['improve', 'blocked', 'mismatch', 'unmeasured']

export function AlignAllTable({ rows, busy, onTick, onChoice, onRemeasure, onOpen, onApply }: {
  rows: readonly AlignAllRow[]; busy: boolean
  onTick: (i: number, on: boolean) => void
  onChoice: (i: number, c: AlignMoverChoice) => void
  onRemeasure: (i: number) => void
  onOpen: (i: number) => void
  onApply: () => void
}) {
  const { t } = useI18n()
  const bucketWord = (b: AlignAllRow['bucket']) => ({ improve: t('would improve'), blocked: t('blocked'),
    mismatch: t('geometry mismatch'), unmeasured: t('not measured') })[b]
  const why = (r: AlignAllRow): string => {
    const x = r.rel
    if (!x) return r.reason
    if (r.bucket === 'mismatch') return x.keys.before
      ? t('shaft {deg}° off the axis at the deepest frame (more than {max}°)').replace('{deg}', x.keys.before.deep.shaftDeg.toFixed(0))
        .replace('{max}', String(ALIGN_MISMATCH_DEG))
      : t('no contact found')
    if (x.discard === 'overlap' && x.collide) return t('would go into {who}: {pair} {mm} mm (allowed {allow} mm)')
      .replace('{who}', x.collide.with).replace('{pair}', x.collide.worst).replace('{mm}', x.collide.afterMm.toFixed(0))
      .replace('{allow}', x.collide.allowMm.toFixed(0))
    if (x.discard === 'worse') return t('ends deeper off its depth and further off the axis than it starts')
    if (x.discard === 'support') return t('the moved role would float above or sink into its surface')
    if (x.discard === 'root') return t('the visible root would end inside the opening')
    const parts: string[] = []
    if (x.reasons.includes('caps')) parts.push(t('a cap was hit'))
    if (x.limitReason === 'posture') parts.push(t('the posture held it back'))
    if (x.reasons.includes('root_inside')) parts.push(t('the visible root is inside the opening'))
    if (r.bucket === 'blocked' && !parts.length) parts.push(t('nothing to gain (less than {mm} mm)').replace('{mm}', String(ALIGN_GAIN_MM)))
    return parts.join(', ')
  }
  const gapMm = (g: [number, number] | null) => (g ? (Math.abs(g[0]) > Math.abs(g[1]) ? g[0] : g[1]).toFixed(0) : '–')
  const supportCell = (x: RelationAlign) => (x.support.mode === 'surface'
    ? `${gapMm(x.support.beforeMm)} → ${gapMm(x.support.afterMm)}` : x.support.mode === 'band' ? t('carried') : '–')
  const counts = BUCKETS.map((b) => [b, rows.filter((r) => r.bucket === b).length] as const)
  const ticked = rows.filter((r) => r.tick).length
  const fmt = (v: number | undefined | null) => (v === undefined || v === null ? '–' : v.toFixed(0))
  const axis = (rep: RelationAlign['keys']['before']) => (rep
    ? Math.max(rep.deep.openOffMm, rep.deep.leverMm, rep.shallow.openOffMm, rep.shallow.leverMm) : null)
  return (
    <div data-testid="align-all-stage" style={{ fontSize: 11 }}>
      <div data-testid="align-all-counts" data-counts={JSON.stringify(Object.fromEntries(counts))}>
        {counts.map(([b, n]) => `${bucketWord(b)} ${n}`).join(' · ')}
      </div>
      <table data-testid="align-all-result" data-result={JSON.stringify(rows)} style={{ borderCollapse: 'collapse' }}>
        <thead><tr>
          <th title={t('Ticked rows are applied and saved by stage 2; only rows that would improve can be ticked.')}>✓</th>
          <th style={{ textAlign: 'left' }}>{t('Clip')}</th><th>{t('Contact')}</th><th>{t('Result')}</th>
          <th title={t('Tip depth at the deepest frame, before → after (mm)')}>{t('depth')}</th>
          <th title={t('Axis error: the opening offset or the angle’s lever, worst of both key frames, before → after (mm)')}>{t('off axis')}</th>
          <th title={t('The visible root at its deepest frame of the loop as rendered, after (mm, negative = outside)')}>{t('root at')}</th>
          <th>{t('moved')}</th>
          <th title={t('The moved role’s turn after the run: tilt / roll / yaw (degrees, from the saved state)')}>{t('turn')}</th>
          <th title={t('The moved role’s lowest support capsule over its surface, the frame furthest from it, before → after (mm; carried = on the other person or on its feet, held by its own posture instead)')}>{t('support')}</th>
          <th title={t('The clip has one root angle: the first relation that carries the part solves it, the others keep it.')}>{t('root')}</th>
          <th style={{ textAlign: 'left' }}>{t('Reason')}</th><th /><th />
        </tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const x = r.rel
            return (
              <tr key={`${r.kind}|${r.set}|${r.key}|${i}`} data-bucket={r.bucket}>
                <td><input type="checkbox" checked={r.tick} disabled={busy || r.bucket !== 'improve'}
                  onChange={(e) => onTick(i, e.target.checked)} /></td>
                <td title={r.set ? `${r.kind} (${r.set})` : r.kind}
                  style={{ maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.kind}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.label}</td>
                <td>{bucketWord(r.bucket)}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{x ? `${fmt(x.keys.before?.deep.depthMm)} → ${fmt(x.keys.after?.deep.depthMm)}` : ''}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{x ? `${fmt(axis(x.keys.before))} → ${fmt(axis(x.keys.after))}` : ''}</td>
                <td style={{ textAlign: 'right' }}>{x?.rendered ? x.rendered.after.visMm.toFixed(0) : ''}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{x ? `${x.moved.toUpperCase()}${x.alternative ? ` (${t('auto alternative')})` : ''}` : ''}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{x ? x.turnDeg.map((v) => v.toFixed(0)).join(' / ') : ''}</td>
                <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>{x ? supportCell(x) : ''}</td>
                <td>{x ? ({ solved: t('solved'), kept: t('kept'), none: '–' })[x.root] : ''}</td>
                <td style={{ maxWidth: 220 }}>{why(r)}{r.outcome ? <span style={{ opacity: 0.8 }}> · {r.outcome}</span> : null}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.bucket === 'blocked' ? (<>
                  <select value={r.choice} disabled={busy} onChange={(e) => onChoice(i, e.target.value as AlignMoverChoice)}
                    style={{ fontSize: 11 }} title={t('Which role the re-measure moves')}>
                    <option value="auto">{t('Auto')}</option>
                    <option value="part">{t('part')}</option>
                    <option value="receiver">{t('receiving')}</option>
                  </select>
                  <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => onRemeasure(i)}>{t('Re-measure')}</button>
                </>) : null}</td>
                <td><button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => onOpen(i)}>{t('Open')}</button></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" data-testid="align-all-apply" disabled={busy || !ticked}
          onClick={onApply}>{t('Apply and save the ticked rows ({n})').replace('{n}', String(ticked))}</button>
        <span className="ga-form-hint" style={{ margin: 0 }}>
          {t('Nothing is moved without a tick. Stage 2 measures each ticked clip again with only its ticked relations and the mover shown, and saves it only when every one of them still improves (one Blender run per clip, no hub jobs); it records every row’s status in its clip.')}
        </span>
      </div>
    </div>
  )
}
