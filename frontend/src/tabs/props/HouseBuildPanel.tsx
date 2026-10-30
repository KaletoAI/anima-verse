import { useEffect, useRef, useState } from 'react'
import { Field } from '@anima/player-ui'
import { SliderInput } from '../../components/SliderInput'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../../lib/api'
import { SurfaceKindSelect } from '../world/SurfaceKindSelect'
import type { SurfaceKind } from '../world/worldTypes'
import type { HouseSpec } from './propTypes'

interface HouseStatus {
  spec: HouseSpec
  footprint_m: [number, number] | null
  error: string
  built: boolean
  running: boolean
  styles: { id: string; name: string }[]
  door_styles: { id: string; name: string }[]
  wall_kinds: SurfaceKind[]
}

export function HouseBuildPanel({ base, prepareBase, onBuilt, onChanged }: {
  base: string
  prepareBase: (label: string) => Promise<string | null>
  onBuilt: () => Promise<void>
  onChanged: () => Promise<unknown>
}) {
  const { t } = useI18n()
  const [status, setStatus] = useState<HouseStatus | null>(null)
  const [spec, setSpec] = useState<HouseSpec | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const callbacks = useRef({ onBuilt })
  callbacks.current = { onBuilt }
  const running = !!status?.running
  useEffect(() => {
    alive.current = true
    let cancelled = false
    void apiGet<HouseStatus>(`${base}/house`).then(data => {
      if (!cancelled) { setStatus(data); setSpec(data.spec) }
    }).catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true; alive.current = false }
  }, [base])
  useEffect(() => {
    if (!running) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const data = await apiGet<HouseStatus>(`${base}/house`)
        if (cancelled) return
        setStatus(data)
        setError('')
        if (!data.running) {
          setSpec(data.spec)
          await callbacks.current.onBuilt()
          return
        }
      } catch (e) { if (!cancelled) setError((e as Error).message) }
      if (!cancelled) timer = setTimeout(() => { void poll() }, 3000)
    }
    timer = setTimeout(() => { void poll() }, 3000)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [base, running])

  const action = async (kind: 'save' | 'build' | 'copy' | 'reset') => {
    if (!spec || busy || running) return
    setBusy(true); setError('')
    try {
      const target = await prepareBase(t('Build from Blender'))
      if (!target || !alive.current) return
      const saved = await apiPut<HouseSpec>(`${target}/house`, spec)
      if (!alive.current) return
      setSpec(saved)
      if (kind === 'build') {
        await apiPost(`${target}/house/build`, {})
        if (alive.current) setStatus(current => current ? { ...current, running: true, error: '' } : current)
      } else if (kind === 'reset') {
        const reset = await apiPost<{ spec: HouseSpec }>(`${target}/house/reset-footprint`, {})
        if (alive.current) setSpec(reset.spec)
      } else if (kind === 'copy') {
        const index = Number(target.substring(target.lastIndexOf('/') + 1))
        await apiPost(`${target.substring(0, target.lastIndexOf('/variants/'))}/house/copy-layout`, { from: index })
      }
      await onChanged()
      if (alive.current && kind !== 'build') setStatus(await apiGet<HouseStatus>(`${target}/house`))
    } catch (e) { if (alive.current) setError((e as Error).message) }
    finally { if (alive.current) setBusy(false) }
  }
  const colourLabels = { tint: t('Facade colour'), roof_tint: t('Roof colour'), frame_color: t('Frame colour'), door_color: t('Door colour') }
  if (!spec || !status) return <section><div className="ga-form-section-label">{t('Build from Blender')}</div>{error && <p role="alert">{error}</p>}</section>
  const overrides = spec.overrides
  const patch = (values: Partial<HouseSpec['overrides']>) => setSpec({ ...spec, overrides: { ...overrides, ...values } })
  const balcony = spec.balconies ?? { edge: 'front' as const, storeys: [], layout: 'per_window', depth_m: .9, railing: 'iron' }
  // Collapsed on ordinary props; open once the variant is a house or building.
  return <details className="ga-form" style={{ gap: 8 }} open={status.built || running || !!status.error || !!error}>
    <summary className="ga-form-section-label">{t('Build from Blender')}</summary>
    <p className="ga-hint">{t('House changes apply immediately after saving.')}</p>
    <div role="status">{running ? t('Building…') : status.built ? t('Built') : t('No house built')}</div>
    <div className="ga-hint">{status.footprint_m
      ? t('Footprint: {w} × {d} m').replace('{w}', status.footprint_m[0].toFixed(2)).replace('{d}', status.footprint_m[1].toFixed(2))
      : t("Set the prop's size first")}</div>
    {(error || status.error) && <p role="alert">{error || status.error}</p>}
    <fieldset disabled={busy || running} className="ga-fieldset">
      <div className="ga-form-row">
        <Field label={t('Style')}><select aria-label={t('Style')} className="ga-input" value={spec.style} onChange={e => setSpec({ ...spec, style: e.target.value })}>
          {status.styles.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select></Field>
        <Field label={t('Storeys')}><SliderInput value={spec.storeys} min={1} max={12} onChange={storeys => setSpec({ ...spec, storeys, balconies: spec.balconies ? { ...spec.balconies, storeys: spec.balconies.storeys.filter(s => s < storeys) } : null })} /></Field>
        <Field label={t('Storey height (m)')}><SliderInput value={spec.storey_m} min={2.6} max={4.5} step={.1} onChange={storey_m => setSpec({ ...spec, storey_m })} /></Field>
        <Field label={t('Units')}><SliderInput value={spec.units} min={1} max={Math.min(8, Math.max(1, Math.floor((status.footprint_m?.[0] ?? 20) / 2.5)))} onChange={units => setSpec({ ...spec, units })} /></Field>
      </div>
      <SurfaceKindSelect label="Wall material" value={spec.wall} kinds={status.wall_kinds} emptyLabel="Style default" onChange={wall => setSpec({ ...spec, wall })} labelWidth={120} />
      <Field label={t('Door style')}><select aria-label={t('Door style')} className="ga-input" value={spec.door.style} onChange={e => setSpec({ ...spec, door: { ...spec.door, style: e.target.value } })}>
        <option value="">{t('Style default')}</option>{status.door_styles.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select></Field>
      <Field label={t('Door position')}><SliderInput value={spec.door.at} min={.1} max={.9} step={.01} onChange={at => setSpec({ ...spec, door: { ...spec.door, at } })} /></Field>
      <Field label={t('Roof form')}><select aria-label={t('Roof form')} className="ga-input" value={overrides.roof_form ?? ''} onChange={e => patch({ roof_form: e.target.value || undefined })}>
        <option value="">{t('Style default')}</option>{[['gable', t('Gable')], ['hip', t('Hip')], ['shed', t('Shed')], ['flat', t('Flat')]].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select></Field>
      <Field label={t('Roof pitch (°)')}><SliderInput value={overrides.pitch_deg} min={5} max={60} step={1} fineStep={.5} clearable placeholder={t('Style default')} disabled={overrides.roof_form === 'flat'} onChange={pitch_deg => patch({ pitch_deg })} onClear={() => patch({ pitch_deg: undefined })} /></Field>
      <div className="ga-form-row">{(['tint', 'roof_tint', 'frame_color', 'door_color'] as const).map(key => <Field key={key} label={colourLabels[key]}>
        <input aria-label={colourLabels[key]} type="color" value={overrides[key] ?? '#ffffff'} onChange={e => patch({ [key]: e.target.value })} />
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => patch({ [key]: undefined })}>{t('Style default')}</button>
      </Field>)}</div>
      <Field label={t('Window frames')}><select aria-label={t('Window frames')} className="ga-input" value={overrides.frames ?? ''} onChange={e => patch({ frames: e.target.value || undefined })}>
        <option value="">{t('Style default')}</option>{[['none', t('None')], ['timber', t('Timber')], ['stone', t('Stone')], ['metal', t('Metal')]].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select></Field>
      <Field label={t('Shutters')}><SliderInput value={overrides.shutters} min={0} max={1} step={.01} clearable placeholder={t('Style default')} onChange={shutters => patch({ shutters })} onClear={() => patch({ shutters: undefined })} /></Field>
      <label><input type="checkbox" checked={!!overrides.shopfront} onChange={e => patch({ shopfront: e.target.checked })} /> {t('Shopfront')}</label>
      <fieldset className="ga-fieldset"><legend>{t('Balconies')}</legend>
        {Array.from({ length: spec.storeys - 1 }, (_, i) => i + 1).map(level => <label key={level}>
          <input type="checkbox" checked={balcony.storeys.includes(level)} onChange={e => setSpec({ ...spec, balconies: { ...balcony, storeys: e.target.checked ? [...balcony.storeys, level] : balcony.storeys.filter(v => v !== level) } })} /> {t('Storey {n}').replace('{n}', String(level))}
        </label>)}
        <Field label={t('Layout')}><select aria-label={t('Layout')} className="ga-input" value={balcony.layout} onChange={e => setSpec({ ...spec, balconies: { ...balcony, layout: e.target.value } })}>
          <option value="per_window">{t('Per window')}</option><option value="continuous">{t('Continuous')}</option>
        </select></Field>
        <Field label={t('Depth (m)')}><SliderInput value={balcony.depth_m} min={.5} max={1.6} step={.1} onChange={depth_m => setSpec({ ...spec, balconies: { ...balcony, depth_m } })} /></Field>
        <Field label={t('Railing')}><select aria-label={t('Railing')} className="ga-input" value={balcony.railing} onChange={e => setSpec({ ...spec, balconies: { ...balcony, railing: e.target.value } })}>
          <option value="iron">{t('Iron')}</option><option value="solid">{t('Solid')}</option><option value="glass">{t('Glass')}</option>
        </select></Field>
      </fieldset>
      <Field label={t('Ornament density')}><SliderInput min={0} max={1} step={.01} value={overrides.ornament_density ?? .5} onChange={ornament_density => patch({ ornament_density })} /></Field>
      <Field label={t('Seed')}><SliderInput min={0} max={2147483647} slider={false} value={spec.seed ?? 0} onChange={seed => setSpec({ ...spec, seed })} /></Field>
      {spec.units > 1 && Array.from({ length: spec.units }, (_, index) => <fieldset className="ga-fieldset" key={index}>
        <legend>{t('Unit {n} colours').replace('{n}', String(index + 1))}</legend>
        {(['tint', 'roof_tint', 'door_color'] as const).map(key => <Field key={key} label={colourLabels[key]}>
          <input type="color" aria-label={colourLabels[key]} value={spec.unit_overrides[index]?.[key] ?? '#ffffff'} onChange={e => {
            const units = [...spec.unit_overrides]
            units[index] = { ...units[index], [key]: e.target.value }
            setSpec({ ...spec, unit_overrides: units })
          }} />
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => {
            const units = [...spec.unit_overrides]
            units[index] = { ...units[index] }; delete units[index][key]
            setSpec({ ...spec, unit_overrides: units })
          }}>{t('Style default')}</button>
        </Field>)}
      </fieldset>)}
      <div className="ga-form-row">
        <button type="button" className="ga-btn" onClick={() => { void action('save') }}>{t('Save')}</button>
        <button type="button" className="ga-btn" onClick={() => { void action('build') }}>{t('Build')}</button>
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => { void action('reset') }}>{t('Reset footprint from size')}</button>
        <button type="button" className="ga-btn" onClick={() => { void action('copy') }}>{t('Copy layout to all variants')}</button>
      </div>
    </fieldset>
  </details>
}
