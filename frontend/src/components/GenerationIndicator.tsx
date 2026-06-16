import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

/**
 * Kompakter Header-Indikator für laufende/wartende Generierungen (Bild/Video/
 * TTS/GPU-Tasks). Pollt /queue/status (gleiche Quelle wie das Player-TaskPanel)
 * und zeigt „▶ N / ⏳ M"; Tooltip listet die einzelnen Titel. Unsichtbar, wenn
 * nichts läuft.
 */
interface ActiveTask {
  task_id?: string
  label?: string
  task_type?: string
  status?: string
  provider?: string
  agent_name?: string
}

export function GenerationIndicator() {
  const { t } = useI18n()
  const [tasks, setTasks] = useState<ActiveTask[]>([])

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await apiGet<{ active_tasks?: ActiveTask[] }>('/queue/status')
        if (alive) setTasks(d.active_tasks || [])
      } catch { /* ignore — header indicator is best-effort */ }
    }
    tick()
    const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (!tasks.length) return null

  const running = tasks.filter((x) => (x.status || '') === 'running')
  const pending = tasks.filter((x) => (x.status || '') === 'pending')
  const tip = tasks
    .map((x) => `${x.status === 'running' ? '▶' : '⏳'} ${x.label || x.task_type || 'Task'}`
      + (x.agent_name ? ` (${x.agent_name})` : '')
      + (x.provider ? ` · ${x.provider}` : ''))
    .join('\n')

  return (
    <span
      title={tip}
      aria-label={t('Generations in progress')}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: '0.82em',
        padding: '2px 9px', borderRadius: 12, cursor: 'default',
        border: '1px solid var(--border, #30363d)', background: 'var(--bg, #0d1117)',
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: '50%', flex: '0 0 auto',
        background: running.length ? 'var(--accent, #6aa9ff)' : 'var(--text-muted, #8b949e)',
      }} />
      {running.length > 0 ? <span>▶ {running.length}</span> : null}
      {pending.length > 0 ? <span style={{ opacity: 0.65 }}>⏳ {pending.length}</span> : null}
    </span>
  )
}
