/**
 * FieldHairstyles — the character tab "Hairstyles" (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
 * Task 14, rebuilt in Task UI4 to the user's checklist for every character tab). Hairstyles are items: several
 * owned, one worn; the mode (`hairdeck` · `body` · `haar`, not built yet) lives on the item.
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
 *     live while dragged (a vertex map, a colour tint, the spring frequencies) and is saved on its own, nothing
 *     runs; the forward shift shows a centimetre ruler and the shift itself in the preview while hovered;
 *   - sub-tabs: Steps (one row per step: traffic light, the reason in plain words, its single button that redoes
 *     the step even when current, with its cost), Settings (mode, text, colour and placement facts) and HairDeck
 *     images (three small tiles, a click enlarges).
 * A temporary NPC has no figure: the list and the settings stay, no step runs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { createPortal } from 'react-dom'
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
  colourTint, fittedPlacement, hairStepRows, jobsLabel, listLight, listReason, placementIdentity, placementMap, placementRuler, previewMotion, wearButton,
} from './hairstylesModel'
import type { Light, PreviewMotionInput, StepRow, Vec3 } from './hairstylesModel'
import { Model3DViewer } from './Model3DViewer'
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
  preview_motion?: PreviewMotionInput | null
}

const VIEWER_HEIGHT = 580
const LIGHT_COLOR: Record<Light, string> = {
  green: 'var(--success, #3fb950)',
  yellow: 'var(--warning, #d29922)',
  red: 'var(--danger, #f85149)',
  grey: 'var(--text-muted, #6e7681)',
  blue: 'var(--accent, #58a6ff)',
}
const PANEL: CSSProperties = {
  border: '1px solid var(--border, #30363d)', borderRadius: 8, padding: 10, display: 'flex',
  flexDirection: 'column', gap: 8, minWidth: 0,
}

export function StepLight({ light, title }: { light: Light; title?: string }) {
  return (
    <span aria-hidden title={title} style={{
      flex: '0 0 10px', width: 10, height: 10, borderRadius: '50%', background: LIGHT_COLOR[light],
      boxShadow: light === 'blue' ? '0 0 0 3px rgba(88,166,255,0.25)' : undefined, display: 'inline-block',
    }} />
  )
}

/** The "New hairstyle" dialog: description + mode (HAAR listed, disabled "not built yet"). Create starts
 *  nothing; the new hairstyle is not worn (except a character's first one — the server decides). */
function NewHairstyleDialog({ character, defaultMode, onClose, onCreated }: {
  character: string
  defaultMode: HairMode
  onClose: () => void
  onCreated: (itemId: string) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<HairMode>(hairModeDisabled(defaultMode) ? 'body' : defaultMode)
  const [posting, setPosting] = useState(false)
  const reason = newHairstyleDisabled(description, mode)
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
          <label className="ga-form-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Description')}
            <textarea className="ga-input" rows={3} value={description} disabled={posting}
              placeholder={t('e.g. shoulder-length wavy auburn hair with a side parting')}
              onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className="ga-form-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Mode')}
            <select className="ga-input" value={mode} disabled={posting} aria-label={t('Hair mode')}
              onChange={(e) => setMode(e.target.value as HairMode)}>
              {HAIR_MODES.map((m) => (
                <option key={m} value={m} disabled={!!hairModeDisabled(m)}>
                  {t(HAIR_MODE_LABELS[m])}{hairModeDisabled(m) ? ` — ${t(hairModeDisabled(m) || '')}` : ''}
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
          {reason ? <span className="ga-hint">{t(reason)}</span> : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** One step: light, name, state; the reason (mouse-over: the numbers); its single button. */
function StepRowView({ row, children }: { row: StepRow; children?: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, paddingBottom: 6,
      borderBottom: '1px solid var(--border, #30363d)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} title={row.detail || undefined}>
        <StepLight light={row.light} />
        <strong style={{ fontSize: 13 }}>{row.name}</strong>
        <span className="ga-hint" style={{ marginLeft: 'auto', color: LIGHT_COLOR[row.light] }}>{row.state}</span>
      </div>
      <div className="ga-hint" style={{ overflowWrap: 'anywhere' }} title={row.detail || undefined}>{row.reason}</div>
      {children}
      {row.button?.disabled ? <div className="ga-hint">{row.button.disabled}</div> : null}
    </div>
  )
}

/** The selected hairstyle: flow head, preview with its live settings beside it, and the sub-tabs. */
function HairstyleDetail({ character, entry, onChanged, onRunEnded, onOpenFigure }: {
  character: string
  entry: HairstyleEntry
  /** The mode was saved: the list and the Build line reload. */
  onChanged: () => void
  /** A run of this hairstyle ended: the list (its light) reloads. */
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
  const garment = info?.garment ?? null
  // The live previews: placement (vertex map about the fit's pivot), colour (tint), stiffness (spring frequency).
  const pivot = (hd?.placement as unknown as { pivot?: Vec3 | null } | undefined)?.pivot ?? null
  const headCapsule = info?.collision?.capsules?.find((c) => c.region === 'head')
  const halfWidth = headCapsule?.r ?? 0.08
  const fitted = hd ? fittedPlacement(hd.placement) : null
  const meshAdjust = useMemo(() => {
    if (!hd || !info?.item_id) return null
    const map = pivot && fitted && drafts.placement && !placementIdentity(fitted, drafts.placement)
      ? placementMap(pivot, fitted, drafts.placement, pivot[0], halfWidth) : null
    const shown = hd.colour.fitted?.applied === false ? hd.colour.auto
      : hd.colour.fitted?.target || hd.colour.target || hd.colour.profile?.hex || hd.colour.auto
    const tint = drafts.colour ? colourTint(shown, drafts.colour) : null
    return map || tint ? { match: `garment_hair_${info.item_id}`, map, tint } : null
  }, [hd, info?.item_id, pivot, fitted?.forward_m, fitted?.tilt_deg, fitted?.width_scale, drafts.placement, // eslint-disable-line react-hooks/exhaustive-deps
    drafts.colour, halfWidth])
  const motion = useMemo(() => previewMotion(info?.preview_motion,
    drafts.stiffness ?? hd?.chains?.stiffness ?? 1), [info?.preview_motion, drafts.stiffness, hd?.chains?.stiffness])
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
    if (hairModeDisabled(next) || next === mode || posting) return
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
  const preview = mode === 'hairdeck' && garment?.preview_url ? (
    <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={VIEWER_HEIGHT}
      previewTilt freshness={garment.preview_freshness} builtAt={garment.preview_built_at}
      collision={info.collision} motion={motion} meshAdjust={meshAdjust} polylines={polylines} focus={focus}
      motionToolbar={hd ? (
        <HairLiveControls character={character} itemId={itemId} hd={hd} info={info} busy={busy || !info.pipeline}
          previewSwings={motion ? 'yes' : 'no_swing'} onDraft={onDraft} onRuler={setRuler} onSaved={reload} />
      ) : undefined} />
  ) : mode === 'body' && info.plain && info.body_url ? (
    <Model3DViewer key={info.body_url} url={info.body_url} format="glb" height={VIEWER_HEIGHT}
      builtAt={info.body_built_at} />
  ) : (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
      <div className="ga-hint" style={{ ...EMPTY_TILE, flex: '0 1 440px', height: VIEWER_HEIGHT, padding: 16,
        textAlign: 'center' }}>
        {mode === 'hairdeck'
          ? (info.pipeline ? t('No fitted hair yet — Run all makes it ({cost}).')
            .replace('{cost}', jobsLabel(info.run?.hub_jobs ?? null, t))
            : t('No 3D preview — a temporary NPC has no figure.'))
          : mode === 'body'
            ? t('Its hair is in the body: the plain body is rendered with it when it is worn and built — the Figure tab shows the figure.')
            : t('HAAR hair is not built yet — there is nothing to preview.')}
      </div>
      {mode === 'hairdeck' && hd && info.pipeline ? (
        <aside className="ga-model3d-toolbar" style={{ flex: '0 0 220px' }}>
          <HairLiveControls character={character} itemId={itemId} hd={hd} info={info} busy={busy}
            previewSwings="no_preview" onDraft={onDraft} onRuler={setRuler} onSaved={reload} />
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
              disabled={busy || !garment || actions.runAll.disabled}
              title={[t('Runs every step that is missing or out of date, in order, and skips what is current'),
                info.run?.note || ''].filter(Boolean).join(' — ')}
              onClick={() => onRun({}, 'all')} label={actions.runAll.label} />
            {info.run?.hub_jobs ? <span className="ga-hint">{t(ESTIMATE_NOTE)}</span> : null}
          </>
        ) : null}
        {mode === 'body' ? (
          <span className="ga-hint">{t('Its flow is the Figure tab’s Build.')}</span>
        ) : null}
        {mode === 'body' && onOpenFigure ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenFigure}>{t('Open Figure tab')}</button>
        ) : null}
        {mode === 'hairdeck' && garment?.preview_url ? (
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
      {mode === 'hairdeck' ? (
        <RunStatusLine garment={garment} feedback={feedback} stepLabels={HAIR_STEP_LABELS} bare
          onCancel={() => { void cancel() }} />
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 680px) minmax(300px, 1fr)', gap: 14,
        alignItems: 'start' }}>
        <div className="ga-model3d-fit" style={{ minWidth: 0 }}>{preview}</div>
        <div style={PANEL}>
          <nav className="ga-subtabs" style={{ margin: 0 }}>
            {(['steps', 'settings', ...(mode === 'hairdeck' ? ['images'] as const : [])] as const).map((id) => (
              <button key={id} type="button" className={`ga-btn ga-btn-sm${sub === id ? ' ga-btn-primary' : ''}`}
                onClick={() => setSub(id)}>
                {id === 'steps' ? t('Steps') : id === 'settings' ? t('Settings') : t('HairDeck images')}
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
                        title={row.button.disabled || t('Redoes this step even when it is current')}
                        onClick={() => onRun(row.id === 'hairdeck' ? { step: 'hairdeck', force: true, chain: true }
                          : { step: 'fit', force: true })}
                        label={row.button.label} />
                    </div>
                  ) : null}
                  {row.id === 'fit' && fitRecord ? (
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
                    <option key={m} value={m} disabled={!!hairModeDisabled(m)}>
                      {t(HAIR_MODE_LABELS[m])}{hairModeDisabled(m) ? ` — ${t(hairModeDisabled(m) || '')}` : ''}
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
              <div className="ga-hint" style={{ gridColumn: '1 / -1' }}>{t(HAIR_MODE_HINTS[mode]) || t('HAAR hair is not built yet.')}</div>
              <div style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span className="ga-form-hint">{t('Description')}</span>
                <span style={{ overflowWrap: 'anywhere' }}>{info.description || entry.description || '—'}</span>
              </div>
              {hd ? (
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
                opacity: h.mode === 'haar' ? 0.7 : 1,
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
                  <button type="button" className="ga-btn ga-btn-sm" disabled={posting || h.mode === 'haar'}
                    title={h.mode === 'haar' ? t('HAAR hair is not built yet') : wearBtn.title}
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
          <HairstyleDetail key={current.id} character={character} entry={current} onOpenFigure={onOpenFigure}
            onChanged={() => { setChanged((v) => v + 1); void load() }} onRunEnded={reloadList} />
        ) : (
          <div className="ga-hint" style={{ ...EMPTY_TILE, height: 200, padding: 16 }}>
            {t('Create a hairstyle with “New hairstyle” — creating runs nothing.')}
          </div>
        )}
      </div>
      {dialog ? (
        <NewHairstyleDialog character={character} defaultMode={list.default_mode}
          onClose={() => setDialog(false)}
          onCreated={(id) => { setDialog(false); setSelected(id); void load() }} />
      ) : null}
    </div>
  )
}
