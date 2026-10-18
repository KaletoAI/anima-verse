import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SliderInput } from '../../components/SliderInput'
import type { BlenderStatus } from '../../components/ModelGallery'
import { HullStyleEditor, type HullStyle } from './HullStyleEditor'

type RoofForm = 'gable' | 'hip' | 'shed' | 'flat'
interface HullDescription {
  style: string
  seed: number
  overrides: { storeys_total?: number; roof_form?: RoofForm; pitch_deg?: number; ornament_density: number; tint?: string }
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
  styles: HullStyle[]
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

  return <div className="ga-form" style={{ gap: 8, padding: 8, border: '1px solid var(--ga-border, #444)', borderRadius: 6 }}>
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
      <fieldset disabled={locked} className="ga-form" style={{ border: 0, padding: 0, gap: 8 }}>
        <label>{t('Hull style')}{' '}
          <select className="ga-input" value={desc.style} onChange={(e) => setDesc({ ...desc, style: e.target.value })}>
            {status?.styles.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}
          </select>
        </label>
        <span className="ga-hint">{selected?.description}</span>
        <button className="ga-btn ga-btn-sm" disabled={!selected} onClick={() => setEditing(true)}>{t('Edit hull style')}</button>
        <SliderInput label={t('Seed')} value={desc.seed} min={0} max={2147483647} slider={false}
          onChange={(seed) => setDesc({ ...desc, seed })}>
          <button className="ga-btn ga-btn-sm" aria-label={t('Random seed')}
            onClick={() => setDesc({ ...desc, seed: Math.floor(Math.random() * 2147483647) })}>🎲</button>
        </SliderInput>
        <label>{t('Storeys total')}{' '}<input className="ga-input" type="number" min={0} max={40} step={1}
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
        <label>{t('Form')}{' '}<select className="ga-input" value={overrides.roof_form ?? ''}
          onChange={(e) => patch({ roof_form: (e.target.value || undefined) as RoofForm | undefined })}>
          <option value="">{t('Style default')}</option>
          <option value="gable">{t('Gable')}</option><option value="hip">{t('Hip')}</option>
          <option value="shed">{t('Shed')}</option><option value="flat">{t('Flat')}</option>
        </select></label>
        <SliderInput label={t('Pitch (°)')} min={5} max={60} step={1} fineStep={0.5}
          value={overrides.pitch_deg} clearable placeholder={t('Style default')}
          disabled={overrides.roof_form === 'flat'} onChange={(pitch_deg) => patch({ pitch_deg })}
          onClear={() => patch({ pitch_deg: undefined })} />
        <SliderInput label={t('Ornament density')} min={0} max={1} step={0.01}
          value={overrides.ornament_density} onChange={(ornament_density) => patch({ ornament_density })} />
        <label>{t('Tint')}{' '}<input type="color" value={overrides.tint ?? '#ffffff'}
          onChange={(e) => patch({ tint: e.target.value })} />{' '}
          <button className="ga-btn ga-btn-sm" onClick={() => patch({ tint: undefined })}>{t('none')}</button>
          {!overrides.tint ? <span className="ga-hint"> {t('none')}</span> : null}
        </label>
      </fieldset>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="ga-btn ga-btn-sm" disabled={locked} onClick={() => { void propose() }}>{t('Suggest from description (LLM)')}</button>
        <button className="ga-btn ga-btn-sm" disabled={locked || !selected} onClick={() => { void build(desc) }}>{t('Build hull')}</button>
      </div>
    </> : null}
    {editing && selected ? <HullStyleEditor style={selected} onClose={() => setEditing(false)}
      onSaved={async () => { setStatus(await apiGet<HullStatus>(path)) }} /> : null}
  </div>
}
