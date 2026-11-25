/**
 * TemplateParamsDialog — the parameter dialog of an outfit piece in mode "template" (Rulings A138, A142): the
 * sewing-pattern parameters the drape is made from — only the fields of the chosen kind (`kind_fields` of the server:
 * a skirt has length / flare / waistband / slit, a top sleeves / fit / neckline, a jacket also front and collar, a
 * dress its shoulders) — drawn on the character (A188, below).
 * "Suggest from picture" asks the vision task
 * ONCE (1 LLM call, nothing saved) and fills the fields; Save stores them on the ITEM (every wearer) and spends
 * nothing — the next Build re-drapes (CPU, 0 hub jobs). Rendered through a portal; no native dialogs.
 *
 * A168: opened from the Figure tab's row AND from the Wardrobe's piece row. Its progress box shows this character's
 * drape of the piece (`progress` of the GET: state, reason, error, and the step list Parameters → Picture → Drape in
 * the same ModelSteps list the own-mesh dialog shows), polled while a Build drapes it; a missing or failed drape of a
 * worn piece offers the Build (FigureBuildButton — the one start of a drape, CPU, 0 hub jobs).
 *
 * A188: the piece is drawn ON the character's plain base-body front, live while the fields change (TemplateOverlay —
 * the server registers the picture to the body's metres and returns the piece as pixel polygons); the 1.70 m
 * reference figure is gone (the person is the reference). The item picture stays as a small thumbnail under the
 * fields (click enlarges): it is the source of the texture (user finding 2026-11-20 — the piece-only views and the
 * texture from cut are both made from it).
 *
 * Plan 2026-11-20-template-cut-uv-texture: a top has the field Texture (Projection / From cut) and the "Texture from
 * cut" flow (TemplateCutTextureBox); with "From cut" the front piece-only view is only the projection fallback and the
 * back view is Picture 2 of the cut's back job.
 *
 * Rework after the user's Dario test (2026-11-20): the dialog fits one 1080p screen as three sub-tabs with a traffic
 * light each — Cut (overlay, presets, fields, item picture, drape status + Build), Texture (the cut flow, kept mounted
 * so its tab light stays live) and Views (the piece-only views). While a hub-job flow of the piece runs every other
 * job button of it is off with the reason (`piece_jobs` on the server refuses it with 409 as well).
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { thumbUrl, thumbWidth } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut, apiUpload } from '../../lib/api'
import { guardedInterval } from '../../lib/guardedPoll'
import { useToast } from '../../lib/Toast'
import { FITTED_KINDS, TEMPLATE_CHOICE_LABELS, TEMPLATE_PRESET_HINTS, TEMPLATE_PRESET_LABELS, choiceLabel, TEMPLATE_DRAPE_FABRIC, TEMPLATE_FABRIC_NOTES, TEMPLATE_FIELD_HINTS, TEMPLATE_FIELD_LABELS, TEMPLATE_MATERIAL_HINT, cm, choiceAllowed, corsetTop, defaultSeat, hasBodice, offShoulder, lengthLabel, templateCost } from './figureModel'
import { TEMPLATE_STATE_COLOR, TEMPLATE_STATE_LABELS, failureLines, templateLiveText } from './figureModel'
import { FailureDetails } from './BuildProblem'
import type { TemplateFieldSpec, TemplateInfo, TemplateParams, TemplateProgress } from './figureModel'
import { FigureBuildButton } from './FigureBuildButton'
import { TemplateOverlay } from './TemplateOverlay'
import { StepLine, TemplateCutTextureBox, Thumb } from './TemplateCutTextureBox'
import { ModelSteps } from './ModelSteps'
import { MaterialSelect } from './WardrobeGarment'
import type { PieceMaterialInfo } from './useGarment'

interface TemplatePayload {
  item_id: string
  name: string
  params: TemplateParams | null
  source: string
  updated_at: string
  spec: Record<keyof TemplateParams, TemplateFieldSpec>
  built: string[]
  /** Ruling A142: the fields that mean something per kind (`garment_template.KIND_FIELDS`). */
  kind_fields: Record<string, (keyof TemplateParams)[]>
  cost: TemplateInfo['cost']
  progress?: TemplateProgress
  /** A172: the kind the item most likely is (slots / name) — the starting kind with nothing stored. */
  default_kind?: string
  /** A172: the starting values per kind (a kind change starts from them). */
  kind_defaults?: Record<string, TemplateParams>
  /** Bug round 2026-11-20: named presets per kind (`garment_template.LEGGINGS` for trousers). */
  presets?: Record<string, Record<string, Partial<TemplateParams>>>
  /** A223: the piece's material preset (`piece_material.describe`). */
  material?: PieceMaterialInfo
  /** The item picture shown beside the fields — the source of the texture (`source` "" = the item has none). */
  front_picture?: { source: '' | 'item'; url: string } | null
  /** A205: the piece-only views the bake reads (`garment_template_views.status`). */
  views?: TemplateViews
}

interface TemplateViewAttempt { n: number; ok: boolean; reasons: string[]; skin?: number | null; stamp: number }
interface TemplateViewCell {
  view: 'front' | 'back'
  accepted: boolean
  stamp: number
  source: string
  accepted_by_user: boolean
  skin?: number | null
  attempts: TemplateViewAttempt[]
  running: boolean
  error: string
  max_jobs: number
}
interface TemplateViews {
  views: TemplateViewCell[]
  sheer: boolean
  required: boolean
  missing: string[]
  hub_jobs: number
  max_jobs: number
  /** The texture comes from the cut: the views only feed the projection fallback — never due. */
  optional?: boolean
  /** With the texture from cut: the views the cut reads (["back"]: Picture 2 of its back job). */
  cut_uses?: string[]
  /** Why every job button of the piece is off now ("" = free): another hub-job flow of the piece runs. */
  busy?: string
}

const PICTURE_H = 120
/** A picture that came landscape is shown square, a portrait one narrow. */
const PICTURE_W = { portrait: 80, square: PICTURE_H }

/** The item picture beside the fields — small, captioned as the texture's source, click enlarges it. */
function FrontPicture({ picture }: { picture?: TemplatePayload['front_picture'] }) {
  const { t } = useI18n()
  const [big, setBig] = useState(false)
  const [broken, setBroken] = useState(false)
  const [wide, setWide] = useState(false)
  const box: CSSProperties = { width: wide ? PICTURE_W.square : PICTURE_W.portrait, height: PICTURE_H, border: '1px solid var(--border, #30363d)',
    borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
    background: 'var(--bg-subtle, #161b22)' }
  const src = picture?.source && picture.url && !broken ? picture.url : ''
  const caption = t('Item picture — source of the texture')
  return (
    <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 4, flex: '0 0 auto' }}
      data-front-picture={src ? picture?.source : 'none'}>
      {src ? (
        <button type="button" style={{ ...box, padding: 0, cursor: 'zoom-in' }} onClick={() => setBig(true)}
          title={`${caption}\n${t('click to enlarge')}`}>
          <img src={thumbUrl(src, thumbWidth(PICTURE_H))} alt={caption}
            onError={() => setBroken(true)}
            onLoad={(e) => setWide(e.currentTarget.naturalWidth >= 0.9 * e.currentTarget.naturalHeight)}
            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
        </button>
      ) : (
        <div style={box} className="ga-hint">{t('No item picture')}</div>
      )}
      <figcaption className="ga-form-hint" style={{ textAlign: 'center', maxWidth: wide ? PICTURE_W.square : PICTURE_W.portrait }}>
        {caption}<br />{t('Edit it in the Items tab')}
      </figcaption>
      {big && src ? createPortal(
        <div className="ga-modal-backdrop" style={{ zIndex: 2000, cursor: 'zoom-out' }} onMouseDown={() => setBig(false)}
          role="dialog" aria-modal="true" aria-label={caption}>
          <img src={src} alt={caption}
            style={{ maxWidth: '92vw', maxHeight: '92vh', objectFit: 'contain', margin: 'auto', display: 'block' }} />
        </div>,
        document.body,
      ) : null}
    </figure>
  )
}

const GRID: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '6px 12px' }
const WARN: CSSProperties = { color: 'var(--warning, #d29922)' }
const ORDER: (keyof TemplateParams)[] = ['kind', 'fabric', 'opacity', 'length_m', 'flare', 'waist_height', 'slit', 'slit_m',
  'shoulders', 'band_m', 'band_drop_m', 'lacing', 'lace_depth_m', 'fit', 'neckline', 'neck_depth_m', 'sleeves',
  'sleeve_fit', 'front', 'collar',
  'rise', 'waistband', 'sides', 'string_width_m', 'leg_length_m', 'leg_cut', 'back_coverage', 'side_width_m',
  'gusset_m',
  'cup_style', 'cup_coverage', 'push_up', 'underband_m', 'center_gore', 'closure', 'straps', 'fingers', 'length', 'cuff',
  'tights_style', 'feet', 'garters', 'trouser_length', 'leg_shape', 'seat', 'trouser_waist', 'fly', 'hem', 'placket', 'buttons',
  'texture']
/** `garment_template.TEXTURE_ONLY`: a save that changes only these re-assembles, it never re-drapes. */
const TEXTURE_ONLY_FIELDS: (keyof TemplateParams)[] = ['texture', 'sleeve_print', 'placket', 'buttons', 'fly']
/** `garment_template.neck_piece`: a covered top is cut by the neck-ring rules only with a collar or a placket — a
 *  placket switched on or off there is a new cut (its key gains or loses "neck"), not a re-assembly. */
const neckCut = (p: TemplateParams | undefined | null): boolean => !!p && p.kind === 'top' && p.shoulders === 'covered'
  && ((p.collar || 'none') !== 'none' || (p.placket || 'none') !== 'none')
/** Fields shown as a 0…1 number rather than centimetres. */
const SHARES = new Set<keyof TemplateParams>(['flare', 'fit', 'sleeve_fit', 'opacity', 'leg_cut', 'back_coverage', 'cup_coverage', 'push_up'])

/** Whether a field is shown for the draft: the kind's fields, minus the ones another field switches off. */
/** A227: a jacket with a lapel collar: its opening is the lapel's V whatever the neckline says. */
function lapelNeck(p: TemplateParams): boolean {
  return p.kind === 'jacket' && p.collar === 'lapel'
}

function shown(key: keyof TemplateParams, p: TemplateParams, fields: Record<string, (keyof TemplateParams)[]>): boolean {
  if (!(fields[p.kind] || ORDER).includes(key)) return false
  if (key === 'slit_m' && p.slit === 'none') return false
  if (key === 'opacity' && p.fabric !== 'sheer') return false
  const bodice = hasBodice(p)
  // A221: a corset top (strapless or straps) keeps its neckline (straight / sweetheart) and, for a sweetheart, the
  // dip's depth
  const strapTop = corsetTop(p)
  if (key === 'sleeves' && !bodice) return false
  if (key === 'neckline' && !bodice && !strapTop) return false
  // A227: a lapel collar cuts the jacket's front as a V down to the chest (`bodice_spec`) — the neckline choice does
  // not reach the cut, so it is not offered (the depth still deepens the V)
  if (key === 'neckline' && lapelNeck(p)) return false
  // A229: an off-shoulder piece's neckline is its band (no neckline / depth); the band and lacing fields are its own
  const off = offShoulder(p)
  if ((key === 'neckline' || key === 'neck_depth_m') && off) return false
  if ((key === 'band_m' || key === 'band_drop_m' || key === 'lacing') && !off) return false
  if (key === 'lace_depth_m' && (!off || p.lacing !== 'front')) return false
  if (key === 'neck_depth_m' && !bodice && !(strapTop && p.neckline === 'sweetheart')) return false
  if (key === 'fit' && p.kind === 'dress' && p.shoulders === 'strapless') return false
  // A232: briefs with legs (boxers) hem straight round the thigh: no leg cut / seat shape; the ease only for them
  const legs = p.kind === 'briefs' && Number(p.leg_length_m || 0) > 0
  if ((key === 'leg_cut' || key === 'back_coverage') && legs) return false
  if (key === 'fit' && p.kind === 'briefs' && !legs) return false
  // A235: string briefs — only a front and a back panel, thin hip bands: no side panel, no legs
  const string = p.kind === 'briefs' && p.sides === 'string'
  if ((key === 'side_width_m' || key === 'leg_length_m') && string) return false
  if (key === 'string_width_m' && !string) return false
  if (key === 'sides' && legs) return false
  if (key === 'sleeve_fit' && (!bodice || p.sleeves === 'none')) return false
  // A223: a bandeau is one band round the chest — no gore, no push-up
  if ((key === 'center_gore' || key === 'push_up') && p.kind === 'bra' && p.cup_style === 'bandeau') return false
  // A223: garter tabs only on thigh-high stockings, a waistband only on full tights
  if (key === 'garters' && p.kind === 'tights' && p.tights_style !== 'thigh_high') return false
  if (key === 'waistband' && p.kind === 'tights' && p.tights_style !== 'tights') return false
  // B10: the button count only for a buttoned placket
  if (key === 'buttons' && p.placket !== 'buttons') return false
  // B9 / phase E: a top's or dress's collar stands on a neck ring — only with covered shoulders
  if (key === 'collar' && (p.kind === 'top' || p.kind === 'dress') && p.shoulders !== 'covered') return false
  return true
}

function defaults(p: TemplatePayload, kind?: string): TemplateParams {
  const k = kind || p.default_kind || ''
  if (k && p.kind_defaults?.[k]) return { ...p.kind_defaults[k] }
  const out: Record<string, string | number> = {}
  for (const key of ORDER) out[key] = p.spec[key].default
  return out as unknown as TemplateParams
}

export function TemplateParamsDialog({ character, itemId, onClose, onSaved }: {
  character: string
  itemId: string
  onClose: () => void
  /** Saved on the item: the caller reloads its rows (the drape is due for the next Build). */
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const path = `/characters/${encodeURIComponent(character)}/figure/template/${encodeURIComponent(itemId)}`
  const [data, setData] = useState<TemplatePayload | null>(null)
  const [draft, setDraft] = useState<TemplateParams | null>(null)
  const [source, setSource] = useState<'llm' | 'user'>('user')
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState<'' | 'suggest' | 'save'>('')
  const [saved, setSaved] = useState('')
  const [tab, setTab] = useState<'cut' | 'texture' | 'views'>('cut')
  const [cutTab, setCutTab] = useState<{ light: string; tip: string }>({ light: 'grey', tip: '' })
  const onCutLight = useCallback((light: string, tip: string) => setCutTab({ light, tip }), [])
  useEffect(() => {
    let gone = false
    apiGet<TemplatePayload>(path)
      .then((p) => {
        if (gone) return
        setData(p)
        setDraft(p.params || defaults(p))
        setSource(p.source === 'llm' ? 'llm' : 'user')
      })
      .catch((e) => { if (!gone) setError((e as Error).message) })
    return () => { gone = true }
  }, [path])
  /** Re-read only the progress (after a save, a started Build, and every 3 s while a Build drapes it) — and the
   *  views and the saved parameters: the cut flow sets Texture to "From cut" and may render the back view. */
  const reloadProgress = useCallback(() => {
    return apiGet<TemplatePayload>(`${path}?picture=0`)
      .then((p) => {
        setData((d) => (d ? { ...d, progress: p.progress, params: p.params, updated_at: p.updated_at,
          material: p.material, views: p.views } : p))
        // a texture the server switched (the cut flow selects "From cut") reaches an unchanged draft too
        // …and so does the sleeve option the Texture tab sets (its own control, never a field here)
        setDraft((dr) => (dr && p.params && (dr.texture !== p.params.texture || dr.sleeve_print !== p.params.sleeve_print)
          ? { ...dr, texture: p.params.texture, sleeve_print: p.params.sleeve_print } : dr))
      })
      .catch(() => { /* the last known progress stays */ })
  }, [path])
  const running = data?.progress?.state === 'running'
  useEffect(() => {
    if (!running) return
    return guardedInterval(reloadProgress, 1500)
  }, [running, reloadProgress])
  const set = (key: keyof TemplateParams, value: string | number) => {
    if (!draft || !data) return
    // A172: a kind change starts from that kind's values (a top's length and sleeves are no skirt's); the fabric stays
    const next = key === 'kind' ? { ...defaults(data, String(value)), fabric: draft.fabric, opacity: draft.opacity } : { ...draft, [key]: value }
    // A221: a shoulders change can leave a neckline the piece cannot have (a strapless top: straight / sweetheart)
    if (data.spec.neckline?.type === 'choice' && !choiceAllowed('neckline', next.neckline, next)) {
      next.neckline = data.spec.neckline.choices.find((c) => choiceAllowed('neckline', c, next)) || next.neckline
    }
    // A229: off the shoulders a piece keeps at least short sleeves
    if (data.spec.sleeves?.type === 'choice' && !choiceAllowed('sleeves', next.sleeves, next)) next.sleeves = 'short'
    // bug round 2026-11-20: a leg shape change carries the seat along unless one was chosen (skinny: fitted)
    if (key === 'leg_shape' && (draft.seat || 'regular') === defaultSeat(draft)) next.seat = defaultSeat(next)
    if (!choiceAllowed('seat', next.seat || 'regular', next)) next.seat = 'fitted'
    setDraft(next)
    setSource('user')
    setSaved('')
  }
  /** Bug round 2026-11-20: a preset sets its fields at once (leggings = skinny, fitted seat, fit 0, full length). */
  const applyPreset = (values: Partial<TemplateParams>) => {
    if (!draft) return
    const next = { ...draft, ...values } as TemplateParams
    if (!choiceAllowed('hem', next.hem || 'plain', next)) next.hem = 'plain'
    if (!choiceAllowed('seat', next.seat || 'regular', next)) next.seat = 'fitted'
    setDraft(next)
    setSource('user')
    setSaved('')
  }
  const presets = draft && data?.presets ? Object.entries(data.presets[draft.kind] || {}) : []
  const suggest = async () => {
    setBusy('suggest')
    setError('')
    try {
      const r = await apiPost<{ params: TemplateParams; errors: string[] }>(`${path}/suggest`, {})
      setDraft(r.params)
      setWarnings(r.errors || [])
      setSource('llm')
      setSaved('')
      toast(t('Suggested from the picture — check and save'), 'success')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }
  const save = async () => {
    if (!draft) return
    setBusy('save')
    setError('')
    try {
      await apiPut(path, { params: draft, source })
      // the texture source alone never re-drapes (TEXTURE_ONLY): only the figure is assembled again
      const recut = !!data?.params && neckCut(draft) !== neckCut(data.params)
      const textureOnly = !!data?.params && !recut && (Object.keys(draft) as (keyof TemplateParams)[])
        .every((k) => TEXTURE_ONLY_FIELDS.includes(k) || draft[k] === data.params?.[k])
      setSaved(t(recut && draft.texture === 'cut'
        ? 'Saved — the next Build cuts the pattern again and renders the texture from cut again (image jobs)'
        : textureOnly ? 'Saved — the figure is assembled again with this texture (CPU, 0 hub jobs)'
          : 'Saved — the next Build drapes it (CPU, 0 hub jobs)'))
      toast(t('Template parameters saved'), 'success')
      onSaved()
      reloadProgress()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }
  const title = t('Template parameters — {name}').replace('{name}', data?.name || itemId)
  const kindBuilt = !draft || !data || data.built.includes(draft.kind)
  const hasTexture = !!(data && draft && (data.kind_fields?.[draft.kind] || []).includes('texture'))
  const textureNote = t(draft?.texture === 'cut'
    ? 'The pattern pieces filled from pictures (Texture tab). Until it is made, the projection is shown.'
    : 'Projected from the piece-only views or the item picture during the drape.')
  // one traffic light per tab: the drape, the texture from cut, the piece-only views
  const prog = data?.progress
  const views = data?.views
  const tabs: { id: 'cut' | 'texture' | 'views'; label: string; light: string; tip: string }[] = [
    { id: 'cut', label: t('Cut'), tip: prog ? t(TEMPLATE_STATE_LABELS[prog.state]) : '',
      light: !prog ? 'grey' : prog.state === 'ready' ? 'green' : prog.state === 'running' ? 'blue'
        : prog.state === 'failed' ? 'red' : 'yellow' },
    ...(hasTexture ? [{ id: 'texture' as const, label: t('Texture'), tip: cutTab.tip, light: cutTab.light }] : []),
    { id: 'views', label: t('Views'), tip: views?.busy ? t(views.busy) : '',
      light: views?.views.some((v) => v.running) ? 'blue' : views && views.hub_jobs > 0 ? 'yellow'
        : views && views.missing.length && !views.optional ? 'yellow' : 'green' },
  ]
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={title}
        style={{ maxWidth: 1480, width: '96vw', minHeight: 'min(70vh, 760px)', maxHeight: '92vh' }}>
        <div className="ga-modal-header" style={{ gap: 12, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0 }}>{title}</h3>
          {data && draft ? (
            <nav className="ga-subtabs" aria-label={t('Template sections')} style={{ display: 'flex', gap: 4 }}>
              {tabs.map((tb) => (
                <button key={tb.id} type="button" aria-pressed={tab === tb.id} data-template-tab={tb.id}
                  className={`ga-btn ga-btn-sm${tab === tb.id ? ' ga-btn-primary' : ''}`} title={tb.tip}
                  onClick={() => setTab(tb.id)} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className={`ga-model3d-status-dot ga-model3d-status-${tb.light}`}
                    style={{ width: 8, height: 8, flex: '0 0 8px', boxShadow: '0 0 0 1px rgba(255,255,255,0.55)', ...(tb.light === 'blue' ? { background: 'var(--accent, #6aa9ff)' } : {}) }} />
                  {tb.label}
                </button>
              ))}
            </nav>
          ) : null}
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13, flex: 1, minHeight: 0 }}>
          {!data && !error ? <div className="ga-hint">{t('Loading…')}</div> : null}
          {data && draft && tab === 'cut' ? (
            <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }} data-template-panel="cut">
              <TemplateOverlay path={path} draft={draft} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: '1 1 0', minWidth: 0 }}>
                {presets.length ? (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }} data-template-presets="">
                    <span className="ga-form-hint">{t('Preset')}</span>
                    {presets.map(([name, values]) => (
                      <button key={name} type="button" className="ga-btn" disabled={!!busy}
                        title={t(TEMPLATE_PRESET_HINTS[name] || '')} onClick={() => applyPreset(values)}>
                        {t(TEMPLATE_PRESET_LABELS[name] || name)}
                      </button>
                    ))}
                  </div>
                ) : null}
                <div style={GRID}>
                  {ORDER.filter((key) => data.spec[key] && shown(key, draft, data.kind_fields || {})).map((key) => {
                    const f = data.spec[key]
                    return (
                      <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}
                        title={key === 'texture' ? textureNote : undefined}>
                        <span className="ga-form-hint">
                          {t(key === 'length_m' ? lengthLabel(draft.kind) : TEMPLATE_FIELD_LABELS[key])}
                        </span>
                        {f.type === 'choice' ? (
                          <select className="ga-input" value={String(draft[key])}
                            onChange={(e) => set(key, e.target.value)}>
                            {f.choices.filter((c) => choiceAllowed(key, c, draft)).map((c) => (
                              <option key={c} value={c}>
                                {t(choiceLabel(key, c))}
                                {key === 'kind' && !data.built.includes(c) ? ` (${t('not built yet')})` : ''}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input type="range" min={f.min} max={f.max}
                              step={key === 'buttons' ? 1 : f.max - f.min < 0.05 ? 0.001 : 0.01} style={{ flex: 1, minWidth: 0 }}
                              value={Number(draft[key])} onChange={(e) => set(key, Number(e.target.value))} />
                            <span style={{ width: 52, textAlign: 'right' }}>
                              {key === 'buttons' ? (Number(draft[key]) > 0 ? String(Number(draft[key])) : t('auto'))
                                : SHARES.has(key) ? Number(draft[key]).toFixed(2)
                                : key === 'string_width_m' ? `${Math.round(Number(draft[key]) * 1000)} mm`
                                  : cm(Number(draft[key]))}
                            </span>
                          </span>
                        )}
                        {TEMPLATE_FIELD_HINTS[key] ? (
                          <span className="ga-form-hint" data-field-hint={key}>{t(TEMPLATE_FIELD_HINTS[key] as string)}</span>
                        ) : null}
                        {key === 'fabric' && TEMPLATE_FABRIC_NOTES[draft.fabric] ? (
                          <span className="ga-form-hint" data-fabric-note={draft.fabric}>
                            {t(TEMPLATE_FABRIC_NOTES[draft.fabric])}
                            {data.params && data.params.fabric !== draft.fabric
                              ? ` ${t(TEMPLATE_DRAPE_FABRIC[draft.fabric] && TEMPLATE_DRAPE_FABRIC[draft.fabric] === TEMPLATE_DRAPE_FABRIC[data.params.fabric]
                                ? 'Switching between these finishes only re-assembles the model on the CPU (no new drape, 0 hub jobs).'
                                : 'Switching the fabric re-drapes the piece on the CPU (0 hub jobs).')}` : ''}
                          </span>
                        ) : null}
                        {key === 'fabric' && data.material ? (
                          <span data-material-select="" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            <MaterialSelect itemId={itemId} material={data.material} onChanged={reloadProgress} />
                            <span className="ga-form-hint" data-material-hint="">{t(TEMPLATE_MATERIAL_HINT)}</span>
                            {draft.fabric.startsWith('leather_') ? (
                              <span className="ga-form-hint">
                                {t('A leather finish sets its own surface: the material preset\'s metal and sheen do not apply.')}
                              </span>
                            ) : null}
                          </span>
                        ) : null}
                        {key === 'collar' && lapelNeck(draft) ? (
                          <span className="ga-form-hint" data-lapel-note="">
                            {t('A lapel opens the front in a V down to the chest; it replaces the neckline.')}
                          </span>
                        ) : null}
                        {key === 'placket' ? (
                          <span className="ga-form-hint" data-placket-note="">
                            {draft.kind === 'top' && draft.shoulders === 'covered'
                              ? t('Painted onto the texture from cut along the front. On a top, switching it on or off cuts the pattern again (the next Build renders the texture from cut again, image jobs); the style and the button count only re-assemble the figure.')
                              : t('Painted onto the texture from cut along the front; a switch only re-assembles the figure (0 hub jobs).')}
                          </span>
                        ) : null}
                        {key === 'texture' ? (
                          <span className="ga-form-hint" data-texture-note={draft.texture || 'projection'}>
                            {t('A switch only re-assembles the figure (no new drape, 0 hub jobs).')}
                          </span>
                        ) : null}
                        {key === 'opacity' ? (
                          <span className="ga-form-hint">
                            {t('Only the material: a change re-assembles the figure, no new drape.')}
                          </span>
                        ) : null}
                      </label>
                    )
                  })}
                </div>
                {!kindBuilt ? (
                  <div className="ga-hint" style={WARN}>
                    {t('This kind is not draped yet — the piece stays left off until it is supported.')}
                  </div>
                ) : null}
                {FITTED_KINDS.includes(draft.kind) ? (
                  <div className="ga-hint">{t('A close-fitting piece is cut from the body itself and pinned at its bands — it has no length of its own.')}</div>
                ) : null}
                {draft.kind === 'trousers' ? (
                  <div className="ga-hint">{t('Trousers are cut from the body from the waistband to the hem and widened round each leg by the leg shape. Above the crotch the seat decides: fitted lies on the skin (a skinny leg starts fitted), regular and relaxed span the hollows and stand off the seat. A skinny full-length leg goes into the shoe; every other leg hangs over it. The fly and belt loops come from the picture.')}</div>
                ) : null}
                {draft.kind === 'jacket' ? (
                  <div className="ga-hint">{t('A jacket is draped over the tops and dresses worn with it (built first).')}</div>
                ) : null}
                {warnings.length ? (
                  <div className="ga-hint" style={WARN} title={warnings.join('\n')}>
                    {t('The suggestion had {n} value(s) out of range — corrected').replace('{n}', String(warnings.length))}
                  </div>
                ) : null}
                {!data.params && !saved ? (
                  <div className="ga-hint" style={WARN}>
                    {t(draft.kind === data.default_kind
                      ? 'Not saved yet — starting values for a {kind} (from the item); Suggest or adjust, then Save'
                      : 'Not saved yet — starting values for a {kind}; Suggest or adjust, then Save')
                      .replace('{kind}', t(TEMPLATE_CHOICE_LABELS[draft.kind] || draft.kind).toLowerCase())}
                  </div>
                ) : null}
                <div className="ga-hint">
                  {source === 'llm' ? t('Values from the picture suggestion') : t('Values set by hand')}
                  {data.updated_at ? ` · ${t('saved {at}').replace('{at}', data.updated_at.replace('T', ' ').slice(0, 16))}` : ''}
                  {' · '}{templateCost(data.cost, t)}
                </div>
                {saved ? <div className="ga-hint" style={{ color: 'var(--success, #3fb950)' }}>{saved}</div> : null}
                <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <FrontPicture picture={data.front_picture} />
                  {data.progress ? (
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <TemplateProgressBox character={character} progress={data.progress} onStarted={reloadProgress} />
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
          {data && draft && hasTexture ? (
            <div data-template-panel="texture" style={{ display: tab === 'texture' ? 'block' : 'none' }}>
              <TemplateCutTextureBox path={path} onChanged={reloadProgress} onLight={onCutLight}
                refreshKey={`${data.progress?.state || ''}:${data.progress?.built_at || ''}:${data.params?.texture || ''}`} />
            </div>
          ) : null}
          {data && draft && tab === 'views' && data.views ? (
            <div data-template-panel="views">
              <TemplateViewsBox path={path} views={data.views}
                onChange={(v) => { setData((d) => (d ? { ...d, views: v } : d)); reloadProgress() }} />
            </div>
          ) : null}
          {error ? <div className="ga-hint" style={WARN}>{error}</div> : null}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
          <button type="button" className="ga-btn" disabled={!data || !!busy} onClick={() => { void suggest() }}
            title={t('Reads the item picture and text with the vision model; fills the fields, saves nothing')}>
            {busy === 'suggest' ? t('Asking the LLM…') : t('Suggest from picture (1 LLM call)')}
          </button>
          <span style={{ display: 'flex', gap: 6 }}>
            <button type="button" className="ga-btn" disabled={!!busy} onClick={onClose}>{t('Close')}</button>
            <button type="button" className="ga-btn ga-btn-primary" disabled={!draft || !!busy}
              onClick={() => { void save() }}>{busy === 'save' ? t('Saving…') : t('Save')}</button>
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** A168: this character's drape of the piece — one state line (state, reason / error, when it was draped), the step
 *  list (ModelSteps, as in the own-mesh dialog) and, for a worn piece that is not draped or failed, the Build. */
function TemplateProgressBox({ character, progress, onStarted }: {
  character: string
  progress: TemplateProgress
  onStarted: () => void
}) {
  const { t } = useI18n()
  const p = progress
  // A failed drape in plain words (its raw checks are behind Details below); the raw error only from an older server.
  const plain = p.state === 'failed' && p.failure?.lines.length ? failureLines(p.failure, t).join(' ') : ''
  const why = plain || (p.state === 'failed' && p.error ? `${t('Drape failed')}: ${p.error}`
    : p.state === 'ready' || p.state === 'running' ? '' : t(p.reason))
  const at = p.built_at ? t('draped {at}').replace('{at}', p.built_at.replace('T', ' ').slice(0, 16)) : ''
  return (
    <div role="status" aria-label={t('Drape progress')} data-template-state={p.state}
      style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px',
        border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong>{t('Drape on {name}').replace('{name}', character)}</strong>
        <span style={{ padding: '1px 6px', borderRadius: 8, fontSize: '0.85em',
          border: `1px solid ${TEMPLATE_STATE_COLOR[p.state]}` }}>{t(TEMPLATE_STATE_LABELS[p.state])}</span>
        {at ? <span className="ga-hint">{at}</span> : null}
      </div>
      {why ? (
        <div className="ga-hint" style={p.state === 'failed' ? { color: 'var(--danger, #f85149)' } : WARN}>{why}</div>
      ) : null}
      {p.state === 'failed' && p.failure ? <FailureDetails failure={p.failure} /> : null}
      {p.state === 'running' ? (
        <div className="ga-hint" data-template-live={p.live?.stage || 'waiting'}
          style={{ color: 'var(--accent, #6aa9ff)' }}>
          {p.live ? templateLiveText(p.live, t) : t('The Build runs — the drape starts at its step')}
        </div>
      ) : null}
      <ModelSteps steps={p.steps} />
      {p.inner_collider && p.inner_collider.mode !== 'full' ? (
        <div className="ga-hint" data-inner-collider={p.inner_collider.mode} style={WARN}
          title={p.inner_collider.failed.map((f) => `${f.mode}: ${f.error}`).join('\n') || undefined}>
          {t(p.inner_collider.mode === 'shrunk'
            ? 'The pieces under it were made slimmer for the drape: it failed a check over them as they are'
            : 'Draped without the pieces under it: it failed a check over them — their parts under it are hidden')}
        </div>
      ) : null}
      {p.hem_moved ? (
        <div className="ga-hint" data-hem-moved="underbust">
          {t('Hem moved below the underbust fold: draped {draped} m long instead of {asked} m')
            .replace('{draped}', p.hem_moved.draped_length_m.toFixed(2))
            .replace('{asked}', p.hem_moved.length_m.toFixed(2))}
        </div>
      ) : null}
      {!p.worn ? (
        <div className="ga-hint">{t('Not worn now — the Build drapes it once it is worn')}</div>
      ) : p.state === 'missing' || p.state === 'failed' ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <FigureBuildButton character={character} onStarted={onStarted} />
          <span className="ga-hint">{t('The drape runs in the Build — CPU, 0 hub jobs')}</span>
        </div>
      ) : null}
    </div>
  )
}

const VIEW_LABEL: Record<string, string> = { front: 'Front view', back: 'Back view' }
const VIEW_SIDE = 180
const ATTEMPT_SIDE = 64

/** A205: the piece-only views (front + back, the piece alone, cut out) — one cell per view: the accepted view, its
 *  attempts (Use this), Generate / Regenerate (at most 2 hub jobs per view) and Upload. With texture "projection"
 *  the drape bakes its texture from them (a sheer piece needs both); with "From cut" the front view only feeds the
 *  projection fallback and the back view is Picture 2 of the cut's back job. While another hub-job flow of the
 *  piece runs every job button is off with its reason (`busy`, the server refuses it too). */
function TemplateViewsBox({ path, views, onChange }: {
  path: string
  views: TemplateViews
  onChange: (v: TemplateViews) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState('')
  const running = views.views.some((v) => v.running)
  const held = views.busy ? t(views.busy) : ''
  const reload = useCallback(() => {
    return apiGet<TemplateViews>(`${path}/views`).then(onChange).catch(() => { /* the last state stays */ })
  }, [path, onChange])
  useEffect(() => {
    return guardedInterval(reload, running || held ? 2000 : 8000)
  }, [running, held, reload])
  const act = async (key: string, fn: () => Promise<TemplateViews>, done: string) => {
    setBusy(key)
    try {
      onChange(await fn())
      if (done) toast(t(done), 'success')
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }
  const uses = views.cut_uses || []
  const role = (view: string) => views.optional
    ? (uses.includes(view)
      ? t('Used by the texture from cut — Picture 2 of its back job. A new one makes the texture from cut out of date.')
      : t('Only for the projection fallback — not needed with the texture from cut.'))
    : views.sheer
      ? t('Required: the sheer fabric is baked only from these views.')
      : t('The drape bakes the texture from it (else from the item picture); a new one re-drapes at the next Build (CPU).')
  return (
    <div role="group" aria-label={t('Piece-only views')}
      data-template-views={views.optional ? 'optional' : views.missing.length ? 'due' : 'done'}
      style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="ga-hint">
        {t('The piece alone, cut out, rendered from the item picture (occasion “Garment view”). At most 2 hub jobs per view and click; a refused attempt stays offered.')}
      </div>
      {held ? <div className="ga-hint" style={{ color: 'var(--accent, #6aa9ff)' }} data-views-busy="">{held}</div> : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
        {views.views.map((c) => {
          const enc = `${path}/views/${c.view}`
          const due = !c.accepted && !views.optional
          const off = !!busy || c.running || !!held
          return (
            <div key={c.view} data-view-cell={c.view} data-view-state={c.accepted ? 'done' : due ? 'due' : 'none'}
              style={{ display: 'grid', gridTemplateColumns: `${VIEW_SIDE}px minmax(0, 1fr)`, gap: 10, alignItems: 'start' }}>
              <div style={{ width: VIEW_SIDE, height: VIEW_SIDE, border: '1px solid var(--border, #30363d)', borderRadius: 4,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'repeating-conic-gradient(#2a2f36 0% 25%, #1c2026 0% 50%) 50% / 16px 16px' }}>
                {c.accepted
                  ? <Thumb src={`${enc}.png?v=${c.stamp}`} label="" size={VIEW_SIDE - 2} tip={t(VIEW_LABEL[c.view])} />
                  : <span className="ga-hint">{c.running ? t('Rendering…') : t('No view yet')}</span>}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                <StepLine label={t(VIEW_LABEL[c.view])}
                  light={c.running ? 'blue' : c.accepted ? (c.accepted_by_user ? 'yellow' : 'green') : due ? 'yellow' : 'grey'}
                  text={c.running ? t('Rendering…') : c.accepted
                    ? (c.accepted_by_user ? t('Accepted by you despite the check')
                      : t(c.source === 'upload' ? 'uploaded' : 'made'))
                    : due ? t('due') : t('not made')} />
                <span className="ga-hint" style={{ fontSize: 11 }}>{role(c.view)}</span>
                {c.error ? <span className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{c.error}</span> : null}
                {c.attempts.length && !c.running ? (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {c.attempts.map((a) => (
                      <figure key={a.n} style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 2, width: ATTEMPT_SIDE }}
                        title={a.reasons.join('\n') || t('Passed')}>
                        <div style={{ border: `1px solid ${a.ok ? 'var(--success, #3fb950)' : 'var(--danger, #f85149)'}`, borderRadius: 4 }}>
                          <Thumb src={`${enc}.png?attempt=${a.n}&v=${a.stamp}`} label="" size={ATTEMPT_SIDE - 2}
                            tip={`${t('Attempt')} ${a.n}: ${a.reasons.join('; ') || t('Passed')}`} />
                        </div>
                        <button type="button" className="ga-btn ga-btn-sm" disabled={off} title={held || undefined}
                          onClick={() => { void act(`use-${c.view}-${a.n}`, () => apiPost<TemplateViews>(`${enc}/use/${a.n}`, {}), 'View used') }}>
                          {t('Use this')}
                        </button>
                      </figure>
                    ))}
                  </div>
                ) : null}
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  <button type="button" className="ga-btn ga-btn-sm" disabled={off}
                    title={held || t('At most {n} hub jobs for this piece-only view per click — after that it is offered: Use this, Upload or Regenerate.').replace('{n}', String(c.max_jobs))}
                    onClick={() => { void act(`gen-${c.view}`, () => apiPost<TemplateViews>(`${enc}/generate`, {}), '') }}>
                    {c.running ? t('Rendering…') : t(c.accepted || c.attempts.length ? 'Regenerate (1–2 hub jobs)' : 'Generate (1–2 hub jobs)')}
                  </button>
                  <label className="ga-btn ga-btn-sm" aria-disabled={off}
                    style={{ cursor: off ? 'default' : 'pointer', opacity: off ? 0.5 : 1 }} title={held || t('No hub job')}>
                    {t('Upload…')}
                    <input type="file" accept="image/*" hidden disabled={off}
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        e.target.value = ''
                        if (f) void act(`up-${c.view}`, () => apiUpload<TemplateViews>(`${enc}/upload`, f), 'View uploaded')
                      }} />
                  </label>
                  {c.accepted ? (
                    <button type="button" className="ga-btn ga-btn-sm" disabled={off} title={held || undefined}
                      onClick={() => { void act(`del-${c.view}`, () => apiDelete<TemplateViews>(enc), 'View removed') }}>
                      {t('Remove')}
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
