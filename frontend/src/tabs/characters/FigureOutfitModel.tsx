/**
 * FigureOutfitModel — the Figure tab's "Outfit model" sub-tab (Ruling A70; until then the Pose tab's, Task UI5): the
 * current outfit's model, as a step row (`outfitRow`: ready, outdated with the reason, failed with the error,
 * the views the guard left out as warnings) and the model's own steps (ModelSteps, one line per step, the numbers on
 * mouse-over). The Figure tab's viewer shows the figure delivered now, its Build makes this model; nothing here
 * starts a job. Reads GET …/figure?plain=1 (`plain_body.outfit`, useBaseBody) and GET …/model3d (the steps,
 * useModel3DStatus); `refresh` (the Figure tab's Build state) loads both again.
 */
import { useEffect } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ModelSteps } from './ModelSteps'
import type { ModelStep } from './ModelSteps'
import { StepRowView } from './StepRows'
import { outfitRow } from './dressedViewsModel'
import { staleModelText } from './figureModel'
import { useBaseBody } from './useBaseBody'
import type { BaseOutfitInfo } from './useBaseBody'
import { useModel3DStatus } from './useModel3DStatus'

export function FigureOutfitModel({ character, refresh }: {
  character: string
  /** Changes when the Figure tab's Build starts or ends: both reads start again. */
  refresh: string
}) {
  const { t } = useI18n()
  const { st, startPoll } = useModel3DStatus(character)
  const { info, startPoll: startBasePoll } = useBaseBody(character)
  useEffect(() => {
    if (!refresh) return
    startBasePoll(500)
    startPoll(800)
  }, [refresh, startBasePoll, startPoll])
  if (!st || !info) return <div className="ga-hint">{t('Loading…')}</div>
  return <OutfitModelRows outfit={info.pipeline ? info.outfit : null} steps={st.model?.steps ?? []} />
}

/** The sub-tab's rows from the two reads (rendered from a fixture by scripts/check_figure_ui.mjs). */
export function OutfitModelRows({ outfit, steps }: { outfit: BaseOutfitInfo | null | undefined; steps: ModelStep[] }) {
  const { t } = useI18n()
  const modelRow = outfit ? outfitRow(outfit, staleModelText(outfit.stale_reason, t), t) : null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {modelRow ? <StepRowView row={{ name: t('Outfit model (base body)'), ...modelRow }} /> : null}
      {steps.length ? <ModelSteps steps={steps} /> : <div className="ga-hint">{t('No model steps recorded')}</div>}
    </div>
  )
}
