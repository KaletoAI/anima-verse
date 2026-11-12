/**
 * FieldHair — the Hair tab: how the character's hair is made.
 *
 * Two hair methods (spec docs/superpowers/specs/2026-11-11-hair-from-body-design.md):
 * - From the body mesh (`body`, the world default): the base views are rendered
 *   with the hair, so the hair is part of the body mesh. The tab then shows only
 *   the method, the hair description, "Hair comes from the body mesh" and the
 *   base body's prompt freshness — no steps, no run, no preview.
 * - HairDeck (plan docs/superpowers/plans/2026-11-09-hairdeck-hair.md): the
 *   profile picture -> hair cards in one Hub call -> fit onto the rigged base
 *   model. The hair item is a garment worn in the `hair` mesh slot. Every step
 *   is gated.
 *
 * The mode select, the HairDeck colour, the placement and the HairDeck steps
 * (with seed and run) moved to the Wardrobe's hair row (WardrobeHairRow,
 * HairDeckPlacement; plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
 * Task 9) — one place edits them. This tab keeps what the Figure tab (Task 10)
 * takes over: wearing the hair, creating the item, the run state, the fitted
 * preview with "Run all", and the kept results of other methods. With `body`, a
 * base rendered with older prompts (`base_prompts` stale) points to its rebuild.
 *
 * Backend (app/routes/characters.py, app/core/garments.py):
 * GET /characters/{n}/hair (polled while a step runs — useGarment),
 * POST /characters/{n}/hair (create + wear the item, start the chain),
 * POST /characters/{n}/hair/equipped {equipped},
 * POST /characters/{n}/garments/{item}/run {step?, view?, force?}
 * (409 while a garment run of the character goes — shown beside the clicked
 * button; useGarmentRun gives every run click its own feedback).
 *
 * The hair description is DERIVED from Appearance (R3) — read-only here.
 * Changing it does not start GPU work (R14): the tab shows "Hair description
 * changed" and the old hair stays served until Regenerate.
 *
 * Layout: two columns — method, description and state; the fitted preview
 * with "Run all".
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { GarmentFailure, GateChips, RunButton, RunStatusLine } from './GarmentSteps'
import { HAIRDECK_FIT_CHIPS, HAIR_STEP_LABELS, ROW, WARN_STYLE } from './garmentStyle'
import { FreshnessBadge } from './FreshnessBadge'
import type { GarmentRunBody } from './garmentStyle'
import { Model3DViewer } from './Model3DViewer'
import { Swatch } from './WardrobeHairRow'
import { garmentRunning, useGarment, useGarmentRun } from './useGarment'
import type { HairInfo, HairMethod, OtherMethodInfo } from './useGarment'

const STEP_LABELS = HAIR_STEP_LABELS

const METHOD_LABELS: Record<HairMethod, string> = {
  body: 'From the body mesh',
  hairdeck: 'HairDeck',
}

/** Where the hair's settings are edited now (plan 2026-11-12-unified-worn-pieces, Task 9). */
const MOVED_HINT = "Mode, colour, placement and the HairDeck steps are set in the Wardrobe's hair row."

/** "Create hair" exists for HairDeck only — `body` makes no hair item. */
const CREATE_HINT = 'Makes hair cards from the profile picture and fits them onto the base model.'

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Hair description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  fit_algorithm_updated: 'Fit algorithm updated',
  hairdeck_changed: 'Profile picture or HairDeck settings changed',
  colour_changed: 'Hair colour changed',
  placement_changed: 'Hair placement changed',
}

/** The kept results of the methods not selected (newest first), each collapsed
 *  with "Use this method" (the same save as the selector above — the switch
 *  generates nothing). Only HairDeck keeps a result: `body` has no hair mesh of
 *  its own, so nothing is listed for it. */
function OtherMethods({ others, limits, busy, onUse }: {
  others: OtherMethodInfo[]
  limits: HairInfo['limits']
  busy: boolean
  onUse: (method: HairMethod) => void
}) {
  return (
    <>
      {others.map((o) => (
        <OtherMethod key={o.method} other={o} limits={limits} busy={busy} onUse={() => onUse(o.method)} />
      ))}
    </>
  )
}

/** One kept result of a method that is not selected. */
function OtherMethod({ other, limits, busy, onUse }: {
  other: OtherMethodInfo
  limits: HairInfo['limits']
  busy: boolean
  onUse: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const kept = other.created_at
    ? t('kept result from {date} — switching back generates nothing')
      .replace('{date}', formatDateTime(other.created_at, clockSettings()))
    : t('kept result — switching back generates nothing')
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="ga-hint" style={{ cursor: 'pointer' }}>
        {t(METHOD_LABELS[other.method])}: {kept}
        {!other.on_current_base ? ` · ${t('Fitted on an older base model')}` : ''}
      </summary>
      <div style={ROW}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onUse}>
          {t('Use this method')}
        </button>
      </div>
      {other.colour?.target ? (
        <div style={ROW}>
          <span className="ga-hint">{t('Hair colour')}:</span>
          <Swatch hex={other.colour.target} />
          <span className="ga-hint">{other.colour.target}</span>
        </div>
      ) : null}
      <GateChips specs={HAIRDECK_FIT_CHIPS} record={other.metrics} limits={limits.hairdeck_fit} />
      {open && other.preview_url ? (
        <Model3DViewer key={other.preview_url} url={other.preview_url} format="glb" height={300}
          freshness={other.preview_freshness} />
      ) : null}
    </details>
  )
}

export function FieldHair({ character, onEditAppearance }: {
  character: string
  /** Opens the Appearance tab, where the hair text is edited. */
  onEditAppearance?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, setInfo, startPoll } = useGarment<HairInfo>(character ? `/characters/${enc}/hair` : null)
  // The user's own click, until the request answered (the poll then shows
  // the server's running state).
  const [posting, setPosting] = useState(false)

  const call = useCallback(
    async (path: string, body: unknown, after?: (d: unknown) => void | Promise<unknown>) => {
      if (posting) return
      setPosting(true)
      try {
        const d = await apiPost(path, body)
        await after?.(d)
        startPoll(300)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        startPoll()
      } finally {
        setPosting(false)
      }
    },
    [posting, startPoll, t, toast],
  )

  const itemId = info?.item_id || ''
  const { feedback, start, cancel } = useGarmentRun(character, itemId, info, startPoll)

  const create = useCallback(
    () => call(`/characters/${enc}/hair`, {}, (d) => {
      // A run behind the character's other garment runs is queued (the status line shows it).
      const answer = d as { started?: boolean; queued?: boolean } | null
      if (answer?.started === false && !answer.queued) {
        toast(t('A hair run is already going for this character'))
      }
    }),
    [call, enc, t, toast],
  )

  const setEquipped = useCallback(
    (equipped: boolean) => call(`/characters/${enc}/hair/equipped`, { equipped }, () => {
      setInfo((prev: HairInfo | null) => (prev ? { ...prev, equipped } : prev))
    }),
    [call, enc, setInfo],
  )

  const setMethod = useCallback(
    (method: '' | HairMethod) => call(`/characters/${enc}/hair/method`, { method }),
    [call, enc],
  )

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) {
    return <div className="ga-hint">{t('Hair as its own mesh is for humanoid characters only.')}</div>
  }
  if (!info.pipeline) {
    return (
      <div className="ga-hint">
        {t('Hair as its own mesh needs the base body pipeline — switch it on in the Base body tab')}
      </div>
    )
  }

  const editButton = onEditAppearance ? (
    <button type="button" className="ga-btn ga-btn-sm" onClick={onEditAppearance}>
      {t('Edit in Appearance')}
    </button>
  ) : null

  const garment = info.garment
  const busy = posting || feedback.pending !== null || garmentRunning(info)
  const limits = info.limits || {}
  const fit = garment?.steps.fit
  const noHair = !!garment && !garment.served_fsig && !garment.running_step && fit?.status !== 'accepted'
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  const methodBlock = (
    <>
      <div className="ga-fieldset-title">{t('Hair method')}</div>
      <div style={ROW}>
        <span>{t(METHOD_LABELS[info.method] || info.method)}</span>
        <span className="ga-hint">{t(MOVED_HINT)}</span>
      </div>

      <div className="ga-fieldset-title">{t('Hair description')}</div>
      {info.description ? (
        <div style={ROW}>
          <span>{info.description}</span>
          {editButton}
        </div>
      ) : (
        <div style={ROW}>
          <span className="ga-hint">{t('No hair set in Appearance')}</span>
          {editButton}
        </div>
      )}
    </>
  )

  if (info.hair_in_body) {
    // The hair is part of the base body / outfit body mesh: nothing to run here.
    const prompts = info.base_prompts
    return (
      <div className="ga-split ga-split-hair">
        <div className="ga-split-col">
          {methodBlock}
          <div style={ROW}><span>{t('Hair comes from the body mesh')}</span></div>
          <div style={ROW}>
            <span className="ga-hint">{t('Base body prompts')}</span>
            <FreshnessBadge freshness={prompts} compact />
          </div>
          {prompts?.state === 'stale' ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {t('This base body was rendered with older prompts, so its mesh may carry no hair. Rebuild it: Regenerate in the Base body tab, or the Improvements type “Rebuild base bodies made with older prompts”, which runs when the queue is idle.')}
            </div>
          ) : prompts?.state === 'missing' ? (
            <div className="ga-hint">{t('No base body yet — generate it in the Base body tab; it is rendered with the hair.')}</div>
          ) : null}
        </div>
      </div>
    )
  }

  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
      {methodBlock}

      {!info.item_id ? (
        info.description ? (
          <>
            <div style={ROW}>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={posting} onClick={() => { void create() }}>
                {t('Create hair')}
              </button>
              <span className="ga-hint">{t(CREATE_HINT)}</span>
            </div>
          </>
        ) : null
      ) : (
        <>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={info.equipped}
              disabled={posting}
              onChange={(e) => { void setEquipped(e.target.checked) }}
            />
            <span>{t('Wear hair')}</span>
          </label>

          <RunStatusLine garment={garment} feedback={feedback} stepLabels={STEP_LABELS}
            onCancel={() => { void cancel() }} />

          {garment && garment.stale_reasons.length ? (
            <div style={{ ...ROW, padding: 8, borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE}>
                {garment.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              </span>
              <span className="ga-hint">{t('The previous hair stays in use until the new one is fitted.')}</span>
              <RunButton feedback={feedback} slot="stale" disabled={busy} onClick={() => onRun({}, 'stale')}
                label={t('Regenerate')} />
            </div>
          ) : null}

          <GarmentFailure garment={garment} stepLabels={STEP_LABELS} />

          {noHair ? (
            <div style={{ ...ROW, padding: 8, borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE}>{t('No hair from this method yet')}</span>
              <RunButton feedback={feedback} slot="nohair" disabled={busy} onClick={() => onRun({}, 'nohair')}
                label={t('Regenerate')} />
            </div>
          ) : null}

        </>
      )}
      </div>
      {info.item_id ? (
        <>
          <div className="ga-split-col">
            <div className="ga-face-actions-row">
              <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Preview')}</span>
              <RunButton
                feedback={feedback}
                slot="all"
                disabled={busy || !garment}
                title={t('Runs every step that is missing or out of date')}
                onClick={() => onRun({}, 'all')}
                label={garment?.running_step === 'queued' ? t('Queued')
                  : garmentRunning(info) ? t('Generating…') : t('Run all')}
              />
            </div>
            {garment?.preview_url ? (
              <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={380}
                freshness={garment.preview_freshness} collision={info.collision} />
            ) : (
              <div className="ga-hint">{t('No fitted hair yet')}</div>
            )}
            <div className="ga-hint">
              {info.collision?.capsules?.length
                ? t('Collides with the base body\'s torso, arm and head capsules — “Garment collision” in the viewer compares')
                : t('No capsule set on the base model yet — the hair is shown as skinned')}
            </div>
            <OtherMethods others={info.others} limits={limits} busy={busy}
              onUse={(m) => { void setMethod(m) }} />
          </div>
        </>
      ) : null}
    </div>
  )
}
