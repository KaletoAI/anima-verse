/**
 * Create one improvement entry.
 *
 * Two steps in one dialog: pick a TYPE, then fill the parameters that type
 * declares. The fields are rendered from `params_schema` — this file knows
 * the five field KINDS, never a single improvement type. A new type on the
 * server shows up here without a line of frontend work; that is the whole
 * point of the schema.
 *
 * Before creating, "Preview candidates" asks the server what the entry would
 * actually work on. An entry whose parameters match nothing is the expensive
 * mistake here (it looks fine and does nothing), so the count is one click
 * away rather than a surprise after the first scan.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { apiGet } from '../../lib/api'
import { Field } from '../../components/Field'
import { createImprovement, previewImprovement } from './api'
import type { ImprovementType, ParamField, PreviewResult } from './types'

/** The bits of GET /world/imagegen-options this dialog needs. */
interface ImagegenOption {
  name: string
  label: string
  available?: boolean
  category?: string
}

/** The bits of GET /world/props this dialog needs. */
interface MeshBackendOption {
  name: string
}

export function NewImprovementDialog({
  open,
  types,
  onCreated,
  onClose,
}: {
  open: boolean
  types: ImprovementType[]
  /** The entry exists — the caller refetches and closes. */
  onCreated: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [typeId, setTypeId] = useState('')
  const [params, setParams] = useState<Record<string, string>>({})
  const [labelDraft, setLabelDraft] = useState('')
  const [labelTouched, setLabelTouched] = useState(false)
  const [mode, setMode] = useState('one_shot')
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [imageOptions, setImageOptions] = useState<ImagegenOption[] | null>(null)
  const [meshBackends, setMeshBackends] = useState<MeshBackendOption[] | null>(null)

  // Fresh state on every open — a dialog that reopens with the previous
  // entry's parameters half-filled is how a wrong entry gets created.
  useEffect(() => {
    if (!open) return
    setTypeId('')
    setParams({})
    setLabelDraft('')
    setLabelTouched(false)
    setMode('one_shot')
    setPreview(null)
    setBusy(false)
  }, [open])

  // The backend lists are only needed once the dialog is on screen, and only
  // for the field kinds that ask for them — but they are two small calls, so
  // they load together when the dialog first opens rather than per field.
  useEffect(() => {
    if (!open) return
    if (imageOptions === null) {
      apiGet<{ options?: ImagegenOption[] }>('/world/imagegen-options')
        .then((d) => setImageOptions(d.options || []))
        .catch(() => setImageOptions([]))
    }
    if (meshBackends === null) {
      apiGet<{ mesh_backends?: MeshBackendOption[] }>('/world/props')
        .then((d) => setMeshBackends(d.mesh_backends || []))
        .catch(() => setMeshBackends([]))
    }
  }, [open, imageOptions, meshBackends])

  const type = useMemo(
    () => types.find((x) => x.id === typeId) || null, [types, typeId])

  // Inpaint targets belong to the Map-Fit/Match-Edges dialogs, never to a
  // normal render; available backends sort first, offline ones keep the
  // server's own "(offline?)" label.
  const imageEntries = useMemo(() => {
    const list = (imageOptions || []).filter((o) => o.category !== 'inpaint')
    return [...list.filter((o) => o.available !== false),
            ...list.filter((o) => o.available === false)]
  }, [imageOptions])

  /** Type label plus the chosen values — a name the list can be read by. */
  const defaultLabel = useMemo(() => {
    if (!type) return ''
    const values = type.params_schema
      .map((f) => params[f.key] || '')
      .filter(Boolean)
    return values.length ? `${type.label}: ${values.join(', ')}` : type.label
  }, [params, type])

  const label = labelTouched ? labelDraft : defaultLabel

  const setParam = useCallback((key: string, value: string) => {
    setParams((prev) => ({ ...prev, [key]: value }))
    // The parameters ARE the preview's question — a changed answer invalidates
    // a count that is now about something else.
    setPreview(null)
  }, [])

  const pickType = useCallback((nextId: string) => {
    setTypeId(nextId)
    setParams({})
    setPreview(null)
  }, [])

  const missing = (type?.params_schema || [])
    .some((f) => f.required && !(params[f.key] || '').trim())

  const runPreview = useCallback(async () => {
    if (!type) return
    setBusy(true)
    try {
      setPreview(await previewImprovement(type.id, params))
    } catch (e) {
      setPreview(null)
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [params, t, toast, type])

  const create = useCallback(async () => {
    if (!type) return
    setBusy(true)
    try {
      await createImprovement({ type_id: type.id, label, mode, params })
      toast(t('Improvement created'))
      onCreated()
    } catch (e) {
      // The server's message is the TYPE's own validation text ("source and
      // target backend must differ") — it says what to change, so it travels
      // to the user unshortened.
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [label, mode, onCreated, params, t, toast, type])

  if (!open) return null

  const renderField = (field: ParamField) => {
    const value = params[field.key] || ''
    const onChange = (v: string) => setParam(field.key, v)
    switch (field.kind) {
      case 'enum':
      case 'subject_kind':
        return (
          <select className="ga-input" value={value}
            onChange={(e) => onChange(e.target.value)}>
            <option value="">{t('— select —')}</option>
            {field.options.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        )
      case 'mesh_backend':
        return (
          <select className="ga-input" value={value}
            onChange={(e) => onChange(e.target.value)}>
            <option value="">{t('— select —')}</option>
            {(meshBackends || []).map((b) => (
              <option key={b.name} value={b.name}>{b.name}</option>
            ))}
          </select>
        )
      case 'image_backend':
        return (
          <select className="ga-input" value={value}
            onChange={(e) => onChange(e.target.value)}>
            <option value="">{t('— select —')}</option>
            {imageEntries.map((o) => (
              <option key={o.name} value={o.name}>{o.label || o.name}</option>
            ))}
          </select>
        )
      default:
        return (
          <input className="ga-input" value={value}
            onChange={(e) => onChange(e.target.value)} />
        )
    }
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div className="ga-modal" role="dialog" aria-label={t('New improvement')}
        style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('New improvement')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-form">
            <Field label={t('Type')}>
              <select className="ga-input" value={typeId}
                onChange={(e) => pickType(e.target.value)}>
                <option value="">{t('— select —')}</option>
                {types.map((x) => (
                  <option key={x.id} value={x.id}>{x.label}</option>
                ))}
              </select>
            </Field>

            {type ? (
              <>
                {type.params_schema.map((field) => (
                  <Field key={field.key} label={field.label}>
                    {renderField(field)}
                  </Field>
                ))}

                <Field label={t('Label')}
                  hint={t('The name this entry carries in the queue.')}>
                  <input className="ga-input" value={label}
                    onChange={(e) => {
                      setLabelTouched(true)
                      setLabelDraft(e.target.value)
                    }} />
                </Field>

                <Field label={t('Mode')}
                  hint={t('A one-shot entry closes when its candidates are done; a standing one keeps scanning for new ones.')}>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <input type="radio" name="imp-mode"
                        checked={mode === 'one_shot'}
                        onChange={() => setMode('one_shot')} />
                      <span>{t('One-shot')}</span>
                    </label>
                    <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <input type="radio" name="imp-mode"
                        checked={mode === 'standing'}
                        onChange={() => setMode('standing')} />
                      <span>{t('Standing')}</span>
                    </label>
                  </div>
                </Field>

                <div className="ga-imp-preview">
                  <button type="button" className="ga-btn ga-btn-sm"
                    disabled={busy || missing} onClick={runPreview}>
                    {t('Preview candidates')}
                  </button>
                  {preview ? (
                    <>
                      <div className="ga-form-hint">
                        {t('{n} candidates').replace('{n}',
                          String(preview.count))}
                      </div>
                      {preview.sample.length ? (
                        <ul className="ga-imp-preview-list">
                          {/* Candidate labels are not unique (two characters
                              may share a name) — the position is. */}
                          {preview.sample.map((s, i) => (
                            <li key={`${i}:${s}`}>{s}</li>
                          ))}
                        </ul>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        </div>
        <div className="ga-modal-footer"
          style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Cancel')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={!type || busy || missing} onClick={create}>
            {t('Create')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
