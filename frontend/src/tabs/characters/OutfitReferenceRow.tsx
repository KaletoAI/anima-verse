/**
 * OutfitReferenceRow — the Figure tab's "Reference image" step row of the outfit worn now (Ruling A74b), on top of the
 * Dressed views sub-tab. An outfit here is what the tab shows: the worn combination of clothing pieces with the
 * pieces worn open (`outfit_references.outfit_key`); its label is the saved outfit's name or the piece names.
 *
 * - Set: the picture small (a click enlarges it), "Pick from gallery" (a grid of the character's gallery), "Upload"
 *   (stored in the gallery, then picked) and "Clear" (an in-app confirmation — no native dialog). Saving only saves:
 *   nothing renders. While something is painted on the figure the dressed front is then an EDIT of that picture
 *   instead of the body's front, so it shows as due with its cost ("Due with the next Build — 2 image jobs"); with
 *   nothing painted the picture is stored but not used now, and the row says why.
 * - Unset: the views are made as before — an edit of the body's front, or a copy of the body shape's view.
 * - Other outfits with a reference image are listed under it (small picture, label, Clear).
 *
 * Backend (app/routes/figure.py): GET …/figure/outfit-reference, POST …/figure/outfit-reference {image},
 * POST …/figure/outfit-reference/upload (multipart `file`), DELETE …/figure/outfit-reference/{key}.
 */
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { thumbUrl, thumbWidth } from '@anima/player-ui'
import { RefImage } from './RefImage'
import { StepRowView } from './StepRows'
import { imageJobsTr } from './figureModel'
import { outfitReferenceRow } from './dressedViewsModel'
import type { OutfitReferenceInfo } from './dressedViewsModel'

const TILE_W = thumbWidth(96)

/** The character's gallery as a grid; a click picks the picture (GET /characters/{c}/images). */
function GalleryPickDialog({ character, onPick, onClose }: {
  character: string
  onPick: (filename: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [images, setImages] = useState<{ filename: string; url: string }[] | null>(null)
  useEffect(() => {
    apiGet<{ images?: string[]; urls?: string[] }>(`/characters/${encodeURIComponent(character)}/images`)
      .then((d) => setImages((d.images || []).map((f, i) => ({ filename: f, url: d.urls?.[i] || '' }))
        .filter((i) => i.url && !/\.(mp4|webm)$/i.test(i.filename))))
      .catch(() => setImages([]))
  }, [character])
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 720 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Pick the outfit’s reference image')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          {images == null ? <div className="ga-loading">{t('Loading…')}</div>
            : images.length === 0 ? <div className="ga-placeholder">{t('No images available.')}</div> : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))', gap: 8 }}>
                {images.map((img) => (
                  <button key={img.filename} type="button" className="ga-btn" style={{ padding: 2 }}
                    title={img.filename} onClick={() => onPick(img.filename)}>
                    <img src={thumbUrl(img.url, TILE_W)} alt={img.filename} loading="lazy" decoding="async"
                      style={{ width: '100%', aspectRatio: '1', objectFit: 'cover', display: 'block' }} />
                  </button>
                ))}
              </div>
            )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** The in-app confirmation of Clear (no native dialog). */
function ClearConfirm({ label, onConfirm, onClose }: { label: string; onConfirm: () => void; onClose: () => void }) {
  const { t } = useI18n()
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 420 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Clear the reference image?')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>{label}</div>
          <div className="ga-hint">{t('The picture stays in the gallery. Nothing renders now — the dressed views of this outfit are then due and made as before (an edit of the body’s front).')}</div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>{t('Cancel')}</button>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={onConfirm}>{t('Clear reference')}</button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function OutfitReferenceRow({ character, refreshKey, onChanged }: {
  character: string
  /** Changes when the figure changes (a Build ended, another outfit worn): read again. */
  refreshKey?: string
  /** After a save: the views and the plan read again (they turn due). */
  onChanged?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<OutfitReferenceInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [picking, setPicking] = useState(false)
  const [clearing, setClearing] = useState<{ key: string; label: string } | null>(null)

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<OutfitReferenceInfo>(`/characters/${enc}/figure/outfit-reference`))
    } catch {
      setInfo(null)
    }
  }, [enc])
  useEffect(() => { void load() }, [load, refreshKey])

  const run = useCallback(async (call: () => Promise<OutfitReferenceInfo>, done: string) => {
    if (busy) return
    setBusy(true)
    try {
      setInfo(await call())
      toast(t(done))
      onChanged?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [busy, onChanged, t, toast])

  if (!info) return null
  const row = outfitReferenceRow(info, t)
  const record = info.record
  return (
    <>
      <StepRowView row={row}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {record && info.url ? (
            <div style={{ width: 60, flex: '0 0 auto' }}>
              <RefImage key={info.url} src={info.url} height={80} label={info.label} compact />
            </div>
          ) : null}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => setPicking(true)}
                title={t('Saves only — nothing renders. The dressed front is then due with its cost.')}>
                {t('Pick from gallery')}
              </button>
              <label className="ga-btn ga-btn-sm" style={{ cursor: busy ? 'default' : 'pointer' }}
                title={t('Saves only — nothing renders. The dressed front is then due with its cost.')}>
                {t('Upload')}
                <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={busy}
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (file) void run(() => apiUpload<OutfitReferenceInfo>(
                      `/characters/${enc}/figure/outfit-reference/upload`, file), 'Saved')
                  }} />
              </label>
              {record ? (
                <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                  onClick={() => setClearing({ key: info.key, label: info.label })}>{t('Clear reference')}</button>
              ) : null}
            </div>
            {info.jobs !== null && info.jobs > 0 && record && info.applies ? (
              <div className="ga-hint">
                {t('Due with the next Build — {cost}').replace('{cost}', imageJobsTr(info.jobs, t))}
              </div>
            ) : null}
          </div>
        </div>
      </StepRowView>
      {info.others.length ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="ga-hint">{t('Other outfits with a reference image')}</span>
          {info.others.map((o) => (
            <div key={o.key} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {o.url ? (
                <div style={{ width: 36, flex: '0 0 auto' }}>
                  <RefImage key={o.url} src={o.url} height={48} label={o.label} compact />
                </div>
              ) : <span className="ga-hint">{t('Picture gone')}</span>}
              <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{o.label}</span>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                onClick={() => setClearing({ key: o.key, label: o.label })}>{t('Clear reference')}</button>
            </div>
          ))}
        </div>
      ) : null}
      {picking ? (
        <GalleryPickDialog character={character} onClose={() => setPicking(false)}
          onPick={(filename) => {
            setPicking(false)
            void run(() => apiPost<OutfitReferenceInfo>(`/characters/${enc}/figure/outfit-reference`,
              { image: filename }), 'Saved')
          }} />
      ) : null}
      {clearing ? (
        <ClearConfirm label={clearing.label} onClose={() => setClearing(null)}
          onConfirm={() => {
            const key = clearing.key
            setClearing(null)
            void run(() => apiDelete<OutfitReferenceInfo>(
              `/characters/${enc}/figure/outfit-reference/${encodeURIComponent(key)}`), 'Cleared')
          }} />
      ) : null}
    </>
  )
}
