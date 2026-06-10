/**
 * JournalPanel — Gedächtnis + Tagebuch des Avatars (Tier 2, read-only).
 * Quelle: GET /play/journal. Zwei Reiter: Memory (Erinnerungen) · Diary (Tagebuch).
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'
import { EmptyState } from './EmptyState'

interface Mem { content: string; type: string; importance: number; with: string; ts: string; tags: string[] }
interface DiaryEntry { type: string; content: string; ts: string }
interface Journal { avatar: string; memories: Mem[]; diary: DiaryEntry[] }

function clockOf(ts: string): string {
  const d = new Date(ts)
  return isNaN(d.getTime()) ? '' : d.toLocaleString()
}

export function JournalPanel() {
  const { t } = useI18n()
  const [data, setData] = useState<Journal | null>(null)
  const [tab, setTab] = useState<'memory' | 'diary'>('memory')

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try { const d = await apiGet<Journal>('/play/journal'); if (alive) setData(d) } catch { /* auth handled */ }
    }
    tick()
    const id = setInterval(tick, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (!data || !data.avatar) {
    return <EmptyState icon="journal" title={t('No active avatar')} />
  }

  const chip = (active: boolean) => ({
    padding: '2px 10px', borderRadius: 11, cursor: 'pointer', fontSize: '0.8em',
    border: '1px solid ' + (active ? 'var(--accent,#6aa9ff)' : 'rgba(255,255,255,0.2)'),
    background: active ? 'rgba(120,170,255,0.25)' : 'transparent', color: 'inherit',
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%', minHeight: 0, fontSize: '0.88em' }}>
      <div style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
        <button style={chip(tab === 'memory')} onClick={() => setTab('memory')}>🧠 {t('Memory')}</button>
        <button style={chip(tab === 'diary')} onClick={() => setTab('diary')}>📔 {t('Diary')}</button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {tab === 'memory' && (data.memories.length === 0
          ? <EmptyState small icon="journal" title={t('No memories yet')} />
          : data.memories.map((m, i) => (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '4px 6px', borderRadius: 6, background: 'rgba(255,255,255,0.04)' }}>
              <div style={{ lineHeight: 1.3 }}>{m.content}</div>
              <div style={{ display: 'flex', gap: 8, fontSize: '0.72em', opacity: 0.55 }}>
                <span>{m.type}</span>
                {m.with ? <span>· {m.with}</span> : null}
                <span>· {'★'.repeat(Math.max(0, Math.min(5, m.importance)))}</span>
                <span style={{ marginLeft: 'auto' }}>{clockOf(m.ts)}</span>
              </div>
            </div>
          )))}

        {tab === 'diary' && (data.diary.length === 0
          ? <EmptyState small icon="journal" title={t('No diary entries yet')} />
          : data.diary.map((e, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '3px 6px', borderRadius: 6, background: 'rgba(255,255,255,0.04)' }}>
              <span style={{ flex: '0 0 auto', opacity: 0.55, fontSize: '0.72em', width: 64, textTransform: 'capitalize' }}>{e.type}</span>
              <span style={{ flex: 1 }}>{e.content}</span>
              <span style={{ flex: '0 0 auto', opacity: 0.45, fontSize: '0.7em' }}>{clockOf(e.ts)}</span>
            </div>
          )))}
      </div>
    </div>
  )
}
