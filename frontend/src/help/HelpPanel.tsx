import { useEffect, useState } from 'react'
import { useHelp, type HelpItem } from './HelpContext'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'
import { SidePanelShell, CopyBtn } from './SidePanelShell'

interface HelpTopic { title: string; intro?: string; items: HelpItem[] }

/**
 * Context-sensitive help side panel. Topics come from the server
 * (/admin/help-topics → one source, no frontend duplicate). Which topic is
 * shown is driven by the currently focused field via HelpContext.
 */
export function HelpPanel() {
  const { topic, items: dynItems, insert, panel } = useHelp()
  const { t } = useI18n()
  const [topics, setTopics] = useState<Record<string, HelpTopic>>({})
  const open = panel === 'help'

  useEffect(() => {
    if (!open || Object.keys(topics).length) return
    apiGet<{ topics?: Record<string, HelpTopic> }>('/admin/help-topics')
      .then((d) => setTopics(d.topics || {}))
      .catch(() => { /* ignore */ })
  }, [open, topics])

  const data = topic ? topics[topic] : null
  return (
    <SidePanelShell id="help" title={t('Help')}>
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
      ) : null}

      {dynItems.length > 0 ? (
        <div style={{ marginTop: data ? 14 : 0 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('Insert')}</div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {dynItems.map((it, i) => (
              <li key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {it.insert && insert ? (
                  <button
                    type="button"
                    onClick={() => insert(it.insert as string)}
                    title={t('Insert at cursor')}
                    style={{ background: '#1f6feb', color: '#fff', border: 0, borderRadius: 4, cursor: 'pointer', padding: '1px 6px', fontSize: '0.85em' }}
                  >+</button>
                ) : null}
                {it.code ? (
                  <code style={{ background: '#161b22', padding: '1px 5px', borderRadius: 4, color: '#79c0ff' }}>{it.code}</code>
                ) : null}
                <span style={{ opacity: 0.7 }}>{it.text}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!data && dynItems.length === 0 ? (
        <div style={{ opacity: 0.6 }}>{t('Focus a field to see its available options.')}</div>
      ) : null}
    </SidePanelShell>
  )
}
