import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MindPanel } from '../../player/MindPanel'
import { DecencyExemptToggle } from '../../components/DecencyExemptToggle'

/**
 * Mind tab — debug any (non-avatar) character's inner state in the Game-Admin.
 * Left: a "behaviour" debug block (why is the character feeling/acting like this)
 * from GET /characters/{name}/debug-activity. Right: the full player MindPanel
 * (Today · Diary · Memories · Relationships · History) reused for the picked
 * character — its data endpoints are already per-character.
 */

interface DebugActivity {
  character: string
  current_feeling: string
  state_flags: Record<string, boolean>
  status_effects: Record<string, number>
  last_thought_at: string
  last_warning?: { type: string; value: string; ts: string } | null
  reasons: string[]
  mood_recent: { timestamp?: string; mood?: string; source?: string }[]
  state_recent: { ts: string; type: string; value: string }[]
  thoughts_recent: { ts: string; action: string }[]
  block_rules: {
    id: string; name: string; action: string; message: string
    condition?: string; condition_met?: boolean; blocking?: boolean
  }[]
  force_rule?: { rule_name?: string; rule_id?: string; go_to?: string } | null
}

// ISO → kurze lokale Zeit (HH:MM, Datum nur wenn nicht heute). Defensiv.
function fmtTs(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return sameDay ? time : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`
}

export function MindTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [characters, setCharacters] = useState<string[]>([])
  const [selected, setSelected] = useState('')
  const [dbg, setDbg] = useState<DebugActivity | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    apiGet<{ characters?: string[] }>('/characters/list')
      .then((d) => setCharacters(d.characters || []))
      .catch((e) => toast(t('Failed to load') + ': ' + (e as Error).message, 'error'))
  }, [t, toast])

  const loadDebug = useCallback(async (name: string) => {
    if (!name) { setDbg(null); return }
    setLoading(true)
    try {
      setDbg(await apiGet<DebugActivity>(`/characters/${encodeURIComponent(name)}/debug-activity`))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setDbg(null)
    } finally {
      setLoading(false)
    }
  }, [t, toast])

  useEffect(() => { loadDebug(selected) }, [selected, loadDebug])

  return (
    <div className="ga-mind-layout">
      <div className="ga-mind-bar">
        <select className="ga-input" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— {t('select a character')} —</option>
          {characters.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        {selected ? (
          <button className="ga-btn ga-btn-sm" disabled={loading} onClick={() => loadDebug(selected)}>
            {t('Refresh')}
          </button>
        ) : null}
        {dbg?.last_thought_at ? (
          <span style={{ opacity: 0.6, fontSize: 12 }}>
            {t('Last thought')}: {fmtTs(dbg.last_thought_at)}
          </span>
        ) : null}
      </div>

      {!selected ? (
        <div className="ga-placeholder">{t('Select a character to inspect its mind and behaviour.')}</div>
      ) : (
        <div className="ga-mind-body">
          <div className="ga-mind-debug">
            {/* Why — aggregierte Begründung */}
            <div className="ga-mind-card">
              <h4>{t('Why this behaviour?')}</h4>
              {dbg && dbg.reasons.length > 0 ? (
                <div className="ga-mind-reason">
                  {dbg.reasons.map((r, i) => {
                    const cls = /^(must leave|blocked)/i.test(r) ? 'tag warn'
                      : /^forced/i.test(r) ? 'tag force' : 'tag'
                    return <span key={i} className={cls}>{r}</span>
                  })}
                </div>
              ) : (
                <div className="ga-mind-empty">{loading ? t('Loading…') : t('Nothing notable.')}</div>
              )}
            </div>

            {/* State flags */}
            {selected ? (
              <div className="ga-mind-card">
                <h4>{t('State flags')}</h4>
                {dbg && Object.values(dbg.state_flags || {}).some(Boolean) ? (
                  <div className="ga-mind-reason" style={{ marginBottom: 8 }}>
                    {Object.entries(dbg.state_flags).filter(([, v]) => v)
                      .map(([k]) => <span key={k} className="tag">{k}</span>)}
                  </div>
                ) : null}
                <DecencyExemptToggle character={selected} />
              </div>
            ) : null}

            {/* Active rules */}
            {dbg && (dbg.block_rules.length > 0 || dbg.force_rule) ? (
              <div className="ga-mind-card">
                <h4>{t('Active rules')}</h4>
                <ul className="ga-mind-list">
                  {dbg.force_rule ? (
                    <li style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 6 }}>
                      <span className="tag force">{t('force')}</span>
                      <span style={{ fontWeight: 500 }}>{dbg.force_rule.rule_name || dbg.force_rule.rule_id}</span>
                      {dbg.force_rule.go_to ? <span style={{ opacity: 0.6 }}>→ {dbg.force_rule.go_to}</span> : null}
                    </li>
                  ) : null}
                  {dbg.block_rules.map((b) => {
                    // Block-Semantik: Condition erfüllt → Regel greift jetzt.
                    // enter: greift = kein Zutritt · leave: greift = eingesperrt.
                    const isLeave = b.action === 'leave'
                    const active = b.blocking ?? b.condition_met ?? false
                    const status = isLeave
                      ? (active ? t('confined now') : t('free to leave'))
                      : (active ? t('no access') : t('access'))
                    return (
                      <li key={b.id} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 6 }}>
                        <span className={isLeave ? 'tag warn' : 'tag'}>{b.action || 'block'}</span>
                        <span style={{ fontWeight: 500 }}>{b.name || b.id}</span>
                        <span className={active ? 'tag warn' : 'tag ok'} title={b.condition || undefined}>{status}</span>
                        {b.message ? <span style={{ flexBasis: '100%', opacity: 0.6 }}>{b.message}</span> : null}
                      </li>
                    )
                  })}
                </ul>
              </div>
            ) : null}

            {/* Recent thoughts */}
            <div className="ga-mind-card">
              <h4>{t('Recent thought turns')}</h4>
              {dbg && dbg.thoughts_recent.length > 0 ? (
                <ul className="ga-mind-list">
                  {dbg.thoughts_recent.map((th, i) => (
                    <li key={i}><span className="ts">{fmtTs(th.ts)}</span>{th.action}</li>
                  ))}
                </ul>
              ) : (
                <div className="ga-mind-empty">{t('No recent thought turns recorded (resets on restart).')}</div>
              )}
            </div>

            {/* Mood history */}
            <div className="ga-mind-card">
              <h4>{t('Mood history')}</h4>
              {dbg && dbg.mood_recent.length > 0 ? (
                <ul className="ga-mind-list">
                  {dbg.mood_recent.map((m, i) => (
                    <li key={i}>
                      <span className="ts">{fmtTs(m.timestamp)}</span>
                      {m.mood}{m.source ? <span style={{ opacity: 0.55 }}> · {m.source}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="ga-mind-empty">{t('No mood history.')}</div>
              )}
            </div>

            {/* State changes */}
            <div className="ga-mind-card">
              <h4>{t('Recent state changes')}</h4>
              {dbg && dbg.state_recent.length > 0 ? (
                <ul className="ga-mind-list">
                  {dbg.state_recent.map((s, i) => (
                    <li key={i}>
                      <span className="ts">{fmtTs(s.ts)}</span>
                      <span style={{ opacity: 0.6 }}>{s.type}: </span>{s.value}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="ga-mind-empty">{t('No state changes.')}</div>
              )}
            </div>
          </div>

          <div className="ga-mind-panel-wrap">
            <MindPanel character={selected} alwaysLabels />
          </div>
        </div>
      )}
    </div>
  )
}
