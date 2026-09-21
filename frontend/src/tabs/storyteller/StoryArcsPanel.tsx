import { useCallback, useEffect, useRef, useState } from 'react'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { clockSettings, formatDateTime } from '../../lib/clockFormat'
import { useToast } from '../../lib/Toast'

/**
 * Story arcs — the multi-character storylines the story engine generates in
 * the background and the player reads in the quest book. This is the admin
 * side of them: what exists, one by hand, and delete.
 *
 * `GET /queue/story-arc/status`, `POST /queue/story-arc/generate`,
 * `DELETE /queue/story-arc/{id}`. Generation is QUEUED (a background LLM job
 * on the `consolidation` task), so the button can only report that it was
 * handed in — the list is what says whether an arc came out of it. The engine
 * refuses on its own terms (cooldown, maximum active arcs), which is why the
 * hint below names them.
 *
 * `created_at` / `updated_at` are SYSTEM stamps (`utc_now_iso`), not world
 * time — they are rendered with the ordinary date formatter, not a calendar
 * label.
 */
interface StoryArc {
  id: string
  title?: string
  status?: string
  participants?: string[]
  beats?: unknown[]
  max_beats?: number
  tension?: number
  updated_at?: string
}

interface ArcStatus {
  total?: number
  active?: number
  resolved?: number
  arcs?: StoryArc[]
}

/** How long to wait before looking whether the queued job produced an arc. */
const REFRESH_AFTER_QUEUE_MS = 6000

export function StoryArcsPanel() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [data, setData] = useState<ArcStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<StoryArc | null>(null)
  const timer = useRef<number | null>(null)

  const reload = useCallback(async () => {
    try {
      setData(await apiGet<ArcStatus>('/queue/story-arc/status'))
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      setData({ arcs: [] })
    }
  }, [t, toast])

  useEffect(() => {
    void reload()
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [reload])

  const generate = useCallback(async () => {
    setBusy(true)
    try {
      await apiPost('/queue/story-arc/generate', {})
      toast(t('Arc generation queued — it runs as a background LLM job.'))
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => { void reload() }, REFRESH_AFTER_QUEUE_MS)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [reload, t, toast])

  const remove = useCallback(async (arc: StoryArc) => {
    setPendingDelete(null)
    try {
      await apiDelete(`/queue/story-arc/${encodeURIComponent(arc.id)}`)
      toast(t('Arc deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    await reload()
  }, [reload, t, toast])

  const arcs = data?.arcs || []

  return (
    <div style={{ marginTop: 24 }}>
      <div className="ga-section-header" style={{ marginBottom: 8 }}>
        {t('Story arcs')}
      </div>
      <div className="ga-form-hint" style={{ marginBottom: 12 }}>
        {t('Arcs are storylines across several characters: the engine writes a seed and adds a beat whenever the participants meet, and the player reads them spoiler-free in the quest book. Generating one is a background LLM job — the engine declines while its cooldown runs or the maximum number of active arcs is reached, so an arc does not have to appear.')}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm ga-btn-primary"
          disabled={busy}
          onClick={() => { void generate() }}
        >
          {busy ? t('Queuing…') : t('Generate arc')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          onClick={() => { void reload() }}
        >
          ↻ {t('Refresh')}
        </button>
        {data ? (
          <span className="ga-form-hint">
            {t('{n} arcs · {a} active · {r} resolved')
              .replace('{n}', String(data.total ?? arcs.length))
              .replace('{a}', String(data.active ?? 0))
              .replace('{r}', String(data.resolved ?? 0))}
          </span>
        ) : null}
      </div>
      {data === null ? (
        <div className="ga-loading">{t('Loading…')}</div>
      ) : arcs.length === 0 ? (
        <div className="ga-placeholder">{t('No story arcs yet.')}</div>
      ) : (
        <table className="ga-sched-table">
          <thead>
            <tr>
              <th>{t('Title')}</th>
              <th>{t('Status')}</th>
              <th>{t('Participants')}</th>
              <th>{t('Beats')}</th>
              <th>{t('Updated')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {arcs.map((arc) => (
              <tr key={arc.id}>
                <td>{arc.title || arc.id}</td>
                <td className={arc.status === 'active' ? 'ga-status-ok' : 'ga-status-paused'}>
                  {arc.status || '?'}
                </td>
                <td>{(arc.participants || []).join(', ')}</td>
                <td>
                  {(arc.beats || []).length}
                  {arc.max_beats ? ` / ${arc.max_beats}` : ''}
                </td>
                <td>{arc.updated_at
                  ? formatDateTime(arc.updated_at, clockSettings())
                  : ''}</td>
                <td className="ga-or-actions-col">
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => setPendingDelete(arc)}
                  >
                    {t('Delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ConfirmDialog
        open={!!pendingDelete}
        title={t('Delete story arc')}
        message={t('“{title}” and all its beats are gone. Memories the arc already wrote for its participants stay.')
          .replace('{title}', pendingDelete?.title || pendingDelete?.id || '')}
        confirmLabel={t('Delete')}
        danger
        onConfirm={() => { if (pendingDelete) void remove(pendingDelete) }}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  )
}
