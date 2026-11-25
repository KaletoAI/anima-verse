/**
 * PartFields — a part item's own fields in the Items form (design G, plan-anhaenger Task 8): its size (the longest
 * side), how it is attached by default (flat on the band / hanging), whether its front shows the other side of the
 * image (`flip`), who uses it, its mesh state and "Build mesh (1 hub job)". The image prompt is shown read-only with
 * Edit: before the image job the user sees that no host text is in it.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { PART_STATE_COLOR, PART_STATE_LABELS, openInItems } from './itemsModel'
import type { DraftItem, Jewellery } from './itemsModel'

const ROLE_LABELS: Record<string, string> = { buckle: 'Buckle', pendant: 'Pendant', charm: 'Charm' }

interface UsedBy { item_id: string; name: string; role: string; shared: boolean }

export function PartFields({ draft, onUpdate }: {
  draft: DraftItem
  onUpdate: <K extends keyof DraftItem>(key: K, value: DraftItem[K]) => void
}) {
  const { t } = useI18n()
  const [usedBy, setUsedBy] = useState<UsedBy[] | null>(null)
  const [mesh, setMesh] = useState<{ state: string; reason: string } | null>(null)
  const [version, setVersion] = useState(0)
  const [editPrompt, setEditPrompt] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const id = draft.isNew ? '' : draft.id
  useEffect(() => {
    if (!id) { setUsedBy(null); setMesh(null); return }
    let live = true
    apiGet<{ used_by: UsedBy[] }>(`/inventory/items/${encodeURIComponent(id)}/used-by`)
      .then((r) => { if (live) setUsedBy(r.used_by) }).catch(() => { if (live) setUsedBy([]) })
    apiGet<{ state: string; reason: string }>(`/inventory/items/${encodeURIComponent(id)}/part-mesh`)
      .then((r) => { if (live) setMesh(r) }).catch(() => { if (live) setMesh(null) })
    return () => { live = false }
  }, [id, version])
  const j: Jewellery = draft.jewellery || { kind: 'charm' }
  const charm = j.charm || {}
  const setCharm = (patch: Partial<NonNullable<Jewellery['charm']>>) =>
    onUpdate('jewellery', { ...j, kind: 'charm', charm: { ...charm, ...patch } })
  const build = async () => {
    if (!id) return
    setBusy(true); setError('')
    try {
      await apiPost(`/inventory/items/${encodeURIComponent(id)}/part-mesh`, {})
      window.setTimeout(() => setVersion((v) => v + 1), 2500)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const dirtyHint = t('Save first')
  return (
    <div className="ga-section" data-part-fields>
      <div className="ga-form-section-label">{t('Part')}</div>
      <div className="ga-hint" style={{ fontSize: '0.8em' }}>
        {t('Describe only the part here — its host says the rest. The image should show this part alone, front view.')}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 160px))', gap: '6px 12px', alignItems: 'end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="ga-form-hint">{t('Size, longest side (mm)')}</span>
          <input className="ga-input" type="number" min={3} max={120} step={1} value={charm.size_mm ?? 30}
            onChange={(e) => setCharm({ size_mm: Number(e.target.value) || 30 })} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="ga-form-hint">{t('Default attachment')}</span>
          <select className="ga-input" value={charm.mount || 'flat'}
            onChange={(e) => setCharm({ mount: e.target.value })}>
            <option value="flat">{t('Flat')}</option>
            <option value="hang">{t('Hanging')}</option>
          </select>
        </label>
        <label className="ga-form-check" style={{ alignSelf: 'center' }}>
          <input type="checkbox" checked={!!charm.flip} onChange={(e) => setCharm({ flip: e.target.checked })} />
          {t('Front shows the other side')}
        </label>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 6 }}>
        <span className="ga-form-hint">{t('Image prompt')}</span>
        {editPrompt ? (
          <input className="ga-input" value={draft.image_prompt}
            onChange={(e) => onUpdate('image_prompt', e.target.value)} />
        ) : (
          <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <code style={{ fontSize: '0.8em', whiteSpace: 'normal' }}>{draft.image_prompt || '—'}</code>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setEditPrompt(true)}>{t('Edit')}</button>
          </span>
        )}
      </div>
      {id ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
          {mesh ? (
            <span data-part-state={mesh.state} title={t(mesh.reason)}
              style={{ fontSize: '0.72em', padding: '1px 6px', borderRadius: 8,
                border: `1px solid ${PART_STATE_COLOR[mesh.state] || '#888'}` }}>
              {t(PART_STATE_LABELS[mesh.state] || mesh.state)}
            </span>
          ) : null}
          <button type="button" className="ga-btn ga-btn-sm"
            disabled={busy || !mesh || ['ready', 'running', 'no_image'].includes(mesh.state)}
            title={mesh?.state === 'no_image' ? t(mesh.reason) : t('Makes the mesh from this item\'s image; shared by every chain, belt and wearer that uses it')}
            onClick={() => { void build() }}>
            {t('Build mesh (1 hub job)')}
          </button>
          {mesh?.reason && mesh.state !== 'ready' ? <span className="ga-hint" style={{ fontSize: '0.75em' }}>{t(mesh.reason)}</span> : null}
        </div>
      ) : <span className="ga-hint" style={{ fontSize: '0.75em' }}>{dirtyHint}</span>}
      {id ? (
        <div style={{ marginTop: 6 }}>
          <span className="ga-form-hint">{t('Used by')}</span>
          {usedBy && usedBy.length ? (
            <ul style={{ margin: '2px 0 0 16px', padding: 0 }}>
              {usedBy.map((u) => (
                <li key={`${u.item_id}-${u.role}`}>
                  <button type="button" className="ga-btn ga-btn-sm" onClick={() => openInItems(u.item_id)}>{u.name}</button>
                  {' '}<span className="ga-hint">({t(ROLE_LABELS[u.role] || u.role)}{u.shared ? `, ${t('shared')}` : ''})</span>
                </li>
              ))}
            </ul>
          ) : <span className="ga-hint" style={{ marginLeft: 6 }}>{usedBy ? t('No chain or belt yet') : '…'}</span>}
        </div>
      ) : null}
      {error ? <div role="alert" className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{error}</div> : null}
    </div>
  )
}
