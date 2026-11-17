/**
 * PaintedPieceDialog — the steps of a WORN painted piece (Ruling A148), the mesh pieces' dialog counterpart.
 * Opened from the Figure tab's worn row and the Wardrobe row ("Details" / "Paint steps").
 *
 * A painted piece is painted per OUTFIT: its rows are the outfit's steps, and the head names the other painted
 * pieces that share the views and the texture.
 * - Dressed views: the outfit's dressed views as step rows (FieldModelRefs `steps` — tiles that enlarge, state,
 *   Regenerate with its image-job cost, mirror).
 * - Paint region (Ruling A127): the painted texture with this piece's body regions tinted (blue) and painted texels
 *   outside them marked (orange) — GET …/painted/{item}/region.png.
 * - Painted texture: its key, when built, its state; "Paint now (CPU, 0 hub jobs)" (POST …/figure/paint) — enabled
 *   only when the plan's work is CPU only, else the reason under it.
 * - Assembly: the figure with the grafted pieces; built at.
 * - Colour (beside the viewer, like the hair's): picker, presets, strength; dragging previews in the viewer
 *   (POST …/painted/{item}/preview.glb — nothing stored); Save stores it (POST …/colour) and runs nothing — the
 *   texture row then says the repaint is due (CPU, 0 hub jobs). "Painted colours" clears it.
 * Reloads on the push topic `generation` and polls while a Build runs.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { syncHub } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { jobsTr } from './baseBodyModel'
import { FieldModelRefs } from './FieldModelRefs'
import { Model3DViewer } from './Model3DViewer'
import { StepRowView } from './StepRows'
import { Swatch } from './HairstyleParts'
import { colourDirty, fill, paintGate, paintNextLine, rowLight, PAINT_NOW } from './paintedPieceModel'
import type { PaintedColour, PaintedPieceInfo } from './paintedPieceModel'

const TPOSE: ('tpose')[] = ['tpose']
const GROUP: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px',
  border: '1px solid var(--border, #30363d)', borderRadius: 6 }
const ROW: CSSProperties = { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }
const DUE: CSSProperties = { color: 'var(--warning, #d29922)', fontSize: 11, overflowWrap: 'anywhere' }

export function PaintedPieceDialog({ character, itemId, name, onClose, initialInfo }: {
  character: string
  itemId: string
  name: string
  onClose: () => void
  /** A fixture shown before the first load answers (headless checks). */
  initialInfo?: PaintedPieceInfo
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const base = `/characters/${enc}/figure/painted/${encodeURIComponent(itemId)}`
  const [info, setInfo] = useState<PaintedPieceInfo | null>(initialInfo ?? null)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<PaintedColour | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [big, setBig] = useState(false)
  const [posting, setPosting] = useState(false)
  const [regionStamp, setRegionStamp] = useState(0)
  const cost = (n: number) => jobsTr(n, t)

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<PaintedPieceInfo>(base))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [base])
  useEffect(() => { void load() }, [load])
  useEffect(() => syncHub().onTopics(['generation'], () => { void load(); setRegionStamp(Date.now()) }), [load])
  useEffect(() => {
    if (!info?.build_running) return
    const id = window.setInterval(() => { void load() }, 3000)
    return () => window.clearInterval(id)
  }, [info?.build_running, load])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const stored: PaintedColour = { hex: info?.colour.hex || '', strength: info?.colour.strength ?? 1 }
  const shown: PaintedColour = draft ?? stored
  const built = !!info?.texture?.built_at

  // The viewer's model: the painted body in the colour shown (the draft while one is picked).
  const lastUrl = useRef('')
  const timer = useRef<number | null>(null)
  // Only the newest request may show its answer (an older build can finish last); bumped on unmount too,
  // so a late answer releases its blob instead of creating a URL nobody revokes.
  const previewSeq = useRef(0)
  const loadPreview = useCallback((c: PaintedColour) => {
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => {
      timer.current = null
      const seq = ++previewSeq.current
      setPreviewing(true)
      try {
        const res = await fetch(`${base}/preview.glb`, { method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c) })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const blob = await res.blob()
        if (seq !== previewSeq.current) return
        const url = URL.createObjectURL(blob)
        if (lastUrl.current) URL.revokeObjectURL(lastUrl.current)
        lastUrl.current = url
        setPreviewUrl(url)
      } catch {
        if (seq === previewSeq.current) setPreviewUrl('')
      } finally {
        if (seq === previewSeq.current) setPreviewing(false)
      }
    }, 250)
  }, [base])
  useEffect(() => {
    if (info?.texture && built) loadPreview(shown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [built, shown.hex, shown.strength, loadPreview])
  useEffect(() => () => {
    previewSeq.current += 1
    if (timer.current) window.clearTimeout(timer.current)
    if (lastUrl.current) URL.revokeObjectURL(lastUrl.current)
  }, [])

  const saveColour = async (c: PaintedColour | null) => {
    setPosting(true)
    try {
      await apiPost(`${base}/colour`, c ? { hex: c.hex, strength: c.strength } : { hex: '' })
      setDraft(null)
      toast(t('Saved — the texture is due (CPU, 0 hub jobs)'), 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      void load()
    }
  }
  const paintNow = async () => {
    setPosting(true)
    try {
      await apiPost(`/characters/${enc}/figure/paint`, {})
      toast(t('Painting on the CPU (0 hub jobs)'), 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      void load()
    }
  }

  const gate = paintGate(info, cost)
  const next = paintNextLine(info, cost)
  const running = !!info?.build_running
  const texture = info?.texture
  const views = info?.views ?? []
  const viewState = views.every((v) => v.state === 'current') ? 'current' : 'due'
  const viewJobs = views.reduce((n, v) => n + v.jobs, 0)
  const colourDue = texture?.state === 'colour_due'

  const body = !info ? (
    <div className="ga-hint" style={{ padding: 12 }}>{error || t('Loading…')}</div>
  ) : info.note ? (
    <div className="ga-hint" style={{ padding: 12 }}>{t(info.note)}</div>
  ) : (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 340px) 220px minmax(300px, 1fr)', gap: 12,
      padding: 12, alignItems: 'start' }}>
      <div style={{ position: 'relative' }}>
        {previewUrl ? (
          <Model3DViewer url={previewUrl} format="glb" height={420} builtAt={texture?.built_at ?? null} />
        ) : (
          <div className="ga-hint" style={{ height: 420, display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px dashed var(--border, #30363d)', borderRadius: 6, textAlign: 'center', padding: 12 }}>
            {built ? t('Loading…') : t('No painted texture yet — the preview shows once the Build has painted it')}
          </div>
        )}
        {previewing ? <span className="ga-hint" style={{ position: 'absolute', top: 6, right: 8 }}>{t('Recolouring…')}</span> : null}
        {draft ? <div className="ga-hint">{t('Preview only — Save keeps it')}</div> : null}
      </div>

      <div style={GROUP} aria-label={t('Colour')}>
        <strong style={{ fontSize: 12 }}>{t('Colour')}</strong>
        <div style={ROW}>
          <input type="color" aria-label={t('Piece colour')} value={shown.hex || '#808080'} disabled={!built}
            style={{ width: 34, height: 22, padding: 0, border: 'none', background: 'none' }}
            onChange={(e) => setDraft({ hex: e.target.value.toLowerCase(), strength: shown.strength })} />
          <span className="ga-hint">{shown.hex ? shown.hex : t('Painted colours')}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 3 }}>
          {info.colour.presets.map((p) => (
            <button key={p.hex} type="button" title={t(p.name)} aria-label={t(p.name)} disabled={!built}
              onClick={() => setDraft({ hex: p.hex, strength: shown.strength })}
              style={{ height: 18, borderRadius: 3, background: p.hex, cursor: 'pointer',
                border: shown.hex === p.hex ? '2px solid var(--accent, #58a6ff)' : '1px solid rgba(255,255,255,0.25)' }} />
          ))}
        </div>
        <label className="ga-model3d-slider" style={{ fontSize: 11 }}
          title={t('How far the piece moves toward the colour: 100 % puts its middle tone on it, 0 % keeps the painted colours. Shading and folds stay.')}>
          <span style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>{t('Strength')}</span><span>{Math.round(shown.strength * 100)} %</span>
          </span>
          <input type="range" min={0} max={1} step={0.05} value={shown.strength} disabled={!built || !shown.hex}
            onChange={(e) => setDraft({ hex: shown.hex, strength: Number(e.target.value) })} />
        </label>
        <div style={ROW}>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={posting || !colourDirty(draft, stored) || !shown.hex}
            title={t('Saves the colour — nothing runs')} onClick={() => { void saveColour(shown) }}>{t('Save')}</button>
          <button type="button" className="ga-btn ga-btn-sm" disabled={posting || (!info.colour.hex && !draft)}
            title={t('Back to the painted colours — saved at once, nothing runs')}
            onClick={() => { if (info.colour.hex) void saveColour(null); else setDraft(null) }}>{t('Painted colours')}</button>
        </div>
        <span className="ga-hint" style={{ fontSize: 11 }}>
          {t('In use')}: {info.colour.applied ? <Swatch hex={info.colour.applied.hex} /> : null}{' '}
          {info.colour.applied ? `${info.colour.applied.hex} · ${Math.round(info.colour.applied.strength * 100)} %`
            : t('Painted colours')}
        </span>
        {colourDue ? <span style={DUE}>{t('Saved, not applied — Paint now applies it (CPU, 0 hub jobs)')}</span> : null}
        {!built ? <span className="ga-hint" style={{ fontSize: 11 }}>{t('Colour can be set once the texture is painted')}</span> : null}
        {info.shared_with.length ? (
          <span className="ga-hint" style={{ fontSize: 11 }}>
            {t('Only this piece’s texels change; the others keep theirs.')}
          </span>
        ) : null}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        <StepRowView row={{ name: t('Dressed views'), light: rowLight(viewState, running),
          state: viewState === 'current' ? t('Current') : t('Due'),
          reason: viewState === 'current' ? t('Every view shows the outfit')
            : t('{n} missing — the Build renders them ({cost})').replace('{n}', String(views.filter((v) => v.state !== 'current').length))
              .replace('{cost}', cost(viewJobs)) }} />
        <div style={{ maxHeight: 200, overflow: 'auto' }}>
          <FieldModelRefs character={character} kinds={TPOSE} layout="steps" />
        </div>

        <StepRowView row={{ name: t('Paint region'), light: built ? 'green' : 'grey', state: info.regions.join(', '),
          reason: t('Only these body regions may change (soft edge {mm} mm); head, hands and feet stay unless a slot names them.')
            .replace('{mm}', String(info.margin_mm)) }}>
          {built ? (
            <img src={`${info.region_url}?v=${regionStamp}`} alt={t('Paint region')} title={t('Click to enlarge')}
              onClick={() => setBig(true)}
              style={{ width: 120, height: 120, objectFit: 'cover', borderRadius: 4, cursor: 'zoom-in' }} />
          ) : <div className="ga-hint">{t('Shown once the texture is painted')}</div>}
        </StepRowView>

        <StepRowView row={{ name: t('Painted texture'), light: rowLight(texture?.state || 'due', running),
          state: texture?.state === 'current' ? t('Current') : texture?.state === 'left_out' ? t('Left off') : t('Due'),
          reason: texture ? t(texture.reason) : '',
          detail: texture?.proof ? `${texture.proof.texels ?? 0} texels · ΔE ${texture.proof.delta_e_after ?? '–'}` : undefined,
          button: { disabled: gate.disabled && gate.reason ? fill(t(gate.reason), gate.vars) : null } }}>
          <div className="ga-hint" style={{ fontSize: 11 }}>
            {t('Key')}: {texture?.key || '—'} · {texture?.built_at
              ? `${t('Built')} ${new Date(texture.built_at).toLocaleString()}` : t('Not built yet')}
            {texture?.reused ? ` · ${t('painted body reused')}` : ''}
          </div>
          <div style={ROW}>
            <button type="button" className={`ga-btn ga-btn-sm${gate.disabled ? '' : ' ga-btn-primary'}`}
              disabled={posting || gate.disabled} onClick={() => { void paintNow() }}
              title={t('Repaints the texture from the stored painted body with the colours, then assembles — CPU only')}>
              {t(PAINT_NOW)}
            </button>
          </div>
        </StepRowView>

        <StepRowView row={{ name: t('Assembly'), light: rowLight(info.assembly?.state || 'due', running),
          state: info.assembly?.state === 'current' ? t('Current') : t('Due'),
          reason: info.assembly ? t(info.assembly.reason) : '' }}>
          <div className="ga-hint" style={{ fontSize: 11 }}>
            {info.assembly?.built_at ? `${t('Built')} ${new Date(info.assembly.built_at).toLocaleString()}` : t('Not built yet')}
          </div>
        </StepRowView>
      </div>
    </div>
  )

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal ga-garment-dialog" role="dialog" aria-modal="true"
        aria-label={`${t('Paint steps')} · ${name}`}>
        <div className="ga-modal-header ga-garment-dialog-head">
          <span className="ga-garment-dialog-title" title={name}>{name}</span>
          <div style={{ flex: '1 1 auto', minWidth: 0, fontWeight: 400 }}>
            <div className="ga-hint">
              {t('Painted')} · {info?.shared_with.length
                ? t('painted per outfit, together with: {names}').replace('{names}', info.shared_with.map((s) => s.name).join(', '))
                : t('painted per outfit — the only painted piece of this outfit')}
            </div>
            {running ? <div className="ga-hint">{t('A Build runs — it paints too')}</div>
              : next ? <div className="ga-hint">{fill(t(next.key), next.vars)}</div> : null}
          </div>
          <button type="button" className="ga-modal-close" aria-label={t('Close')} onClick={onClose}>×</button>
        </div>
        {body}
        {big && info ? (
          <div className="ga-modal-backdrop" onMouseDown={() => setBig(false)}>
            <img src={`${info.region_url}?v=${regionStamp}`} alt={t('Paint region')}
              style={{ maxWidth: '90vw', maxHeight: '90vh', margin: 'auto', display: 'block' }} />
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}
