/**
 * OutfitReferenceRow — the Figure tab's "Full-body reference" step of the outfit worn now (Ruling A87, which turned
 * A74b's "Reference image" row into the same step as the Base body tab's — `FullBodyReferenceTile`, same wording), on
 * top of the Dressed views sub-tab. An outfit here is what the tab shows: the worn combination of clothing pieces with
 * the pieces worn open (`outfit_references.outfit_key`); its label is the saved outfit's name or the piece names.
 *
 * - Generate (one image job): a full-body picture of the character wearing this outfit — an edit of the plain body's
 *   full-body reference, else of the profile image; the outfit's pieces are named in the prompt. What it makes due is
 *   said under it before the click: the dressed views at the next Build (their image jobs) while something is painted
 *   on the figure, else nothing (the picture is not used now).
 * - Pick from gallery, Upload, Clear (an in-app confirmation) save only — nothing renders.
 * - Unset: the views are made as before — an edit of the body's front, or a copy of the body shape's view.
 * - Other outfits with a reference are listed under it, one line each (a tiny picture, label, Clear).
 * - Ruling A90: row 1 of Dressed views — what the reference is made from (the plain body's full-body reference, else
 *   the profile image; read-only, with its link) → the outfit's full-body reference, side by side.
 *
 * Backend (app/routes/figure.py): GET …/figure/outfit-reference, POST …/figure/outfit-reference {image},
 * POST …/figure/outfit-reference/upload (multipart `file`), POST …/figure/outfit-reference/generate,
 * DELETE …/figure/outfit-reference/{key}.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { RefImage } from './RefImage'
import { ClearConfirm, FullBodyReferenceTile, ReferenceArrow, ReferenceSourceTile } from './FullBodyReferenceTile'
import { fullBodyRow, outfitFollowup } from './fullBodyReferenceModel'
import type { OutfitReferenceInfo } from './dressedViewsModel'

const CLEAR_NOTE = 'The picture stays in the gallery. Nothing renders now — the dressed views of this outfit are then due and made as before (an edit of the body’s front).'

export function OutfitReferenceRow({ character, refreshKey, onChanged, onOpenBaseBody, onOpenGallery }: {
  character: string
  /** The source tile's link when the outfit's reference is made from the plain body's full-body reference. */
  onOpenBaseBody?: () => void
  /** The source tile's link when it is made from the profile image (chosen in the Gallery tab). */
  onOpenGallery?: () => void
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
  const [clearing, setClearing] = useState<{ key: string; label: string } | null>(null)

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<OutfitReferenceInfo>(`/characters/${enc}/figure/outfit-reference`))
    } catch {
      setInfo(null)
    }
  }, [enc])
  useEffect(() => { void load() }, [load, refreshKey])

  // While a Generate runs: read again every 2 s; when it ends, the figure reads again (the dressed views turn due).
  const running = !!info?.run?.running
  const wasRunning = useRef(false)
  useEffect(() => {
    if (wasRunning.current && !running) onChanged?.()
    wasRunning.current = running
    if (!running) return undefined
    const id = window.setTimeout(() => { void load() }, 2000)
    return () => window.clearTimeout(id)
  }, [running, info, load, onChanged])

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
  const row = fullBodyRow('outfit', info, t)
  // Row 1 (Ruling A90): what the outfit's reference is made from → the outfit's full-body reference, side by side.
  const fromBase = info.generate?.source === 'full_body'
  const sourceLink = fromBase
    ? (onOpenBaseBody ? { label: t('Base body'), title: t('The plain body’s full-body reference is made in the Base body tab'),
      onClick: onOpenBaseBody } : undefined)
    : (onOpenGallery ? { label: t('Gallery'), title: t('The profile image is chosen in the Gallery tab'),
      onClick: onOpenGallery } : undefined)
  return (
    <>
      <div className="ga-ref-row">
        <ReferenceSourceTile title={fromBase ? t('Base full-body reference') : t('Profile image')}
          url={info.generate?.source ? info.generate.source_url : ''} empty={t('No profile image')} link={sourceLink} />
        <ReferenceArrow />
        <FullBodyReferenceTile character={character} row={row} record={info.record} url={info.url} run={info.run}
          generate={info.generate} busy={busy} followup={outfitFollowup(info.applies, info.followup_jobs, t)}
          clearNote={t(CLEAR_NOTE)}
          onGenerate={() => void run(() => apiPost<OutfitReferenceInfo>(`/characters/${enc}/figure/outfit-reference/generate`, {}),
            'Generating')}
          onPick={(filename) => void run(() => apiPost<OutfitReferenceInfo>(`/characters/${enc}/figure/outfit-reference`,
            { image: filename }), 'Saved')}
          onUpload={(file) => void run(() => apiUpload<OutfitReferenceInfo>(`/characters/${enc}/figure/outfit-reference/upload`,
            file), 'Saved')}
          onClear={() => void run(() => apiDelete<OutfitReferenceInfo>(
            `/characters/${enc}/figure/outfit-reference/${encodeURIComponent(info.key)}`), 'Cleared')} />
      </div>
      {info.others.length ? (
        <div className="ga-ref-others">
          <span className="ga-hint ga-one-line">{t('Other outfits with a full-body reference')}</span>
          {info.others.map((o) => (
            <div key={o.key} className="ga-ref-other">
              {o.url ? (
                <div style={{ width: 20, flex: '0 0 auto' }}>
                  <RefImage key={o.url} src={o.url} height={28} radius={3} label={o.label} compact bare />
                </div>
              ) : <span className="ga-hint">{t('Picture gone')}</span>}
              <span className="ga-one-line" style={{ flex: 1 }} title={o.label}>{o.label}</span>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy} aria-label={`${t('Clear reference')} · ${o.label}`}
                title={t(CLEAR_NOTE)} onClick={() => setClearing({ key: o.key, label: o.label })}>{t('Clear')}</button>
            </div>
          ))}
        </div>
      ) : null}
      {clearing ? (
        <ClearConfirm label={clearing.label} note={t(CLEAR_NOTE)} onClose={() => setClearing(null)}
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
