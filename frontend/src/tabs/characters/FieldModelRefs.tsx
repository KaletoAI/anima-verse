/**
 * FieldModelRefs — the character's reference renders in the CURRENT outfit.
 * Two kinds: `pose` (default-pose wardrobe preview) and `tpose` (input for the
 * image-to-3D pipeline). Which kinds are shown is chosen by the `kinds` prop —
 * the wardrobe shows only the default pose, the 3D tab only the T-pose.
 *
 * Backend: GET /characters/{name}/model-refs (info),
 * GET .../model-refs/{tpose|pose} (image), POST .../model-refs/generate.
 * The face view's own button opens the image dialog (backend, LoRAs, prompt
 * for that one run); every other button fires directly.
 * The pair is also generated automatically after outfit changes (debounced).
 * Every picture is a shared RefImage tile (creation time, model · size).
 * ``refreshKey`` (e.g. the equipped signature) reloads + cache-busts when the
 * outfit changes, so the preview follows the current combination.
 *
 * Honesty rules of the status display: "Generating…" appears only while a
 * render actually RUNS (backend `status[kind].running`) or right after the
 * user's own click; a merely SCHEDULED debounce timer is reported as
 * "queued", never as generating. Both server-reported states are shown only
 * once they have persisted HINT_AFTER_S seconds (measured on the server's
 * clock), so a quick equip/unequip never flashes a hint at all.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ImageGenDialog } from '../../components/ImageGenDialog'
import type { ImageGenSubmit } from '../../components/ImageGenDialog'
import { RefImage } from './RefImage'
import type { Freshness } from './FreshnessBadge'

interface RefInfo {
  filename?: string
  /** Sidecar stamp, else the file's mtime (server, `image_tile_meta`). */
  created_at?: string
  /** Sidecar `model`, else `service`; absent on older renders. */
  model?: string
  backend?: string
  /** A base-body dressed back kept although its fit checks failed. */
  warning?: string
  /** Made from current data? (server, model_overview.annotate_model_refs_info:
   *  dressed views and drafts against the current base, the face view
   *  against the profile picture) — the tile's corner badge. */
  freshness?: Freshness | null
}

/** What the backend is doing to ONE kind right now (system-time stamps). */
interface KindStatus {
  /** A render thread exists for this kind (queued on its lock or rendering). */
  running: boolean
  started_at?: string | null
  /** A debounce timer is armed for this kind — nothing renders yet. */
  scheduled: boolean
  /** When the timer was (re)armed — every outfit mutation resets it. */
  scheduled_at?: string | null
  /** When the timer fires. */
  due_at?: string | null
}

interface RefsInfo {
  face_view?: {
    exists: boolean; stale: boolean; rendering: boolean; created_at?: string; width?: number; height?: number; url: string
    /** Dialog prefill: the face prompt a render would use, and its reference. */
    prompt?: string
    profile_url?: string
  }
  signature?: string
  tpose?: RefInfo | null
  pose?: RefInfo | null
  // Extra T-pose views for multi-view img2mesh. The body form determines
  // which three views are reported, so
  // the checkboxes can be rendered; `enabled` is the per-character toggle,
  // `info` the stored render (null = not rendered yet). They have no own
  // status lane; they ride with `tpose`.
  views?: Record<string, { enabled: boolean; info?: RefInfo | null }>
  /** On the base-body pipeline only the front and the back are dressed (plus
   *  left and right with the world setting "Dressed side views"): the views
   *  carry those (always on, no toggle) and the face view. */
  pipeline?: boolean
  /** Base-body pipeline: per dressed back/side view, the draft it was fitted
   *  from (served as `tpose_<view>_draft`). */
  drafts?: Record<string, RefInfo | null>
  auto?: { tpose?: boolean; pose?: boolean }
  // Per image — a running default-pose render must not lock the 3D tab's
  // T-pose button (and vice versa): with several backends they run in parallel.
  status?: Partial<Record<RefKind, KindStatus>>
  /** Server clock at response time — state ages are measured against it. */
  now?: string
}

// Display order of the extra views (checkboxes and thumbnails alike).
const VIEW_ORDER = ['front', 'back', 'left', 'right', 'face'] as const
// Base-body views made from a draft, in display order.
const DRAFT_ORDER = ['back', 'left', 'right'] as const

type RefKind = 'pose' | 'tpose'

/** A server-reported state is shown only after persisting this long. */
const HINT_AFTER_S = 20
/** Poll cadence while something runs or is scheduled; slows after ~2 min. */
const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40

/** Seconds from `since` to `now` (server stamps); -1 when either is missing. */
function ageSeconds(now?: string, since?: string | null): number {
  if (!now || !since) return -1
  const a = Date.parse(now)
  const b = Date.parse(since)
  if (Number.isNaN(a) || Number.isNaN(b)) return -1
  return (a - b) / 1000
}

const anyRunning = (d: RefsInfo | null | undefined, kinds: RefKind[]) =>
  kinds.some((k) => !!d?.status?.[k]?.running) || (kinds.includes('tpose') && !!d?.face_view?.rendering)
const anyScheduled = (d: RefsInfo | null | undefined, kinds: RefKind[]) =>
  kinds.some((k) => !!d?.status?.[k]?.scheduled)

/**
 * Identity of what is on screen: outfit signature + stored files of our kinds
 * (and the extra views). The image URLs are cache-busted only when this
 * changes, so a poll tick does not re-fetch an unchanged render every 3 s.
 */
function renderFingerprint(d: RefsInfo | null | undefined, kinds: RefKind[]): string {
  return JSON.stringify([
    d?.signature || '',
    d?.face_view?.created_at || '',
    DRAFT_ORDER.map((v) => [d?.drafts?.[v]?.filename || '', d?.drafts?.[v]?.created_at || '']),
    kinds.map((k) => [d?.[k]?.filename || '', d?.[k]?.created_at || '']),
    VIEW_ORDER.map((v) => [
      d?.views?.[v]?.info?.filename || '',
      d?.views?.[v]?.info?.created_at || '',
    ]),
  ])
}

export function FieldModelRefs({
  character,
  kinds = ['pose', 'tpose'],
  refreshKey = '',
}: {
  character: string
  kinds?: RefKind[]
  refreshKey?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<RefsInfo>({})
  const [bust, setBust] = useState(1)
  // The user's own click: immediate feedback, cleared once the backend
  // reports our kinds idle again.
  const [busy, setBusy] = useState(false)
  const [faceDialogOpen, setFaceDialogOpen] = useState(false)
  // The server's refusal of the last Generate (e.g. 409 "render the base
  // body first"), shown under the images until the next attempt.
  const [genError, setGenError] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Poll generation: a tick whose generation is stale (stopped/restarted
  // meanwhile, or the component is gone) drops its result.
  const pollIdRef = useRef(0)
  const fingerprintRef = useRef('')
  const kindsKey = kinds.join(',')
  // Stable identity for the hook dependencies — the caller passes a literal.
  const kindList = useMemo(() => kindsKey.split(',') as RefKind[], [kindsKey])

  const load = useCallback(async () => {
    if (!character) return null
    try {
      const d = await apiGet<RefsInfo>(`/characters/${enc}/model-refs`)
      setInfo(d)
      return d
    } catch {
      setInfo({})
      return null
    }
  }, [character, enc])

  const stopPoll = useCallback(() => {
    pollIdRef.current += 1
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  // One load now (after `delayMs`), then keep polling while the backend
  // reports OUR kinds running or scheduled. A render can legitimately wait
  // minutes in the backend queue, so there is NO give-up — after ~2 min the
  // poll merely slows down. The chain ends when nothing runs or is scheduled,
  // on stopPoll (unmount, character/outfit switch, restart) — never orphaned.
  const startPoll = useCallback(
    (delayMs = 0) => {
      stopPoll()
      const id = pollIdRef.current
      let n = 0
      let wasActive = false
      const tick = async () => {
        timerRef.current = null
        const d = await load()
        if (pollIdRef.current !== id) return
        const active = anyRunning(d, kindList) || anyScheduled(d, kindList)
        const fp = renderFingerprint(d, kindList)
        // Cache-bust when the shown files changed — or when a render just
        // ended (a re-render keeps the filename; the sidecar stamp may lag).
        if (fp !== fingerprintRef.current || (wasActive && !active)) {
          fingerprintRef.current = fp
          setBust((b) => b + 1)
        }
        if (!active) {
          setBusy(false)
          return
        }
        wasActive = true
        n += 1
        timerRef.current = setTimeout(tick, n >= POLL_SLOW_AFTER ? POLL_SLOW_MS : POLL_MS)
      }
      timerRef.current = setTimeout(tick, delayMs)
    },
    [load, kindList, stopPoll],
  )

  // Reload whenever the character OR the outfit (refreshKey) changes, so a
  // switch to a different combination shows THAT combination's render. A
  // local busy flag from the previous character must not bleed across.
  useEffect(() => {
    setBusy(false)
    startPoll()
    return stopPoll
  }, [startPoll, stopPoll, refreshKey])

  const generate = useCallback(async (view?: 'main' | typeof VIEW_ORDER[number]) => {
    if (busy) return
    setBusy(true)
    try {
      // An explicit view ignores the auto toggles and replaces only that
      // image. The general Generate button still fires this tab's checked kinds.
      const wanted = view ? ['tpose'] : kindList.filter((k) => info.auto?.[k] !== false)
      setGenError('')
      await apiPost(`/characters/${enc}/model-refs/generate`, { kinds: wanted, view })
      toast(t('Generating…'))
      // A beat for the worker thread to register as running before the first
      // status read — an idle read here would clear `busy` too early.
      startPoll(1000)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setGenError((e as Error).message)
      setBusy(false)
    }
  }, [busy, enc, kindList, info.auto, startPoll, t, toast])

  // The face view renders through the image dialog: its backend, LoRAs and
  // prompt apply to this one run only (the automatic render stays routed).
  const generateFace = useCallback(async (p: ImageGenSubmit) => {
    if (busy) return
    setBusy(true)
    try {
      await apiPost(`/characters/${enc}/model-refs/generate`, {
        kinds: ['tpose'], view: 'face',
        prompt: p.prompt,
        backend: p.backend || '',
        loras: p.loras || [],
        negative_prompt: p.negative_prompt || '',
      })
      toast(t('Generating…'))
      startPoll(1000)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [busy, enc, startPoll, t, toast])
  const closeFaceDialog = useCallback(() => setFaceDialogOpen(false), [])

  // Per-image toggle for the automatic outfit-change render (persisted per
  // character); the Generate button fires exactly the checked ones.
  const setAuto = useCallback(
    async (kind: RefKind, value: boolean) => {
      setInfo((prev) => ({ ...prev, auto: { ...(prev.auto || {}), [kind]: value } }))
      try {
        const d = await apiPost<{ auto: RefsInfo['auto'] }>(
          `/characters/${enc}/model-refs/auto`, { [kind]: value })
        setInfo((prev) => ({ ...prev, auto: d.auto }))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        load()
      }
    },
    [enc, load, t, toast],
  )

  // Per-view toggle for the extra T-pose renders (multi-view img2mesh input),
  // persisted per character like the auto toggles. The views are rendered
  // inside the T-pose pass — switching one on makes the next run add it.
  const setView = useCallback(
    async (view: string, value: boolean) => {
      setInfo((prev) => ({
        ...prev,
        views: {
          ...(prev.views || {}),
          [view]: { ...(prev.views?.[view] || {}), enabled: value },
        },
      }))
      try {
        const d = await apiPost<{ views: Record<string, boolean> }>(
          `/characters/${enc}/model-refs/views`, { [view]: value })
        setInfo((prev) => {
          const merged: NonNullable<RefsInfo['views']> = {}
          VIEW_ORDER.filter((v) => v in (prev.views || {})).forEach((v) => {
            merged[v] = { ...(prev.views?.[v] || {}), enabled: !!d.views?.[v] }
          })
          return { ...prev, views: merged }
        })
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        load()
      }
    },
    [enc, load, t, toast],
  )

  const autoOn = (kind: RefKind) => info.auto?.[kind] !== false
  const anyAuto = kindList.some((k) => autoOn(k))

  // Server-reported state of OUR kinds, with how long it has persisted
  // (server clock, as of the last poll). -1 = not in that state.
  const st = (k: RefKind) => info.status?.[k]
  const running = anyRunning(info, kindList)
  const runningFor = Math.max(
    -1, ...kindList.map((k) => (st(k)?.running ? ageSeconds(info.now, st(k)?.started_at) : -1)))
  const scheduledFor = Math.max(
    -1, ...kindList.map((k) => (st(k)?.scheduled ? ageSeconds(info.now, st(k)?.scheduled_at) : -1)))
  const dueIn = Math.max(
    0, ...kindList.map((k) => (st(k)?.scheduled ? -ageSeconds(info.now, st(k)?.due_at) : 0)))
  // The user's own click answers immediately; a render that started on its
  // own (debounce fired, other tab) is announced once it persisted the delay.
  const showGenerating = busy || runningFor >= HINT_AFTER_S
  // "Queued" only when nothing renders yet and the timer has been armed for
  // the delay — a re-arm by another outfit mutation restarts that clock.
  const showQueued = !showGenerating && !running && scheduledFor >= HINT_AFTER_S
  // The button waits only for a REAL render (or the user's click) — a
  // scheduled timer must not stop the user from triggering right away.
  const blocked = busy || running

  const label = (kind: RefKind) => (kind === 'tpose' ? t('Pose') : t('Default pose'))
  // Own source strings on purpose: the bare "Back" is the navigation label
  // elsewhere and localizes accordingly — a back VIEW does not.
  const viewLabel = (view: string) =>
    view === 'face' ? t('Face view') : view === 'front' ? t('Front view') : view === 'back' ? t('Back view') : view === 'left' ? t('Left view') : t('Right view')
  const draftLabel = (view: string) =>
    view === 'back' ? t('Back draft') : view === 'left' ? t('Left draft') : t('Right draft')
  // The backend reports the available views for this character body form.
  const hasViews = kindList.includes('tpose') && !!info.views &&
    Object.keys(info.views).length > 0
  // On the base-body pipeline the dressed views are always rendered: only the
  // face view keeps its toggle.
  const toggleViews = VIEW_ORDER.filter(
    (view) => view in (info.views || {}) && (!info.pipeline || view === 'face'))

  return (
    <div className="ga-form">
      {genError ? <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{genError}</div> : null}
      <div style={{ display: 'flex', gap: 8 }}>
        {kindList.map((kind) => {
          const ri = info[kind]
          return (
            <div key={kind} style={{ flex: 1, minWidth: 0 }}>
              {kindList.length > 1 ? <div className="ga-hint">{label(kind)}</div> : null}
              {ri ? (
                <RefImage
                  // Key by bust so an outfit switch mounts a fresh element —
                  // no stale hidden/size state from a previous render.
                  key={`${kind}-${bust}`}
                  src={`/characters/${enc}/model-refs/${kind}?v=${bust}`}
                  height={320}
                  radius={8}
                  label={label(kind)}
                  meta={ri}
                  action={kind === 'tpose' ? (
                    <button
                      type="button"
                      className="ga-btn ga-btn-sm"
                      disabled={blocked}
                      onClick={() => generate('main')}
                      aria-label={`${t('Regenerate')} · ${t('Main view')}`}
                    >
                      {t('Regenerate')}
                    </button>
                  ) : undefined}
                />
              ) : (
                <div className="ga-hint">{t('No render yet')}</div>
              )}
              {kind === 'tpose' && !ri ? (
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  disabled={blocked}
                  onClick={() => generate('main')}
                  aria-label={`${t('Regenerate')} · ${t('Main view')}`}
                >
                  {t('Regenerate')} · {t('Main view')}
                </button>
              ) : null}
              {kind === 'tpose' &&
              VIEW_ORDER.some((v) => info.views?.[v]?.enabled) ? (
                // Extra T-pose views share the T-pose status lane, but each
                // can be regenerated without replacing the other images.
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  {VIEW_ORDER.filter((v) => info.views?.[v]?.enabled).map(
                    (view) => {
                      const vi = info.views?.[view]?.info
                      return (
                        <div key={view} style={{ flex: 1, minWidth: 0 }}>
                          <div className="ga-hint">{viewLabel(view)}</div>
                          {view === 'face' ? <div className="ga-hint">
                            {t('from profile picture')}
                            {info.face_view?.stale ? <span title={t('The profile picture changed — regenerate')}> · {t('stale')}</span> : null}
                            {info.face_view?.rendering ? <span> · {t('Generating…')}</span> : null}
                          </div> : null}
                          {vi?.warning ? (
                            <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>{vi.warning}</div>
                          ) : null}
                          {vi ? (
                            <RefImage
                              key={`${view}-${bust}`}
                              src={`${view === 'face' ? info.face_view?.url : `/characters/${enc}/model-refs/tpose_${view}`}?v=${bust}`}
                              height={110}
                              radius={6}
                              compact
                              label={viewLabel(view)}
                              meta={vi}
                              action={(
                                <button
                                  type="button"
                                  className="ga-btn ga-btn-sm"
                                  style={{ fontSize: 10, padding: '1px 5px' }}
                                  disabled={view === 'face' ? busy || !!info.face_view?.rendering : blocked || !info.tpose}
                                  onClick={() => (view === 'face' ? setFaceDialogOpen(true) : generate(view))}
                                  aria-label={`${t('Regenerate')} · ${viewLabel(view)}`}
                                >
                                  {t('Regenerate')}
                                </button>
                              )}
                            />
                          ) : (
                            <>
                              <div className="ga-hint">{t('No render yet')}</div>
                              <button
                                type="button"
                                className="ga-btn ga-btn-sm"
                                disabled={view === 'face' ? busy || !!info.face_view?.rendering : blocked || !info.tpose}
                                onClick={() => (view === 'face' ? setFaceDialogOpen(true) : generate(view))}
                                aria-label={`${t('Regenerate')} · ${viewLabel(view)}`}
                              >
                                {t('Regenerate')}
                              </button>
                            </>
                          )}
                        </div>
                      )
                    },
                  )}
                  {info.pipeline ? DRAFT_ORDER.filter((v) => info.views?.[v] && info.drafts && v in info.drafts).map((view) => {
                    // The view's draft (rendered from the dressed front; only
                    // its clothing is fitted onto the base view). Regenerating
                    // the view renders draft and fit anew.
                    const draft = info.drafts?.[view]
                    const label = draftLabel(view)
                    return (
                      <div key={`draft-${view}`} style={{ flex: 1, minWidth: 0 }}>
                        <div className="ga-hint">{label}</div>
                        {draft ? (
                          <RefImage
                            key={`${view}-draft-${bust}`}
                            src={`/characters/${enc}/model-refs/tpose_${view}_draft?v=${bust}`}
                            height={110}
                            radius={6}
                            compact
                            label={label}
                            meta={draft}
                          />
                        ) : (
                          <div className="ga-hint">{t('No render yet')}</div>
                        )}
                      </div>
                    )
                  }) : null}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="ga-hint">
        {kindList.includes('tpose')
          ? t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination. The pose render feeds the image-to-3D pipeline.')
          : t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination.')}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={blocked || !anyAuto}
          onClick={() => generate()}
        >
          {showGenerating ? t('Generating…') : t('Generate')}
        </button>
        {showQueued ? (
          <span className="ga-hint">
            {dueIn > 0
              ? t('Render queued · starts in {s} s').replace('{s}', String(Math.round(dueIn)))
              : t('Render queued')}
          </span>
        ) : null}
        {kindList.map((kind) => (
          <label
            key={kind}
            style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}
            title={t('Render this image automatically after outfit changes')}
          >
            <input
              type="checkbox"
              checked={autoOn(kind)}
              onChange={(e) => setAuto(kind, e.target.checked)}
            />
            <span>
              {t('Auto')}
              {kindList.length > 1 ? ` · ${label(kind)}` : ''}
            </span>
          </label>
        ))}
        {hasViews
          ? toggleViews.map((view) => (
              <label
                key={view}
                style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}
                title={view === 'face' ? t('Render a face close-up for face retexture') : t('Render this extra pose view for multi-view 3D generation')}
              >
                <input
                  type="checkbox"
                  checked={!!info.views?.[view]?.enabled}
                  onChange={(e) => setView(view, e.target.checked)}
                />
                <span>{viewLabel(view)}</span>
              </label>
            ))
          : null}
      </div>
      <ImageGenDialog
        open={faceDialogOpen}
        title={`${t('Generate face view')} · ${character}`}
        defaultPrompt={info.face_view?.prompt || ''}
        sourceImageUrl={info.face_view?.profile_url || undefined}
        defaultUseSource
        requireSourceReference
        sourceReferenceLabel={t('Profile picture as reference')}
        occasion="tpose_view"
        occasionCharacter={character}
        onSubmit={generateFace}
        onClose={closeFaceDialog}
      />
    </div>
  )
}
