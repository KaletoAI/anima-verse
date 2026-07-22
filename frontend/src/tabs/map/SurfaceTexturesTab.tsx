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
import { ListHeader } from '../../components/ListHeader'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SurfaceBlendEditor } from './SurfaceBlendEditor'
import { SurfaceGenerateForm } from './SurfaceGenerateForm'
import { SurfaceKindDetail } from './SurfaceKindDetail'
import { KIND_DATALIST_ID, KNOWN_KINDS, dateShort, madeWith } from './surfaceTypes'
import type { BackendInfo, Blend, TexGroup, TexVersion } from './surfaceTypes'

export function SurfaceTexturesTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [textures, setTextures] = useState<TexGroup[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [backends, setBackends] = useState<BackendInfo[]>([])
  // Per-kind subject phrases (curated server-side) — the visual character
  // of the material; unknown kinds get the generic fallback.
  const [subjects, setSubjects] = useState<Record<string, string>>({})
  // Compositions (AV3D-13 v2): zone gradients toward a neighbor kind —
  // "coast" = water → sand → whatever the other neighbors are.
  const [blends, setBlends] = useState<Record<string, Blend>>({})
  const [blendEdit, setBlendEdit] = useState<{ kind: string; blend: Blend } | null>(null)
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
  const [zoom, setZoom] = useState<{ kind: string; v: TexVersion } | null>(null)
  const [cacheBump, setCacheBump] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const uploadKindRef = useRef('')

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ textures?: TexGroup[]; pending?: string[]
        backends?: BackendInfo[]; subjects?: Record<string, string>
        blends?: Record<string, Blend> }>(
        '/world/surface-textures')
      setTextures(d.textures || [])
      setPending(d.pending || [])
      setBackends(d.backends || [])
      setSubjects(d.subjects || {})
      setBlends(d.blends || {})
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

  // The final prompt = use-case style of the chosen backend + the material
  // subject from the kind — shown in full and editable; manual edits stick.
  useEffect(() => {
    if (promptTouched) return
    const style = backendInfo?.prompt_style || ''
    const k = kind.trim().toLowerCase()
    // Same composition as the server: curated phrase, else the generic
    // "surface of <kind>" fallback.
    const subject = !k ? 'a natural ground surface'
      : (subjects[k] || `the surface of ${k} seen straight from above`)
    setPrompt(style ? `${style}, ${subject}` : subject)
    setNegative(backendInfo?.prompt_negative || '')
  }, [kind, backendInfo, subjects, promptTouched])

  const generate = useCallback(() => {
    const k = kind.trim().toLowerCase()
    if (!k) return
    void apiPost<{ status?: string }>('/world/surface-textures/generate', {
      kind: k, backend: backendInfo?.name || '', prompt, negative,
    })
      .then((d) => {
        toast(d?.status === 'already_running'
          ? t('This kind is already generating on that backend.')
          : t('Generating the texture…'))
        startPoll()
        setCreating(false)
        setSel(k)
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [kind, backendInfo, prompt, negative, load, startPoll, t, toast])

  const pickUpload = useCallback((k: string) => {
    const clean = k.trim().toLowerCase()
    if (!clean) return
    uploadKindRef.current = clean
    uploadRef.current?.click()
  }, [])

  const upload = useCallback((k: string, file: File) => {
    void apiUpload(`/world/surface-textures/${encodeURIComponent(k)}/upload`, file)
      .then(() => { setCacheBump((b) => b + 1); setCreating(false); setSel(k); void load() })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const setSize = useCallback((k: string, filename: string, raw: string) => {
    const n = parseFloat(raw)
    if (!Number.isFinite(n) || n <= 0) return
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/size`,
      { size_m: n, file: filename })
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const select = useCallback((k: string, filename: string) => {
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/select`, { file: filename })
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
    setPromptTouched(false)
  }, [])

  const selectedGroup = textures.find((tx) => tx.kind === sel) || null
  const blendNames = Object.keys(blends).sort()
  const isEmpty = !textures.length && !blendNames.length

  const generateForm = (
    <SurfaceGenerateForm
      kind={kind}
      onKind={setKind}
      lockKind={!!selectedGroup && !creating}
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
      <aside className="ga-twocol-left">
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
                          <img className="ga-list-thumb" alt=""
                            src={`${active.url}?v=${cacheBump}`} />
                        ) : (
                          <span style={{ fontSize: 18 }}>🧱</span>
                        )}
                        <span>{tx.kind}</span>
                        <span className="ga-list-row-sub">
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
      </aside>

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
          />
        ) : creating ? (
          <>
            <DetailToolbar
              title={t('New surface texture')}
              onCancel={() => setCreating(false)}
            />
            {generateForm}
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
            onSelect={(filename) => select(selectedGroup.kind, filename)}
            onRemove={(filename) => remove(selectedGroup.kind, filename)}
            onZoom={(v) => setZoom({ kind: selectedGroup.kind, v })}
            onUpload={() => pickUpload(selectedGroup.kind)}
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

      {zoom ? (
        <div className="ga-gallery-lightbox" onClick={() => setZoom(null)} role="dialog">
          <img src={`${zoom.v.url}?v=${cacheBump}`} alt={zoom.kind} />
          {/* Provenance caption — kind, how it was made, date, full prompt. */}
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: 'absolute', left: '50%', bottom: 16, transform: 'translateX(-50%)',
              maxWidth: '84vw', maxHeight: '30vh', overflow: 'auto', cursor: 'auto',
              background: 'rgba(0,0,0,0.75)', color: '#e6edf3', borderRadius: 6,
              padding: '8px 12px', fontSize: '0.85em', lineHeight: 1.4,
            }}
          >
            <div style={{ fontWeight: 600 }}>
              {zoom.kind} · {madeWith(zoom.v, t)}
              {dateShort(zoom.v.created_at) ? ` · ${dateShort(zoom.v.created_at)}` : ''}
              {` · ${zoom.v.size_m} m`}
            </div>
            {zoom.v.prompt ? (
              <div style={{ opacity: 0.85, marginTop: 4 }}>{zoom.v.prompt}</div>
            ) : null}
            {zoom.v.negative ? (
              <div style={{ opacity: 0.6, marginTop: 2 }}>{t('Negative prompt')}: {zoom.v.negative}</div>
            ) : null}
          </div>
          <button
            type="button"
            className="ga-gallery-lightbox-close"
            onClick={() => setZoom(null)}
            aria-label={t('Close')}
          >
            ×
          </button>
        </div>
      ) : null}
    </div>
  )
}
