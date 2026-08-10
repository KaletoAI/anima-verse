import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { downloadBlob } from '../../lib/download'
import { useToast } from '../../lib/Toast'
import {
  loadCharacters,
  loadItems,
  loadLocations,
  loadProps,
  loadRules,
} from '../../lib/refs'

/**
 * Collection builder — pack several entities of this world into ONE
 * collection ZIP (`POST /api/content/collection/export`).
 *
 * Moving a world by hand means exporting N things and importing N ZIPs; a
 * collection is that same set as a single file, and the generic import
 * dialog installs it entry by entry.
 *
 * Everything here reads from the list endpoints the other tabs already use —
 * no marketplace-only data source. Entities that the exporter refuses on
 * principle are not offered at all: shared-library items and baseline rules
 * ship with the game repo, so exporting them would only cause collisions.
 */

type EntryType = 'location' | 'character' | 'prop' | 'item' | 'rule'

interface Choice {
  id: string
  label: string
}

interface Section {
  type: EntryType
  title: string
  choices: Choice[]
}

// A NUL byte cannot occur in an id or a character name, so the key splits
// back unambiguously — a separator like ':' or ' ' would not.
const KEY_SEP = '\u0000'

const entryKey = (type: EntryType, id: string) => `${type}${KEY_SEP}${id}`

export function CollectionBuilder({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [name, setName] = useState('')
  const [sections, setSections] = useState<Section[] | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({ location: true })
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [withStates, setWithStates] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    // A list endpoint that is unavailable costs its section, not the dialog.
    Promise.all([
      loadLocations().catch(() => []),
      loadCharacters().catch(() => []),
      loadProps().catch(() => []),
      loadItems().catch(() => []),
      loadRules().catch(() => []),
    ])
      .then(([locations, characters, props, items, rules]) => {
        if (!alive) return
        setSections([
          {
            type: 'location',
            title: t('Locations'),
            choices: locations.map((l) => ({ id: l.id, label: l.name || l.id })),
          },
          {
            type: 'character',
            title: t('Characters'),
            // The character export is keyed by NAME, not by an id.
            choices: characters.map((c) => ({ id: c.name, label: c.display_name || c.name })),
          },
          {
            type: 'prop',
            title: t('Props'),
            choices: props.map((p) => ({ id: p.id, label: p.name || p.id })),
          },
          {
            type: 'item',
            title: t('Items'),
            choices: items
              .filter((i) => !i._shared)
              .map((i) => ({ id: i.id, label: i.name || i.id })),
          },
          {
            type: 'rule',
            title: t('Rules'),
            choices: rules
              .filter((r) => r.id && r._origin !== 'shared')
              .map((r) => ({ id: r.id as string, label: r.name || (r.id as string) })),
          },
        ])
      })
      .catch(() => {
        if (alive) setSections([])
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const entries = useMemo(() => {
    const out: { type: string; id: string }[] = []
    for (const [key, on] of Object.entries(picked)) {
      if (!on) continue
      const [type, id] = key.split(KEY_SEP)
      out.push({ type, id })
    }
    if (withStates) out.push({ type: 'states', id: '' })
    return out
  }, [picked, withStates])

  const countIn = (section: Section) =>
    section.choices.filter((c) => picked[entryKey(section.type, c.id)]).length

  const toggleAll = (section: Section, on: boolean) => {
    setPicked((prev) => {
      const next = { ...prev }
      for (const c of section.choices) next[entryKey(section.type, c.id)] = on
      return next
    })
  }

  const submit = async () => {
    if (!name.trim()) {
      toast(t('Name required'), 'error')
      return
    }
    if (entries.length === 0) {
      toast(t('Pick at least one entry'), 'error')
      return
    }
    setBusy(true)
    try {
      const res = await fetch('/api/content/collection/export', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), entries }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const slug = name.trim().replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^[-_.]+|[-_.]+$/g, '')
      downloadBlob(await res.blob(), `collection_${(slug || 'collection').toLowerCase()}.zip`)
      toast(t('Exported'))
      onClose()
    } catch (e) {
      toast(t('Export failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={t('Build collection')}
        style={{ maxWidth: 520, width: 'min(520px, 92vw)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{t('Build collection')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body" style={{ maxHeight: '62vh', overflowY: 'auto' }}>
          <div className="ga-hint" style={{ marginBottom: 8 }}>
            {t('Pack several entities of this world into one ZIP. Import it later through the normal import dialog — it installs every entry.')}
          </div>
          <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Collection name')}
            <input
              className="ga-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              placeholder={t('e.g. Village bundle')}
            />
          </label>

          {sections === null ? (
            <div className="ga-loading" style={{ marginTop: 10 }}>
              {t('Loading…')}
            </div>
          ) : (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {sections.map((section) => {
                const isOpen = !!open[section.type]
                const n = countIn(section)
                return (
                  <div
                    key={section.type}
                    style={{
                      border: '1px solid var(--border, #30363d)',
                      borderRadius: 6,
                      overflow: 'hidden',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => setOpen((o) => ({ ...o, [section.type]: !isOpen }))}
                      style={{
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '6px 8px',
                        background: 'transparent',
                        border: 'none',
                        color: 'inherit',
                        cursor: 'pointer',
                        fontSize: 13,
                        textAlign: 'left',
                      }}
                    >
                      <span style={{ opacity: 0.6 }}>{isOpen ? '▾' : '▸'}</span>
                      <strong style={{ flex: 1 }}>{section.title}</strong>
                      <span style={{ opacity: 0.6, fontSize: 12 }}>
                        {n > 0 ? `${n} / ${section.choices.length}` : section.choices.length}
                      </span>
                    </button>
                    {isOpen ? (
                      <div style={{ padding: '0 8px 8px' }}>
                        {section.choices.length === 0 ? (
                          <div className="ga-hint">{t('Nothing exportable here.')}</div>
                        ) : (
                          <>
                            <div style={{ display: 'flex', gap: 6, margin: '2px 0 6px' }}>
                              <button
                                type="button"
                                className="ga-btn ga-btn-sm"
                                onClick={() => toggleAll(section, true)}
                                disabled={busy}
                              >
                                {t('Select all')}
                              </button>
                              <button
                                type="button"
                                className="ga-btn ga-btn-sm"
                                onClick={() => toggleAll(section, false)}
                                disabled={busy}
                              >
                                {t('Select none')}
                              </button>
                            </div>
                            <div
                              style={{
                                display: 'flex',
                                flexDirection: 'column',
                                gap: 2,
                                maxHeight: 190,
                                overflowY: 'auto',
                              }}
                            >
                              {section.choices.map((c) => {
                                const key = entryKey(section.type, c.id)
                                return (
                                  <label
                                    key={key}
                                    style={{
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 8,
                                      fontSize: 12,
                                      cursor: 'pointer',
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={!!picked[key]}
                                      disabled={busy}
                                      onChange={(e) =>
                                        setPicked((p) => ({ ...p, [key]: e.target.checked }))
                                      }
                                    />
                                    <span
                                      style={{
                                        flex: 1,
                                        minWidth: 0,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                      }}
                                    >
                                      {c.label}
                                    </span>
                                  </label>
                                )
                              })}
                            </div>
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                )
              })}

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 13,
                  padding: '6px 8px',
                  border: '1px solid var(--border, #30363d)',
                  borderRadius: 6,
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={withStates}
                  disabled={busy}
                  onChange={(e) => setWithStates(e.target.checked)}
                />
                <span style={{ flex: 1 }}>
                  <strong>{t('World states')}</strong>{' '}
                  <span style={{ opacity: 0.6, fontSize: 12 }}>
                    — {t('the whole prompt-filter block of this world')}
                  </span>
                </span>
              </label>
            </div>
          )}
        </div>
        <div
          className="ga-modal-footer"
          style={{ display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'flex-end' }}
        >
          <span style={{ marginRight: 'auto', fontSize: 12, opacity: 0.7 }}>
            {t('{n} selected').replace('{n}', String(entries.length))}
          </span>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose} disabled={busy}>
            {t('Cancel')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-primary"
            onClick={submit}
            disabled={busy || entries.length === 0}
          >
            {busy ? t('Building…') : t('Download ZIP')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
