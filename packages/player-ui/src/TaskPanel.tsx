/**
 * TaskPanel — the system task / queue display (plan-room-conversation phase 3).
 *
 * Two groups out of GET /queue/status (via useQueue):
 *   • LLM calls (providers[*].chat_active) — the "X is thinking …" entries
 *     with label, model, running duration, estimate and iteration.
 *   • Tracked tasks (active_tasks) — image/video/TTS/GPU jobs.
 * Polled every 3 s; the running duration ticks locally once a second.
 * Two actions, everything else is display: CANCEL on a running/waiting row
 * (A6), and RETRY on a failed row of the persistent queue — the only rows a
 * worker can really pick up again (see RecentRow).
 */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiDelete, apiPost } from './api'
import { useI18n } from './I18nProvider'
import { useQueue, elapsedSeconds, type LLMTaskInfo, type TrackedTaskInfo, type RecentTaskInfo } from './useQueue'
import { EmptyState } from './EmptyState'
import { Icon, type IconName } from './icons'
import { formatTime } from './clockFormat'
import { clockSettings, useClockSettings } from './clockSettings'

/**
 * Cancel button of a running/waiting row (A6 of
 * plan-room-conversation-ergaenzungsplan.md). One click is enough — no
 * confirmation dialog: a cancelled task can be started again, and a modal for
 * every small thing costs more than the rare misclick.
 *
 * After the click the row stays and fades until the 3-s poll clears it — that
 * is the feedback. When it comes back (the task was already done or unknown),
 * the button is active again. A refusal with a reason (409: a CPU re-fit that
 * is computing cannot be stopped) is shown above the list.
 */
function CancelBtn({ onCancel, busy }: { onCancel: () => void; busy: boolean }) {
  const { t } = useI18n()
  return (
    <button type="button" onClick={onCancel} disabled={busy}
      title={busy ? t('Cancelling…') : t('Cancel task')}
      aria-label={busy ? t('Cancelling…') : t('Cancel task')}
      style={{
        flex: '0 0 auto', background: 'none', border: 'none', padding: '0 2px',
        color: 'var(--text-muted, #8b949e)', cursor: busy ? 'default' : 'pointer',
        opacity: busy ? 0.4 : 0.7, display: 'flex', alignItems: 'center',
      }}>
      <Icon name="close" size={12} />
    </button>
  )
}

function fmtDur(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

function LLMRow({ tk, nowMs, pending, onCancel, cancelling }: {
  tk: LLMTaskInfo; nowMs: number; pending?: boolean;
  onCancel?: (id: string) => void; cancelling?: boolean;
}) {
  const { t } = useI18n()
  // started_at is set only when processing starts; chat_active tasks often do
  // not have it (yet) → created_at (registration time) as the fallback, so the
  // time runs from the start. Waiting calls only have created_at.
  const elapsed = elapsedSeconds(pending ? tk.created_at : (tk.started_at || tk.created_at), nowMs)
  const eta = tk.estimated_duration_s && tk.estimated_duration_s > 0 ? tk.estimated_duration_s : null
  const iter = tk.iteration && tk.iteration > 0 ? `iter ${tk.iteration}/${tk.max_iterations || 1}` : ''
  const meta = [tk.provider_name, tk.model].filter(Boolean).join(' / ')
  const title = tk.label || (tk.agent_name ? `${tk.agent_name}` : tk.task_type || t('LLM call'))
  // Second line (status · duration · provider · iteration) — as wrapping text,
  // so it stays readable in a narrow panel instead of being cut off.
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
        {/* running: a filled, pulsing dot. waiting: a hollow dashed ring. */}
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
        {onCancel && tk.task_id ? (
          <CancelBtn busy={!!cancelling} onCancel={() => onCancel(tk.task_id as string)} />
        ) : null}
      </div>
      <div style={{ paddingLeft: 16, fontSize: '0.72em', opacity: pending ? 0.45 : 0.6, lineHeight: 1.3,
                    fontVariantNumeric: 'tabular-nums', wordBreak: 'break-word',
                    fontStyle: pending ? 'italic' : 'normal' }}>
        {sub}
      </div>
    </div>
  )
}

/**
 * A finished row of the "Recently" block.
 *
 * A FAILED row gets a Retry when the server says it is retryable — that is
 * true for the persistent TaskQueue's own rows only (see collectRecent in
 * useQueue): an LLM call from the provider ring has no row to reset, and a
 * tracked GPU/image job would be reset to pending without any worker ever
 * dequeuing it. Permission-wise Retry sits exactly where Cancel sits: /queue
 * is not an admin prefix, so a logged-in player reaches both.
 */
function RecentRow({ r, onRetry, retrying }: {
  r: RecentTaskInfo; onRetry?: (id: string) => void; retrying?: boolean;
}) {
  const { t } = useI18n()
  const failed = (r.status || '') === 'failed'
  const cancelled = (r.status || '') === 'cancelled'
  const icon = failed ? '✗' : cancelled ? '⊘' : '✓'
  const color = failed ? '#e05656' : cancelled ? 'var(--text-muted, #8b949e)' : '#3fa45a'
  const title = r.label || (r.agent_name || r.task_type || t('Task'))
  const dur = r.duration_s != null ? fmtDur(Math.round(r.duration_s)) : ''
  // Time of day of the entry — created_at is a UTC ISO stamp from the server,
  // rendered in the configured world timezone and clock format. A row of the
  // persistent queue carries completed_at instead; it is finished either way.
  const clock = formatTime(r.created_at || r.completed_at, clockSettings())
  const meta = [clock, dur, r.provider, r.model].filter(Boolean).join(' · ')
  // Two lines like LLMRow/TrackedRow: the title with an ellipsis, the meta below
  // with wordBreak — in a narrow panel the meta line wraps instead of overlapping
  // the title.
  return (
    <div title={r.error || ''}
      style={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: '0.74em', opacity: 0.7 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ color, flex: '0 0 auto' }}>{icon}</span>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {title}
        </span>
        {r.retryable && onRetry && r.task_id ? (
          <button type="button" onClick={() => onRetry(r.task_id as string)} disabled={!!retrying}
            title={retrying ? t('Retrying…') : t('Retry task')}
            aria-label={retrying ? t('Retrying…') : t('Retry task')}
            style={{
              flex: '0 0 auto', border: '1px solid rgba(255,255,255,0.25)',
              background: 'rgba(255,255,255,0.06)', color: 'inherit',
              borderRadius: 6, padding: '0 6px', fontSize: '0.95em',
              cursor: retrying ? 'default' : 'pointer', opacity: retrying ? 0.4 : 0.85,
            }}>
            {t('Retry')}
          </button>
        ) : null}
      </div>
      {meta ? (
        <div style={{ paddingLeft: 14, fontSize: '0.94em', opacity: 0.8, lineHeight: 1.3,
                      fontVariantNumeric: 'tabular-nums', wordBreak: 'break-word' }}>
          {meta}
        </div>
      ) : null}
    </div>
  )
}

function TrackedRow({ tk, nowMs, onCancel, cancelling }: {
  tk: TrackedTaskInfo; nowMs: number;
  onCancel?: (id: string) => void; cancelling?: boolean;
}) {
  const { t } = useI18n()
  const running = (tk.status || '') === 'running'
  const elapsed = elapsedSeconds(tk.started_at, nowMs)
  const waited = elapsedSeconds(tk.created_at, nowMs)
  const title = tk.label || tk.task_type || t('Task')
  // Second line like the LLM calls': status · duration · backend · agent.
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
        {/* running: a filled, pulsing dot (like LLM). pending: a hollow,
            dashed ring → waiting tasks clearly set apart. */}
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
        {onCancel && tk.task_id ? (
          <CancelBtn busy={!!cancelling} onCancel={() => onCancel(tk.task_id as string)} />
        ) : null}
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
  // Subscribe to the shared clock settings so the stamp helpers above
  // re-render once the server-configured format and timezone arrive.
  useClockSettings()
  const { t } = useI18n()
  // Shared /queue/status feed via the poll hub (one fetch, visibility pause,
  // error backoff). GenerationIndicator subscribes to the same key.
  const { llmTasks, pendingLLM, trackedTasks, recent, channels, refresh } = useQueue(3000)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [showRecent, setShowRecent] = useState(false)
  // Ids whose cancel is on its way out. ONE endpoint for both groups:
  // DELETE /queue/tasks/{id} tries the provider queue first and falls back to
  // the tracked tasks (app/routes/queue.py cancel_task) — the row need not know
  // which queue it sits in.
  const [cancelling, setCancelling] = useState<Record<string, boolean>>({})
  // The server's reason when it refuses a cancel (409, e.g. a CPU re-fit that is
  // computing) — English from the server, translated here; cleared by the next click.
  const [cancelRefused, setCancelRefused] = useState('')
  const cancel = useCallback(async (id: string) => {
    setCancelRefused('')
    setCancelling((c) => ({ ...c, [id]: true }))
    try {
      await apiDelete(`/queue/tasks/${encodeURIComponent(id)}`)
    } catch (err) {
      // Not found or already done: free the button again, the row then goes
      // away with the next poll on its own — or it does not. A refusal says why.
      if (err instanceof ApiError && err.status === 409) setCancelRefused(err.message)
      setCancelling((c) => { const n = { ...c }; delete n[id]; return n })
    }
  }, [])

  // Ids whose retry is in flight. POST /queue/tasks/item/{id}/retry puts a
  // FAILED row of the persistent queue back to pending; the snapshot is
  // refreshed right away so the row moves out of "Recently" without waiting
  // for the 3-s tick.
  const [retrying, setRetrying] = useState<Record<string, boolean>>({})
  const retry = useCallback(async (id: string) => {
    setRetrying((r) => ({ ...r, [id]: true }))
    try {
      await apiPost(`/queue/tasks/item/${encodeURIComponent(id)}/retry`, {})
      await refresh()
    } catch {
      // Gone or no longer failed: free the button again, the next poll decides.
    } finally {
      setRetrying((r) => { const n = { ...r }; delete n[id]; return n })
    }
  }, [refresh])

  // One-second UI clock (local, not a network poll) while anything with a
  // running duration / wait time is shown (running + pending LLM + tracked).
  const anyLive = llmTasks.length > 0 || pendingLLM.length > 0 || trackedTasks.length > 0
  useEffect(() => {
    if (!anyLive) return
    const id = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [anyLive])

  // Show all LLM providers, but only image backends that have a PROBLEM
  // (unhealthy) — healthy image backends stay hidden to declutter.
  const shownChannels = channels.filter((ch) => ch.kind === 'llm' || !ch.healthy)
  const hasTasks = llmTasks.length > 0 || pendingLLM.length > 0 || trackedTasks.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {shownChannels.length > 0 && (
        // Multi-column table: an auto-fill grid — as many columns as the panel
        // width holds; per cell status dot | name (ellipsis) | counter right-
        // aligned, so the columns line up like a table.
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
          gap: '3px 16px',
        }}>
          {shownChannels.map((ch) => {
            const state = ch.healthy ? (ch.busy ? t('busy') : t('available')) : t('unavailable')
            // Icon = type, colour = status (like the panel bar icons).
            const color = !ch.healthy ? '#e05656' : ch.busy ? 'var(--accent, #6aa9ff)' : '#3fa45a'
            const icon: IconName = ch.kind === 'llm' ? 'brain'
              : ch.type === 'a1111' ? 'sliders'
              : 'cloud'  // civitai / together / openai_chat / openai_diffusion (cloud/OpenAI APIs)
            const typeName = ch.kind === 'llm' ? t('LLM provider')
              : ch.type === 'civitai' ? 'CivitAI'
              : ch.type === 'together' ? 'Together.ai'
              : ch.type === 'openai_chat' ? 'OpenAI Chat'
              : ch.type === 'openai_diffusion' ? 'OpenAI Diffusion'
              : ch.type === 'a1111' ? 'Automatic1111'
              : t('Image backend')
            return (
              <span key={ch.key} title={`${typeName}${ch.group ? ` · Group ${ch.group}` : ''} · ${state}`}
                style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8em', minWidth: 0 }}>
                {/* Icon codiert den Typ, color (via currentColor) den Status. */}
                <span style={{ flex: '0 0 auto', color, display: 'flex' }}>
                  <Icon name={icon} size={14} />
                </span>
                <span style={{
                  flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  opacity: ch.healthy ? 0.85 : 0.55,
                  fontStyle: ch.kind === 'image' ? 'italic' : 'normal',
                }}>{ch.group ? <span style={{ opacity: 0.6 }}>({ch.group}) </span> : null}{ch.name}</span>
                {ch.running > 0 || ch.waiting > 0 ? (
                  <span style={{ flex: '0 0 auto', opacity: 0.55, fontVariantNumeric: 'tabular-nums' }}>
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
      {shownChannels.length > 0 && hasTasks && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }} />
      )}
      {cancelRefused && (
        <div role="alert" style={{ fontSize: '0.78em', color: '#e05656', lineHeight: 1.3 }}>
          {t(cancelRefused)}
        </div>
      )}
      {!hasTasks && (
        <EmptyState small icon="tasks" title={t('No active tasks')} />
      )}
      {llmTasks.length > 0 || pendingLLM.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {llmTasks.map((tk, i) => <LLMRow key={tk.task_id || `llm${i}`} tk={tk} nowMs={nowMs}
            onCancel={cancel} cancelling={!!cancelling[tk.task_id || '']} />)}
          {pendingLLM.map((tk, i) => <LLMRow key={tk.task_id || `pllm${i}`} tk={tk} nowMs={nowMs} pending
            onCancel={cancel} cancelling={!!cancelling[tk.task_id || '']} />)}
        </div>
      ) : null}
      {(llmTasks.length > 0 || pendingLLM.length > 0) && trackedTasks.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }} />
      )}
      {trackedTasks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {trackedTasks.map((tk, i) => <TrackedRow key={tk.task_id || `trk${i}`} tk={tk} nowMs={nowMs}
            onCancel={cancel} cancelling={!!cancelling[tk.task_id || '']} />)}
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
              {recent.map((r, i) => <RecentRow key={r.task_id || `rec${i}`} r={r}
                onRetry={retry} retrying={!!retrying[r.task_id || '']} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
