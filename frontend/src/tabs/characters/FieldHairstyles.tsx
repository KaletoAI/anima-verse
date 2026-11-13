/**
 * FieldHairstyles — the character tab "Hairstyles" (plan
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 14, Rulings P2/P3; the user's rule R1–R4 for
 * every flow of the character area). A special tab placed directly after the Wardrobe (CharactersTab), for
 * humanoids. The Wardrobe shows no hair at all (P3); the Figure tab keeps its hair row (name + mode).
 *
 * Left: the hairstyles the character owns (GET /characters/{c}/hairstyles — worn first, "<name> · <mode>",
 * `hairstyleRows`), each with its freshness and "Wear" (POST …/hairstyles/{id}/wear — an outfit change: the
 * Build is requested, nothing else runs), and "New hairstyle" (a createPortal dialog: description + mode; HAAR
 * listed disabled "not built yet", an empty description disables Create with "Describe the hairstyle"; POST
 * …/hairstyles — starts nothing). After a Wear or a mode change the character's pending changes and its ONE
 * Build (FigureBuildLine).
 *
 * Right, for the SELECTED hairstyle (GET /characters/{c}/hair?item_id=, polled while a run goes — useGarment):
 * - a live 3D preview (orbit / zoom, the old Hair tab's): HairDeck — the hair fitted on the plain body
 *   (`garment.preview_url`, with the base model's capsules); `body` — the plain body itself when this hairstyle
 *   is the plain body's (`body_url`); otherwise why there is none;
 * - Settings, each SAVED ON ITS OWN, nothing runs (R3): the mode (POST …/hair/method {method, item_id}), the
 *   HairDeck colour (POST …/hair/colour), placement forward / tilt / width (POST …/hair/placement) and Swing /
 *   Stiffness with the chain count (POST …/hair/motion) — a saved value makes the fit stale;
 * - Run (R1/R2): HairDeck has two steps (HairDeck → fit), so it has "Run all" that skips what is current
 *   (POST …/garments/{item}/run {}; its label from `garments.run_estimate`: "Run all: create + fit (1 hub job)",
 *   "Run all: re-fit (no hub job)", disabled "Everything is current"), and the single steps that re-run even
 *   when current: "Regenerate hair (HairDeck) — 1 hub job" and "Re-fit — no hub job". A `body` hairstyle has
 *   no run of its own — its hair is part of the body, the Figure tab's Build makes it (R4: no legacy steps, no
 *   "other methods" results).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { FreshnessBadge } from './FreshnessBadge'
import type { Freshness } from './FreshnessBadge'
import { GarmentFailure, RunButton, RunStatusLine } from './GarmentSteps'
import { HAIR_STEP_LABELS, ROW, WARN_STYLE } from './garmentStyle'
import type { GarmentRunBody } from './garmentStyle'
import { HairDeckPlacement } from './HairDeckPlacement'
import { FigureBuildLine, HairColour, HairDeckSteps } from './HairstyleParts'
import { Model3DViewer } from './Model3DViewer'
import {
  ESTIMATE_NOTE, HAIR_MODES, HAIR_MODE_HINTS, HAIR_MODE_LABELS, HAIRSTYLE_SAVED_NOTE, hairModeDisabled,
  hairstyleActions, hairstyleRows, newHairstyleDisabled,
} from './figureModel'
import type { HairMode, Hairstyle, HairstylesPayload } from './figureModel'
import { garmentRunning, useGarment, useGarmentRun } from './useGarment'
import type { HairInfo } from './useGarment'

/** Why the served HairDeck fit is not the current one (`garments.garment_info` stale reasons). */
const STALE_LABELS: Record<string, string> = {
  description_changed: 'Hair description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  fit_algorithm_updated: 'Fit algorithm updated',
  hairdeck_changed: 'Profile picture or HairDeck settings changed',
  colour_changed: 'Hair colour changed',
  placement_changed: 'Hair placement changed',
  swing_changed: 'Swing changed',
}

const PREVIEW_HEIGHT = 420

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
        style={{ maxWidth: 520 }}>
        <div className="ga-modal-header"><h3>{t('New hairstyle')}</h3></div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
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
          </label>
          <span className="ga-hint">{t(HAIR_MODE_HINTS[mode])}</span>
          <span className="ga-hint">{t('Creating runs nothing and wears nothing — Wear it, then the Build makes it.')}</span>
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

/** The selected hairstyle: its preview, its settings (saved on their own) and its run. */
function HairstyleDetail({ character, entry, onChanged, onRunEnded, onOpenFigure }: {
  character: string
  entry: Hairstyle
  /** The mode was saved: the list and the Build line reload. */
  onChanged: () => void
  /** A run of this hairstyle ended: the list (its freshness) reloads. */
  onRunEnded: () => void
  onOpenFigure?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const itemId = entry.id
  const { info, startPoll } = useGarment<HairInfo>(
    `/characters/${enc}/hair?item_id=${encodeURIComponent(itemId)}`)
  const { feedback, start, cancel } = useGarmentRun(character, itemId, info, startPoll)
  const [posting, setPosting] = useState(false)
  const [saved, setSaved] = useState(false)
  const wasRunning = useRef(false)
  const runningNow = !!info && garmentRunning(info)
  useEffect(() => {
    if (wasRunning.current && !runningNow) {
      setSaved(false)
      onRunEnded()
    }
    wasRunning.current = runningNow
  }, [runningNow, onRunEnded])

  const save = useCallback(async (path: string, body: Record<string, unknown>) => {
    if (posting) return false
    setPosting(true)
    try {
      await apiPost(`/characters/${enc}/${path}`, { ...body, item_id: itemId })
      setSaved(true)
      return true
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return false
    } finally {
      setPosting(false)
      startPoll(300)
    }
  }, [enc, itemId, posting, startPoll, t, toast])

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) return <div className="ga-hint">{t('Hairstyles are for humanoid characters only.')}</div>

  const mode: HairMode = (HAIR_MODES as string[]).includes(info.method) ? info.method as HairMode : 'hairdeck'
  const garment = info.garment
  const running = garmentRunning(info)
  const busy = posting || feedback.pending !== null || running
  const hd = mode === 'hairdeck' ? info.hairdeck : null
  const actions = hairstyleActions(mode, info.run, t)
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  const setMode = async (next: HairMode) => {
    if (hairModeDisabled(next) || next === mode) return
    if (await save('hair/method', { method: next })) onChanged()
  }

  let preview
  if (mode === 'hairdeck' && garment?.preview_url) {
    preview = (
      <>
        <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={PREVIEW_HEIGHT}
          freshness={garment.preview_freshness} collision={info.collision} />
        <div className="ga-hint">
          {info.collision?.capsules?.length
            ? t('Fitted on the plain body; collides with its torso, arm and head capsules')
            : t('Fitted on the plain body; no capsule set on the base model yet — the hair is shown as skinned')}
        </div>
      </>
    )
  } else if (mode === 'body' && info.plain && info.body_url) {
    preview = (
      <>
        <Model3DViewer key={info.body_url} url={info.body_url} format="glb" height={PREVIEW_HEIGHT} />
        <div className="ga-hint">{t('The plain body — this hairstyle is part of its mesh')}</div>
      </>
    )
  } else {
    preview = (
      <div className="ga-hint" style={{ padding: '24px 8px' }}>
        {mode === 'hairdeck'
          ? t('No fitted hair yet — Run all makes it')
          : mode === 'body'
            ? t('Its body shape is made by the Build when it is worn — the Figure tab shows the figure')
            : t('HAAR hair is not built yet')}
      </div>
    )
  }

  const prompts = info.base_prompts
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Preview')}</span>
      {preview}

      <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Settings')}</span>
      <div className="ga-hint">{t('Each setting is saved on its own — nothing runs.')}</div>
      <div style={ROW}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4 }} title={t(HAIR_MODE_HINTS[mode])}>
          <span className="ga-hint">{t('Mode')}</span>
          <select className="ga-input" style={{ width: 'auto' }} value={mode}
            disabled={!info.pipeline || busy} aria-label={t('Hair mode')}
            onChange={(e) => { void setMode(e.target.value as HairMode) }}>
            {HAIR_MODES.map((m) => (
              <option key={m} value={m} disabled={!!hairModeDisabled(m)}>{t(HAIR_MODE_LABELS[m])}</option>
            ))}
          </select>
        </label>
        <span className="ga-hint">{t(HAIR_MODE_LABELS.haar)}: {t(hairModeDisabled('haar') || '')}</span>
      </div>
      <span className="ga-hint">{t(HAIR_MODE_HINTS[mode])}</span>
      {!info.pipeline ? (
        <div className="ga-hint" style={WARN_STYLE}>
          {t('A temporary NPC has no figure — its hairstyles are not built.')}
        </div>
      ) : null}
      <div style={ROW}>
        <span className="ga-hint">{t('Description')}:</span>
        <span>{info.description || entry.description}</span>
      </div>
      {hd ? (
        <>
          <div className="ga-fieldset-title">{t('Hair colour')}</div>
          <HairColour
            key={`${itemId}|${hd.colour.target || ''}|${hd.colour.profile?.hex || ''}|${hd.colour.auto || ''}`}
            colour={hd.colour}
            busy={busy}
            running={running}
            onApply={(hex) => { void save('hair/colour', { hex }) }}
          />
          {hd.placement ? (
            <>
              <div className="ga-fieldset-title">{t('Hair placement')}</div>
              <HairDeckPlacement character={character} itemId={itemId} method="hairdeck"
                placement={hd.placement} chains={hd.chains}
                swingPending={!!garment?.stale_reasons.includes('swing_changed')}
                busy={busy} running={running} onSaved={() => { setSaved(true); startPoll(300) }} />
            </>
          ) : null}
        </>
      ) : null}
      {saved && actions.runAll && !actions.runAll.disabled ? (
        <div className="ga-hint" style={WARN_STYLE}>{t(HAIRSTYLE_SAVED_NOTE)}</div>
      ) : null}

      <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Run')}</span>
      <div style={ROW}>
        <span className="ga-hint">{t('Status')}:</span>
        <FreshnessBadge freshness={entry.freshness as Freshness | null} compact />
      </div>
      {mode === 'hairdeck' && info.pipeline ? (
        <>
          <RunStatusLine garment={garment} feedback={feedback} stepLabels={HAIR_STEP_LABELS}
            onCancel={() => { void cancel() }} />
          <GarmentFailure garment={garment} stepLabels={HAIR_STEP_LABELS} />
          {garment && garment.stale_reasons.length ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {garment.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              {' — '}{t('the previous hair stays in use until the new one is fitted')}
            </div>
          ) : null}
          {actions.runAll ? (
            <div style={ROW}>
              <RunButton
                feedback={feedback}
                slot="all"
                primary
                disabled={busy || !garment || actions.runAll.disabled}
                title={[t('Runs every step that is missing or out of date'), info.run?.note || ''].filter(Boolean)
                  .join(' — ')}
                onClick={() => onRun({}, 'all')}
                label={actions.runAll.label}
              />
              {info.run?.hub_jobs ? <span className="ga-hint">{t(ESTIMATE_NOTE)}</span> : null}
            </div>
          ) : null}
          {hd && actions.regenerate && actions.refit ? (
            <HairDeckSteps info={info} hd={hd} busy={busy} onRun={onRun} feedback={feedback}
              regenerateLabel={actions.regenerate} refitLabel={actions.refit} />
          ) : null}
        </>
      ) : mode === 'body' ? (
        <>
          <div className="ga-hint">
            {t('In the body: no run of its own — the hair is part of the body mesh, the Figure tab’s Build makes it.')}
          </div>
          {prompts ? (
            <div style={ROW}>
              <span className="ga-hint">{t('Base body prompts')}</span>
              <FreshnessBadge freshness={prompts} compact />
            </div>
          ) : null}
          {onOpenFigure ? (
            <div><button type="button" className="ga-btn ga-btn-sm" onClick={onOpenFigure}>
              ↗ {t('Figure')}
            </button></div>
          ) : null}
        </>
      ) : null}
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
  const [list, setList] = useState<HairstylesPayload | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState('')
  const [dialog, setDialog] = useState(false)
  const [posting, setPosting] = useState(false)
  // Bumped by every Wear / mode change: the Build line shows (and reloads).
  const [changed, setChanged] = useState(0)

  const load = useCallback(async () => {
    try {
      setList(await apiGet<HairstylesPayload>(`/characters/${enc}/hairstyles`))
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
  const rows = hairstyleRows(list.hairstyles, wornId, t)
  const current = rows.find((h) => h.id === selected) || rows[0] || null

  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={ROW}>
          <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Hairstyles')}</span>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" onClick={() => setDialog(true)}>
            {t('New hairstyle')}
          </button>
        </div>
        {!rows.length ? (
          <div className="ga-hint">{t('No hairstyle yet — the Build makes the first one from Appearance, or create one.')}</div>
        ) : null}
        {rows.map((h) => (
          <div key={h.id} role="button" tabIndex={0}
            onClick={() => setSelected(h.id)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSelected(h.id) }}
            style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
              borderLeft: `3px solid ${h.worn ? 'var(--accent, #58a6ff)' : 'rgba(255,255,255,0.18)'}`,
              background: current?.id === h.id ? 'rgba(120,170,255,0.16)' : 'rgba(255,255,255,0.04)',
            }}>
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={h.description}>
                {h.label}
              </span>
              <span style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.75em' }}>
                {h.worn ? <span className="ga-hint">{t('Worn')}</span> : null}
                {h.plain ? <span className="ga-hint">{t('Plain body')}</span> : null}
                <FreshnessBadge freshness={h.freshness as Freshness | null} compact />
              </span>
            </div>
            <button type="button" className="ga-btn ga-btn-sm" disabled={h.worn || posting}
              title={h.worn ? t('Worn now') : t('Wearing it is an outfit change — the Build makes it')}
              onClick={(e) => { e.stopPropagation(); void wear(h.id) }}>
              {t('Wear')}
            </button>
          </div>
        ))}
        {changed > 0 ? <FigureBuildLine character={character} version={changed} /> : null}
      </div>
      <div className="ga-split-col">
        {current ? (
          <HairstyleDetail key={current.id} character={character} entry={current} onOpenFigure={onOpenFigure}
            onChanged={() => { setChanged((v) => v + 1); void load() }} onRunEnded={reloadList} />
        ) : (
          <div className="ga-hint">{t('Select a hairstyle')}</div>
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
