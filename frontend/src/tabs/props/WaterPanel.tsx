import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPatch, apiPost } from '../../lib/api'
import { useI18n } from '../../i18n/I18nProvider'
import type { ModelWater, WaterRegion } from './propTypes'

interface WaterResponse { status: 'none' | 'valid' | 'stale'; water: ModelWater | null }
const looks = ['Pool', 'Bath', 'Pond', 'Hot spring', 'Lake', 'Custom']
const presets = ['pool', 'bath', 'pond', 'hot_spring', 'lake', 'custom']

export function useModelWater(endpoint: string, revision: string | number,
  beforeImmediate?: (label: string) => Promise<boolean>,
  onChanged?: () => Promise<unknown>) {
  const [data, setData] = useState<WaterResponse>({ status: 'none', water: null })
  const [busy, setBusy] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [error, setError] = useState('')
  const [shape, setShape] = useState<'rect' | 'ellipse' | null>(null)
  const [size, setSize] = useState<[number, number]>([1, 1])
  const generation = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => {
    const gen = ++generation.current
    setData({ status: 'none', water: null })
    setShape(null)
    setBusy(false)
    setDetecting(false)
    setError('')
    if (endpoint) apiGet<WaterResponse>(endpoint).then(d => {
      if (generation.current === gen) setData(d)
    }).catch(e => { if (generation.current === gen) setError(String(e.message)) })
    return () => { generation.current = gen + 1; clearTimeout(timer.current) }
  }, [endpoint, revision])
  const patch = async (body: unknown) => {
    if (busy || detecting) return
    if (beforeImmediate && !await beforeImmediate('Change water')) return
    const gen = generation.current
    setBusy(true)
    setError('')
    try {
      const d = await apiPatch<WaterResponse>(endpoint, body)
      if (generation.current === gen) setData(d)
      await onChanged?.()
    } catch (e) { if (generation.current === gen) setError((e as Error).message) }
    finally { if (generation.current === gen) setBusy(false) }
  }
  const detect = async () => {
    if (beforeImmediate && !await beforeImmediate('Detect water')) return
    const gen = generation.current
    const stamp = data.water?.detected_at
    const deadline = Date.now() + 300000
    setDetecting(true)
    setShape(null)
    setError('')
    try {
      await apiPost(endpoint + '/detect', {})
      const poll = async () => {
        if (generation.current !== gen) return
        try {
          const d = await apiGet<WaterResponse>(endpoint)
          if (generation.current !== gen) return
          setData(d)
          if (d.water && d.water.detected_at !== stamp) {
            setDetecting(false)
            await onChanged?.()
            return
          }
          if (Date.now() >= deadline) { setError('Water detection timed out.'); setDetecting(false); return }
          timer.current = setTimeout(() => { void poll() }, 3000)
        } catch (e) {
          if (generation.current === gen) { setError((e as Error).message); setDetecting(false) }
        }
      }
      if (generation.current === gen) timer.current = setTimeout(() => { void poll() }, 3000)
    } catch (e) { if (generation.current === gen) { setError((e as Error).message); setDetecting(false) } }
  }
  const water = data.water
  const extent = water ? (water.measure === 'xyz' ? Math.max(...water.extent_snapped) : Math.max(water.extent_snapped[0], water.extent_snapped[2])) : 1
  const scale = water ? water.target_m / (extent || 1) : 1
  return { ...data, busy, detecting, error, shape, setShape, size, setSize, scale, patch, detect,
    pick: (point: [number, number, number]) => {
      if (!water || !shape) return
      void patch({ add: { shape, center: [point[0], point[2]], size: size.map(v => v / scale), level: point[1] - water.box_min[1] } })
      setShape(null)
    } }
}

/** Keep the drag local; publish its final value as soon as the gesture ends. */
function WaterRange({ value, min, max, step, onCommit, label }: {
  value: number; min: number; max: number; step: number; onCommit: (value: number) => void; label: string
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const commit = (input: HTMLInputElement) => {
    const parsed = input.valueAsNumber
    if (!Number.isFinite(parsed)) return
    const next = Math.min(max, Math.max(min, parsed))
    if (next !== value) onCommit(next)
  }
  return <><input type="range" aria-label={label} min={min} max={max} step={step} value={draft}
    onChange={e => setDraft(+e.target.value)}
    onPointerUp={e => commit(e.currentTarget)} onKeyUp={e => commit(e.currentTarget)}
    onBlur={e => commit(e.currentTarget)} />
    <input className="ga-input" type="number" aria-label={label} min={min} max={max} step={step}
      value={draft} style={{ width: 88 }} onChange={e => {
        const next = e.currentTarget.valueAsNumber
        if (Number.isFinite(next)) setDraft(Math.min(max, Math.max(min, next)))
      }} onBlur={e => commit(e.currentTarget)}
      onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
  </>
}

export function WaterPanel({ controller: c, onPlace }: { controller: ReturnType<typeof useModelWater>; onPlace?: () => void }) {
  const { t } = useI18n()
  const { setShape } = c
  const change = (r: WaterRegion, fields: object) => { void c.patch({ regions: [{ id: r.id, ...fields }] }) }
  useEffect(() => {
    const cancel = (e: KeyboardEvent) => { if (e.key === 'Escape') setShape(null) }
    window.addEventListener('keydown', cancel)
    return () => window.removeEventListener('keydown', cancel)
  }, [setShape])
  return <section className="ga-form" style={{ width: '100%', gap: 8 }}>
    <div className="ga-form-section-label">{t('Water')}</div>
    <p className="ga-hint">{t('Wird sofort angewendet. Verwerfen setzt Wasseränderungen nicht zurück.')}</p>
    <div aria-live="polite">{t(c.status === 'valid' ? 'Water detected' : c.status === 'stale' ? 'Water is stale — detect again' : 'No water detected')}
      {c.water && <> · {t('Regions')}: {c.water.regions.length}</>}
    </div>
    <button type="button" className="ga-btn ga-btn-sm" disabled={c.busy || c.detecting} onClick={() => { void c.detect() }}>
      {c.detecting ? <> <span className="tool-status-spinner" style={{ display: 'inline-block', verticalAlign: 'middle' }} /> {t('Detecting water…')}</> : t('Detect water')}
    </button>
    {c.error && <div role="alert" className="ga-hint">{t(c.error)}</div>}
    <fieldset disabled={c.busy || c.detecting} style={{ border: 0, padding: 0, margin: 0 }}>
      {c.water?.regions.map(r => <div key={r.id} className="ga-form" style={{ marginBottom: 12, gap: 6 }}>
        <label><input type="checkbox" checked={r.enabled} onChange={e => change(r, { enabled: e.target.checked })} /> {r.id} · {t(r.kind === 'basin' ? 'Basin' : r.kind === 'painted' ? 'Painted water' : 'Manual water')} · {t(r.confidence === 'sure' ? 'Sure' : 'Candidate')}</label>
        <span>{r.area_m2.toFixed(2)} m² · {t('Depth')}: {(r.depth_m * 100).toFixed(0)} cm</span>
        <label>{t('Look')} <select className="ga-input" value={r.look.preset} onChange={e => change(r, { look: e.target.value === 'custom' ? { ...r.look, preset: 'custom' } : { preset: e.target.value } })}>
          {presets.map((p, i) => <option key={p} value={p}>{t(looks[i])}</option>)}
        </select></label>
        {r.look.preset === 'custom' && <>
          <label>{t('Tint')} <input type="color" value={r.look.tint} onChange={e => change(r, { look: { ...r.look, tint: e.target.value } })} /></label>
          <div>{t('Clarity')} <WaterRange label={`${r.id}: ${t('Clarity')}`} min={0} max={1} step={0.01} value={r.look.clarity} onCommit={v => change(r, { look: { ...r.look, clarity: v } })} /></div>
        </>}
        <div>{t('Water level (cm)')} <WaterRange label={`${r.id}: ${t('Water level (cm)')}`} min={r.bed * c.scale * 100} max={(c.water!.box_max[1] - c.water!.box_min[1]) * c.scale * 100} step={1} value={r.level * c.scale * 100} onCommit={v => change(r, { level: v / (100 * c.scale) })} /> cm · {t('Depth')}: {(r.depth_m * 100).toFixed(0)} cm</div>
        {r.kind === 'manual' && <button type="button" className="ga-btn ga-btn-sm" onClick={() => { void c.patch({ remove: [r.id] }) }}>{t('Remove')}</button>}
      </div>)}
      {c.water && <>
        {(['rect', 'ellipse'] as const).map(s => <button type="button" className="ga-btn ga-btn-sm" key={s} onClick={() => { onPlace?.(); c.setShape(s) }}>{t(s === 'rect' ? 'Add rectangle' : 'Add ellipse')}</button>)}
        {c.shape && <div>
          {([0, 1] as const).map(i => <label key={i}>{t(i === 0 ? 'Width (m)' : 'Depth (m)')} <input className="ga-input" type="number" min={0.05} max={Math.max(10, c.water!.target_m)} step={0.05} value={c.size[i]} onChange={e => {
            const value = e.currentTarget.valueAsNumber
            if (Number.isFinite(value) && value >= 0.05) c.setSize(i === 0 ? [value, c.size[1]] : [c.size[0], value])
          }} /> m </label>)}
          <button type="button" className="ga-btn ga-btn-sm" onClick={onPlace}>{t('Place in viewer')}</button> {t('Click the model…')}
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => c.setShape(null)}>{t('Cancel')}</button>
        </div>}
      </>}
    </fieldset>
  </section>
}
