/**
 * StatsPanel — the character's status values (`profile.status_effects`) as ONE
 * pick-and-set control: a select for the stat, a field for its value.
 *
 * WHICH stats exist is never decided here. The character template declares
 * them (fields with `store: "status_effects"`, contributed by packages such as
 * `plugins/rp`), and `GET /characters/{n}/status-effects` returns exactly
 * those — in template order, seeding missing ones from the template defaults,
 * with the display name per stat in `bar_meta`. No stat name lives in this
 * code, so a package that adds one gets the control for free.
 *
 * The stat fields themselves carry `editor_visible: false` and are therefore
 * skipped by the generic field renderer; the template's `traits` section
 * renders this panel instead through its `special: "stats"` slot.
 *
 * An edit queues the WHOLE map under the profile key `status_effects` — one
 * pending field, exactly as the one `/profile` request it produces — so the
 * Character tab's Save writes every value that was touched. Without a draft
 * (no `queueField`) each edit saves itself, the same way the field renderer
 * behaves outside the Character tab.
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

interface BarMeta {
  name?: string
  name_de?: string
}

export function StatsPanel({
  character,
  queueField,
  draftStatus,
  discardSignal,
  savedSignal,
}: {
  character: string
  /** Remember the whole map instead of saving it (the Character tab's draft). */
  queueField?: (scope: 'profile' | 'config', key: string, value: unknown) => void
  /** The draft's version of `status_effects`, laid over the server's values. */
  draftStatus?: Record<string, unknown>
  /** Bumped by a Discard — reloads the server values and drops what was typed. */
  discardSignal?: number
  /** Bumped by a successful Save — the draft is gone then, so the values this
   *  panel shows have to come from the server again. */
  savedSignal?: number
}) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [server, setServer] = useState<Record<string, unknown>>({})
  const [meta, setMeta] = useState<Record<string, BarMeta>>({})
  const [sel, setSel] = useState('')
  const [local, setLocal] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let alive = true
    setLoaded(false)
    apiGet<{ status_effects: Record<string, unknown>; bar_meta: Record<string, BarMeta> }>(
      `/characters/${encodeURIComponent(character)}/status-effects`,
    )
      .then((r) => {
        if (!alive) return
        setServer(r.status_effects || {})
        setMeta(r.bar_meta || {})
      })
      .catch(() => {
        if (alive) setServer({})
      })
      .finally(() => {
        if (alive) setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [character, discardSignal, savedSignal])

  // Draft over server — template order first, a draft-only key appended.
  const eff = useMemo(
    () => ({ ...server, ...(draftStatus || {}) }),
    [server, draftStatus],
  )
  const keys = useMemo(() => Object.keys(eff), [eff])

  // Keep the selection on an existing stat (first one after a load/switch).
  useEffect(() => {
    if (keys.length && !keys.includes(sel)) setSel(keys[0])
  }, [keys, sel])

  // Show the selected stat's value — on a switch, a reload and a discard, but
  // never while it is being typed (the value it would write is the same one).
  const current = sel in eff ? eff[sel] : ''
  useEffect(() => {
    setLocal(current === null || current === undefined ? '' : String(current))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, loaded, discardSignal, savedSignal])

  const label = (key: string): string => {
    const m = meta[key] || {}
    const name = lang === 'de' ? m.name_de || m.name : m.name
    return name || key
  }

  const commit = async (raw: string) => {
    if (!sel) return
    const txt = raw.trim()
    const value: unknown = txt === '' ? '' : Number(txt)
    if (txt !== '' && !Number.isFinite(value as number)) {
      setLocal(current === null || current === undefined ? '' : String(current))
      return
    }
    if (String(value) === String(current ?? '')) return
    const next = { ...eff, [sel]: value }
    if (queueField) {
      queueField('profile', 'status_effects', next)
      return
    }
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/profile`, {
        fields: { status_effects: next },
      })
      setServer(next)
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setLocal(current === null || current === undefined ? '' : String(current))
    }
  }

  if (loaded && !keys.length) {
    return <div className="ga-hint">{t('This character has no status values.')}</div>
  }

  return (
    <>
      <Field label={t('Stat')}>
        <select
          className="ga-input"
          value={sel}
          onChange={(e) => setSel(e.target.value)}
        >
          {keys.map((k) => (
            <option key={k} value={k}>
              {label(k)}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t('Value')}>
        <input
          className="ga-input"
          type="number"
          value={local}
          disabled={!sel}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={() => commit(local)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commit(local)
            }
          }}
        />
      </Field>
    </>
  )
}
