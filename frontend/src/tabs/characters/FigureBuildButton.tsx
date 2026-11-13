/**
 * FigureBuildButton — the Figure tab's Build on another screen (Ruling A13b): the Pose tab's outfit-model status
 * and the 3D tab's Model row start the same `POST …/figure/build` with the same label and job count
 * ("Build (N jobs)" / "Build base body (N jobs)", `figureModel.buildButton`) — never a cascade of their own.
 * Reads `GET …/figure` through useFigure (polled while a Build runs); renders nothing off the pipeline.
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { BUILD_RUNNING_NOTE, BUILD_STATUS, buildButton } from './figureModel'
import { useFigure } from './useFigure'

export function FigureBuildButton({ character, onStarted }: {
  character: string
  /** A Build was started or queued (the caller re-reads its own status). */
  onStarted?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { data, startPoll } = useFigure(character)
  const [posting, setPosting] = useState(false)

  const build = useCallback(async () => {
    if (posting) return
    setPosting(true)
    try {
      const d = await apiPost<Record<string, unknown>>(`/characters/${enc}/figure/build`, {})
      const status = String(d?.status || '')
      toast(t(BUILD_STATUS[status] || status), 'success')
      onStarted?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      startPoll(300)
    }
  }, [enc, onStarted, posting, startPoll, t, toast])

  if (!data?.pipeline) return null
  const button = buildButton(data, t)
  return (
    <>
      <button type="button" className="ga-btn ga-btn-sm" disabled={posting || !!button.disabled}
        title={button.disabled || t(data.cost.note)} onClick={build}>
        {button.label}
      </button>
      {data.build.running ? <span className="ga-hint">{t(BUILD_RUNNING_NOTE)}</span> : null}
    </>
  )
}
