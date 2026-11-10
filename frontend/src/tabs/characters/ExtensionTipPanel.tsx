/**
 * ExtensionTipPanel — one pair tip extension group of the base model, in the
 * Base body tab's side column next to the viewer: where its tips sit (the
 * colour marker or, without one, the geometry crest as a suggestion), an
 * offset per side (up / away from the midline, mm), mirror, and a colour
 * disc painted into the texture around each tip.
 *
 * Backend: `extension_tips[]` of GET /characters/{c}/base-body
 * (`app/core/extension_tip.py::tip_panels`); Apply/Reset POST
 * /characters/{c}/model3d/extension-tip {signature, group, tip} — the server
 * stores the override and rebuilds the model's extension rig in the
 * background; the caller polls until `running` ends and the viewer reloads.
 *
 * While the sliders move, `onPreview` hands the caller dots for the viewer:
 * the built tip moved by the draft's difference along the surface tangents
 * there — a preview only; the build walks the real surface.
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { ExtensionTipOverride, ExtensionTipPanelInfo } from './useBaseBody'

export type TipDots = Array<{ at: [number, number, number]; color: string }>

const BUILT_COLOR = '#3fb950'
const DRAFT_COLOR = '#f0b35c'

function draftOf(panel: ExtensionTipPanelInfo): ExtensionTipOverride {
  const stored = panel.override
  const offsets = [0, 1].map((i) => ({ up: stored?.offsets?.[i]?.up ?? 0, out: stored?.offsets?.[i]?.out ?? 0 }))
  return { offsets, mirror: !!stored?.mirror, disc: { ...panel.limits.disc_defaults, ...stored?.disc } }
}

const keyOf = (value: ExtensionTipOverride) => JSON.stringify(value)

export function ExtensionTipPanel({ character, signature, panel, disabled, onPreview, onStarted }: {
  character: string
  /** The model the panel acts on (the base signature). */
  signature: string
  panel: ExtensionTipPanelInfo
  disabled: boolean
  onPreview: (group: string, dots: TipDots | null) => void
  onStarted: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
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
  const changed = keyOf(draft) !== storedKey
  const limit = panel.limits.offset_max_mm
  const busy = disabled || posting || panel.running

  useEffect(() => {
    const dots: TipDots = []
    panel.sides.forEach((side, i) => {
      if (!side) return
      const base = side.tip ?? side.suggested
      const built = side.tip ? side.offset_mm : [0, 0]
      const offset = draft.offsets[draft.mirror ? 0 : i]
      const du = (offset.up - built[0]) / 1000
      const dout = (offset.out - built[1]) / 1000
      const moved = Math.abs(du) > 1e-9 || Math.abs(dout) > 1e-9
      dots.push({
        at: [0, 1, 2].map((k) => base[k] + du * side.tangent_up[k] + dout * side.tangent_out[k]) as [number, number, number],
        color: moved ? DRAFT_COLOR : BUILT_COLOR,
      })
    })
    onPreview(panel.id, dots.length ? dots : null)
  }, [draft, onPreview, panel.id, panel.sides])
  useEffect(() => () => onPreview(panel.id, null), [onPreview, panel.id])

  const setOffset = (i: number, key: 'up' | 'out', value: number) => setDraft((previous) => {
    const offsets = previous.offsets.map((row) => ({ ...row }))
    offsets[i][key] = value
    if (previous.mirror) offsets[1 - i][key] = value
    return { ...previous, offsets }
  })

  const send = async (tip: ExtensionTipOverride | null) => {
    setPosting(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/model3d/extension-tip`,
        { signature, group: panel.id, tip })
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setPosting(false) }
  }

  const moved = draft.offsets.some((row) => row.up || row.out)
  const source = panel.tip_source === 'colour' ? t('Position: colour marker')
    : panel.tip_source === 'geometry' ? t('Position: geometry (suggestion)') : t('Position: not found')
  const state = panel.running ? t('Rebuilding…')
    : panel.error ? `${t('Failed')}: ${panel.error}`
    : panel.status !== 'applied' ? `${t('Not built')}${panel.reason ? `: ${panel.reason}` : ''}`
    : panel.disc?.status === 'failed' ? `${t('Colour disc failed')}: ${panel.disc.reason}`
    : ''
  const help = t('Where the tips of this group sit. Without a colour marker the geometry crest is a suggestion; move each tip along the body surface (up, and away from the midline) and add a colour disc around it. Apply rebuilds the extension bones of the base model; outfit models built on it take its tips and texture.')
  const sideLabel = (i: number) => panel.sides[i]?.side === 'right' ? t('Right') : t('Left')

  return (
    <fieldset className="ga-fieldset ga-model3d-group" title={help}>
      <legend>{panel.label}</legend>
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
              disabled={busy || (draft.mirror && i === 1) || !panel.sides[i]}
              onChange={(event) => setOffset(i, key, Number(event.target.value))} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{draft.offsets[i][key].toFixed(1)} mm</span>
          </label>
        )))}
      </div>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <input type="checkbox" checked={draft.mirror} disabled={busy}
          onChange={(event) => setDraft((previous) => ({ ...previous, mirror: event.target.checked,
            offsets: event.target.checked ? [{ ...previous.offsets[0] }, { ...previous.offsets[0] }] : previous.offsets }))} />
        {t('Mirror (both sides alike)')}
      </label>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <input type="checkbox" checked={draft.disc.enabled} disabled={busy}
          onChange={(event) => setDraft((previous) => ({ ...previous, disc: { ...previous.disc, enabled: event.target.checked } }))} />
        {t('Colour disc')}
        <input type="color" value={draft.disc.color} disabled={busy || !draft.disc.enabled}
          aria-label={t('Disc colour')}
          onChange={(event) => setDraft((previous) => ({ ...previous, disc: { ...previous.disc, color: event.target.value } }))} />
      </label>
      {draft.disc.enabled ? (
        <div className="ga-collision-grid">
          <label style={{ display: 'contents' }}>
            <span>{t('Diameter')}</span>
            <input type="range" min={panel.limits.diameter_mm[0]} max={panel.limits.diameter_mm[1]} step={1}
              value={draft.disc.diameter_mm} disabled={busy}
              onChange={(event) => setDraft((previous) => ({ ...previous,
                disc: { ...previous.disc, diameter_mm: Number(event.target.value) } }))} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{draft.disc.diameter_mm.toFixed(0)} mm</span>
          </label>
          <label style={{ display: 'contents' }}>
            <span>{t('Soft edge')}</span>
            <input type="range" min={0} max={panel.limits.soft_max_mm} step={0.5}
              value={draft.disc.soft_mm} disabled={busy}
              onChange={(event) => setDraft((previous) => ({ ...previous,
                disc: { ...previous.disc, soft_mm: Number(event.target.value) } }))} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{draft.disc.soft_mm.toFixed(1)} mm</span>
          </label>
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !changed}
          title={changed ? t('Unsaved changes') : undefined}
          onClick={() => void send(draft)}>{t('Apply')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !changed}
          onClick={() => setDraft(stored)}>{t('Revert')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !panel.override}
          onClick={() => void send(null)}>{t('Reset')}</button>
      </div>
    </fieldset>
  )
}
