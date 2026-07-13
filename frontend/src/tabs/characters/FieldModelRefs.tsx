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
  pending?: boolean
}

const KINDS = ['tpose', 'pose'] as const

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
                  style={{ width: '100%', borderRadius: 4 }}
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
        {t('Rendered automatically after outfit changes (debounced). The T-pose image feeds the image-to-3D pipeline.')}
      </div>
      <div>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={generate}>
          {busy ? t('Generating…') : t('Generate now')}
        </button>
      </div>
    </div>
  )
}
