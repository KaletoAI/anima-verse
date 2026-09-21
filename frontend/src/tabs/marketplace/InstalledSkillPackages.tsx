import { useCallback, useEffect, useState } from 'react'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * What the marketplace has INSTALLED into `plugins/installed/` — the only
 * place a skill package can land from here, and the only place removal
 * touches. Packages that ship in the repository under `plugins/` are not in
 * this list and the backend refuses to delete them
 * (`skill_package_io.remove_skill_package` resolves the id inside
 * `plugins/installed` and nowhere else).
 *
 * Removing is a folder delete plus a skill reload: the verbs are gone at
 * once, but whatever the package registered while it was loaded — event
 * hooks, capability providers (`app/core/hooks.py` has no unregister) — lives
 * until the server restarts. The dialog says exactly that instead of
 * pretending the process is clean.
 */
interface InstalledPackage {
  id: string
  name?: string
  version?: string
  description?: string
  /** Where it lives, the only origin anything records (no catalog is stored). */
  source?: string
  /** The skill verbs the manifest declares. */
  verbs?: string[]
}

export function InstalledSkillPackages() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [packages, setPackages] = useState<InstalledPackage[] | null>(null)
  const [pendingRemove, setPendingRemove] = useState<InstalledPackage | null>(null)
  const [busy, setBusy] = useState('')

  const reload = useCallback(async () => {
    try {
      const d = await apiGet<{ packages?: InstalledPackage[] }>(
        '/api/content/skill-packages')
      setPackages(d.packages || [])
    } catch {
      setPackages([])
    }
  }, [])

  useEffect(() => { void reload() }, [reload])

  const remove = useCallback(async (pkg: InstalledPackage) => {
    setPendingRemove(null)
    setBusy(pkg.id)
    try {
      await apiPost('/api/content/skill-packages/remove', { package_id: pkg.id })
      toast(t('Removed. Its verbs are gone at once — code it registered while loaded (hooks, capability providers) goes away with the next server restart.'))
    } catch (e) {
      toast(t('Removal failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy('')
      await reload()
    }
  }, [reload, t, toast])

  // Nothing installed is the normal state of a fresh world — no empty box.
  if (packages !== null && packages.length === 0) return null

  return (
    <div style={{ marginTop: 10, borderTop: '1px solid var(--border, #30363d)', paddingTop: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
        {t('Installed skill packages')}
      </div>
      {packages === null ? (
        <div className="ga-loading">{t('Loading…')}</div>
      ) : (
        <ul className="ga-list">
          {packages.map((p) => (
            <li key={p.id} style={{ padding: '4px 2px' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <strong style={{ flex: 1, minWidth: 0, overflow: 'hidden',
                                 textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.name || p.id}
                </strong>
                <span style={{ fontSize: 11, opacity: 0.6 }}>
                  {p.version ? `v${p.version}` : ''}
                </span>
                <button
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  disabled={busy === p.id}
                  onClick={() => setPendingRemove(p)}
                >
                  {busy === p.id ? t('Removing…') : t('Remove')}
                </button>
              </div>
              <div style={{ fontSize: 11, opacity: 0.55, wordBreak: 'break-all' }}>
                {p.source || ''}
                {p.verbs && p.verbs.length > 0 ? ` · ${p.verbs.join(', ')}` : ''}
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={!!pendingRemove}
        title={t('Remove skill package')}
        message={t('“{name}” is deleted from plugins/installed/ and its skills are reloaded. Its verbs disappear at once; code it registered while loaded (hooks, capability providers) stays until the server restarts. Packages shipped with the repository are not affected.')
          .replace('{name}', pendingRemove?.name || pendingRemove?.id || '')}
        confirmLabel={t('Remove')}
        danger
        onConfirm={() => { if (pendingRemove) void remove(pendingRemove) }}
        onClose={() => setPendingRemove(null)}
      />
    </div>
  )
}
