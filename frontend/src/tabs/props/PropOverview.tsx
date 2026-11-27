import { Field } from '@anima/player-ui'
import { CATEGORY_DATALIST_ID, MOUNT_KINDS } from './propTypes'
import { draftValue, GENERAL_TARGET } from './pendingFields'
import type { PropWorkspace } from './usePropWorkspace'

export function PropOverview({ workspace }: { workspace: PropWorkspace }) {
  const { t, nameNow, queueGeneral, categoryNow, tagsNow, swayNow,
    mountSuggested, mountNow, prop, shownVariant, queueVariant, variant,
    shownHasMesh, actions, shownDims, buf } = workspace
  const mountKnown = MOUNT_KINDS.some((mount) => mount.kind === mountNow)
  const mountInDraft = 'mount' in (buf.get(GENERAL_TARGET) || {})
  const surfaceNow = draftValue<{ height_m: number } | null>(
    buf, GENERAL_TARGET, 'surface', prop.surface ?? null)
  const hasSurface = surfaceNow !== null
  const variantHeight = shownDims.height_m
  const bindings = workspace.derivedBindings[shownVariant?.uid || ''] || []
  const places = new Set(bindings.flatMap(binding => binding.marker_ids)).size
  return <div className="ga-form prop-area-content">
    <h3>{t('Overview')}</h3>
    <p className="ga-hint">{t('Save applies object fields and geometry fields together.')}</p>
    <div className="prop-overview-short-fields">
    <Field label={t('Name')}>
      <input aria-label={t('Name')} className="ga-input" value={nameNow} onChange={(event) => queueGeneral({ name: event.target.value })} />
    </Field>
    <Field label={t('Category')}>
      <input aria-label={t('Category')} className="ga-input" list={CATEGORY_DATALIST_ID} value={categoryNow}
        onChange={(event) => queueGeneral({ category: event.target.value })} />
    </Field>
    <Field label={t('Tags (comma-separated)')}
      tip={t('Tag "walkable" lets figures stand on this prop; its surface is baked from the mesh.')}>
      <input aria-label={t('Tags (comma-separated)')} className="ga-input" value={tagsNow} onChange={(event) => queueGeneral({ tags: event.target.value })} />
    </Field>
    </div>
    {shownVariant && <Field label={t('Description / generation subject of the selected variant')}>
      <textarea aria-label={t('Description / generation subject of the selected variant')} className="ga-textarea" rows={5} value={shownVariant.description || ''}
        onChange={(event) => queueVariant(variant, { description: event.target.value })} />
    </Field>}
    <section className="prop-inspector-group">
      <h3>{t('Mount & wind')}</h3>
      <div className="prop-overview-short-fields">
      <Field label={t('Mount')} hint={t(!mountNow ? 'Unclassified'
        : !mountKnown ? 'Unknown mount value — choose a mount'
          : mountSuggested ? 'LLM suggestion — confirm or change'
            : mountInDraft ? 'Confirmation in draft — not saved yet' : 'Confirmed')}>
        <select aria-label={t('Mount')} className="ga-input" value={mountNow} onChange={(event) => queueGeneral({ mount: event.target.value })}>
          <option value="">{t('— unclassified —')}</option>
          {mountNow && !mountKnown && <option value={mountNow}>{t('Unknown value')}: {mountNow}</option>}
          {MOUNT_KINDS.map((mount) => <option key={mount.kind} value={mount.kind}>{t(mount.label)}</option>)}
        </select>
      </Field>
      {mountSuggested && <button type="button" className="ga-btn ga-btn-sm"
        disabled={!mountKnown}
        onClick={() => queueGeneral({ mount: mountNow })}>{t('Confirm suggestion in draft')}</button>}
      <Field label={t('Sway factor')}
        tip={t('1 = full wind motion of the surface; 0 = fixed. Applies to the entire prop.')}>
        <input aria-label={t('Sway factor')} className="ga-input" type="number" min={0} max={1} step={0.05} value={swayNow}
          onChange={(event) => {
            const value = event.currentTarget.valueAsNumber
            if (Number.isFinite(value)) queueGeneral({ sway_factor: Math.max(0, Math.min(1, value)) })
          }} />
      </Field>
      </div>
    </section>
    <section className="prop-inspector-group">
      <h3>{t('Storage surface')}</h3>
      <label className="ga-form-row">
        <input type="checkbox" checked={hasSurface} onChange={(event) => {
          if (!event.target.checked) {
            queueGeneral({ surface: null })
          } else {
            const start = Math.round(Math.max(0.01, Math.min(10, variantHeight || 0.75)) * 1000) / 1000
            queueGeneral({ surface: { height_m: start } })
          }
        }} />
        {t('Storage surface')}
      </label>
      {surfaceNow && <div className="prop-overview-short-fields">
        <Field label={t('Surface height (m)')}
          hint={`${t('Prop height {h} m').replace('{h}', variantHeight.toFixed(2))} · ${t('A table top is about 0.75 m; a person is 1.70 m')}`}>
          <input aria-label={t('Surface height (m)')} className="ga-input" type="number" min={0.01} max={10} step={0.01}
            value={surfaceNow.height_m}
            onChange={(event) => {
              const value = event.currentTarget.valueAsNumber
              if (Number.isFinite(value) && value > 0) {
                queueGeneral({ surface: { height_m: Math.min(10, Math.round(value * 1000) / 1000) } })
              }
            }} />
        </Field>
      </div>}
    </section>
    <section className="prop-inspector-group prop-overview-status">
      <h3>{t('Model & actions')}</h3>
      <span>{t(shownHasMesh ? 'Model available for this variant' : 'This variant has no model yet')}</span>
      <span>{actions.length} {t('actions')} · {places} {t('places')}</span>
      {prop.measured?.tris ? <span className="ga-hint">
        {prop.measured.tris.toLocaleString()} {t('tris')}
        {prop.measured.uv_layers === 0 && (prop.measured.vertex_colors || 0) > 0 ? ` · ${t('no UVs, colour in the vertices')}` : ''}
      </span> : null}
      {prop.prompt && <span className="ga-hint" title={prop.prompt}>
        {t(prop.source === 'generated' ? 'Generated' : 'Source')}{prop.backend ? ` · ${prop.backend}` : ''}
      </span>}
    </section>
  </div>
}
