/**
 * PropCreateForm — the "new prop" form of the prop library: generate the
 * object from a product-shot render (use case "prop") → img2mesh, or create
 * the bare record and upload a GLB later.
 *
 * The final render prompt is assembled here and shown in full (final-prompt
 * rule): use-case style + object subject, both editable. The weaving itself is
 * the shared `composePropPrompt`, so this form and the render dialog send the
 * same text the server would compose — and the 3D-asset framing ("A
 * high-quality 3D model of …, designed for 3D asset generation, 8k
 * resolution") stays where it lives, in the "prop" use-case style.
 */
import { useCallback, useEffect, useState } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { CATEGORY_DATALIST_ID, composePropPrompt } from './propTypes'
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
  // Per-run mesh overrides (empty = the picked backend's defaults) — the
  // same pair every 3D generate dialog offers.
  const [faceDraft, setFaceDraft] = useState('')
  const [texSize, setTexSize] = useState('')
  const [style, setStyle] = useState('')
  const [negative, setNegative] = useState('')
  const [styleTouched, setStyleTouched] = useState(false)

  const imageBackendInfo = imageBackends.find((b) => b.name === imageBackend) || imageBackends[0]
  // 0 = no cap. Above its cap such a backend does not fail, it HANGS.
  const faceLimit = meshBackends.find((b) => b.name === meshBackend)?.face_num_max || 0

  // The final prompt = the use-case style of the chosen image backend + the
  // object subject (description, else the name). Style is its OWN editable
  // field (final-prompt rule); manual edits stick.
  useEffect(() => {
    if (styleTouched) return
    setStyle(imageBackendInfo?.prompt_style || '')
    setNegative(imageBackendInfo?.prompt_negative || '')
  }, [imageBackendInfo, styleTouched])

  // The shared weaver, the same one the render dialog uses: the style owns the
  // wording (including the 3D-asset framing and its {subject} slot), this form
  // only supplies the object. Nothing about the framing is written here — it
  // would end up in the final prompt twice.
  const subject = (description.trim() || name.trim())
  const finalPrompt = composePropPrompt(style, subject)

  // One approximate size creates a placeholder cube — the three dims refine
  // themselves from the mesh proportions as soon as the model exists.
  const dimsPayload = () => {
    const n = parseFloat(sizeM)
    const v = Number.isFinite(n) && n > 0 ? n : 1
    return { width_m: v, depth_m: v, height_m: v }
  }

  const generate = useCallback(() => {
    if (!name.trim()) return
    void apiPost<{ status?: string; prop?: PropFull }>('/world/props/generate', {
      name: name.trim(), category: category.trim(), ...dimsPayload(),
      description: description.trim(),
      prompt: finalPrompt, negative,
      image_backend: imageBackendInfo?.name || '', mesh_backend: meshBackend,
      ...((): Record<string, number> => {
        const out: Record<string, number> = {}
        let f = parseInt(faceDraft, 10)
        const selected = meshBackends.find((x) => x.name === meshBackend)
        // A backend with a face limit HANGS above it instead of failing.
        const max = selected?.face_num_max || 0
        if (Number.isFinite(f) && max > 0 && f > max) f = max
        // Untouched prefill = the backend default — only a changed value is
        // a real per-run override.
        if (Number.isFinite(f) && f > 0 && f !== (selected?.face_num || 0)) out.face_num = f
        const tex = parseInt(texSize, 10)
        if (Number.isFinite(tex) && tex > 0) out.texture_size = tex
        return out
      })(),
    })
      .then((d) => {
        toast(t('Generating the prop…'))
        if (d?.prop?.id) onCreated(d.prop.id)
        onGenerating()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, category, sizeM, description, finalPrompt, negative, imageBackendInfo,
      meshBackend, meshBackends, faceDraft, texSize, onCreated, onGenerating, t, toast])

  const createEmpty = useCallback(() => {
    if (!name.trim()) return
    void apiPost<{ status?: string; prop?: PropFull }>('/world/props', {
      name: name.trim(), category: category.trim(), ...dimsPayload(),
      description: description.trim(),
    })
      .then((d) => {
        toast(t('Prop created — upload a GLB or generate its model.'))
        if (d?.prop?.id) onCreated(d.prop.id)
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, category, sizeM, description, onCreated, t, toast])

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
          <Field label={t('Approx. size (m)')} compact
            hint={t('Largest edge of the FIRST model variant — width/depth/height land on it and refine automatically from the model’s proportions once it exists. Every further variant gets its own size in the variant strip.')}>
            <input className="ga-input" type="number" min={0.05} step={0.05}
              style={{ width: 90 }}
              value={sizeM} onChange={(e) => setSizeM(e.target.value)} />
          </Field>
        </div>

        <Field label={t('Object description (subject)')}
          hint={t('Lands on the first model variant and feeds its render prompt — describe materials, colour, style. Empty = the name is used.')}>
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
              onChange={(e) => {
                setMeshBackend(e.target.value)
                const b = meshBackends.find((x) => x.name === e.target.value)
                setFaceDraft(b?.face_num ? String(b.face_num) : '')
              }}>
              <option value="">{t('— default (cheapest available) —')}</option>
              {meshBackends.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}{b.face_num ? ` · ${b.face_num.toLocaleString()} ${t('faces')}` : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('Face count')}
            hint={faceLimit
              ? `${t('Max')} ${faceLimit.toLocaleString()} — ${t('this backend hangs above its limit')}`
              : undefined}>
            <input className="ga-input" type="number" min={500}
              max={faceLimit || 100000}
              step={500} value={faceDraft} placeholder={t('backend default')}
              title={t('Target triangle count for THIS run — small deco needs far fewer faces than a character (2,000–20,000).')}
              onChange={(e) => setFaceDraft(e.target.value)} />
          </Field>
          <Field label={t('Texture size')}>
            <select className="ga-input" value={texSize}
              title={t('Sent as "input_texture_resolution" whenever the alias declares it.')}
              onChange={(e) => setTexSize(e.target.value)}>
              <option value="">{t('— backend default —')}</option>
              {[512, 1024, 2048].map((v) => (
                <option key={v} value={String(v)}>{v} × {v}</option>
              ))}
            </select>
          </Field>
        </div>

        <Field label={t('Style (use-case)')}
          hint={t('The “prop” use-case style of this backend. {subject} is where the object description is woven in — it carries the 3D-asset framing, so leave the placeholder in place. Without it the subject is appended at the end.')}>
          <textarea className="ga-textarea" rows={2} value={style}
            onChange={(e) => { setStyle(e.target.value); setStyleTouched(true) }} />
        </Field>
        {imageBackendInfo?.supports_negative_prompt === false ? (
          <div className="ga-form-hint">
            {t('This backend has no negative input — negations are part of the prompt above.')}
          </div>
        ) : (
          <Field label={t('Negative prompt')}>
            <textarea className="ga-textarea" rows={2} value={negative}
              onChange={(e) => { setNegative(e.target.value); setStyleTouched(true) }} />
          </Field>
        )}
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
