import { useI18n } from '../../i18n/I18nProvider'
import { AnimationSituations } from './AnimationSituations'
import { ExtensionBonesBox } from './ExtensionBonesBox'
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

/** The 3D tab's "Extension bones" section. On the base-body pipeline the box lives in the Base body tab beside
 *  the tip panels and acts on the base model, whose switches the outfit models take (Ruling A45): here only the
 *  way there. Off the pipeline (an animal, a temporary NPC — no base body) it is the box of the served model. */
export function Model3DExtensions({ character, onOpenBaseBody }: {
  character: string
  /** Switches to the Base body tab. */
  onOpenBaseBody?: () => void
}) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, pending, busy, rigless, mixamo, viewTier, extensionResult,
    canMeasure, model, setExtensionOption, setExtensionMotion, rebuildExtensions } = panel
  if (st.pipeline) {
    return (
      <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 8 }}>
        <span className="ga-hint">{t('Set on the base body — the outfit models take its extension bones.')}</span>
        {onOpenBaseBody ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}>{t('Open Base body tab')}</button>
        ) : null}
      </div>
    )
  }
  const signature = st.model?.signature || ''
  return (
    <ExtensionBonesBox groups={st.extension_groups ?? []} result={extensionResult} tier={viewTier}
      signature={signature} switches={st.options?.extension_rig_models?.[signature]}
      inherited={st.extension_inherited} motionDefaults={st.motion_defaults}
      motionOverrides={st.options?.extension_motion} disabled={pending || busy} rigless={rigless}
      draftKey={`${character}:${signature || st.signature || ''}`}
      onSwitch={(id, key, value) => { void setExtensionOption(id, key, value) }}
      onMotion={(id, values) => setExtensionMotion(id, values)}
      rebuild={model?.format === 'glb' && mixamo ? {
        label: t('Rebuild extension bones'), disabled: pending || !canMeasure, onClick: () => { void rebuildExtensions() },
      } : null} />
  )
}

export function Model3DGeneration({ character }: { character: string }) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, setModelOption } = panel
  // Base-body pipeline: every outfit model is built from the base body on
  // its own (no backend, no GPU) — nothing to choose here. The face options
  // (face cleanup, face before rigging) live with the model they act on:
  // ModelFaceActions, in the Figure tab's plain-body details on the pipeline, beside the
  // preview in the 3D tab off it.
  if (st.pipeline) return <div className="ga-hint">{t('Outfit models are built from the base body by the Figure tab’s Build.')}</div>
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
