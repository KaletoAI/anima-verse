/**
 * MindPanel — das Innenleben des Avatars (ersetzt das alte JournalPanel).
 * v1: Heute · Tagebuch · Erinnerungen — Beziehungen + Verlauf folgen als
 * eigene Sektionen (Navi ist darauf ausgelegt).
 *
 * Quellen (read-only):
 *   Heute        GET /characters/{avatar}/memory/today + GET /diary/me/{avatar}
 *   Tagebuch     GET /diary/me/{avatar}?date&type&limit&offset, /dates
 *   Erinnerungen GET /characters/{avatar}/memory/list?q&tier&source&related&sort
 * Einzige Schreib-Aktion: POST /diary/me/{avatar}/summary (async → Poll).
 * Das user_id-Segment der Diary-Routen wird serverseitig ignoriert → "me".
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { EmptyState } from './EmptyState'

// ---------------------------------------------------------------------------
// API-Shapes
// ---------------------------------------------------------------------------
interface DiaryEntry {
  type: string
  content: string
  timestamp: string
  end_timestamp?: string
  repeat_count?: number
  metadata?: Record<string, any>
}
interface DiaryResponse { entries: DiaryEntry[]; types: Record<string, string>; icons: Record<string, string> }

interface TodayStatus {
  location: string; location_id?: string; room?: string; room_id?: string
  activity: string; mood: string
  since?: { activity?: string | null; location?: string | null; mood?: string | null }
  last_warning?: string
}
interface ActiveMemory {
  id: number; memory_type: string; ts: string; content: string
  importance: number; related_character: string; score: number; tags: string[]
}
interface TodayResponse { character: string; now: string; status: TodayStatus; active_memories: ActiveMemory[] }

interface MemoryItem {
  id: number; timestamp: string; memory_type: string; content: string
  tags: string[]; importance: number; access_count: number
  related_character: string; source: string
}
interface MemoryFacets {
  tiers: Record<string, number>
  sources: Record<string, number>
  related_characters: Array<{ name: string; count: number }>
}
interface MemoryListResponse {
  character: string; total: number; total_unfiltered: number
  limit: number; offset: number; items: MemoryItem[]; facets: MemoryFacets
}

interface BondEvent { timestamp: string; type: string; initiator: string; summary: string; sentiment_delta: number }
interface BondItem {
  partner: string; type: string; strength: number
  sentiment_self_to_other: number; sentiment_other_to_self: number
  romantic_tension: number; interaction_count: number; last_interaction: string
  memories_count: number; history_recent: BondEvent[]
}

type HistoryKind = 'daily' | 'weekly' | 'monthly' | 'history' | 'evolution'
interface HistoryDailyItem { date: string; partner: string; content: string }
interface HistoryPeriodItem { week?: string; month?: string; content: string }
interface EvolutionItem {
  ts: string; trigger: string; beliefs: string; lessons: string; goals: string
  diff: null | Record<'beliefs' | 'lessons' | 'goals', { removed: string[]; added: string[] }>
}

// ---------------------------------------------------------------------------
// Format-Helfer
// ---------------------------------------------------------------------------
function clockOf(ts: string): string {
  const d = new Date(ts)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
function dayOf(ts: string): string {
  const d = new Date(ts)
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString()
}
/** „seit“-Stempel: heute nur Uhrzeit, sonst Datum + Uhrzeit. */
function sinceOf(ts: string | null | undefined): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const sameDay = d.toDateString() === new Date().toDateString()
  return sameDay ? clockOf(ts) : `${d.toLocaleDateString()} ${clockOf(ts)}`
}
function stars(n: number): string {
  return '★'.repeat(Math.max(0, Math.min(5, Math.round(n))))
}
/** Vorzeichenbehaftete Sentiment-Zahl mit Ampelfarbe. */
function SignedNum({ v }: { v: number }) {
  const color = v > 0.02 ? '#3fa45a' : v < -0.02 ? '#e05656' : 'inherit'
  return (
    <span style={{ color, fontVariantNumeric: 'tabular-nums' }}>
      {(v > 0 ? '+' : '') + v.toFixed(2)}
    </span>
  )
}

// Kompakt-Overrides zur Klasse ga-input (liefert soliden dunklen Hintergrund —
// wichtig fuer native <option>-Listen, die sonst weiss aufklappen).
const inputStyle: React.CSSProperties = {
  padding: '3px 8px', fontSize: '0.82em', minWidth: 0,
}
const chipBtnStyle: React.CSSProperties = {
  fontSize: '0.82em', cursor: 'pointer',
}
const sepStyle: React.CSSProperties = {
  margin: '6px 0 2px', fontSize: '0.74em', opacity: 0.55, letterSpacing: 0.4,
  borderBottom: '1px solid rgba(255,255,255,0.12)', paddingBottom: 2,
}

// ---------------------------------------------------------------------------
// Zeitstrahl-Zeile (Tagebuch/Heute): Uhrzeit | Icon | Inhalt (+Meta)
// ---------------------------------------------------------------------------
function TimelineRow({ e, icons }: { e: DiaryEntry; icons: Record<string, string> }) {
  const meta = e.metadata || {}
  const bits: string[] = []
  if (meta.partner) bits.push(String(meta.partner))
  if (meta.location_name) bits.push(String(meta.location_name))
  if (meta.outcome) bits.push(String(meta.outcome))
  if (e.repeat_count && e.repeat_count > 1) bits.push(`×${e.repeat_count}`)
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
      <span style={{ flex: '0 0 38px', opacity: 0.5, fontSize: '0.74em', fontVariantNumeric: 'tabular-nums' }}>
        {clockOf(e.timestamp)}
      </span>
      <span style={{ flex: '0 0 auto' }}>{icons[e.type] || '•'}</span>
      <span style={{ flex: 1, minWidth: 0, lineHeight: 1.35 }}>
        {e.content}
        {bits.length > 0 && (
          <span style={{ opacity: 0.5, fontSize: '0.78em' }}> · {bits.join(' · ')}</span>
        )}
      </span>
    </div>
  )
}

/** Entries chronologisch (neueste zuerst) mit Tages-Trennern rendern. */
function Timeline({ entries, icons, withDays }: {
  entries: DiaryEntry[]; icons: Record<string, string>; withDays: boolean
}) {
  const out: React.ReactNode[] = []
  let lastDay = ''
  entries.forEach((e, i) => {
    const day = dayOf(e.timestamp)
    if (withDays && day && day !== lastDay) {
      lastDay = day
      out.push(<div key={`d${day}${i}`} style={sepStyle}>{day}</div>)
    }
    out.push(<TimelineRow key={`e${i}`} e={e} icons={icons} />)
  })
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{out}</div>
}

// ---------------------------------------------------------------------------
// Sektion „Heute“ — Status + Tages-Zeitstrahl + aktive Erinnerungen
// ---------------------------------------------------------------------------
function TodayView({ avatar, onOpenMemories }: { avatar: string; onOpenMemories?: () => void }) {
  const { t } = useI18n()
  const [today, setToday] = useState<TodayResponse | null>(null)
  const [diary, setDiary] = useState<DiaryResponse | null>(null)
  const enc = encodeURIComponent(avatar)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const [td, dy] = await Promise.all([
          apiGet<TodayResponse>(`/characters/${enc}/memory/today`),
          apiGet<DiaryResponse>(`/diary/me/${enc}?limit=200`),
        ])
        if (alive) { setToday(td); setDiary(dy) }
      } catch { /* auth/offline — naechster Tick */ }
    }
    tick()
    const id = setInterval(tick, 10000)
    return () => { alive = false; clearInterval(id) }
  }, [enc])

  if (!today) return <EmptyState small icon="journal" title={t('Loading…')} />
  const s = today.status || ({} as TodayStatus)
  const since = s.since || {}

  const statusRow = (icon: string, value: string, sinceTs?: string | null) => value ? (
    <div style={{ display: 'flex', gap: 7, alignItems: 'baseline', minWidth: 0 }}>
      <span style={{ flex: '0 0 auto' }}>{icon}</span>
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
      {sinceTs ? (
        <span style={{ flex: '0 0 auto', opacity: 0.45, fontSize: '0.74em' }}>
          {t('since')} {sinceOf(sinceTs)}
        </span>
      ) : null}
    </div>
  ) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px',
                    borderRadius: 8, background: 'rgba(255,255,255,0.05)' }}>
        {statusRow('📍', [s.location, s.room].filter(Boolean).join(' · '), since.location)}
        {statusRow('🎭', s.activity, since.activity)}
        {statusRow('🙂', s.mood, since.mood)}
        {s.last_warning ? (
          <div style={{ fontSize: '0.78em', color: '#e0a356' }}>⚠ {s.last_warning}</div>
        ) : null}
      </div>

      {/* „Im Kopf“ direkt beim Status (beides = aktueller Zustand), kompakt
          auf Top 6 — das volle Archiv ist einen Klick entfernt. Der Tages-
          Zeitstrahl bekommt dadurch das untere, wachsende Ende. */}
      {today.active_memories && today.active_memories.length > 0 && (
        <div>
          <div style={{ ...sepStyle, display: 'flex', alignItems: 'baseline' }}
               title={t('What is on their mind right now — top memories ranked by importance, decay and recency. The Memories section is the full searchable archive.')}>
            <span>{t('Active memories')}</span>
            {onOpenMemories && (
              <button onClick={onOpenMemories}
                style={{ marginLeft: 'auto', background: 'none', border: 0, padding: 0,
                         cursor: 'pointer', color: 'var(--accent, #6aa9ff)', fontSize: '1em' }}>
                {t('all')} →
              </button>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {today.active_memories.slice(0, 6).map((m) => (
              <div key={m.id} style={{ display: 'flex', flexDirection: 'column', gap: 1,
                                       padding: '3px 6px', borderRadius: 6, background: 'rgba(255,255,255,0.04)' }}>
                <div style={{ lineHeight: 1.3 }}>{m.content}</div>
                <div style={{ display: 'flex', gap: 8, fontSize: '0.72em', opacity: 0.55, flexWrap: 'wrap' }}>
                  <span>{stars(m.importance)}</span>
                  <span>{m.memory_type}</span>
                  {m.related_character ? <span>· {m.related_character}</span> : null}
                  <span style={{ marginLeft: 'auto' }}>{sinceOf(m.ts)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <div style={sepStyle}>{t('Today')}</div>
        {diary && diary.entries.length > 0
          ? <Timeline entries={diary.entries} icons={diary.icons || {}} withDays={false} />
          : <EmptyState small icon="journal" title={t('No entries yet')} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sektion „Tagebuch“ — Datum/Typ-Filter, Suche, Zeitstrahl, Tagesrückblick
// ---------------------------------------------------------------------------
function DiaryView({ avatar }: { avatar: string }) {
  const { t } = useI18n()
  const enc = encodeURIComponent(avatar)
  const LIMIT = 100
  const [dates, setDates] = useState<string[]>([])
  const [date, setDate] = useState<string>('')        // '' = heute (Server-Default)
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [q, setQ] = useState('')
  const [data, setData] = useState<DiaryResponse | null>(null)
  const [entries, setEntries] = useState<DiaryEntry[]>([])
  const [offset, setOffset] = useState(0)
  const [mayHaveMore, setMayHaveMore] = useState(false)
  const [genState, setGenState] = useState<'' | 'generating' | 'done' | 'exists' | 'empty' | 'error'>('')

  useEffect(() => {
    apiGet<string[]>(`/diary/me/${enc}/dates`).then(setDates).catch(() => setDates([]))
  }, [enc])

  const load = async (newOffset: number, append: boolean) => {
    const params = new URLSearchParams()
    if (date) params.set('date', date)
    if (typeFilter) params.set('type', typeFilter)
    params.set('limit', String(LIMIT))
    params.set('offset', String(newOffset))
    try {
      const d = await apiGet<DiaryResponse>(`/diary/me/${enc}?${params.toString()}`)
      setData(d)
      setEntries((prev) => append ? [...prev, ...d.entries] : d.entries)
      setOffset(newOffset)
      setMayHaveMore(d.entries.length >= LIMIT)
    } catch { /* offline/auth */ }
  }
  useEffect(() => { load(0, false) }, [enc, date, typeFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  // Nach „Summary erzeugen“: pollen bis der daily_summary-Eintrag erscheint
  // (max. 90s) — der Endpoint ist fire-&-forget.
  useEffect(() => {
    if (genState !== 'generating') return
    let tries = 0
    const id = setInterval(async () => {
      tries += 1
      await load(0, false)
      if (tries >= 22) { setGenState('error'); clearInterval(id) }
    }, 4000)
    return () => clearInterval(id)
  }, [genState]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (genState === 'generating' && entries.some((e) => e.type === 'daily_summary')) {
      setGenState('done')
    }
  }, [entries, genState])

  const generateSummary = async () => {
    setGenState('generating')
    try {
      await apiPost(`/diary/me/${enc}/summary`, date ? { date } : {})
    } catch (err: any) {
      const msg = String(err?.message || err)
      if (msg.includes('409')) setGenState('exists')
      else if (msg.includes('404')) setGenState('empty')
      else setGenState('error')
    }
  }

  const needle = q.trim().toLowerCase()
  const visible = needle
    ? entries.filter((e) => (e.content || '').toLowerCase().includes(needle))
    : entries
  const types = data?.types || {}
  const icons = data?.icons || {}
  const genLabel: Record<string, string> = {
    generating: t('generating…'), done: t('done'),
    exists: t('already summarized'), empty: t('no events for this day'), error: t('failed'),
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: '0 0 auto', alignItems: 'center' }}>
        <select className="ga-input" style={inputStyle} value={date} onChange={(e) => setDate(e.target.value)}>
          <option value="">{t('Today')}</option>
          <option value="all">{t('All days')}</option>
          {dates.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select className="ga-input" style={inputStyle} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">{t('All types')}</option>
          {Object.keys(types).map((k) => (
            <option key={k} value={k}>{(icons[k] ? icons[k] + ' ' : '') + (types[k] || k)}</option>
          ))}
        </select>
        <input className="ga-input" style={{ ...inputStyle, flex: 1, minWidth: 70 }} placeholder={t('Search…')}
               value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {date !== 'all' && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flex: '0 0 auto' }}>
          <button
            onClick={generateSummary}
            disabled={genState === 'generating'}
            className="player-chip"
            style={{ ...chipBtnStyle, cursor: genState === 'generating' ? 'wait' : 'pointer' }}>
            📔 {t('Generate day summary')}
          </button>
          {genState ? <span style={{ fontSize: '0.76em', opacity: 0.6 }}>{genLabel[genState] || ''}</span> : null}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {visible.length === 0
          ? <EmptyState small icon="journal" title={t('No entries')} />
          : <Timeline entries={visible} icons={icons} withDays={date === 'all'} />}
        {mayHaveMore && !needle && (
          <button className="player-chip" style={{ ...chipBtnStyle, marginTop: 8 }}
                  onClick={() => load(offset + LIMIT, true)}>
            {t('Load more')}
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sektion „Erinnerungen“ — Facetten-Suche über memory/list
// ---------------------------------------------------------------------------
function MemoriesView({ avatar, initialRelated = '' }: { avatar: string; initialRelated?: string }) {
  const { t } = useI18n()
  const enc = encodeURIComponent(avatar)
  const LIMIT = 50
  const [q, setQ] = useState('')
  const [qDebounced, setQDebounced] = useState('')
  const [tier, setTier] = useState('')
  const [source, setSource] = useState('')
  const [related, setRelated] = useState(initialRelated)
  const [sort, setSort] = useState('recent')
  const [resp, setResp] = useState<MemoryListResponse | null>(null)
  const [items, setItems] = useState<MemoryItem[]>([])
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    const id = setTimeout(() => setQDebounced(q.trim()), 300)
    return () => clearTimeout(id)
  }, [q])

  const load = async (newOffset: number, append: boolean) => {
    const params = new URLSearchParams()
    params.set('limit', String(LIMIT))
    params.set('offset', String(newOffset))
    params.set('sort', sort)
    if (qDebounced) params.set('q', qDebounced)
    if (tier) params.set('tier', tier)
    if (source) params.set('source', source)
    if (related) params.set('related', related)
    try {
      const d = await apiGet<MemoryListResponse>(`/characters/${enc}/memory/list?${params.toString()}`)
      setResp(d)
      setItems((prev) => append ? [...prev, ...d.items] : d.items)
      setOffset(newOffset)
    } catch { /* offline/auth */ }
  }
  useEffect(() => { load(0, false) }, [enc, qDebounced, tier, source, related, sort]) // eslint-disable-line react-hooks/exhaustive-deps

  const facets = resp?.facets
  const total = resp?.total ?? 0
  const optionList = (rec: Record<string, number> | undefined) =>
    Object.entries(rec || {}).map(([k, n]) => (
      <option key={k} value={k}>{k} ({n})</option>
    ))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: '0 0 auto' }}>
        <input className="ga-input" style={{ ...inputStyle, flex: '1 1 100%', minWidth: 90 }} placeholder={t('Search…')}
               value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="ga-input" style={inputStyle} value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="">{t('All tiers')}</option>
          {optionList(facets?.tiers)}
        </select>
        <select className="ga-input" style={inputStyle} value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">{t('All sources')}</option>
          {optionList(facets?.sources)}
        </select>
        <select className="ga-input" style={inputStyle} value={related} onChange={(e) => setRelated(e.target.value)}>
          <option value="">{t('Anyone')}</option>
          {related && !(facets?.related_characters || []).some((r) => r.name === related) && (
            <option value={related}>{related}</option>
          )}
          {(facets?.related_characters || []).map((r) => (
            <option key={r.name} value={r.name}>{r.name} ({r.count})</option>
          ))}
        </select>
        <select className="ga-input" style={inputStyle} value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="recent">{t('Recent')}</option>
          <option value="importance">{t('Importance')}</option>
          <option value="access">{t('Most accessed')}</option>
          <option value="score">{t('Score')}</option>
        </select>
      </div>

      <div style={{ fontSize: '0.74em', opacity: 0.5, flex: '0 0 auto' }}>
        {t('{n} memories').replace('{n}', String(total))}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 5 }}>
        {items.length === 0
          ? <EmptyState small icon="journal" title={t('No memories found')} />
          : items.map((m) => (
            <div key={m.id} style={{ display: 'flex', flexDirection: 'column', gap: 2,
                                     padding: '4px 6px', borderRadius: 6, background: 'rgba(255,255,255,0.04)' }}>
              <div style={{ lineHeight: 1.3 }}>{m.content}</div>
              <div style={{ display: 'flex', gap: 8, fontSize: '0.72em', opacity: 0.55, flexWrap: 'wrap' }}>
                <span>{stars(m.importance)}</span>
                <span>{m.memory_type}</span>
                {m.related_character ? <span>· {m.related_character}</span> : null}
                {m.source ? <span>· {m.source}</span> : null}
                {(m.tags || []).slice(0, 4).map((tag) => (
                  <span key={tag} style={{ border: '1px solid rgba(255,255,255,0.2)', borderRadius: 8,
                                           padding: '0 6px' }}>{tag}</span>
                ))}
                <span style={{ marginLeft: 'auto' }}>{sinceOf(m.timestamp)}</span>
              </div>
            </div>
          ))}
        {items.length < total && (
          <button className="player-chip" style={{ ...chipBtnStyle, alignSelf: 'flex-start' }}
                  onClick={() => load(offset + LIMIT, true)}>
            {t('Load more')} ({items.length}/{total})
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sektion „Beziehungen“ — Sentiment/Tension/Interaktionen je Partner
// ---------------------------------------------------------------------------
function BondsView({ avatar, onOpenMemories }: {
  avatar: string; onOpenMemories?: (partner: string) => void
}) {
  const { t } = useI18n()
  const enc = encodeURIComponent(avatar)
  const [items, setItems] = useState<BondItem[] | null>(null)
  const [open, setOpen] = useState<string>('')   // Partner mit ausgeklappter Historie

  useEffect(() => {
    let alive = true
    apiGet<{ items: BondItem[] }>(`/characters/${enc}/memory/relationships?history_limit=10`)
      .then((d) => { if (alive) setItems(d.items || []) })
      .catch(() => { if (alive) setItems([]) })
    return () => { alive = false }
  }, [enc])

  if (items === null) return <EmptyState small icon="journal" title={t('Loading…')} />
  if (items.length === 0) return <EmptyState small icon="journal" title={t('No bonds yet')} />

  return (
    <div style={{ height: '100%', minHeight: 0, overflow: 'auto',
                  display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.map((b) => {
        const expanded = open === b.partner
        return (
          <div key={b.partner} style={{ padding: '5px 7px', borderRadius: 6, background: 'rgba(255,255,255,0.04)' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', cursor: 'pointer' }}
                 onClick={() => setOpen(expanded ? '' : b.partner)}>
              <span style={{ fontWeight: 600, minWidth: 0, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.partner}</span>
              <span style={{ fontSize: '0.72em', opacity: 0.55, border: '1px solid rgba(255,255,255,0.2)',
                             borderRadius: 8, padding: '0 6px', flex: '0 0 auto' }}>{b.type}</span>
              <span style={{ marginLeft: 'auto', flex: '0 0 auto', fontSize: '0.72em', opacity: 0.5 }}>
                {b.interaction_count}× {b.last_interaction ? '· ' + sinceOf(b.last_interaction) : ''}
              </span>
              <span style={{ flex: '0 0 auto', opacity: 0.5, fontSize: '0.8em' }}>{expanded ? '▾' : '▸'}</span>
            </div>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: '0.76em', opacity: 0.8, marginTop: 2 }}>
              <span title={t('my sentiment toward them')}>→ <SignedNum v={b.sentiment_self_to_other} /></span>
              <span title={t('their sentiment toward me')}>← <SignedNum v={b.sentiment_other_to_self} /></span>
              {b.romantic_tension > 0 && (
                <span title={t('romantic tension')} style={{ color: '#d77bae' }}>
                  ♥ {b.romantic_tension.toFixed(2)}
                </span>
              )}
              <span title={t('bond strength')} style={{ opacity: 0.7 }}>⚡ {b.strength}</span>
              {b.memories_count > 0 && onOpenMemories && (
                <button onClick={(ev) => { ev.stopPropagation(); onOpenMemories(b.partner) }}
                  style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer',
                           color: 'var(--accent, #6aa9ff)', fontSize: '1em' }}>
                  {t('{n} memories').replace('{n}', String(b.memories_count))} →
                </button>
              )}
            </div>
            {expanded && b.history_recent.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 5,
                            paddingTop: 4, borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                {b.history_recent.map((ev, i) => (
                  <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'baseline', fontSize: '0.78em' }}>
                    <span style={{ flex: '0 0 auto', opacity: 0.45, fontVariantNumeric: 'tabular-nums' }}>
                      {sinceOf(ev.timestamp)}
                    </span>
                    <span style={{ flex: 1, minWidth: 0, opacity: 0.85, lineHeight: 1.3 }}>{ev.summary || ev.type}</span>
                    {typeof ev.sentiment_delta === 'number' && ev.sentiment_delta !== 0 && (
                      <span style={{ flex: '0 0 auto' }}><SignedNum v={ev.sentiment_delta} /></span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sektion „Verlauf“ — daily/weekly/monthly-Summaries, Gesamt, Evolution-Diffs
// ---------------------------------------------------------------------------
function HistoryView({ avatar }: { avatar: string }) {
  const { t } = useI18n()
  const enc = encodeURIComponent(avatar)
  const LIMIT = 30
  const [kind, setKind] = useState<HistoryKind>('daily')
  const [resp, setResp] = useState<any>(null)
  const [items, setItems] = useState<any[]>([])
  const [offset, setOffset] = useState(0)

  const load = async (newOffset: number, append: boolean) => {
    const params = new URLSearchParams({ kind, limit: String(LIMIT), offset: String(newOffset) })
    try {
      const d = await apiGet<any>(`/characters/${enc}/memory/history?${params.toString()}`)
      setResp(d)
      setItems((prev) => append ? [...prev, ...(d.items || [])] : (d.items || []))
      setOffset(newOffset)
    } catch { /* offline/auth */ }
  }
  useEffect(() => { setResp(null); load(0, false) }, [enc, kind]) // eslint-disable-line react-hooks/exhaustive-deps

  const kinds: Array<{ id: HistoryKind; label: string }> = [
    { id: 'daily', label: t('Daily') },
    { id: 'weekly', label: t('Weekly') },
    { id: 'monthly', label: t('Monthly') },
    { id: 'history', label: t('Overall') },
    { id: 'evolution', label: t('Evolution') },
  ]
  const total: number = resp?.total ?? 0
  const paged = kind === 'daily'   // nur daily ist serverseitig paginiert

  const evoDiffRows = (label: string, d?: { removed: string[]; added: string[] }) => {
    if (!d || (d.added.length === 0 && d.removed.length === 0)) return null
    return (
      <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <div style={{ fontSize: '0.72em', opacity: 0.5, textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
        {d.added.map((line, i) => (
          <div key={`a${i}`} style={{ color: '#3fa45a', fontSize: '0.82em', lineHeight: 1.3 }}>+ {line}</div>
        ))}
        {d.removed.map((line, i) => (
          <div key={`r${i}`} style={{ color: '#e05656', fontSize: '0.82em', lineHeight: 1.3,
                                      textDecoration: 'line-through', opacity: 0.75 }}>− {line}</div>
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', flex: '0 0 auto' }}>
        {kinds.map((k) => (
          <button key={k.id} className={'player-chip' + (kind === k.id ? ' on' : '')}
                  style={{ ...chipBtnStyle, ...(kind === k.id ? {
                    borderColor: 'var(--accent, #6aa9ff)', background: 'rgba(120,170,255,0.18)',
                  } : {}) }}
                  onClick={() => setKind(k.id)}>
            {k.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {resp === null ? (
          <EmptyState small icon="journal" title={t('Loading…')} />
        ) : kind === 'history' ? (
          (resp.content || '').trim()
            ? <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>{resp.content}</div>
            : <EmptyState small icon="journal" title={t('No summary yet')} />
        ) : items.length === 0 ? (
          <EmptyState small icon="journal" title={t('No entries')} />
        ) : kind === 'evolution' ? (
          (items as EvolutionItem[]).map((s, i) => (
            <div key={i} style={{ padding: '5px 7px', borderRadius: 6, background: 'rgba(255,255,255,0.04)',
                                  display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                <span style={{ fontSize: '0.74em', opacity: 0.5, fontVariantNumeric: 'tabular-nums' }}>{sinceOf(s.ts)}</span>
                {s.trigger ? <span style={{ fontSize: '0.78em', opacity: 0.7 }}>{s.trigger}</span> : null}
              </div>
              {s.diff ? (
                [evoDiffRows(t('Beliefs'), s.diff.beliefs),
                 evoDiffRows(t('Lessons'), s.diff.lessons),
                 evoDiffRows(t('Goals'), s.diff.goals)].filter(Boolean).length > 0
                  ? <>
                      {evoDiffRows(t('Beliefs'), s.diff.beliefs)}
                      {evoDiffRows(t('Lessons'), s.diff.lessons)}
                      {evoDiffRows(t('Goals'), s.diff.goals)}
                    </>
                  : <div style={{ fontSize: '0.78em', opacity: 0.5 }}>{t('no changes')}</div>
              ) : (
                <div style={{ fontSize: '0.82em', opacity: 0.8, lineHeight: 1.35 }}>
                  {[s.beliefs, s.lessons, s.goals].filter(Boolean).join(' · ')}
                </div>
              )}
            </div>
          ))
        ) : (
          <>
            {items.map((it: HistoryDailyItem & HistoryPeriodItem, i: number) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2,
                                    padding: '4px 6px', borderRadius: 6, background: 'rgba(255,255,255,0.04)' }}>
                <div style={{ display: 'flex', gap: 8, fontSize: '0.74em', opacity: 0.55 }}>
                  <span style={{ fontVariantNumeric: 'tabular-nums' }}>{it.date || it.week || it.month}</span>
                  {it.partner ? <span>· {it.partner}</span> : null}
                </div>
                <div style={{ lineHeight: 1.35 }}>{it.content}</div>
              </div>
            ))}
            {paged && items.length < total && (
              <button className="player-chip" style={{ ...chipBtnStyle, alignSelf: 'flex-start' }}
                      onClick={() => load(offset + LIMIT, true)}>
                {t('Load more')} ({items.length}/{total})
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Haupt-Panel: Navi links (schmal → nur Icons) + Sektions-Inhalt rechts
// ---------------------------------------------------------------------------
type SectionId = 'today' | 'diary' | 'memories' | 'bonds' | 'history'

export function MindPanel({ avatar }: { avatar: string }) {
  const { t } = useI18n()
  const [section, setSection] = useState<SectionId>('today')
  const [narrow, setNarrow] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  // Schmal-Erkennung: unter 340px Panel-Breite kollabiert die Navi auf Icons.
  useEffect(() => {
    const el = rootRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((ents) => {
      const w = ents[0]?.contentRect?.width || 0
      setNarrow(w > 0 && w < 340)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Vorbelegter Bezugsperson-Filter beim Sprung Beziehungen → Erinnerungen.
  const [memRelated, setMemRelated] = useState('')
  const openMemories = (partner = '') => { setMemRelated(partner); setSection('memories') }

  const sections = useMemo(() => ([
    { id: 'today' as SectionId, icon: '☀️', label: t('Today') },
    { id: 'diary' as SectionId, icon: '📔', label: t('Diary') },
    { id: 'memories' as SectionId, icon: '🧠', label: t('Memories') },
    { id: 'bonds' as SectionId, icon: '🤝', label: t('Bonds') },
    { id: 'history' as SectionId, icon: '🕰️', label: t('History') },
  ]), [t])

  if (!avatar) {
    return <EmptyState icon="journal" title={t('No active avatar')} />
  }

  return (
    <div ref={rootRef} style={{ display: 'flex', gap: 10, height: '100%', minHeight: 0, fontSize: '0.88em' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: '0 0 auto',
                    borderRight: '1px solid rgba(255,255,255,0.1)', paddingRight: narrow ? 6 : 8 }}>
        {sections.map((sec) => {
          const active = section === sec.id
          return (
            <button key={sec.id} title={sec.label}
              onClick={() => (sec.id === 'memories' ? openMemories('') : setSection(sec.id))}
              style={{
                display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer',
                padding: narrow ? '4px 6px' : '4px 9px', borderRadius: 7, textAlign: 'left',
                border: '1px solid ' + (active ? 'var(--accent,#6aa9ff)' : 'transparent'),
                background: active ? 'rgba(120,170,255,0.18)' : 'transparent',
                color: 'inherit', fontSize: '0.92em', opacity: active ? 1 : 0.65,
              }}>
              <span>{sec.icon}</span>
              {!narrow && <span>{sec.label}</span>}
            </button>
          )
        })}
      </div>
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: section === 'today' ? 'auto' : 'hidden' }}>
        {section === 'today' && <TodayView avatar={avatar} onOpenMemories={() => openMemories('')} />}
        {section === 'diary' && <DiaryView avatar={avatar} />}
        {section === 'memories' && <MemoriesView avatar={avatar} initialRelated={memRelated} />}
        {section === 'bonds' && <BondsView avatar={avatar} onOpenMemories={openMemories} />}
        {section === 'history' && <HistoryView avatar={avatar} />}
      </div>
    </div>
  )
}
