import { useEffect, useRef, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import { LayoutDraftPreview, type LayoutDraftNormalized, type LayoutDraftWarning } from '../world-dev/LayoutDraftPreview'

type Finding = LayoutDraftWarning | string
type Hull = { style: string; seed: number; overrides?: Record<string, unknown> }
type Proposal = {
  ok: boolean; error?: string; message?: string; draft: Record<string, unknown>
  normalized: LayoutDraftNormalized; warnings: Finding[]; errors: Finding[]; seed: number; hull: Hull | null
}
type Status = {
  state: 'idle' | 'running' | 'done' | 'failed'; snapshot_id: string
  steps: { id: 'floorplan' | 'hull' | 'furnish'; state: string; message: string; counts: Record<string, unknown> }[]
}

export function BuildingAssistantPanel({ locationId, unsaved, onReload }: {
  locationId: string; unsaved: boolean; onReload: () => void
}) {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [style, setStyle] = useState('')
  const [styles, setStyles] = useState<{ id: string; name: string }[]>([])
  const [revision, setRevision] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [status, setStatus] = useState<Status>({ state: 'idle', snapshot_id: '', steps: [] })
  const [busy, setBusy] = useState<'propose' | 'apply' | 'undo' | ''>('')
  const [error, setError] = useState('')
  const [applyErrors, setApplyErrors] = useState<Finding[]>([])
  const [confirmUndo, setConfirmUndo] = useState(false)
  const alive = useRef(true)
  const reload = useRef(onReload)
  reload.current = onReload
  const observed = useRef({ snapshot: '', floor: false, finished: false })
  const path = `/world/locations/${encodeURIComponent(locationId)}/building-assistant`
  const running = status.state === 'running'
  const locked = !!busy || running

  const finding = (item: Finding): string => {
    const code = typeof item === 'string' ? item : item.code
    switch (code) {
      case 'contour_split': return t('Rooms do not form one building')
      case 'contour_hole': return t('The rooms leave a hole')
      case 'storey_overhang': return t('An upper storey overhangs the one below')
      default: return typeof item === 'string' ? item : item.message || item.code
    }
  }
  const failure = (value: unknown) => {
    const data = value instanceof ApiError ? value.detail : value
    if (data && typeof data === 'object') {
      const body = data as { error?: string; message?: string; errors?: Finding[] }
      if (body.errors) setApplyErrors(body.errors)
      if (body.error === 'no_layout') return t('The assistant answered without a floor plan - try again.')
      if (body.error === 'busy') return t('A building job is already running. Try again when it finishes.')
      if (body.message || body.error) return body.message || body.error!
    }
    return value instanceof Error ? value.message : t('The request failed. Please try again.')
  }

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  useEffect(() => {
    let cancelled = false
    void apiGet<{ styles: { id: string; name: string }[] }>('/world/hull-styles')
      .then((data) => { if (!cancelled) setStyles(data.styles) })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    let fetching = false
    const poll = async () => {
      if (fetching) return
      fetching = true
      try {
        const next = await apiGet<Status>(`${path}/status`)
        if (cancelled) return
        setStatus(next)
        if (next.snapshot_id) {
          if (observed.current.snapshot !== next.snapshot_id) {
            observed.current = { snapshot: next.snapshot_id, floor: false, finished: false }
          }
          const floorDone = next.steps.some((step) => step.id === 'floorplan' && step.state === 'done')
          const finished = next.state === 'done' || next.state === 'failed'
          if ((floorDone && !observed.current.floor) || (finished && !observed.current.finished)) {
            observed.current.floor = floorDone
            observed.current.finished = finished
            reload.current()
          }
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      } finally { fetching = false }
    }
    void poll()
    const timer = running ? setInterval(() => { void poll() }, 2000) : undefined
    return () => { cancelled = true; if (timer !== undefined) clearInterval(timer) }
  }, [path, running])

  const propose = async (revise: boolean) => {
    if (locked) return
    setBusy('propose'); setError(''); setApplyErrors([])
    try {
      const result = await apiPost<Proposal>(`${path}/propose`, {
        text, style, ...(revise && proposal ? { previous: proposal.normalized, revision } : {}),
      })
      if (!alive.current) return
      if (!result.ok) { setError(failure(result)); return }
      setProposal(result); setRevision('')
    } catch (e) { if (alive.current) setError(failure(e)) }
    finally { if (alive.current) setBusy('') }
  }
  const apply = async () => {
    if (!proposal || locked || unsaved || proposal.errors.length) return
    setBusy('apply'); setError(''); setApplyErrors([])
    try {
      const result = await apiPost<{ ok: boolean; snapshot_id: string }>(`${path}/apply`, {
        draft: proposal.draft, hull: proposal.hull,
      })
      if (!alive.current) return
      if (!result.ok) { setError(failure(result)); return }
      setStatus({ state: 'running', snapshot_id: result.snapshot_id, steps: [
        { id: 'floorplan', state: 'done', message: '', counts: {} },
        { id: 'hull', state: 'pending', message: '', counts: {} },
        { id: 'furnish', state: 'pending', message: '', counts: {} },
      ] })
      observed.current = { snapshot: result.snapshot_id, floor: true, finished: false }
      reload.current()
    } catch (e) { if (alive.current) setError(failure(e)) }
    finally { if (alive.current) setBusy('') }
  }
  const undo = async () => {
    if (locked || unsaved) return
    setConfirmUndo(false); setBusy('undo'); setError('')
    try {
      const result = await apiPost<{ ok: boolean }>(`${path}/undo`, { snapshot_id: status.snapshot_id })
      if (!alive.current) return
      if (!result.ok) { setError(failure(result)); return }
      setStatus({ state: 'idle', snapshot_id: '', steps: [] }); setProposal(null); setApplyErrors([])
      reload.current()
    } catch (e) { if (alive.current) setError(failure(e)) }
    finally { if (alive.current) setBusy('') }
  }
  const errors = [...(proposal?.errors || []), ...applyErrors]
  const hull = proposal?.hull
  return <aside className="ga-plan-inspector" style={{ width: 360 }} aria-label={t('Building assistant')}>
    <div className="ga-form-section-label">{t('Building assistant')}</div>
    <div className="ga-plan-inspector-body ga-form">
      <label>{t('Describe the building')}
        <textarea className="ga-input" rows={4} maxLength={2000} value={text} disabled={locked}
          placeholder={t("A two-storey bakery: shop at the front, bakehouse behind, the baker's flat upstairs")}
          onChange={(e) => setText(e.target.value)} />
      </label>
      <label>{t('Style')}
        <select className="ga-input" value={style} disabled={locked} onChange={(e) => setStyle(e.target.value)}>
          <option value="">{t('Let the assistant choose')}</option>
          {styles.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
        </select>
      </label>
      <button className="ga-btn" disabled={locked || !text.trim()} onClick={() => { void propose(false) }}>
        {busy === 'propose' ? t('Designing...') : t('Propose')}</button>
      {error && <div role="alert" style={{ color: '#f85149' }}>{error}</div>}
      {proposal && <>
        <LayoutDraftPreview normalized={proposal.normalized} warnings={[]} />
        <table className="ga-table"><thead><tr>
          <th>{t('Name')}</th><th>{t('Storey')}</th><th>{t('Room type')}</th><th>{t('Area (m²)')}</th>
        </tr></thead><tbody>{proposal.normalized.rooms.map((room) => {
          const { outline, w, d } = room.layout
          const area = outline && outline.length >= 3 ? Math.abs(outline.reduce((sum, p, i) => {
            const q = outline[(i + 1) % outline.length]
            return sum + p[0] * q[1] - q[0] * p[1]
          }, 0)) / 2 : w * d
          return <tr key={room.room_id}><td>{room.name}</td><td>{room.layout.level ?? 0}</td>
            <td>{room.room_type || '—'}</td><td>{area.toFixed(1)}</td></tr>
        })}</tbody></table>
        <div>{t('Hull')}: {hull ? styles.find((entry) => entry.id === hull.style)?.name || hull.style : t('Let the assistant choose')}
          {' · '}{t('Seed')}: {hull?.seed ?? proposal.seed}
          {hull && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {([
              ['frame_color', t('Window frame colour')], ['shop_color', t('Shopfront colour')],
              ['awning_color', t('Awning colour')], ['door_color', t('Door colour')],
            ] as const).map(([key, label]) => typeof hull.overrides?.[key] === 'string' &&
              <span key={key} title={`${label}: ${hull.overrides[key]}`}>
                <span style={{ display: 'inline-block', width: 12, height: 12, backgroundColor: String(hull.overrides[key]), border: '1px solid #8b949e' }} /> {label}
              </span>)}
            <span>{t('Blind windows')}: {hull.overrides?.blind_windows ? t('Yes') : t('No')}</span>
            <span>{t('Shopfront')}: {hull.overrides?.shopfront ? t('Yes') : t('No')}</span>
          </div>}
        </div>
        {!!proposal.warnings.length && <div style={{ color: '#d29922' }}>{t('Warnings')}
          <ul>{proposal.warnings.map((item, i) => <li key={i}>{finding(item)}</li>)}</ul></div>}
        <label>{t('Change something')}<input className="ga-input" value={revision} disabled={locked}
          onChange={(e) => setRevision(e.target.value)} /></label>
        <button className="ga-btn" disabled={locked || !revision.trim() || !text.trim()} onClick={() => { void propose(true) }}>{t('Revise')}</button>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="ga-btn ga-btn-primary" disabled={locked || unsaved || !!errors.length} onClick={() => { void apply() }}>{t('Apply and build')}</button>
          <button className="ga-btn" disabled={locked} onClick={() => { setProposal(null); setApplyErrors([]); setRevision(''); setError('') }}>{t('Discard')}</button>
        </div>
      </>}
      {!!errors.length && <div role="alert" style={{ color: '#f85149' }}>{t('Errors')}
        <ul>{errors.map((item, i) => <li key={i}>{finding(item)}</li>)}</ul></div>}
      {unsaved && <div className="ga-form-hint">{t('Save the location before applying or undoing a building design.')}</div>}
      {!!status.steps.length && <div aria-live="polite">{status.steps.map((step) => <div key={step.id}>
        {step.state === 'done' ? '✓' : step.state === 'failed' ? '✗' : step.state === 'running' ? '⟳' : '○'}{' '}
        {step.id === 'floorplan' ? t('Floor plan') : step.id === 'hull' ? t('Hull') : t('Furniture')}: {' '}
        {step.state === 'running' ? t('Running...') : step.state === 'done' ? t('Done') : step.state === 'failed' ? t('Failed') : step.state === 'skipped' ? t('Skipped') : t('Pending')}
        {step.message ? ` · ${step.message}` : ''}
        {Object.keys(step.counts || {}).length ? <div className="ga-form-hint">{Object.entries(step.counts).map(([key, value]) => {
          const label = key === 'rooms' ? t('Rooms') : key === 'new_rooms' ? t('New rooms')
            : key === 'openings' ? t('Openings') : key === 'boundary_openings' ? t('Plot entrances')
              : key === 'stairs' ? t('Stairs') : key === 'skipped' ? t('Skipped') : key
          const detail = value && typeof value === 'object'
            ? Object.entries(value).map(([reason, count]) => `${reason}: ${count}`).join(', ')
            : String(value)
          return `${label}: ${detail}`
        }).join(' · ')}</div> : null}
      </div>)}</div>}
      {status.snapshot_id && !running && <button className="ga-btn" disabled={locked || unsaved} onClick={() => setConfirmUndo(true)}>{t('Undo')}</button>}
    </div>
    <ConfirmDialog open={confirmUndo} title={t('Restore this floor plan?')}
      message={t('Restore the previous floor plan and model selection? The new hull stays in the gallery.')}
      confirmLabel={t('Undo')} onClose={() => setConfirmUndo(false)} onConfirm={() => { void undo() }} />
  </aside>
}
