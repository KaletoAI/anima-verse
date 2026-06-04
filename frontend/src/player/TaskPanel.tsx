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
  // Sekundärzeile (Status · Dauer · Provider · Iteration) — als umbrechender
  // Text, damit es bei schmaler Panel-Breite lesbar bleibt statt abzuschneiden.
  const sub = [
    elapsed != null ? t('thinking {n}').replace('{n}', fmtDur(elapsed)) : t('thinking'),
    eta != null ? `~${fmtDur(Math.round(eta))}` : '',
    meta, iter,
  ].filter(Boolean).join(' · ')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span className="player-task-pulse" style={{
          width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
          background: 'var(--accent, #6aa9ff)',
        }} />
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em' }}>
          {title}
        </span>
      </div>
      <div style={{ paddingLeft: 16, fontSize: '0.72em', opacity: 0.6, lineHeight: 1.3,
                    fontVariantNumeric: 'tabular-nums', wordBreak: 'break-word' }}>
        {sub}
      </div>
    </div>
  )
}

function TrackedRow({ tk, nowMs }: { tk: TrackedTaskInfo; nowMs: number }) {
  const { t } = useI18n()
  const running = (tk.status || '') === 'running'
  const elapsed = elapsedSeconds(tk.started_at, nowMs)
  const waited = elapsedSeconds(tk.created_at, nowMs)
  const title = tk.label || tk.task_type || t('Task')
  // Sekundärzeile wie bei LLM-Calls: Status · Dauer · Backend · Agent.
  const sub = running
    ? [
        elapsed != null ? `${t('running')} ${fmtDur(elapsed)}` : t('running'),
        tk.provider, tk.agent_name,
      ].filter(Boolean).join(' · ')
    : [
        t('pending'),
        waited != null ? t('waiting {n}').replace('{n}', fmtDur(waited)) : '',
        tk.provider, tk.agent_name,
      ].filter(Boolean).join(' · ')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        {/* running: gefüllter, pulsierender Punkt (wie LLM). pending: hohler,
            gestrichelter Ring → wartende Tasks klar abgesetzt. */}
        {running ? (
          <span className="player-task-pulse" style={{
            width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
            background: 'var(--accent, #6aa9ff)',
          }} />
        ) : (
          <span style={{
            width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
            background: 'transparent', border: '1.5px dashed var(--text-muted, #8b949e)',
            boxSizing: 'border-box',
          }} />
        )}
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em', opacity: running ? 1 : 0.7 }}>
          {title}
        </span>
      </div>
      <div style={{ paddingLeft: 16, fontSize: '0.72em', opacity: running ? 0.6 : 0.45,
                    lineHeight: 1.3, fontVariantNumeric: 'tabular-nums',
                    fontStyle: running ? 'normal' : 'italic', wordBreak: 'break-word' }}>
        {sub}
      </div>
    </div>
  )
}

export function TaskPanel() {
  const { t } = useI18n()
  const { llmTasks, trackedTasks, channels } = useQueue(2000)
  const [nowMs, setNowMs] = useState(() => Date.now())

  // Sekündlicher Tick, wenn LLM-Calls ODER laufende Tracked-Tasks (z.B.
  // Bildgenerierung) mit laufender Dauer angezeigt werden.
  const anyRunning = llmTasks.length > 0
    || trackedTasks.some((t) => (t.status || '') === 'running')
  useEffect(() => {
    if (!anyRunning) return
    const id = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [anyRunning])

  const hasTasks = llmTasks.length > 0 || trackedTasks.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {channels.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }}>
          {channels.map((ch) => {
            const state = ch.healthy ? (ch.busy ? t('busy') : t('available')) : t('unavailable')
            const kindLabel = ch.kind === 'image' ? t('Image backend') : t('LLM provider')
            const color = !ch.healthy ? '#e05656' : ch.busy ? 'var(--accent, #6aa9ff)' : '#3fa45a'
            return (
              <span key={ch.key} title={`${kindLabel} · ${state}`}
                style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.8em' }}>
                {/* Image-Backends: eckiger Marker (mit Rahmen) — LLM-Provider: runder Punkt. */}
                <span style={{
                  width: 8, height: 8, flex: '0 0 auto', background: color,
                  borderRadius: ch.kind === 'image' ? 2 : '50%',
                  outline: ch.kind === 'image' ? '1px solid rgba(255,255,255,0.55)' : 'none',
                  outlineOffset: ch.kind === 'image' ? 1 : 0,
                }} />
                <span style={{
                  opacity: ch.healthy ? 0.85 : 0.55,
                  fontStyle: ch.kind === 'image' ? 'italic' : 'normal',
                }}>{ch.name}</span>
              </span>
            )
          })}
        </div>
      )}
      {channels.length > 0 && hasTasks && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }} />
      )}
      {!hasTasks && (
        <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No active tasks')}</div>
      )}
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
          {trackedTasks.map((tk, i) => <TrackedRow key={tk.task_id || `trk${i}`} tk={tk} nowMs={nowMs} />)}
        </div>
      )}
    </div>
  )
}
