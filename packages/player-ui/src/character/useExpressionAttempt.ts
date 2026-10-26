import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '../api'

interface ExpressionAttempt {
  attempt_id: string
  identity: string
  state: 'pending' | 'running' | 'ready' | 'failed' | 'superseded' | 'invalidated'
  content_version: string
  error: string
}

/** Explicit force follows the accepted attempt, not a changing current-state URL. */
export function useExpressionAttempt(character: string) {
  const [attempt, setAttempt] = useState<ExpressionAttempt | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  useEffect(() => {
    generation.current += 1
    setAttempt(null)
    setStarting(false)
    setError('')
    return () => { generation.current += 1 }
  }, [character])
  const start = useCallback(async (body: Record<string, unknown>) => {
    const current = generation.current
    setStarting(true)
    setError('')
    try {
      const result = await apiPost<ExpressionAttempt>(`/characters/${encodeURIComponent(character)}/expression-generation`, body)
      if (current === generation.current) {
        setAttempt(result)
        if (result.state === 'failed' || result.state === 'invalidated' || result.state === 'superseded') setError(result.error || result.state)
      }
    } catch (e) { if (current === generation.current) setError((e as Error).message) }
    finally { if (current === generation.current) setStarting(false) }
  }, [character])
  const id = attempt?.attempt_id
  const polling = attempt?.state === 'pending' || attempt?.state === 'running'
  useEffect(() => {
    if (!id || !polling) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const result = await apiGet<ExpressionAttempt>(`/characters/${encodeURIComponent(character)}/expression-status?attempt_id=${encodeURIComponent(id)}`)
        if (!alive) return
        setAttempt(result)
        if (result.state === 'pending' || result.state === 'running') timer = setTimeout(() => { void poll() }, 2000)
        else if (result.state !== 'ready') setError(result.error || result.state)
      } catch (e) {
        if (!alive) return
        setError((e as Error).message)
        setAttempt(null)
      }
    }
    timer = setTimeout(() => { void poll() }, 1000)
    return () => { alive = false; clearTimeout(timer) }
  }, [character, id, polling])
  return { start, error, busy: starting || attempt?.state === 'pending' || attempt?.state === 'running',
    contentVersion: attempt?.state === 'ready' ? attempt.content_version : '', state: attempt?.state }
}
