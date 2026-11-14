/**
 * FieldModelRefs — the character's reference renders in the CURRENT outfit.
 * Two kinds: `pose` (default-pose wardrobe preview) and `tpose` (input for the
 * image-to-3D pipeline). Which kinds are shown is chosen by the `kinds` prop —
 * the wardrobe shows only the default pose (`layout="row"`); the T-pose and its
 * views as step rows (`layout="steps"`, Task UI5) are the Figure tab's "Dressed
 * views" on the figure pipeline (Ruling A70) and the 3D tab's "Pose render" off it
 * (an animal, a temporary NPC).
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
import { StepRowView } from './StepRows'
import { DRAFT_NOTE, MAIN_FOLLOWUP, VIEW_FOLLOWUP, renderAllLabel, viewAction, viewRow } from './dressedViewsModel'
import type { DressedSource } from './dressedViewsModel'
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

export interface RefsInfo {
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
  /** Base-body pipeline: per dressed back/side view, the draft it was composited
   *  from (served as `tpose_<view>_draft`). */
  drafts?: Record<string, RefInfo | null>
  auto?: { tpose?: boolean; pose?: boolean }
  /** Base-body pipeline: the character's Build (it renders the dressed views; a manual
   *  render of them is refused while it runs — 409, shown under the images). */
  build?: { running: boolean; step?: string }
  /** Base-body pipeline: where a view's render comes from now — an edit (1 image job) or a copy of the body
   *  shape's view (no job; Ruling A70). Null when the server could not judge it. */
  dressed_source?: DressedSource | null
  // Per image — a running default-pose render must not lock the 3D tab's
  // T-pose button (and vice versa): with several backends they run in parallel.
  status?: Partial<Record<RefKind, KindStatus>>
  /** Server clock at response time — state ages are measured against it. */
  now?: string
}

/** Shown while the character's Build runs (it renders these views; Regenerate waits for it). */
const BUILD_RUNS_VIEWS = 'A Build is running for this character — it renders these views; regenerate after it'
/** On the figure pipeline (every humanoid): the dressed views are a step of the Figure tab's Build. */
const BUILD_MAKES_VIEWS = 'The Figure tab\'s Build makes these views (its "Build automatically" decides when). A back or side view is a draft composited onto the base view on the CPU — no second render.'

// Display order of the extra views (checkboxes and thumbnails alike).
const VIEW_ORDER = ['front', 'back', 'left', 'right', 'face'] as const
// Base-body views made from a draft, in display order.
const DRAFT_ORDER = ['back', 'left', 'right'] as const

type RefKind = 'pose' | 'tpose'

/** Thumbnail size of a step row (small: a click enlarges). */
const STEP_THUMB_W = 84
const STEP_THUMB_H = 140
/** A step row: its thumbnails, then where the view comes from and its button beside them (checklist point 5). */
const ROW_BODY = { display: 'flex', gap: 8, alignItems: 'flex-start' } as const
const ROW_ACTIONS = { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, flex: 1 } as const
/** A server-reported state is shown only after persisting this long. */
const HINT_AFTER_S = 20
/** Poll cadence while something runs or is scheduled; slows after ~2 min. */
const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40

/**
 * The body of POST …/model-refs/generate: one view → exactly that view's job (`{kinds: ['tpose'], view}` — an
 * explicit view ignores the auto toggles and replaces only that image); none → this panel's checked kinds, and on
 * the pipeline always the T-pose pass.
 */
export function generateBody(view: string | undefined, kinds: readonly RefKind[], info: Pick<RefsInfo, 'pipeline' | 'auto'>):
  { kinds: RefKind[]; view?: string } {
  if (view) return { kinds: ['tpose'], view }
  return { kinds: kinds.filter((k) => (!!info.pipeline && k === 'tpose') || info.auto?.[k] !== false), view }
}

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
/** A Build of a pipeline character runs: it renders the dressed views (`tpose`). */
const buildRunning = (d: RefsInfo | null | undefined, kinds: RefKind[]) =>
  kinds.includes('tpose') && !!d?.pipeline && !!d?.build?.running

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
  layout = 'row',
  onOpenBaseBody,
  onOpenBody,
  onLights,
  initialInfo,
}: {
  character: string
  kinds?: RefKind[]
  refreshKey?: string
  /** `steps`: the dressed views — one step row per view with its light, small thumbnails (a click enlarges) and
   *  its own Regenerate (Task UI5; the Figure tab's Dressed views, Ruling A70). `row`: the default-pose tile of the
   *  Wardrobe and General tabs. */
  layout?: 'row' | 'steps'
  /** `steps`: switches to the Base body tab (the face view is the plain body's; a copy of its view). */
  onOpenBaseBody?: () => void
  /** `steps`: switches to the Figure tab's Body sub-tab (a copy of the body shape's view). */
  onOpenBody?: () => void
  /** `steps`: the views' lights, comma-joined, for the tab's flow head. */
  onLights?: (lights: string) => void
  /** What is shown before the first load answers (scripts/check_figure_ui.mjs renders a fixture with it); the
   *  load replaces it. */
  initialInfo?: RefsInfo
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<RefsInfo>(initialInfo ?? {})
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
        const active = anyRunning(d, kindList) || anyScheduled(d, kindList) || buildRunning(d, kindList)
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
      setGenError('')
      const d = await apiPost<{ status?: string }>(`/characters/${enc}/model-refs/generate`,
        generateBody(view, kindList, { pipeline: info.pipeline, auto: info.auto }))
      // Ruling A70: nothing is painted on the figure — the server copies the view from its shape again (no job).
      toast(d?.status === 'copying' ? t('Copying the view from its body shape — no job') : t('Generating…'))
      // A beat for the worker thread to register as running before the first
      // status read — an idle read here would clear `busy` too early.
      startPoll(1000)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setGenError((e as Error).message)
      setBusy(false)
    }
  }, [busy, enc, kindList, info.auto, info.pipeline, startPoll, t, toast])

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
  // On the figure pipeline the T-pose pass is a step of the Build: the Figure tab's
  // "Build automatically" decides (one switch per thing), so this toggle is off-limits.
  const buildDecides = (kind: RefKind) => !!info.pipeline && kind === 'tpose'
  /** Every kind of this view is the Build's (the dressed views on the pipeline). */
  const pipelineViews = kindList.every(buildDecides)
  // What Generate fires: the checked kinds, and on the pipeline always the T-pose pass.
  const fires = (kind: RefKind) => buildDecides(kind) || autoOn(kind)
  const anyAuto = kindList.some((k) => fires(k))

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
  // A running Build renders the dressed views itself (a manual render is refused meanwhile).
  const building = buildRunning(info, kindList)
  const blocked = busy || running || building

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

  // One extra view (its regenerate button in the corner) and one draft tile.
  const renderView = (view: typeof VIEW_ORDER[number], height: number) => {
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
            height={height}
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
  }
  const renderDraft = (view: typeof DRAFT_ORDER[number], height: number) => {
    // The view's draft (rendered from the dressed front; only
    // its clothing is composited onto the base view on the CPU).
    // Regenerating the view renders the draft anew.
    const draft = info.drafts?.[view]
    const label = draftLabel(view)
    return (
      <div key={`draft-${view}`} style={{ flex: 1, minWidth: 0 }}>
        <div className="ga-hint">{label}</div>
        {draft ? (
          <RefImage
            key={`${view}-draft-${bust}`}
            src={`/characters/${enc}/model-refs/tpose_${view}_draft?v=${bust}`}
            height={height}
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
  }
  const draftViews = info.pipeline
    ? DRAFT_ORDER.filter((v) => info.views?.[v] && info.drafts && v in info.drafts) : []

  // `layout="steps"` (Task UI5; the Figure tab's Dressed views, Ruling A70): one step row per dressed view — light,
  // state, reason (mouse-over: the full reason and what resolves it), where the view comes from (an edit, or a copy
  // of the body shape's view with the link to where that view lives), small thumbnails that enlarge on a click and
  // the view's own button with its true cost. The face view is the plain body's (Base body tab, face retexture) on
  // the pipeline: a link and the one setting of the views pass that renders it.
  const tposeRunning = !!st('tpose')?.running || building
  const mainRow = viewRow(info.tpose, null, tposeRunning, t)
  const extraViews = VIEW_ORDER.filter((v) => v !== 'face' && info.views?.[v]?.enabled)
  const extraRows = extraViews.map((view) => ({ view, row: viewRow(info.views?.[view]?.info,
    info.pipeline ? info.drafts?.[view] : null, tposeRunning, t) }))
  const stepLights = layout === 'steps' && info.signature !== undefined
    ? [mainRow.light, ...extraRows.map((r) => r.row.light)].join(',') : ''
  useEffect(() => { if (stepLights) onLights?.(stepLights) }, [stepLights, onLights])

  if (layout === 'steps') {
    const thumb = (src: string, lbl: string, meta: RefInfo | null | undefined, k: string) => (
      <div key={k} style={{ width: STEP_THUMB_W, minWidth: 0 }}>
        <RefImage key={`${k}-${bust}`} src={`${src}?v=${bust}`} width={STEP_THUMB_W} height={STEP_THUMB_H} radius={6}
          compact label={lbl} meta={meta} />
        <div className="ga-hint" style={{ fontSize: 11 }}>{lbl}</div>
      </div>
    )
    const viewDisabled = (needsMain: boolean): string | null =>
      building ? t(BUILD_RUNS_VIEWS) : busy || running ? t('Rendering…') : needsMain && !info.tpose
        ? t('Render the main view first') : null
    // Ruling A70: an edit costs 1 image job; a copy of the body shape's view costs none and says so.
    const action = viewAction(info.pipeline ? info.dressed_source : null, t)
    const copy = action.jobs === 0
    const source = info.pipeline && info.dressed_source ? info.dressed_source : null
    const plainShape = !!source && source.shape.startsWith('base')
    const fromLine = !source ? null : (
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="ga-hint" title={copy ? action.note : undefined}>
          {source.source === 'shape' ? t('Copy of the body shape’s view — nothing painted')
            : source.source === 'plain' ? t('Copy of the plain body’s view — nothing painted')
              : plainShape ? t('Painted on the plain body’s view') : t('Painted on the body shape’s view')}
        </span>
        {plainShape ? (onOpenBaseBody ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}
            title={t('The plain body’s views are made in the Base body tab')}>↗ {t('Base body')}</button>
        ) : null) : onOpenBody ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBody}
            title={t('The body shape and its pieces: the Body sub-tab')}>↗ {t('Body')}</button>
        ) : null}
      </div>
    )
    const regen = (view: 'main' | typeof VIEW_ORDER[number], title: string) => {
      const why = viewDisabled(view !== 'main')
      return (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={!!why} title={why || (copy ? action.note : title)}
            onClick={() => generate(view)}
            aria-label={`${t('Regenerate')} · ${view === 'main' ? t('Main view') : viewLabel(view)}`}>
            {action.label}
          </button>
          {why && why !== t('Rendering…') ? <span className="ga-hint">{why}</span> : null}
        </div>
      )
    }
    const faceInfo = info.views?.face
    const faceOn = !!faceInfo?.enabled
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
        {genError ? <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{genError}</div> : null}
        <StepRowView row={{ name: t('Main view'), ...mainRow }}>
          <div style={ROW_BODY}>
            {info.tpose ? thumb(`/characters/${enc}/model-refs/tpose`, t('Front view'), info.tpose, 'main') : null}
            <div style={ROW_ACTIONS}>
              {fromLine}
              {regen('main', info.pipeline ? `${t(MAIN_FOLLOWUP)}\n${t(VIEW_FOLLOWUP)}` : '')}
            </div>
          </div>
        </StepRowView>
        {extraRows.map(({ view, row }) => {
          const draft = info.pipeline ? info.drafts?.[view] : null
          const vi = info.views?.[view]?.info
          return (
            <StepRowView key={view} row={{ name: viewLabel(view), ...row,
              detail: [row.detail, draft !== undefined && info.pipeline && !copy ? t(DRAFT_NOTE) : '']
                .filter(Boolean).join('\n') }}>
              <div style={ROW_BODY}>
                {vi ? thumb(`/characters/${enc}/model-refs/tpose_${view}`, viewLabel(view), vi, view) : null}
                {draft ? thumb(`/characters/${enc}/model-refs/tpose_${view}_draft`, draftLabel(view), draft, `${view}-draft`)
                  : null}
                <div style={ROW_ACTIONS}>
                  {fromLine}
                  {regen(view, info.pipeline ? t(VIEW_FOLLOWUP) : '')}
                </div>
              </div>
            </StepRowView>
          )
        })}
        {faceInfo && info.pipeline ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span className="ga-hint">{t('Face view: it textures the plain body’s face — regenerated in the Base body tab')}</span>
              {onOpenBaseBody ? (
                <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}>↗ {t('Base body')}</button>
              ) : null}
            </div>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
              title={t('Render a face close-up for face retexture')}>
              <input type="checkbox" checked={faceOn} onChange={(e) => setView('face', e.target.checked)} />
              <span>{t('Render a missing face view with these views')}</span>
              <span className="ga-hint">{faceOn ? t('Saved — the next views render adds it if missing (1 image job)')
                : t('Saved — nothing runs')}</span>
            </label>
          </div>
        ) : faceInfo ? renderView('face', STEP_THUMB_H) : null}
        {info.pipeline ? null : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid var(--border, #30363d)',
            paddingTop: 6 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={blocked || !anyAuto}
                title={t('Re-renders the current combination, every switched-on view included')}
                onClick={() => generate()}>
                {showGenerating ? t('Generating…') : renderAllLabel(extraViews.length, t)}
              </button>
              {showQueued ? (
                <span className="ga-hint">
                  {dueIn > 0 ? t('Render queued · starts in {s} s').replace('{s}', String(Math.round(dueIn)))
                    : t('Render queued')}
                </span>
              ) : null}
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              {kindList.map((kind) => (
                <label key={kind} style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}
                  title={t('Render this image automatically after outfit changes')}>
                  <input type="checkbox" checked={autoOn(kind)} onChange={(e) => setAuto(kind, e.target.checked)} />
                  <span>{t('Auto')}</span>
                </label>
              ))}
              {toggleViews.map((view) => (
                <label key={view} style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}
                  title={view === 'face' ? t('Render a face close-up for face retexture')
                    : t('Render this extra pose view for multi-view 3D generation')}>
                  <input type="checkbox" checked={!!info.views?.[view]?.enabled}
                    onChange={(e) => setView(view, e.target.checked)} />
                  <span>{viewLabel(view)}</span>
                </label>
              ))}
            </div>
            <span className="ga-hint">{t('Saved at once — a view switched on renders with the next render (1 image job each)')}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="ga-form">
      {genError ? <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{genError}</div> : null}
      {building ? (
        <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>
          {t(BUILD_RUNS_VIEWS)}{info.build?.step ? ` · ${info.build.step}` : ''}
        </div>
      ) : null}
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
                  {VIEW_ORDER.filter((v) => info.views?.[v]?.enabled).map((view) => renderView(view, 110))}
                  {draftViews.map((view) => renderDraft(view, 110))}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="ga-hint">
        {kindList.includes('tpose') && info.pipeline
          ? t(BUILD_MAKES_VIEWS)
          : kindList.includes('tpose')
          ? t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination. The pose render feeds the image-to-3D pipeline.')
          : t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination.')}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* On the pipeline the dressed views are the Build's (its "Build (N jobs)" is this tab's Run all, beside
            the outfit model); a second all-views render here and the T-pose path's disabled Auto box are not
            shown (Task UI1, rule R4) — each view keeps its own Regenerate. */}
        {pipelineViews ? null : (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={blocked || !anyAuto}
            onClick={() => generate()}
          >
            {showGenerating ? t('Generating…') : t('Generate')}
          </button>
        )}
        {showQueued ? (
          <span className="ga-hint">
            {dueIn > 0
              ? t('Render queued · starts in {s} s').replace('{s}', String(Math.round(dueIn)))
              : t('Render queued')}
          </span>
        ) : null}
        {kindList.filter((kind) => !buildDecides(kind)).map((kind) => (
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
