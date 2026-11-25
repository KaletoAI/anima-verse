/**
 * PartLinkFields — the part links of a chain or a belt (design G, plan-anhaenger Task 8).
 *
 * A necklace links one pendant item, a belt one buckle item and up to MAX_CHARMS charm items (each with its place on
 * the belt, flat or hanging, and a drop). A part item is an outfit piece without a slot (`jewellery.kind: charm`); it
 * has its own image and its own mesh (ONE hub job, shared by every host and wearer). "Make … item" creates a new part
 * item linked here and generates its image (1 image job, a prompt without the host's text); "Build mesh (1 hub job)"
 * makes the mesh of a linked part. Everything else is CPU (0 hub jobs).
 *
 * Used by the Items form (no character: the chips show the part mesh state) and the Wardrobe accessory dialog (the
 * rows of GET …/figure/accessory/{item} add whether the build carries the part and `host_mentions`).
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { thumbUrl } from '@anima/player-ui'
import {
  MAX_CHARMS, PART_STATE_COLOR, PART_STATE_LABELS, isPartItem, openInItems, partLinksOf, updateCharm, withCharm,
  withLink, withLinkSize, withoutCharm, type CharmAt, type Item, type Jewellery, type PartOption, type PartRowInfo,
} from './itemsModel'

const AT_LABELS: Record<string, string> = { front: 'Front', left_hip: 'Left hip', right_hip: 'Right hip', angle: 'Angle' }
const CHIP: CSSProperties = { fontSize: '0.72em', padding: '1px 6px', borderRadius: 8 }
const BOX: CSSProperties = { border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: '6px 8px',
  display: 'flex', flexDirection: 'column', gap: 6 }
const ROW: CSSProperties = { display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) repeat(3, minmax(0, 1fr)) auto',
  gap: 6, alignItems: 'end' }

/** Every part item of the world and the library, for a picker without the figure route (the Items form). */
function useOwnOptions(given: PartOption[] | null | undefined, version: number) {
  const [own, setOwn] = useState<PartOption[]>([])
  useEffect(() => {
    if (given) return
    let live = true
    apiGet<{ items: Array<Item & { part?: boolean }> }>('/inventory/items?include_shared=1')
      .then((r) => {
        if (!live) return
        setOwn(r.items.filter((i) => i.part || isPartItem(i)).map((i) => ({
          id: i.id, name: i.name || i.id, state: '',
          image_url: i.image ? `/inventory/items/${encodeURIComponent(i.id)}/image` : '',
        })).sort((a, b) => a.id.localeCompare(b.id)))
      })
      .catch(() => { if (live) setOwn([]) })
    return () => { live = false }
  }, [given, version])
  return given || own
}

/** The mesh state of each linked part (the Items form has no figure route): GET …/part-mesh per part. */
function usePartStates(ids: string[], given: PartRowInfo[] | undefined, version: number) {
  const [states, setStates] = useState<Record<string, { state: string; reason: string }>>({})
  const key = ids.join(',')
  useEffect(() => {
    if (given || !key) return
    let live = true
    Promise.all(key.split(',').map((id) => apiGet<{ state: string; reason: string }>(
      `/inventory/items/${encodeURIComponent(id)}/part-mesh`).then((r) => [id, r] as const)
      .catch(() => [id, { state: 'gone', reason: '' }] as const)))
      .then((pairs) => { if (live) setStates(Object.fromEntries(pairs)) })
    return () => { live = false }
  }, [key, given, version])
  return states
}

export function PartLinkFields({ hostId, jewellery, onChange, options, rows, dirty, onChanged }: {
  hostId: string
  jewellery: Jewellery
  onChange: (next: Jewellery) => void
  /** null: the component loads the parts itself. */
  options?: PartOption[] | null
  rows?: PartRowInfo[]
  /** Unsaved changes on the host: Make / Build wait for a save (the server writes the host's links). */
  dirty: boolean
  /** After a part was made or a mesh job started: re-read. */
  onChanged: () => void
}) {
  const { t } = useI18n()
  const [version, setVersion] = useState(0)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ id: string; text: string } | null>(null)
  const [error, setError] = useState('')
  const opts = useOwnOptions(options, version)
  const draft = { jewellery, jewellery_dirty: false }
  const links = partLinksOf(draft)
  const states = usePartStates(links.map((l) => l.item), rows, version)
  const isBelt = jewellery.kind === 'belt'
  const head: 'buckle' | 'pendant' = isBelt ? 'buckle' : 'pendant'
  const headLink = jewellery[head] || null
  const charms = isBelt ? jewellery.charms || [] : []

  const stateOf = (role: string, index: number, item: string) => {
    const row = rows?.find((r) => r.role === role && r.index === index && r.item === item)
    if (row) return row
    const st = states[item]
    return st ? { role, index, item, state: st.state, reason: st.reason } as PartRowInfo : null
  }
  const make = useCallback(async (role: 'buckle' | 'pendant' | 'charm') => {
    setBusy(`make-${role}`); setError('')
    try {
      const r = await apiPost<{ part_id: string }>(`/inventory/items/${encodeURIComponent(hostId)}/make-part`,
        { role, at: 'front' })
      setNotice({ id: r.part_id,
        text: t('Part item created — its image is being generated (1 image job). Describe it in Items, then Build mesh.') })
      setVersion((v) => v + 1)
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }, [hostId, onChanged, t])
  const buildMesh = useCallback(async (item: string) => {
    setBusy(`mesh-${item}`); setError('')
    try {
      const r = await apiPost<{ status: string }>(`/inventory/items/${encodeURIComponent(item)}/part-mesh`, {})
      setNotice({ id: item, text: r.status === 'ready' ? t('The mesh is already built')
        : r.status === 'running' ? t('The mesh is being built') : t('Mesh job started (1 hub job)') })
      window.setTimeout(() => { setVersion((v) => v + 1); onChanged() }, 2500)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }, [onChanged, t])

  const chip = (role: string, index: number, item: string) => {
    const row = stateOf(role, index, item)
    if (!row) return null
    return (
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span data-part-state={row.state} title={t(row.reason)}
          style={{ ...CHIP, border: `1px solid ${PART_STATE_COLOR[row.state] || '#888'}` }}>
          {t(PART_STATE_LABELS[row.state] || row.state)}
        </span>
        {row.on_figure && row.metrics?.size_mm ? (
          <span className="ga-hint" style={{ fontSize: '0.75em' }}>{row.metrics.size_mm} mm</span>
        ) : row.reason ? <span className="ga-hint" style={{ fontSize: '0.75em' }}>{t(row.reason)}</span> : null}
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={!!busy || dirty || ['ready', 'running', 'no_image', 'gone'].includes(row.state)}
          title={dirty ? t('Save first') : t('Makes the mesh from the part item\'s image; shared by every chain, belt and wearer that uses it')}
          onClick={() => { void buildMesh(item) }}>
          {t('Build mesh (1 hub job)')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => openInItems(item)}>{t('Open in Items')}</button>
        {row.host_mentions ? (
          <span className="ga-hint" style={{ flexBasis: '100%', fontSize: '0.75em', color: 'var(--warning, #d29922)' }}>
            {t("The chain's text also describes the part — remove it there so it is described once")}
          </span>
        ) : null}
      </span>
    )
  }
  const picker = (value: string, onPick: (id: string | null) => void, label: string) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span className="ga-form-hint">{label}</span>
      <select className="ga-input" value={value} onChange={(e) => onPick(e.target.value || null)}>
        <option value="">{t('none')}</option>
        {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        {value && !opts.some((o) => o.id === value) ? <option value={value}>{value} ({t('gone')})</option> : null}
      </select>
    </label>
  )
  const image = (item: string) => {
    const o = opts.find((x) => x.id === item)
    return o?.image_url ? (
      <img src={thumbUrl(o.image_url, 96)} alt={o.name} loading="lazy"
        style={{ width: 48, height: 48, objectFit: 'contain', borderRadius: 4, background: '#fff' }} />
    ) : null
  }

  return (
    <fieldset style={BOX} data-part-links={jewellery.kind}>
      <legend className="ga-form-hint">{isBelt ? t('Buckle and charms') : t('Pendant')}</legend>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0, 2fr) minmax(0, 1fr)', gap: 8, alignItems: 'end' }}>
        {headLink ? image(headLink.item) || <span style={{ width: 48 }} /> : <span style={{ width: 48 }} />}
        {picker(headLink?.item || '', (id) => onChange(withLink(draft, head, id).jewellery as Jewellery),
          isBelt ? t('Buckle item') : t('Pendant item'))}
        {headLink ? (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}
            title={t('Empty: the size stored on the part item')}>
            <span className="ga-form-hint">{t('Size (mm)')}</span>
            <input className="ga-input" type="number" min={3} max={120} step={1} placeholder={t("part's own")}
              value={headLink.size_mm ?? ''}
              onChange={(e) => onChange(withLinkSize(draft, head,
                e.target.value === '' ? null : Number(e.target.value)).jewellery as Jewellery)} />
          </label>
        ) : <span />}
      </div>
      {headLink ? chip(head, 0, headLink.item) : null}
      <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={!!busy || dirty}
          title={dirty ? t('Save first') : t('A new part item, linked here; its image is generated without the chain\'s or belt\'s text (1 image job)')}
          onClick={() => { void make(head) }}>
          {isBelt ? t('Make buckle item') : t('Make pendant item')}
        </button>
      </span>

      {isBelt ? (
        <>
          <div className="ga-form-hint" style={{ marginTop: 4 }}>
            {t('Charms')} ({charms.length}/{MAX_CHARMS})
          </div>
          {charms.map((c, i) => {
            const atKey = typeof c.at === 'number' ? 'angle' : c.at
            return (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={ROW}>
                  {picker(c.item, (id) => onChange((id ? updateCharm(draft, i, { item: id })
                    : withoutCharm(draft, i)).jewellery as Jewellery), `${t('Charm')} ${i + 1}`)}
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="ga-form-hint">{t('Position')}</span>
                    <select className="ga-input" value={atKey}
                      onChange={(e) => onChange(updateCharm(draft, i, {
                        at: (e.target.value === 'angle' ? 45 : e.target.value) as CharmAt,
                      }).jewellery as Jewellery)}>
                      {Object.keys(AT_LABELS).map((k) => <option key={k} value={k}>{t(AT_LABELS[k])}</option>)}
                    </select>
                    {typeof c.at === 'number' ? (
                      <input className="ga-input" type="number" min={-180} max={180} step={5} value={c.at}
                        aria-label={t('Angle (°, +90 = left hip)')} title={t('Angle (°, +90 = left hip)')}
                        onChange={(e) => onChange(updateCharm(draft, i, { at: Number(e.target.value) })
                          .jewellery as Jewellery)} />
                    ) : null}
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="ga-form-hint">{t('Attachment')}</span>
                    <select className="ga-input" value={c.mount || ''}
                      onChange={(e) => onChange(updateCharm(draft, i, {
                        mount: (e.target.value || undefined) as 'flat' | 'hang' | undefined,
                      }).jewellery as Jewellery)}>
                      <option value="">{t("Part's own")}</option>
                      <option value="flat">{t('Flat')}</option>
                      <option value="hang">{t('Hanging')}</option>
                    </select>
                  </label>
                  {c.mount === 'hang' ? (
                    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span className="ga-form-hint">{t('Drop (cm)')}</span>
                      <input className="ga-input" type="number" min={0} max={30} step={0.5} value={c.drop_cm ?? 0}
                        onChange={(e) => onChange(updateCharm(draft, i, { drop_cm: Number(e.target.value) || 0 })
                          .jewellery as Jewellery)} />
                    </label>
                  ) : <span />}
                  <button type="button" className="ga-btn ga-btn-sm"
                    onClick={() => onChange(withoutCharm(draft, i).jewellery as Jewellery)}>{t('Remove')}</button>
                </div>
                {chip('charm', i, c.item)}
              </div>
            )
          })}
          <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <select className="ga-input" style={{ maxWidth: 220 }} value="" aria-label={t('Add charm')}
              disabled={charms.length >= MAX_CHARMS || !opts.length}
              onChange={(e) => {
                const next = e.target.value ? withCharm(draft, { item: e.target.value }) : null
                if (next) onChange(next.jewellery as Jewellery)
              }}>
              <option value="">{t('Add charm…')}</option>
              {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            <button type="button" className="ga-btn ga-btn-sm" disabled={!!busy || dirty || charms.length >= MAX_CHARMS}
              title={dirty ? t('Save first') : t('A new part item, linked here; its image is generated without the chain\'s or belt\'s text (1 image job)')}
              onClick={() => { void make('charm') }}>
              {t('Add charm item')}
            </button>
          </span>
        </>
      ) : null}

      {notice ? (
        <div className="ga-hint" role="status" style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span>{notice.text}</span>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openInItems(notice.id)}>{t('Open in Items')}</button>
        </div>
      ) : null}
      {error ? <div role="alert" className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{error}</div> : null}
      <span className="ga-hint" style={{ fontSize: '0.72em' }}>
        {t('Size and placement are CPU only (0 hub jobs). A part\'s mesh is one hub job, shared by everyone using it.')}
      </span>
    </fieldset>
  )
}
