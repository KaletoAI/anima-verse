/**
 * WardrobeAccessory — an accessory piece's controls (Ruling A118, A216; spec
 * docs/superpowers/specs/2026-11-16-accessories-design.md § 6 / § 7).
 *
 * The row shows the build state as a chip (the reason in its tooltip) and
 * "Accessory settings…". The dialog holds the kind (with the suggested one),
 * the Drop slider (named lengths below the jugular notch), the thickness and
 * the metal BESIDE a 3D view of the plain body: dragging rotates the body, the
 * chain's centre line follows the sliders live (POST …/curve, nothing stored)
 * and a 1.70 m figure stands beside it. Save stores the item-wide settings
 * (no job; the accessory step becomes due), Build makes it on the CPU (0 hub
 * jobs). Reads GET /characters/{c}/figure/accessory/{item}.
 *
 * A225: the chain material includes cords (leather, string, fabric; thicker by
 * default). Design G (plan-anhaenger Task 8): a necklace's pendant and a belt's
 * buckle and charms are linked PART ITEMS (`PartLinkFields`: pick, make —
 * 1 image job —, Build mesh — 1 hub job per part, shared by every host and
 * wearer); a placeholder box stands where a linked part goes until the build
 * carries it.
 *
 * A234: every other kind. Belt / choker / strap are a flat band (height, width,
 * the layer it sits on, band material; a strap's place and side); anklet /
 * bracelet a round tube (height, thickness, side); A238 a ring (hand, finger,
 * place along the finger, band width and thickness — its size comes from the
 * skeleton); earrings a stud or hoop (CPU) or a drop from the item image (its
 * mesh: POST /inventory/items/{item}/part-mesh, 1 hub job). The live dots are the piece's
 * centre line(s) on the body (POST …/curve with the unsaved description); a
 * small piece is framed close.
 *
 * Glasses (bug round 2026-11-20): the frame outline (four buttons), size step,
 * rim thickness, frame material (a metal, or acetate with its colour), the
 * temples' end, and the lenses — clear, or a sunglass tint with its opacity
 * and a mirror. Their size comes from the face; the dots are the rims, the
 * bridge and the temples where the Build lays them, with the live sizes.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { FigureBuildButton } from './FigureBuildButton'
import { Model3DViewer } from './Model3DViewer'
import {
  ACCESSORY_BAND_MATERIAL_LABELS, ACCESSORY_EARRING_LABELS, ACCESSORY_FINGER_LABELS, ACCESSORY_FOCUS_M,
  ACCESSORY_KIND_LABELS, ACCESSORY_METAL_LABELS, ACCESSORY_PART_NAMES, ACCESSORY_POSE_LABELS, ACCESSORY_SIDE_LABELS, ACCESSORY_STATE_COLOR,
  ACCESSORY_STATE_LABELS, ACCESSORY_STRAP_AT_LABELS, BAND_KINDS, PENDANT_STATE_COLOR, PENDANT_STATE_LABELS,
  TUBE_KINDS, dropPresetOf, pendantBoxPoints, GLASSES_FRAME_LABELS, GLASSES_SHAPE_LABELS, GLASSES_SIZE_LABELS,
  GLASSES_TEMPLE_LABELS, LENS_TINT_LABELS, earReason, glassesLine,
} from './figureModel'
import type { AccessoryInfo, AccessoryPendant, GlassesNumbers, GlassesSpec, Jewellery } from './figureModel'
import { PartLinkFields } from '../items/PartLinkFields'
import type { Jewellery as ItemJewellery } from '../items/itemsModel'

const CHIP: CSSProperties = { fontSize: '0.72em', padding: '1px 6px', borderRadius: 8 }
const GRID: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '6px 12px' }

function useAccessory(character: string, itemId: string) {
  const path = `/characters/${encodeURIComponent(character)}/figure/accessory/${encodeURIComponent(itemId)}`
  const [data, setData] = useState<AccessoryInfo | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try {
      setData(await apiGet<AccessoryInfo>(path))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [path])
  return { path, data, error, load }
}

/** The Wardrobe / Figure row's chip and button of an accessory piece. */
export function AccessoryPieceControls({ character, itemId, version = 0 }: {
  character: string
  itemId: string
  /** Bumped by the row on a mode change: re-read. */
  version?: number
}) {
  const { t } = useI18n()
  const { data, error, load } = useAccessory(character, itemId)
  const [open, setOpen] = useState(false)
  useEffect(() => { void load() }, [load, version])
  const state = data?.state
  return (
    <>
      {state ? (
        <span data-accessory-state={state} title={[t(ACCESSORY_STATE_LABELS[state] || state), t(data.reason)]
          .filter(Boolean).join('\n')}
          style={{ ...CHIP, border: `1px solid ${ACCESSORY_STATE_COLOR[state] || '#888'}` }}>
          {t(ACCESSORY_STATE_LABELS[state] || state)}
        </span>
      ) : null}
      <button type="button" className="ga-btn ga-btn-sm" aria-haspopup="dialog" style={{ marginLeft: 'auto' }}
        title={t("Kind, drop, material and linked parts of this accessory, with a 3D view; the piece is made on the CPU (0 hub jobs), a linked part's mesh is 1 hub job per part")}
        onClick={() => setOpen(true)}>
        {t('Accessory settings…')}
      </button>
      {data && state !== 'current' && data.reason ? (
        <span className="ga-hint" style={{ flexBasis: '100%', fontSize: '0.72em',
          color: state === 'failed' ? 'var(--danger, #f85149)' : 'var(--warning, #d29922)' }}>{t(data.reason)}</span>
      ) : null}
      {data?.pendant && !data.pendant.on_figure && data.pendant.reason ? (
        <span className="ga-hint" data-pendant-state={data.pendant.state} style={{ flexBasis: '100%', fontSize: '0.72em',
          color: ['refused', 'failed'].includes(data.pendant.state) ? 'var(--danger, #f85149)' : 'var(--warning, #d29922)' }}>
          {t(data.pendant.reason)}
        </span>
      ) : null}
      {error ? <span className="ga-hint" style={{ flexBasis: '100%', fontSize: '0.72em' }}>{error}</span> : null}
      {open ? (
        <AccessoryDialog character={character} itemId={itemId}
          onClose={() => { setOpen(false); void load() }} />
      ) : null}
    </>
  )
}

/** The accessory dialog: settings beside the 3D view (checklist points 2, 4, 7, 8, 9). */
export function AccessoryDialog({ character, itemId, onClose }: {
  character: string
  itemId: string
  onClose: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const { path, data, error, load } = useAccessory(character, itemId)
  const [draft, setDraft] = useState<Jewellery | null>(null)
  const [points, setPoints] = useState<Array<[number, number, number]>>([])
  const [anchor, setAnchor] = useState<{ at: [number, number, number]; out: [number, number, number] } | null>(null)
  // Design G: where each linked part of a belt goes (POST …/curve `anchors`), for the placeholder boxes
  const [linkAnchors, setLinkAnchors] = useState<Array<{ index: number; role: string;
    at: [number, number, number]; out: [number, number, number] }>>([])
  // Glasses: the live preview's sizes for the unsaved settings
  const [liveGlasses, setLiveGlasses] = useState<GlassesNumbers | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [pendantBusy, setPendantBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const seq = useRef(0)
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (data && !draft) setDraft(data.jewellery || { kind: data.suggested || 'necklace',
      chain: { drop_cm: 4, thickness_mm: 1.5, style: 'cable' }, metal: 'gold' })
  }, [data, draft])
  const drop = draft?.chain?.drop_cm ?? 4
  const thick = draft?.chain?.thickness_mm ?? 1.5
  // A234: the live rings of the other kinds (the shape fields only — the material does not move them).
  const shapeKey = draft && draft.kind !== 'necklace'
    ? JSON.stringify({ kind: draft.kind, band: draft.band, side: draft.side, finger: draft.finger,
      earring: draft.earring, chain: draft.chain, ring: draft.ring, glasses: draft.glasses,
      buckle: draft.buckle, charms: draft.charms })
    : ''
  useEffect(() => {
    if (!shapeKey) return
    const mine = ++seq.current
    const id = window.setTimeout(() => {
      apiPost<{ rings: Array<Array<[number, number, number]>>; glasses?: GlassesNumbers;
        anchors?: Array<{ index: number; role: string; at: [number, number, number]; out: [number, number, number] }> }>(
        `${path}/curve`, { jewellery: JSON.parse(shapeKey) })
        .then((r) => {
          if (mine !== seq.current) return
          setPoints(r.rings.flat()); setAnchor(null); setLiveGlasses(r.glasses || null); setPreviewError('')
          setLinkAnchors(r.anchors || [])
        })
        .catch((e) => {
          if (mine === seq.current) {
            setPoints([]); setLiveGlasses(null); setLinkAnchors([]); setPreviewError((e as Error).message)
          }
        })
    }, 150)
    return () => window.clearTimeout(id)
  }, [path, shapeKey])
  // The live centre line: the newest request wins (a slider sends many).
  useEffect(() => {
    if (!draft || draft.kind !== 'necklace') { if (!shapeKey) setPoints([]); return }
    const mine = ++seq.current
    const id = window.setTimeout(() => {
      apiPost<{ points: Array<[number, number, number]>; anchor?: [number, number, number];
        anchor_outward?: [number, number, number] }>(`${path}/curve`, { drop_cm: drop, thickness_mm: thick })
        .then((r) => {
          if (mine !== seq.current) return
          setPoints(r.points)
          setAnchor(r.anchor && r.anchor_outward ? { at: r.anchor, out: r.anchor_outward } : null)
        })
        .catch(() => { if (mine === seq.current) { setPoints([]); setAnchor(null) } })
    }, 120)
    return () => window.clearTimeout(id)
  }, [path, drop, thick, draft, shapeKey])
  const setChain = (key: 'drop_cm' | 'thickness_mm', v: number) =>
    setDraft((d) => (d ? { ...d, chain: { ...(d.chain || {}), [key]: v } } : d))
  // design G: a necklace's pendant is a linked part item
  const pendantOn = draft?.kind === 'necklace' && !!draft?.pendant?.item
  const pendantSize = draft?.pendant?.size_mm ?? data?.pendant_defaults?.size_mm ?? 18
  // A225: a cord is thicker — switching to one takes the cord default unless the thickness was moved off the chain's.
  const setMaterial = (m: string) => setDraft((d) => {
    if (!d || !data) return d
    const cord = data.cords.includes(m)
    const wasCord = data.cords.includes(d.metal || '')
    const chain = cord !== wasCord
      ? { ...(d.chain || {}), thickness_mm: cord ? data.cord_thickness_mm : 1.5 }
      : d.chain
    return { ...d, metal: m, chain }
  })
  // While unsaved, unbuilt or built without the pendant: a placeholder box at the chain's lowest point.
  const pendantRow: AccessoryPendant | null = data?.pendant || null
  // the earrings' drop is meshed from their own image (1 hub job): POST /inventory/items/{item}/part-mesh
  const buildPendant = async () => {
    setPendantBusy(true)
    try {
      const r = await apiPost<{ status: string }>(`/inventory/items/${encodeURIComponent(itemId)}/part-mesh`, {})
      toast(r.status === 'ready' ? t('The pendant is already built') : r.status === 'running'
        ? t('The pendant is being built') : t('Pendant job started (1 hub job)'), 'info')
      window.setTimeout(() => { void load() }, 2500)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPendantBusy(false)
    }
  }
  const stored = JSON.stringify(data?.jewellery || null)
  const dirty = !!draft && JSON.stringify({ ...(data?.jewellery || {}), ...draft }) !== stored
  const partRows = data?.parts || []
  const necklaceRow = partRows.find((r) => r.role === 'pendant')
  const showBox = pendantOn && !!anchor && (dirty || !necklaceRow?.on_figure)
  // a belt's links: a box at each link's place until the build carries that part
  const beltLinks = draft?.kind === 'belt'
    ? [...(draft.buckle?.item ? [{ role: 'buckle', index: 0, size: draft.buckle.size_mm ?? 50 }] : []),
      ...(draft.charms || []).map((c, i) => ({ role: 'charm', index: i, size: c.size_mm ?? 25 }))]
    : []
  const boxDots = [
    ...(showBox && anchor ? pendantBoxPoints(anchor.at, anchor.out, pendantSize) : []),
    ...beltLinks.flatMap((l, k) => {
      const a = linkAnchors[k]
      const row = partRows.find((r) => r.role === l.role && r.index === l.index)
      return a && (dirty || !row?.on_figure) ? pendantBoxPoints(a.at, a.out, l.size) : []
    }),
  ]
  const save = async () => {
    if (!draft) return
    setSaving(true)
    try {
      // A216 review M1: the draft starts from what the server stored (normalised), never from the old load.
      const saved = await apiPut<{ jewellery: Jewellery }>(path, { jewellery: draft })
      setDraft(saved.jewellery)
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }
  const title = t('Accessory — {name}').replace('{name}', data?.name || itemId)
  const ranges = data?.ranges || {}
  const preset = dropPresetOf(drop, data?.drop_presets || {})
  const built = !!draft && !!data && data.built_kinds.includes(draft.kind)
  // A234: switching the kind takes that kind's width / thickness default.
  const setKind = (kind: string) => setDraft((d) => {
    if (!d || !data) return d
    const width = data.kind_widths?.[kind]
    const thickness = data.kind_thickness?.[kind]
    return { ...d, kind,
      // A238: a ring is on one hand
      side: kind === 'ring' && !(data.ring_sides || []).includes(d.side || '') ? data.ring_sides?.[0] : d.side,
      glasses: kind === 'glasses' ? (d.glasses || {}) : d.glasses,
      // a glasses frame is never a cord or a custom chain colour: the server stores the default metal then
      metal: kind === 'glasses' && (data.cords.includes(d.metal || '') || d.metal === 'custom') ? 'gold' : d.metal,
      band: width !== undefined ? { ...(d.band || {}), width_cm: width } : d.band,
      chain: thickness !== undefined && !data.cords.includes(d.metal || '')
        ? { ...(d.chain || {}), thickness_mm: thickness } : d.chain }
  })
  const isBand = !!draft && BAND_KINDS.includes(draft.kind)
  const isGlasses = draft?.kind === 'glasses'
  const focusM = draft ? ACCESSORY_FOCUS_M[draft.kind] || 0 : 0
  const focus = focusM && points.length ? {
    center: [0, 1, 2].map((k) => points.reduce((a, p) => a + p[k], 0) / points.length) as [number, number, number],
    radius: focusM,
  } : null
  const state = data?.state
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !saving) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={title} style={{ maxWidth: 1100 }}>
        <div className="ga-modal-header"><h3>{title}</h3></div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
          {!data && !error ? <div className="ga-hint">{t('Loading…')}</div> : null}
          {error ? <div role="alert">{error}</div> : null}
          {data && draft ? (
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 420px', minWidth: 0 }}>
                <Model3DViewer key={data.glb_url} url={data.glb_url} format="glb" height={460} subject="figure"
                  builtAt={state === 'current' ? data.built_at : null}
                  figureHeight={focus ? 0 : 1.7} scaleFigure={!focus} focus={focus}
                  surfacePoints={[
                    ...points.map((at) => ({ at, color: dirty || state !== 'current' ? '#ffb000' : '#d4af37' })),
                    ...boxDots.map((at) => ({ at, color: '#58a6ff' })),
                  ]} />
                <div className="ga-hint" style={{ fontSize: '0.75em' }}>
                  {draft.kind === 'necklace'
                    ? t('Drag rotates the body, Shift+drag moves it. The dots are the chain for the values beside it; the 1.70 m figure gives the scale.')
                    : focus ? t('Drag rotates the body, Shift+drag moves it. The dots are the piece for the values beside it, on the body\'s surface; the view is framed close on it.')
                      : t('Drag rotates the body, Shift+drag moves it. The dots are the piece for the values beside it, on the body\'s surface (the clothing under it is taken by Build); the 1.70 m figure gives the scale.')}
                  {boxDots.length ? ' ' + t('A blue box is where a linked part goes, at its size, until the build carries it.') : ''}
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: '1 1 300px', minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span data-accessory-state={state}
                    title={t(data.reason)}
                    style={{ ...CHIP, border: `1px solid ${ACCESSORY_STATE_COLOR[state || ''] || '#888'}` }}>
                    {t(ACCESSORY_STATE_LABELS[state || ''] || state || '')}
                  </span>
                  <span className="ga-hint" style={{ fontSize: '0.75em' }}>{t(data.reason)}</span>
                </div>
                <div style={GRID}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="ga-form-hint">{t('Kind')}</span>
                    <select className="ga-input" value={draft.kind}
                      onChange={(e) => setKind(e.target.value)}>
                      {data.kinds.map((k) => (
                        <option key={k} value={k}>
                          {t(ACCESSORY_KIND_LABELS[k] || k)}
                          {!data.built_kinds.includes(k) ? ` (${t('not built yet')})` : ''}
                        </option>
                      ))}
                    </select>
                    {data.suggested && data.suggested !== draft.kind ? (
                      <button type="button" className="ga-btn ga-btn-sm"
                        onClick={() => setKind(data.suggested || draft.kind)}>
                        {t('Use suggested: {kind}').replace('{kind}', t(ACCESSORY_KIND_LABELS[data.suggested] || data.suggested))}
                      </button>
                    ) : null}
                  </label>
                  {isBand ? (
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span className="ga-form-hint">{t('Band material')}</span>
                      <select className="ga-input" value={draft.band?.material || 'from_image'}
                        onChange={(e) => setDraft({ ...draft, band: { ...(draft.band || {}), material: e.target.value } })}>
                        {(data.band_materials || []).map((m) => (
                          <option key={m} value={m}>{t(ACCESSORY_BAND_MATERIAL_LABELS[m] || m)}</option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  {!isGlasses && (!isBand || draft.band?.material === 'metal') ? (
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span className="ga-form-hint">{t(isBand ? 'Metal' : 'Material')}</span>
                      <select className="ga-input" value={draft.metal || 'gold'}
                        onChange={(e) => setMaterial(e.target.value)}>
                        {data.metals.filter((m) => m !== 'custom' && (!isBand || !data.cords.includes(m))).map((m) => (
                          <option key={m} value={m}>{t(ACCESSORY_METAL_LABELS[m] || m)}</option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                </div>
                {isGlasses ? (
                  <GlassesFields data={data} draft={draft} setDraft={setDraft} />
                ) : draft.kind !== 'necklace' ? (
                  <AroundFields data={data} draft={draft} setDraft={setDraft} />
                ) : null}
                {isGlasses && previewError ? (
                  <div className="ga-hint" role="alert" style={{ fontSize: '0.75em', color: 'var(--danger, #f85149)' }}>
                    {previewError}
                  </div>
                ) : null}
                {isGlasses && liveGlasses && (dirty || state !== 'current') ? (
                  <div className="ga-hint" style={{ fontSize: '0.75em' }}
                    title={t('The sizes for the values beside it, from the face; the Build may still move the lenses forward to clear the brow')}>
                    {t('Preview')}: {glassesLine(liveGlasses, t)}
                  </div>
                ) : null}
                {draft.kind === 'earrings' && draft.earring?.style === 'drop' ? (
                  <ImagePartFields data={data} draft={draft} setDraft={setDraft} row={pendantRow} dirty={dirty}
                    busy={pendantBusy} onBuild={() => { void buildPendant() }} />
                ) : null}
                {draft.kind === 'belt' ? (
                  <PartLinkFields hostId={itemId} jewellery={draft as unknown as ItemJewellery} dirty={dirty}
                    options={data.part_options || []} rows={partRows}
                    onChange={(next) => setDraft(next as unknown as Jewellery)}
                    onChanged={() => { setDraft(null); void load() }} />
                ) : null}
                {draft.kind === 'necklace' ? (
                  <>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span className="ga-form-hint">
                        {t('Drop below the neck notch')}: {drop.toFixed(1)} cm{preset ? ` · ${t(preset)}` : ''}
                      </span>
                      <input type="range" aria-label={t('Drop below the neck notch')}
                        min={ranges.drop_cm?.[0] ?? 0} max={ranges.drop_cm?.[1] ?? 30} step={0.5} value={drop}
                        onChange={(e) => setChain('drop_cm', Number(e.target.value))} />
                      <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {Object.entries(data.drop_presets).map(([name, cm]) => (
                          <button key={name} type="button" className="ga-btn ga-btn-sm"
                            onClick={() => setChain('drop_cm', cm)}>{t(name)} {cm} cm</button>
                        ))}
                      </span>
                    </label>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span className="ga-form-hint">{t('Chain thickness')}: {thick.toFixed(1)} mm</span>
                      <input type="range" aria-label={t('Chain thickness')}
                        min={ranges.thickness_mm?.[0] ?? 0.5} max={ranges.thickness_mm?.[1] ?? 6} step={0.1}
                        value={thick} onChange={(e) => setChain('thickness_mm', Number(e.target.value))} />
                    </label>
                    <PartLinkFields hostId={itemId} jewellery={draft as unknown as ItemJewellery} dirty={dirty}
                      options={data.part_options || []} rows={partRows}
                      onChange={(next) => setDraft(next as unknown as Jewellery)}
                      onChanged={() => { setDraft(null); void load() }} />
                  </>
                ) : null}
                {!built ? (
                  <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>
                    {t('This kind is stored but not built yet in this version.')}
                  </div>
                ) : null}
                {/* A238 review: the numbers are the STORED build's — shown only while the draft keeps the stored
                    kind (a ring's metrics and the others' share no field), the line picked by what they carry */}
                {data.metrics && data.jewellery?.kind !== draft.kind ? null
                  : data.metrics && data.metrics.frame_mm !== undefined ? (
                  <div className="ga-hint" style={{ fontSize: '0.75em' }}
                    title={t('The glasses\' size comes from the face: the nose root and the nose\'s width set the bridge, the head\'s width the frame. Gap: the smallest distance from the frame to the face; the nose pads keep about 1 mm.')}>
                    {glassesLine(data.metrics, t)}
                    {' · '}{data.metrics.triangles} {t('triangles')}
                    {' · '}{t('gap')} {data.metrics.gap_mm?.min ?? '–'} mm
                    {data.metrics.pad_gap_mm != null ? ` · ${t('nose pads')} ${data.metrics.pad_gap_mm} mm` : ''}
                    {data.metrics.forward_mm ? ` · ${t('moved forward to clear the brow')} ${data.metrics.forward_mm} mm` : ''}
                    {Object.values(data.metrics.ear_used || {}).some((u) => !u) ? (
                      <div>{t('Ear not used — the temple runs straight back')} ({earReason(data.metrics, t)})</div>
                    ) : null}
                  </div>
                ) : data.metrics && data.metrics.inner_radius_mm !== undefined ? (
                  <div className="ga-hint" style={{ fontSize: '0.75em' }}
                    title={t('The ring\'s size comes from the skeleton: the hand\'s width across the knuckles and the length of the finger\'s first bone, within a range set by the body\'s height. It is not measured on the skin, so it can cut into a thick finger.')}>
                    {t('Inner radius')}: {data.metrics.inner_radius_mm ?? '–'} mm
                    {' · '}{t('hand width')}: {data.metrics.hand_width_mm ?? '–'} mm
                    {' · '}{t('finger bone')}: {data.metrics.bone_length_mm ?? '–'} mm
                    {data.metrics.clamped ? ` · ${t('limited to the range for this height')}` : ''}
                    {' · '}{data.metrics.triangles} {t('triangles')}
                  </div>
                ) : data.metrics ? (
                  <div className="ga-hint" style={{ fontSize: '0.75em' }}
                    title={draft.kind === 'necklace'
                      ? t('Distance from the chain to the skin along the whole chain, in the rest pose')
                      : t('Distance from the piece to the layer under it (skin or clothing) in the rest pose; the poses: the smallest distance to the body in the rest, walk, sit and run test poses')}>
                    {t(draft.kind === 'necklace' ? 'Gap to the skin' : 'Gap to the layer under it')}: {data.metrics.gap_mm?.min ?? '–'}–{data.metrics.gap_mm?.p95 ?? '–'} mm
                    {' · '}{t('inside the body')}: {Math.round((data.metrics.inside_share || 0) * 100)} %
                    {data.metrics.on_clothing_share !== undefined
                      ? ` · ${t('on clothing')}: ${Math.round(data.metrics.on_clothing_share * 100)} %` : ''}
                    {' · '}{data.metrics.triangles} {t('triangles')}
                    {data.metrics.poses && draft.kind !== 'necklace' ? (
                      <div>{Object.entries(data.metrics.poses).map(([pose, m]) =>
                        `${t(ACCESSORY_POSE_LABELS[pose] || pose)} ${m.gap_min_mm} mm`).join(' · ')}</div>
                    ) : null}
                  </div>
                ) : null}
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={!dirty || saving}
                    onClick={() => { void save() }}>{t('Save')}</button>
                  <span className="ga-hint" style={{ fontSize: '0.75em' }}>
                    {dirty ? t(draft.kind === 'necklace' ? 'Saving spends nothing; the chain is made again on the next Build (CPU, 0 hub jobs).'
                      : 'Saving spends nothing; the piece is made again on the next Build (CPU, 0 hub jobs).')
                      : t('Saved')}
                  </span>
                </div>
                <FigureBuildButton character={character} onStarted={() => { window.setTimeout(() => { void load() }, 2500) }} />
              </div>
            </div>
          ) : null}
        </div>
        <div className="ga-modal-footer">
          <button type="button" className="ga-btn" disabled={saving} onClick={onClose}>{t('Close')}</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

type SetDraft = (f: (d: Jewellery | null) => Jewellery | null) => void

function Slider({ label, value, unit, min, max, step, digits = 1, onChange, hint }: {
  label: string; value: number; unit: string; min: number; max: number; step: number; digits?: number
  onChange: (v: number) => void; hint?: string
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }} title={hint}>
      <span className="ga-form-hint">{label}: {value.toFixed(digits)} {unit}</span>
      <input type="range" aria-label={label} min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

function Choice({ label, value, options, labels, onChange }: {
  label: string; value: string; options: string[]; labels: Record<string, string>; onChange: (v: string) => void
}) {
  const { t } = useI18n()
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="ga-form-hint">{label}</span>
      <select className="ga-input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o} value={o}>{t(labels[o] || o)}</option>)}
      </select>
    </label>
  )
}

/** A234: the shape fields of a band / tube / earrings (every field saves with Save, no job). */
function AroundFields({ data, draft, setDraft }: { data: AccessoryInfo; draft: Jewellery; setDraft: SetDraft }) {
  const { t } = useI18n()
  const ranges = data.ranges || {}
  const kind = draft.kind
  const band = draft.band || {}
  const setBand = (key: string, v: number | string) => setDraft((d) => (d ? { ...d, band: { ...(d.band || {}), [key]: v } } : d))
  const setField = (key: string, v: unknown) => setDraft((d) => (d ? { ...d, [key]: v } : d))
  const isBand = BAND_KINDS.includes(kind)
  const isTube = TUBE_KINDS.includes(kind)
  const isRing = kind === 'ring'
  const strapAt = band.at || 'thigh'
  const paired = ['anklet', 'bracelet', 'ring', 'earrings'].includes(kind) || (kind === 'strap' && strapAt !== 'chest')
  const along = draft.ring?.along ?? 0.5
  const height = band.height_cm ?? 0
  const width = band.width_cm ?? data.kind_widths?.[kind] ?? 4
  const thick = draft.chain?.thickness_mm ?? data.kind_thickness?.[kind] ?? 1.5
  const ear = draft.earring || {}
  const heightLabel = kind === 'belt' ? t('Height (from the waist, or just under the waistband of trousers worn under it)')
    : isBand || isTube ? t('Height (along the body part; + toward the trunk / up)') : ''
  const [hMin, hMax] = isTube ? [-5, 5] : kind === 'choker' ? [-3, 3] : [-15, 15]
  return (
    <div style={{ ...GRID }}>
      {kind === 'strap' ? (
        <Choice label={t('Where it goes round')} value={strapAt} options={data.strap_at || []}
          labels={ACCESSORY_STRAP_AT_LABELS} onChange={(v) => setBand('at', v)} />
      ) : null}
      {paired ? (
        <Choice label={t(isRing ? 'Hand' : 'Body side')} value={draft.side || (isRing ? 'left' : 'both')}
          options={(isRing ? data.ring_sides : data.sides) || []} labels={ACCESSORY_SIDE_LABELS}
          onChange={(v) => setField('side', v)} />
      ) : null}
      {kind === 'ring' ? (
        <Choice label={t('Finger')} value={draft.finger || 'ring'} options={data.fingers || []}
          labels={ACCESSORY_FINGER_LABELS} onChange={(v) => setField('finger', v)} />
      ) : null}
      {kind === 'earrings' ? (
        <Choice label={t('Style')} value={ear.style || 'stud'} options={data.earring_styles || []}
          labels={ACCESSORY_EARRING_LABELS} onChange={(v) => setField('earring', { ...ear, style: v })} />
      ) : null}
      {heightLabel ? (
        <Slider label={heightLabel} value={height} unit="cm" min={hMin} max={hMax} step={isTube ? 0.1 : 0.5}
          onChange={(v) => setBand('height_cm', v)} />
      ) : null}
      {isRing ? (
        <Slider label={t('Place along the finger (from the knuckle)')} value={Math.round(along * 100)} unit="%" digits={0}
          min={Math.round((ranges.ring_along?.[0] ?? 0.15) * 100)} max={Math.round((ranges.ring_along?.[1] ?? 0.85) * 100)}
          step={1} onChange={(v) => setField('ring', { ...(draft.ring || {}), along: v / 100 })} />
      ) : null}
      {isBand ? (
        <Slider label={t('Width')} value={width} unit="cm" min={ranges.width_cm?.[0] ?? 0.5}
          max={ranges.width_cm?.[1] ?? 12} step={0.1} onChange={(v) => setBand('width_cm', v)} />
      ) : null}
      {isRing ? (
        <Slider label={t('Band width')} value={width * 10} unit="mm" min={(ranges.ring_width_cm?.[0] ?? 0.15) * 10}
          max={(ranges.ring_width_cm?.[1] ?? 1.2) * 10} step={0.5} onChange={(v) => setBand('width_cm', v / 10)} />
      ) : null}
      {isTube || isRing || (kind === 'earrings' && ear.style === 'hoop') ? (
        <Slider label={t(kind === 'earrings' ? 'Wire thickness' : 'Thickness')} value={thick} unit="mm"
          min={ranges.thickness_mm?.[0] ?? 0.5} max={ranges.thickness_mm?.[1] ?? 6} step={0.1}
          onChange={(v) => setDraft((d) => (d ? { ...d, chain: { ...(d.chain || {}), thickness_mm: v } } : d))} />
      ) : null}
      {kind === 'earrings' && ear.style !== 'drop' ? (
        <Slider label={t(ear.style === 'hoop' ? 'Hoop diameter' : 'Stud size')} value={ear.size_mm ?? 6} unit="mm" digits={0}
          min={ranges.earring_mm?.[0] ?? 2} max={ranges.earring_mm?.[1] ?? 60} step={1}
          onChange={(v) => setField('earring', { ...ear, size_mm: v })} />
      ) : null}
      {isBand || isTube ? (
        <Choice label={t('Sits on')} value={band.layer || 'auto'} options={['auto', 'body']}
          labels={{ auto: 'The outermost clothing under it', body: 'The body' }} onChange={(v) => setBand('layer', v)} />
      ) : null}
    </div>
  )
}

/** Glasses: shape (four buttons), size, rim thickness, frame material and colour, temples, lenses (every field saves
 *  with Save, no job; the lenses and the frame colour re-assemble without a rebuild). */
function GlassesFields({ data, draft, setDraft }: { data: AccessoryInfo; draft: Jewellery; setDraft: SetDraft }) {
  const { t } = useI18n()
  const opts = data.glasses
  if (!opts) return null
  const ranges = data.ranges || {}
  const g: GlassesSpec = draft.glasses || {}
  const frame = g.frame || 'metal'
  const lens = g.lens || {}
  const tint = lens.tint || 'clear'
  const sun = tint !== 'clear'
  const set = (patch: Partial<GlassesSpec>) => setDraft((d) => (d ? { ...d, glasses: { ...(d.glasses || {}), ...patch } } : d))
  const setLens = (patch: GlassesSpec['lens']) => set({ lens: { ...lens, ...patch } })
  const rim = g.rim_mm ?? opts.rim_mm[frame] ?? 2
  const opacity = lens.opacity ?? (sun ? opts.sun_opacity : opts.clear_opacity)
  const BOX: CSSProperties = { border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: '6px 8px',
    display: 'flex', flexDirection: 'column', gap: 6 }
  return (
    <>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="ga-form-hint">{t('Frame shape')}</span>
        <span role="group" aria-label={t('Frame shape')} style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {opts.shapes.map((s) => (
            <button key={s} type="button" aria-pressed={(g.shape || 'rectangular') === s}
              className={'ga-btn ga-btn-sm' + ((g.shape || 'rectangular') === s ? ' ga-btn-primary' : '')}
              onClick={() => set({ shape: s })}>{t(GLASSES_SHAPE_LABELS[s] || s)}</button>
          ))}
        </span>
      </div>
      <div style={GRID}>
        <Choice label={t('Size')} value={g.size || 'regular'} options={opts.sizes} labels={GLASSES_SIZE_LABELS}
          onChange={(v) => set({ size: v })} />
        <Choice label={t('Temples')} value={g.temple || 'hook'} options={opts.temples} labels={GLASSES_TEMPLE_LABELS}
          onChange={(v) => set({ temple: v })} />
        <Slider label={t('Rim thickness')} value={rim} unit="mm" min={ranges.rim_mm?.[0] ?? 0.8}
          max={ranges.rim_mm?.[1] ?? 5} step={0.1} onChange={(v) => set({ rim_mm: v })} />
        {/* switching the frame takes that frame's rim default */}
        <Choice label={t('Frame material')} value={frame} options={opts.frames} labels={GLASSES_FRAME_LABELS}
          onChange={(v) => set({ frame: v, rim_mm: opts.rim_mm[v] ?? rim })} />
        {frame === 'metal' ? (
          <Choice label={t('Metal')} value={draft.metal && !data.cords.includes(draft.metal) && draft.metal !== 'custom'
            ? draft.metal : 'gold'}
            options={data.metals.filter((m) => m !== 'custom' && !data.cords.includes(m))} labels={ACCESSORY_METAL_LABELS}
            onChange={(v) => setDraft((d) => (d ? { ...d, metal: v } : d))} />
        ) : (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="ga-form-hint">{t('Frame colour')}</span>
            <input type="color" aria-label={t('Frame colour')} value={draft.color || opts.acetate_color}
              onChange={(e) => setDraft((d) => (d ? { ...d, color: e.target.value } : d))} />
          </label>
        )}
      </div>
      <fieldset style={BOX}>
        <legend className="ga-form-hint">{t('Lenses')}</legend>
        <span role="group" aria-label={t('Lenses')} style={{ display: 'flex', gap: 4 }}>
          <button type="button" aria-pressed={!sun} className={'ga-btn ga-btn-sm' + (!sun ? ' ga-btn-primary' : '')}
            onClick={() => setLens({ tint: 'clear', opacity: opts.clear_opacity, mirror: false })}>{t('Clear lenses')}</button>
          <button type="button" aria-pressed={sun} className={'ga-btn ga-btn-sm' + (sun ? ' ga-btn-primary' : '')}
            onClick={() => { if (!sun) setLens({ tint: 'grey', opacity: opts.sun_opacity }) }}>{t('Sunglasses')}</button>
        </span>
        {sun ? (
          <div style={GRID}>
            <Choice label={t('Tint')} value={tint} options={opts.tints.filter((x) => x !== 'clear')}
              labels={LENS_TINT_LABELS} onChange={(v) => setLens({ tint: v })} />
            {tint === 'custom' ? (
              <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span className="ga-form-hint">{t('Tint colour')}</span>
                <input type="color" aria-label={t('Tint colour')} value={lens.color || '#2b2b2b'}
                  onChange={(e) => setLens({ color: e.target.value })} />
              </label>
            ) : null}
          </div>
        ) : null}
        <Slider label={t('Lens opacity')} value={Math.round(opacity * 100)} unit="%" digits={0}
          min={Math.round((ranges.lens_opacity?.[0] ?? 0) * 100)} max={Math.round((ranges.lens_opacity?.[1] ?? 0.9) * 100)}
          step={1} onChange={(v) => setLens({ opacity: v / 100 })} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={!!lens.mirror} onChange={(e) => setLens({ mirror: e.target.checked })} />
          {t('Mirrored lenses')}
        </label>
        <span className="ga-hint" style={{ fontSize: '0.72em' }}>
          {t('Lenses and frame colour change the look only — the figure is put together again, nothing is rebuilt. Far away, clear lenses and the temples are left off.')}
        </span>
      </fieldset>
    </>
  )
}

/** A234: the earrings' drop from their own item image — the item's ONE hub job
 *  (POST /inventory/items/{item}/part-mesh), its size and its state. */
function ImagePartFields({ data, draft, setDraft, row, dirty, busy, onBuild }: {
  data: AccessoryInfo; draft: Jewellery; setDraft: SetDraft; row: AccessoryPendant | null; dirty: boolean
  busy: boolean; onBuild: () => void
}) {
  const { t } = useI18n()
  const part = ACCESSORY_PART_NAMES[draft.kind] || 'Earring drop'
  const size = draft.pendant?.size_mm ?? data.pendant_defaults?.size_mm ?? 18
  const set = (s: number) => setDraft((d) => (d ? { ...d, pendant: { size_mm: s } } : d))
  const ranges = data.ranges || {}
  return (
    <fieldset style={{ border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: '6px 8px',
      display: 'flex', flexDirection: 'column', gap: 6 }}>
      <legend className="ga-form-hint">{t(part)}</legend>
      <Slider label={t('Drop size (mm)')} value={size} unit="mm" digits={0}
        min={ranges.size_mm?.[0] ?? 3} max={Math.min(ranges.size_mm?.[1] ?? 120, 100)} step={1}
        onChange={(v) => set(v)} />
      {row ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span data-pendant-state={row.state} title={t(row.reason)}
            style={{ ...CHIP, border: `1px solid ${PENDANT_STATE_COLOR[row.state] || '#888'}` }}>
            {t(PENDANT_STATE_LABELS[row.state] || row.state)}
          </span>
          <span className="ga-hint" style={{ fontSize: '0.75em' }}>
            {row.on_figure && row.metrics ? `${row.metrics.size_mm} mm` : t(row.reason)}
          </span>
        </div>
      ) : null}
      <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={busy || dirty || !row || ['ready', 'running', 'no_image'].includes(row.state)}
          title={dirty ? t('Save first') : t('Makes the mesh from the item image; shared by everyone wearing this item')}
          onClick={onBuild}>
          {t('Build mesh (1 hub job)')}
        </button>
        <span className="ga-hint" style={{ fontSize: '0.72em' }}>{t('Size and placement are CPU only (0 hub jobs).')}</span>
      </span>
    </fieldset>
  )
}
