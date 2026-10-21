import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { getAt, setAt, type Json } from './schemaValues'

/** One row of GET /admin/world-settings/packages (loader.package_inventory). */
interface PackageRow {
  id: string
  label: string
  description: string
  version: string
  category: 'skill' | 'content' | 'adult'
  /** repo = shipped here, linked = private pack (symlink), installed = marketplace. */
  source: 'repo' | 'linked' | 'installed'
  requires: string[]
  conflicts: string[]
  /** Active in the running server (activation is fixed at startup). */
  loaded: boolean
}

const PATH = 'packages.enabled'

const SECTIONS: Array<{ id: PackageRow['category']; title: string; hint: string }> = [
  { id: 'skill', title: 'Skills', hint: 'Packages that give characters verbs (tools).' },
  { id: 'content', title: 'Body & content', hint: 'Species, body slots, templates and providers without verbs of their own.' },
  { id: 'adult', title: 'Adult', hint: 'Packages that declare adult content.' },
]

/** The enabled ids in stored order; whitespace and empty entries dropped. */
function parseIds(raw: unknown): string[] {
  return String(raw ?? '').split(',').map((s) => s.trim()).filter(Boolean)
}

/**
 * Game-Admin → Setup → Packages: the world's `packages.enabled` comma list as
 * a checklist, grouped by the package's `category` (plugin.yaml; a package
 * without one is "skill" when it has verbs, else "content"). The stored value
 * stays the comma list: ticking appends, unticking removes, the order of the
 * rest is kept, and an enabled id that has no folder on disk is shown and
 * retained (the field's contract). Saved with the Setup toolbar; activation
 * changes take effect after a server restart.
 */
export function PackagesSetup({ values, onChange }: {
  values: Json
  onChange: (path: string, next: Json) => void
}) {
  const { t } = useI18n()
  const [packages, setPackages] = useState<PackageRow[]>([])
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let live = true
    apiGet<{ packages: PackageRow[] }>('/admin/world-settings/packages')
      .then((data) => { if (live) { setPackages(data.packages || []); setLoaded(true) } })
      .catch((e) => { if (live) setError(String(e)) })
    return () => { live = false }
  }, [])

  const enabled = useMemo(() => parseIds(getAt(values, PATH)), [values])
  const enabledSet = useMemo(() => new Set(enabled), [enabled])
  const known = useMemo(() => new Set(packages.map((p) => p.id)), [packages])
  const missingOnDisk = enabled.filter((id) => !known.has(id))

  const toggle = (id: string, on: boolean) => {
    const next = on ? [...enabled.filter((x) => x !== id), id] : enabled.filter((x) => x !== id)
    onChange(PATH, setAt(values, PATH, next.join(',')))
  }

  if (error) return <div role="alert">{t('Failed to load')}: {error}</div>
  if (!loaded) return <div>{t('Loading…')}</div>

  const status = (p: PackageRow, on: boolean): { text: string; tone: 'ok' | 'muted' | 'warn' } => {
    if (on && p.loaded) return { text: t('active'), tone: 'ok' }
    if (on) return { text: t('active after restart'), tone: 'warn' }
    if (p.loaded) return { text: t('off after restart'), tone: 'warn' }
    return { text: t('off'), tone: 'muted' }
  }

  const problems = (p: PackageRow, on: boolean): string[] => {
    if (!on) return []
    const out: string[] = []
    for (const r of p.requires) {
      if (!known.has(r)) out.push(t('Requires “{id}” — not installed').replace('{id}', r))
      else if (!enabledSet.has(r)) out.push(t('Requires “{id}” — not enabled').replace('{id}', r))
    }
    // `conflicts` is per character (F9), never per world: both packages may
    // be enabled side by side, so it is a note below, not a warning here.
    return out
  }

  const sourceLabel = (p: PackageRow) =>
    p.source === 'linked' ? t('private pack') : p.source === 'installed' ? t('marketplace') : ''

  return (
    <div className="ga-form">
      <p className="ga-hint">
        {t('Changes are saved with Save at the top and take effect after a server restart.')}
      </p>
      {SECTIONS.map((section) => {
        const rows = packages.filter((p) => p.category === section.id)
        if (!rows.length) return null
        const count = rows.filter((p) => enabledSet.has(p.id)).length
        return (
          <div className="ga-fieldset" key={section.id}>
            <div className="ga-fieldset-title">
              {t(section.title)} <span className="ga-sched-muted">({count} / {rows.length})</span>
            </div>
            <p className="ga-form-hint">{t(section.hint)}</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {rows.map((p) => {
                const on = enabledSet.has(p.id)
                const st = status(p, on)
                const warn = problems(p, on)
                const src = sourceLabel(p)
                return (
                  <label key={p.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
                    <input type="checkbox" checked={on} style={{ marginTop: 3 }}
                      onChange={(e) => toggle(p.id, e.target.checked)} />
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                      <span>
                        <strong>{p.label}</strong>
                        {p.label !== p.id && <span className="ga-sched-muted"> · {p.id}</span>}
                        {src && <span className="ga-sched-muted"> · {src}</span>}
                        <span className={st.tone === 'warn' ? 'ga-img-nomatch' : 'ga-sched-muted'}> · {st.text}</span>
                      </span>
                      {p.description && <span className="ga-form-hint" style={{ margin: 0 }}>{p.description}</span>}
                      {p.requires.length > 0 && (
                        <span className="ga-sched-muted">{t('Requires')}: {p.requires.join(', ')}</span>
                      )}
                      {p.conflicts.length > 0 && (
                        <span className="ga-sched-muted">
                          {t('Not on the same character as: {ids}').replace('{ids}', p.conflicts.join(', '))}
                        </span>
                      )}
                      {warn.map((w) => <span key={w} className="ga-img-nomatch">{w}</span>)}
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        )
      })}
      {missingOnDisk.length > 0 && (
        <div className="ga-fieldset">
          <div className="ga-fieldset-title">{t('Enabled but not found')}</div>
          <p className="ga-form-hint">
            {t('These ids are enabled in this world but no package folder has them. They stay in the list until you remove them.')}
          </p>
          {missingOnDisk.map((id) => (
            <label key={id} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <input type="checkbox" checked onChange={() => toggle(id, false)} />
              <span>{id}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
