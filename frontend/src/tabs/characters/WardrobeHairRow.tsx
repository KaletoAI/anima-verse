/**
 * WardrobeHairRow — the hair as the first row of the Wardrobe (plan
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 9; spec
 * rulings 5 and 6). Phase 1 keeps one hair per character, so its mode is the
 * character's `hair_method`, not an item's.
 *
 * The row: the hair description (read-only — derived from Appearance, with
 * the link there), the mode select (HairDeck · HAAR · In the body; HAAR is
 * listed disabled, "not built yet" written under it), saved at once and
 * spending nothing (POST /characters/{n}/hair/method) — after a change the
 * row shows the character's pending changes and its Build (GET
 * /characters/{n}/figure, POST …/figure/build). In HairDeck mode without a
 * hair item the row offers "Create hair" (POST …/hair: create + wear the
 * item, start its chain — the Build would make it too). Collapsed "Details":
 * for HairDeck "Wear hair", the colour, the placement (HairDeckPlacement) and
 * the HairDeck steps with seed and run; in the body the base body's prompt
 * freshness. (Create and Wear moved here in plan Task 11.)
 *
 * Backend (app/routes/characters.py): GET /characters/{n}/hair (polled while
 * a step runs — useGarment), POST …/hair/method {method}, POST …/hair
 * (create), POST …/hair/equipped {equipped}, POST …/hair/colour {hex}, POST
 * …/hair/placement, POST /characters/{n}/garments/{item}/run {step?, force?}
 * (useGarmentRun; a colour or placement change re-fits from the stored
 * HairDeck result).
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import {
  FitBlock, GarmentFailure, RecordNumbers, RunBadge, RunButton, RunStatusLine, StepState,
} from './GarmentSteps'
import {
  EMPTY_TILE, ERROR_STYLE, HAIRDECK_FIT_CHIPS, HAIR_STEP_LABELS, ROW, WARN_STYLE, flatFit, num,
} from './garmentStyle'
import type { GarmentRunBody } from './garmentStyle'
import { FreshnessBadge } from './FreshnessBadge'
import { HairDeckPlacement } from './HairDeckPlacement'
import { RefImage } from './RefImage'
import { BuildSteps } from './WardrobeGarment'
import {
  BUILD_STATUS, HAIR_MODES, HAIR_MODE_HINTS, HAIR_MODE_LABELS, figureBuildLine, hairModeDisabled,
} from './figureModel'
import type { HairMode } from './figureModel'
import { garmentRunning, runMark, runSlot, useGarment, useGarmentRun } from './useGarment'
import type { HairDeckPanel, HairInfo, RunFeedback } from './useGarment'

/** "Create hair" exists for HairDeck only — `body` makes no hair item. */
const CREATE_HINT = 'Makes hair cards from the profile picture and fits them onto the base model.'

/** HairDeck's three image tiles: small, a click enlarges. */
const HAIRDECK_TILE = 120

/** The HairDeck method's steps (`garment_store.steps_for`). */
const HAIRDECK_ORDER = ['hairdeck', 'fit'] as const

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

export function Swatch({ hex }: { hex: string }) {
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

/** The HairDeck steps: its three image tiles, status with attempt / seed /
 *  backend, "Regenerate hair (HairDeck)" (a new seed), the fit with its chips
 *  and the refused fit attempts. */
function HairDeckSteps({ info, hd, busy, onRun, feedback }: {
  info: HairInfo
  hd: HairDeckPanel
  busy: boolean
  onRun: (body: GarmentRunBody, slot?: string) => void
  feedback: RunFeedback
}) {
  useClockSettings()
  const { t } = useI18n()
  const garment = info.garment
  const noInput = !hd.images.input
  return (
    <>
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
          disabled={busy || !garment || noInput}
          onClick={() => onRun({ step: 'hairdeck', force: true })}
          label={t('Regenerate hair (HairDeck)')}
        />
      </div>
      {noInput ? <div className="ga-hint" style={WARN_STYLE}>{t('Set a profile picture first')}</div> : null}
      {hd.notes.length ? <div className="ga-hint">{t('Notes')}: {hd.notes.join(' · ')}</div> : null}
      {hd.status === 'refused' && hd.error ? <div className="ga-hint" style={ERROR_STYLE}>{hd.error}</div> : null}
      {garment ? <StepState garment={garment} step="hairdeck" /> : null}

      <FitBlock garment={garment} chips={HAIRDECK_FIT_CHIPS} limits={info.limits?.hairdeck_fit}
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
  )
}

/** GET /characters/{n}/figure — the parts the hair row reads. */
interface FigureCost {
  pipeline: boolean
  changes: Array<{ key: string; name: string }>
  cost: { hub_jobs: number | null; note: string; steps: Array<{ label: string }> }
}

/** The line after a hair mode change: the character's pending changes and
 *  ONE "Build (cost)" button (POST /characters/{n}/figure/build — a manual
 *  Build); its reason under it when there is nothing to build. */
function FigureBuildLine({ character, version }: { character: string; version: number }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [data, setData] = useState<FigureCost | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    try {
      setData(await apiGet<FigureCost>(`/characters/${enc}/figure`))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [enc])
  useEffect(() => { void load() }, [load, version])
  if (error) return <div className="ga-hint" style={WARN_STYLE}>{error}</div>
  if (!data) return <div className="ga-hint">{t('Loading…')}</div>
  const changes = data.changes.length
  const line = figureBuildLine(changes, data.cost.hub_jobs)
  const jobs = data.cost.hub_jobs === null ? t('cost unknown')
    : data.cost.hub_jobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(data.cost.hub_jobs))
  const build = async () => {
    setBusy(true)
    try {
      const d = await apiPost<{ status: string }>(`/characters/${enc}/figure/build`, {})
      toast(t(BUILD_STATUS[d.status] || d.status), 'success')
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: '0.75em' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span>
          {changes === 0 ? t('No changes') : changes === 1 ? t('1 change')
            : t('{n} changes').replace('{n}', String(changes))}
          {changes ? `: ${data.changes.map((c) => t(c.name)).join(', ')}` : ''}
        </span>
        {line.button ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} title={t(data.cost.note)}
            onClick={() => { void build() }}>
            {t('Build ({cost})').replace('{cost}', jobs)}
          </button>
        ) : null}
      </div>
      {line.reason ? <span className="ga-hint">{t(line.reason)}</span> : null}
      <BuildSteps steps={data.cost.steps.map((s) => s.label)}
        summary={t('What the Build runs ({cost})').replace('{cost}', jobs)} />
    </div>
  )
}

export function WardrobeHairRow({ character, onEditAppearance }: {
  character: string
  /** Opens the Appearance tab, where the hair text is edited. */
  onEditAppearance?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, startPoll } = useGarment<HairInfo>(character ? `/characters/${enc}/hair` : null)
  // The user's own click, until the request answered (the poll then shows the server's running state).
  const [posting, setPosting] = useState(false)
  // Bumped by every saved mode change: the Build line shows (and reloads).
  const [changed, setChanged] = useState(0)

  const call = useCallback(
    async (path: string, body: unknown, after?: (d: unknown) => void | Promise<unknown>) => {
      if (posting) return false
      setPosting(true)
      try {
        const d = await apiPost(path, body)
        await after?.(d)
        startPoll(300)
        return true
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        startPoll()
        return false
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
    (equipped: boolean) => call(`/characters/${enc}/hair/equipped`, { equipped }),
    [call, enc],
  )

  const setMode = useCallback(async (mode: HairMode) => {
    if (hairModeDisabled(mode)) return
    if (await call(`/characters/${enc}/hair/method`, { method: mode })) setChanged((v) => v + 1)
  }, [call, enc])

  // Store the colour, then re-fit (only the fit runs: the HairDeck result is cached).
  const applyColour = useCallback(
    (hex: string) => call(`/characters/${enc}/hair/colour`, { hex }, () => (
      itemId && info?.method === 'hairdeck'
        ? apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
        : undefined
    )),
    [call, enc, info?.method, itemId],
  )

  if (!info || !info.humanoid) return null

  const garment = info.garment
  const running = garmentRunning(info)
  const busy = posting || feedback.pending !== null || running
  const hd = info.hairdeck
  const mode: HairMode = info.method === 'hairdeck' ? 'hairdeck' : 'body'
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  const disabledReasons = HAIR_MODES.map((m) => [m, hairModeDisabled(m)] as const).filter(([, r]) => r)

  let details
  if (mode === 'hairdeck') {
    details = !info.item_id ? (
      <div className="ga-hint">{t('No hair item yet — the Build makes it.')}</div>
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
        <RunStatusLine garment={garment} feedback={feedback} stepLabels={HAIR_STEP_LABELS}
          onCancel={() => { void cancel() }} />
        <GarmentFailure garment={garment} stepLabels={HAIR_STEP_LABELS} />
        {hd ? (
          <>
            <div className="ga-fieldset-title">{t('Hair colour')}</div>
            <HairColour
              key={`${hd.colour.target || ''}|${hd.colour.profile?.hex || ''}|${hd.colour.auto || ''}`}
              colour={hd.colour}
              busy={busy}
              running={running}
              onApply={(hex) => { void applyColour(hex) }}
            />
            {hd.placement ? (
              <>
                <div className="ga-fieldset-title">{t('Hair placement')}</div>
                <HairDeckPlacement character={character} itemId={itemId} method={info.method}
                  placement={hd.placement} chains={hd.chains}
                  swingPending={!!garment?.stale_reasons.includes('swing_changed')}
                  busy={busy} running={running} onSaved={() => startPoll(300)} />
              </>
            ) : null}
            <div className="ga-fieldset-title">{t('HairDeck')}</div>
            <HairDeckSteps info={info} hd={hd} busy={busy} onRun={onRun} feedback={feedback} />
          </>
        ) : null}
      </>
    )
  } else {
    const prompts = info.base_prompts
    details = (
      <>
        <div style={ROW}>
          <span className="ga-hint">{t('Base body prompts')}</span>
          <FreshnessBadge freshness={prompts} compact />
        </div>
        {prompts?.state === 'stale' ? (
          <div className="ga-hint" style={WARN_STYLE}>
            {t('This base body was rendered with older prompts, so its mesh may carry no hair. A manual Build rebuilds it.')}
          </div>
        ) : prompts?.state === 'missing' ? (
          <div className="ga-hint">{t('No base body yet — a manual Build makes it; it is rendered with the hair.')}</div>
        ) : null}
      </>
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', borderRadius: 6,
      borderLeft: '3px solid rgba(255,255,255,0.18)', background: 'rgba(120,170,255,0.08)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        <span style={{
          width: 40, height: 40, flex: '0 0 auto', borderRadius: 4, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontSize: 24, background: 'rgba(255,255,255,0.08)',
        }} aria-hidden>💇</span>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <span>{t('Hair')}</span>
          <span style={{ fontSize: '0.72em', opacity: 0.6, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' }} title={info.description || undefined}>
            {info.description || t('No hair set in Appearance')}
          </span>
        </div>
        {onEditAppearance ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onEditAppearance}>
            {t('Edit in Appearance')}
          </button>
        ) : null}
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, paddingLeft: 50, flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75em' }}
            title={t(HAIR_MODE_HINTS[mode])}>
            <span style={{ opacity: 0.7 }}>{t('Mode')}</span>
            <select className="ga-input" style={{ width: 'auto', padding: '1px 4px', fontSize: '1em' }}
              value={mode} disabled={!info.pipeline || busy} aria-label={t('Hair mode')}
              onChange={(e) => { void setMode(e.target.value as HairMode) }}>
              {HAIR_MODES.map((m) => (
                <option key={m} value={m} disabled={!!hairModeDisabled(m)}>{t(HAIR_MODE_LABELS[m])}</option>
              ))}
            </select>
          </label>
          {disabledReasons.map(([m, r]) => (
            <span key={m} className="ga-hint" style={{ fontSize: '0.7em' }}>
              {t(HAIR_MODE_LABELS[m])}: {t(r || '')}
            </span>
          ))}
          {!info.pipeline ? (
            <span className="ga-hint" style={{ fontSize: '0.7em' }}>
              {t('Only characters on the figure pipeline use modes')}
            </span>
          ) : info.method_source === 'world' ? (
            <span className="ga-hint" style={{ fontSize: '0.7em' }}>{t('World default')}</span>
          ) : null}
          {running ? (
            <span className="ga-hint" style={{ ...WARN_STYLE, fontSize: '0.7em' }}>{t('Wait for the running hair job')}</span>
          ) : null}
        </span>
        <span className="ga-hint" style={{ fontSize: '0.72em', flex: '1 1 160px' }}>{t(HAIR_MODE_HINTS[mode])}</span>
      </div>
      {mode === 'hairdeck' && info.pipeline && !info.item_id && info.description ? (
        <div style={{ ...ROW, paddingLeft: 50, fontSize: '0.75em' }}>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={posting}
            onClick={() => { void create() }}>
            {t('Create hair')}
          </button>
          <span className="ga-hint">{t(CREATE_HINT)}</span>
        </div>
      ) : null}
      {changed > 0 ? (
        <div style={{ paddingLeft: 50 }}>
          <FigureBuildLine character={character} version={changed} />
        </div>
      ) : null}
      {info.pipeline ? (
        <details style={{ paddingLeft: 50 }}>
          <summary className="ga-hint" style={{ cursor: 'pointer', fontSize: '0.75em' }}>{t('Details')}</summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 4 }}>{details}</div>
        </details>
      ) : null}
    </div>
  )
}
