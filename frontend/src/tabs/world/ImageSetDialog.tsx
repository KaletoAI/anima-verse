import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { type Location } from './worldTypes'

/**
 * ImageSetDialog — generates a whole image SET for one location with ONE
 * chosen backend/model: the location itself and/or every room, each as
 * day + night. Uses the existing batch endpoint
 * POST /world/locations/{id}/gallery/batch (sequential background jobs,
 * visible as tracks in the task panel).
 */
interface BackendOpt {
  name: string
  label: string
  category?: string
  models?: string[]
  default_model?: string
}

export function ImageSetDialog({ location, onClose }: {
  location: Location
  onClose: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [options, setOptions] = useState<BackendOpt[] | null>(null)
  const [backend, setBackend] = useState('')
  const [model, setModel] = useState('')
  const [incLocation, setIncLocation] = useState(true)
  const [incRooms, setIncRooms] = useState(true)
  const [incDay, setIncDay] = useState(true)
  const [incNight, setIncNight] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    apiGet<{ options?: BackendOpt[] }>('/world/imagegen-options')
      .then((d) => {
        // Inpaint backends are edit-only targets — not for set generation.
        const opts = (d.options || []).filter((o) => (o.category || '') !== 'inpaint')
        setOptions(opts)
        if (opts.length) setBackend(opts[0].name)
      })
      .catch(() => setOptions([]))
  }, [])

  const selected = useMemo(
    () => (options || []).find((o) => o.name === backend),
    [options, backend],
  )

  const rooms = location.rooms || []
  const jobs = useMemo(() => {
    const types = [
      ...(incDay ? (['day'] as const) : []),
      ...(incNight ? (['night'] as const) : []),
    ]
    const out: Array<{ label: string; prompt_type: string; room_id?: string }> = []
    for (const type of types) {
      if (incLocation) {
        out.push({ label: `${location.name} · ${type}`, prompt_type: type })
      }
      if (incRooms) {
        for (const r of rooms) {
          if (!r.id) continue
          out.push({ label: `${r.name || r.id} · ${type}`, prompt_type: type, room_id: r.id })
        }
      }
    }
    return out
  }, [incLocation, incRooms, incDay, incNight, location.name, rooms])

  const start = async () => {
    if (!jobs.length || submitting) return
    setSubmitting(true)
    try {
      const body: Record<string, unknown> = { jobs }
      if (backend) body.backend = backend
      if (model) body.model_override = model
      await apiPost(`/world/locations/${encodeURIComponent(location.id)}/gallery/batch`, body)
      toast(t('{n} image jobs started — watch the task panel').replace('{n}', String(jobs.length)))
      onClose()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setSubmitting(false)
    }
  }

  const check = (label: string, val: boolean, set: (v: boolean) => void, disabled = false) => (
    <label className="ga-form-check" style={{ marginRight: 12 }}>
      <input type="checkbox" checked={val} disabled={disabled || submitting}
        onChange={(e) => set(e.target.checked)} />
      <span>{label}</span>
    </label>
  )

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !submitting) onClose() }}>
      <div className="ga-modal" role="dialog" aria-label={t('Generate image set')} style={{ maxWidth: 520 }}>
        <div className="ga-modal-header">
          <span>🖼 {t('Generate image set')} — {location.name}</span>
          <button className="ga-modal-close" onClick={onClose} disabled={submitting} aria-label={t('Close')}>×</button>
        </div>
        <div className="ga-modal-body">
          {!options ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : !options.length ? (
            <div className="ga-form-hint">{t('No image backends available.')}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label className="ga-imagegen-label">{t('Backend')}</label>
              <select className="ga-input" value={backend} disabled={submitting}
                onChange={(e) => { setBackend(e.target.value); setModel('') }}>
                {options.map((o) => (
                  <option key={o.name} value={o.name}>{o.label}</option>
                ))}
              </select>
              {selected?.models?.length ? (
                <>
                  <label className="ga-imagegen-label">{t('Model')}</label>
                  <select className="ga-input" value={model} disabled={submitting}
                    onChange={(e) => setModel(e.target.value)}>
                    <option value="">— {t('backend default')} —</option>
                    {selected.models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </>
              ) : null}
              <label className="ga-imagegen-label">{t('Targets')}</label>
              <div>
                {check(t('Location'), incLocation, setIncLocation)}
                {check(t('All rooms ({n})').replace('{n}', String(rooms.length)), incRooms, setIncRooms, rooms.length === 0)}
              </div>
              <div>
                {check(t('Day'), incDay, setIncDay)}
                {check(t('Night'), incNight, setIncNight)}
              </div>
              <div className="ga-form-hint">
                {t('{n} images will be generated sequentially on the chosen backend.')
                  .replace('{n}', String(jobs.length))}
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button className="ga-btn ga-btn-sm" onClick={onClose} disabled={submitting}>
                  {t('Cancel')}
                </button>
                <button className="ga-btn ga-btn-sm ga-btn-primary" onClick={() => { void start() }}
                  disabled={submitting || !jobs.length}>
                  {submitting ? t('Starting…') : t('Generate {n} images').replace('{n}', String(jobs.length))}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
