/**
 * FieldHair — the Hair tab: the character's hair as its own mesh (plan
 * docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md). The hair
 * item is a garment worn in the `hair` mesh slot; its chain renders the
 * base views with hair (haired), the hair alone (hair-only / ghost), squares
 * them into cut-outs, builds and decimates a mesh, and fits it onto the
 * rigged base model. Every step is gated; the tab shows each step's numbers
 * against the server's limits so a refusal is visible, never silent.
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
 * Layout: three columns — method, description and state; the selected
 * method's steps (small tiles, a click enlarges); the fitted preview with
 * what re-fits it (HairDeck colour and placement), "Run all" and the other
 * method's last result.
 *
 * Two hair methods (plan docs/superpowers/plans/2026-11-09-hairdeck-hair.md,
 * Task 5): Hair views → mesh (the edit chain above), or HairDeck (the profile picture -> hair
 * cards in one Hub call -> fit). The method selector at the top stores the
 * character's choice (POST /characters/{n}/hair/method, "" = world default);
 * the selected method's section is shown, the other method's last result is
 * collapsed below ("Other method"). A switch generates nothing. The HairDeck
 * colour (POST /characters/{n}/hair/colour) and the placement (POST
 * /characters/{n}/hair/placement {forward_m, tilt_deg}, null = automatic)
 * only re-fit from the stored HairDeck result.
 *
 * The third method, Subtract (plan docs/superpowers/plans/2026-11-10-hair-subtract-method.md,
 * Task 2 — HairSubtract.tsx): the haired views -> one mesh of the haired
 * character -> the hair cut off it on the CPU -> fit. Its shape and shell
 * thickness (POST /characters/{n}/hair/subtract {shape, shell_mm}) sit beside
 * the preview and re-cut + re-fit from the stored source mesh.
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import {
  FitBlock, GarmentFailure, GarmentSteps, GateChips, RecordNumbers, RefitNotice, RunBadge, RunButton, RunStatusLine,
  StepState,
} from './GarmentSteps'
import type { ImageStepSpec } from './GarmentSteps'
import { EMPTY_TILE, ERROR_STYLE, ROW, WARN_STYLE, flatFit, num } from './garmentStyle'
import type { ChipSpec, GarmentRunBody } from './garmentStyle'
import { SubtractSettings, SubtractSteps } from './HairSubtract'
import { Model3DViewer } from './Model3DViewer'
import { RefImage } from './RefImage'
import { garmentRunning, runMark, runSlot, useGarment, useGarmentRun } from './useGarment'
import type { HairDeckPanel, HairInfo, HairMethod, HairPlacement, OtherMethodInfo } from './useGarment'

/** HairDeck's three image tiles: small, a click enlarges. */
const HAIRDECK_TILE = 140

/** The HairDeck method's steps (`garment_store.steps_for`). */
const HAIRDECK_ORDER = ['hairdeck', 'fit'] as const

const STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  haired: 'Haired views',
  ghost: 'Hair-only views',
  cutout: 'Cut-outs',
  mesh: 'Mesh',
  hairdeck: 'HairDeck',
  mesh_source: 'Source mesh',
  cut: 'Cut',
  fit: 'Fit',
}

const METHOD_LABELS: Record<HairMethod, string> = {
  edit_chain: 'Hair views → mesh',
  hairdeck: 'HairDeck',
  subtract: 'Subtract',
}

/** Every method in the selector's order. */
const METHODS: HairMethod[] = ['edit_chain', 'hairdeck', 'subtract']

const METHOD_HINTS: Record<HairMethod, string> = {
  edit_chain: 'Hair views → mesh renders the hair views and builds one mesh from them.',
  hairdeck: 'HairDeck makes hair cards from the profile picture in one step.',
  subtract: 'Subtract meshes the haired character once and cuts the hair off it against the bald base body.',
}

const CREATE_HINTS: Record<HairMethod, string> = {
  edit_chain: 'Renders the hair views, builds the mesh and fits it onto the base model.',
  hairdeck: 'Makes hair cards from the profile picture and fits them onto the base model.',
  subtract: 'Renders the haired views, meshes the haired character and cuts the hair off it.',
}

const HAIRDECK_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  refused: 'Refused',
  missing: 'Not run yet',
}

const HAIRDECK_TILES: Array<['input' | 'prep' | 'model_input', string]> = [
  ['input', 'Input (profile picture)'],
  ['prep', 'Prepared'],
  ['model_input', 'Model input'],
]

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Hair description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  fit_algorithm_updated: 'Fit algorithm updated',
  hairdeck_changed: 'Profile picture or HairDeck settings changed',
  colour_changed: 'Hair colour changed',
  placement_changed: 'Hair placement changed',
  shape_changed: 'Hair shape changed',
  shell_changed: 'Shell thickness changed',
}

const HAIRED_CHIPS: ChipSpec[] = [
  { key: 'body_xor', label: 'Body change', scale: 100, unit: '%', digits: 2 },
  { key: 'body_dRGB', label: 'Colour change', scale: 1, unit: '', digits: 2 },
  { key: 'chest_dRGB', label: 'Chest', scale: 1, unit: '', digits: 2 },
]

const GHOST_CHIPS: ChipSpec[] = [
  { key: 'top_dy', label: 'Top offset', scale: 1, unit: 'px', digits: 0 },
  { key: 'centre_dx', label: 'Centre offset', scale: 1, unit: 'px', digits: 1 },
  { key: 'w_ratio', label: 'Width ratio', scale: 1, unit: '', digits: 3 },
  { key: 'body_left', label: 'Body left', scale: 100, unit: '%', digits: 2 },
  // The correction applied before the gate (garment_images._register); the offsets
  // above are its residual. Fractions of the figure height / a factor.
  { key: 'reg_shift', label: 'Registration shift', scale: 100, unit: '%', digits: 2 },
  { key: 'reg_scale', label: 'Registration scale', scale: 1, unit: '', digits: 3 },
]

const FIT_CHIPS: ChipSpec[] = [
  { key: 'bib_cm2', label: 'Bib', scale: 1, unit: 'cm²', digits: 1 },
  { key: 'poke_share', label: 'Crown poke', scale: 100, unit: '%', digits: 2 },
  { key: 'scalp_uncovered_share', label: 'Scalp uncovered', scale: 100, unit: '%', digits: 1 },
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'largest_component_share', label: 'Largest part', scale: 100, unit: '%', digits: 1 },
  // Reported, not gated (R7): its plausible range depends on the hair length.
  { key: 'drop_below_chin_m', label: 'Drop below chin', scale: 100, unit: 'cm', digits: 1 },
]

const HAIRDECK_FIT_CHIPS: ChipSpec[] = [
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'icp_resid_p95_m', label: 'Head match (p95)', scale: 1000, unit: 'mm', digits: 1 },
  // Reported, not gated.
  { key: 'icp_scale', label: 'Scale', scale: 1, unit: '', digits: 3 },
  { key: 'cap_tris', label: 'Scalp cap triangles', scale: 1, unit: '', digits: 0 },
  { key: 'forward_m', label: 'Forward shift', scale: 1000, unit: 'mm', digits: 1 },
  { key: 'tilt_deg', label: 'Forward tilt', scale: 1, unit: '°', digits: 1 },
]

/** The hair chain's image steps in order, with the chips of their gates. */
const HAIR_IMAGE_STEPS: ImageStepSpec[] = [
  { step: 'haired', chips: HAIRED_CHIPS },
  { step: 'ghost', chips: GHOST_CHIPS },
  { step: 'cutout' },
]

function Swatch({ hex }: { hex: string }) {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block', width: 18, height: 18, borderRadius: 4, background: hex,
        border: '1px solid var(--border, #30363d)', verticalAlign: 'middle',
      }}
    />
  )
}

/** The HairDeck hair colour: automatic (the profile's named hair colour, else
 *  HairDeck's own) or a manual one; the last fit's colour distance (ΔE).
 *  Keyed by the server values, so the draft starts from them after a save. */
function HairColour({ colour, busy, running, onApply }: {
  colour: HairDeckPanel['colour']
  busy: boolean
  /** A hair run is active: the colour waits for it. */
  running: boolean
  onApply: (hex: string) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(colour.target || colour.profile?.hex || colour.auto || '#7f6248')
  const fitted = colour.fitted
  return (
    <>
      <div style={ROW}>
        <span className="ga-hint">{t('Automatic')}:</span>
        {colour.profile ? <Swatch hex={colour.profile.hex} /> : null}
        {colour.profile ? <span className="ga-hint">{`${t('Profile colour')} (${colour.profile.name})`}</span> : null}
        {colour.auto ? <Swatch hex={colour.auto} /> : null}
        <span className="ga-hint">{colour.auto ? t("HairDeck's own colours") : t('HairDeck has not run yet')}</span>
        <span className="ga-hint">·</span>
        <span className="ga-hint">{t('In use')}:</span>
        {colour.target ? <Swatch hex={colour.target} /> : null}
        <span className="ga-hint">
          {colour.target ? `${t('Manual')} ${colour.target}`
            : colour.profile ? `${t('Profile colour')} (${colour.profile.name})` : t('Automatic')}
        </span>
      </div>
      {fitted && fitted.delta_e_before != null ? (
        <div className="ga-hint">
          {t('Last fit')}: {fitted.source === 'profile' && !fitted.applied
            ? `${t("HairDeck's own colours kept")} (ΔE ${fitted.delta_e_before})`
            : `ΔE ${fitted.delta_e_before} → ${fitted.delta_e_after ?? '–'}`}
        </div>
      ) : null}
      <div style={ROW}>
        <input
          type="color"
          value={draft}
          disabled={busy}
          aria-label={t('Hair colour')}
          onChange={(e) => setDraft(e.target.value.toLowerCase())}
        />
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || draft === colour.target}
          onClick={() => onApply(draft)}
        >
          {t('Apply')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !colour.target}
          onClick={() => onApply('')}
        >
          {t('Reset to automatic')}
        </button>
        {running ? <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span> : null}
      </div>
      <div className="ga-hint">
        {t('A colour change re-fits the hair from the stored HairDeck result — HairDeck does not run again.')}
      </div>
    </>
  )
}

/** A placement draft field as a number; '' = automatic (null), NaN = invalid. */
function draftNumber(text: string, scale: number): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const n = Number(trimmed.replace(',', '.'))
  return Number.isFinite(n) ? n / scale : NaN
}

const draftText = (v: number | null, scale: number) => (v === null ? '' : String(Math.round(v * scale * 100) / 100))

/** The HairDeck placement: forward shift (shown in mm) and forward tilt (°).
 *  Empty = automatic. Keyed by the server values, so the drafts restart
 *  from them after a save. */
function HairPlacementForm({ placement, busy, running, onApply }: {
  placement: HairPlacement
  busy: boolean
  /** A hair run is active: the placement waits for it. */
  running: boolean
  onApply: (forward_m: number | null, tilt_deg: number | null) => void
}) {
  const { t } = useI18n()
  const [forward, setForward] = useState(draftText(placement.forward_m, 1000))
  const [tilt, setTilt] = useState(draftText(placement.tilt_deg, 1))
  const f = draftNumber(forward, 1000)
  const a = draftNumber(tilt, 1)
  const valid = (v: number | null, limit: number) => v === null || (!Number.isNaN(v) && Math.abs(v) <= limit)
  const ok = valid(f, placement.limits.forward_m) && valid(a, placement.limits.tilt_deg)
  const same = f === placement.forward_m && a === placement.tilt_deg
  const manual = placement.forward_m !== null || placement.tilt_deg !== null
  const fitted = placement.fitted
  const src = (s: string | null | undefined) => (s === 'manual' ? t('Manual') : t('Automatic'))
  return (
    <>
      <div style={ROW}>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Forward shift (mm)')}
          <input
            className="ga-input"
            type="number"
            step="1"
            style={{ width: 90 }}
            value={forward}
            placeholder={t('Auto')}
            disabled={busy}
            onChange={(e) => setForward(e.target.value)}
          />
        </label>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Forward tilt (°)')}
          <input
            className="ga-input"
            type="number"
            step="0.5"
            style={{ width: 90 }}
            value={tilt}
            placeholder={t('Auto')}
            disabled={busy}
            onChange={(e) => setTilt(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !ok || same}
          title={!ok ? t('Value out of range') : undefined}
          onClick={() => onApply(f, a)}
        >
          {t('Apply')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !manual}
          onClick={() => onApply(null, null)}
        >
          {t('Reset to automatic')}
        </button>
        {running ? <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span> : null}
      </div>
      {fitted && fitted.forward_m !== null && fitted.tilt_deg !== null ? (
        <div className="ga-hint">
          {t('Last fit')}: {t('Forward shift')} {(fitted.forward_m * 1000).toFixed(1)} mm ({src(fitted.forward_source)})
          {' · '}{t('Forward tilt')} {fitted.tilt_deg.toFixed(1)}° ({src(fitted.tilt_source)})
          {fitted.hairline_y !== null
            ? ` · ${t('Hairline')} ${fitted.hairline_y.toFixed(3)} m`
              + (fitted.hairline_target_y !== null ? ` (${t('target')} ${fitted.hairline_target_y.toFixed(3)} m)` : '')
            : ''}
        </div>
      ) : null}
      <div className="ga-hint">
        {t('Empty = automatic: a small forward shift and the tilt that brings the front hairline down to the brow line.')}
        {' '}
        {t('A placement change re-fits the hair from the stored HairDeck result — HairDeck does not run again.')}
      </div>
    </>
  )
}

/** The collapsed newest last result among the methods that are not selected. */
function OtherMethod({ other, method, limits }: {
  other: OtherMethodInfo | null
  method: HairMethod
  limits: HairInfo['limits']
}) {
  useClockSettings()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!other) {
    const others = METHODS.filter((m) => m !== method).map((m) => t(METHOD_LABELS[m])).join(', ')
    return (
      <div className="ga-hint">
        {t('Other method')} ({others}): {t('no result yet')}
      </div>
    )
  }
  const hairdeck = other.method === 'hairdeck'
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="ga-hint" style={{ cursor: 'pointer' }}>
        {t('Other method')} ({t(METHOD_LABELS[other.method])}): {t('last result')}
        {other.created_at ? ` · ${formatDateTime(other.created_at, clockSettings())}` : ''}
      </summary>
      {!other.on_current_base ? (
        <div className="ga-hint" style={WARN_STYLE}>{t('Fitted on an older base model')}</div>
      ) : null}
      {other.colour?.target ? (
        <div style={ROW}>
          <span className="ga-hint">{t('Hair colour')}:</span>
          <Swatch hex={other.colour.target} />
          <span className="ga-hint">{other.colour.target}</span>
        </div>
      ) : null}
      <GateChips
        specs={hairdeck ? HAIRDECK_FIT_CHIPS : FIT_CHIPS}
        record={other.metrics}
        limits={hairdeck ? limits.hairdeck_fit : limits.fit}
      />
      {open && other.preview_url ? (
        <Model3DViewer key={other.preview_url} url={other.preview_url} format="glb" height={300}
          freshness={other.preview_freshness} />
      ) : null}
      <div className="ga-hint">
        {t('Select this method above to use it again — its files stay, the switch generates nothing.')}
      </div>
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

  // Store the colour, then re-fit (only the fit runs: the HairDeck result is cached).
  const applyColour = useCallback(
    (hex: string) => call(`/characters/${enc}/hair/colour`, { hex }, () => (
      itemId && info?.method === 'hairdeck'
        ? apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
        : undefined
    )),
    [call, enc, info?.method, itemId],
  )

  // Store the placement, then re-fit (like the colour: only the fit runs).
  const applyPlacement = useCallback(
    (forward_m: number | null, tilt_deg: number | null) => call(
      `/characters/${enc}/hair/placement`, { forward_m, tilt_deg }, () => (
        itemId && info?.method === 'hairdeck'
          ? apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
          : undefined
      )),
    [call, enc, info?.method, itemId],
  )

  // Store shape + shell thickness, then re-cut + re-fit when the source mesh is there (CPU only — a run
  // without it would start the source mesh job, so it waits for the next run).
  const applySubtract = useCallback(
    (shape: '' | 'cut' | 'shell', shellMm: number | null) => call(
      `/characters/${enc}/hair/subtract`, { shape, shell_mm: shellMm }, () => (
        itemId && info?.method === 'subtract' && info.garment?.steps.mesh_source?.status === 'accepted'
          ? apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
          : undefined
      )),
    [call, enc, info?.garment?.steps.mesh_source?.status, info?.method, itemId],
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
  const hd = info.hairdeck
  const isHairDeck = info.method === 'hairdeck'
  const isSubtract = info.method === 'subtract'
  const noHair = !!garment && !garment.served_fsig && !garment.running_step && fit?.status !== 'accepted'
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }

  const editChainSection = (
    <GarmentSteps
      garment={garment}
      imageSteps={HAIR_IMAGE_STEPS}
      stepLabels={STEP_LABELS}
      limits={limits}
      fitChips={FIT_CHIPS}
      busy={busy}
      onRun={onRun}
      lowFailedText="Distance tier failed — the full hair is used"
      compact
      feedback={feedback}
    />
  )

  const hairdeckSection = hd ? (
    <>
      <div className="ga-fieldset-title">{t('HairDeck')}</div>
      <div style={{ display: 'flex', gap: 6 }}>
        {HAIRDECK_TILES.map(([key, tileLabel]) => {
          const img = hd.images[key]
          // A character with facial hair sends HairDeck the picture with the beard removed.
          const label = key === 'input' && hd.input_source === 'beard_free' ? 'Input (beard removed)' : tileLabel
          return (
            <div key={key} style={{ flex: 1, minWidth: 0 }}>
              <div className="ga-hint">{t(label)}</div>
              {img ? (
                <RefImage key={img.url} src={img.url} height={HAIRDECK_TILE} label={t(label)} meta={img} compact />
              ) : (
                <div className="ga-hint" style={{ ...EMPTY_TILE, height: HAIRDECK_TILE }}>
                  {key === 'input' ? t('No profile picture') : t('No render yet')}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div style={ROW}>
        <RunBadge mark={runMark(feedback, garment, HAIRDECK_ORDER, 'hairdeck')} />
        <span className="ga-hint">
          {t(HAIRDECK_STATUS[hd.status] || hd.status)}
          {hd.attempt ? ` · ${t('Attempt')} ${hd.attempt}` : ''}
          {hd.seed != null ? ` · ${t('Seed')} ${hd.seed}` : ''}
          {hd.seed != null && hd.seeds_tried > 0 ? ` (${t('of {n} tried').replace('{n}', String(hd.seeds_tried))})` : ''}
          {hd.backend ? ` · ${hd.backend}` : ''}
          {hd.created_at ? ` · ${formatDateTime(hd.created_at, clockSettings())}` : ''}
        </span>
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'hairdeck' })}
          disabled={busy || !garment || !hd.images.input}
          title={!hd.images.input ? t('Set a profile picture first') : undefined}
          onClick={() => onRun({ step: 'hairdeck', force: true })}
          label={t('Regenerate hair (HairDeck)')}
        />
      </div>
      {hd.notes.length ? <div className="ga-hint">{t('Notes')}: {hd.notes.join(' · ')}</div> : null}
      {hd.status === 'refused' && hd.error ? <div className="ga-hint" style={ERROR_STYLE}>{hd.error}</div> : null}
      {garment ? <StepState garment={garment} step="hairdeck" /> : null}

      <FitBlock garment={garment} chips={HAIRDECK_FIT_CHIPS} limits={limits.hairdeck_fit}
        ready={hd.status === 'accepted'} busy={busy} onRun={onRun}
        lowFailedText="Distance tier failed — the full hair is used"
        feedback={feedback} order={HAIRDECK_ORDER} />
      {hd.attempts.length ? (
        <details>
          <summary className="ga-hint" style={{ cursor: 'pointer' }}>
            {t('Refused fit attempts')} ({hd.attempts.length})
          </summary>
          {hd.attempts.map((g, i) => (
            <RecordNumbers key={i} label={`${t('Attempt')} ${num(g.attempt) ?? i + 1}`} record={flatFit(g)} />
          ))}
        </details>
      ) : null}
    </>
  ) : null

  const subtractSection = (
    <SubtractSteps garment={garment} limits={limits} hairedChips={HAIRED_CHIPS} fitChips={FIT_CHIPS}
      busy={busy} onRun={onRun} feedback={feedback} />
  )

  // Shape and shell thickness re-cut + re-fit the hair: beside the preview.
  const sub = info.subtract
  const subtractLook = isSubtract && sub ? (
    <SubtractSettings
      key={`${sub.shape_override}|${sub.shell_mm}`}
      settings={sub}
      busy={busy}
      running={garmentRunning(info)}
      sourceReady={garment?.steps.mesh_source?.status === 'accepted'}
      onApply={(shape, mm) => { void applySubtract(shape, mm) }}
    />
  ) : null

  // Colour and placement re-fit the hair: they sit beside the preview.
  const hairdeckLook = hd && isHairDeck ? (
    <>
      <div className="ga-fieldset-title">{t('Hair colour')}</div>
      <HairColour
        key={`${hd.colour.target || ''}|${hd.colour.profile?.hex || ''}|${hd.colour.auto || ''}`}
        colour={hd.colour}
        busy={busy}
        running={garmentRunning(info)}
        onApply={(hex) => { void applyColour(hex) }}
      />

      {hd.placement ? (
        <>
          <div className="ga-fieldset-title">{t('Hair placement')}</div>
          <HairPlacementForm
            key={`${hd.placement.forward_m ?? ''}|${hd.placement.tilt_deg ?? ''}`}
            placement={hd.placement}
            busy={busy}
            running={garmentRunning(info)}
            onApply={(forward, tilt) => { void applyPlacement(forward, tilt) }}
          />
        </>
      ) : null}
    </>
  ) : null

  return (
    <div className="ga-split ga-split-hair">
      <div className="ga-split-col">
      <div className="ga-fieldset-title">{t('Hair method')}</div>
      <div style={ROW}>
        <select
          className="ga-input"
          style={{ width: 'auto', maxWidth: '100%' }}
          value={info.method_source === 'character' ? info.method : ''}
          disabled={busy}
          title={garmentRunning(info) ? t('Wait for the running hair job') : undefined}
          aria-label={t('Hair method')}
          onChange={(e) => { void setMethod(e.target.value as '' | HairMethod) }}
        >
          <option value="">{t('World default')} ({t(METHOD_LABELS[info.world_method])})</option>
          {METHODS.map((m) => <option key={m} value={m}>{t(METHOD_LABELS[m])}</option>)}
        </select>
        <span className="ga-hint">{t(METHOD_HINTS[info.method] || METHOD_HINTS.edit_chain)}</span>
        {garmentRunning(info) ? (
          <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span>
        ) : null}
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

      {!info.item_id ? (
        info.description ? (
          <>
            {/* No preview yet: the subtract shape is chosen here, before the first run. */}
            {subtractLook}
            <div style={ROW}>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={posting} onClick={() => { void create() }}>
                {t('Create hair')}
              </button>
              <span className="ga-hint">{t(CREATE_HINTS[info.method] || CREATE_HINTS.edit_chain)}</span>
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

          <RefitNotice garment={garment} feedback={feedback} busy={busy} onRun={onRun} />

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
            {isHairDeck ? hairdeckSection : isSubtract ? subtractSection : editChainSection}
          </div>
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
            {hairdeckLook}
            {subtractLook}
            <OtherMethod other={info.other} method={info.method} limits={limits} />
          </div>
        </>
      ) : null}
    </div>
  )
}
