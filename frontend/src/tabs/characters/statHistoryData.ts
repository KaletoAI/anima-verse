import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import type { StatCause } from '@anima/player-ui'

export interface StatHistoryRow {
  id: number
  ts: string
  game_ts: string
  /** World-calendar label rendered by the server; empty for old rows. */
  game_label?: string
  label: string
  stat_labels?: Record<string, string>
  changes: Record<string, { old: number; new: number }>
  cause?: Record<string, StatCause & { rules?: { id: string; name: string; factor: number }[] }>
  event_id?: string
}

interface BarMeta {
  name?: string
  name_de?: string
}

/** The newest stat-history rows of one character, reloaded whenever
 *  `revision` changes. Shared by the sparklines in the Character tab and the
 *  history card in the Mind tab. */
export function useStatHistory(character: string, revision: string, limit = 30) {
  const [rows, setRows] = useState<StatHistoryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    setRows([])
    setLoading(true)
    setError('')
    apiGet<{ rows: StatHistoryRow[] }>(`/characters/${encodeURIComponent(character)}/stat-history?limit=${limit}`)
      .then(result => { if (alive) setRows(result.rows) })
      .catch(error => { if (alive) setError((error as Error).message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [character, revision, attempt, limit])
  return { rows, loading, error, retry: () => setAttempt(n => n + 1) }
}

/** Display names of a character's stats (`bar_meta` of the status-effects
 *  endpoint), for callers that do not load them already. */
export function useStatLabels(character: string): (key: string) => string {
  const { lang } = useI18n()
  const [meta, setMeta] = useState<Record<string, BarMeta>>({})
  useEffect(() => {
    let alive = true
    apiGet<{ bar_meta: Record<string, BarMeta> }>(`/characters/${encodeURIComponent(character)}/status-effects`)
      .then(result => { if (alive) setMeta(result.bar_meta || {}) })
      .catch(() => { if (alive) setMeta({}) })
    return () => { alive = false }
  }, [character])
  return useMemo(() => (key: string) => {
    const m = meta[key] || {}
    return (lang === 'de' ? m.name_de || m.name : m.name) || key
  }, [meta, lang])
}
