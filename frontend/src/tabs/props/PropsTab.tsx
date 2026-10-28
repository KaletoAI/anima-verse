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
import { BulkPublishButton, ImportButton } from '../../components/ImportExport'
import { ListPane } from '../../components/ListPane'
import { MeshBackendDialog } from '../../components/MeshBackendDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { PropCreateForm } from './PropCreateForm'
import { PropDetail } from './PropDetail'
import { PropImageDialog } from './PropImageDialog'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { CATEGORY_DATALIST_ID, MOUNT_KINDS, mountLabel, hasIncompleteActionBindings } from './propTypes'
import { propGenerationTarget, propGenerationAuthor, resolveVariantAfterBarrier, type PropGenerationTarget } from './propOperations'
import type {
  ImageBackendInfo, MeshBackendInfo, PropFull, PropSourceImage, PropVariant, PropView, PropWorkspaceArea,
} from './propTypes'

export type { ImageBackendInfo, MeshBackendInfo, PropFull, PropMarker } from './propTypes'

export function PropsTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [props, setProps] = useState<PropFull[]>([])
  const [pending, setPending] = useState<string[]>([])
  // WHICH variant of a pending prop is running, by STORE index — the same
  // number every variant-scoped route takes, so the strip can put the spinner
  // on the chip the job writes into instead of on the first one. `pending`
  // stays the aggregate: the library row says THAT the prop is busy.
  const [genVariants, setGenVariants] = useState<Record<string, number[]>>({})
  const [imageBackends, setImageBackends] = useState<ImageBackendInfo[]>([])
  const [meshBackends, setMeshBackends] = useState<MeshBackendInfo[]>([])
  // The admin's configured img2mesh alias ('' = none). What a run would
  // really start on, and therefore whose face count the variants' budget
  // fields show as their placeholder (v2 E5).
  const [meshDefault, setMeshDefault] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [selected, setSelected] = useState('')
  const [area, setArea] = useState<PropWorkspaceArea>('overview')
  const [armedDel, setArmedDel] = useState('')
  const [cacheBump, setCacheBump] = useState(0)
  const [creating, setCreating] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const libraryButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!libraryOpen) return
    const pane = document.querySelector<HTMLElement>('.props-admin .prop-library')
    const focusable = () => Array.from(pane?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]') || [])
    focusable()[0]?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation()
        setLibraryOpen(false)
      } else if (event.key === 'Tab') {
        const nodes = focusable(), first = nodes[0], last = nodes[nodes.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }
    pane?.addEventListener('keydown', onKey)
    return () => { pane?.removeEventListener('keydown', onKey); libraryButton.current?.focus() }
  }, [libraryOpen])
  // Prop id whose 🧊 regenerate waits in the backend dialog (every 3D
  // generate button goes through the dialog — face count / texture size
  // are per-run overrides). Existing targets keep their stable UID; only
  // the explicit new-variant operation carries an append plan.
  // `views` are the extra views that variant HAS a picture for — the dialog
  // offers exactly those to the multi-view alias, and the ones the admin
  // ticks travel with the mesh call.
  const [regen, setRegen] = useState<
    { id: string; meshOnly: boolean; variant?: number; uid?: string; author: PropVariant
      plan?: PropGenerationTarget; views?: PropView[] } | null>(null)
  // Prop whose 🖼 image-only regenerate waits in the image dialog (backend +
  // final prompt; the mesh stays until re-meshed from the new image). The
  // VARIANT travels with it: the source image belongs to the variant, so the
  // render targets exactly the one the detail has open, and `image` is that
  // variant's current record — the dialog opens on the backend THIS picture
  // was made with, not on the primary variant's. `subject` is the text THAT
  // variant renders from (its own description, else the prop's) — the dialog
  // composes the final prompt, so it must compose from the variant's sentence.
  // `view` names WHICH of the four pictures is rendered (the front is the
  // variant's source image, the other three are mesh input beside it) and
  // `refVariants` lists every variant holding a front image — the pictures
  // this render may take as its appearance reference, which is how a new
  // version of the object is authored from the one before it.
  const [imgRegen, setImgRegen] = useState<
    { prop: PropFull; variant: number; uid: string; view: PropView; refs: PropVariant[]
      image?: PropSourceImage; subject: string } | null>(null)
  const [query, setQuery] = useState('')
  const [catFilter, setCatFilter] = useState('')
  // How the pieces are MOUNTED: '' = every prop, 'none' = the ones nobody has
  // classified yet (the working list of the classify button), otherwise one
  // of the four kinds. 'none' is its own token because the unclassified state
  // is the ABSENCE of a kind, not a kind.
  const [mountFilter, setMountFilter] = useState('')
  // Props whose size is still the placeholder cube the create form wrote
  // (`dims_estimated`). Those metres are what the furnish budget is spent
  // from, so a wrong one eats a room — this filter is where the admin finds
  // them (plan-furnish-v2.md § 2 B3).
  const [estimatedOnly, setEstimatedOnly] = useState(false)
  const [missingModelOnly, setMissingModelOnly] = useState(false)
  const [actionsOnly, setActionsOnly] = useState(false)
  const [incompleteBindingsOnly, setIncompleteBindingsOnly] = useState(false)
  // Selection mode for the bulk publish: a click on a row ticks it instead of
  // opening it (plan-marketplace-props.md Teil E).
  const [pickMode, setPickMode] = useState(false)
  // While a bulk publish runs the selection mode stays on: leaving it would
  // unmount the button that polls the job and reports its outcome.
  const [bulkRunning, setBulkRunning] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const togglePick = useCallback((id: string) => {
    setPicked((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])
  // The classify run: the confirmation the button opens, and whether it is
  // running (the route is synchronous — it holds the LLM call).
  const [classifyOpen, setClassifyOpen] = useState(false)
  const [classifying, setClassifying] = useState(false)
  const [classifyReport, setClassifyReport] = useState<{
    classified: number; unresolved: string[]
  } | null>(null)
  // How many unsaved FIELD edits the open detail holds (its change buffer,
  // `pendingFields`). A tab switch is asked about by the shell
  // (`lib/unsavedGuard`), but switching to another prop never leaves this tab —
  // so that question is ours, and it is asked with real UI: no
  // window.confirm in this admin.
  const [dirty, setDirty] = useState(0)
  const [leaveTo, setLeaveTo] = useState<{ id: string; creating: boolean } | null>(null)
  const goTo = useCallback((id: string, creating: boolean) => {
    setLeaveTo(null)
    setCreating(creating)
    setSelected(id)
    setLibraryOpen(false)
  }, [])
  /** Open another prop (or the create form) — asking first when the detail
   *  still holds a draft. Selecting the prop that is already open is not a
   *  navigation and never asks. */
  const navigate = useCallback((id: string, creating = false) => {
    if (dirty > 0 && (creating || id !== selected)) {
      setLeaveTo({ id, creating })
      return
    }
    goTo(id, creating)
  }, [dirty, goTo, selected])

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ props?: PropFull[]; pending?: string[]
        generating_variants?: Record<string, number[]>
        image_backends?: ImageBackendInfo[]; mesh_backends?: MeshBackendInfo[]
        mesh_default?: string }>(
        '/world/props')
      setProps(d.props || [])
      setPending(d.pending || [])
      setGenVariants(d.generating_variants || {})
      setImageBackends(d.image_backends || [])
      setMeshBackends(d.mesh_backends || [])
      setMeshDefault(d.mesh_default || '')
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
      if (mountFilter === 'none' ? !!p.mount
        : mountFilter && p.mount !== mountFilter) return false
      if (estimatedOnly && !p.dims_estimated) return false
      if (missingModelOnly && p.has_model) return false
      if (actionsOnly && !(p.actions || []).length) return false
      if (incompleteBindingsOnly && !hasIncompleteActionBindings(p)) return false
      if (!q) return true
      return p.name.toLowerCase().includes(q)
        || p.tags.some((tag) => tag.toLowerCase().includes(q))
    })
  }, [props, query, catFilter, mountFilter, estimatedOnly, missingModelOnly, actionsOnly, incompleteBindingsOnly])

  /** How many props have no mount yet — what the classify run would work on,
   *  and the number its confirmation states. */
  const unclassified = useMemo(
    () => props.filter((p) => !p.mount).length, [props])

  const classifyMounts = useCallback(async () => {
    setClassifyOpen(false)
    setClassifying(true)
    try {
      const d = await apiPost<{ classified?: number; unresolved?: string[] }>(
        '/world/props/mount-classify', {})
      toast(t('{n} props classified, {m} unresolved')
        .replace('{n}', String(d?.classified || 0))
        .replace('{m}', String((d?.unresolved || []).length)))
      await load()
      setClassifyReport({ classified: d?.classified || 0, unresolved: d?.unresolved || [] })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setClassifying(false)
    }
  }, [load, t, toast])

  const selectedProp = props.find((p) => p.id === selected) || null

  return (
    <div className={`ga-twocol props-admin${libraryOpen ? ' is-library-open' : ''}`}>
      <button ref={libraryButton} type="button" className="ga-btn prop-library-toggle"
        aria-expanded={libraryOpen} aria-controls="prop-library"
        onClick={() => setLibraryOpen((open) => !open)}>{t('Bibliothek')}</button>
      {libraryOpen && <button type="button" className="prop-library-backdrop"
        aria-label={t('Bibliothek schließen')} onClick={() => setLibraryOpen(false)} />}
      <ListPane id="props" label={t('Props')} className="ga-twocol-left prop-library"
        expanded={libraryOpen || bulkRunning ? true : undefined}
        collapseDisabled={bulkRunning}
        onExpandedChange={libraryOpen ? () => setLibraryOpen(false) : undefined}>
        <div id="prop-library" className="prop-library-content">
        <header className="ga-twocol-header prop-library-header">
          <h3>{t('Props')}</h3>
          <div className="prop-library-actions" role="group" aria-label={t('Bibliotheksaktionen')}>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
              aria-label={t('New')} title={t('New')} onClick={() => navigate('', true)}>
              <span aria-hidden="true">+</span>
            </button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={classifying}
              aria-label={classifying ? t('Classifying…') : t('Classify mount (LLM)')}
              title={classifying ? t('Classifying…') : t('Classify mount (LLM)')}
              onClick={() => setClassifyOpen(true)}>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="m4 20 12-12 4 4L8 24M14 10l4 4M5 3v6M2 6h6M19 2v4M17 4h4" transform="translate(0 -2)" />
              </svg>
            </button>
            <div className="prop-library-import">
              <ImportButton title={t('Import')}
                onImported={() => { void load(); setCacheBump((b) => b + 1) }} />
            </div>
            <button type="button" className={`ga-btn ga-btn-sm${pickMode ? ' ga-btn-primary' : ''}`}
              disabled={bulkRunning} aria-label={t('Select')} title={t('Select')} aria-pressed={pickMode}
              onClick={() => { setPickMode((m) => !m); setPicked(new Set()) }}>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="4" y="4" width="16" height="16" rx="2" /><path d="m8 12 3 3 5-6" />
              </svg>
            </button>
          </div>
        </header>
        {pickMode ? (
          <div className="ga-form-row prop-library-selection">
            <span style={{ fontSize: 12 }}>{t('{n} selected').replace('{n}', String(picked.size))}</span>
            <button className="ga-btn ga-btn-sm"
              onClick={() => setPicked(new Set(visible.map((p) => p.id)))}>
              {t('Select all shown')}
            </button>
            <button className="ga-btn ga-btn-sm" disabled={picked.size === 0}
              onClick={() => setPicked(new Set())}>
              {t('Clear')}
            </button>
            <BulkPublishButton packType="prop" entityIds={[...picked]}
              onRunningChange={setBulkRunning} />
          </div>
        ) : null}
        <div className="prop-library-search">
          <input className="ga-input" value={query} placeholder={t('Search…')} aria-label={t('Props durchsuchen')}
            onChange={(e) => setQuery(e.target.value)} />
          <div className="prop-library-filter-selects">
            <select className="ga-input" value={catFilter} aria-label={t('Category')}
              title={t('Category')} onChange={(e) => setCatFilter(e.target.value)}>
              <option value="">{t('All categories')}</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select className="ga-input" value={mountFilter} aria-label={t('All mounts')}
              title={t('All mounts')} onChange={(e) => setMountFilter(e.target.value)}>
              <option value="">{t('All mounts')}</option>
              <option value="none">{t('Unclassified')}</option>
              {MOUNT_KINDS.map((m) => (
                <option key={m.kind} value={m.kind}>{t(m.label)}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="prop-library-filters">
          <label title={t('Props whose size is still the placeholder cube of the create form. Those metres are what a room’s furnishing budget is spent from — fix them in the variant strip.')}>
            <input type="checkbox" checked={estimatedOnly}
              onChange={(e) => setEstimatedOnly(e.target.checked)} />
            {t('Maße geschätzt')}
          </label>
          <label title={t('Modell fehlt')}><input type="checkbox" checked={missingModelOnly} onChange={(event) => setMissingModelOnly(event.target.checked)} /> {t('Ohne Modell')}</label>
          <label title={t('Aktionen vorhanden')}><input type="checkbox" checked={actionsOnly} onChange={(event) => setActionsOnly(event.target.checked)} /> {t('Mit Aktionen')}</label>
          <label title={t('Aktionsbindung unvollständig')}><input type="checkbox" checked={incompleteBindingsOnly} onChange={(event) => setIncompleteBindingsOnly(event.target.checked)} /> {t('Bindung offen')}</label>
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
              const secondary = [
                p.category, p.mount ? t(mountLabel(p.mount)) : '',
                pending.includes(p.id) ? t('generating…') : '',
                !p.has_model ? t('no model') : '',
                (p.variant_count || 0) > 1 ? `${p.variant_count} ${t('Varianten')}` : '',
                p.variants_missing_mesh ? `${p.variants_missing_mesh} ${t('mesh missing')}` : '',
                p.variants_missing_image ? `${p.variants_missing_image} ${t('image missing')}` : '',
                hasIncompleteActionBindings(p) ? t('Aktionsbindung prüfen')
                  : (p.actions || []).length ? t('Aktionen definiert; Raumweg nicht geprüft')
                    : t('Dekorativ · keine Aktionen nötig'),
                p.mount_suggested ? t('suggested') : '',
              ].filter(Boolean).join(' · ')
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    className={`ga-list-row${isActive ? ' is-active' : ''}`}
                    aria-pressed={pickMode ? picked.has(p.id) : undefined}
                    onClick={() => (pickMode ? togglePick(p.id) : navigate(p.id))}
                  >
                    {pickMode && <span aria-hidden className="prop-library-pick">
                      {picked.has(p.id) ? '☑' : '☐'}
                    </span>}
                    {p.has_source ? <img className="ga-list-thumb" alt=""
                      src={`/assets/props/${encodeURIComponent(p.id)}/source?v=${cacheBump}`} />
                      : <span aria-hidden className="prop-library-icon">📦</span>}
                    <span className="ga-list-row-main">
                      <span className="prop-library-name" title={p.name}>{p.name}</span>
                      <span className="ga-list-row-sub" title={secondary}>{secondary}</span>
                    </span>
                  </button>
                </li>
              )
            })
          )}
        </ul>
        </div>
      </ListPane>
      <section className={`ga-twocol-right prop-workspace-container${!creating && selectedProp ? ' is-workspace' : ''}`}>
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
            key={selectedProp.id}
            prop={selectedProp}
            area={area}
            onAreaChange={setArea}
            pending={pending.includes(selectedProp.id)}
            generatingVariants={genVariants[selectedProp.id] || []}
            cacheBump={cacheBump}
            onChanged={load}
            onDelete={() => remove(selectedProp.id)}
            armedDelete={armedDel === selectedProp.id}
            onRegenerate={(plan, author) => setRegen({ id: selectedProp.id, meshOnly: plan.kind === 'existing' && author.has_source, plan, author,
              views: (['back', 'left', 'right'] as PropView[]).filter(view => !!author.images?.[view]),
              ...(plan.kind === 'existing' ? { variant: plan.index, uid: plan.uid } : {}) })}
            onRegenerateMesh={(target, views) =>
              setRegen({ id: selectedProp.id, meshOnly: true, variant: target.index, uid: target.uid, author: target, views })}
            onRegenerateImage={(target, view, image, subject, refs, author) =>
              setImgRegen({ prop: author, variant: target.index, uid: target.uid, view,
                refs, image, subject })}
            onGenerating={startPoll}
            // The face count a run would really start on — the PLACEHOLDER
            // behind the variants' budget fields (v2 E5). The admin's
            // CONFIGURED alias, because that is the one an unqualified run
            // picks; the first backend that declares a count stands in where
            // none is configured, so the field still says a number instead of
            // going quiet.
            backendFaces={meshBackends.find((b) => b.name === meshDefault)?.face_num
              || meshBackends.find((b) => b.face_num)?.face_num || 0}
            onDirtyChange={setDirty}
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
          title={regen?.plan?.kind === 'append' ? t('+ Generate new variant') : t('Regenerate selected variant')}
          hint={regen?.plan?.kind === 'append'
            ? t('A new variant will be created. Generation uses the configured paid backends.')
            : t('Only the selected variant is replaced. No variant is created.')}
          backends={meshBackends}
          defaultBackend={meshDefault
            || (meshBackends.length === 1 ? meshBackends[0].name : '')}
          generateLabel={regen?.meshOnly ? t('Mesh') : t('Regenerate')}
          // Existing targets use their own budgets; append copies the confirmed
          // primary author's settings, independent of the currently selected prop.
          faceTargets={{ high: regen?.author.target_faces_high, low: regen?.author.target_faces_low }}
          showTier
          // Only a RE-MESH offers views, and only the ones this variant
          // really holds a file for — a stored picture has no alternatives,
          // so each is a single-option checkbox the admin ticks off.
          views={regen?.meshOnly && regen.views?.length
            ? regen.views.map((view) => ({ view, options: [{ value: view, label: t('stored') }] }))
            : undefined}
          onGenerate={async (backend, opts) => {
            const request = regen
            setRegen(null)
            if (!request) return
            const base = `/world/props/${encodeURIComponent(request.id)}`
            try {
              const current = await apiGet<{ variants: PropVariant[]; max: number;
                revision: string; generating_variants: number[] }>(`${base}/variants`)
              let index: number | undefined
              let plan = request.plan
              let author: PropVariant
              if (request.plan?.kind === 'append' && current.generating_variants.length) {
                throw new Error(t('Generation is running for this prop. Wait for it to finish.'))
              }
              if (request.plan?.kind !== 'append') {
                const target = await resolveVariantAfterBarrier(request.uid || '', async () => true,
                  async () => current.variants)
                if (!target) return
                if (current.generating_variants.includes(target.index)) {
                  throw new Error(t('This variant is generating right now.'))
                }
                if (request.meshOnly && !target.has_source) throw new Error(t('This variant has no source image.'))
                index = target.index
                author = target
              } else {
                plan = propGenerationTarget(current.variants, current.max, current.generating_variants)
                author = propGenerationAuthor(current.variants, plan)
              }
              const changed = JSON.stringify(plan) !== JSON.stringify(request.plan)
                || author.uid !== request.author.uid
                || author.index !== request.author.index
                || author.target_faces_high !== request.author.target_faces_high
                || author.target_faces_low !== request.author.target_faces_low
                || (request.meshOnly && JSON.stringify(author.images) !== JSON.stringify(request.author.images))
              if (changed) {
                setRegen({ ...request, plan, author,
                  variant: index,
                  uid: index === undefined ? undefined : author.uid,
                  views: request.meshOnly ? (['back', 'left', 'right'] as PropView[])
                    .filter((view) => !!author.images?.[view]) : request.views })
                toast(t('The generation target or its settings changed. Review again before starting.'), 'error')
                return
              }
              const answer = await apiPost<{ status?: string }>(
                index === undefined ? `${base}/generate` : `${base}/variants/${index}/generate`,
                { mesh_backend: backend, base_revision: current.revision,
                  ...(index !== undefined ? { mesh_only: request.meshOnly, variant_uid: author.uid } : { generation_target: plan }),
                  ...(opts.face_num ? { face_num: opts.face_num } : {}),
                  ...(opts.texture_size ? { texture_size: opts.texture_size } : {}),
                  ...(opts.lod_faces !== undefined ? { lod_faces: opts.lod_faces } : {}),
                  ...(opts.tier ? { tier: opts.tier } : {}),
                  ...(opts.views ? { views: Object.keys(opts.views) } : {}) })
              toast(answer?.status === 'already_running' ? t('This variant is already generating.')
                : t('Generation started for the confirmed target.'))
              startPoll()
            } catch (error) { toast(t('Error') + ': ' + t((error as Error).message), 'error') }
          }}
          onClose={() => setRegen(null)}
        >
          {regen?.plan?.kind === 'existing' && regen.author.has_source && <fieldset>
            <legend>{t('Generation mode')}</legend>
            <label><input type="radio" name="prop-regen-mode" checked={regen.meshOnly}
              onChange={() => setRegen({ ...regen, meshOnly: true })} />{t('3D model from the existing image')}</label>
            <label><input type="radio" name="prop-regen-mode" checked={!regen.meshOnly}
              onChange={() => setRegen({ ...regen, meshOnly: false })} />{t('New image + 3D model')}</label>
          </fieldset>}
        </MeshBackendDialog>
        <PropImageDialog
          prop={imgRegen?.prop || null}
          variant={imgRegen?.variant || 0}
          view={imgRegen?.view || 'front'}
          refVariants={imgRegen?.refs.map((entry) => entry.index) || []}
          subject={imgRegen?.subject}
          image={imgRegen?.image}
          backends={imageBackends}
          cacheBump={cacheBump}
          onGenerate={async (imageBackend, prompt, negative, referenceVariant) => {
            const request = imgRegen
            setImgRegen(null)
            if (!request) return
            try {
              const base = `/world/props/${encodeURIComponent(request.prop.id)}`
              const current = await apiGet<{ variants: PropVariant[]; revision: string;
                generating_variants: number[] }>(`${base}/variants`)
              const target = await resolveVariantAfterBarrier(request.uid, async () => true,
                async () => current.variants)
              if (!target) return
              if (current.generating_variants.includes(target.index)) {
                throw new Error(t('This variant is generating right now.'))
              }
              let referenceIndex: number | undefined
              let referenceUid: string | undefined
              if (referenceVariant !== null) {
                const uid = request.refs.find((entry) => entry.index === referenceVariant)?.uid || ''
                const reference = await resolveVariantAfterBarrier(uid, async () => true,
                  async () => current.variants)
                if (!reference) return
                referenceIndex = reference.index
                referenceUid = reference.uid
              }
              const answer = await apiPost<{ status?: string }>(`${base}/variants/${target.index}/generate`,
                { image_only: true, image_backend: imageBackend, prompt, negative, view: request.view,
                  base_revision: current.revision, variant_uid: target.uid,
                  front_reference: referenceIndex !== undefined,
                  ...(referenceIndex !== undefined
                    ? { reference_variant: referenceIndex, reference_variant_uid: referenceUid } : {}) })
              toast(answer?.status === 'already_running' ? t('This variant is already generating.') : t('Rendering a new source image…'))
              startPoll()
            } catch (error) { toast(t('Error') + ': ' + t((error as Error).message), 'error') }
          }}
          onClose={() => setImgRegen(null)}
        />
        {/* The classify run is asked about before it starts: it costs an LLM
            call per 40 props and writes a value into every one of them. Real
            UI, never a window.confirm. */}
        {classifyOpen ? (
          <PropWorkspaceDialog title={t('Classify mount (LLM)')} onCancel={() => setClassifyOpen(false)}>
            <div className="ga-modal-body">
              <p>{t('Wird sofort angewendet. Dies startet kostenpflichtige LLM-Aufrufe gemäß deiner Backend-Konfiguration und speichert Befestigungsvorschläge sofort.')}</p>
              <p>{unclassified
                ? t('{n} unklassifizierte Props; bis zu {calls} LLM-Aufrufe (40 Props je Aufruf). Vorschläge werden anschließend je Prop im Entwurf bestätigt.')
                  .replace('{n}', String(unclassified)).replace('{calls}', String(Math.ceil(unclassified / 40)))
                : t('Every prop already has a mount. There is nothing to classify.')}</p>
              <p>{t('Lokale Befestigungsänderungen bleiben erhalten; Überschneidungen erscheinen als Feldkonflikt.')}</p>
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" onClick={() => setClassifyOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={!unclassified}
                onClick={() => { void classifyMounts() }}>{t('LLM-Aufrufe starten & Vorschläge speichern')}</button>
            </div>
          </PropWorkspaceDialog>
        ) : null}
        {classifyReport && <PropWorkspaceDialog title={t('Ergebnis der Befestigungsklassifizierung')} onCancel={() => setClassifyReport(null)}>
          <div className="ga-modal-body">
            <p>{classifyReport.classified} {t('Vorschläge sofort gespeichert')}; {classifyReport.unresolved.length} {t('ungeklärt')}.</p>
            {classifyReport.unresolved.length > 0 && <ul>{classifyReport.unresolved.map((id) => <li key={id}>{props.find((item) => item.id === id)?.name || id}</li>)}</ul>}
            <p>{t('Vorschläge in Übersicht prüfen und bestätigen. Lokale Entwürfe wurden nicht verworfen.')}</p>
          </div>
          <div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setClassifyReport(null)}>{t('Schließen')}</button></div>
        </PropWorkspaceDialog>}
        {/* The prop-switch guard. The same question the shell asks before a
            tab switch, asked here because a prop switch stays inside the tab
            — and asked as UI, never as window.confirm. */}
        {leaveTo ? (
          <PropWorkspaceDialog title={t('Unsaved changes')} onCancel={() => setLeaveTo(null)}>
              <div className="ga-modal-body">
                {t('This prop holds {n} field changes that were never saved. Opening another prop discards them.')
                  .replace('{n}', String(dirty))}
              </div>
              <div className="ga-modal-footer">
                <button className="ga-btn" onClick={() => setLeaveTo(null)}>
                  {t('Stay')}
                </button>
                <button className="ga-btn ga-btn-danger"
                  onClick={() => goTo(leaveTo.id, leaveTo.creating)}>
                  {t('Leave and discard')}
                </button>
              </div>
          </PropWorkspaceDialog>
        ) : null}
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
