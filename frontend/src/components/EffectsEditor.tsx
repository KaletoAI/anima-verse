import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { useMoods } from '../lib/moods'
import { apiGet } from '../lib/api'

/**
 * Two-column editor for activity / item effects.
 *
 * Left: textarea where each line is `key: value`. Right: clickable stats
 * (numeric `_change` keys derived from character templates) and moods.
 * Clicking a stat appends `<stat>_change: ` to the textarea on a fresh
 * line; clicking a mood appends `mood_influence: <id>`.
 *
 * The moods come from the server (`shared/config/moods.json` via
 * `useMoods`), so this editor and the character placement editor offer the
 * same list — the two hand-kept copies had already drifted apart. The chips
 * are quick-insert helpers, not validation: any key and any mood can be
 * typed straight into the textarea.
 */
// Share the in-flight request across all editor instances; retry after failures.
let statKeysRequest: Promise<string[]> | undefined
function loadStatKeys() {
  statKeysRequest ??= apiGet<{ keys: string[] }>('/world/stat-keys')
    .then(result => result.keys)
    .catch(error => { statKeysRequest = undefined; throw error })
  return statKeysRequest
}

export function EffectsEditor({
  value,
  onChange,
  rows = 4,
  placeholder,
}: {
  value: string
  onChange: (next: string) => void
  rows?: number
  placeholder?: string
}) {
  const { t } = useI18n()
  const [stats, setStats] = useState<string[]>([])
  const [statsError, setStatsError] = useState(false)
  useEffect(() => {
    let alive = true
    loadStatKeys().then(keys => { if (alive) setStats(keys) })
      .catch(() => { if (alive) setStatsError(true) })
    return () => { alive = false }
  }, [])
  const moods = useMoods()
  const taRef = useRef<HTMLTextAreaElement | null>(null)

  const appendLine = (line: string) => {
    const cur = value.replace(/\s+$/, '')
    const next = cur ? `${cur}\n${line}` : line
    onChange(next)
    // Move caret to end of the appended line so the user can immediately type.
    requestAnimationFrame(() => {
      const ta = taRef.current
      if (!ta) return
      ta.focus()
      ta.selectionStart = ta.selectionEnd = next.length
    })
  }

  const usedStats = new Set<string>()
  const usedMoods = new Set<string>()
  for (const line of value.split('\n')) {
    const m = line.match(/^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:/)
    if (!m) continue
    if (m[1].endsWith('_change')) usedStats.add(m[1].slice(0, -'_change'.length))
    else if (m[1] === 'mood_influence') {
      const v = line.split(':', 2)[1]?.trim().toLowerCase()
      if (v) usedMoods.add(v)
    }
  }

  return (
    <div className="ga-effects-editor">
      <textarea
        ref={taRef}
        className="ga-textarea ga-effects-textarea"
        rows={rows}
        value={value}
        placeholder={placeholder ?? t('Effects as key: value, one per line')}
        onChange={(e) => onChange(e.target.value)}
        style={{ fontFamily: 'monospace' }}
      />
      <div className="ga-effects-helpers">
        <div className="ga-effects-helper">
          <div className="ga-effects-helper-title">{t('Stats')}</div>
          {statsError && <div className="ga-hint" role="status">{t('Could not load stat keys.')}</div>}
          <div className="ga-effects-helper-list">
            {stats.map((s) => (
              <button
                key={s}
                type="button"
                className={`ga-effects-chip${usedStats.has(s) ? ' is-used' : ''}`}
                onClick={() => appendLine(`${s}_change: `)}
                title={t('Append "{key}_change: " line').replace('{key}', s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="ga-effects-helper">
          <div className="ga-effects-helper-title">{t('Moods')}</div>
          <div className="ga-effects-helper-list">
            {moods.map((m) => (
              <button
                key={m}
                type="button"
                className={`ga-effects-chip${usedMoods.has(m) ? ' is-used' : ''}`}
                onClick={() => appendLine(`mood_influence: ${m}`)}
                title={t('Append "mood_influence: {id}" line').replace('{id}', m)}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
