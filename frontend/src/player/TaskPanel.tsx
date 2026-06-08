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
import { useQueue, elapsedSeconds, type LLMTaskInfo, type TrackedTaskInfo, type RecentTaskInfo } from './useQueue'

function fmtDur(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

function LLMRow({ tk, nowMs, pending }: { tk: LLMTaskInfo; nowMs: number; pending?: boolean }) {
  const { t } = useI18n()
  // started_at wird erst bei Verarbeitungsstart gesetzt; chat_active-Tasks haben
  // es oft (noch) nicht → created_at (Registrierungszeit) als Fallback, damit die
  // Zeit von Anfang an mitläuft. Wartende Calls haben nur created_at.
  const elapsed = elapsedSeconds(pending ? tk.created_at : (tk.started_at || tk.created_at), nowMs)
  const eta = tk.estimated_duration_s && tk.estimated_duration_s > 0 ? tk.estimated_duration_s : null
  const iter = tk.iteration && tk.iteration > 0 ? `iter ${tk.iteration}/${tk.max_iterations || 1}` : ''
  const meta = [tk.provider_name, tk.model].filter(Boolean).join(' / ')
  const title = tk.label || (tk.agent_name ? `${tk.agent_name}` : tk.task_type || t('LLM call'))
  // Sekundärzeile (Status · Dauer · Provider · Iteration) — als umbrechender
  // Text, damit es bei schmaler Panel-Breite lesbar bleibt statt abzuschneiden.
  const sub = pending
    ? [
        elapsed != null ? t('waiting {n}').replace('{n}', fmtDur(elapsed)) : t('pending'),
        meta, iter,
      ].filter(Boolean).join(' · ')
    : [
        elapsed != null ? t('thinking {n}').replace('{n}', fmtDur(elapsed)) : t('thinking'),
        eta != null ? `~${fmtDur(Math.round(eta))}` : '',
        meta, iter,
      ].filter(Boolean).join(' · ')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        {/* laufend: gefüllter, pulsierender Punkt. wartend: hohler gestrichelter Ring. */}
        {pending ? (
          <span style={{
            width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
            background: 'transparent', border: '1.5px dashed var(--text-muted, #8b949e)',
            boxSizing: 'border-box',
          }} />
        ) : (
          <span className="player-task-pulse" style={{
            width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
            background: 'var(--accent, #6aa9ff)',
          }} />
        )}
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em', opacity: pending ? 0.7 : 1 }}>
          {title}
        </span>
      </div>
      <div style={{ paddingLeft: 16, fontSize: '0.72em', opacity: pending ? 0.45 : 0.6, lineHeight: 1.3,
                    fontVariantNumeric: 'tabular-nums', wordBreak: 'break-word',
                    fontStyle: pending ? 'italic' : 'normal' }}>
        {sub}
      </div>
    </div>
  )
}

function RecentRow({ r }: { r: RecentTaskInfo }) {
  const { t } = useI18n()
  const failed = (r.status || '') === 'failed'
  const cancelled = (r.status || '') === 'cancelled'
  const icon = failed ? '✗' : cancelled ? '⊘' : '✓'
  const color = failed ? '#e05656' : cancelled ? 'var(--text-muted, #8b949e)' : '#3fa45a'
  const title = r.label || (r.agent_name || r.task_type || t('Task'))
  const dur = r.duration_s != null ? fmtDur(Math.round(r.duration_s)) : ''
  const meta = [dur, r.provider, r.model].filter(Boolean).join(' · ')
  return (
    <div title={r.error || ''}
      style={{ display: 'flex', alignItems: 'baseline', gap: 6, fontSize: '0.74em', opacity: 0.7 }}>
      <span style={{ color, flex: '0 0 auto' }}>{icon}</span>
      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {title}
      </span>
      {meta ? (
        <span style={{ flex: '0 0 auto', opacity: 0.8, fontVariantNumeric: 'tabular-nums' }}>{meta}</span>
      ) : null}
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
  const { llmTasks, pendingLLM, trackedTasks, recent, channels } = useQueue(2000)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [showRecent, setShowRecent] = useState(false)

  // Sekündlicher Tick, solange irgendwas mit mitlaufender Dauer/Wartezeit
  // angezeigt wird (laufende + wartende LLM-Calls + getrackte Tasks).
  const anyLive = llmTasks.length > 0 || pendingLLM.length > 0 || trackedTasks.length > 0
  useEffect(() => {
    if (!anyLive) return
    const id = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [anyLive])

  const hasTasks = llmTasks.length > 0 || pendingLLM.length > 0 || trackedTasks.length > 0

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
                {ch.running > 0 || ch.waiting > 0 ? (
                  <span style={{ opacity: 0.55, fontVariantNumeric: 'tabular-nums' }}>
                    {ch.running > 0 ? `▶${ch.running}` : ''}
                    {ch.running > 0 && ch.waiting > 0 ? ' ' : ''}
                    {ch.waiting > 0 ? `⏳${ch.waiting}` : ''}
                  </span>
                ) : null}
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
      {llmTasks.length > 0 || pendingLLM.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {llmTasks.map((tk, i) => <LLMRow key={tk.task_id || `llm${i}`} tk={tk} nowMs={nowMs} />)}
          {pendingLLM.map((tk, i) => <LLMRow key={tk.task_id || `pllm${i}`} tk={tk} nowMs={nowMs} pending />)}
        </div>
      ) : null}
      {(llmTasks.length > 0 || pendingLLM.length > 0) && trackedTasks.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }} />
      )}
      {trackedTasks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {trackedTasks.map((tk, i) => <TrackedRow key={tk.task_id || `trk${i}`} tk={tk} nowMs={nowMs} />)}
        </div>
      )}
      {recent.length > 0 && (
        <div style={{ marginTop: 2 }}>
          <button
            onClick={() => setShowRecent((v) => !v)}
            style={{
              background: 'none', border: 0, padding: 0, cursor: 'pointer', color: 'inherit',
              opacity: 0.55, fontSize: '0.78em',
            }}
          >
            {showRecent ? '▾' : '▸'} {t('Recently')} ({recent.length})
          </button>
          {showRecent && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 4 }}>
              {recent.map((r, i) => <RecentRow key={r.task_id || `rec${i}`} r={r} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
