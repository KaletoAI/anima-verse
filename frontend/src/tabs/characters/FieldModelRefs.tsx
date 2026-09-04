/**
 * FieldModelRefs — the character's reference renders in the CURRENT outfit.
 * Two kinds: `pose` (default-pose wardrobe preview) and `tpose` (input for the
 * image-to-3D pipeline). Which kinds are shown is chosen by the `kinds` prop —
 * the wardrobe shows only the default pose, the 3D tab only the T-pose.
 *
 * Backend: GET /characters/{name}/model-refs (info),
 * GET .../model-refs/{tpose|pose} (image), POST .../model-refs/generate.
 * The pair is also generated automatically after outfit changes (debounced).
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
import { useEnlarge } from '../../components/ZoomButton'

interface RefInfo {
  filename?: string
  created_at?: string
  backend?: string
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
  signature?: string
  tpose?: RefInfo | null
  pose?: RefInfo | null
  // Extra T-pose views for multi-view img2mesh (back/left/right). ALL three
  // are reported for a humanoid character (empty for a non-humanoid one), so
  // the checkboxes can be rendered; `enabled` is the per-character toggle,
  // `info` the stored render (null = not rendered yet). They have no own
  // status lane; they ride with `tpose`.
  views?: Record<string, { enabled: boolean; info?: RefInfo | null }>
  auto?: { tpose?: boolean; pose?: boolean }
  // Per image — a running default-pose render must not lock the 3D tab's
  // T-pose button (and vice versa): with several backends they run in parallel.
  status?: Partial<Record<RefKind, KindStatus>>
  /** Server clock at response time — state ages are measured against it. */
  now?: string
}

// Display order of the extra views (checkboxes and thumbnails alike).
const VIEW_ORDER = ['back', 'left', 'right'] as const

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
  kinds.some((k) => !!d?.status?.[k]?.running)
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
    kinds.map((k) => [d?.[k]?.filename || '', d?.[k]?.created_at || '']),
    VIEW_ORDER.map((v) => [
      d?.views?.[v]?.info?.filename || '',
      d?.views?.[v]?.info?.created_at || '',
    ]),
  ])
}

/**
 * Preview image with the render's pixel size as a corner badge. The size is
 * read from the loaded bitmap itself (naturalWidth/Height) — what the file
 * actually is, not what the config asked for. A click opens the render in
 * the shared Lightbox — the ONE place for all instances (T-pose + extra views).
 */
function RefImage({
  src,
  height,
  radius,
  showSize = false,
  label,
}: {
  src: string
  height: number
  radius: number
  showSize?: boolean
  /** Lightbox alt text (which render this is). */
  label?: string
}) {
  const [size, setSize] = useState('')
  const [hidden, setHidden] = useState(false)
  const enlarge = useEnlarge()
  const zoom = enlarge({ src, alt: label || '' })
  return (
    <div style={{ position: 'relative' }}>
      <img
        src={src}
        alt=""
        {...zoom}
        style={{
          ...zoom.style,
          display: 'block',
          width: '100%',
          height,
          objectFit: 'contain',
          borderRadius: radius,
          border: '1px solid var(--border, #30363d)',
          background: 'rgba(255, 255, 255, 0.04)',
          visibility: hidden ? 'hidden' : undefined,
        }}
        onLoad={(e) => {
          const im = e.target as HTMLImageElement
          setSize(`${im.naturalWidth}×${im.naturalHeight}`)
        }}
        onError={() => setHidden(true)}
      />
      {showSize && size && !hidden ? (
        <span
          style={{
            position: 'absolute',
            right: 6,
            bottom: 6,
            padding: '1px 5px',
            borderRadius: 4,
            background: 'rgba(0, 0, 0, 0.55)',
            color: '#fff',
            fontSize: 11,
            lineHeight: '16px',
            pointerEvents: 'none',
          }}
        >
          {size}
        </span>
      ) : null}
    </div>
  )
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

  const generate = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      // Only this tab's checked kinds — wardrobe (pose) and 3D tab (tpose)
      // fire independent renders.
      const wanted = kindList.filter((k) => info.auto?.[k] !== false)
      await apiPost(`/characters/${enc}/model-refs/generate`, { kinds: wanted })
      toast(t('Generating…'))
      // A beat for the worker thread to register as running before the first
      // status read — an idle read here would clear `busy` too early.
      startPoll(1000)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [busy, enc, kindList, info.auto, startPoll, t, toast])

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
          VIEW_ORDER.forEach((v) => {
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

  const label = (kind: RefKind) => (kind === 'tpose' ? t('T-pose') : t('Default pose'))
  // Own source strings on purpose: the bare "Back" is the navigation label
  // elsewhere and localizes accordingly — a back VIEW does not.
  const viewLabel = (view: string) =>
    view === 'back' ? t('Back view') : view === 'left' ? t('Left view') : t('Right view')
  // The extra views only exist for humanoid characters — the backend reports
  // an empty map for everyone else, and then there is nothing to offer.
  const hasViews = kindList.includes('tpose') && !!info.views &&
    Object.keys(info.views).length > 0

  return (
    <div className="ga-form">
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
                  showSize={kind === 'tpose'}
                  label={label(kind)}
                />
              ) : (
                <div className="ga-hint">{t('No render yet')}</div>
              )}
              {ri?.created_at ? (
                <div className="ga-hint">{new Date(ri.created_at).toLocaleString()}</div>
              ) : null}
              {kind === 'tpose' &&
              VIEW_ORDER.some((v) => info.views?.[v]?.enabled) ? (
                // Extra T-pose views (multi-view img2mesh input). Rendered as
                // part of the T-pose pass — no own buttons, just visibility.
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  {VIEW_ORDER.filter((v) => info.views?.[v]?.enabled).map(
                    (view) => {
                      const vi = info.views?.[view]?.info
                      return (
                        <div key={view} style={{ flex: 1, minWidth: 0 }}>
                          <div className="ga-hint">{viewLabel(view)}</div>
                          {vi ? (
                            <RefImage
                              key={`${view}-${bust}`}
                              src={`/characters/${enc}/model-refs/tpose_${view}?v=${bust}`}
                              height={110}
                              radius={6}
                              showSize
                              label={viewLabel(view)}
                            />
                          ) : (
                            <div className="ga-hint">{t('No render yet')}</div>
                          )}
                        </div>
                      )
                    },
                  )}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="ga-hint">
        {kindList.includes('tpose')
          ? t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination. The T-pose image feeds the image-to-3D pipeline.')
          : t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination.')}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={blocked || !anyAuto}
          onClick={generate}
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
          ? VIEW_ORDER.map((view) => (
              <label
                key={view}
                style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}
                title={t('Render this extra T-pose view for multi-view 3D generation')}
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
    </div>
  )
}
