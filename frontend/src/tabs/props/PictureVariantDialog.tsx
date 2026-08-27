/**
 * PictureVariantDialog — hang pictures on the prop's key surfaces.
 *
 * A picture assignment IS a variant of the frame prop (D2): the server copies
 * the primary mesh and the values ride on the copy. So this dialog collects
 * exactly one thing — what each area shows — plus the name the variant is
 * listed under, and hands it over. It creates nothing and knows no route.
 *
 * One control per area, chosen by the area's KIND (R8, `AREA_KINDS`): a
 * `picture` panel gets the gallery picker, a `glass` pane the preset list of
 * @anima/scene-render (`MATERIAL_PRESETS` — a look no renderer draws must not
 * be offerable). An area whose kind this client does not know is listed and
 * left alone rather than silently dropped.
 *
 * THE LABEL IS THREE-VALUED (R10): untouched it is not sent at all, and the
 * server keeps (or derives) the name; edited it travels verbatim. Re-hanging a
 * picture must not rename the variant behind the admin's back.
 *
 * Rendered via `createPortal` to `document.body` — the prop detail sits inside
 * a scrolled grid panel, and a modal nested in it renders as a floating box
 * with nowhere to go.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { MATERIAL_PRESETS } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { ImagePicker } from './ImagePicker'
import { areaKindOf, type PropArea, type PropSlotValues } from './propTypes'

export function PictureVariantDialog({ open, title, areas, initial, initialLabel,
  busy, onSubmit, onClose }: {
  /** false = closed (nothing is rendered). */
  open: boolean
  /** Header line — "New picture variant", or the variant being edited. */
  title: string
  /** The prop's real areas; the dialog renders one control per entry. */
  areas: PropArea[]
  /** What is on them already (editing an existing variant), or the prop's
   *  defaults as the starting point for a new one. */
  initial?: PropSlotValues
  /** The variant's stored name ('' = none yet). */
  initialLabel?: string
  /** A request is in flight — the actions are locked, nothing is discarded. */
  busy?: boolean
  /** `label` is `undefined` while the field was never touched (R10). */
  onSubmit: (slotValues: PropSlotValues, label: string | undefined) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [values, setValues] = useState<PropSlotValues>({})
  const [label, setLabel] = useState('')
  const [labelTouched, setLabelTouched] = useState(false)

  // Re-arm per open — the dialog is mounted once and reused, so a second open
  // must not show the first one's pictures.
  useEffect(() => {
    if (!open) return
    setValues({ ...(initial || {}) })
    setLabel(initialLabel || '')
    setLabelTouched(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const set = (id: string, next: { image?: string; preset?: string } | null) => {
    setValues((cur) => {
      const merged: PropSlotValues = { ...cur }
      // An empty value is NO value: the key goes, so the area falls back to
      // the prop's default (and the server refuses an empty assignment as a
      // picture variant, which is the honest answer).
      if (next) merged[id] = next
      else delete merged[id]
      return merged
    })
  }

  const filled = Object.keys(values).length

  return createPortal(
    <div className="ga-modal-backdrop">
      <div className="ga-modal" role="dialog" aria-label={title}
        style={{ maxWidth: 620 }}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-form">
            {areas.length ? areas.map((area) => {
              const kind = areaKindOf(area.kind)
              const value = values[area.id]
              return (
                <div key={area.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label className="ga-hint">
                    {kind ? t(kind.label) : area.kind}
                    {' · '}{area.id}
                    {' · '}{`${area.size_m[0].toFixed(2)} × ${area.size_m[1].toFixed(2)} m`}
                  </label>
                  {area.kind === 'picture' ? (
                    <ImagePicker
                      value={value?.image || ''}
                      onChange={(url) => set(area.id, url ? { image: url } : null)}
                    />
                  ) : area.kind === 'glass' ? (
                    <select
                      className="ga-input" style={{ maxWidth: 180 }}
                      value={value?.preset || ''}
                      title={t('Which look this pane gets.')}
                      onChange={(e) => set(area.id,
                        e.target.value ? { preset: e.target.value } : null)}
                    >
                      <option value="">{t('None')}</option>
                      {MATERIAL_PRESETS.map((p) => (
                        <option key={p} value={p}>{p === 'glass' ? t('Glass') : p}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="ga-hint">
                      {t('This area kind is not editable in this admin build.')}
                    </span>
                  )}
                </div>
              )
            }) : (
              <span className="ga-hint">
                {t('This prop has no key areas yet — detect or draw one first.')}
              </span>
            )}
            <label className="ga-hint">{t('Name')}</label>
            <input
              className="ga-input" value={label}
              placeholder={t('from the picture file names')}
              title={t('How this variant is listed. Left untouched the server names it after the pictures on it.')}
              onChange={(e) => { setLabel(e.target.value); setLabelTouched(true) }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
                {t('Cancel')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
                disabled={!filled || !!busy}
                title={filled ? undefined
                  : t('Pick at least one picture — an empty assignment is a plain model variant, not a picture one.')}
                onClick={() => onSubmit(values, labelTouched ? label.trim() : undefined)}>
                {busy ? t('Saving…') : t('Save')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
