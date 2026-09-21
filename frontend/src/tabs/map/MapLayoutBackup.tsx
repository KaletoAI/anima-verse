import { useCallback, useRef, useState } from 'react'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiUpload } from '../../lib/api'
import { downloadBlob } from '../../lib/download'
import { useToast } from '../../lib/Toast'

/**
 * Save and restore the MAP LAYOUT — `GET /world/map/export` and
 * `POST /world/map/import` (both admin-only).
 *
 * What travels is exactly one row per location: `{id, name, pos_x, pos_z,
 * yaw_deg}` in world metres (`content_io.export_map_layout_to_zip`). NOT the
 * locations themselves, and NOT terrain areas, strokes or height areas — the
 * dialog says so, because "restore the map" reads like it would take those
 * with it.
 *
 * The import matches by ID only, validates every row before the first write
 * and then goes through `update_location_position`, which takes the
 * OCCUPANTS along. Unknown ids are reported, never created.
 */
export function MapLayoutBackup({ onRestored }: { onRestored?: () => void }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [pending, setPending] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)

  const download = useCallback(async () => {
    try {
      const res = await fetch('/world/map/export', { credentials: 'same-origin' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      downloadBlob(await res.blob(), 'map_layout.zip')
      toast(t('Exported'))
    } catch (e) {
      toast(t('Export failed') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  const restore = useCallback(async (file: File) => {
    setPending(null)
    setBusy(true)
    try {
      const res = await apiUpload<{
        applied_count?: number
        skipped_unknown_count?: number
        skipped_invalid_count?: number
      }>('/world/map/import', file)
      toast(t('{n} locations placed, {u} unknown, {i} unusable rows')
        .replace('{n}', String(res.applied_count ?? 0))
        .replace('{u}', String(res.skipped_unknown_count ?? 0))
        .replace('{i}', String(res.skipped_invalid_count ?? 0)))
      onRestored?.()
    } catch (e) {
      toast(t('Restore failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [onRestored, t, toast])

  return (
    <>
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        title={t('Save where every location stands (position and rotation, in metres) as a ZIP')}
        onClick={() => { void download() }}
      >
        ↓ {t('Download layout')}
      </button>
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        disabled={busy}
        title={t('Put every location back where a saved layout says it stood')}
        onClick={() => fileRef.current?.click()}
      >
        ↑ {busy ? t('Restoring…') : t('Restore layout')}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".zip"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          if (f) setPending(f)
        }}
      />
      <ConfirmDialog
        open={!!pending}
        title={t('Restore map layout')}
        message={t('Every location this file knows is moved to the position and rotation it records — characters standing in them travel along. Terrain, strokes and height areas are NOT touched, and no location is created: entries for places this world does not have are reported and skipped.')}
        confirmLabel={t('Restore layout')}
        danger
        onConfirm={() => { if (pending) void restore(pending) }}
        onClose={() => setPending(null)}
      />
    </>
  )
}
