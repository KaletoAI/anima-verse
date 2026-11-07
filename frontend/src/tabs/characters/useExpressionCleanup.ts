import { useEffect, useRef, useState } from 'react'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import { useI18n } from '../../i18n/I18nProvider'

export interface CleanupFile { file: string; action: 'keep' | 'adopt' | 'remove' | 'review'; reason: string; target?: string }
interface CleanupPreview { revision: string; counts: Record<CleanupFile['action'], number>; files: CleanupFile[] }

/**
 * Expression cleanup: preview what would be adopted/removed, then apply exactly
 * that. Split in three so the trigger can sit in the Expressions tab's header
 * row while the preview opens below it: `useExpressionCleanup` holds the state,
 * `ExpressionCleanupButton` starts a preview, `ExpressionCleanupPreview` shows it.
 */
export function useExpressionCleanup(character: string, onChanged: () => Promise<void>) {
  const { t } = useI18n()
  const [preview, setPreview] = useState<CleanupPreview | null>(null)
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')
  const generation = useRef(0)
  const base = `/characters/${encodeURIComponent(character)}`
  useEffect(() => {
    generation.current += 1
    setPreview(null); setArmed(false); setBusy(false); setError(''); setResult('')
    return () => { generation.current += 1 }
  }, [character])
  const load = async () => {
    const current = generation.current
    setBusy(true); setArmed(false); setError(''); setResult('')
    try {
      const response = await apiGet<CleanupPreview>(`${base}/expression-cleanup`)
      if (current === generation.current) setPreview(response)
    } catch (e) { if (current === generation.current) setError((e as Error).message) }
    finally { if (current === generation.current) setBusy(false) }
  }
  const apply = async () => {
    if (!preview || busy) return
    const current = generation.current
    setBusy(true); setError('')
    try {
      const response = await apiPost<Record<string, number>>(`${base}/expression-cleanup`, { revision: preview.revision })
      if (current !== generation.current) return
      setResult(`${t('Cleanup applied')}: ${t('Adopted')} ${response.adopted}, ${t('Removed')} ${response.removed}`)
      setPreview(null); setArmed(false)
      await onChanged()
    } catch (e) {
      if (current !== generation.current) return
      setArmed(false)
      if (e instanceof ApiError && e.status === 409) {
        try {
          const refreshed = await apiGet<CleanupPreview>(`${base}/expression-cleanup`)
          if (current === generation.current) {
            setPreview(refreshed)
            setError(t('The preview changed. Review the refreshed actions before applying.'))
          }
        } catch (refreshError) {
          if (current === generation.current) {
            setPreview(null)
            setError((refreshError as Error).message)
          }
        }
      } else if (e instanceof ApiError && e.detail && typeof e.detail === 'object') {
        const detail = e.detail as { message?: string; completed?: Record<string, number> }
        setError(`${detail.message || e.message}${detail.completed ? ` — ${t('Completed operations')}: ${JSON.stringify(detail.completed)}` : ''}`)
        setPreview(null)
        await onChanged()
      } else setError((e as Error).message)
    } finally { if (current === generation.current) setBusy(false) }
  }
  return { base, preview, setPreview, armed, setArmed, busy, error, result, load, apply }
}

export type ExpressionCleanup = ReturnType<typeof useExpressionCleanup>
