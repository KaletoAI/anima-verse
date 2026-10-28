import { Field } from '@anima/player-ui'
import { CATEGORY_DATALIST_ID, MOUNT_KINDS } from './propTypes'
import { GENERAL_TARGET } from './pendingFields'
import type { PropWorkspace } from './usePropWorkspace'

export function PropOverview({ workspace }: { workspace: PropWorkspace }) {
  const { t, nameNow, queueGeneral, categoryNow, tagsNow, swayNow,
    mountSuggested, mountNow, prop, shownVariant, queueVariant, variant,
    shownHasMesh, actions } = workspace
  const mountKnown = MOUNT_KINDS.some((mount) => mount.kind === mountNow)
  const mountInDraft = 'mount' in (workspace.buf.get(GENERAL_TARGET) || {})
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
