/**
 * FieldHairstyles — the character tab "Hairstyles" (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
 * Task 14, rebuilt in Task UI4 to the user's checklist for every character tab). Hairstyles are items: several
 * owned, one worn; the mode (`hairdeck` · `haar` · `body`) lives on the item.
 *
 * Layout (one screen, no scrolling at 1600×900):
 * - left: the owned hairstyles (GET /characters/{c}/hairstyles — worn first), one traffic light each with its
 *   reason on mouse-over, "Wear" with what the Build after it costs (`wear`: automatic → "Wear · Build 9 hub
 *   jobs", else "Wear · no job now"), "New hairstyle" (a createPortal dialog; starts nothing);
 * - the selected hairstyle (GET /characters/{c}/hair?item_id=, polled while a run goes — useGarment):
 *   - its flow head: "Run all" with the job count, skipping what is current ("Everything is current" at 0;
 *     POST …/garments/{item}/run {}); a body hairstyle's flow belongs to the Figure tab — only a link to it;
 *   - the 3D preview (the hair fitted on the plain body, "Built <time>" in its corner, framed on the head) with
 *     the settings that change it BESIDE it (HairLiveControls): placement, colour, Swing / Stiffness — each acts
 *     live while dragged (a vertex map, a colour tint, the strands' stiffness) and is saved on its own, nothing
 *     runs; the forward shift shows a centimetre ruler and the shift itself in the preview while hovered;
 *   - the preview runs the game's per-strand sim on the previewed fit's strand record (`preview_strands_url`,
 *     strand-hair spec § 6.2.5, ruling H-R2): a drag turns the figure so the hair reacts, Sway / Walk / Turn /
 *     Stop beside the viewer; with Swing off, or without a record, the hair stays still and says why;
 *   - sub-tabs: Steps (one row per step: traffic light, the reason in plain words, its single button that redoes
 *     the step even when current, with its cost), Settings (mode, the text — saved on its own, nothing runs, what
 *     became due written beside it —, colour and placement facts) and HairDeck images (three small tiles, a click
 *     enlarges) or, for HAAR hair, HAAR variants (strand-hair spec § 6.3.4: one small tile per seed, a click
 *     enlarges; its light with the reason, the numbers on mouse-over; "In use" or "Use this — no hub job, CPU
 *     refit", which saves the pick and runs nothing).
 * HAAR without a routed backend (occasion hair_strands) says so beside Run all with a link to the routing and
 * spends nothing: Run all and the strands step are off.
 * A temporary NPC has no figure: the list and the settings stay, no step runs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { STRAND_RECORD_VERSION } from '@anima/scene-render'
import type { HairStrandRecord } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { stampLabel } from './freshnessText'
import { GateChips, RecordNumbers, RunButton, RunStatusLine } from './GarmentSteps'
import { EMPTY_TILE, HAIRDECK_FIT_CHIPS, HAIR_STEP_LABELS, WARN_STYLE, flatFit, num } from './garmentStyle'
import type { GarmentRunBody } from './garmentStyle'
import { HairLiveControls } from './HairLiveControls'
import type { HairDrafts } from './HairLiveControls'
import { FigureBuildLine } from './HairstyleParts'
import {
  HAAR_NO_ROUTE, ROUTING_URL, colourTint, fittedPlacement, haarRunCost, haarVariantRows, hairStepRows, jobsLabel,
  listLight, listReason, newHairstyleText, placementIdentity, placementMap, placementRuler, standardHairText,
  strandPreviewState, variantAction, wearButton,
} from './hairstylesModel'
import type { HaarPanel, Light, Vec3, VariantLight } from './hairstylesModel'
import { Model3DViewer } from './Model3DViewer'
import { StepLight, StepRowView } from './StepRows'
import { LIGHT_COLOR, PANEL } from './stepStyle'
import { RefImage } from './RefImage'
import {
  ESTIMATE_NOTE, HAIR_MODES, HAIR_MODE_HINTS, HAIR_MODE_LABELS, hairModeDisabled, hairstyleActions, hairstyleRows,
  newHairstyleDisabled,
} from './figureModel'
import type { HairMode, Hairstyle, HairstylesPayload } from './figureModel'
import { garmentRunning, runSlot, useGarment, useGarmentRun } from './useGarment'
import type { HairInfo } from './useGarment'

/** GET …/hairstyles with the Wear estimate (Task UI4). */
type HairstyleEntry = Hairstyle & {
  wear?: { hub_jobs: number | null; automatic: boolean; note: string } | null
  due?: string[]
}
type HairstylesList = Omit<HairstylesPayload, 'hairstyles'> & {
  hairstyles: HairstyleEntry[]
  pipeline?: boolean
  auto_build?: boolean
}
/** GET …/hair with the Task UI4 additions. */
type HairDetail = HairInfo & {
  step_jobs?: Record<string, number>
}

const VIEWER_HEIGHT = 580
/** The "New hairstyle" dialog: description + mode (every mode the server lists as built). Create starts
 *  nothing; the new hairstyle is not worn (except a character's first one — the server decides).
 *  Ruling A54: the description opens with the standard text (`standard`, the Appearance's hair text the server
 *  would use for an empty one), editable before Create; "Reset to standard text" brings it back. Without a
 *  standard text the field stays empty and the server's message stands under it before Create. */
function NewHairstyleDialog({ character, defaultMode, built, standard, onClose, onCreated }: {
  character: string
  defaultMode: HairMode
  built: readonly string[]
  standard: string
  onClose: () => void
  onCreated: (itemId: string) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [description, setDescription] = useState(standard)
  const [mode, setMode] = useState<HairMode>(hairModeDisabled(defaultMode, built) ? 'body' : defaultMode)
  const [posting, setPosting] = useState(false)
  const reason = newHairstyleDisabled(description, mode, built)
  const field = newHairstyleText(standard, description)
  const create = async () => {
    if (reason || posting) return
    setPosting(true)
    try {
      const d = await apiPost<{ item_id: string }>(`/characters/${encodeURIComponent(character)}/hairstyles`,
        { description: description.trim(), mode })
      onCreated(d.item_id)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('New hairstyle')}
        style={{ maxWidth: 560 }}>
        <div className="ga-modal-header"><h3>{t('New hairstyle')}</h3></div>
        <div className="ga-modal-body" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 170px', gap: 10 }}>
          <div className="ga-form-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {t('Description')}
              <textarea className="ga-input" rows={3} value={description} disabled={posting}
                placeholder={t('e.g. shoulder-length wavy auburn hair with a side parting')}
                onChange={(e) => setDescription(e.target.value)} />
            </label>
            {field.hint ? <span className="ga-hint" role="note" style={WARN_STYLE}>{t(field.hint)}</span> : null}
            {field.fromStandard ? <span className="ga-hint">{t('Standard text from the hair in Appearance')}</span> : null}
            {field.reset ? (
              <button type="button" disabled={posting} title={standard}
                style={{ alignSelf: 'flex-start', background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                  color: 'var(--accent, #58a6ff)', textDecoration: 'underline', fontSize: '0.95em' }}
                onClick={() => setDescription(standard)}>
                {t('Reset to standard text')}
              </button>
            ) : null}
          </div>
          <label className="ga-form-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Mode')}
            <select className="ga-input" value={mode} disabled={posting} aria-label={t('Hair mode')}
              onChange={(e) => setMode(e.target.value as HairMode)}>
              {HAIR_MODES.map((m) => (
                <option key={m} value={m} disabled={!!hairModeDisabled(m, built)}>
                  {t(HAIR_MODE_LABELS[m])}{hairModeDisabled(m, built) ? ` — ${t(hairModeDisabled(m, built) || '')}` : ''}
                </option>
              ))}
            </select>
            <span className="ga-hint">{t(HAIR_MODE_HINTS[mode])}</span>
          </label>
          <span className="ga-hint" style={{ gridColumn: '1 / -1' }}>
            {t('Creating runs nothing and wears nothing — Wear it, then the Build makes it.')}
          </span>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" className="ga-btn" disabled={posting} onClick={onClose}>{t('Cancel')}</button>
            <button type="button" className="ga-btn ga-btn-primary" disabled={!!reason || posting}
              onClick={() => { void create() }}>{t('Create')}</button>
          </div>
          {reason && !field.hint ? <span className="ga-hint">{t(reason)}</span> : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** "No backend for occasion hair_strands — …" with the routing page as a link: HAAR spends nothing until one is set. */
function NoRouteLine() {
  const { t } = useI18n()
  return (
    <span className="ga-hint" style={{ ...WARN_STYLE, display: 'inline-block' }}>
      {t(HAAR_NO_ROUTE)} — <a href={ROUTING_URL} target="_blank" rel="noreferrer"
        style={{ color: 'var(--accent, #58a6ff)' }}>{t('open the routing')}</a>.{' '}
      {t('Nothing is spent until one is set.')}
    </span>
  )
}

const VARIANT_LIGHT: Record<VariantLight, Light> = { ok: 'green', bad: 'red', wait: 'grey' }

/** The "HAAR variants" sub-tab (strand-hair spec § 6.3.4): one small tile per seed in a 3-column grid, a click
 *  enlarges (RefImage); its light with the reason in plain words, the numbers on mouse-over; "In use", or "Use this
 *  — no hub job, CPU refit" which saves the pick (POST …/hair/haar-seed) and runs nothing — the Fit row then reads
 *  due. "Automatic" clears the pick (the best passing variant). */
function HaarVariants({ character, itemId, panel, busy, onSaved }: {
  character: string
  itemId: string
  panel: HaarPanel
  busy: boolean
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [posting, setPosting] = useState(false)
  const [saved, setSaved] = useState(false)
  const rows = haarVariantRows(panel, t)
  const use = async (seed: number | null) => {
    if (posting) return
    setPosting(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/hair/haar-seed`, { item_id: itemId, seed })
      setSaved(true)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onSaved()
    }
  }
  if (!rows.length) {
    return (
      <div className="ga-hint" style={{ ...EMPTY_TILE, height: 110, padding: 12, textAlign: 'center' }}>
        {t('No variants yet — Run all makes {n} from the hairstyle text.').replace('{n}', String(panel.jobs))}
      </div>
    )
  }
  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        {rows.map((r) => {
          const action = variantAction(r, t)
          const hover = [r.reason, r.numbers].filter(Boolean).join('\n')
          return (
            <div key={r.seed} style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0, padding: 4,
              borderRadius: 6, border: `1px solid ${r.inUse ? 'var(--accent, #58a6ff)' : 'var(--border, #30363d)'}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={hover}>
                <StepLight light={VARIANT_LIGHT[r.light]} />
                <strong style={{ fontSize: 12 }}>{t('Seed')} {r.seed}</strong>
              </div>
              {r.tileUrl ? (
                <RefImage key={r.tileUrl} src={r.tileUrl} height={92} compact
                  label={`${t('HAAR variant')} ${r.seed} — ${t('front | back')}`} />
              ) : (
                <div className="ga-hint" style={{ ...EMPTY_TILE, height: 92, fontSize: 10, textAlign: 'center' }}>
                  {t('No picture yet — the next fit renders it')}
                </div>
              )}
              <div className="ga-hint" title={hover} style={{ fontSize: 11, lineHeight: 1.25, overflowWrap: 'anywhere',
                color: r.light === 'bad' ? LIGHT_COLOR.red : undefined }}>
                {r.reason}
              </div>
              {action.button ? (
                <button type="button" className="ga-btn ga-btn-sm" disabled={busy || posting}
                  title={t('Saves this variant as the pick — nothing runs; the Fit row then reads due and its Re-fit applies it on the CPU (no hub job)')}
                  onClick={() => { void use(r.seed) }}>{action.label}</button>
              ) : (
                <span className="ga-hint" style={{ fontSize: 11, color: r.inUse ? LIGHT_COLOR.blue : LIGHT_COLOR.yellow }}>
                  {action.label}
                </span>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {panel.picked !== null ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy || posting}
            title={t('Clears the pick — nothing runs; the best passing variant is used after the Re-fit (no hub job)')}
            onClick={() => { void use(null) }}>{t('Automatic')}</button>
        ) : null}
        <span className="ga-hint">
          {panel.picked !== null ? t('Picked: seed {seed}.').replace('{seed}', String(panel.picked))
            : t('Automatic: the best passing variant is used.')}
        </span>
        {saved ? <span className="ga-hint" style={{ color: LIGHT_COLOR.yellow }}>{t('Saved — Re-fit applies it (no hub job)')}</span> : null}
      </div>
      <div className="ga-hint">
        {t('Click a picture to enlarge it (front | back). The numbers are on mouse-over.')}{' '}
        {panel.next_seeds.length ? t('The HAAR strands step makes {n} more (seeds {seeds}).')
          .replace('{n}', String(panel.jobs)).replace('{seeds}', panel.next_seeds.join(', ')) : ''}
      </div>
    </>
  )
}

/** The hairstyle's text, saved on its own (rule: saving runs nothing); what the save made due is written beside it
 *  (POST …/hair/description answers the Run all estimate after the save). */
function HairstyleText({ character, itemId, mode, text, busy, onSaved }: {
  character: string
  itemId: string
  mode: HairMode
  text: string
  busy: boolean
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [draft, setDraft] = useState<string | null>(null)
  const [posting, setPosting] = useState(false)
  const [note, setNote] = useState('')
  const value = draft ?? text
  const changed = draft !== null && draft.trim() !== text.trim()
  const save = async () => {
    if (!changed || posting || !value.trim()) return
    setPosting(true)
    try {
      const d = await apiPost<{ run?: { steps: string[]; hub_jobs: number | null; cpu_fits?: number } | null }>(
        `/characters/${encodeURIComponent(character)}/hair/description`, { item_id: itemId, description: value })
      const run = d.run ?? null
      const stepName = (s: string) => t(HAIR_STEP_LABELS[s] || s)
      setNote(mode === 'body' ? t('Saved — nothing ran; the Figure tab’s Build makes it.')
        : !run ? t('Saved — nothing ran.')
          : !run.steps.length ? t('Saved — nothing ran, nothing is due.')
            : t('Saved — nothing ran. Now due: {steps} ({cost}).')
              .replace('{steps}', run.steps.map(stepName).join(' → '))
              .replace('{cost}', mode === 'haar' ? haarRunCost(run, t) : jobsLabel(run.hub_jobs, t)))
      setDraft(null)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onSaved()
    }
  }
  return (
    <div style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 3 }}>
      <label className="ga-form-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {mode === 'haar' ? t('Text (the HAAR prompt)') : t('Description')}
        <textarea className="ga-input" rows={2} value={value} disabled={busy || posting}
          onChange={(e) => { setDraft(e.target.value); setNote('') }} />
      </label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || posting || !changed || !value.trim()}
          title={t('Saves the text — nothing runs')} onClick={() => { void save() }}>{t('Save')}</button>
        {changed ? <button type="button" className="ga-btn ga-btn-sm" disabled={posting}
          onClick={() => setDraft(null)}>{t('Discard')}</button> : null}
        <span className="ga-hint" style={{ color: note ? LIGHT_COLOR.yellow : undefined }}>
          {note || (changed ? (mode === 'haar'
            ? t('Saving runs nothing; then the strands are due — Run all makes 3 new variants (3 hub jobs).')
            : t('Saving runs nothing.')) : t('Saved on Save — nothing runs.'))}
        </span>
      </div>
    </div>
  )
}

/** The selected hairstyle: flow head, preview with its live settings beside it, and the sub-tabs. */
function HairstyleDetail({ character, entry, built, onChanged, onRunEnded, onOpenFigure }: {
  character: string
  entry: HairstyleEntry
  /** The modes the server lists as built (GET …/hairstyles `built_modes`). */
  built: readonly string[]
  /** The mode was saved: the list and the Build line reload. */
  onChanged: () => void
  /** A run of this hairstyle ended: the list (its light) reloads. */
  /** Reloads the list (a run ended, a pick or a text was saved): no Build line, unlike `onChanged`. */
  onRunEnded: () => void
  onOpenFigure?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const itemId = entry.id
  const { info, startPoll } = useGarment<HairDetail>(
    `/characters/${enc}/hair?item_id=${encodeURIComponent(itemId)}`)
  const { feedback, start, cancel } = useGarmentRun(character, itemId, info, startPoll)
  const [posting, setPosting] = useState(false)
  const [sub, setSub] = useState<'steps' | 'settings' | 'images'>('steps')
  const [drafts, setDrafts] = useState<HairDrafts>({ placement: null, colour: null, stiffness: null })
  const [ruler, setRuler] = useState(false)
  const [side, setSide] = useState(false)
  const [modeSaved, setModeSaved] = useState(0)
  const wasRunning = useRef(false)
  const runningNow = !!info && garmentRunning(info)
  useEffect(() => {
    if (wasRunning.current && !runningNow) onRunEnded()
    wasRunning.current = runningNow
  }, [runningNow, onRunEnded])
  const onDraft = useCallback((d: HairDrafts) => setDrafts(d), [])
  const reload = useCallback(() => startPoll(300), [startPoll])

  const hd = info?.hairdeck ?? null
  const haarPanel = info?.haar ?? null
  const isHaar = info?.method === 'haar'
  const garment = info?.garment ?? null
  // The live previews: placement (vertex map about the fit's pivot), colour (tint), stiffness (spring frequency).
  const pivot = (hd?.placement as unknown as { pivot?: Vec3 | null } | undefined)?.pivot ?? null
  const headCapsule = info?.collision?.capsules?.find((c) => c.region === 'head')
  const halfWidth = headCapsule?.r ?? 0.08
  const fitted = hd ? fittedPlacement(hd.placement) : null
  const meshAdjust = useMemo(() => {
    if (!hd || !info?.item_id) return null
    // HAAR hair has no placement; its colour in use is the manual one, else the named one, else the atlas white.
    const map = !isHaar && pivot && fitted && drafts.placement && !placementIdentity(fitted, drafts.placement)
      ? placementMap(pivot, fitted, drafts.placement, pivot[0], halfWidth) : null
    const shown = isHaar ? hd.colour.target || hd.colour.profile?.hex || '#ffffff'
      : hd.colour.fitted?.applied === false ? hd.colour.auto
        : hd.colour.fitted?.target || hd.colour.target || hd.colour.profile?.hex || hd.colour.auto
    const tint = drafts.colour ? colourTint(shown, drafts.colour) : null
    return map || tint ? { match: `garment_hair_${info.item_id}`, map, tint } : null
  }, [hd, isHaar, info?.item_id, pivot, fitted?.forward_m, fitted?.tilt_deg, fitted?.width_scale, drafts.placement, // eslint-disable-line react-hooks/exhaustive-deps
    drafts.colour, halfWidth])
  // The per-strand preview (strand-hair spec § 6.2.5): the previewed fit's record, fetched once per previewed fit
  // while Swing is on; the dragged Stiffness goes to the sim live.
  const strandState = strandPreviewState(info ?? {}, hd?.chains?.swing ?? true)
  const strandKey = strandState === 'swings' && info?.preview_strands_url
    ? `${info.preview_strands_url}|${garment?.preview_url ?? ''}` : ''
  const [strandFetch, setStrandFetch] = useState<{ key: string; record: HairStrandRecord | null } | null>(null)
  useEffect(() => {
    if (!strandKey) return
    let gone = false
    const url = strandKey.slice(0, strandKey.indexOf('|'))
    apiGet<HairStrandRecord>(url)
      .then((record) => { if (!gone) setStrandFetch({ key: strandKey, record: record?.version === STRAND_RECORD_VERSION ? record : null }) })
      .catch(() => { if (!gone) setStrandFetch({ key: strandKey, record: null }) })
    return () => { gone = true }
  }, [strandKey])
  const strandRecord = strandFetch?.key === strandKey ? strandFetch.record : null
  const strandStiffness = drafts.stiffness ?? hd?.chains?.stiffness ?? 1
  const strandHair = useMemo(() => (strandRecord ? { record: strandRecord, stiffness: strandStiffness } : null),
    [strandRecord, strandStiffness])
  const strandIssue = strandState !== 'swings' || strandRecord ? null
    : strandFetch?.key === strandKey ? t('No strand record for this fit — the hair stays still.')
      : t('Loading the strands…')
  const hairlineY = hd?.placement.fitted?.hairline_y ?? (pivot ? pivot[1] + 0.04 : null)
  const polylines = useMemo(() => (ruler && pivot && hairlineY !== null
    ? placementRuler(pivot, pivot[0] + halfWidth + 0.03, hairlineY,
      drafts.placement?.forward_m ?? fitted?.forward_m ?? 0)
    : undefined), [ruler, pivot, hairlineY, halfWidth, drafts.placement?.forward_m, fitted?.forward_m])
  const focus = useMemo(() => (pivot ? { center: [pivot[0], pivot[1] - 0.04, pivot[2] - 0.02] as Vec3,
    radius: 0.24, side } : null), [pivot, side])

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) return <div className="ga-hint">{t('Hairstyles are for humanoid characters only.')}</div>

  const mode: HairMode = (HAIR_MODES as string[]).includes(info.method) ? info.method as HairMode : 'hairdeck'
  const running = garmentRunning(info)
  const busy = posting || feedback.pending !== null || running
  const when = (s: string | null | undefined) => stampLabel(s)
  const rows = hairStepRows(info, t, when)
  const actions = hairstyleActions(mode, info.run, t)
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  const setMode = async (next: HairMode) => {
    if (hairModeDisabled(next, built) || next === mode || posting) return
    setPosting(true)
    try {
      await apiPost(`/characters/${enc}/hair/method`, { method: next, item_id: itemId })
      setModeSaved((v) => v + 1)
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      startPoll(300)
    }
  }
  const title = `${entry.name || entry.id} · ${t(HAIR_MODE_LABELS[mode])}`
  // HAAR without a routed backend: the strands cannot be made — said beside Run all, nothing is spent.
  const noRoute = mode === 'haar' && haarPanel?.route?.routed === false
  const strandsDue = !!info.run?.steps.includes('haar')
  const haarCost = mode === 'haar' ? haarRunCost(info.run, t) : ''
  const fitted3d = mode === 'hairdeck' || mode === 'haar'
  const preview = fitted3d && garment?.preview_url ? (
    <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={VIEWER_HEIGHT}
      sideToolbar subject="figure" freshness={garment.preview_freshness} builtAt={garment.preview_built_at}
      alphaCutoff={info.alpha_cutoff} collision={info.collision} meshAdjust={meshAdjust} polylines={polylines} focus={focus}
      strandHair={strandHair}
      strandNote={strandState === 'swing_off' ? t('Swing is off — the hair stays still.') : strandIssue || undefined}
      motionToolbar={hd ? (
        <HairLiveControls character={character} itemId={itemId} mode={mode === 'haar' ? 'haar' : 'hairdeck'} hd={hd}
          info={info} busy={busy || !info.pipeline} previewSwings={strandState} strandIssue={strandIssue}
          onDraft={onDraft} onRuler={setRuler} onSaved={reload} />
      ) : undefined} />
  ) : mode === 'body' && info.plain && info.body_url ? (
    <Model3DViewer key={info.body_url} url={info.body_url} format="glb" height={VIEWER_HEIGHT}
      builtAt={info.body_built_at} subject="figure" />
  ) : (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
      <div className="ga-hint" style={{ ...EMPTY_TILE, flex: '0 1 440px', height: VIEWER_HEIGHT, padding: 16,
        textAlign: 'center' }}>
        {!info.pipeline && fitted3d ? t('No 3D preview — a temporary NPC has no figure.')
          : mode === 'hairdeck'
            ? t('No fitted hair yet — Run all makes it ({cost}).').replace('{cost}', jobsLabel(info.run?.hub_jobs ?? null, t))
            : mode === 'haar'
              ? (noRoute && strandsDue ? t('No fitted hair yet — nothing can be made until a backend is routed (see above).')
                : t('No fitted hair yet — Run all makes it ({cost}).').replace('{cost}', haarCost || jobsLabel(info.run?.hub_jobs ?? null, t)))
              : t('Its hair is in the body: the plain body is rendered with it when it is worn and built — the Figure tab shows the figure.')}
      </div>
      {fitted3d && hd && info.pipeline ? (
        <aside className="ga-model3d-toolbar" style={{ flex: '0 0 220px' }}>
          <HairLiveControls character={character} itemId={itemId} mode={mode === 'haar' ? 'haar' : 'hairdeck'} hd={hd}
            info={info} busy={busy} previewSwings="no_preview" onDraft={onDraft} onRuler={setRuler} onSaved={reload} />
        </aside>
      ) : null}
    </div>
  )

  const fit = garment?.steps.fit
  const fitRecord = fit && fit.status !== 'missing' ? fit.metrics : null
  const hairdeckRow = rows.find((r) => r.id === 'hairdeck')
  const fitRow = rows.find((r) => r.id === 'fit')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
      {/* The flow head: what this hairstyle is, its Run all with the count (or the tab its flow belongs to). */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', minHeight: 30 }}>
        <strong style={{ fontSize: 14 }}>{title}</strong>
        {entry.worn ? <span className="ga-hint">{t('Worn')}</span> : null}
        {actions.runAll && info.pipeline ? (
          <>
            <RunButton feedback={feedback} slot="all" primary
              disabled={busy || !garment || actions.runAll.disabled || (noRoute && strandsDue)}
              title={[t('Runs every step that is missing or out of date, in order, and skips what is current'),
                haarCost || info.run?.note || ''].filter(Boolean).join(' — ')}
              onClick={() => onRun({}, 'all')} label={actions.runAll.label} />
            {haarCost && !(noRoute && strandsDue) ? <span className="ga-hint">{haarCost}</span> : null}
            {noRoute && strandsDue ? <NoRouteLine /> : null}
            {info.run?.hub_jobs && !(noRoute && strandsDue) ? <span className="ga-hint">{t(ESTIMATE_NOTE)}</span> : null}
          </>
        ) : null}
        {mode === 'body' ? (
          <span className="ga-hint">{t('Its flow is the Figure tab’s Build.')}</span>
        ) : null}
        {mode === 'body' && onOpenFigure ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenFigure}>{t('Open Figure tab')}</button>
        ) : null}
        {fitted3d && garment?.preview_url ? (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
            <button type="button" className={`ga-btn ga-btn-sm${side ? '' : ' ga-btn-primary'}`}
              onClick={() => setSide(false)}>{t('Front view')}</button>
            <button type="button" className={`ga-btn ga-btn-sm${side ? ' ga-btn-primary' : ''}`}
              title={t('Forward shift and tilt read best from the side')}
              onClick={() => setSide(true)}>{t('Side view')}</button>
          </span>
        ) : null}
      </div>
      {!info.pipeline ? (
        <div className="ga-hint" style={WARN_STYLE}>{t('A temporary NPC has no figure — its hairstyles are not built.')}</div>
      ) : null}
      {fitted3d ? (
        <RunStatusLine garment={garment} feedback={feedback} stepLabels={HAIR_STEP_LABELS} bare
          onCancel={() => { void cancel() }} />
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 680px) minmax(300px, 1fr)', gap: 14,
        alignItems: 'start' }}>
        <div className="ga-model3d-fit" style={{ minWidth: 0 }}>{preview}</div>
        <div style={PANEL}>
          <nav className="ga-subtabs" style={{ margin: 0 }}>
            {(['steps', 'settings', ...(fitted3d ? ['images'] as const : [])] as const).map((id) => (
              <button key={id} type="button" className={`ga-btn ga-btn-sm${sub === id ? ' ga-btn-primary' : ''}`}
                onClick={() => setSub(id)}>
                {id === 'steps' ? t('Steps') : id === 'settings' ? t('Settings')
                  : mode === 'haar' ? t('HAAR variants') : t('HairDeck images')}
              </button>
            ))}
          </nav>

          {sub === 'steps' ? (
            <>
              {rows.map((row) => (
                <StepRowView key={row.id} row={row}>
                  {row.button ? (
                    <div>
                      <RunButton feedback={feedback} slot={runSlot({ step: row.id })}
                        disabled={busy || !!row.button.disabled}
                        title={row.button.disabled || (row.id === 'haar'
                          ? t('Asks HAAR for the next {n} seeds (the older variants stay), then fits them on the CPU — {cost}')
                            .replace('{n}', String(haarPanel?.jobs ?? 3)).replace('{cost}', haarRunCost(
                              { steps: ['haar', 'fit'], hub_jobs: haarPanel?.jobs ?? 3, cpu_fits: haarPanel?.jobs ?? 3 }, t))
                          : t('Redoes this step even when it is current'))}
                        onClick={() => onRun(row.id === 'hairdeck' || row.id === 'haar'
                          ? { step: row.id, force: true, chain: true } : { step: 'fit', force: true })}
                        label={row.button.label} />
                    </div>
                  ) : null}
                  {row.id === 'fit' && fitRecord && mode === 'hairdeck' ? (
                    <GateChips specs={HAIRDECK_FIT_CHIPS} record={fitRecord} limits={info.limits?.hairdeck_fit} />
                  ) : null}
                </StepRowView>
              ))}
              {hairdeckRow && fitRow && hd?.attempts.length ? (
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
          ) : sub === 'settings' ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '8px 12px' }}>
              <label className="ga-form-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}
                title={t(HAIR_MODE_HINTS[mode]) || undefined}>
                {t('Mode')}
                <select className="ga-input" value={mode} disabled={posting || running} aria-label={t('Hair mode')}
                  onChange={(e) => { void setMode(e.target.value as HairMode) }}>
                  {HAIR_MODES.map((m) => (
                    <option key={m} value={m} disabled={!!hairModeDisabled(m, built)}>
                      {t(HAIR_MODE_LABELS[m])}{hairModeDisabled(m, built) ? ` — ${t(hairModeDisabled(m, built) || '')}` : ''}
                    </option>
                  ))}
                </select>
              </label>
              <div className="ga-hint" style={{ alignSelf: 'end' }}>
                {modeSaved ? (entry.worn ? t('Saved — nothing ran; the Figure tab’s Build makes it.')
                  : t('Saved — nothing ran; it applies when worn.'))
                  : t('Saved on change — nothing runs.')}
              </div>
              {modeSaved && entry.worn ? (
                <div style={{ gridColumn: '1 / -1' }}><FigureBuildLine character={character} version={modeSaved} /></div>
              ) : null}
              <div className="ga-hint" style={{ gridColumn: '1 / -1' }}>{t(HAIR_MODE_HINTS[mode])}</div>
              <HairstyleText key={itemId} character={character} itemId={itemId} mode={mode}
                text={info.description || entry.description || ''} busy={busy || running}
                onSaved={() => { reload(); if (mode === 'body') onChanged(); else onRunEnded() }} />
              {hd && mode === 'haar' ? (
                <>
                  <div className="ga-hint">
                    <span className="ga-form-hint">{t('Colour')}</span><br />
                    {hd.colour.target ? `${t('Manual')} ${hd.colour.target}`
                      : hd.colour.profile ? `${t('Automatic')}: ${t('Profile colour')} (${hd.colour.profile.name})`
                        : `${t('Automatic')}: ${t('None named — the cards stay plain')}`}
                  </div>
                  <div className="ga-hint">
                    <span className="ga-form-hint">{t('Variant in use')}</span><br />
                    {haarPanel?.in_use != null ? `${t('Seed')} ${haarPanel.in_use}`
                      : garment?.preview_url ? t('None of this text yet — the preview shows the hair made before')
                        : t('No fit yet')}
                    {haarPanel?.picked != null ? ` · ${t('picked')}` : ` · ${t('automatic')}`}
                  </div>
                  <div className="ga-hint" style={{ gridColumn: '1 / -1' }}>
                    {t('Colour and motion sit beside the preview: they act while dragged and save on their own. HAAR hair has no placement — its strands are fitted to the head.')}
                  </div>
                </>
              ) : hd ? (
                <>
                  <div className="ga-hint" title={hd.colour.auto ? `${t("HairDeck's own")} ${hd.colour.auto}` : undefined}>
                    <span className="ga-form-hint">{t('Colour')}</span><br />
                    {hd.colour.target ? `${t('Manual')} ${hd.colour.target}`
                      : hd.colour.profile ? `${t('Automatic')}: ${t('Profile colour')} (${hd.colour.profile.name})`
                        : `${t('Automatic')}: ${t("HairDeck's own")}`}
                    {hd.colour.fitted?.delta_e_before != null
                      ? ` · ΔE ${hd.colour.fitted.delta_e_before} → ${hd.colour.fitted.delta_e_after ?? '–'}` : ''}
                  </div>
                  <div className="ga-hint">
                    <span className="ga-form-hint">{t('Last fit')}</span><br />
                    {hd.placement.fitted && hd.placement.fitted.forward_m !== null
                      ? `${(hd.placement.fitted.forward_m * 1000).toFixed(1)} mm · ${(hd.placement.fitted.tilt_deg ?? 0).toFixed(1)}° · ${(hd.placement.fitted.width_scale ?? 1).toFixed(2)}×`
                      : t('No fit yet')}
                    {hd.placement.fitted?.hairline_y != null
                      ? ` · ${t('Hairline')} ${hd.placement.fitted.hairline_y.toFixed(3)} m` : ''}
                  </div>
                  <div className="ga-hint" style={{ gridColumn: '1 / -1' }}>
                    {t('Placement, colour and motion sit beside the preview: they act while dragged and save on their own.')}
                  </div>
                </>
              ) : null}
            </div>
          ) : mode === 'haar' ? (
            haarPanel ? (
              <HaarVariants character={character} itemId={itemId} panel={haarPanel} busy={busy || !info.pipeline}
                onSaved={() => { reload(); onRunEnded() }} />
            ) : <div className="ga-hint">{t('Loading…')}</div>
          ) : hd ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6 }}>
                {([['input', hd.input_source === 'beard_free' ? 'Input (beard removed)' : 'Input (profile picture)'],
                  ['prep', 'Prepared'], ['model_input', 'Model input']] as const).map(([key, label]) => {
                  const img = hd.images[key]
                  return (
                    <div key={key} style={{ minWidth: 0 }}>
                      <div className="ga-hint">{t(label)}</div>
                      {img ? <RefImage key={img.url} src={img.url} height={110} label={t(label)} meta={img} compact />
                        : <div className="ga-hint" style={{ ...EMPTY_TILE, height: 110 }}>
                          {key === 'input' ? t('No profile picture') : t('No render yet')}
                        </div>}
                    </div>
                  )
                })}
              </div>
              <div className="ga-hint">{t('Click a picture to enlarge it.')}</div>
              {hd.notes.length ? <div className="ga-hint">{t('Notes')}: {hd.notes.join(' · ')}</div> : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export function FieldHairstyles({ character, onOpenFigure }: {
  character: string
  /** Opens the Figure tab (the Build, the figure with every worn piece). */
  onOpenFigure?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [list, setList] = useState<HairstylesList | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState('')
  const [dialog, setDialog] = useState(false)
  const [posting, setPosting] = useState(false)
  // Bumped by every Wear / mode change: the Build line shows (and reloads).
  const [changed, setChanged] = useState(0)

  const load = useCallback(async () => {
    try {
      setList(await apiGet<HairstylesList>(`/characters/${enc}/hairstyles`))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [enc])
  useEffect(() => { void load() }, [load])
  const reloadList = useCallback(() => { void load() }, [load])

  const wear = useCallback(async (id: string) => {
    if (posting) return
    setPosting(true)
    try {
      await apiPost(`/characters/${enc}/hairstyles/${encodeURIComponent(id)}/wear`, {})
      setChanged((v) => v + 1)
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }, [enc, load, posting, t, toast])

  if (error) return <div className="ga-hint" style={WARN_STYLE}>{error}</div>
  if (!list) return <div className="ga-hint">{t('Loading…')}</div>

  const wornId = list.hairstyles.find((h) => h.worn)?.id || ''
  const rows = hairstyleRows(list.hairstyles, wornId, t) as Array<HairstyleEntry & { label: string }>
  const current = rows.find((h) => h.id === selected) || rows[0] || null

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '230px minmax(0, 1fr)', gap: 16, alignItems: 'start',
      fontSize: 13 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Hairstyles')}</span>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" style={{ marginLeft: 'auto' }}
            title={t('Creating runs nothing and wears nothing — Wear it, then the Build makes it.')}
            onClick={() => setDialog(true)}>
            {t('New hairstyle')}
          </button>
        </div>
        {!rows.length ? (
          <div className="ga-hint">{list.pipeline === false
            ? t('No hairstyle yet. A temporary NPC has no figure — a hairstyle stays a description.')
            : t('No hairstyle yet — the Build makes the first one from the Appearance text, or create one.')}</div>
        ) : null}
        {rows.map((h) => {
          const light = listLight(h.freshness?.state, h.mode, h.due)
          const reason = listReason(h.freshness, h.due, t)
          const wearBtn = wearButton(h.wear, t)
          return (
            <div key={h.id} role="button" tabIndex={0}
              onClick={() => setSelected(h.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSelected(h.id) }}
              title={[h.description, reason ? `${t('Status')}: ${reason}` : ''].filter(Boolean).join('\n')}
              style={{
                display: 'flex', flexDirection: 'column', gap: 3, padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
                borderLeft: `3px solid ${h.worn ? 'var(--accent, #58a6ff)' : 'rgba(255,255,255,0.18)'}`,
                background: current?.id === h.id ? 'rgba(120,170,255,0.16)' : 'rgba(255,255,255,0.04)',
              }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <StepLight light={light} />
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {h.label}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8em' }}>
                <span className="ga-hint" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap' }}>
                  {[h.worn ? t('Worn') : '', h.plain ? t('Plain body') : '', reason].filter(Boolean).join(' · ')}
                </span>
                {!h.worn ? (
                  <button type="button" className="ga-btn ga-btn-sm" disabled={posting}
                    title={wearBtn.title}
                    onClick={(e) => { e.stopPropagation(); void wear(h.id) }}>
                    {wearBtn.label}
                  </button>
                ) : null}
              </div>
            </div>
          )
        })}
        {changed > 0 ? <FigureBuildLine character={character} version={changed} /> : null}
      </div>
      <div style={{ minWidth: 0 }}>
        {current ? (
          <HairstyleDetail key={current.id} character={character} entry={current} built={list.built_modes || HAIR_MODES}
            onOpenFigure={onOpenFigure}
            onChanged={() => { setChanged((v) => v + 1); void load() }} onRunEnded={reloadList} />
        ) : (
          <div className="ga-hint" style={{ ...EMPTY_TILE, height: 200, padding: 16 }}>
            {t('Create a hairstyle with “New hairstyle” — creating runs nothing.')}
          </div>
        )}
      </div>
      {dialog ? (
        <NewHairstyleDialog character={character} defaultMode={list.default_mode} built={list.built_modes || HAIR_MODES}
          standard={standardHairText(list)} onClose={() => setDialog(false)}
          onCreated={(id) => { setDialog(false); setSelected(id); void load() }} />
      ) : null}
    </div>
  )
}
