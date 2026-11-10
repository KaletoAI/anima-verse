/**
 * MeshJobFetch — "Fetch finished job…" on the mesh row of a garment's steps
 * (Wardrobe clothing + footwear, the Hair tab's views → mesh and subtract
 * source mesh): a mesh job that outlived our own poll (a timeout, a server
 * restart) but finished on the gateway is collected by its id. POST `url`
 * {job_id} (server `garments.collect_mesh_job`): the delivered mesh goes
 * through the step's own prepare + gate and record; nothing else runs — the
 * next run reuses it. Same look and texts as the character model's
 * "Fetch by job ID…" (FieldModel3D); the answer stays on an inline line.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { ERROR_STYLE, WARN_STYLE } from './garmentStyle'

interface FetchAnswer {
  status?: string
  job_id?: string
  progress?: number | null
  error?: string
}

export function MeshJobFetch({ url, disabled, onDone }: {
  /** POST /characters/{c}/garments/{item}/mesh/fetch (footwear: …/footwear/mesh/fetch); null hides it. */
  url: string | null
  disabled?: boolean
  /** The step's record changed (accepted or refused): reload the panel. */
  onDone: () => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [jobId, setJobId] = useState('')
  const [pending, setPending] = useState(false)
  const [result, setResult] = useState<{ text: string; tone: 'ok' | 'warn' | 'error' } | null>(null)
  if (!url) return null

  const fetchJob = async () => {
    const id = jobId.trim()
    if (!id || pending || disabled) return
    setPending(true)
    setResult(null)
    try {
      const d = await apiPost<FetchAnswer>(url, { job_id: id })
      if (d.status === 'accepted') {
        setResult({ text: `${t('Accepted')} · ${t('job')} ${d.job_id || id}`, tone: 'ok' })
        setJobId('')
        onDone()
      } else if (d.status === 'refused') {
        setResult({ text: `${t('Refused')} · ${t('job')} ${d.job_id || id}${d.error ? `: ${d.error}` : ''}`, tone: 'error' })
        onDone()
      } else {
        const pct = typeof d.progress === 'number' ? ` — ${Math.round(d.progress * 100)} %` : ''
        setResult({
          text: `${d.status === 'queued' ? t('Job is still queued on the gateway') : t('Job is still running on the gateway')}${pct}`,
          tone: 'warn',
        })
      }
    } catch (e) {
      setResult({ text: `${t('Error')}: ${(e as Error).message}`, tone: 'error' })
    } finally {
      setPending(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flexBasis: '100%', minWidth: 0 }}>
      <div>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${open ? ' ga-btn-primary' : ''}`}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          title={t('Collects a mesh job that finished on the gateway after the generation here gave up waiting — by the job id from the log.')}
        >
          {t('Fetch finished job…')}
        </button>
      </div>
      {open ? (
        <>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="ga-input"
              style={{ flex: '1 1 12rem', minWidth: 0 }}
              value={jobId}
              placeholder={t('Job ID, e.g. 466a4e41b73d')}
              aria-label={t('Job ID')}
              disabled={pending}
              onChange={(e) => {
                setJobId(e.target.value)
                setResult(null)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void fetchJob()
              }}
            />
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={pending || disabled || !jobId.trim()}
              aria-busy={pending || undefined}
              onClick={() => { void fetchJob() }}
            >
              {pending ? t('Fetching…') : t('Fetch')}
            </button>
          </div>
          {result ? (
            <div className="ga-hint" role="status" style={{
              ...(result.tone === 'error' ? ERROR_STYLE : result.tone === 'warn' ? WARN_STYLE : {}),
              overflowWrap: 'anywhere',
            }}>
              {result.text}
            </div>
          ) : (
            <div className="ga-hint">
              {t('Stored as this step’s mesh and gated like a new one; the steps after it run on the next run. A job that is still running changes nothing — try again once it is done.')}
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}
