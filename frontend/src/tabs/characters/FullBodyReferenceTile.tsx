/**
 * FullBodyReferenceTile — the "Full-body reference" step (Ruling A87): the picture the A-pose front is an edit of. ONE
 * component with the same wording in both places: the Base body tab (Views, the first step — the plain body's
 * reference, made from the profile image) and the Figure tab (Dressed views — the reference of the outfit worn now,
 * made from the plain body's full-body reference, else the profile image).
 *
 * Ruling A90 (the user: less text, references side by side): the tile is compact — light, name and state; the
 * picture small (a click enlarges it); "Built <time>" (what it was made from on mouse-over); the buttons
 * "Generate · 1 image" / "↻ 1 image", "Gallery" (an in-app picker), "Upload", "Clear" (an in-app confirmation) — what
 * each does and makes due on its mouse-over, before the click; the prompt behind ⓘ. Only a yellow or red light keeps its
 * reason visible, in one line. `ReferenceSourceTile` is the read-only picture the reference is made from, shown before
 * it with an arrow (`ReferenceArrow`): the profile image, or the plain body's full-body reference for an outfit.
 * Optional: Run all and the Build never generate it.
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
import { StepLight } from './StepRows'
import type { StepRowData } from './StepRows'
import { LIGHT_COLOR } from './stepStyle'
import { shortCost } from './figureModel'
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

/** A read-only reference picture in the references row (Ruling A90): the profile image, or the plain body's full-body
 *  reference an outfit's is made from — the same size as the full-body reference tile beside it, a click enlarges it,
 *  and a link to the tab that owns it. */
export function ReferenceSourceTile({ title, url, empty, link }: {
  title: string
  url: string
  /** Shown in place of the picture when there is none. */
  empty: string
  link?: { label: string; title: string; onClick: () => void }
}) {
  return (
    <div className="ga-ref-tile ga-ref-source">
      <div className="ga-ref-head"><strong className="ga-one-line" title={title}>{title}</strong></div>
      <div className="ga-ref-pic">
        {url ? <RefImage key={url} src={url} height={PIC_H} label={title} compact />
          : <div className="ga-hint ga-ref-empty" style={{ height: PIC_H }}>{empty}</div>}
      </div>
      {link ? (
        <button type="button" className="ga-btn ga-btn-sm" title={link.title} onClick={link.onClick}>↗ {link.label}</button>
      ) : null}
    </div>
  )
}

/** The arrow between a reference and what is made from it. */
export function ReferenceArrow() {
  return <span className="ga-ref-arrow" aria-hidden>→</span>
}

/** The picture height of the references row (both tiles the same size). */
const PIC_H = 120

/**
 * The full-body reference step as one compact tile (Ruling A90; the same component in both places, Ruling A87):
 * light, name and state on top; the picture (a click enlarges it, the prompt it was made with on mouse-over); beside
 * it "Built <time>" (what it was made from on mouse-over) and the compact buttons — Generate / ↻ with the cost, Gallery,
 * Upload, Clear — each saying in its mouse-over what it does and makes due; ⓘ carries the prompt of the next Generate.
 * Visible text beyond that only for a yellow or red light: its reason in one line (the whole on mouse-over), and why the
 * buttons wait.
 */
export function FullBodyReferenceTile({ character, row, record, url, run, generate, followup, busy, disabledReason,
  clearNote, onGenerate, onPick, onUpload, onClear, extra, children }: {
  character: string
  row: StepRowData
  record: FullBodyRecord | null
  url: string
  run: FullBodyRun | undefined
  generate: FullBodyGenerate | undefined
  /** What a new reference makes due, said before the click (Generate, Pick, Upload) — on mouse-over. */
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
  /** Ruling A151: compact controls under the buttons (the reference post-process switch). */
  extra?: ReactNode
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
  const color = LIGHT_COLOR[row.light]
  // Only a yellow or red light keeps its reason visible (one line); every other sentence is a mouse-over.
  const loud = row.light === 'yellow' || row.light === 'red'
  const generateTitle = [generateLabel(!!record, jobs, t), followup, prompt ? `${t('Prompt')}: ${prompt}` : '']
    .filter(Boolean).join('\n')
  const info = [prompt ? `${t('Prompt of the next Generate')}: ${prompt}` : '',
    used && used !== prompt ? `${t('Prompt of the stored picture')}: ${used}` : ''].filter(Boolean).join('\n\n')
  return (
    <>
      <div className="ga-ref-tile ga-ref-main">
        <div className="ga-ref-head" title={[row.reason, row.detail].filter(Boolean).join('\n') || undefined}>
          <StepLight light={row.light} />
          <strong className="ga-one-line">{row.name}</strong>
          <span className="ga-ref-state" style={{ color }}>{row.state}</span>
        </div>
        <div className="ga-ref-body">
          <div className="ga-ref-pic" title={used ? `${t('Prompt')}: ${used}` : undefined}>
            {record && url ? (
              <RefImage key={url} src={url} height={PIC_H} label={row.name} compact />
            ) : (
              <div className="ga-hint ga-ref-empty" style={{ height: PIC_H }}>
                {running ? t('Generating…') : t('No full-body reference')}
              </div>
            )}
          </div>
          <div className="ga-ref-side">
            {record ? (
              <span className="ga-hint ga-one-line" title={madeFromWords(record, t)}>
                {built ? `${t('Built')} ${built}` : madeFromWords(record, t)}
              </span>
            ) : null}
            <div className="ga-ref-buttons">
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={disabled || !!blocked}
                title={generateTitle} aria-label={generateLabel(!!record, jobs, t)} onClick={onGenerate}>
                {record ? `↻ ${shortCost(jobs, undefined, t)}` : `${t('Generate')} · ${shortCost(jobs, undefined, t)}`}
              </button>
              <button type="button" className="ga-btn ga-btn-sm" disabled={disabled} title={saveTitle}
                aria-label={t('Pick from gallery')} onClick={() => setPicking(true)}>
                {t('Gallery')}
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
                <button type="button" className="ga-btn ga-btn-sm" disabled={disabled} title={clearNote}
                  aria-label={t('Clear reference')} onClick={() => setClearing(true)}>
                  {t('Clear')}
                </button>
              ) : null}
              {info ? <span className="ga-info" tabIndex={0} title={info} aria-label={info}>i</span> : null}
            </div>
            {extra}
          </div>
        </div>
        {loud && row.reason ? (
          <div className="ga-hint ga-one-line" style={{ color }} title={row.reason}>{row.reason}</div>
        ) : null}
        {blocked ? <div className="ga-hint ga-one-line" title={t(blocked)}>{t(blocked)}</div> : null}
        {disabledReason ? <div className="ga-hint ga-one-line" title={disabledReason}>{disabledReason}</div> : null}
      </div>
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
