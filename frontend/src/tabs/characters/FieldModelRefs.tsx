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
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface RefInfo {
  filename?: string
  created_at?: string
  backend?: string
}

interface RefsInfo {
  tpose?: RefInfo | null
  pose?: RefInfo | null
  auto?: { tpose?: boolean; pose?: boolean }
  // Per image — a running default-pose render must not lock the 3D tab's
  // T-pose button (and vice versa): with several backends they run in parallel.
  pending?: { tpose?: boolean; pose?: boolean }
}

type RefKind = 'pose' | 'tpose'

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
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const settleRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const kindsKey = kinds.join(',')

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

  // Only THIS tab's kinds matter — the other tab's render must not lock us.
  const myPending = useCallback(
    (d?: RefsInfo | null) => kinds.some((k) => !!d?.pending?.[k]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [kindsKey],
  )

  // Poll until the backend reports OUR kinds finished (pending clears),
  // refreshing both the info (timestamps) and the image URLs via cache-buster.
  // n>=60 (~180s) is only the give-up bound; the button must not stay locked
  // for the full timeout once the render is done.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    pollRef.current = setInterval(async () => {
      n += 1
      const d = await load()
      setBust((b) => b + 1)
      if (!myPending(d) || n >= 60) {
        if (pollRef.current) clearInterval(pollRef.current)
        setBusy(false)
      }
    }, 3000)
  }, [load, myPending])

  // Reload + cache-bust whenever the character OR the outfit (refreshKey)
  // changes, so a switch to a different combination shows THAT combination's
  // render instead of the previously loaded image. A local busy flag from the
  // previous character must not bleed across the switch. When a render is
  // already running (switched in / debounced) track it to completion; and when
  // a shown render is still missing (the outfit-change render is debounced
  // ~60s), keep polling a bounded while so it appears without reopening the tab.
  useEffect(() => {
    let cancelled = false
    let tries = 0
    setBusy(false)
    const tick = async () => {
      const d = await load()
      if (cancelled) return
      setBust((b) => b + 1)
      if (myPending(d)) startPoll()
      const missing = kinds.some((k) => !d?.[k])
      tries += 1
      if (missing && tries < 22) {
        settleRef.current = setTimeout(tick, 6000)
      }
    }
    tick()
    return () => {
      cancelled = true
      if (settleRef.current) clearTimeout(settleRef.current)
      if (pollRef.current) clearInterval(pollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, refreshKey, kindsKey])

  const generate = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      // Only this tab's checked kinds — wardrobe (pose) and 3D tab (tpose)
      // fire independent renders.
      const wanted = kinds.filter((k) => info.auto?.[k] !== false)
      await apiPost(`/characters/${enc}/model-refs/generate`, { kinds: wanted })
      toast(t('Generating…'))
      startPoll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, enc, kindsKey, info.auto, startPoll, t, toast])

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

  const autoOn = (kind: RefKind) => info.auto?.[kind] !== false
  const anyAuto = kinds.some((k) => autoOn(k))
  // A render of OUR kinds is in flight if the backend says so (manual, auto,
  // or switched in) or a local click just fired — either way the button waits.
  const pending = myPending(info) || busy

  const label = (kind: RefKind) => (kind === 'tpose' ? t('T-pose') : t('Default pose'))

  return (
    <div className="ga-form">
      <div style={{ display: 'flex', gap: 8 }}>
        {kinds.map((kind) => {
          const ri = info[kind]
          return (
            <div key={kind} style={{ flex: 1, minWidth: 0 }}>
              {kinds.length > 1 ? <div className="ga-hint">{label(kind)}</div> : null}
              {ri ? (
                <img
                  // Key by bust so an outfit switch mounts a fresh element —
                  // no stale visibility:hidden from a previous missing render.
                  key={`${kind}-${bust}`}
                  src={`/characters/${enc}/model-refs/${kind}?v=${bust}`}
                  alt=""
                  style={{
                    width: '100%',
                    height: 320,
                    objectFit: 'contain',
                    borderRadius: 8,
                    border: '1px solid var(--border, #30363d)',
                    background: 'rgba(255, 255, 255, 0.04)',
                  }}
                  onError={(e) => {
                    ;(e.target as HTMLImageElement).style.visibility = 'hidden'
                  }}
                />
              ) : (
                <div className="ga-hint">{t('No render yet')}</div>
              )}
              {ri?.created_at ? (
                <div className="ga-hint">{new Date(ri.created_at).toLocaleString()}</div>
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="ga-hint">
        {kinds.includes('tpose')
          ? t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination. The T-pose image feeds the image-to-3D pipeline.')
          : t('Rendered automatically after outfit changes (debounced); Generate re-renders the current combination.')}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={pending || !anyAuto}
          onClick={generate}
        >
          {pending ? t('Generating…') : t('Generate')}
        </button>
        {kinds.map((kind) => (
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
              {kinds.length > 1 ? ` · ${label(kind)}` : ''}
            </span>
          </label>
        ))}
      </div>
    </div>
  )
}
