/**
 * BuildProblem — what failed in the character's Build and the action that fixes it (Ruling A61; the tab checklist
 * point 8: the step, the reason in plain words, the view, the action with its cost). Shown under the flow head of
 * every tab that runs the Build: Figure, Base body and 3D.
 * - `BuildProblemView` draws a `BuildProblem` (`GET …/figure` `problem`, `figureModel.problemText`): a red light,
 *   "<step> failed — <view>", the reason, the button that fixes it naming its hub jobs, and why automatic Builds
 *   do not repeat it; the worker's own message on mouse-over.
 * - `BuildProblemNote` reads `GET …/figure` itself (useFigure) and runs the fix as the Build does
 *   (`POST …/figure/build` — a manual Build: it makes the mesh again first, or retries the step once).
 */
import { useCallback, useState, type CSSProperties, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import {
  BUILD_STATUS, attemptLines, failureLines, failureRowText, isLeftDue, problemText, type BuildProblem,
  type StepFailure,
} from './figureModel'
import { StepLight } from './StepRows'
import { LIGHT_COLOR } from './stepStyle'
import { useFigure } from './useFigure'

const PRE: CSSProperties = { margin: '4px 0 0', padding: 6, maxHeight: 240, overflow: 'auto', fontSize: 11,
  whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--bg-subtle, rgba(127,127,127,0.08))',
  borderRadius: 4 }
const SUMMARY: CSSProperties = { cursor: 'pointer', fontSize: 12 }
const CELL: CSSProperties = { padding: '1px 8px 1px 0', verticalAlign: 'top' }

/**
 * What stands behind a failed step's sentence, collapsed: "Details" — for a structured failure (`failure`) the table
 * of every check (value, limit, passed / failed / slow, gating or reported) and the raw message, otherwise the raw
 * message with one line per attempt (`attemptLines`) — and "Blender output" (`failure.log_tail`, monospace) when
 * there is one. Nothing to show → nothing rendered.
 */
export function FailureDetails({ failure, detail }: { failure?: StepFailure | null; detail?: string }) {
  const { t } = useI18n()
  const raw = (failure?.error || detail || '').trim()
  const rows = failure?.rows || []
  const tail = failure?.log_tail || ''
  if (!raw && !rows.length && !tail) return null
  return (
    <div style={{ paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 2 }}>
      {rows.length || raw ? (
        <details>
          <summary className="ga-hint" style={SUMMARY}>{t('Details')}</summary>
          {rows.length ? (
            <table style={{ fontSize: 11, marginTop: 4, borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr>{[t('Drape check'), t('Value'), t('Limit'), t('Result'), t('Effect')].map((h) => (
                  <th key={h} style={CELL}>{h}</th>))}</tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const w = failureRowText(r, t)
                  return (
                    <tr key={r.check} style={!r.ok ? { color: r.gate ? LIGHT_COLOR.red : LIGHT_COLOR.yellow } : undefined}>
                      {[w.check, w.value, w.limit, w.result, w.effect].map((c, i) => <td key={i} style={CELL}>{c}</td>)}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : null}
          {raw ? <pre style={PRE}>{attemptLines(raw).join('\n')}</pre> : null}
        </details>
      ) : null}
      {tail ? (
        <details>
          <summary className="ga-hint" style={SUMMARY}>{t('Blender output')}</summary>
          <pre style={{ ...PRE, fontFamily: 'var(--font-mono, monospace)' }}>{tail}</pre>
        </details>
      ) : null}
    </div>
  )
}

/** The one-line attempts of a refusal (`attemptLines`) under its notice, each clipped with the whole on mouse-over;
 *  nothing for a message of one attempt. */
export function AttemptLines({ detail }: { detail: string }) {
  const lines = attemptLines(detail)
  if (lines.length < 2) return null
  return (
    <div style={{ paddingLeft: 16, display: 'flex', flexDirection: 'column' }}>
      {lines.map((line, i) => <span key={i} className="ga-one-line ga-hint" title={line}>{line}</span>)}
    </div>
  )
}

export function BuildProblemView({ problem, busy, onRun, runLabel, extra, compact }: {
  problem: BuildProblem
  /** Ruling A90: one notice line — the light, the title and the reason (the whole, the measured detail and the note on
   *  mouse-over) and the fix's button with its cost (the Figure tab's notices). */
  compact?: boolean
  busy?: boolean
  /** Runs the fix; without it the action is named, not offered. */
  onRun?: () => void
  /** Replaces the button's words (the Base body tab runs the same step through Run all). */
  runLabel?: string
  /** More buttons beside the action (a link into another tab). */
  extra?: ReactNode
}) {
  const { t } = useI18n()
  const text = problemText(problem, t)
  // A run that ended without a verdict (timeout, interrupted, Blender unavailable) is a note, not a red failure.
  const leftDue = isLeftDue(problem.failure)
  const light = leftDue ? 'grey' : 'red'
  const color = leftDue ? undefined : LIGHT_COLOR.red
  const role = leftDue ? 'status' : 'alert'
  const below = (
    <>
      {problem.failure ? null : <AttemptLines detail={problem.detail} />}
      <FailureDetails failure={problem.failure} detail={problem.detail} />
    </>
  )
  if (compact) {
    const title = [text.reason, text.detail, text.note].filter(Boolean).join('\n')
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
        <div role={role} className="ga-notice" title={title || undefined}>
          <StepLight light={light} />
          <span className="ga-one-line ga-notice-text" style={color ? { color } : undefined}>
            <strong>{text.title}</strong>{problem.failure?.lines.length ? '' : ` · ${text.reason}`}
          </span>
          {onRun ? (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy} onClick={onRun} title={title || undefined}>
              {runLabel || text.action}
            </button>
          ) : <span className="ga-hint">{text.action}</span>}
          {extra}
        </div>
        {problem.failure?.lines.length ? (
          // The plain sentences in full (the one-line notice above carries only the step).
          <div style={{ paddingLeft: 16, overflowWrap: 'anywhere', ...(color ? { color } : {}) }} className="ga-hint">
            {failureLines(problem.failure, t).map((line, i) => <div key={i}>{line}</div>)}
            {text.note ? <div>{text.note}</div> : null}
          </div>
        ) : null}
        {below}
      </div>
    )
  }
  return (
    <div role={role} style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px',
      border: `1px solid ${color || 'var(--border, #30363d)'}`, borderRadius: 6, fontSize: 13 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} title={text.detail || undefined}>
        <StepLight light={light} />
        <strong style={color ? { color } : undefined}>{text.title}</strong>
      </div>
      <div className="ga-hint" style={{ overflowWrap: 'anywhere' }} title={text.detail || undefined}>{text.reason}</div>
      {below}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {onRun ? (
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy} onClick={onRun}
            title={text.detail || undefined}>
            {runLabel || text.action}
          </button>
        ) : <span className="ga-hint">{text.action}</span>}
        {extra}
      </div>
      {text.note ? <div className="ga-hint" style={{ fontSize: 12 }}>{text.note}</div> : null}
    </div>
  )
}

export function BuildProblemNote({ character, onStarted, extra }: {
  character: string
  /** A Build was started or queued (the caller re-reads its own status). */
  onStarted?: () => void
  extra?: ReactNode
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { data, startPoll } = useFigure(character)
  const [posting, setPosting] = useState(false)
  const run = useCallback(async () => {
    if (posting) return
    setPosting(true)
    try {
      const d = await apiPost<Record<string, unknown>>(`/characters/${enc}/figure/build`, {})
      const status = String(d?.status || '')
      toast(t(BUILD_STATUS[status] || status), 'success')
      onStarted?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      startPoll(300)
    }
  }, [enc, onStarted, posting, startPoll, t, toast])
  if (!data?.pipeline || !data.problem || data.build.running) return null
  return <BuildProblemView problem={data.problem} busy={posting} onRun={run} extra={extra} />
}
