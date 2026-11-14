/**
 * ExtensionTipPanel — one pair tip extension group of the base model, in the
 * Base body tab's Extension bones sub-tab: EVERYTHING of the group in one box
 * (Ruling A53) — its light with the reason and "Built <time>", the Enabled
 * switch, where its tips sit (the colour marker or, without one, the geometry
 * crest as a suggestion), an offset per side (up / away from the midline, mm),
 * the markers, mirror, the colour disc painted into the texture around each
 * tip, the length and diameter factors, and Save / Discard changes / Reset to
 * default / Rebuild. The Extension bones box beside it lists only the groups
 * without a tip panel.
 *
 * Backend: `extension_tips[]` of `plain_body` in GET /characters/{c}/figure?plain=1
 * (`app/core/extension_tip.py::tip_panels`, grouped by `group_tip_settings`:
 * `light`, `controls`, `built_at`). Settings are saved on their own (rule R3):
 * Save / Reset / the Enabled box POST /characters/{c}/model3d/extension-tip
 * {signature, group, tip | enabled} — stored, nothing rebuilt; the panel then
 * says "Saved — not built yet" (`due`) and the Base body tab's Run all picks
 * the rebuild up. The length and diameter factors are motion values, saved
 * character-wide by the caller (`motion.onSave`, POST …/model3d/extension-motion)
 * — they act at once, and the viewer shows the draft while a slider moves
 * (`motion.onPreview`). Rebuild (rule R2, also when current) POST
 * …/model3d/extension-tip/apply {signature}: the CPU extension rebuild in the
 * background, no hub job; the caller polls until `running` ends.
 *
 * While "Show markers" is on, `onPreview` hands the caller dots for the
 * viewer (`tipPreviewDots`): the built tip moved by the draft's difference
 * along the surface tangents there — a preview only; the build walks the real
 * surface. The box starts off on every load (Ruling A62, not saved); moving a
 * position slider turns it on.
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useClockSettings } from '../../lib/clockFormat'
import type { Physics } from '../../lib/motionDraft'
import { useToast } from '../../lib/Toast'
import { stampLabel } from './freshnessText'
import { StepLight } from './StepRows'
import type { ExtensionTipOverride, ExtensionTipPanelInfo } from './useBaseBody'
import { TIP_DUE_NOTE, TIP_MARKERS_START_SHOWN, TIP_REBUILD_LABEL, tipPreviewDots } from './baseBodyModel'
import type { TipDots } from './baseBodyModel'

function draftOf(panel: ExtensionTipPanelInfo): ExtensionTipOverride {
  const stored = panel.override
  const offsets = [0, 1].map((i) => ({ up: stored?.offsets?.[i]?.up ?? 0, out: stored?.offsets?.[i]?.out ?? 0 }))
  return { offsets, mirror: !!stored?.mirror, disc: { ...panel.limits.disc_defaults, ...stored?.disc } }
}

const keyOf = (value: unknown) => JSON.stringify(value)

/** The motion factors a tip panel edits (the group's `controls`), their range and their words. */
const FACTORS: Array<{ key: 'length' | 'girth'; label: string; max: number }> = [
  { key: 'length', label: 'Length factor (1 = as modelled)', max: 3 },
  { key: 'girth', label: 'Diameter factor (1 = as modelled)', max: 2 },
]

/** The group's motion values: the defaults, the saved overrides, how to save them and how to preview a draft. */
export interface TipMotion {
  defaults: Physics | undefined
  overrides: Physics | undefined
  /** Saves the given values into the group's overrides (character-wide; they act at once). */
  onSave: (values: Physics) => Promise<boolean>
  /** Drops the group's overrides (Reset to default). */
  onReset: () => Promise<boolean>
  /** The viewer shows the draft (null: back to the saved values). */
  onPreview: (values: Physics | null) => void
}

export function ExtensionTipPanel({ character, signature, panel, disabled, onPreview, onStarted, motion, wide }: {
  character: string
  /** The model the panel acts on (the base signature). */
  signature: string
  panel: ExtensionTipPanelInfo
  disabled: boolean
  onPreview: (group: string, dots: TipDots | null) => void
  onStarted: () => void
  /** The length / diameter factors (absent: the group declares none, or no motion defaults yet). */
  motion?: TipMotion
  /** A lone panel spans both columns of the grid. */
  wide?: boolean
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  useClockSettings()   // re-render when the clock settings change ("Built <time>")
  const stored = useMemo(() => draftOf(panel), [panel])
  const [draft, setDraft] = useState<ExtensionTipOverride>(stored)
  const [posting, setPosting] = useState(false)
  // A poll that brings the same stored values keeps the draft; new ones replace it.
  const storedKey = keyOf(stored)
  const [seenKey, setSeenKey] = useState(storedKey)
  if (seenKey !== storedKey) {
    setSeenKey(storedKey)
    setDraft(stored)
  }
  // The factors the group declares and has defaults for; their saved values (override, else default, else 1).
  const factors = FACTORS.filter((f) => (panel.controls ?? []).includes(f.key) && motion?.defaults
    && motion.defaults[f.key] !== undefined)
  const storedFactors = Object.fromEntries(factors.map((f) =>
    [f.key, Number(motion?.overrides?.[f.key] ?? motion?.defaults?.[f.key] ?? 1)])) as Record<string, number>
  const storedFactorsKey = keyOf(storedFactors)
  const [factorDraft, setFactorDraft] = useState<Record<string, number>>(storedFactors)
  const [seenFactorsKey, setSeenFactorsKey] = useState(storedFactorsKey)
  if (seenFactorsKey !== storedFactorsKey) {
    setSeenFactorsKey(storedFactorsKey)
    setFactorDraft(storedFactors)
  }
  const tipChanged = keyOf(draft) !== storedKey
  const factorsChanged = keyOf(factorDraft) !== storedFactorsKey
  const changed = tipChanged || factorsChanged
  const hasFactorOverride = factors.some((f) => motion?.overrides?.[f.key] !== undefined)
  // The dots cover the very tips they mark: off on every load (Ruling A62 — a view switch of the open tab, never
  // saved), on by the box, and on as soon as a slider moves.
  const [showDots, setShowDots] = useState(TIP_MARKERS_START_SHOWN)
  const limit = panel.limits.offset_max_mm
  const busy = disabled || posting || panel.running
  // This model's own switch for the group (extension_rig_models[sig][group].enabled) — only here: the Extension
  // bones box no longer lists tip groups (Ruling A53). Off: no tip bone,
  // stub or disc; the controls rest until it is on again.
  const off = panel.enabled === false
  const locked = busy || off

  useEffect(() => {
    onPreview(panel.id, tipPreviewDots(panel, draft, showDots, off))
  }, [draft, off, onPreview, panel, showDots])
  useEffect(() => () => onPreview(panel.id, null), [onPreview, panel.id])

  const setOffset = (i: number, key: 'up' | 'out', value: number) => { setShowDots(true); setDraft((previous) => {
    const offsets = previous.offsets.map((row) => ({ ...row }))
    offsets[i][key] = value
    if (previous.mirror) offsets[1 - i][key] = value
    return { ...previous, offsets }
  }) }

  // Save (rule R3): the settings only — nothing is rebuilt; the poll then reports `due`.
  const send = async (change: { tip: ExtensionTipOverride | null } | { enabled: boolean }, quiet = false) => {
    setPosting(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/model3d/extension-tip`,
        { signature, group: panel.id, ...change })
      if (!quiet) toast(t('Saved'))
      onStarted()
      return true
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return false
    } finally { setPosting(false) }
  }
  // One Save for the whole group: the tip settings (rebuilt by Rebuild / Run all) and the factors (act at once).
  const save = async () => {
    if (tipChanged && !(await send({ tip: draft }, factorsChanged))) return
    if (factorsChanged && motion) {
      setPosting(true)
      try { if (await motion.onSave(factorDraft)) motion.onPreview(null) } finally { setPosting(false) }
    }
  }
  const discard = () => {
    setDraft(stored)
    setFactorDraft(storedFactors)
    motion?.onPreview(null)
  }
  const reset = async () => {
    if (panel.override && !(await send({ tip: null }, hasFactorOverride))) return
    if (hasFactorOverride && motion) {
      setPosting(true)
      try { if (await motion.onReset()) motion.onPreview(null) } finally { setPosting(false) }
    }
  }
  const setFactor = (key: string, value: number) => {
    const next = { ...factorDraft, [key]: value }
    setFactorDraft(next)
    motion?.onPreview(next)
  }
  // Rebuild (rule R2): the model's extension bones from the saved settings — also when they are built already.
  const rebuild = async () => {
    setPosting(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/model3d/extension-tip/apply`, { signature })
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setPosting(false) }
  }

  const moved = draft.offsets.some((row) => row.up || row.out)
  const source = panel.tip_source === 'colour' ? t('Position: colour marker')
    : panel.tip_source === 'geometry' ? t('Position: geometry (suggestion)') : t('Position: not found')
  // Saved settings not built yet outrank a green record: the light turns yellow and says so (one line, not two).
  const dueLight = !!panel.due && !panel.running && panel.light?.light === 'green'
  const state = panel.running ? t('Rebuilding…')
    : off ? t('Group switched off for this model')
    : panel.active === false ? t('Source group switched off for this model')
    : panel.error ? `${t('Failed')}: ${panel.error}`
    : panel.status !== 'applied' ? `${t('Not built')}${panel.reason ? `: ${panel.reason}` : ''}`
    : panel.due && !dueLight ? t(TIP_DUE_NOTE)
    : panel.disc?.status === 'failed' ? `${t('Colour disc failed')}: ${panel.disc.reason}`
    : ''
  const help = t('Everything of this tip group in one place. Without a colour marker the geometry crest is a suggestion; move each tip along the body surface (up, and away from the midline) and add a colour disc around it. Save stores the settings without building; Rebuild (or Run all) rebuilds the extension bones of the base model; outfit models built on it take its tips and texture. The length and diameter factors act at once.')
  const sideLabel = (i: number) => panel.sides[i]?.side === 'right' ? t('Right') : t('Left')
  const light = dueLight && panel.light ? { ...panel.light, light: 'yellow' as const, state: TIP_DUE_NOTE, reason: '' }
    : panel.light
  const builtAt = panel.built_at ? stampLabel(panel.built_at) || panel.built_at : ''

  return (
    <fieldset className={`ga-fieldset ga-model3d-group${wide ? ' ga-ext-wide' : ''}`} title={help}>
      <legend>{panel.label}</legend>
      {light ? (
        <div className="ga-ext-light" data-light={light.light} aria-live="polite"
          title={light.detail ? `${t('Build record')}: ${light.detail}` : undefined}>
          <StepLight light={light.light} /> <strong>{t(light.state)}</strong>
          {light.reason ? <> — {t(light.reason)}</> : null}
          {light.detail && light.light === 'red' ? <span className="ga-hint"> ({light.detail})</span> : null}
        </div>
      ) : null}
      {builtAt ? <div className="ga-hint" style={{ fontSize: 10, margin: 0 }}>{t('Built')} {builtAt}</div> : null}
      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}
        title={t('Off builds this model without the tips of this group: no tip bone, no stub, no colour disc.')}>
        <input type="checkbox" checked={!off} disabled={busy}
          onChange={(event) => void send({ enabled: event.target.checked })} />
        {t('Enabled')}
      </label>
      <div className="ga-hint" style={{ fontSize: 10, margin: 0 }}>
        {source}{moved ? ` · ${t('moved')}` : ''}
      </div>
      {state ? (
        <div className="ga-hint" role={panel.error ? 'alert' : undefined} title={state}
          style={{ fontSize: 10, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {state}
        </div>
      ) : null}
      <div className="ga-collision-grid">
        {[0, 1].map((i) => (['up', 'out'] as const).map((key) => (
          <label key={`${i}-${key}`} style={{ display: 'contents' }}>
            <span>{sideLabel(i)} {key === 'up' ? t('up') : t('out')}</span>
            <input type="range" min={-limit} max={limit} step={0.5} value={draft.offsets[i][key]}
              disabled={locked || (draft.mirror && i === 1) || !panel.sides[i]}
              onChange={(event) => setOffset(i, key, Number(event.target.value))} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{draft.offsets[i][key].toFixed(1)} mm</span>
          </label>
        )))}
      </div>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}
        title={t('Hide the dots to look at the built tips; moving a slider shows them again.')}>
        <input type="checkbox" checked={showDots} onChange={(event) => setShowDots(event.target.checked)} />
        {t('Show markers')}
      </label>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <input type="checkbox" checked={draft.mirror} disabled={locked}
          onChange={(event) => setDraft((previous) => ({ ...previous, mirror: event.target.checked,
            offsets: event.target.checked ? [{ ...previous.offsets[0] }, { ...previous.offsets[0] }] : previous.offsets }))} />
        {t('Mirror (both sides alike)')}
      </label>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <input type="checkbox" checked={draft.disc.enabled} disabled={locked}
          onChange={(event) => setDraft((previous) => ({ ...previous, disc: { ...previous.disc, enabled: event.target.checked } }))} />
        {t('Colour disc')}
        <input type="color" value={draft.disc.color} disabled={locked || !draft.disc.enabled}
          aria-label={t('Disc colour')}
          onChange={(event) => setDraft((previous) => ({ ...previous, disc: { ...previous.disc, color: event.target.value } }))} />
      </label>
      {draft.disc.enabled ? (
        <div className="ga-collision-grid">
          <label style={{ display: 'contents' }}>
            <span>{t('Diameter')}</span>
            <input type="range" min={panel.limits.diameter_mm[0]} max={panel.limits.diameter_mm[1]} step={1}
              value={draft.disc.diameter_mm} disabled={locked}
              onChange={(event) => setDraft((previous) => ({ ...previous,
                disc: { ...previous.disc, diameter_mm: Number(event.target.value) } }))} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{draft.disc.diameter_mm.toFixed(0)} mm</span>
          </label>
          <label style={{ display: 'contents' }}>
            <span>{t('Soft edge')}</span>
            <input type="range" min={0} max={panel.limits.soft_max_mm} step={0.5}
              value={draft.disc.soft_mm} disabled={locked}
              onChange={(event) => setDraft((previous) => ({ ...previous,
                disc: { ...previous.disc, soft_mm: Number(event.target.value) } }))} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{draft.disc.soft_mm.toFixed(1)} mm</span>
          </label>
        </div>
      ) : null}
      {factors.length ? (
        <div className="ga-collision-grid" style={{ marginTop: 4 }}>
          {factors.map((f) => (
            <label key={f.key} style={{ display: 'contents' }} title={t(f.label)}>
              <span>{t(f.label).split(' (')[0]}</span>
              <input type="range" min={0.5} max={f.max} step={0.05} value={factorDraft[f.key] ?? 1}
                disabled={locked} onChange={(event) => setFactor(f.key, Number(event.target.value))} />
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>× {(factorDraft[f.key] ?? 1).toFixed(2)}</span>
            </label>
          ))}
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={locked || !changed}
          title={changed ? t('Unsaved changes') : undefined}
          onClick={() => void save()}>{t('Save')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={locked || !changed}
          title={t('Back to the saved values')}
          onClick={discard}>{t('Discard changes')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={locked || !(panel.override || hasFactorOverride)}
          title={t('Saves the defaults (nothing is rebuilt)')}
          onClick={() => void reset()}>{t('Reset to default')}</button>
        <button type="button" className={`ga-btn ga-btn-sm${panel.due ? ' ga-btn-primary' : ''}`}
          disabled={busy || changed}
          title={changed ? t('Save or revert the changes first — Rebuild builds the saved settings')
            : t('Rebuilds the extension bones of the base model from the saved settings, also when they are built already.')}
          onClick={() => void rebuild()}>{t(TIP_REBUILD_LABEL)}</button>
      </div>
      <div className="ga-hint" style={{ fontSize: 10, margin: '2px 0 0' }}>
        {t('Position and colour disc take effect after Rebuild; length and diameter act at once.')}
      </div>
    </fieldset>
  )
}
