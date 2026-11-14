import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { AnimationSituations } from './AnimationSituations'
import { ExtensionBonesBox } from './ExtensionBonesBox'
import { publishModel3DTargets, useModel3DPanel } from './model3dPanel'
import { outfitOnlyGroups, outfitOnlyLine } from './model3dModel'
import { SubTabs } from './StepRows'
import { PANEL } from './stepStyle'
import { useBaseBody } from './useBaseBody'

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
  const { info } = useBaseBody(character)
  if (!panel) return <div className="ga-hint">{t('Loading…')}</div>
  const { st, pending, busy, rigless, mixamo, viewTier, extensionResult,
    canMeasure, model, setExtensionOption, setExtensionMotion, rebuildExtensions } = panel
  if (st.pipeline) {
    // A group the served outfit model carries and the base model does not has no switch anywhere (Task UI5):
    // named read-only, so it is not a mystery in the viewer.
    const only = outfitOnlyGroups((st.extension_groups ?? []).map((group) => group.id),
      info?.extension ? info.extension.groups.map((group) => group.id) : null)
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 8 }}>
          <span className="ga-hint">{t('Set on the base body — the outfit models take its extension bones.')}</span>
          {onOpenBaseBody ? (
            <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}>{t('Open Base body tab')}</button>
          ) : null}
        </div>
        {only.length ? <div className="ga-hint">{outfitOnlyLine(only, t)}</div> : null}
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

type DetailTab = 'steps' | 'model' | 'situations' | 'extensions' | 'advanced'
const HIDDEN: CSSProperties = { display: 'none' }

/**
 * The 3D tab's right-hand panel (Task UI5, the tab checklist: sub-tabs instead of scrolling): Steps (the model's
 * steps, one line each), Model (its facts and single steps, the off-pipeline generation switch), Situations (the
 * clips that play), Extension bones and Advanced. Steps, Model and Advanced are FieldModel3D's own parts, rendered
 * into this panel's elements (publishModel3DTargets → createPortal); the rest are the side panels above.
 */
export function Model3DDetails({ character, onOpenBaseBody }: {
  character: string
  /** Switches to the Base body tab. */
  onOpenBaseBody?: () => void
}) {
  const { t } = useI18n()
  const panel = useModel3DPanel(character)
  const [sub, setSub] = useState<DetailTab>('steps')
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
  const tabs: Array<{ id: DetailTab; label: string }> = [
    { id: 'steps', label: count ? `${t('Steps')} (${count})` : t('Steps') },
    { id: 'model', label: t('Model') },
    { id: 'situations', label: t('Situations') },
    { id: 'extensions', label: t('Extension bones') },
    { id: 'advanced', label: t('Advanced') },
  ]
  return (
    <div className="ga-model3d-side" style={PANEL}>
      <SubTabs tabs={tabs} value={sub} onChange={setSub} />
      <div ref={steps} style={sub === 'steps' ? undefined : HIDDEN} />
      <div style={sub === 'model' ? { display: 'flex', flexDirection: 'column', gap: 8 } : HIDDEN}>
        {panel && !panel.st.pipeline ? <Model3DGeneration character={character} /> : null}
        <div ref={model} />
      </div>
      {sub === 'situations' ? <Model3DAnimations character={character} /> : null}
      {sub === 'extensions' ? <Model3DExtensions character={character} onOpenBaseBody={onOpenBaseBody} /> : null}
      <div ref={advanced} style={sub === 'advanced' ? undefined : HIDDEN} />
    </div>
  )
}
