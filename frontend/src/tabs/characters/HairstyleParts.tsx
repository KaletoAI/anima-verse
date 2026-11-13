/**
 * HairstyleParts — the parts of a HairDeck hairstyle's settings and steps that the Hairstyles tab
 * (FieldHairstyles; plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 14, Rulings P2/P3)
 * renders for the SELECTED hairstyle. They were the Wardrobe's hair row (Task 9) until P3 took the hair out of
 * the Wardrobe.
 *
 * - HairColour: automatic (the hairstyle text's named colour, else HairDeck's own) or a manual one — Apply only
 *   SAVES it (rule R3; POST /characters/{n}/hair/colour {hex, item_id}); the fit becomes stale and Run all /
 *   Re-fit applies it.
 * - HairDeckSteps: HairDeck's three image tiles, its status (attempt / seed / backend), "Regenerate hair
 *   (HairDeck) — 1 hub job" (a new seed, then the fit; rule R2) and the fit block with "Re-fit — no hub job".
 * - FigureBuildLine: the character's pending changes and ONE "Build (cost)" button (POST
 *   /characters/{n}/figure/build) — shown after a Wear or a mode change.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { FitBlock, RecordNumbers, RunBadge, RunButton, StepState } from './GarmentSteps'
import {
  EMPTY_TILE, ERROR_STYLE, HAIRDECK_FIT_CHIPS, ROW, WARN_STYLE, flatFit, num,
} from './garmentStyle'
import type { GarmentRunBody } from './garmentStyle'
import { RefImage } from './RefImage'
import { BuildSteps } from './WardrobeGarment'
import { BUILD_STATUS, figureBuildLine } from './figureModel'
import { runMark, runSlot } from './useGarment'
import type { HairDeckPanel, HairInfo, RunFeedback } from './useGarment'

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
 *  Keyed by the server values, so the draft starts from them after a save.
 *  Apply only saves (rule R3) — the fit then shows stale. */
export function HairColour({ colour, busy, running, onApply }: {
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
        {t('Saving runs nothing. Run all or Re-fit then fits the hair in the new colour from the stored HairDeck result (no hub job).')}
      </div>
    </>
  )
}

/** The HairDeck steps: its three image tiles, status with attempt / seed /
 *  backend, "Regenerate hair (HairDeck) — 1 hub job" (a new seed, then the fit — rule R2: it re-runs even when
 *  current), the fit with its chips and "Re-fit — no hub job", and the refused fit attempts. */
export function HairDeckSteps({ info, hd, busy, onRun, feedback, regenerateLabel, refitLabel }: {
  info: HairInfo
  hd: HairDeckPanel
  busy: boolean
  onRun: (body: GarmentRunBody, slot?: string) => void
  feedback: RunFeedback
  /** The single steps' labels with their cost (`hairstyleActions`). */
  regenerateLabel: string
  refitLabel: string
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
          onClick={() => onRun({ step: 'hairdeck', force: true, chain: true })}
          label={regenerateLabel}
        />
      </div>
      {noInput ? <div className="ga-hint" style={WARN_STYLE}>{t('Set a profile picture first')}</div> : null}
      {hd.notes.length ? <div className="ga-hint">{t('Notes')}: {hd.notes.join(' · ')}</div> : null}
      {hd.status === 'refused' && hd.error ? <div className="ga-hint" style={ERROR_STYLE}>{hd.error}</div> : null}
      {garment ? <StepState garment={garment} step="hairdeck" /> : null}

      <FitBlock garment={garment} chips={HAIRDECK_FIT_CHIPS} limits={info.limits?.hairdeck_fit}
        ready={hd.status === 'accepted'} busy={busy} onRun={onRun}
        lowFailedText="Distance tier failed — the full hair is used"
        feedback={feedback} order={HAIRDECK_ORDER} runLabel={refitLabel} />
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

/** The line after a Wear or a hair mode change: the character's pending changes and
 *  ONE "Build (cost)" button (POST /characters/{n}/figure/build — a manual
 *  Build); its reason under it when there is nothing to build. */
export function FigureBuildLine({ character, version }: { character: string; version: number }) {
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
