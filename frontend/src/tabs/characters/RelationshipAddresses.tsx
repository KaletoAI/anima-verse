import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { loadCharacters } from '../../lib/refs'

/**
 * Form of address per pair (Characters → Relationships).
 *
 * Pair data, not template fields — hence a dedicated panel instead of a
 * generic template section. One row per known pair with both directions as
 * free text; the speaking character's chat prompt carries its own direction,
 * which is what stops a world from drifting between a formal and an informal
 * address mid-conversation.
 *   GET /characters/{c}/relationships/addresses
 *   PUT /characters/{c}/relationships/{other}/address  ({outgoing?, incoming?})
 * Both are admin-only: this is world authoring.
 */

const MAX_LEN = 120

interface AddressItem {
  other: string
  outgoing: string
  incoming: string
  type: string
  strength: number
}

type RowState = { outgoing: string; incoming: string }

export function RelationshipAddresses({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)

  const [items, setItems] = useState<AddressItem[]>([])
  const [draft, setDraft] = useState<Record<string, RowState>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string>('')
  const [names, setNames] = useState<string[]>([])
  const [picked, setPicked] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await apiGet<{ items?: AddressItem[] }>(`/characters/${enc}/relationships/addresses`)
      const list = d.items || []
      setItems(list)
      const next: Record<string, RowState> = {}
      for (const it of list) next[it.other] = { outgoing: it.outgoing, incoming: it.incoming }
      setDraft(next)
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [enc, t, toast])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    loadCharacters()
      .then((cs) => setNames(cs.map((c) => c.name).filter(Boolean)))
      .catch(() => setNames([]))
  }, [])

  const known = useMemo(() => new Set(items.map((i) => i.other)), [items])
  const addable = useMemo(
    () => names.filter((n) => n !== character && !known.has(n)).sort((a, b) => a.localeCompare(b)),
    [names, character, known],
  )

  const save = async (other: string) => {
    const row = draft[other]
    if (!row) return
    setBusy(other)
    try {
      await apiPut(`/characters/${enc}/relationships/${encodeURIComponent(other)}/address`, {
        outgoing: row.outgoing,
        incoming: row.incoming,
      })
      setItems((prev) => prev.map((i) => (i.other === other ? { ...i, ...row } : i)))
      toast(t('Saved'), 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  const addPair = async () => {
    if (!picked) return
    setBusy(picked)
    try {
      await apiPut(`/characters/${enc}/relationships/${encodeURIComponent(picked)}/address`, {
        outgoing: '',
        incoming: '',
      })
      setPicked('')
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  const dirty = (it: AddressItem) => {
    const row = draft[it.other]
    return !!row && (row.outgoing !== it.outgoing || row.incoming !== it.incoming)
  }

  const setField = (other: string, key: keyof RowState, value: string) => {
    setDraft((prev) => ({ ...prev, [other]: { ...(prev[other] || { outgoing: '', incoming: '' }), [key]: value } }))
  }

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div>
      <div style={{ fontSize: '0.8em', opacity: 0.55, marginBottom: 10 }}>
        {t('Free text per direction: how one addresses the other. The speaking character gets its own direction in the chat prompt, so the form of address stays the same from turn to turn. Example: “formal, calls her Harbour Mistress” / “informal, nickname Pip”.')}
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <select
          className="ga-input"
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          aria-label={t('Add pair…')}
        >
          <option value="">{t('Add pair…')}</option>
          {addable.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
        <button className="ga-btn ga-btn-sm" disabled={!picked || busy !== ''} onClick={addPair}>
          {t('Add')}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="ga-placeholder">{t('No pairs yet — add one above.')}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map((it) => {
            const row = draft[it.other] || { outgoing: '', incoming: '' }
            return (
              <div
                key={it.other}
                style={{
                  border: '1px solid var(--border, #30363d)', borderRadius: 8,
                  padding: 10, background: 'var(--bg, #0d1117)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <strong>{it.other}</strong>
                  <span style={{ fontSize: '0.8em', opacity: 0.6 }}>
                    {t(it.type)} · {t('closeness')} {Math.round(it.strength)}
                  </span>
                  <button
                    className="ga-btn ga-btn-sm ga-btn-primary"
                    style={{ marginLeft: 'auto' }}
                    disabled={!dirty(it) || busy === it.other}
                    onClick={() => save(it.other)}
                  >
                    {busy === it.other ? t('Saving…') : t('Save')}
                  </button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.82em' }}>
                    <span style={{ opacity: 0.7 }}>
                      {t('How {a} addresses {b}').replace('{a}', character).replace('{b}', it.other)}
                    </span>
                    <input
                      className="ga-input"
                      maxLength={MAX_LEN}
                      value={row.outgoing}
                      onChange={(e) => setField(it.other, 'outgoing', e.target.value)}
                      onBlur={() => { if (dirty(it)) save(it.other) }}
                    />
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.82em' }}>
                    <span style={{ opacity: 0.7 }}>
                      {t('How {a} addresses {b}').replace('{a}', it.other).replace('{b}', character)}
                    </span>
                    <input
                      className="ga-input"
                      maxLength={MAX_LEN}
                      value={row.incoming}
                      onChange={(e) => setField(it.other, 'incoming', e.target.value)}
                      onBlur={() => { if (dirty(it)) save(it.other) }}
                    />
                  </label>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
