/**
 * BuildProblem — what failed in the character's Build and the action that fixes it (Ruling A61; the tab checklist
 * point 8: the step, the reason in plain words, the view, the action with its cost). Shown under the flow head of
 * every tab that runs the Build: Pose, Figure, Base body and 3D.
 * - `BuildProblemView` draws a `BuildProblem` (`GET …/figure` `problem`, `figureModel.problemText`): a red light,
 *   "<step> failed — <view>", the reason, the button that fixes it naming its hub jobs, and why automatic Builds
 *   do not repeat it; the worker's own message on mouse-over.
 * - `BuildProblemNote` reads `GET …/figure` itself (useFigure) and runs the fix as the Build does
 *   (`POST …/figure/build` — a manual Build: it makes the mesh again first, or retries the step once).
 */
import { useCallback, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { BUILD_STATUS, problemText, type BuildProblem } from './figureModel'
import { StepLight } from './StepRows'
import { LIGHT_COLOR } from './stepStyle'
import { useFigure } from './useFigure'

export function BuildProblemView({ problem, busy, onRun, runLabel, extra }: {
  problem: BuildProblem
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
  return (
    <div role="alert" style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px',
      border: `1px solid ${LIGHT_COLOR.red}`, borderRadius: 6, fontSize: 13 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} title={text.detail || undefined}>
        <StepLight light="red" />
        <strong style={{ color: LIGHT_COLOR.red }}>{text.title}</strong>
      </div>
      <div className="ga-hint" style={{ overflowWrap: 'anywhere' }} title={text.detail || undefined}>{text.reason}</div>
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
