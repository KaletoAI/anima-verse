/**
 * useModel3DStatus — `GET /characters/{name}/model3d` for the tabs that act
 * on a character's model without being the 3D tab itself (the Base body tab's
 * face and rig actions, the Pose tab's outfit-model preview). One load, then
 * a 3 s tick while the server reports a model run (`pending`); after ~2 min
 * the tick slows down. Stopped on unmount / character switch. The 3D tab
 * (FieldModel3D) keeps its own poll — it also drives the preview states.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { Model3DStatus } from './FieldModel3D'

const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40

export function useModel3DStatus(character: string) {
  const enc = encodeURIComponent(character)
  const [st, setSt] = useState<Model3DStatus | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollIdRef = useRef(0)

  const stopPoll = useCallback(() => {
    pollIdRef.current += 1
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  const startPoll = useCallback((delayMs = 0) => {
    stopPoll()
    const id = pollIdRef.current
    let n = 0
    const tick = async () => {
      timerRef.current = null
      let d: Model3DStatus | null = null
      try {
        d = await apiGet<Model3DStatus>(`/characters/${enc}/model3d`)
      } catch {
        d = null
      }
      if (pollIdRef.current !== id) return
      if (d) setSt(d)
      if (!d?.pending) return
      n += 1
      timerRef.current = setTimeout(tick, n >= POLL_SLOW_AFTER ? POLL_SLOW_MS : POLL_MS)
    }
    timerRef.current = setTimeout(tick, delayMs)
  }, [enc, stopPoll])

  /** One fresh read (resolves with it), restarting the poll when a run goes. */
  const load = useCallback(async () => {
    startPoll()
  }, [startPoll])

  useEffect(() => {
    setSt(null)
    if (!character) return stopPoll
    startPoll()
    return stopPoll
  }, [character, startPoll, stopPoll])

  return { st, setSt, load, startPoll }
}
