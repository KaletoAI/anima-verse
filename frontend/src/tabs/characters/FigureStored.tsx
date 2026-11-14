/**
 * FigureStored — the stored body shapes and painted bodies of a character,
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="ga-hint">
        {t('Kept for reuse: switching back to an outfit built on one of these costs nothing. Only Delete removes what no outfit needs now.')}
        {totalUnneeded ? ` ${t('Not needed now: {size}.').replace('{size}', megabytes(totalUnneeded))}` : ''}
      </div>
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
                <div>{e.kind === 'shape' ? t('Body shape') : t('Painted body')}</div>
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
          label={`${confirm.kind === 'shape' ? t('Body shape') : t('Painted body')}${confirm.built_for_name
            ? ` (${confirm.built_for_name})` : ''}`}
          onClose={() => setConfirm(null)}
          onDeleted={() => { setConfirm(null); onDeleted?.(); void load() }} />
      ) : null}
    </div>
  )
}
