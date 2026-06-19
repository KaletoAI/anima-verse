/**
 * PhonePanel — 1:1 Messaging (Säule B, medium="messaging").
 *
 * Async-Modell: Senden legt eine chat_messages-Zeile (= Inbox des Charakters)
 * an und bumpt ihn. Der Charakter antwortet in EIGENER Zeit über den Agent-Loop
 * und DARF ignorieren. Dieses Panel pollt Verlauf + Status (kein Fake-"tippt").
 *
 * Master-Detail: Kontaktliste → Thread (mit Zurück) — phone-artig, funktioniert
 * auch in schmalen Panels.
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

interface Conversation {
  partner: string; avatar_url: string; last: string; last_ts: string
  mine_last: boolean; unread: number; status: string; location: string
}
interface ThreadMsg { mine: boolean; content: string; ts: string }
interface MessagesResp { avatar?: string; conversations?: Conversation[]; available?: string[] }

function fmtTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString([], { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
}

export function PhonePanel() {
  const { t } = useI18n()
  const [convs, setConvs] = useState<Conversation[]>([])
  const [available, setAvailable] = useState<string[]>([])
  const [loaded, setLoaded] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [thread, setThread] = useState<ThreadMsg[]>([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [picking, setPicking] = useState(false)
  const alive = useRef(true)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const selRef = useRef<string | null>(null)
  selRef.current = selected

  const loadConvs = useCallback(async () => {
    try {
      const d = await apiGet<MessagesResp>('/play/messages')
      if (!alive.current) return
      setConvs(d.conversations || [])
      setAvailable(d.available || [])
      setLoaded(true)
    } catch { /* api layer handles auth */ }
  }, [])

  const loadThread = useCallback(async (partner: string) => {
    try {
      const d = await apiGet<{ messages?: ThreadMsg[] }>(
        '/play/messages/thread?partner=' + encodeURIComponent(partner))
      if (alive.current && selRef.current === partner) setThread(d.messages || [])
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    alive.current = true
    loadConvs()
    const id = window.setInterval(() => {
      loadConvs()
      if (selRef.current) loadThread(selRef.current)
    }, 5000)
    return () => { alive.current = false; window.clearInterval(id) }
  }, [loadConvs, loadThread])

  useEffect(() => {
    if (selected) { setThread([]); loadThread(selected) }
  }, [selected, loadThread])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [thread, selected])

  const openConv = (partner: string) => { setPicking(false); setSelected(partner) }

  const markAllRead = useCallback(async () => {
    // Optimistisch lokal auf 0 setzen, dann Backend + Reload.
    setConvs((prev) => prev.map((c) => ({ ...c, unread: 0 })))
    try { await apiPost('/play/messages/read-all', {}) } catch { /* ignore */ }
    loadConvs()
  }, [loadConvs])

  const send = useCallback(async () => {
    const partner = selRef.current
    const text = draft.trim()
    if (!partner || !text || sending) return
    setSending(true)
    setThread((prev) => [...prev, { mine: true, content: text, ts: new Date().toISOString() }])
    setDraft('')
    try {
      await apiPost('/play/messages/send', { partner, content: text })
      await loadThread(partner)
      loadConvs()
    } catch { /* ignore */ }
    finally { if (alive.current) setSending(false) }
  }, [draft, sending, loadThread, loadConvs])

  // ----- Thread-Ansicht -----
  if (selected) {
    const conv = convs.find((c) => c.partner === selected)
    const statusLabel = conv?.status === 'sleeping' ? t('asleep')
      : (conv?.location || t('available'))
    return (
      <div style={WRAP}>
        <div style={HEAD}>
          <button onClick={() => setSelected(null)} style={BACK_BTN} title={t('Back')}>‹</button>
          {conv?.avatar_url
            ? <img src={conv.avatar_url} alt="" style={AVATAR} />
            : <span style={AVATAR_FB}>{selected[0]}</span>}
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{selected}</div>
            <div style={{ fontSize: 11, opacity: 0.65 }}>
              <span style={{ color: conv?.status === 'sleeping' ? '#d99' : '#9c9' }}>●</span> {statusLabel}
            </div>
          </div>
        </div>
        <div ref={scrollRef} style={THREAD_SCROLL}>
          {thread.length === 0 && <div style={EMPTY}>{t('No messages yet')}</div>}
          {thread.map((m, i) => (
            <div key={i} style={{ alignSelf: m.mine ? 'flex-end' : 'flex-start', maxWidth: '78%' }}>
              <div style={{ ...BUBBLE, ...(m.mine ? BUBBLE_MINE : BUBBLE_THEIRS) }}>{m.content}</div>
              <div style={{ fontSize: 10, opacity: 0.45, textAlign: m.mine ? 'right' : 'left', marginTop: 1 }}>{fmtTime(m.ts)}</div>
            </div>
          ))}
        </div>
        <div style={COMPOSER}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder={t('Message…')}
            rows={1}
            style={COMPOSER_INPUT} />
          <button onClick={send} disabled={sending || !draft.trim()} style={SEND_BTN}>{t('Send')}</button>
        </div>
      </div>
    )
  }

  // ----- Kontaktliste -----
  const totalUnread = convs.reduce((s, c) => s + (c.unread || 0), 0)
  return (
    <div style={WRAP}>
      <div style={{ ...HEAD, justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 600 }}>{t('Conversations')}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {totalUnread > 0 && (
            <button onClick={markAllRead} style={NEW_BTN} title={t('Mark all as read')}>
              ✓ {t('Mark all read')}
            </button>
          )}
          <button onClick={() => setPicking((v) => !v)} style={NEW_BTN}>{picking ? t('Cancel') : '+ ' + t('New')}</button>
        </div>
      </div>
      {picking && (
        <div style={{ flex: '0 0 auto', maxHeight: 160, overflow: 'auto', borderBottom: '1px solid var(--border, #30363d)' }}>
          {available.length === 0 && <div style={{ padding: 10, opacity: 0.5 }}>{t('No characters')}</div>}
          {available.map((name) => (
            <div key={name} onClick={() => openConv(name)} style={CONTACT_ROW}>{name}</div>
          ))}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {loaded && convs.length === 0 && !picking && (
          <div style={EMPTY}>{t('No conversations yet — tap + New')}</div>
        )}
        {convs.map((c) => (
          <div key={c.partner} onClick={() => openConv(c.partner)} style={CONTACT_ROW}>
            {c.avatar_url
              ? <img src={c.avatar_url} alt="" style={AVATAR} />
              : <span style={AVATAR_FB}>{c.partner[0]}</span>}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                <span style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.partner}</span>
                <span style={{ fontSize: 10, opacity: 0.5, flex: '0 0 auto' }}>{fmtTime(c.last_ts)}</span>
              </div>
              <div style={{ fontSize: 11, opacity: 0.6, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {c.mine_last ? '→ ' : ''}{c.last}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flex: '0 0 auto' }}>
              <span title={c.status === 'sleeping' ? t('asleep') : t('available')}
                style={{ color: c.status === 'sleeping' ? '#d99' : '#9c9', fontSize: 9 }}>●</span>
              {c.unread > 0 && <span style={UNREAD}>{c.unread}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const WRAP: CSSProperties = { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, fontSize: 13 }
const HEAD: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--border, #30363d)', flex: '0 0 auto' }
const THREAD_SCROLL: CSSProperties = { flex: 1, minHeight: 0, overflow: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }
const COMPOSER: CSSProperties = { display: 'flex', gap: 6, padding: 8, borderTop: '1px solid var(--border, #30363d)', flex: '0 0 auto' }
const COMPOSER_INPUT: CSSProperties = { flex: 1, resize: 'none', background: 'var(--bg-container, #161b22)', color: 'inherit', border: '1px solid var(--border, #30363d)', borderRadius: 8, padding: '6px 8px', fontFamily: 'inherit', fontSize: 13 }
const SEND_BTN: CSSProperties = { flex: '0 0 auto', background: 'var(--accent, #6aa9ff)', color: '#06121f', border: 'none', borderRadius: 8, padding: '0 12px', cursor: 'pointer', fontWeight: 600 }
const NEW_BTN: CSSProperties = { background: 'transparent', border: '1px solid var(--border, #30363d)', color: 'inherit', borderRadius: 6, padding: '2px 8px', cursor: 'pointer', fontSize: 12 }
const BACK_BTN: CSSProperties = { background: 'transparent', border: 'none', color: 'inherit', fontSize: 22, lineHeight: 1, cursor: 'pointer', padding: '0 4px' }
const CONTACT_ROW: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--border, #30363d)', cursor: 'pointer' }
const AVATAR: CSSProperties = { width: 30, height: 30, borderRadius: '50%', objectFit: 'cover', flex: '0 0 auto' }
const AVATAR_FB: CSSProperties = { width: 30, height: 30, borderRadius: '50%', background: 'var(--bg-hover, #1f2937)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: '0 0 auto', textTransform: 'uppercase' }
const BUBBLE: CSSProperties = { padding: '6px 10px', borderRadius: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }
const BUBBLE_MINE: CSSProperties = { background: 'var(--accent, #6aa9ff)', color: '#06121f' }
const BUBBLE_THEIRS: CSSProperties = { background: 'var(--bg-hover, #1f2937)', color: 'var(--text, #e6edf3)' }
const EMPTY: CSSProperties = { opacity: 0.5, padding: 14, textAlign: 'center' }
const UNREAD: CSSProperties = { background: '#e5534b', color: '#fff', borderRadius: 10, minWidth: 16, height: 16, fontSize: 10, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '0 4px' }
