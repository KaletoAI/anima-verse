/**
 * ExtensionBonesBox — the "Extension bones" box of ONE stored model: its extension rig's state for the shown tier,
 * then one row per extension group with the model's own switches (Enabled, Flip direction — saved for that model,
 * built by the next rebuild), the Bounce / Weight sliders (live in the viewer while they move, Save stores them)
 * and the group's motion values (saved character-wide, live in the preview), and the rebuild button.
 *
 * Two homes (Ruling A45): the Base body tab, beside the tip panels, acting on the base model — the outfit models
 * built on it take its switches; there the caller passes only the groups WITHOUT a tip panel (`box_groups`): a tip
 * group's light, switch, factors and Rebuild sit in its own tip panel (Ruling A53); and the 3D tab for a character off the base-body pipeline (an animal, a
 * temporary NPC), acting on the served model. The owner holds the state and the requests; this box only renders.
 */
import type { ExtensionRigDeclaration, SecondaryMotionPayload } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import type { Physics } from '../../lib/motionDraft'
import { ExtensionMotionDraft, ExtensionMotionSliders } from './ExtensionMotionDraft'
import { MotionPreviewHint } from './MotionPreviewHint'
import type { ExtensionRigResult } from './FieldModel3D'
import { StepLight } from './StepRows'
import type { ExtensionGroupLight } from './useBaseBody'

export interface ExtensionBonesBoxProps {
  groups: ExtensionRigDeclaration[]
  /** The extension rig's record of the shown tier. */
  result: ExtensionRigResult | undefined
  tier: 'full' | 'low'
  /** The model the switches belong to; empty = no stored model, the switches rest. */
  signature: string
  /** The model's own switches (`model3d_opts.extension_rig_models[signature]`). */
  switches: Record<string, { enabled?: boolean; flip?: boolean }> | undefined
  /** Switches the model takes from its base model, shown locked (`extension_inherited`). */
  inherited?: Record<string, { enabled: boolean; reason: string }>
  motionDefaults: SecondaryMotionPayload['groups'] | undefined
  motionOverrides: Record<string, Physics> | undefined
  disabled: boolean
  /** A static mesh: the motion values rest. */
  rigless: boolean
  /** Keys the drafts to the model, so a model switch starts them afresh. */
  draftKey: string
  onSwitch: (id: string, key: 'enabled' | 'flip', value: boolean) => void
  onMotion: (id: string, values?: Physics) => Promise<boolean>
  /** Given: the Bounce / Weight sliders sit in the box (else beside the viewer, the 3D tab's). */
  sliders?: {
    onPreview: (id: string, values: Physics) => void
    onSave: (id: string, values: Physics) => Promise<boolean>
  }
  /** One light per group (Base body tab, Ruling A49): its build state and the reason in plain words. */
  lights?: Record<string, ExtensionGroupLight>
  /** A line under the state, e.g. "Saved — not built yet …". */
  note?: string
  /** Given: the box is a framed group with this legend, like the tip panels it sits beside (Base body tab); the
   *  state line then starts with the tier. Absent: the section around it carries the title (3D tab). */
  legend?: string
  rebuild?: { label: string; title?: string; disabled: boolean; primary?: boolean; onClick: () => void } | null
}

export function ExtensionBonesBox({ groups, result, tier, signature, switches, inherited,
  motionDefaults, motionOverrides, disabled, rigless, draftKey, onSwitch, onMotion, sliders, lights, note,
  legend, rebuild }: ExtensionBonesBoxProps) {
  const { t } = useI18n()
  const tierLabel = tier === 'low' ? t('Distance') : t('Full')
  if (!groups.length) return <div className="ga-hint">{t('No extension bones on this model.')}</div>
  return (
    <fieldset className={`ga-form ga-ext-panel${legend ? ' ga-model3d-group' : ''}`}>
      {legend ? <legend>{legend}</legend> : null}
      <div className="ga-hint" aria-live="polite">
        <strong>{legend ? tierLabel : `${t('Extension bones')} · ${tierLabel}`}: </strong>
        {t(result?.status === 'applied' ? 'Applied'
          : result?.status === 'failed' ? 'Failed'
          : result?.status === 'not_found' ? 'Geometry not found'
          : result?.status === 'none_applicable' ? 'No applicable groups'
          : 'Not processed')}
        {result?.reason ? ` · ${result.reason}` : ''}
        {result?.metrics ? (
          <details>
            <summary>{t('Metrics')}</summary>
            <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {JSON.stringify(result.metrics, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>
      {note ? <div className="ga-hint">{note}</div> : null}

      {groups.map((group) => {
        // An outfit model on the base body: a group the base switched off
        // is off here too, whatever this model's own switch says.
        const locked = inherited?.[group.id]
        const own = switches?.[group.id]
        const hasSliders = !!sliders && !!motionDefaults?.[group.id]
          && (group.controls == null || group.controls.some((key) => ['bounce', 'weight'].includes(key)))
        const light = lights?.[group.id]
        return (
          <div key={group.id} className="ga-ext-row">
            <strong>{group.id}</strong>
            {light ? (
              <span className="ga-ext-light" data-light={light.light}
                title={light.detail ? `${t('Build record')}: ${light.detail}` : undefined}>
                <StepLight light={light.light} /> <strong>{t(light.state)}</strong>
                {light.reason ? <> — {t(light.reason)}</> : null}
                {light.detail && light.light === 'red' ? <span className="ga-hint"> ({light.detail})</span> : null}
              </span>
            ) : null}
            <label title={locked ? t(locked.reason) : undefined}>
              <input type="checkbox" disabled={disabled || !signature || !!locked}
                checked={!locked && own?.enabled !== false}
                onChange={(event) => onSwitch(group.id, 'enabled', event.target.checked)} />
              {' '}{t('Enabled')} <MotionPreviewHint field="enabled" />
              {locked ? <span className="ga-hint" style={{ marginLeft: 4 }}>{t(locked.reason)}</span> : null}
            </label>
            {group.op === 'appendage_chain' ? (
              <label>
                <input type="checkbox" disabled={disabled || !signature}
                  checked={own?.flip === true}
                  onChange={(event) => onSwitch(group.id, 'flip', event.target.checked)} />
                {' '}{t('Flip direction')} <MotionPreviewHint field="flip" />
              </label>
            ) : null}
            {hasSliders && sliders ? (
              <div className="ga-ext-sliders">
                <ExtensionMotionSliders key={`${draftKey}:${group.id}:sliders`} controls={group.controls}
                  overrides={motionOverrides?.[group.id] ?? {}} disabled={disabled || rigless}
                  onPreview={(values) => sliders.onPreview(group.id, values)}
                  onSave={(values) => sliders.onSave(group.id, values)} />
              </div>
            ) : null}
            {motionDefaults?.[group.id] ? <ExtensionMotionDraft
              key={`${draftKey}:${group.id}`}
              controls={group.controls}
              defaults={motionDefaults[group.id] as unknown as Physics}
              overrides={motionOverrides?.[group.id] ?? {}}
              disabled={disabled || rigless}
              onSave={(values) => onMotion(group.id, values)} /> : null}
          </div>
        )
      })}
      <div className="ga-ext-row">
        {rebuild ? (
          <button type="button" className={`ga-btn ga-btn-sm${rebuild.primary ? ' ga-btn-primary' : ''}`}
            disabled={rebuild.disabled} title={rebuild.title} onClick={rebuild.onClick}>{rebuild.label}</button>
        ) : null}
        <span className="ga-hint">{t('Enabled and flip are saved for this model; they take effect after rebuilding its extension bones.')}</span>
      </div>
    </fieldset>
  )
}
