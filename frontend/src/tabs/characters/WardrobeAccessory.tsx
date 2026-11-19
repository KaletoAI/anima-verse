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
  ACCESSORY_KIND_LABELS, ACCESSORY_METAL_LABELS, ACCESSORY_STATE_COLOR, ACCESSORY_STATE_LABELS, dropPresetOf,
} from './figureModel'
import type { AccessoryInfo, Jewellery } from './figureModel'

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
        title={t('Kind, drop and metal of this accessory, with a 3D view; made on the CPU (0 hub jobs)')}
        onClick={() => setOpen(true)}>
        {t('Accessory settings…')}
      </button>
      {data && state !== 'current' && data.reason ? (
        <span className="ga-hint" style={{ flexBasis: '100%', fontSize: '0.72em',
          color: state === 'failed' ? 'var(--danger, #f85149)' : 'var(--warning, #d29922)' }}>{t(data.reason)}</span>
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
  const [saving, setSaving] = useState(false)
  const seq = useRef(0)
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (data && !draft) setDraft(data.jewellery || { kind: data.suggested || 'necklace',
      chain: { drop_cm: 4, thickness_mm: 1.5, style: 'cable' }, metal: 'gold' })
  }, [data, draft])
  const drop = draft?.chain?.drop_cm ?? 4
  const thick = draft?.chain?.thickness_mm ?? 1.5
  // The live centre line: the newest request wins (a slider sends many).
  useEffect(() => {
    if (!draft || draft.kind !== 'necklace') { setPoints([]); return }
    const mine = ++seq.current
    const id = window.setTimeout(() => {
      apiPost<{ points: Array<[number, number, number]> }>(`${path}/curve`, { drop_cm: drop, thickness_mm: thick })
        .then((r) => { if (mine === seq.current) setPoints(r.points) })
        .catch(() => { if (mine === seq.current) setPoints([]) })
    }, 120)
    return () => window.clearTimeout(id)
  }, [path, drop, thick, draft])
  const setChain = (key: 'drop_cm' | 'thickness_mm', v: number) =>
    setDraft((d) => (d ? { ...d, chain: { ...(d.chain || {}), [key]: v } } : d))
  const stored = JSON.stringify(data?.jewellery || null)
  const dirty = !!draft && JSON.stringify({ ...(data?.jewellery || {}), ...draft }) !== stored
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
                  figureHeight={1.7} scaleFigure
                  surfacePoints={points.map((at) => ({ at, color: dirty || state !== 'current' ? '#ffb000' : '#d4af37' }))} />
                <div className="ga-hint" style={{ fontSize: '0.75em' }}>
                  {t('Drag rotates the body, Shift+drag moves it. The dots are the chain for the values beside it; the 1.70 m figure gives the scale.')}
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
                      onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                      {data.kinds.map((k) => (
                        <option key={k} value={k}>
                          {t(ACCESSORY_KIND_LABELS[k] || k)}
                          {!data.built_kinds.includes(k) ? ` (${t('not built yet')})` : ''}
                        </option>
                      ))}
                    </select>
                    {data.suggested && data.suggested !== draft.kind ? (
                      <button type="button" className="ga-btn ga-btn-sm"
                        onClick={() => setDraft({ ...draft, kind: data.suggested || draft.kind })}>
                        {t('Use suggested: {kind}').replace('{kind}', t(ACCESSORY_KIND_LABELS[data.suggested] || data.suggested))}
                      </button>
                    ) : null}
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="ga-form-hint">{t('Metal')}</span>
                    <select className="ga-input" value={draft.metal || 'gold'}
                      onChange={(e) => setDraft({ ...draft, metal: e.target.value })}>
                      {data.metals.filter((m) => m !== 'custom').map((m) => (
                        <option key={m} value={m}>{t(ACCESSORY_METAL_LABELS[m] || m)}</option>
                      ))}
                    </select>
                  </label>
                </div>
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
                  </>
                ) : null}
                {!built ? (
                  <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>
                    {t('This kind is stored but not built yet in this version.')}
                  </div>
                ) : null}
                {data.metrics ? (
                  <div className="ga-hint" style={{ fontSize: '0.75em' }}
                    title={t('Distance from the chain to the skin along the whole chain, in the rest pose')}>
                    {t('Gap to the skin')}: {data.metrics.gap_mm?.min ?? '–'}–{data.metrics.gap_mm?.p95 ?? '–'} mm
                    {' · '}{t('inside the body')}: {Math.round((data.metrics.inside_share || 0) * 100)} %
                    {' · '}{data.metrics.triangles} {t('triangles')}
                  </div>
                ) : null}
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={!dirty || saving}
                    onClick={() => { void save() }}>{t('Save')}</button>
                  <span className="ga-hint" style={{ fontSize: '0.75em' }}>
                    {dirty ? t('Saving spends nothing; the chain is made again on the next Build (CPU, 0 hub jobs).')
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
