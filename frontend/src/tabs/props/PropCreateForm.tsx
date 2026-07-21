/**
 * PropCreateForm — the "new prop" form of the prop library: generate the
 * object from a product-shot render (use case "prop") → img2mesh, or create
 * the bare record and upload a GLB later.
 *
 * The final render prompt is assembled here and shown in full (final-prompt
 * rule): use-case style + object subject, both editable.
 */
import { useCallback, useEffect, useState } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { CATEGORY_DATALIST_ID } from './propTypes'
import type { ImageBackendInfo, MeshBackendInfo, PropFull } from './propTypes'

export function PropCreateForm({ imageBackends, meshBackends, onCreated, onGenerating, onCancel }: {
  imageBackends: ImageBackendInfo[]
  meshBackends: MeshBackendInfo[]
  /** A prop record now exists — select it in the list. */
  onCreated: (id: string) => void
  /** A generation was kicked off — the container starts polling. */
  onGenerating: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [sizeM, setSizeM] = useState('1')
  const [imageBackend, setImageBackend] = useState('')
  const [meshBackend, setMeshBackend] = useState('')
  const [style, setStyle] = useState('')
  const [negative, setNegative] = useState('')
  const [styleTouched, setStyleTouched] = useState(false)

  const imageBackendInfo = imageBackends.find((b) => b.name === imageBackend) || imageBackends[0]

  // The final prompt = the use-case style of the chosen image backend + the
  // object subject (description, else the name). Style is its OWN editable
  // field (final-prompt rule); manual edits stick.
  useEffect(() => {
    if (styleTouched) return
    setStyle(imageBackendInfo?.prompt_style || '')
    setNegative(imageBackendInfo?.prompt_negative || '')
  }, [imageBackendInfo, styleTouched])

  const subject = (description.trim() || name.trim())
  const finalPrompt = style.trim()
    ? (subject ? `${style.trim()}, ${subject}` : style.trim())
    : subject

  const sizeValue = () => {
    const n = parseFloat(sizeM)
    return Number.isFinite(n) && n > 0 ? n : 1
  }

  const generate = useCallback(() => {
    if (!name.trim()) return
    void apiPost<{ status?: string; prop?: PropFull }>('/world/props/generate', {
      name: name.trim(), category: category.trim(), size_m: sizeValue(),
      prompt: finalPrompt, negative,
      image_backend: imageBackendInfo?.name || '', mesh_backend: meshBackend,
    })
      .then((d) => {
        toast(t('Generating the prop…'))
        if (d?.prop?.id) onCreated(d.prop.id)
        onGenerating()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, category, sizeM, finalPrompt, negative, imageBackendInfo, meshBackend,
      onCreated, onGenerating, t, toast])

  const createEmpty = useCallback(() => {
    if (!name.trim()) return
    void apiPost<{ status?: string; prop?: PropFull }>('/world/props', {
      name: name.trim(), category: category.trim(), size_m: sizeValue(),
    })
      .then((d) => {
        toast(t('Prop created — upload a GLB or generate its model.'))
        if (d?.prop?.id) onCreated(d.prop.id)
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, category, sizeM, onCreated, t, toast])

  return (
    <>
      <DetailToolbar title={t('New prop')} onCancel={onCancel} />
      <form className="ga-form" onSubmit={(e) => e.preventDefault()}>
        <div className="ga-form-row">
          <Field label={t('Name')}>
            <input className="ga-input" value={name}
              placeholder={t('e.g. Oak dining chair')}
              onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t('Category')}>
            <input className="ga-input" list={CATEGORY_DATALIST_ID} value={category}
              placeholder={t('chair, table, …')}
              onChange={(e) => setCategory(e.target.value)} />
          </Field>
          <Field label={t('Size (m)')} compact
            hint={t('Largest real edge in metres — the mesh loses its scale, so the client sizes the object by this.')}>
            <input className="ga-input" type="number" min={0.05} step={0.05}
              style={{ width: 90 }}
              value={sizeM} onChange={(e) => setSizeM(e.target.value)} />
          </Field>
        </div>

        <Field label={t('Object description (subject)')}
          hint={t('Defaults to the name — describe materials, colour, style.')}>
          <input className="ga-input" value={description}
            onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <div className="ga-form-row">
          <Field label={t('Image backend (render)')}>
            <select className="ga-input" value={imageBackendInfo?.name || ''}
              onChange={(e) => { setImageBackend(e.target.value); setStyleTouched(false) }}>
              {imageBackends.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
            </select>
          </Field>
          <Field label={t('Mesh backend (img2mesh)')}>
            <select className="ga-input" value={meshBackend}
              onChange={(e) => setMeshBackend(e.target.value)}>
              <option value="">{t('— default (cheapest available) —')}</option>
              {meshBackends.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}{b.face_num ? ` · ${b.face_num.toLocaleString()} ${t('faces')}` : ''}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label={t('Style (use-case)')}>
          <textarea className="ga-textarea" rows={2} value={style}
            onChange={(e) => { setStyle(e.target.value); setStyleTouched(true) }} />
        </Field>
        <Field label={t('Negative prompt')}>
          <textarea className="ga-textarea" rows={2} value={negative}
            onChange={(e) => { setNegative(e.target.value); setStyleTouched(true) }} />
        </Field>
        <Field label={t('Final prompt (sent to the render)')}>
          <textarea className="ga-textarea" rows={2} value={finalPrompt} readOnly
            style={{ opacity: 0.85 }} />
        </Field>

        <div className="ga-form-row">
          <button type="button" className="ga-btn ga-btn-primary"
            disabled={!name.trim() || !meshBackends.length || !imageBackends.length}
            onClick={generate}>
            {t('Generate')}
          </button>
          <button type="button" className="ga-btn"
            disabled={!name.trim()}
            onClick={createEmpty}
            title={t('Create the record only — then upload a GLB in its detail panel.')}>
            {t('Create empty (upload later)')}
          </button>
        </div>
        {!meshBackends.length ? (
          <span className="ga-hint">
            {t('No img2mesh backend configured (api_type openai_mesh) — you can still create empty props and upload GLBs.')}
          </span>
        ) : null}
      </form>
    </>
  )
}
