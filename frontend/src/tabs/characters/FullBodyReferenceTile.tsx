/**
 * FullBodyReferenceTile — the "Full-body reference" step (Ruling A87): the picture the A-pose front is an edit of. ONE
 * component with the same wording in both places: the Base body tab (Views, the first step — the plain body's
 * reference, made from the profile image) and the Figure tab (Dressed views — the reference of the outfit worn now,
 * made from the plain body's full-body reference, else the profile image).
 *
 * - The picture small (a click enlarges it), beside it what it was made from and "Built <time>"; its
 *   light with the state and the reason in plain words (`fullBodyRow`).
 * - "Generate — 1 image job" (the primary path; "Regenerate" once one is set) with what it makes due under it, before
 *   the click; the prompt it sends on mouse-over and under "Prompt" (the character's attributes it carries).
 * - "Pick from gallery" (an in-app picker), "Upload" and "Clear" (an in-app confirmation) — they save only.
 * - Optional: Run all and the Build never generate it.
 *
 * Backend (app/routes/figure.py): the plain body under /characters/{c}/base-body/full-body-reference (GET, POST
 * {image}, POST /upload, POST /generate, DELETE), an outfit under /characters/{c}/figure/outfit-reference (GET, POST
 * {image}, POST /upload, POST /generate, DELETE /{key}).
 */
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { thumbUrl, thumbWidth } from '@anima/player-ui'
import { useClockSettings } from '../../lib/clockFormat'
import { stampLabel } from './freshnessText'
import { RefImage } from './RefImage'
import { StepRowView } from './StepRows'
import type { StepRowData } from './StepRows'
import { SAVES_ONLY, generateLabel } from './fullBodyReferenceModel'
import type { FullBodyGenerate, FullBodyRecord, FullBodyRun } from './fullBodyReferenceModel'

const TILE_W = thumbWidth(96)

/** The character's gallery as a grid; a click picks the picture (GET /characters/{c}/images). */
export function GalleryPickDialog({ character, title, onPick, onClose }: {
  character: string
  title: string
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
          <span>{title}</span>
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
export function ClearConfirm({ label, note, onConfirm, onClose }: {
  label: string
  note: string
  onConfirm: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 420 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Clear the full-body reference?')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>{label}</div>
          <div className="ga-hint">{note}</div>
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

function madeFromWords(record: FullBodyRecord, t: (s: string) => string): string {
  if (record.origin === 'upload') return t('Uploaded')
  if (record.origin !== 'generated') return t('Picked from the gallery')
  return record.made_from?.kind === 'full_body' ? t('Generated from the plain body’s full-body reference')
    : t('Generated from the profile image')
}

export function FullBodyReferenceTile({ character, row, record, url, run, generate, followup, busy, disabledReason,
  clearNote, onGenerate, onPick, onUpload, onClear, children }: {
  character: string
  row: StepRowData
  record: FullBodyRecord | null
  url: string
  run: FullBodyRun | undefined
  generate: FullBodyGenerate | undefined
  /** What a new reference makes due, said before the click (Generate, Pick, Upload). */
  followup: string
  /** A click is in flight. */
  busy: boolean
  /** Why the actions wait (e.g. a Build runs), "" when they do not. */
  disabledReason?: string
  /** Under Clear's confirmation: what clearing does. */
  clearNote: string
  onGenerate: () => void
  onPick: (filename: string) => void
  onUpload: (file: File) => void
  onClear: () => void
  children?: ReactNode
}) {
  const { t } = useI18n()
  const [picking, setPicking] = useState(false)
  const [clearing, setClearing] = useState(false)
  const running = !!run?.running
  const disabled = busy || running || !!disabledReason
  const jobs = generate?.jobs ?? 1
  const blocked = generate && !generate.ready ? generate.blocked : ''
  const prompt = generate?.prompt || ''
  const used = record?.prompt || ''
  const saveTitle = [t(SAVES_ONLY), followup].filter(Boolean).join(' ')
  useClockSettings()   // re-render when the clock settings change
  const built = stampLabel(record?.set_at)
  return (
    <>
      <StepRowView row={row}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <div style={{ width: 84, flex: '0 0 auto' }} title={used ? `${t('Prompt')}: ${used}` : undefined}>
            {record && url ? (
              <RefImage key={url} src={url} height={112} label={row.name} compact />
            ) : (
              <div className="ga-hint" style={{ height: 112, display: 'flex', alignItems: 'center', justifyContent: 'center',
                textAlign: 'center', border: '1px dashed var(--border, #30363d)', borderRadius: 6, fontSize: 11, padding: 4 }}>
                {running ? t('Generating…') : t('No full-body reference')}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, flex: 1 }}>
            {record ? (
              <span className="ga-hint" style={{ fontSize: 11 }}>
                {[madeFromWords(record, t), built ? `${t('Built')} ${built}` : ''].filter(Boolean).join(' · ')}
              </span>
            ) : null}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={disabled || !!blocked}
                title={prompt ? `${t('Prompt')}: ${prompt}` : undefined} onClick={onGenerate}>
                {generateLabel(!!record, jobs, t)}
              </button>
              <button type="button" className="ga-btn ga-btn-sm" disabled={disabled} title={saveTitle}
                onClick={() => setPicking(true)}>
                {t('Pick from gallery')}
              </button>
              <label className="ga-btn ga-btn-sm" style={{ cursor: disabled ? 'default' : 'pointer' }} title={saveTitle}>
                {t('Upload')}
                <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={disabled}
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (file) onUpload(file)
                  }} />
              </label>
              {record ? (
                <button type="button" className="ga-btn ga-btn-sm" disabled={disabled} onClick={() => setClearing(true)}>
                  {t('Clear reference')}
                </button>
              ) : null}
            </div>
            {blocked ? <span className="ga-hint">{t(blocked)}</span> : null}
            {disabledReason ? <span className="ga-hint">{disabledReason}</span> : null}
            {followup ? <span className="ga-hint" style={{ overflowWrap: 'anywhere' }}>{followup}</span> : null}
            {prompt ? (
              <details className="ga-hint" style={{ fontSize: 11 }}>
                <summary style={{ cursor: 'pointer' }}>{t('Prompt of the next Generate')}</summary>
                <div style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{prompt}</div>
                {used && used !== prompt ? (
                  <div style={{ overflowWrap: 'anywhere', marginTop: 4 }}>
                    <strong>{t('Prompt of the stored picture')}:</strong> {used}
                  </div>
                ) : null}
              </details>
            ) : null}
          </div>
        </div>
      </StepRowView>
      {children}
      {picking ? (
        <GalleryPickDialog character={character} title={t('Pick the full-body reference')}
          onClose={() => setPicking(false)}
          onPick={(filename) => { setPicking(false); onPick(filename) }} />
      ) : null}
      {clearing ? (
        <ClearConfirm label={row.name} note={clearNote} onClose={() => setClearing(false)}
          onConfirm={() => { setClearing(false); onClear() }} />
      ) : null}
    </>
  )
}
