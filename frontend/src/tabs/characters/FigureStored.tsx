/**
 * FigureStored — the stored body shapes and texture bodies of a character,
 * collapsed under the Figure tab's "Body:" line (plan
 * 2026-11-12-unified-worn-pieces Task 10; spec "Reuse, not rebuild" and
 * Ruling 5a). Switching outfits back and forth costs nothing because these
 * stay stored; an automatic collect never deletes one merely because no
 * outfit wants it now ("stored, not needed now") — only the Delete here
 * does.
 *
 * Backend (app/routes/figure.py → app/core/figure.py): GET
 * /characters/{c}/figure/stored → `{stored: [{key, kind, bytes, built_for,
 * built_for_name, outfits, last_used, reason, unneeded, deletable, running,
 * current}]}`; DELETE …/figure/stored/{key} (409 while an outfit would be
 * built on it, the figure stands on it or a run works on it). A Delete is
 * confirmed in an in-app dialog (StoredDeleteDialog, a portal — Ruling A64:
 * the files, MB, the outfit models built on a shape and what becomes due, from
 * GET …/figure/stored/{key}/preview); a row that cannot be deleted says why
 * under it (`refusal`), a shape kept only by an outfit model built on it
 * (`history`) is deletable and says so.
 *
 * Round 2026-11-25 (Arvid's six body shapes): a shape is kept only for the worn combination and the saved outfit
 * sets (`spare`: neither — deletable), a shape with views only says "superseded, not meshed" (`meshed` false), and
 * "Delete all not needed…" opens the same dialog with every deletable not-needed entry. Nothing is deleted
 * without that confirmation.
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { StoredDeleteDialog } from './StoredDeleteDialog'
import { StepLight } from './StepRows'
import { megabytes, refusalText, storedState } from './storedDeleteModel'
import type { StoredRefusal } from './storedDeleteModel'

export interface StoredEntry {
  key: string
  kind: 'shape' | 'texture'
  bytes: number
  built_for: string
  built_for_name: string
  outfits: string[]
  last_used: string
  /** The artefact graph's verdict (server English). */
  reason: string
  /** Stored, not needed now (Ruling 5a). */
  unneeded: boolean
  deletable: boolean
  running: boolean
  /** The worn figure's shape or texture. */
  current: boolean
  /** Why it cannot be deleted ("" when it can) — Ruling A64. */
  refusal?: StoredRefusal
  /** A shape kept only because an outfit model was built on it: deletable, that model goes with it. */
  history?: boolean
  /** A shape neither worn nor of a saved outfit set, or never meshed — deletable (round 2026-11-25). */
  spare?: boolean
  /** A shape has its model; false = views only (a run superseded mid-way). */
  meshed?: boolean
}

const CELL: CSSProperties = { padding: '3px 6px', verticalAlign: 'top' }
const MUTED: CSSProperties = { opacity: 0.65 }

export function FigureStored({ character, onDeleted }: {
  character: string
  /** A Delete went through (the figure's state may name the key). */
  onDeleted?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const enc = encodeURIComponent(character)
  const [entries, setEntries] = useState<StoredEntry[] | null>(null)
  const [error, setError] = useState('')
  const [confirm, setConfirm] = useState<StoredEntry | null>(null)
  const [bulk, setBulk] = useState<StoredEntry[] | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ stored: StoredEntry[] }>(`/characters/${enc}/figure/stored`)
      setEntries(d.stored)
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [enc])
  useEffect(() => { void load() }, [load])

  if (error) return <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{error}</div>
  if (!entries) return <div className="ga-hint">{t('Loading…')}</div>
  if (!entries.length) return <div className="ga-hint">{t('Nothing stored besides the plain body.')}</div>

  // An older server without `refusal`: the old rule (running, current, else needed).
  const why = (e: StoredEntry) => refusalText(e.refusal ?? (e.running ? 'running' : e.current ? 'current' : 'needed'),
    e.reason, t)
  const totalUnneeded = entries.filter((e) => e.unneeded).reduce((sum, e) => sum + e.bytes, 0)
  const bulkEntries = entries.filter((e) => e.unneeded && e.deletable)
  const labelOf = (e: StoredEntry) => `${e.kind === 'shape' ? t('Body shape') : t('Texture body')}${e.built_for_name
    ? ` (${e.built_for_name})` : ''}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="ga-hint">
        {t('Kept for reuse: switching back to an outfit built on one of these costs nothing. Only Delete removes what no outfit needs now.')}
        {totalUnneeded ? ` ${t('Not needed now: {size}.').replace('{size}', megabytes(totalUnneeded))}` : ''}
        {' '}{t('Every combination of in-body pieces is its own body shape with its own mesh run; one is kept for the outfit worn now and for each saved outfit set.')}
      </div>
      {bulkEntries.length > 1 ? (
        <div>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => setBulk(bulkEntries)}
            title={t('Opens the confirmation with every entry not needed now — nothing is deleted before it')}>
            {t('Delete all not needed…')} ({bulkEntries.length} · {megabytes(bulkEntries.reduce((sum, e) => sum + e.bytes, 0))})
          </button>
        </div>
      ) : null}
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.92em' }}>
        <thead>
          <tr style={{ textAlign: 'left', ...MUTED }}>
            <th style={CELL}>{t('Kind')}</th>
            <th style={CELL}>{t('Built for')}</th>
            <th style={CELL}>{t('Size')}</th>
            <th style={CELL}>{t('Last used')}</th>
            <th style={CELL} />
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={`${e.kind}:${e.key}`} style={{ borderTop: '1px solid var(--border, #30363d)' }}>
              <td style={CELL}>
                <div>{e.kind === 'shape' ? t('Body shape') : t('Texture body')}</div>
                <div className="ga-hint" style={{ fontFamily: 'monospace' }}>{e.key}</div>
              </td>
              <td style={CELL}>
                <div>{e.built_for_name || (e.built_for ? e.built_for : '—')}</div>
                <div className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <StepLight light={storedState(e, t).light} />{storedState(e, t).text}
                </div>
              </td>
              <td style={CELL}>{megabytes(e.bytes)}</td>
              <td style={CELL}>{e.last_used ? formatDateTime(e.last_used, clockSettings()) : '—'}</td>
              <td style={CELL}>
                <button type="button" className="ga-btn ga-btn-sm" disabled={!e.deletable}
                  onClick={() => setConfirm(e)}>
                  {t('Delete…')}
                </button>
                {!e.deletable ? <div className="ga-hint" style={{ maxWidth: 220 }}>{why(e)}</div> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {confirm ? (
        <StoredDeleteDialog character={character} entryKey={confirm.key} kind={confirm.kind}
          label={labelOf(confirm)}
          onClose={() => setConfirm(null)}
          onDeleted={() => { setConfirm(null); onDeleted?.(); void load() }} />
      ) : null}
      {bulk && bulk.length ? (
        <StoredDeleteDialog character={character} entryKey={bulk[0].key} kind={bulk[0].kind} label={labelOf(bulk[0])}
          more={bulk.slice(1).map((e) => ({ key: e.key, label: labelOf(e) }))}
          onClose={() => setBulk(null)}
          onDeleted={() => { setBulk(null); onDeleted?.(); void load() }} />
      ) : null}
    </div>
  )
}
