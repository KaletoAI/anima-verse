import { Field } from '@anima/player-ui'
import { CATEGORY_DATALIST_ID, MOUNT_KINDS } from './propTypes'
import { GENERAL_TARGET } from './pendingFields'
import type { PropWorkspace } from './usePropWorkspace'

export function PropOverview({ workspace }: { workspace: PropWorkspace }) {
  const { t, nameNow, queueGeneral, categoryNow, tagsNow, swayNow,
    mountSuggested, mountNow, prop, shownVariant, queueVariant, variant,
    shownHasMesh, actions, navigate } = workspace
  const mountKnown = MOUNT_KINDS.some((mount) => mount.kind === mountNow)
  const mountInDraft = 'mount' in (workspace.buf.get(GENERAL_TARGET) || {})
  const bindings = shownVariant?.action_bindings || []
  const repair = actions.filter((action) => action.enabled && !bindings.some((binding) =>
    binding.action_id === action.id && (!binding.supported || binding.validation !== 'repair_required')))
  return <div className="ga-form prop-area-content">
    <h3>{t('Übersicht')}</h3>
    <p className="ga-hint">{t('Objektfelder und Geometriefelder werden gemeinsam mit Speichern übernommen.')}</p>
    <Field label={t('Name')}>
      <input className="ga-input" value={nameNow} onChange={(event) => queueGeneral({ name: event.target.value })} />
    </Field>
    <Field label={t('Category')}>
      <input className="ga-input" list={CATEGORY_DATALIST_ID} value={categoryNow}
        onChange={(event) => queueGeneral({ category: event.target.value })} />
    </Field>
    <Field label={t('Tags (comma-separated)')}
      tip={t('Tag "walkable" lets figures stand on this prop; its surface is baked from the mesh.')}>
      <input className="ga-input" value={tagsNow} onChange={(event) => queueGeneral({ tags: event.target.value })} />
    </Field>
    {shownVariant && <Field label={t('Beschreibung / Generierungsbeschreibung der ausgewählten Variante')}>
      <textarea className="ga-textarea" rows={5} value={shownVariant.description || ''}
        onChange={(event) => queueVariant(variant, { description: event.target.value })} />
    </Field>}
    <section className="prop-inspector-group">
      <h3>{t('Befestigung & Wind')}</h3>
      <Field label={t('Mount')} hint={t(!mountNow ? 'Nicht klassifiziert'
        : !mountKnown ? 'Unbekannter Befestigungswert — bitte zuordnen'
          : mountSuggested ? 'LLM-Vorschlag — bestätigen oder ändern'
            : mountInDraft ? 'Bestätigung im Entwurf — noch nicht gespeichert' : 'Bestätigt')}>
        <select className="ga-input" value={mountNow} onChange={(event) => queueGeneral({ mount: event.target.value })}>
          <option value="">{t('— unclassified —')}</option>
          {mountNow && !mountKnown && <option value={mountNow}>{t('Unbekannter Wert')}: {mountNow}</option>}
          {MOUNT_KINDS.map((mount) => <option key={mount.kind} value={mount.kind}>{t(mount.label)}</option>)}
        </select>
      </Field>
      {mountSuggested && <button type="button" className="ga-btn ga-btn-sm"
        disabled={!mountKnown}
        onClick={() => queueGeneral({ mount: mountNow })}>{t('Vorschlag im Entwurf bestätigen')}</button>}
      <Field label={t('Sway factor')}
        tip={t('1 = volle Windbewegung des Untergrunds; 0 = unbeweglich. Gilt für das gesamte Prop.')}>
        <input className="ga-input" type="number" min={0} max={1} step={0.05} value={swayNow}
          onChange={(event) => {
            const value = event.currentTarget.valueAsNumber
            if (Number.isFinite(value)) queueGeneral({ sway_factor: Math.max(0, Math.min(1, value)) })
          }} />
      </Field>
    </section>
    <section className="prop-inspector-group prop-overview-status">
      <h3>{t('Modell & Handlungen')}</h3>
      <span>{t(shownHasMesh ? 'Modell für diese Variante vorhanden' : 'Diese Variante hat noch kein Modell')}</span>
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => navigate('assets')}>{t('Modell & Varianten öffnen')}</button>
      <span>{actions.length ? `${actions.length} ${t('definierte Handlungen')}` : t('Dekoratives Prop ohne Aktionen')}</span>
      {repair.length > 0 && <span className="ga-hint">{repair.length} {t('aktive Handlungen ohne vollständige Bindung dieser Variante')}</span>}
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => navigate(repair.length ? 'places' : 'actions')}>
        {t(repair.length ? 'Räumliche Bindung ansehen' : 'Aktionen ansehen')}
      </button>
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
