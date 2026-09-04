/**
 * SurfaceTexturesTab — the global surface-texture library (AV3D-13) as its
 * own Game-Admin tab (next to the Map). Terrain tiles (road, water, …) in
 * the 3D client use these seamless top-down materials as ground instead of
 * the 2D icons. Like the galleries, SEVERAL versions per kind are stored —
 * one is ACTIVE (what the client gets); each version shows HOW it was made
 * (backend/upload + date, full prompt in the lightbox). Generate runs
 * through the normal image pipeline (use case "surface_texture"); the
 * COMPLETE final prompt is shown and editable before generating. An empty
 * library is fine — the client falls back to its procedural materials.
 *
 * Shell: the standard list-detail layout (`ga-twocol`) of the other tabs —
 * texture kinds and compositions on the left, the generator / the selected
 * kind's versions / the blend editor on the right.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { ListHeader } from '../../components/ListHeader'
import { ListPane } from '../../components/ListPane'
import { openLightbox } from '../../components/Lightbox'
import { ZoomButton } from '../../components/ZoomButton'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SurfaceBlendEditor } from './SurfaceBlendEditor'
import { SurfaceGenerateForm } from './SurfaceGenerateForm'
import { SurfaceKindDetail } from './SurfaceKindDetail'
import { KIND_DATALIST_ID, KNOWN_KINDS, SURFACE_PROMPT_CONTEXT, dateShort, madeWith, unslugKind } from './surfaceTypes'
import type { BackendInfo, Blend, TexGroup, TexVersion } from './surfaceTypes'

export function SurfaceTexturesTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [textures, setTextures] = useState<TexGroup[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [backends, setBackends] = useState<BackendInfo[]>([])
  // Compositions (AV3D-13 v2): zone gradients toward a neighbor kind —
  // "coast" = water → sand → whatever the other neighbors are.
  const [blends, setBlends] = useState<Record<string, Blend>>({})
  const [blendEdit, setBlendEdit] = useState<{ kind: string; blend: Blend } | null>(null)
  // The world's seasons (E2c): a version may be selected FOR one of them.
  // Empty = a world without seasons, and then the season controls stay away.
  const [worldSeasons, setWorldSeasons] = useState<string[]>([])
  const [currentSeason, setCurrentSeason] = useState('')
  const [loaded, setLoaded] = useState(false)
  // Selected list row: a texture kind, `blend:<kind>` or '' (nothing).
  const [sel, setSel] = useState('')
  const [creating, setCreating] = useState(false)
  const [kind, setKind] = useState('')
  const [backend, setBackend] = useState('')
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')
  const [promptTouched, setPromptTouched] = useState(false)
  const [armedDel, setArmedDel] = useState('')
  // New-kind drafts. The NAME is what you type; the id is derived from it by
  // the server (the `kind` field above stays empty unless you override it),
  // and the description is the only text that reaches the prompt.
  const [nameDraft, setNameDraft] = useState('')
  const [descDraft, setDescDraft] = useState('')
  const [cacheBump, setCacheBump] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Provenance caption for the shared lightbox — kind, how it was made, date,
  // size, and the full prompt (the pill clips; its tooltip carries it all).
  const zoomItem = useCallback((kind: string, v: TexVersion) => {
    const head = [kind, madeWith(v, t), dateShort(v.created_at), `${v.size_m} m`].filter(Boolean).join(' · ')
    const tail = [v.prompt, v.negative ? `${t('Negative prompt')}: ${v.negative}` : ''].filter(Boolean).join(' — ')
    return { src: `${v.url}?v=${cacheBump}`, alt: kind, caption: tail ? `${head} — ${tail}` : head }
  }, [cacheBump, t])
  const zoomVersion = useCallback((kind: string, v: TexVersion) => openLightbox(zoomItem(kind, v)), [zoomItem])
  const uploadRef = useRef<HTMLInputElement>(null)
  const uploadKindRef = useRef('')

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ textures?: TexGroup[]; pending?: string[]
        backends?: BackendInfo[]; blends?: Record<string, Blend>
        world_seasons?: string[]; current_season?: string }>(
        '/world/surface-textures')
      setTextures(d.textures || [])
      setPending(d.pending || [])
      setBackends(d.backends || [])
      setBlends(d.blends || {})
      setWorldSeasons(d.world_seasons || [])
      setCurrentSeason(d.current_season || '')
      setLoaded(true)
      return d
    } catch {
      setLoaded(true)
      return null
    }
  }, [])

  // Poll while a generation runs — same pattern as the building models:
  // pending comes from the server, never a local never-reset flag.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const d = await load()
      if (!d?.pending?.length) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        setCacheBump((b) => b + 1)
      }
    }, 3000)
  }, [load])

  useEffect(() => {
    load().then((d) => { if (d?.pending?.length) startPoll() })
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [load, startPoll])

  const backendInfo = backends.find((b) => b.name === backend) || backends[0]

  // The final prompt = the chosen backend's use-case style + the material's
  // DESCRIPTION. Same chain as surface_description() on the server —
  // description, then name, then the id as words. The id itself is never the
  // subject; that was the whole defect. Manual edits stick.
  useEffect(() => {
    if (promptTouched) return
    const style = backendInfo?.prompt_style || ''
    const k = kind.trim().toLowerCase()
    const stored = textures.find((tx) => tx.kind === k)
    const subject = (creating
      ? (descDraft.trim() || nameDraft.trim())
      : ((stored?.description || '').trim() || (stored?.name || '').trim()
        || (k ? `the surface of ${unslugKind(k)} seen straight from above` : '')))
      || 'a natural ground surface'
    setPrompt(style ? `${style}, ${subject}` : subject)
    setNegative(backendInfo?.prompt_negative || '')
  }, [kind, creating, textures, backendInfo, descDraft, nameDraft, promptTouched])

  const saveKindMeta = useCallback(async (k: string, meta: {
    name?: string; description?: string
    material?: Record<string, unknown> }) => {
    try {
      await apiPost(`/world/surface-textures/${encodeURIComponent(k)}/meta`, meta)
      // Reload: the server clamps a material declaration, so the dials must
      // show what was STORED, not what was typed.
      void load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [load, t, toast])

  const generate = useCallback(() => {
    const k = kind.trim().toLowerCase()
    // A new kind needs only a name — the SERVER derives the id and answers
    // with the one it used. Nothing here slugifies, so the two cannot drift.
    if (!k && !nameDraft.trim()) return
    void apiPost<{ status?: string; kind?: string }>(
      '/world/surface-textures/generate', {
        kind: k,
        // Only while CREATING — an existing kind has its own name and
        // description, and a leftover draft has no business near them.
        ...(creating ? { name: nameDraft, description: descDraft } : {}),
        backend: backendInfo?.name || '', prompt, negative,
      })
      .then((d) => {
        toast(d?.status === 'already_running'
          ? t('This kind is already generating on that backend.')
          : t('Generating the texture…'))
        startPoll()
        setCreating(false)
        if (d?.kind) { setSel(d.kind); setKind(d.kind) }
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [kind, creating, nameDraft, descDraft, backendInfo,
    prompt, negative, load, startPoll, t, toast])

  // An upload creates a kind just as a generation does: with an id it goes
  // to that kind, without one the server derives it from the name ("-" says
  // "no id, use the name") and answers with the id it used.
  const pickUpload = useCallback((k: string) => {
    const clean = k.trim().toLowerCase()
    if (!clean && !nameDraft.trim()) return
    uploadKindRef.current = clean || '-'
    uploadRef.current?.click()
  }, [nameDraft])

  const upload = useCallback((k: string, file: File) => {
    void apiUpload<{ kind?: string }>(
      `/world/surface-textures/${encodeURIComponent(k)}/upload`, file, 'file',
      k === '-' ? { name: nameDraft } : undefined)
      .then((d) => {
        setCacheBump((b) => b + 1)
        setCreating(false)
        const id = d?.kind || k
        setSel(id)
        setKind(id)
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [nameDraft, load, t, toast])

  const setSize = useCallback((k: string, filename: string, raw: string) => {
    const n = parseFloat(raw)
    if (!Number.isFinite(n) || n <= 0) return
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/size`,
      { size_m: n, file: filename })
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  // `season` targets ONE season slot instead of the default pick; an empty
  // filename with a season clears that slot (E2c).
  const select = useCallback((k: string, filename: string, season = '') => {
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/select`,
      { file: filename, season })
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const remove = useCallback((k: string, filename: string) => {
    if (armedDel !== filename) {
      setArmedDel(filename)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/surface-textures/${encodeURIComponent(k)}?file=${encodeURIComponent(filename)}`)
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [armedDel, load, t, toast])

  const saveBlend = useCallback(() => {
    if (!blendEdit) return
    const k = blendEdit.kind.trim().toLowerCase()
    if (!k || !blendEdit.blend.toward.trim()) {
      toast(t('A composition needs a kind and a "toward" kind.'), 'error')
      return
    }
    void apiPost(`/world/surface-textures/blends/${encodeURIComponent(k)}`,
      { blend: blendEdit.blend })
      .then(() => {
        setBlendEdit({ kind: k, blend: blendEdit.blend })
        setSel(`blend:${k}`)
        toast(t('Saved'))
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [blendEdit, load, t, toast])

  const removeBlend = useCallback((k: string) => {
    if (armedDel !== `blend:${k}`) {
      setArmedDel(`blend:${k}`)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/surface-textures/blends/${encodeURIComponent(k)}`)
      .then(() => { setBlendEdit(null); setSel(''); void load() })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [armedDel, load, t, toast])

  // ── List selection ──
  const pickKind = useCallback((k: string) => {
    setBlendEdit(null)
    setCreating(false)
    setSel(k)
    // The embedded generator produces a NEW VERSION of this kind — prefill it
    // and recompose the final prompt for it.
    setKind(k)
    setPromptTouched(false)
  }, [])

  const pickBlend = useCallback((k: string, blend: Blend) => {
    setCreating(false)
    setSel(`blend:${k}`)
    setBlendEdit({ kind: k, blend: JSON.parse(JSON.stringify(blend)) as Blend })
  }, [])

  const startCreate = useCallback(() => {
    setBlendEdit(null)
    setSel('')
    setCreating(true)
    setKind('')
    setNameDraft('')
    setDescDraft('')
    setPromptTouched(false)
  }, [])

  const selectedGroup = textures.find((tx) => tx.kind === sel) || null
  const blendNames = Object.keys(blends).sort()
  const isEmpty = !textures.length && !blendNames.length

  const generateForm = (
    <SurfaceGenerateForm
      ready={creating ? !!(nameDraft.trim() || kind.trim()) : !!kind.trim()}
      generateLabel={creating ? t('Generate') : t('Generate new version')}
      backends={backends}
      backendName={backendInfo?.name || ''}
      onBackend={(name) => { setBackend(name); setPromptTouched(false) }}
      prompt={prompt}
      onPrompt={(v) => { setPrompt(v); setPromptTouched(true) }}
      negative={negative}
      onNegative={(v) => { setNegative(v); setPromptTouched(true) }}
      onGenerate={generate}
      onUpload={() => pickUpload(kind)}
    />
  )

  return (
    <div className="ga-twocol">
      <ListPane id="surface-textures" label={t('Surface textures')}>
        <ListHeader title={t('Surface textures')} onNew={startCreate} />
        <ul className="ga-list">
          {!loaded ? (
            <li className="ga-list-empty">{t('Loading…')}</li>
          ) : isEmpty ? (
            <li className="ga-list-empty">{t('No textures yet.')}</li>
          ) : (
            <>
              {textures.map((tx) => {
                const active = tx.versions.find((v) => v.active) || tx.versions[0]
                return (
                  <li key={tx.kind}>
                    <button
                      type="button"
                      className={`ga-list-row${sel === tx.kind ? ' is-active' : ''}`}
                      onClick={() => pickKind(tx.kind)}
                    >
                      <span className="ga-list-row-main">
                        {active ? (
                          <span style={{ position: 'relative', display: 'inline-flex', flex: '0 0 auto' }}>
                            <img className="ga-list-thumb" alt=""
                              src={`${active.url}?v=${cacheBump}`} />
                            <ZoomButton item={() => zoomItem(tx.kind, active)}
                              size={11} style={{ top: -3, right: -3, width: 16, height: 16 }} />
                          </span>
                        ) : (
                          <span style={{ fontSize: 18 }}>🧱</span>
                        )}
                        <span>{tx.name || tx.kind}</span>
                        <span className="ga-list-row-sub">
                          {tx.name ? `${tx.kind} · ` : ''}
                          {active ? `${active.size_m} m` : ''}
                          {tx.versions.length > 1
                            ? ` · ${t('{n} versions').replace('{n}', String(tx.versions.length))}`
                            : ''}
                        </span>
                      </span>
                      {pending.includes(tx.kind) ? (
                        <span className="ga-source">{t('generating…')}</span>
                      ) : null}
                    </button>
                  </li>
                )
              })}
              {blendNames.map((bk) => (
                <li key={`blend:${bk}`}>
                  <button
                    type="button"
                    className={`ga-list-row${sel === `blend:${bk}` ? ' is-active' : ''}`}
                    onClick={() => pickBlend(bk, blends[bk])}
                  >
                    <span className="ga-list-row-main">
                      <span style={{ fontSize: 18 }}>🧬</span>
                      <span>{bk}</span>
                      <span className="ga-list-row-sub">{t('composition')}</span>
                    </span>
                  </button>
                </li>
              ))}
            </>
          )}
        </ul>
      </ListPane>

      <section className="ga-twocol-right">
        {blendEdit ? (
          <SurfaceBlendEditor
            value={blendEdit}
            onChange={setBlendEdit}
            onSave={saveBlend}
            onCancel={() => { setBlendEdit(null); setSel('') }}
            onDelete={blends[blendEdit.kind]
              ? () => removeBlend(blendEdit.kind) : undefined}
            armedDelete={armedDel === `blend:${blendEdit.kind}`}
            kinds={textures.map((tx) => ({
              kind: tx.kind, name: tx.name || tx.kind }))}
            kindThumb={(k) => {
              const g = textures.find((tx) => tx.kind === k)
              const v = g?.versions.find((vv) => vv.active) || g?.versions[0]
              return v ? `${v.url}?v=${cacheBump}` : ''
            }}
          />
        ) : creating ? (
          <>
            <DetailToolbar
              title={t('New surface texture')}
              onCancel={() => setCreating(false)}
            />
            {/* Same order as the detail view: what it is called, what it is,
                then how it is made. The ID is derived from the name by the
                server — the field is only here to override that. */}
            <div className="ga-form">
              <div className="ga-form-section-label">{t('Properties')}</div>
              <div className="ga-form-row">
                <Field label={t('Name')}
                  hint={t('Free text, spaces welcome — this is what every picker shows.')}>
                  <input
                    className="ga-input"
                    placeholder={t('e.g. Dark stone')}
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                  />
                </Field>
                <Field label={t('ID')} compact
                  hint={t('Optional — derived from the name.')}>
                  <input
                    className="ga-input"
                    list={KIND_DATALIST_ID}
                    style={{ width: 130 }}
                    placeholder={t('auto')}
                    value={kind}
                    onChange={(e) => setKind(e.target.value)}
                    title={t('Lowercase, no spaces. It must match the terrain field of the tiles it should cover, it is fixed once created, and it never reaches a prompt.')}
                  />
                </Field>
              </div>
              <Field label={t('Description')} help="surface_prompt"
                promptContext={SURFACE_PROMPT_CONTEXT}
                hint={t('Flows into the final prompt and is stored for regeneration.')}>
                <textarea
                  className="ga-textarea"
                  rows={2}
                  placeholder={t('What the texture shows, e.g. "seamless rubber flooring with a fine round-stud pattern"')}
                  value={descDraft}
                  onChange={(e) => setDescDraft(e.target.value)}
                />
              </Field>
              {generateForm}
            </div>
            <div className="ga-form">
              <div className="ga-form-section-label">{t('Compositions (blends)')}</div>
              <span className="ga-hint">
                {t('A composition is a zone gradient toward a neighbor kind instead of a texture — e.g. coast: water → sand → whatever the other neighbors are. A composition wins over textures of the same kind.')}
              </span>
              <div>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  onClick={() => {
                    setCreating(false)
                    setSel('')
                    setBlendEdit({ kind: 'coast', blend: {
                      toward: 'water',
                      zones: [{ kind: 'water', until: 0.42 },
                              { kind: 'sand', until: 0.62 },
                              { kind: 'neighbor' }],
                      noise: 0.08,
                    } })
                  }}
                  title={t('Prefilled with the contract example (coast: water → sand → neighbor).')}
                >
                  + {t('New composition')}
                </button>
              </div>
            </div>
          </>
        ) : selectedGroup ? (
          <SurfaceKindDetail
            group={selectedGroup}
            pending={pending.includes(selectedGroup.kind)}
            cacheBump={cacheBump}
            armedDel={armedDel}
            onSize={(filename, raw) => setSize(selectedGroup.kind, filename, raw)}
            onSelect={(filename, season) => select(selectedGroup.kind, filename, season)}
            worldSeasons={worldSeasons}
            currentSeason={currentSeason}
            onRemove={(filename) => remove(selectedGroup.kind, filename)}
            onZoom={(v) => zoomVersion(selectedGroup.kind, v)}
            onUpload={() => pickUpload(selectedGroup.kind)}
            onMeta={(meta) => {
              void saveKindMeta(selectedGroup.kind, meta).then(() => load())
            }}
            generateForm={generateForm}
          />
        ) : (
          <div className="ga-placeholder">
            {t('Seamless top-down ground materials for terrain tiles in the 3D client — one texture per kind, matching the terrain field (road, water, …). Without a texture the client uses its built-in materials.')}
          </div>
        )}
      </section>

      {/* One shared kind vocabulary for the generator and the blend editor. */}
      <datalist id={KIND_DATALIST_ID}>
        {KNOWN_KINDS.map((k) => <option key={k} value={k} />)}
      </datalist>
      <input
        ref={uploadRef}
        type="file"
        accept=".jpg,.jpeg,.png,.webp"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f && uploadKindRef.current) upload(uploadKindRef.current, f)
          e.target.value = ''
        }}
      />

    </div>
  )
}
