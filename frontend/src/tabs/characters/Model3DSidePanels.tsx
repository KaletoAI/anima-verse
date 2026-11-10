import { useI18n } from '../../i18n/I18nProvider'
import { AnimationSituations } from './AnimationSituations'
import { ExtensionMotionDraft } from './ExtensionMotionDraft'
import { MotionPreviewHint } from './MotionPreviewHint'
import type { Physics } from '../../lib/motionDraft'
import { useModel3DPanel } from './model3dPanel'

export function Model3DAnimations({ character }: { character: string }) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, model, mixamo, setPlayUrl } = panel
  if (!model) return <div className="ga-hint">{t('Not generated yet')}</div>
  return mixamo ? <AnimationSituations
    key={`${character}:${(st.animation_sets || [st.animation_set || '']).join(':')}`}
    character={character} onPlay={setPlayUrl} /> : <div className="ga-hint">
    {t('Generic rig (no standard skeleton) — Mixamo clips will not drive this model.')}
  </div>
}

export function Model3DExtensions({ character }: { character: string }) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, pending, busy, rigless, mixamo, viewTier, extensionResult,
    canMeasure, model, setExtensionOption, setExtensionMotion, rebuildExtensions } = panel
  return <>
      {st.extension_groups?.length ? (
        <fieldset className="ga-form ga-ext-panel">
          <div className="ga-hint" aria-live="polite">
            <strong>{t('Extension bones')} · {viewTier}: </strong>
            {t(extensionResult?.status === 'applied' ? 'Applied'
              : extensionResult?.status === 'failed' ? 'Failed'
              : extensionResult?.status === 'not_found' ? 'Geometry not found'
              : extensionResult?.status === 'none_applicable' ? 'No applicable groups'
              : 'Not processed')}
            {extensionResult?.reason ? ` · ${extensionResult.reason}` : ''}
            {extensionResult?.metrics ? (
              <details>
                <summary>{t('Metrics')}</summary>
                <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {JSON.stringify(extensionResult.metrics, null, 2)}
                </pre>
              </details>
            ) : null}
          </div>

          {st.extension_groups.map((group) => {
            // An outfit model on the base body: a group the base switched off
            // is off here too, whatever this model's own switch says.
            const inherited = st.extension_inherited?.[group.id]
            return (
            <div key={group.id} className="ga-ext-row">
              <strong>{group.id}</strong>
              <label title={inherited ? t(inherited.reason) : undefined}>
                <input type="checkbox" disabled={pending || busy || !st.model?.signature || !!inherited}
                  checked={!inherited && st.options?.extension_rig_models?.[st.model?.signature || '']?.[group.id]?.enabled !== false}
                  onChange={(event) => setExtensionOption(group.id, 'enabled', event.target.checked)} />
                {' '}{t('Enabled')} <MotionPreviewHint field="enabled" />
                {inherited ? <span className="ga-hint" style={{ marginLeft: 4 }}>{t(inherited.reason)}</span> : null}
              </label>
              {group.op === 'appendage_chain' ? (
                <label>
                  <input type="checkbox" disabled={pending || busy || !st.model?.signature}
                    checked={st.options?.extension_rig_models?.[st.model?.signature || '']?.[group.id]?.flip === true}
                    onChange={(event) => setExtensionOption(group.id, 'flip', event.target.checked)} />
                  {' '}{t('Flip direction')} <MotionPreviewHint field="flip" />
                </label>
              ) : null}
              {st.motion_defaults?.[group.id] ? <ExtensionMotionDraft
                key={`${character}:${st.model?.signature || st.signature || ''}:${group.id}`}
                controls={group.controls}
                defaults={st.motion_defaults[group.id] as unknown as Physics}
                overrides={st.options?.extension_motion?.[group.id] ?? {}}
                disabled={pending || busy || rigless}
                onSave={values => setExtensionMotion(group.id, values)} /> : null}
            </div>
            )
          })}
          <div className="ga-ext-row">
            {model?.format === 'glb' && mixamo ? (
              <button type="button" className="ga-btn ga-btn-sm" disabled={pending || !canMeasure}
                onClick={rebuildExtensions}>{t('Rebuild extension bones')}</button>
            ) : null}
            <span className="ga-hint">{t('Enabled and flip are saved for this model; they take effect after rebuilding its extension bones.')}</span>
          </div>
        </fieldset>
      ) : <div className="ga-hint">{t('No extension bones on this model.')}</div>}
  </>
}

export function Model3DGeneration({ character }: { character: string }) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, setModelOption } = panel
  // Base-body pipeline: every outfit model is built from the base body on
  // its own (no backend, no GPU) — nothing to choose here. The face options
  // (face cleanup, face before rigging) live with the model they act on:
  // ModelFaceActions, in the Base body tab on the pipeline, beside the
  // preview in the 3D tab off it.
  if (st.pipeline) return <div className="ga-hint">{t('Outfit models are built from the base body automatically.')}</div>
  return (
    <label className="ga-check-row"
      title={t('Once the T-pose render of a NEW outfit combination has succeeded, the mesh is generated automatically on the cheapest matching backend — the T-pose is always awaited first.')}>
      <input
        type="checkbox"
        checked={!!st.options?.auto_generate}
        onChange={(e) => setModelOption('auto_generate', e.target.checked)}
      />
      <span>{t('Auto-generate 3D model (cheapest backend)')}</span>
    </label>
  )
}
