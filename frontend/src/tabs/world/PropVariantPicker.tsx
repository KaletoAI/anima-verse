/**
 * PropVariantPicker — which model variant ONE prop placement shows.
 *
 * The placement side of the model-variant feature (E2.3a). It sits in the
 * floor-plan editor's placement strip, beside the yaw and height dials,
 * because it describes the same thing they do: THIS placement, in THIS room.
 *
 * The value is a POSITION in the prop's ACTIVE, MESHED variants — exactly the
 * list the scene payload resolves a placement's `variant` against, which is
 * why only those are offered. A prop with at most one usable variant has
 * nothing to pick, so the control stays away entirely.
 *
 * Like every other dial in the strip it writes the DRAFT only; one Save
 * persists all of them together.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

interface VariantEntry {
  index: number
  active: boolean
  primary: boolean
  has_model: boolean
}

export function PropVariantPicker({ propId, variant, onVariant }: {
  propId: string
  /** Stored `variant` of the placement (undefined = the primary one). */
  variant?: number
  /** Writes the variant into the DRAFT — the strip's other dials do the same. */
  onVariant: (value: number | undefined) => void
}) {
  const { t } = useI18n()
  const [variants, setVariants] = useState<VariantEntry[]>([])

  useEffect(() => {
    let stale = false
    if (!propId) { setVariants([]); return }
    apiGet<{ variants?: VariantEntry[] }>(
      `/world/props/${encodeURIComponent(propId)}/variants`)
      .then((d) => { if (!stale) setVariants(d.variants || []) })
      .catch(() => { if (!stale) setVariants([]) })
    return () => { stale = true }
  }, [propId])

  const usable = variants.filter((v) => v.active && v.has_model)
  if (usable.length <= 1) return null

  return (
    <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
      title={t('Which of the prop’s model variants THIS placement shows. 1 is the primary one — the mesh every consumer gets by default.')}>
      {t('Variant')}
      <select
        className="ga-input"
        style={{ width: 90 }}
        value={variant ?? 0}
        onChange={(e) => {
          const v = parseInt(e.target.value, 10) || 0
          onVariant(v > 0 ? v : undefined)
        }}
      >
        {usable.map((_, pos) => (
          <option key={pos} value={pos}>
            {pos === 0 ? `★ ${t('primary')}` : `v${pos + 1}`}
          </option>
        ))}
      </select>
    </label>
  )
}
