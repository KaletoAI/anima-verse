import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SliderInput } from '../../components/SliderInput'
import type { BlenderStatus } from '../../components/ModelGallery'
import { SurfaceKindSelect } from './SurfaceKindSelect'
import type { SurfaceKind } from './worldTypes'
import { HullStyleEditor, type HullStyle } from './HullStyleEditor'

type HullMaterials = { roof?: string; trim?: string; plinth?: string }
type RoofForm = 'gable' | 'hip' | 'shed' | 'flat'
interface HullDescription {
  style: string
  seed: number
  overrides: { storeys_total?: number; roof_form?: RoofForm; pitch_deg?: number; max_rise_m?: number; ornament_density: number; tint?: string; roof_tint?: string; blind_windows?: boolean; shopfront?: boolean; frame_color?: string; door_color?: string; shop_color?: string; awning_color?: string; materials?: HullMaterials }
}
interface HullStatus {
  ok: boolean
  error: string
  has_hull: boolean
  active: boolean
  stale: boolean
  pending: boolean
  description: HullDescription | null
  storeys_plan: number
  filler_levels: number
  styles: (HullStyle & { materials?: HullMaterials })[]
}

export function HullBuilder(props: {
  apiBase: string
  blender?: BlenderStatus
  pending: boolean
  onStarted: () => void
}) {
  // A location switch starts with a fresh form, even while an old request finishes.
  return props.blender?.usable ? <HullForm key={props.apiBase} {...props} /> : null
}

function HullForm({ apiBase, pending, onStarted }: {
  apiBase: string
  pending: boolean
  onStarted: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [status, setStatus] = useState<HullStatus | null>(null)
  const [desc, setDesc] = useState<HullDescription | null>(null)
  const [surfaceKinds, setSurfaceKinds] = useState<SurfaceKind[]>([])
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const path = `/world/locations/${apiBase}/hull`

  useEffect(() => {
    let cancelled = false
    void apiGet<HullStatus>(path).then((data) => {
      if (cancelled) return
      setStatus(data)
      setDesc((current) => current ?? data.description ?? {
        style: data.styles[0]?.id ?? '', seed: 0, overrides: { ornament_density: 0.5 },
      })
    }).catch((e: Error) => { if (!cancelled) toast(t('Error') + ': ' + e.message, 'error') })
    return () => { cancelled = true }
  }, [path, pending, t, toast])

  useEffect(() => {
    let cancelled = false
    void apiGet<SurfaceKind[]>('/assets/surface-textures').then((list) => {
      const byKind = new Map<string, SurfaceKind>()
      for (const entry of Array.isArray(list) ? list : []) {
        const kind = (entry?.kind || '').trim()
        if (!kind || byKind.has(kind)) continue
        byKind.set(kind, { ...entry, kind, name: (entry.name || '').trim() || kind, url: entry.url || '' })
      }
      if (!cancelled) setSurfaceKinds([...byKind.values()].sort((a, b) => a.name.localeCompare(b.name)))
    }).catch(() => { if (!cancelled) setSurfaceKinds([]) })
    return () => { cancelled = true }
  }, [])

  // A build that finishes before the panel's first poll never flips the
  // parent's `pending`, so the optimistic "Building…" set by `build` would
  // stand forever — this form asks the hull status itself until it is done.
  const building = !!status?.pending
  useEffect(() => {
    if (!building) return
    const id = setInterval(() => {
      void apiGet<HullStatus>(path).then(setStatus).catch(() => { /* next tick */ })
    }, 2000)
    return () => clearInterval(id)
  }, [building, path])

  const locked = busy || pending || !!status?.pending
  const selected = status?.styles.find((style) => style.id === desc?.style)
  const overrides = desc?.overrides
  const facadeStoreys = (status?.filler_levels ?? 0)
    + Math.max(0, (overrides?.storeys_total ?? 0) - (status?.storeys_plan ?? 0))
  const patch = (part: Partial<HullDescription['overrides']>) =>
    setDesc((current) => current ? { ...current, overrides: { ...current.overrides, ...part } } : current)

  const propose = async () => {
    setBusy(true)
    try {
      const data = await apiPost<{ description_json: HullDescription; llm: boolean }>(`${path}/propose`, {})
      setDesc(data.description_json)
      toast(data.llm ? t('proposed by the LLM') : t('default — no LLM answer'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }
  const build = async (description: HullDescription) => {
    setBusy(true)
    try {
      const data = await apiPost<{ ok: boolean; started: boolean }>(`${path}/generate`, { description })
      if (data.ok && data.started) {
        setStatus((current) => current ? { ...current, pending: true } : current)
        toast(t('Building…'))
        onStarted()
      }
    } catch (e) {
      const message = (e as Error).message
      toast(message.includes('too_large')
        ? t('This building is too large for one hull — split the outline or simplify it, or lower Storeys total.')
        : t('Error') + ': ' + message, 'error')
    } finally { setBusy(false) }
  }

  return <div className="ga-form ga-hull-builder" style={{ gap: 8, padding: 8, border: '1px solid var(--ga-border, #444)', borderRadius: 6 }}>
    <strong>{t('Building hull')}</strong>
    <span className="ga-hint" role="status">
      {pending || status?.pending ? t('Building…') : status?.active ? t('Active') : status?.has_hull ? t('Hull is not active') : t('No hull built')}
    </span>
    {status && !status.ok && status.error === 'no_outline'
      ? <div className="ga-hint">{t('This location has no building outline — draw one in the floor plan editor first.')}</div>
      : null}
    {status?.stale ? <div className="ga-hint">{t('Floor plan changed — hull is out of date')}
      {' '}<button className="ga-btn ga-btn-sm" disabled={locked || !status.description}
        onClick={() => { if (status.description) void build(status.description) }}>{t('Rebuild')}</button>
    </div> : null}
    {desc && overrides ? <>
      <div className="ga-hull-grid">
      <fieldset disabled={locked} className="ga-fieldset">
        <legend className="ga-fieldset-title">{t('Style')}</legend>
        <label><span>{t('Hull style')}</span>
          <select className="ga-input" value={desc.style} onChange={(e) => setDesc({ ...desc, style: e.target.value })}>
            {status?.styles.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}
          </select>
        </label>
        <span className="ga-hint">{selected?.description}</span>
        <button className="ga-btn ga-btn-sm" disabled={!selected} onClick={() => setEditing(true)}>{t('Edit hull style')}</button>
        <button className="ga-btn ga-btn-sm" onClick={() => { void propose() }}>{t('Suggest from description (LLM)')}</button>
      </fieldset>
      <fieldset disabled={locked} className="ga-fieldset">
        <legend className="ga-fieldset-title">{t('Shape')}</legend>
        <label><span>{t('Storeys total')}</span><input className="ga-input" type="number" min={0} max={40} step={1}
          value={overrides.storeys_total ?? 0} onChange={(e) => {
            const total = Math.max(0, Math.min(40, Math.trunc(Number(e.target.value) || 0)))
            setDesc((current) => {
              if (!current) return current
              const next = { ...current.overrides }
              if (total > 0) next.storeys_total = total
              else delete next.storeys_total
              return { ...current, overrides: next }
            })
          }} /></label>
        <span className="ga-hint">0 = {t('From floor plan')}</span>
        {facadeStoreys > 0 ? <span className="ga-hint">
          {t('{n} facade storeys (not enterable)').replace('{n}', String(facadeStoreys))}
        </span> : null}
        <label><span>{t('Form')}</span><select className="ga-input" value={overrides.roof_form ?? ''}
          onChange={(e) => patch({ roof_form: (e.target.value || undefined) as RoofForm | undefined })}>
          <option value="">{t('Style default')}</option>
          <option value="gable">{t('Gable')}</option><option value="hip">{t('Hip')}</option>
          <option value="shed">{t('Shed')}</option><option value="flat">{t('Flat')}</option>
        </select></label>
        <SliderInput style={{ display: 'flex', flexWrap: 'wrap' }} label={<span className="ga-hull-label">{t('Pitch (°)')}</span>} min={5} max={60} step={1} fineStep={0.5}
          value={overrides.pitch_deg} clearable placeholder={t('Style default')}
          disabled={overrides.roof_form === 'flat'} onChange={(pitch_deg) => patch({ pitch_deg })}
          onClear={() => patch({ pitch_deg: undefined })} />
        <SliderInput style={{ display: 'flex', flexWrap: 'wrap' }} label={<span className="ga-hull-label">{t('Max roof height (m)')}</span>} min={1.5} max={12} step={0.5} fineStep={0.1}
          value={overrides.max_rise_m} clearable placeholder={t('Style default ({value} m max)').replace('{value}', String(selected?.roof.max_rise_m ?? ''))}
          disabled={overrides.roof_form === 'flat'} onChange={(max_rise_m) => patch({ max_rise_m })}
          onClear={() => setDesc((current) => {
            if (!current) return current
            const next = { ...current.overrides }
            delete next.max_rise_m
            return { ...current, overrides: next }
          })} />
        {overrides.max_rise_m === undefined && selected ? <span className="ga-hint">
          {t('Lower of this and the wall height × {ratio}.').replace('{ratio}', String(selected.roof.max_rise_ratio))}
        </span> : null}
      </fieldset>
      <fieldset disabled={locked} className="ga-fieldset">
        <legend className="ga-fieldset-title">{t('Look')}</legend>
        <SliderInput style={{ display: 'flex', flexWrap: 'wrap' }} label={<span className="ga-hull-label">{t('Seed')}</span>} value={desc.seed} min={0} max={2147483647} slider={false}
          onChange={(seed) => setDesc({ ...desc, seed })}>
          <button className="ga-btn ga-btn-sm" aria-label={t('Random seed')}
            onClick={() => setDesc({ ...desc, seed: Math.floor(Math.random() * 2147483647) })}>🎲</button>
        </SliderInput>
        <SliderInput style={{ display: 'flex', flexWrap: 'wrap' }} label={<span className="ga-hull-label">{t('Ornament density')}</span>} min={0} max={1} step={0.01}
          value={overrides.ornament_density} onChange={(ornament_density) => patch({ ornament_density })} />
        {(['tint', 'roof_tint'] as const).map((slot) => <label key={slot}>
          <span>{slot === 'tint' ? t('Tint') : t('Roof tint')}</span>
          <span className="ga-hull-colour">
            <input type="color" value={overrides[slot] ?? '#ffffff'}
              onChange={(e) => patch({ [slot]: e.target.value })} />
            <button className="ga-btn ga-btn-sm" onClick={() => patch({ [slot]: undefined })}>{t('none')}</button>
            {!overrides[slot] ? <span className="ga-hint">{t('none')}</span> : null}
          </span>
        </label>)}
        <span className="ga-hint">{t('Overrides Tint for the roof.')}</span>
        <label><span>{t('Window frame colour')}</span>
          <span className="ga-hull-colour">
            <input type="color" value={overrides.frame_color ?? selected?.palette.frame ?? '#ffffff'}
              onChange={(e) => patch({ frame_color: e.target.value })} />
            <button className="ga-btn ga-btn-sm" onClick={() => patch({ frame_color: undefined })}>{t('none')}</button>
            {!overrides.frame_color ? <span className="ga-hint">{t('Style default ({value})').replace('{value}', selected?.palette.frame ?? '')}</span> : null}
          </span>
        </label>
        <label><span>{t('Door colour')}</span>
          <span className="ga-hull-colour">
            <input type="color" title={t('Painted doors only')} value={overrides.door_color ?? '#ffffff'}
              onChange={(e) => patch({ door_color: e.target.value })} />
            <button className="ga-btn ga-btn-sm" onClick={() => patch({ door_color: undefined })}>{t('none')}</button>
            {!overrides.door_color ? <span className="ga-hint">{t('Style default')}</span> : null}
            <span className="ga-hint">{t('Painted doors only')}</span>
          </span>
        </label>
        <label><input type="checkbox" checked={!!overrides.blind_windows}
          onChange={(e) => patch({ blind_windows: e.target.checked || undefined })} />{t('Fill blank walls with blind windows')}</label>
      </fieldset>
      <fieldset disabled={locked} className="ga-fieldset">
        <legend className="ga-fieldset-title">{t('Shopfront')}</legend>
        <label><input type="checkbox" checked={!!overrides.shopfront}
          onChange={(e) => patch({ shopfront: e.target.checked || undefined })} />{t('Shopfront ground floor')}</label>
        {(['shop_color', 'awning_color'] as const).map((slot) => {
          const colour = selected?.palette[slot === 'shop_color' ? 'shop' : 'awning'] ?? '#ffffff'
          return <label key={slot}>
            <span>{slot === 'shop_color' ? t('Shopfront colour') : t('Awning colour')}</span>
            <span className="ga-hull-colour">
              <input type="color" disabled={!overrides.shopfront} value={overrides[slot] ?? colour}
                onChange={(e) => patch({ [slot]: e.target.value })} />
              <button className="ga-btn ga-btn-sm" disabled={!overrides.shopfront}
                onClick={() => patch({ [slot]: undefined })}>{t('none')}</button>
              {!overrides[slot] ? <span className="ga-hint">{t('Style default ({value})').replace('{value}', colour)}</span> : null}
            </span>
          </label>
        })}
      </fieldset>
      <fieldset disabled={locked} className="ga-fieldset">
        <legend className="ga-fieldset-title">{t('Materials')}</legend>
        {(['roof', 'trim', 'plinth'] as const).map((slot) => {
          const kind = selected?.materials?.[slot] ?? ''
          const name = surfaceKinds.find((entry) => entry.kind === kind)?.name || kind || t('none')
          return <SurfaceKindSelect key={slot} label={slot === 'roof' ? 'Roof' : slot === 'trim' ? 'Trim' : 'Plinth'}
            labelWidth={72} kinds={surfaceKinds} value={overrides.materials?.[slot] ?? ''}
            emptyLabel={t('Style default ({kind})').replace('{kind}', name)}
            onChange={(value) => {
              const materials = { ...overrides.materials }
              if (value) materials[slot] = value
              else delete materials[slot]
              patch({ materials: Object.keys(materials).length ? materials : undefined })
            }} />
        })}
        <span className="ga-hint">{t('Wall textures per storey: floor plan → storey inspector (Wall / Shell).')}</span>
        <span className="ga-hint">{t('Textures changed? Build the hull again.')}</span>
      </fieldset>
      </div>
      <div className="ga-hull-footer">
        <button className="ga-btn ga-btn-primary" disabled={locked || !selected} onClick={() => { void build(desc) }}>{t('Build hull')}</button>
      </div>
    </> : null}
    {editing && selected ? <HullStyleEditor style={selected} onClose={() => setEditing(false)}
      onSaved={async () => { setStatus(await apiGet<HullStatus>(path)) }} /> : null}
  </div>
}
