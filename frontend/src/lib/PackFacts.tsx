import { useI18n } from '../i18n/I18nProvider'

/**
 * The facts a marketplace pack carries (`facts` in the catalog index, built
 * server-side by `content_io.pack_preview`) as a small key/value table.
 * Shared by the marketplace detail and the publish dialog, so a pack reads
 * the same before and after it is published.
 *
 * Labels are a STATIC map (each one a literal `t()` call, which keeps the
 * i18n orphan check honest) for the fixed keys of props, locations and items.
 * A character's facts come from its own template, so the pack carries their
 * labels (`fact_labels`) — those win. A key neither knows is not shown.
 */
export type PackFactsMap = Record<string, unknown>

function useFactLabels(): Record<string, string> {
  const { t } = useI18n()
  return {
    category: t('Category'),
    mount: t('Mount'),
    dims_m: t('Size'),
    variants: t('Variants'),
    seasons: t('Seasons'),
    tiers: t('Resolution tiers'),
    tris: t('Triangles'),
    slots: t('Slots'),
    rooms: t('Rooms'),
    storeys: t('Storeys'),
    images: t('Images'),
    props: t('Props'),
    items: t('Items'),
    has_3d: t('3D model'),
    species: t('Species'),
    gender: t('Gender'),
    age: t('Age'),
    height: t('Height'),
  }
}

function formatFact(key: string, value: unknown, yes: string, no: string, ownLabel: boolean): string {
  if (typeof value === 'boolean') return value ? yes : no
  if (key === 'dims_m' && Array.isArray(value)) {
    return value.map((v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })).join(' × ') + ' m'
  }
  // A template label already names its unit ("Height (cm)").
  if (key === 'height' && typeof value === 'number' && !ownLabel) return `${value} cm`
  if (Array.isArray(value)) return value.map(String).join(', ')
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

export function PackFacts({ facts, labels: own }: {
  facts?: PackFactsMap | null
  labels?: Record<string, string> | null
}) {
  const { t } = useI18n()
  const labels = useFactLabels()
  const labelOf = (k: string) => (own && own[k] ? t(own[k]) : labels[k])
  const rows = Object.entries(facts || {}).filter(([k]) => labelOf(k))
  if (rows.length === 0) return null
  return (
    <table style={{ fontSize: 12, borderCollapse: 'collapse', margin: '4px 0 12px' }}>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td style={{ color: '#8b949e', padding: '1px 12px 1px 0', whiteSpace: 'nowrap' }}>{labelOf(k)}</td>
            <td style={{ padding: '1px 0' }}>{formatFact(k, v, t('yes'), t('no'), Boolean(own && own[k]))}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
