/**
 * FieldPose — the Pose tab (template section `model_refs`): the current
 * outfit's pose renders, the image-to-3D input, in two columns like the
 * Base body tab — the views stacked and small on the left (FieldModelRefs,
 * `layout="stack"`; a click enlarges a tile), the model built from them on
 * the right: its 3D preview with the step checklist beside it, and on the
 * base-body pipeline the outfit model's status with "Rebuild outfit model"
 * (BaseBodyOutfitStatus) under it.
 *
 * The model is the 3D tab's (GET /characters/{n}/model3d, useModel3DStatus):
 * the current outfit's own model, or the stored stand-in with the most similar
 * outfit (`match: nearest`, its freshness badge says so). Generating it off
 * the pipeline (mesh backend dialog, upload) stays in the 3D tab.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { BaseBodyOutfitStatus } from './BaseBodyOutfitStatus'
import { FieldModelRefs } from './FieldModelRefs'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { useModel3DStatus } from './useModel3DStatus'

function PoseOutfitModel({ character, onOpen3D }: { character: string; onOpen3D?: () => void }) {
  const { t } = useI18n()
  const enc = encodeURIComponent(character)
  const { st, startPoll } = useModel3DStatus(character)
  const model = st?.model
  const bust = model?.model_rev || model?.created_at || st?.signature || ''
  return (
    <>
      <div className="ga-face-actions-row">
        <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('3D model (current outfit)')}</span>
        {onOpen3D ? <button type="button" className="ga-btn ga-btn-sm" onClick={onOpen3D}>{t('Open 3D tab')}</button> : null}
      </div>
      {!st ? <div className="ga-hint">{t('Loading…')}</div> : model ? (
        <div className="ga-model3d-fit">
          <Model3DViewer key={`${model.signature || ''}:${bust}`} previewTilt height={480}
            url={`/characters/${enc}/model3d/file?v=${encodeURIComponent(bust)}`}
            format={model.format || 'fbx'}
            textureUrl={model.texture_url ? `${model.texture_url}?v=${bust}` : ''}
            embeddedTakes={model.rig === 'generic'} clipLoops={model.clips}
            freshness={model.freshness} collision={model.collision}
            statusPanel={model.steps?.length ? <ModelSteps steps={model.steps} /> : undefined} />
        </div>
      ) : (
        <div className="ga-hint">
          {st.pending ? t('Generating the 3D model — this takes a few minutes.')
            : st.pipeline ? t('No 3D model for this outfit yet — it is built from the base body (Rebuild from base body).')
              : t('No 3D model for this outfit yet — upload one or generate it from the pose render.')}
        </div>
      )}
      <BaseBodyOutfitStatus key={character} character={character} onStarted={() => startPoll(800)} />
    </>
  )
}

export function FieldPose({ character, onOpen3D }: {
  character: string
  /** Switches to the 3D tab (generation off the pipeline, upload, clips). */
  onOpen3D?: () => void
}) {
  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <FieldModelRefs character={character} kinds={['tpose']} layout="stack" />
      </div>
      <div className="ga-split-col">
        <PoseOutfitModel character={character} onOpen3D={onOpen3D} />
      </div>
    </div>
  )
}
