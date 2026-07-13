/**
 * FieldModelRefs — T-pose + default-pose reference renders of a character
 * in the CURRENT outfit (3D pipeline inputs). Rendered template-driven via
 * the section flag `special: "model_refs"` (slot wired in CharactersTab).
 *
 * Backend: GET /characters/{name}/model-refs (info),
 * GET .../model-refs/{tpose|pose} (image), POST .../model-refs/generate.
 * The pair is also generated automatically after outfit changes (debounced,
 * see admin settings "Image/Video Generation").
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
  pending?: boolean
}

// Display order: default pose first, T-pose second (wardrobe + 3D tab).
const KINDS = ['pose', 'tpose'] as const

export function FieldModelRefs({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<RefsInfo>({})
  const [bust, setBust] = useState(1)
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    if (!character) return
    try {
      setInfo(await apiGet<RefsInfo>(`/characters/${enc}/model-refs`))
    } catch {
      setInfo({})
    }
  }, [character, enc])

  useEffect(() => {
    load()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [load])

  // Generation renders two images sequentially — poll a while and refresh
  // both the info (timestamps) and the image URLs via cache-buster.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    pollRef.current = setInterval(async () => {
      n += 1
      await load()
      setBust((b) => b + 1)
      if (n >= 60) {
        if (pollRef.current) clearInterval(pollRef.current)
        setBusy(false)
      }
    }, 3000)
  }, [load])

  const generate = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      await apiPost(`/characters/${enc}/model-refs/generate`, {})
      toast(t('Generating…'))
      startPoll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [busy, enc, startPoll, t, toast])

  // Per-image toggle for the automatic outfit-change render (persisted per
  // character); the Generate button fires exactly the checked ones.
  const setAuto = useCallback(
    async (kind: (typeof KINDS)[number], value: boolean) => {
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

  const autoOn = (kind: (typeof KINDS)[number]) => info.auto?.[kind] !== false
  const anyAuto = KINDS.some((k) => autoOn(k))

  const label = (kind: (typeof KINDS)[number]) =>
    kind === 'tpose' ? t('T-pose') : t('Default pose')

  return (
    <div className="ga-form">
      <div style={{ display: 'flex', gap: 8 }}>
        {KINDS.map((kind) => {
          const ri = info[kind]
          return (
            <div key={kind} style={{ flex: 1, minWidth: 0 }}>
              <div className="ga-hint">{label(kind)}</div>
              {ri ? (
                <img
                  src={`/characters/${enc}/model-refs/${kind}?v=${bust}`}
                  alt=""
                  style={{
                    // Fixed shared height so both panes always line up
                    // (320px = the tpl-field-image preview cap).
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
        {t('Checked images are rendered automatically after outfit changes (debounced, cached per outfit combination); Generate re-renders the current combination. The T-pose image feeds the image-to-3D pipeline.')}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !anyAuto}
          onClick={generate}
        >
          {busy ? t('Generating…') : t('Generate')}
        </button>
        {KINDS.map((kind) => (
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
            <span>{label(kind)}</span>
          </label>
        ))}
      </div>
    </div>
  )
}
