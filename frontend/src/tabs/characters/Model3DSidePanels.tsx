import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { AnimationSituations } from './AnimationSituations'
import { ExtensionBonesBox } from './ExtensionBonesBox'
import { FieldModelRefs } from './FieldModelRefs'
import { hasExtensionSection } from './model3dModel'
import { publishModel3DTargets, useModel3DPanel } from './model3dPanel'
import { SubTabs } from './StepRows'
import { PANEL } from './stepStyle'

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

/** The 3D tab's "Extension bones" sub-tab — only OFF the base-body pipeline (an animal, a temporary NPC: no base
 *  body) and only for a served model with extension groups (`hasExtensionSection`): the box of the served model. On
 *  the pipeline the box, its switches and the state preview live in the Base body tab (Rulings A45, A66). */
export function Model3DExtensions({ character }: { character: string }) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, pending, busy, rigless, mixamo, viewTier, extensionResult,
    canMeasure, model, setExtensionOption, setExtensionMotion, rebuildExtensions } = panel
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
  // Off the pipeline only (Model3DDetails' Model sub-tab): on it every outfit model is built from the base body by
  // the Figure tab's Build — nothing to choose, the flow head says so.
  if (st.pipeline) return null
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

type DetailTab = 'steps' | 'model' | 'pose' | 'situations' | 'extensions' | 'advanced'
/** The pose render is the T-pose kind's (a literal kept stable for FieldModelRefs' poll). */
const TPOSE: ('tpose')[] = ['tpose']
const HIDDEN: CSSProperties = { display: 'none' }

/**
 * The 3D tab's right-hand panel (Task UI5, the tab checklist: sub-tabs instead of scrolling): Steps (the model's
 * steps, one line each), Model (its facts and single steps, the off-pipeline generation switch), off the pipeline
 * Pose render (an animal's or a temporary NPC's T-pose render and its views, the input of the mesh: one step row
 * each with its Regenerate, "Render all views", Auto and the view switches — Ruling A70 moved it here from the
 * dissolved Pose tab; on the pipeline the dressed views are the Figure tab's), Situations (the clips that play),
 * Extension bones (off the pipeline with groups only — `hasExtensionSection`, Ruling A66) and Advanced. Steps,
 * Model and Advanced are FieldModel3D's own parts, rendered into this panel's elements (publishModel3DTargets →
 * createPortal); the rest are the side panels above.
 */
export function Model3DDetails({ character }: { character: string }) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  // Situations opens first (Ruling A108: the tab opens on the figure walking, its hair moving); the choice is not
  // stored — every opening of the tab starts there.
  const [sub, setSub] = useState<DetailTab>('situations')
  const steps = useRef<HTMLDivElement>(null)
  const model = useRef<HTMLDivElement>(null)
  const advanced = useRef<HTMLDivElement>(null)
  const publish = useCallback(() => {
    if (steps.current && model.current && advanced.current) {
      publishModel3DTargets(character, { steps: steps.current, model: model.current, advanced: advanced.current })
    }
  }, [character])
  useEffect(() => {
    publish()
    return () => publishModel3DTargets(character, null)
  }, [character, publish])
  const count = panel?.model?.steps?.length
  const extensions = !!panel && hasExtensionSection(panel.st)
  // The Extension bones sub-tab left (the model went onto the pipeline, its groups went): show the Steps.
  // The Pose render left the same way (the character went onto the pipeline): show the Steps.
  const poseRender = !!panel && !panel.st.pipeline
  const current: DetailTab = (sub === 'extensions' && !extensions) || (sub === 'pose' && !poseRender) ? 'steps' : sub
  const tabs: Array<{ id: DetailTab; label: string }> = [
    { id: 'steps', label: count ? `${t('Steps')} (${count})` : t('Steps') },
    { id: 'model', label: t('Model') },
    ...(poseRender ? [{ id: 'pose' as const, label: t('Pose render') }] : []),
    { id: 'situations', label: t('Situations') },
    ...(extensions ? [{ id: 'extensions' as const, label: t('Extension bones') }] : []),
    { id: 'advanced', label: t('Advanced') },
  ]
  return (
    <div className="ga-model3d-side" style={PANEL}>
      <SubTabs tabs={tabs} value={current} onChange={setSub} />
      <div ref={steps} style={current === 'steps' ? undefined : HIDDEN} />
      <div style={current === 'model' ? { display: 'flex', flexDirection: 'column', gap: 8 } : HIDDEN}>
        {panel && !panel.st.pipeline ? <Model3DGeneration character={character} /> : null}
        <div ref={model} />
      </div>
      {current === 'pose' ? <FieldModelRefs character={character} kinds={TPOSE} layout="steps" /> : null}
      {current === 'situations' ? <Model3DAnimations character={character} /> : null}
      {current === 'extensions' ? <Model3DExtensions character={character} /> : null}
      <div ref={advanced} style={current === 'advanced' ? undefined : HIDDEN} />
    </div>
  )
}
