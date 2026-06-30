import { useEffect, useState } from 'react'
import { useHelp } from './HelpContext'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

interface HelpItem { code?: string; text: string; copy?: boolean }
interface HelpTopic { title: string; intro?: string; items: HelpItem[] }

/** Kleiner Copy-Button: kopiert den Code-String (z.B. "{avatar}") in die Zwischenablage. */
function CopyBtn({ value }: { value: string }) {
  const { t } = useI18n()
  const [done, setDone] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(value).then(() => {
      setDone(true)
      setTimeout(() => setDone(false), 1000)
    }).catch(() => { /* ignore */ })
  }
  return (
    <button
      type="button"
      onClick={copy}
      title={t('Copy')}
      style={{
        background: 'none', border: 0, color: done ? '#3fb950' : '#8b949e',
        cursor: 'pointer', padding: '0 2px', fontSize: '0.9em', lineHeight: 1,
      }}
    >{done ? '✓' : '⧉'}</button>
  )
}

/**
 * Ausklappbares Hilfe-Panel am rechten Rand. Themen kommen vom Server
 * (/admin/help-topics → eine Quelle, kein Frontend-Duplikat). Welches Thema
 * gezeigt wird, steuert das gerade fokussierte Feld via HelpContext.
 */
export function HelpPanel() {
  const { topic, open, setOpen } = useHelp()
  const { t } = useI18n()
  const [topics, setTopics] = useState<Record<string, HelpTopic>>({})

  useEffect(() => {
    if (!open || Object.keys(topics).length) return
    apiGet<{ topics?: Record<string, HelpTopic> }>('/admin/help-topics')
      .then((d) => setTopics(d.topics || {}))
      .catch(() => { /* ignore */ })
  }, [open, topics])

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={t('Show help')}
        style={{
          position: 'fixed', right: 0, top: 140, zIndex: 60,
          background: '#1f6feb', color: '#fff', border: 0,
          borderRadius: '6px 0 0 6px', padding: '10px 7px', cursor: 'pointer',
          writingMode: 'vertical-rl', fontSize: '0.8em', letterSpacing: 1,
        }}
      >
        ? {t('Help')}
      </button>
    )
  }

  const data = topic ? topics[topic] : null
  return (
    <aside
      style={{
        position: 'fixed', right: 0, top: 100, bottom: 0, width: 320, zIndex: 60,
        background: '#0d1117', borderLeft: '1px solid #30363d',
        boxShadow: '-4px 0 16px rgba(0,0,0,0.4)', display: 'flex',
        flexDirection: 'column', color: '#c9d1d9',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', padding: '8px 10px',
        borderBottom: '1px solid #30363d', flex: '0 0 auto',
      }}>
        <strong style={{ fontSize: '0.85em' }}>{t('Help')}</strong>
        <button
          type="button"
          onClick={() => setOpen(false)}
          title={t('Collapse')}
          style={{ marginLeft: 'auto', background: 'none', border: 0, color: '#8b949e', cursor: 'pointer', fontSize: '1.1em' }}
        >×</button>
      </div>
      <div style={{ padding: '10px 12px', overflowY: 'auto', fontSize: '0.82em', lineHeight: 1.5 }}>
        {data ? (
          <>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>{data.title}</div>
            {data.intro ? <div style={{ opacity: 0.75, marginBottom: 10 }}>{data.intro}</div> : null}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {data.items.map((it, i) => (
                <li key={i}>
                  {it.code ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <code style={{ background: '#161b22', padding: '1px 5px', borderRadius: 4, color: '#79c0ff' }}>{it.code}</code>
                      {it.copy !== false ? <CopyBtn value={it.code} /> : null}
                    </span>
                  ) : null}
                  <div style={{ opacity: 0.8, marginTop: 2 }}>{it.text}</div>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div style={{ opacity: 0.6 }}>{t('Focus a field to see its available options.')}</div>
        )}
      </div>
    </aside>
  )
}
