/**
 * PropsTab — the prop library (plan-room-props.md) as its own Game-Admin tab
 * (next to Surface textures). A prop is ONE furnishing object (chair, table,
 * plant …) as its own GLB mesh, generated from a product-shot render
 * (use case "prop") → img2mesh, or uploaded. Each prop carries object-local
 * animation markers so a marker travels WITH the object into any room.
 *
 * Shell: the standard list-detail layout (`ga-twocol`) of the other tabs —
 * library list with search + category filter on the left, the create form or
 * the selected prop's detail on the right. An empty library is the normal
 * starting state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ImportButton } from '../../components/ImportExport'
import { ListHeader } from '../../components/ListHeader'
import { MeshBackendDialog } from '../../components/MeshBackendDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { PropCreateForm } from './PropCreateForm'
import { PropDetail } from './PropDetail'
import { PropImageDialog } from './PropImageDialog'
import { CATEGORY_DATALIST_ID } from './propTypes'
import type { ImageBackendInfo, MeshBackendInfo, PropFull } from './propTypes'

export type { ImageBackendInfo, MeshBackendInfo, PropFull, PropMarker } from './propTypes'

export function PropsTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [props, setProps] = useState<PropFull[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [imageBackends, setImageBackends] = useState<ImageBackendInfo[]>([])
  const [meshBackends, setMeshBackends] = useState<MeshBackendInfo[]>([])
  const [loaded, setLoaded] = useState(false)
  const [selected, setSelected] = useState('')
  const [armedDel, setArmedDel] = useState('')
  const [cacheBump, setCacheBump] = useState(0)
  const [creating, setCreating] = useState(false)
  // Prop id whose 🧊 regenerate waits in the backend dialog (every 3D
  // generate button goes through the dialog — face count / texture size
  // are per-run overrides). `variant` is the model variant a RE-MESH refines;
  // the plain regenerate has none, because it appends one.
  const [regen, setRegen] = useState<
    { id: string; meshOnly: boolean; variant?: number } | null>(null)
  // Prop whose 🖼 image-only regenerate waits in the image dialog (backend +
  // final prompt; the mesh stays until re-meshed from the new image).
  const [imgRegen, setImgRegen] = useState<PropFull | null>(null)
  const [query, setQuery] = useState('')
  const [catFilter, setCatFilter] = useState('')

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ props?: PropFull[]; pending?: string[]
        image_backends?: ImageBackendInfo[]; mesh_backends?: MeshBackendInfo[] }>(
        '/world/props')
      setProps(d.props || [])
      setPending(d.pending || [])
      setImageBackends(d.image_backends || [])
      setMeshBackends(d.mesh_backends || [])
      setLoaded(true)
      return d
    } catch {
      setLoaded(true)
      return null
    }
  }, [])

  // Poll while a generation runs — pending comes from the server (same as the
  // surface textures / building models), never a local never-reset flag.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    const tick = async () => {
      n += 1
      const d = await load()
      if (!d?.pending?.length) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        setCacheBump((b) => b + 1)
        return
      }
      // Meshing takes minutes — slow the poll down after ~2 min, never give up.
      if (n === 40) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(tick, 15000)
      }
    }
    pollRef.current = setInterval(tick, 3000)
  }, [load])

  useEffect(() => {
    load().then((d) => { if (d?.pending?.length) startPoll() })
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [load, startPoll])

  const remove = useCallback((id: string) => {
    if (armedDel !== id) {
      setArmedDel(id)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/props/${encodeURIComponent(id)}`)
      .then(() => { if (selected === id) setSelected(''); void load() })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [armedDel, selected, load, t, toast])

  const categories = useMemo(() => {
    const set = new Set<string>()
    for (const p of props) if (p.category) set.add(p.category)
    return Array.from(set).sort()
  }, [props])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return props.filter((p) => {
      if (catFilter && p.category !== catFilter) return false
      if (!q) return true
      return p.name.toLowerCase().includes(q)
        || p.tags.some((tag) => tag.toLowerCase().includes(q))
    })
  }, [props, query, catFilter])

  const selectedProp = props.find((p) => p.id === selected) || null

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
        <ListHeader
          title={t('Props')}
          onNew={() => { setCreating(true); setSelected('') }}
          extra={
            <ImportButton
              endpoint="/world/props/import"
              overwriteSupported
              onImported={() => { void load(); setCacheBump((b) => b + 1) }}
            />
          }
        />
        <div className="ga-form-row" style={{ padding: '0 8px 8px' }}>
          <input className="ga-input" value={query} placeholder={t('Search…')}
            onChange={(e) => setQuery(e.target.value)} />
          <select className="ga-input" value={catFilter} style={{ maxWidth: 140 }}
            onChange={(e) => setCatFilter(e.target.value)}>
            <option value="">{t('All categories')}</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <ul className="ga-list">
          {!loaded ? (
            <li className="ga-list-empty">{t('Loading…')}</li>
          ) : visible.length === 0 ? (
            <li className="ga-list-empty">
              {props.length ? t('Nothing matches the filter') : t('No props yet')}
            </li>
          ) : (
            visible.map((p) => {
              const isActive = p.id === selected
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    className={`ga-list-row${isActive ? ' is-active' : ''}`}
                    onClick={() => { setCreating(false); setSelected(p.id) }}
                  >
                    <span className="ga-list-row-main">
                      {p.has_source ? (
                        <img className="ga-list-thumb" alt=""
                          src={`/assets/props/${encodeURIComponent(p.id)}/source?v=${cacheBump}`} />
                      ) : (
                        <span style={{ fontSize: 18 }}>📦</span>
                      )}
                      <span>{p.name}</span>
                      <span className="ga-list-row-sub">
                        {p.category ? `${p.category} · ` : ''}
                        {`${p.width_m}×${p.depth_m}×${p.height_m} m`}
                      </span>
                    </span>
                    {pending.includes(p.id) ? (
                      <span className="ga-source">{t('generating…')}</span>
                    ) : null}
                    {!p.has_model ? <span className="ga-source">{t('no model')}</span> : null}
                    {/* Several meshes of the same object — worth seeing from
                        the list, a scattered prop looks different with them. */}
                    {(p.variant_count || 0) > 1 ? (
                      <span className="ga-tag" title={t('Model variants of this prop')}>
                        ×{p.variant_count}
                      </span>
                    ) : null}
                  </button>
                </li>
              )
            })
          )}
        </ul>
      </aside>
      <section className="ga-twocol-right">
        {creating ? (
          <PropCreateForm
            imageBackends={imageBackends}
            meshBackends={meshBackends}
            onCreated={(id) => { setCreating(false); setSelected(id); void load() }}
            onGenerating={startPoll}
            onCancel={() => setCreating(false)}
          />
        ) : selectedProp ? (
          <PropDetail
            prop={selectedProp}
            pending={pending.includes(selectedProp.id)}
            cacheBump={cacheBump}
            onChanged={load}
            onDelete={() => remove(selectedProp.id)}
            armedDelete={armedDel === selectedProp.id}
            onRegenerate={() => setRegen({ id: selectedProp.id, meshOnly: false })}
            onRegenerateMesh={(variant) =>
              setRegen({ id: selectedProp.id, meshOnly: true, variant })}
            onRegenerateImage={() => setImgRegen(selectedProp)}
            onGenerating={startPoll}
            onRefresh={() => {
              setCacheBump((b) => b + 1)
              void load()
            }}
          />
        ) : (
          <div className="ga-placeholder">{t('Pick a prop or create a new one.')}</div>
        )}
        <MeshBackendDialog
          open={regen !== null}
          title={regen?.meshOnly
            ? `${t('Re-mesh from the source image')} · ${t('Variant')} ${(regen.variant || 0) + 1}`
            : t('Regenerate prop model — as another variant')}
          backends={meshBackends}
          defaultBackend={meshBackends.length === 1 ? meshBackends[0].name : ''}
          generateLabel={regen?.meshOnly ? t('Mesh') : t('Regenerate')}
          showTier
          onGenerate={(backend, opts) => {
            const target = regen
            setRegen(null)
            if (!target) return
            // A RE-MESH refines the variant the detail has open, so it goes to
            // that variant's route; the plain regenerate stays unqualified,
            // which is what makes it APPEND another variant.
            const base = `/world/props/${encodeURIComponent(target.id)}`
            void apiPost<{ status?: string }>(
              target.meshOnly
                ? `${base}/variants/${target.variant || 0}/generate`
                : `${base}/generate`,
              { mesh_backend: backend,
                ...(target.meshOnly ? { mesh_only: true } : {}),
                ...(opts.face_num ? { face_num: opts.face_num } : {}),
                ...(opts.texture_size ? { texture_size: opts.texture_size } : {}),
                ...(opts.lod_faces ? { lod_faces: opts.lod_faces } : {}),
                ...(opts.tier ? { tier: opts.tier } : {}) })
              .then((d) => {
                toast(d?.status === 'already_running'
                  ? t('This prop is already generating.')
                  : target.meshOnly
                    ? t('Meshing the source image…')
                    : t('Generating another model variant…'))
                startPoll()
              })
              .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
          }}
          onClose={() => setRegen(null)}
        />
        <PropImageDialog
          prop={imgRegen}
          backends={imageBackends}
          onGenerate={(imageBackend, prompt, negative) => {
            const target = imgRegen
            setImgRegen(null)
            if (!target) return
            void apiPost<{ status?: string }>(
              `/world/props/${encodeURIComponent(target.id)}/generate`,
              { image_only: true, image_backend: imageBackend,
                prompt, negative })
              .then((d) => {
                toast(d?.status === 'already_running'
                  ? t('This prop is already generating.')
                  : t('Rendering a new source image…'))
                startPoll()
              })
              .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
          }}
          onClose={() => setImgRegen(null)}
        />
      </section>
      {/* One shared category vocabulary for the create form and the detail —
          the categories the EXISTING props use (same source as the list
          filter), not a predefined list. Free text stays possible. */}
      <datalist id={CATEGORY_DATALIST_ID}>
        {categories.map((c) => <option key={c} value={c} />)}
      </datalist>
    </div>
  )
}
