/**
 * PromptImprover — the optional LLM row of the player image dialogs
 * (gallery/Instagram regenerate, diary-page regenerate, scene photo).
 *
 * "✨ Improve prompt": with a change wish the LLM rewrites the prompt
 * accordingly; with the wish left empty it only optimises the prompt for the
 * image model (same content).
 * "🦴 Check pose" + "Pose check before generating" (only when the dialog's
 * occasion renders people, `pose`): the LLM pose check repairs arms, legs and
 * poses (app/imagegen/pose_check.py) — now, into the prompt field, or right
 * before the render. Running it here switches the automatic check off; the
 * prompt is already checked.
 *
 * `media="video"` (the animate dialog) rewrites an image-to-video motion
 * prompt instead: the server keeps motion, camera and pacing (template
 * video_prompt_improver) and no pose controls are offered.
 *
 * Results replace the dialog's prompt field, so they stay visible and
 * editable before anything is generated. Same server route as the Game-Admin
 * dialog: POST /world/imagegen-enhance-prompt
 * { prompt, improvement_request?, mode? }.
 */
import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from './api'
import { useI18n } from './I18nProvider'

/** The pose-check part of an /world/imagegen-options answer. */
export interface PoseCheckOption { supported: boolean; default: boolean }

/** Pose-check state of a dialog: offered for occasions with people, preset
 * from the routing switch until the user touches it. `value` is undefined
 * when the occasion offers no check — the request then carries no override. */
export function usePoseCheck(option: PoseCheckOption | null | undefined) {
  const [checked, setChecked] = useState(false)
  const touched = useRef(false)
  useEffect(() => {
    if (option && !touched.current) setChecked(!!option.default)
  }, [option])
  const supported = !!option?.supported
  return {
    supported,
    checked,
    value: supported ? checked : undefined,
    set: (v: boolean) => { touched.current = true; setChecked(v) },
  }
}

/** The pose-check option of an occasion, for dialogs that do not read
 * /world/imagegen-options themselves. */
export function usePoseCheckOption(occasion: string): PoseCheckOption | null {
  const [option, setOption] = useState<PoseCheckOption | null>(null)
  useEffect(() => {
    let stale = false
    apiGet<{ pose_check?: PoseCheckOption }>(`/world/imagegen-options?occasion=${encodeURIComponent(occasion)}`)
      .then((d) => { if (!stale) setOption(d?.pose_check ?? null) })
      .catch(() => { if (!stale) setOption(null) })
    return () => { stale = true }
  }, [occasion])
  return option
}

export function PromptImprover({ prompt, onPrompt, disabled = false, onBusyChange, pose, media = 'image' }: {
  prompt: string
  onPrompt: (prompt: string) => void
  disabled?: boolean
  /** Lets the host block its Generate button while the LLM rewrites. */
  onBusyChange?: (busy: boolean) => void
  /** Pose-check state from `usePoseCheck`; omitted = no pose controls. */
  pose?: ReturnType<typeof usePoseCheck>
  /** What the prompt drives: an image render (default) or an image-to-video clip. */
  media?: 'image' | 'video'
}) {
  const { t } = useI18n()
  const [wish, setWish] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const run = async (mode: 'improve' | 'pose') => {
    const base = prompt.trim()
    if (!base || busy || disabled) return
    setBusy(true); onBusyChange?.(true); setError('')
    try {
      const res = await apiPost<{ prompt?: string }>('/world/imagegen-enhance-prompt',
        mode === 'pose' ? { prompt: base, mode: 'pose' }
          : { prompt: base, improvement_request: wish.trim(), ...(media === 'video' ? { mode: 'video' } : {}) })
      if (!alive.current) return
      if (res?.prompt) {
        onPrompt(res.prompt)
        if (mode === 'pose') pose?.set(false)
        else setWish('')
      }
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : t('Prompt improvement failed.'))
    } finally {
      if (alive.current) { setBusy(false); onBusyChange?.(false) }
    }
  }

  const off = busy || disabled
  return <div className="ga-field" style={{ marginBottom: 10 }}>
    <span className="ga-field-caption">{t('Improvement request')}</span>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      <input className="ga-input" style={{ flex: 1, minWidth: 140 }} value={wish} disabled={off}
        placeholder={t('What to change (optional)')}
        onChange={(e) => setWish(e.target.value)}
        // The player dialogs are forms: Enter here improves, it must not generate.
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void run('improve') } }} />
      <button type="button" className="ga-btn" disabled={off || !prompt.trim()}
        title={wish.trim()
          ? t('Rewrite the prompt with this change via LLM')
          : media === 'video'
            ? t('Optimise the prompt for the video model via LLM (content stays the same)')
            : t('Optimise the prompt for the image model via LLM (content stays the same)')}
        onClick={() => { void run('improve') }}>
        {busy ? '…' : `✨ ${t('Improve prompt')}`}
      </button>
      {pose?.supported && (
        <button type="button" className="ga-btn" disabled={off || !prompt.trim()}
          title={t('Repair arms, legs and poses in the prompt via LLM (what the image shows stays the same)')}
          onClick={() => { void run('pose') }}>
          {busy ? '…' : `🦴 ${t('Check pose')}`}
        </button>
      )}
    </div>
    {pose?.supported && (
      <label className="player-photo-check"
        title={t('An LLM repairs arms, legs and poses in the prompt right before the image is generated. Preset from the image routing of this occasion.')}>
        <input type="checkbox" checked={pose.checked} disabled={off}
          onChange={(e) => pose.set(e.target.checked)} />
        <span>{t('Pose check before generating')}</span>
      </label>
    )}
    {error && <div className="player-photo-hint" role="alert">{error}</div>}
  </div>
}
