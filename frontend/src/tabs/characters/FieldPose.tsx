/**
 * FieldPose — the Pose tab (template section `model_refs`): the current outfit's dressed views, the input of the
 * outfit model, and that model. Laid out to the user's tab checklist in Task UI5, the way the Figure and Hairstyles
 * tabs are:
 * - the flow head: the light with its words (`poseHead`: "Up to date", "1 step due", "A step failed", "Building
 *   now"), the Figure tab's Build on the figure pipeline (FigureBuildButton — the same POST …/figure/build, its cost
 *   on it, "Everything is current" when nothing is due; Ruling A13b: no cascade of its own) and the links to the
 *   Figure and 3D tabs; one line says the Build renders these views (VIEWS_BY_BUILD), another a running Build;
 * - left: the outfit model (GET …/model3d, useModel3DStatus — the current outfit's own model or the stored
 *   stand-in, its freshness badge says so), "Built <time>" in its corner; the mouse turns the figure;
 * - right: sub-tabs instead of scrolling —
 *   - "Views": one step row per dressed view (FieldModelRefs `layout="steps"`): light, state, reason, small
 *     thumbnails that enlarge, and the view's own Regenerate with its cost ("Regenerate this view — 1 image job",
 *     the follow-up on mouse-over); the face view on the pipeline is the plain body's (a link to the Base body tab
 *     and the one setting of the views pass that renders it); off the pipeline "Render all views", Auto and the
 *     view switches, saved at once;
 *   - "Outfit model": its status as a step row (`outfitRow`: ready with the proof's numbers, outdated with the
 *     reason, failed with the error, the views the guard left out as warnings) and the model's steps (ModelSteps,
 *     one line per step, the numbers on mouse-over).
 * Generating a model off the pipeline (mesh backend dialog, upload) stays in the 3D tab.
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { FieldModelRefs } from './FieldModelRefs'
import { FigureBuildButton } from './FigureBuildButton'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { StepLight, StepRowView, SubTabs } from './StepRows'
import { staleModelText } from './figureModel'
import type { Light } from './hairstylesModel'
import { VIEWS_BY_BUILD, outfitRow, poseHead } from './poseModel'
import { LIGHT_COLOR, PANEL } from './stepStyle'
import { useBaseBody } from './useBaseBody'
import { useModel3DStatus } from './useModel3DStatus'

/** A share (0..1) from the outfit proof's `texels` block, or null when absent. */
function texelShare(proof: Record<string, unknown> | null | undefined, key: string): number | null {
  const texels = proof?.texels
  if (!texels || typeof texels !== 'object') return null
  const v = (texels as Record<string, unknown>)[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

const pct = (v: number) => `${(v * 100).toFixed(1)} %`

export function FieldPose({ character, onOpen3D, onOpenFigure, onOpenBaseBody }: {
  character: string
  /** Switches to the 3D tab (generation off the pipeline, upload, clips). */
  onOpen3D?: () => void
  /** Switches to the Figure tab (the Build, the plain body). */
  onOpenFigure?: () => void
  /** Switches to the Base body tab (the face view is the plain body's). */
  onOpenBaseBody?: () => void
}) {
  const { t } = useI18n()
  const enc = encodeURIComponent(character)
  const { st, startPoll } = useModel3DStatus(character)
  const { info, figure, startPoll: startBasePoll } = useBaseBody(character)
  const [sub, setSub] = useState<'views' | 'model'>('views')
  const [viewLights, setViewLights] = useState('')
  const onLights = useCallback((l: string) => setViewLights(l), [])

  const model = st?.model
  const bust = model?.model_rev || model?.created_at || st?.signature || ''
  const outfit = info?.pipeline ? info.outfit : null
  const coverage = texelShare(outfit?.proof, 'garment_share_of_exposed')
  const filled = texelShare(outfit?.proof, 'unseen_filled_share_of_exposed_garment')
  const proofLine = [
    coverage !== null ? `${t('Garment coverage of the visible surface')}: ${pct(coverage)}` : '',
    filled !== null ? `${t('Garment filled in without a view')}: ${pct(filled)}` : '',
  ].filter(Boolean).join(' · ')
  const modelRow = outfit ? outfitRow(outfit, staleModelText(outfit.stale_reason, t), proofLine, t) : null
  const buildRunning = !!figure?.build?.running
  const lights = [...(viewLights ? viewLights.split(',') as Light[] : []), ...(modelRow ? [modelRow.light] : [])]
  const head = poseHead(lights, buildRunning, t)
  const viewCount = viewLights ? viewLights.split(',').length : 0
  const tabs = [
    { id: 'views' as const, label: viewCount ? `${t('Views')} (${viewCount})` : t('Views') },
    { id: 'model' as const, label: t('Outfit model') },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, fontSize: 13 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <StepLight light={head.light} />
        <strong style={{ color: LIGHT_COLOR[head.light] }}>{head.words}</strong>
        {info?.pipeline ? (
          <FigureBuildButton character={character} primary
            onStarted={() => { startBasePoll(500); startPoll(800) }} />
        ) : null}
        {onOpenFigure && info?.pipeline ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenFigure}>↗ {t('Figure')}</button>
        ) : null}
        {onOpen3D ? <button type="button" className="ga-btn ga-btn-sm" onClick={onOpen3D}>↗ {t('3D')}</button> : null}
      </div>
      {info?.pipeline ? <div className="ga-hint">{t(VIEWS_BY_BUILD)}</div> : null}
      <div className="ga-split ga-split-views ga-split-figure">
        <div className="ga-split-col">
          {!st ? <div className="ga-hint">{t('Loading…')}</div> : model ? (
            <Model3DViewer key={`${model.signature || ''}:${bust}`} height={600} subject="figure"
              url={`/characters/${enc}/model3d/file?v=${encodeURIComponent(bust)}`}
              format={model.format || 'fbx'}
              textureUrl={model.texture_url ? `${model.texture_url}?v=${bust}` : ''}
              embeddedTakes={model.rig === 'generic'} clipLoops={model.clips}
              freshness={model.freshness} collision={model.collision} builtAt={model.created_at}
              footPose={model.foot_pose ?? null} clipGroup={model.foot_pose ? 'ground' : undefined} />
          ) : (
            <div className="ga-hint" style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: 12, textAlign: 'center' }}>
              {st.pending ? t('Generating the 3D model — this takes a few minutes.')
                : st.pipeline ? t('No 3D model for this outfit yet — the Figure tab’s Build makes it from the base body.')
                  : t('No 3D model for this outfit yet — upload one or generate it from the pose render.')}
            </div>
          )}
        </div>
        <div className="ga-split-col" style={PANEL}>
          <SubTabs tabs={tabs} value={sub} onChange={setSub} />
          {/* Kept mounted while hidden: it polls the views and reports their lights to the flow head. */}
          <div style={sub === 'views' ? undefined : { display: 'none' }}>
            <FieldModelRefs character={character} kinds={['tpose']} layout="steps" onOpenBaseBody={onOpenBaseBody}
              onLights={onLights} />
          </div>
          {sub === 'model' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {modelRow ? <StepRowView row={{ name: t('Outfit model (base body)'), ...modelRow }} /> : null}
              {model?.steps?.length ? <ModelSteps steps={model.steps} /> : (
                <div className="ga-hint">{t('No model steps recorded')}</div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
