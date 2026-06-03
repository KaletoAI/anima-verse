/**
 * TaskPanel — System-Task-/Queue-Anzeige, analog zur alten UI.
 * plan-room-conversation Phase 3.
 *
 * Zwei Gruppen aus GET /queue/status (via useQueue):
 *   • LLM-Calls (providers[*].chat_active) — die "X denkt …"-Einträge mit
 *     Label, Modell, GPU, laufender Dauer, Schätzung und Iteration.
 *   • Getrackte Tasks (active_tasks) — Bild-/Video-/TTS-/GPU-Tasks.
 * Read-only, Poll alle 2 s; laufende Dauer tickt sekündlich lokal.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { useQueue, elapsedSeconds, type LLMTaskInfo, type TrackedTaskInfo } from './useQueue'

function fmtDur(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

function LLMRow({ tk, nowMs }: { tk: LLMTaskInfo; nowMs: number }) {
  const { t } = useI18n()
  // started_at wird erst bei Verarbeitungsstart gesetzt; chat_active-Tasks haben
  // es oft (noch) nicht → created_at (Registrierungszeit) als Fallback, damit die
  // Zeit von Anfang an mitläuft.
  const elapsed = elapsedSeconds(tk.started_at || tk.created_at, nowMs)
  const eta = tk.estimated_duration_s && tk.estimated_duration_s > 0 ? tk.estimated_duration_s : null
  const iter = tk.iteration && tk.iteration > 0 ? `iter ${tk.iteration}/${tk.max_iterations || 1}` : ''
  const meta = [tk.provider_name, tk.model].filter(Boolean).join(' / ')
  const title = tk.label || (tk.agent_name ? `${tk.agent_name}` : tk.task_type || t('LLM call'))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span className="player-task-pulse" style={{
          width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
          background: 'var(--accent, #6aa9ff)',
        }} />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em' }}>
          {title}
        </span>
        <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.78em', opacity: 0.75 }}>
          {elapsed != null ? t('thinking {n}').replace('{n}', fmtDur(elapsed)) : t('thinking')}
          {eta != null ? <span style={{ opacity: 0.6 }}> · ~{fmtDur(Math.round(eta))}</span> : null}
        </span>
      </div>
      {(meta || iter) && (
        <div style={{ paddingLeft: 16, fontSize: '0.7em', opacity: 0.5, display: 'flex', gap: 8 }}>
          {meta ? <span>{meta}</span> : null}
          {iter ? <span>{iter}</span> : null}
        </div>
      )}
    </div>
  )
}

function TrackedRow({ tk }: { tk: TrackedTaskInfo }) {
  const { t } = useI18n()
  const running = (tk.status || '') === 'running'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
        background: running ? 'var(--accent, #6aa9ff)' : 'var(--text-muted, #8b949e)',
        opacity: running ? 1 : 0.5,
      }} />
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em' }}>
        {tk.label || tk.task_type || t('Task')}
        {tk.agent_name ? <span style={{ opacity: 0.6 }}> · {tk.agent_name}</span> : null}
      </span>
      <span style={{ fontSize: '0.7em', opacity: 0.6 }}>{running ? t('running') : t('pending')}</span>
    </div>
  )
}

export function TaskPanel() {
  const { t } = useI18n()
  const { llmTasks, trackedTasks } = useQueue(2000)
  const [nowMs, setNowMs] = useState(() => Date.now())

  // Sekündlicher Tick nur, wenn LLM-Calls mit laufender Dauer angezeigt werden.
  useEffect(() => {
    if (!llmTasks.length) return
    const id = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [llmTasks.length])

  if (!llmTasks.length && !trackedTasks.length) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No active tasks')}</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {llmTasks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {llmTasks.map((tk, i) => <LLMRow key={tk.task_id || `llm${i}`} tk={tk} nowMs={nowMs} />)}
        </div>
      )}
      {llmTasks.length > 0 && trackedTasks.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }} />
      )}
      {trackedTasks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {trackedTasks.map((tk, i) => <TrackedRow key={tk.task_id || `trk${i}`} tk={tk} />)}
        </div>
      )}
    </div>
  )
}
