/**
 * ModelSteps — the side overview of a model: what was done to it and how
 * each step came out, one row per step, rendered beside the 3D preview
 * (Model3DViewer's `statusPanel`). The list is built on the server
 * (`app/core/model_overview.py`) as `[{id, label, status, detail, numbers}]`
 * — the base model in the Base body tab, an outfit model of the base-body
 * pipeline in the 3D tab — so both tabs render the same component. The
 * 3D tab keeps its own overview for a model of the old path (no `steps`).
 *
 * status → dot: done green · warning yellow · failed red · skipped and
 * missing (nothing recorded) grey. `label` is a fixed English phrase
 * (translated); `detail` is server text with the numbers in it; `numbers`
 * are the raw values, in the row's tooltip.
 */
import { useI18n } from '../../i18n/I18nProvider'

export interface ModelStep {
  id: string
  label: string
  status: 'done' | 'skipped' | 'warning' | 'failed' | 'missing'
  detail: string
  numbers: Record<string, number | string>
}

const DOT: Record<ModelStep['status'], string> = {
  done: 'green',
  warning: 'yellow',
  failed: 'red',
  skipped: 'grey',
  missing: 'grey',
}

const STATUS_LABEL: Record<ModelStep['status'], string> = {
  done: 'Done',
  warning: 'Warning',
  failed: 'Failed',
  skipped: 'Skipped',
  missing: 'Not recorded',
}

const formatNumber = (value: number | string) =>
  typeof value === 'number' ? (Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '')) : value

export function ModelSteps({ steps }: { steps: ModelStep[] }) {
  const { t } = useI18n()
  return (
    <div className="ga-model3d-status" aria-label={t('Model steps')}>
      {steps.map((s) => {
        const numbers = Object.entries(s.numbers || {})
          .map(([key, value]) => `${key} ${formatNumber(value)}`).join(' · ')
        const tip = [`${t(s.label)}: ${t(STATUS_LABEL[s.status] || s.status)}`, s.detail, numbers]
          .filter(Boolean).join('\n')
        return (
          <div key={s.id} className="ga-model3d-status-row" title={tip}>
            <span className={`ga-model3d-status-dot ga-model3d-status-${DOT[s.status] || 'grey'}`} />
            <span>{t(s.label)}{s.detail ? ` · ${s.detail}` : ` · ${t(STATUS_LABEL[s.status] || s.status)}`}</span>
          </div>
        )
      })}
    </div>
  )
}
