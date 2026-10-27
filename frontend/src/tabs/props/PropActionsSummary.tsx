import type { PropWorkspace } from './usePropWorkspace'

/** Read the real author document. Semantic authoring is supplied by Task 8. */
export function PropActionsSummary({ workspace }: { workspace: PropWorkspace }) {
  const { t, actions, shownVariant, navigate } = workspace
  const bindings = shownVariant?.action_bindings || []
  return <div className="ga-form prop-area-content">
    <h3>{t('Aktionen')}</h3>
    <p className="ga-hint">{t('Handlungen gelten für das gesamte Prop; ihre räumliche Bindung gehört zur ausgewählten Variante.')}</p>
    {actions.length === 0 ? <p>{t('Keine Aktionen definiert. Dekorative Props benötigen keine Handlung.')}</p>
      : <ul className="prop-actions-summary">
        {actions.map((action) => {
          const binding = bindings.find((item) => item.action_id === action.id)
          return <li key={action.id}>
            <strong>{action.name}</strong>
            <span>{t(action.enabled ? 'Aktiviert' : 'Deaktiviert')} · {action.participants} {t('Personen')} · {action.ability}</span>
            {action.description && <p>{action.description}</p>}
            <span className="ga-hint">{!binding ? t('Keine Bindung für diese Variante')
              : !binding.supported ? t('In dieser Variante nicht unterstützt')
                : binding.validation === 'repair_required' ? t('Räumliche Bindung benötigt Reparatur')
                  : binding.validation === 'local_valid' ? t('Lokal geprüft; Raumweg nicht geprüft')
                    : t('Räumlicher Vorschlag; Raumweg nicht geprüft')}</span>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => navigate('places')}>{t('Plätze im Modell ansehen')}</button>
          </li>
        })}
      </ul>}
  </div>
}
