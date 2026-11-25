/**
 * useFigure — the Figure tab's state as `GET /characters/{name}/figure`
 * reports it (`app/core/figure_build.py::figure_info`, plan
 * 2026-11-12-unified-worn-pieces Task 10): one load, then a 3 s tick while
 * a Build or a body shape view's Regenerate runs (`build.running`, `body.shape.regenerate.running`; no give-up — a step may wait minutes in a
 * queue, after ~2 min the tick slows down), stopped on unmount / character
 * switch. `startPoll(delay)` after an own action (a Build, a single action of
 * the Body details) re-reads and keeps ticking while the Build runs. The push
 * topic `generation` (Ruling A42: the character's pause or its waiting jobs
 * changed — admins only) re-reads once, 300 ms after the last push of a burst.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { syncHub } from '@anima/player-ui'
import { apiGet } from '../../lib/api'
import { debounced } from '../../lib/guardedPoll'
import type { FigurePayload } from './figureModel'

const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40
const PUSH_DEBOUNCE_MS = 300

export function useFigure(character: string) {
  const enc = encodeURIComponent(character)
  const [data, setData] = useState<FigurePayload | null>(null)
  const [error, setError] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Poll generation: a tick of a stopped/restarted chain drops its result.
  const pollIdRef = useRef(0)

  const stopPoll = useCallback(() => {
    pollIdRef.current += 1
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  const startPoll = useCallback(
    (delayMs = 0) => {
      stopPoll()
      const id = pollIdRef.current
      let n = 0
      const tick = async () => {
        timerRef.current = null
        let d: FigurePayload | null = null
        let failure = ''
        try {
          d = await apiGet<FigurePayload>(`/characters/${enc}/figure`)
        } catch (e) {
          failure = (e as Error).message
        }
        if (pollIdRef.current !== id) return
        if (d) setData(d)
        setError(failure)
        // A body shape view's Regenerate (round 2026-11-25) keeps the tick too: the thumbnail changes at its end.
        if (!d?.build?.running && !d?.body?.shape?.regenerate?.running) return
        n += 1
        timerRef.current = setTimeout(tick, n >= POLL_SLOW_AFTER ? POLL_SLOW_MS : POLL_MS)
      }
      timerRef.current = setTimeout(tick, delayMs)
    },
    [enc, stopPoll],
  )

  useEffect(() => {
    setData(null)
    setError('')
    if (!character) return stopPoll
    startPoll()
    const onPush = debounced(() => startPoll(0), PUSH_DEBOUNCE_MS)
    const off = syncHub().onTopics(['generation'], onPush)
    return () => { off(); onPush.cancel(); stopPoll() }
  }, [character, startPoll, stopPoll])

  return { data, error, startPoll }
}
