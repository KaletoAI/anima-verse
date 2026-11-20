/**
 * "Build all open" under the character list's header (`app/core/figure_batch.py`): one click runs, for every
 * character with open work, first its base body and then its outfit Build — at most three characters at
 * once, on the SERVER (closing the browser does not stop it). Before it starts an in-app confirmation names
 * how many characters run and the estimated hub jobs (`GET /characters/build-all/preview`); while it runs a
 * progress line with Cancel (stops scheduling characters that have not begun); afterwards a summary whose
 * mouse-over lists what stayed open (reasons and 409 details come translated: every call sends `?lang=`). `onRunning` tells the list to re-read its open-step badges while the
 * run goes and once more when it ended.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ConfirmDialog, syncHub } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'

interface BatchRow { name: string; phase?: string; reason?: string; step?: string }
interface BatchStatus {
  running: boolean
  collecting: boolean
  cancel: boolean
  finished_at: string | null
  characters: BatchRow[]
  counts: Record<string, number>
  total: number
}
interface Preview {
  characters: { name: string; base: number; outfit: number; hub_jobs: number | null }[]
  hub_jobs: number | null
  media_generation_enabled: boolean
}

const RUNNING_POLL_MS = 3000

export function BuildAllOpenButton({ onRunning }: { onRunning: (running: boolean) => void }) {
  const { t, lang } = useI18n()
  const q = `?lang=${encodeURIComponent(lang)}`
  const [status, setStatus] = useState<BatchStatus | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const load = useCallback(() => {
    apiGet<BatchStatus>(`/characters/build-all${q}`).then(setStatus).catch(() => { /* keep the last answer */ })
  }, [q])
  useEffect(() => {
    load()
    return syncHub().onTopics(['generation'], load)
  }, [load])
  const running = !!status?.running
  useEffect(() => {
    if (!running) return
    const id = setInterval(load, RUNNING_POLL_MS)
    return () => clearInterval(id)
  }, [running, load])
  // Tell the list on every change — including the end, so it re-reads the badges one last time.
  const wasRunning = useRef(false)
  useEffect(() => {
    if (running !== wasRunning.current) {
      wasRunning.current = running
      onRunning(running)
    }
  }, [running, onRunning])

  const ask = async () => {
    setError('')
    setLoading(true)
    try {
      setPreview(await apiGet<Preview>('/characters/build-all/preview'))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  const startRun = async () => {
    setPreview(null)
    try {
      setStatus(await apiPost<BatchStatus>(`/characters/build-all/start${q}`, {}))
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const cancelRun = async () => {
    try {
      setStatus(await apiPost<BatchStatus>(`/characters/build-all/cancel${q}`, {}))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const count = (phase: string) => status?.counts?.[phase] || 0
  const open = (status?.characters || []).filter((r) => r.phase === 'failed' || r.phase === 'skipped')
  const n = preview?.characters.length || 0
  const jobs = preview?.hub_jobs
  const message = !preview ? ''
    : !preview.media_generation_enabled ? t('Media generation is switched off — switch it on first.')
      : n === 0 ? t('No character has open base body or outfit steps.')
        : t('{n} characters: first the base body, then the outfit, at most 3 characters at once.')
          .replace('{n}', String(n)) + ' '
          + (jobs === null || jobs === undefined ? t('hub jobs unknown')
            : t('About {n} hub jobs (estimate, retries extra).').replace('{n}', String(jobs)))
  const canStart = !!preview && preview.media_generation_enabled && n > 0

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4, marginBottom: 8 }}>
      <button type="button" className="ga-btn ga-btn-sm" disabled={running || loading} onClick={ask}
        title={t('Runs every character\'s open base body steps, then its outfit Build — 3 characters at once.')}>
        {running ? t('Building all…') : t('Build all open')}
      </button>
      {running || status?.finished_at || error ? (
        <div className="ga-muted" style={{ flexBasis: '100%', fontSize: 12 }}>
          {error ? <span style={{ color: 'var(--ga-danger, #c33)' }}>{error} </span> : null}
          {running ? (
            <>
              {status?.collecting ? t('Build all open: collecting characters…')
                : t('Build all open: {done} of {total} finished, {active} running')
                  .replace('{done}', String(count('done') + count('failed') + count('skipped')))
                  .replace('{total}', String(status?.total || 0))
                  .replace('{active}', String(count('base') + count('outfit')))}
              {status?.cancel ? ` · ${t('cancelling — running characters finish')}` : null}
              {!status?.cancel ? (
                <button type="button" className="ga-btn ga-btn-sm" style={{ marginLeft: 6 }} onClick={cancelRun}>
                  {t('Cancel')}
                </button>
              ) : null}
            </>
          ) : status?.finished_at ? (
            <span title={open.map((r) => `${r.name}: ${r.reason || r.phase}`).join('\n')}>
              {t('Build all open finished: {done} done, {failed} failed, {skipped} skipped')
                .replace('{done}', String(count('done')))
                .replace('{failed}', String(count('failed')))
                .replace('{skipped}', String(count('skipped')))}
            </span>
          ) : null}
        </div>
      ) : null}
      <ConfirmDialog open={preview !== null} title={t('Build all open?')} message={message}
        confirmLabel={canStart ? t('Build all open') : t('Close')}
        onConfirm={() => { if (canStart) { void startRun() } else { setPreview(null) } }}
        onClose={() => setPreview(null)} />
    </div>
  )
}
