/**
 * SurfaceBlendEditor — a composition (AV3D-13 v2) instead of a texture: a
 * zone gradient toward a neighbour kind ("coast" = water → sand → whatever
 * the other neighbours are). Deterministic data, no generation involved.
 */
import { DetailToolbar } from '../../components/DetailToolbar'
import { useI18n } from '../../i18n/I18nProvider'
import { KIND_DATALIST_ID, KNOWN_KINDS } from './surfaceTypes'
import type { Blend } from './surfaceTypes'

interface SurfaceBlendEditorProps {
  value: { kind: string; blend: Blend }
  onChange: (value: { kind: string; blend: Blend }) => void
  onSave: () => void
  onCancel: () => void
  /** Absent for a composition that was never saved. */
  onDelete?: () => void
  armedDelete: boolean
}

export function SurfaceBlendEditor({
  value, onChange, onSave, onCancel, onDelete, armedDelete,
}: SurfaceBlendEditorProps) {
  const { t } = useI18n()
  const { kind, blend } = value
  const setBlend = (patch: Partial<Blend>) => onChange({ kind, blend: { ...blend, ...patch } })

  return (
    <>
      <DetailToolbar
        title={kind || t('New composition')}
        onSave={onSave}
        onCancel={onCancel}
        onDelete={onDelete}
        deleteLabel={armedDelete ? t('Really delete?') : t('Delete')}
      />
      <div className="ga-form">
        <span className="ga-hint">
          {t('A composition is a zone gradient toward a neighbor kind instead of a texture — e.g. coast: water → sand → whatever the other neighbors are. The tiles involved need their terrain set (sea: water, coast: coast). A composition wins over textures of the same kind.')}
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            className="ga-input"
            style={{ width: 120 }}
            placeholder={t('kind (coast, …)')}
            value={kind}
            onChange={(e) => onChange({ kind: e.target.value, blend })}
          />
          <span className="ga-hint">{t('toward')}</span>
          <input
            className="ga-input"
            list={KIND_DATALIST_ID}
            style={{ width: 110 }}
            value={blend.toward}
            title={t('The neighbor kind the gradient runs to (from the map grid).')}
            onChange={(e) => setBlend({ toward: e.target.value })}
          />
          <span className="ga-hint">{t('noise')}</span>
          <input
            className="ga-input"
            type="number"
            min={0}
            max={0.5}
            step={0.01}
            style={{ width: 64 }}
            value={blend.noise ?? ''}
            placeholder="0.06"
            title={t('Border fraying (0..0.5).')}
            onChange={(e) => {
              const n = parseFloat(e.target.value)
              setBlend({ noise: Number.isFinite(n) ? n : undefined })
            }}
          />
        </div>
        {blend.zones.map((z, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="ga-hint" style={{ width: 52 }}>{t('Zone')} {i + 1}</span>
            <input
              className="ga-input"
              list="surface-zone-options"
              style={{ width: 120 }}
              value={z.kind}
              title={t('A library kind — or "neighbor" for the dominant non-toward neighbor kind.')}
              onChange={(e) => setBlend({
                zones: blend.zones.map((zz, j) => (j === i ? { ...zz, kind: e.target.value } : zz)),
              })}
            />
            <input
              className="ga-input"
              type="number"
              min={0.01}
              max={1}
              step={0.01}
              style={{ width: 72 }}
              value={z.until ?? ''}
              placeholder={i === blend.zones.length - 1 ? t('rest') : '0.5'}
              title={t('Share of the transition path (0..1, ascending) — the last zone may stay empty (= rest).')}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                setBlend({
                  zones: blend.zones.map((zz, j) =>
                    (j === i ? { ...zz, until: Number.isFinite(n) ? n : undefined } : zz)),
                })
              }}
            />
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={blend.zones.length <= 1}
              onClick={() => setBlend({ zones: blend.zones.filter((_, j) => j !== i) })}
            >
              ✕
            </button>
          </div>
        ))}
        <div>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={blend.zones.length >= 8}
            onClick={() => setBlend({ zones: [...blend.zones, { kind: 'neighbor' }] })}
          >
            + {t('Zone')}
          </button>
        </div>
        <datalist id="surface-zone-options">
          {['neighbor', ...KNOWN_KINDS].map((k) => <option key={k} value={k} />)}
        </datalist>
      </div>
    </>
  )
}
