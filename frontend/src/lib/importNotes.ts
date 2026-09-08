/**
 * What an importer answers and how to tell the user about it — shared by the
 * local ZIP import dialog (`ImportExport`) and the marketplace install
 * (`MarketplaceTab`). Both call the same backend importers, so both must show
 * the same things: a partly failed collection, the props a location could not
 * find, and everything the world's sanitizers dropped. The marketplace used
 * to swallow all three behind a green "Installed" toast — a location whose
 * plan had lost its area was found weeks later instead of right away.
 */

/** A collection carries one row per sub-pack; every other type reports a
 *  single `status`. */
export interface ImportResultRow {
  name?: string; type?: string; status?: string; error?: string
  /** A sub-pack's own importer dict — a nested location reports its
   *  `props_missing` and `warnings` in here, not on the collection's top
   *  level. */
  result?: { props_missing?: unknown; warnings?: unknown }
}

export interface ImportResult {
  status?: string
  results?: ImportResultRow[]
  props_missing?: unknown
  /** What the world's sanitizers refused, in plain words (no migration, so
   *  the import SAYS what fell away). */
  warnings?: unknown
}

export interface ImportOutcome {
  /** "3 installed, 1 failed" for a collection; empty for a single pack. */
  summary: string
  /** Nothing landed, or something in a collection broke, or a single pack
   *  reports `failed`. */
  wentWrong: boolean
  /** Everything that must NOT vanish with a 2-second toast, one entry per
   *  topic, ready to render in a persistent panel. */
  notes: string[]
}

const asStrings = (v: unknown) => (Array.isArray(v) ? v.map(String).filter(Boolean) : [])

export function summarizeImport(
  result: ImportResult,
  t: (s: string) => string,
): ImportOutcome {
  const rows = Array.isArray(result.results) ? result.results : []
  // A collection installs entry by entry and never aborts, so its outcome is
  // only in the rows: counting them is what keeps a run in which NOTHING
  // landed from reading as a green "Imported".
  const n = (s: string) => rows.filter((r) => r.status === s).length
  const installed = n('success')
  const existed = n('exists')
  const broken = n('failed') + n('skipped')
  const parts: string[] = []
  if (installed) parts.push(t('{n} installed').replace('{n}', String(installed)))
  if (existed) parts.push(t('{n} already there').replace('{n}', String(existed)))
  if (broken) parts.push(t('{n} failed').replace('{n}', String(broken)))
  const summary = rows.length > 0 ? parts.join(', ') : ''
  const wentWrong = rows.length > 0 ? installed === 0 || broken > 0 : result.status === 'failed'

  const notes: string[] = []
  if (wentWrong && summary) {
    const why = rows
      .filter((r) => r.status !== 'success')
      .map((r) => `${r.name || r.type || '?'}: ${r.error || r.status}`)
    notes.push(t('Import result:') + ' ' + summary
      + (why.length > 0 ? ' — ' + why.join('; ') : ''))
  }
  // A location import lists every prop its placements name that is neither
  // bundled nor already known here — those placements render as "missing".
  // In a collection the location sits one level down, so its list is in
  // `results[i].result.props_missing` — the union of both levels is shown,
  // ids deduped.
  const missingIds = [...new Set([
    ...asStrings(result.props_missing),
    ...rows.flatMap((r) => asStrings(r.result?.props_missing)),
  ])]
  if (missingIds.length > 0) {
    notes.push(t('Missing props (placements will render as missing):')
      + ' ' + missingIds.join(', '))
  }
  // The importer runs an archive through the world's own sanitizers and does
  // NOT migrate what they refuse — a pre-v6 pack arrives without its letter
  // edges and without layouts that carry no metric rectangle. Each drop is
  // one line, and it stays on screen: a silently emptied room is found weeks
  // later, this is found now.
  const dropped = [...new Set([
    ...asStrings(result.warnings),
    ...rows.flatMap((r) => asStrings(r.result?.warnings)),
  ])]
  if (dropped.length > 0) {
    notes.push(t('Dropped on import (no migration — rebuild these):')
      + '\n· ' + dropped.join('\n· '))
  }
  return { summary, wentWrong, notes }
}
