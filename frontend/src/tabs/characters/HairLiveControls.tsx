/**
 * HairLiveControls — the settings of a HairDeck or HAAR hairstyle that change its 3D preview, compact BESIDE the
 * viewer (FieldHairstyles passes them as the viewer's toolbar; Task UI4, the user's checklist points 2 and 4).
 * HAAR hair has no placement (its strands are registered on the head; strand-hair spec § 6.3.4): the group is
 * hidden, colour and motion stay.
 *
 * Every slider acts on the preview WHILE it is dragged (the drafts go up through `onDraft`; FieldHairstyles
 * turns them into the viewer's live vertex map, colour tint and spring frequencies) and is SAVED on its own
 * with its group's Save — saving runs nothing. What a save made due is written in the group
 * (`settingDue`: "Saved, not applied — Re-fit applies it (no hub job)").
 *
 * - Placement: forward shift (mm), up/down (mm, Ruling A85), forward tilt (°; back −15 … forward +30), hair width (×);
 *   each row's Auto clears that value, Automatic clears all four (POST /characters/{n}/hair/placement
 *   {forward_m, tilt_deg, width_scale, up_m, item_id}, null = automatic). Hovering a shift slider draws its
 *   centimetre ruler and the shift in the preview (`onRuler('forward' | 'up')`).
 * - Colour: a manual hair colour, Automatic clears it (POST …/hair/colour {hex, item_id}).
 * - Cut (HAAR only, Ruling A71): Length — the whole length, a maximum length (cm) or where the hair ends on the body
 *   (chin / shoulder / shoulder blades / mid back / waist) — and Ends, the soft tip (cm; Auto = the fit's default).
 *   The preview cuts the uncut cards live with the server's rule (`hairCut.ts`); Save stores the setting only
 *   (POST …/hair/cut {max_cm, at, ends_cm, item_id}, null = automatic) and the fit reads due — Re-fit cuts on the
 *   CPU (no hub job).
 * - Motion: Swing (saved at once — a fit input) and Stiffness (POST …/hair/motion {swing, stiffness,
 *   item_id}); Stiffness acts on the motion only, nothing becomes due. The preview runs the game's per-strand sim
 *   (strand-hair spec § 6.2.5): Stiffness acts on it live while dragged (`setStiffness`); the group's hint says
 *   whether the strands swing (`strandPreviewState`, `STRAND_PREVIEW_HINTS`).
 */
import { useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { CUT_AT_LABELS, STRAND_PREVIEW_HINTS, cutLabel, fittedPlacement, jobsLabel, settingDue } from './hairstylesModel'
import type { PlacementValues, StepInput, StrandPreviewState } from './hairstylesModel'
import { cutEqual, cutPostBody, normaliseCut } from './hairCut'
import type { HaarCutPanel, HairCut } from './hairCut'
import type { HairDeckPanel } from './useGarment'
import { Swatch } from './HairstyleParts'

/** What the sliders show right now (null = the stored value: nothing to preview). */
export interface HairDrafts {
  placement: PlacementValues | null
  colour: string | null
  stiffness: number | null
  /** The dragged HAAR cut (null = the stored one). */
  cut: HairCut | null
}

const GROUP: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 2, padding: '4px 8px 6px' }
const BTN_ROW: CSSProperties = { display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }
const DUE: CSSProperties = { color: 'var(--warning, #d29922)', fontSize: 10, overflowWrap: 'anywhere' }

function Slider({ label, value, shown, min, max, step, disabled, title, onChange, onFocus, onBlur, onAuto,
  autoLabel = 'Auto', autoTitle }: {
  label: string
  value: number
  shown: string
  min: number
  max: number
  step: number
  disabled: boolean
  title: string
  onChange: (v: number) => void
  onFocus?: () => void
  onBlur?: () => void
  /** The row's own "Auto" (back to automatic for this value only); absent = no button, null = shown disabled. */
  onAuto?: (() => void) | null
  autoLabel?: string
  autoTitle?: string
}) {
  return (
    <label className="ga-model3d-slider" title={title} style={{ gap: 0, fontSize: 10 }}
      onMouseEnter={onFocus} onMouseLeave={onBlur}>
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 4, alignItems: 'center' }}>
        <span>{label}</span>
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>{shown}</span>
          {onAuto !== undefined ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={disabled || !onAuto} title={autoTitle}
              style={{ fontSize: 9, padding: '0 4px', lineHeight: '14px' }}
              onClick={(e) => { e.preventDefault(); onAuto?.() }}>{autoLabel}</button>
          ) : null}
        </span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled}
        onFocus={onFocus} onBlur={onBlur} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="ga-fieldset ga-model3d-group" style={GROUP}>
      <span className="ga-fieldset-title" style={{ margin: 0, fontSize: 11 }}>{title}</span>
      {children}
    </div>
  )
}

export function HairLiveControls({ character, itemId, mode = 'hairdeck', hd, info, busy, previewSwings, strandIssue,
  cutPanel = null, cutLive = false, onDraft, onRuler, onSaved }: {
  character: string
  itemId: string
  /** The hairstyle's mode: HAAR hides the placement and names its own colour sources. */
  mode?: 'hairdeck' | 'haar'
  hd: HairDeckPanel
  /** The hair GET: what a save made due. */
  info: StepInput
  /** A hair step runs or a request is in flight: nothing is saved meanwhile. */
  busy: boolean
  /** `swings`: the preview runs every strand, the Stiffness drag acts on it; `swing_off`: Swing is off, the hair
   *  stays still; `no_preview`: there is no fitted hair to preview yet (`strandPreviewState`). */
  previewSwings: StrandPreviewState
  /** Why the strands do not swing although they should (no record for this fit, loading) — shown instead of
   *  the `swings` hint; null otherwise. */
  strandIssue?: string | null
  /** HAAR: the Cut control's block of the hair GET (`haar.cut`); null hides the group. */
  cutPanel?: HaarCutPanel | null
  /** The preview can cut live (the uncut cards of the shown fit are loaded). */
  cutLive?: boolean
  onDraft: (d: HairDrafts) => void
  /** A shift ruler is wanted in the preview (its slider is hovered or focused): forward, up/down or none. */
  onRuler: (which: 'forward' | 'up' | null) => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const p = hd.placement
  const fitted = fittedPlacement(p)
  // The stored values as the sliders show them (automatic = what the fit used / will use).
  const stored: PlacementValues = {
    forward_m: p.forward_m ?? (p.fitted?.forward_source === 'default' ? fitted.forward_m : p.default_forward_m),
    tilt_deg: p.tilt_deg ?? fitted.tilt_deg,
    width_scale: p.width_scale ?? fitted.width_scale,
    up_m: p.up_m ?? 0,
  }
  const [placement, setPlacement] = useState<PlacementValues | null>(null)
  // Which placement values were dragged: an untouched one keeps its stored value (automatic stays automatic).
  const [touched, setTouched] = useState<Partial<Record<keyof PlacementValues, boolean>>>({})
  const colourStored = hd.colour.target || hd.colour.profile?.hex || hd.colour.auto || '#7f6248'
  const [colour, setColour] = useState<string | null>(null)
  const chains = hd.chains
  const [stiffness, setStiffness] = useState<number | null>(null)
  const [cut, setCut] = useState<HairCut | null>(null)
  const [posting, setPosting] = useState(false)
  const off = busy || posting

  // A new server answer: the drafts restart from it.
  const cutSaved = normaliseCut(cutPanel?.saved)
  const serverKey = `${itemId}|${p.forward_m}|${p.tilt_deg}|${p.width_scale}|${p.up_m}|${hd.colour.target}|${chains?.stiffness}`
    + `|${JSON.stringify(cutSaved)}`
  useEffect(() => {
    setPlacement(null); setTouched({}); setColour(null); setStiffness(null); setCut(null)
  }, [serverKey])
  useEffect(() => {
    onDraft({ placement, colour, stiffness, cut })
  }, [placement, colour, stiffness, cut, onDraft])

  const post = async (path: string, body: Record<string, unknown>) => {
    if (posting) return
    setPosting(true)
    try {
      await apiPost(`/characters/${enc}/hair/${path}`, { ...body, item_id: itemId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onSaved()
    }
  }

  const cur = placement ?? stored
  const lim = p.limits
  const manual = p.forward_m !== null || p.tilt_deg !== null || p.width_scale !== null || p.up_m !== null
  const edit = (patch: Partial<PlacementValues>) => {
    setPlacement({ ...cur, ...patch })
    setTouched((prev) => ({ ...prev, ...Object.fromEntries(Object.keys(patch).map((k) => [k, true])) }))
  }
  /** The value a Save sends: the dragged one, else the stored one (null = automatic). */
  const sent = (key: keyof PlacementValues) => (touched[key] && placement ? placement[key] ?? null : p[key])
  const KEYS: Array<keyof PlacementValues> = ['forward_m', 'tilt_deg', 'width_scale', 'up_m']
  /** A row's Auto: a stored manual value is cleared at once (the others keep their stored values, nothing runs);
   *  a value only dragged goes back to its stored one. null when the row is automatic and untouched. */
  const autoOf = (key: keyof PlacementValues): (() => void) | null => {
    if (p[key] !== null) {
      return () => { void post('placement', Object.fromEntries(KEYS.map((k) => [k, k === key ? null : p[k]]))) }
    }
    if (!touched[key] || !placement) return null
    return () => {
      const next = { ...placement, [key]: stored[key] }
      const left = { ...touched, [key]: false }
      setTouched(left)
      setPlacement(KEYS.some((k) => left[k]) ? next : null)
    }
  }
  const autoTitle = t('This value back to automatic — saved at once, nothing runs')
  const autoLabel = t('Auto')
  const placementDue = settingDue('placement', info, t)
  const colourDue = settingDue('colour', info, t)
  const swingDue = settingDue('swing', info, t)
  const cutDue = settingDue('cut', info, t)
  const cutCur = cut ?? cutSaved
  const cutLimits = cutPanel?.limits ?? { max_cm: [3, 150] as [number, number], ends_cm: [0.5, 12] as [number, number] }
  const autoEnds = cutPanel?.auto_ends_cm ?? 3
  const cutMode = cutCur.at ? `at:${cutCur.at}` : cutCur.max_cm != null ? 'max' : 'full'
  const editCut = (patch: HairCut, drop?: 'max_cm' | 'at' | 'ends_cm') => {
    const next: HairCut = { ...cutCur, ...patch }
    if (drop) delete next[drop]
    setCut(normaliseCut(next))
  }
  const landmarkTitle = (at: string) => {
    const y = cutPanel?.landmarks?.[at]
    return y != null ? `${t(CUT_AT_LABELS[at] ?? at)} · ${Math.round(y * 100)} cm` : t(CUT_AT_LABELS[at] ?? at)
  }
  const autoMark = (isManual: boolean) => (isManual ? '' : ` ${t('auto')}`)
  const mm = (m: number) => `${m >= 0 ? '+' : ''}${(m * 1000).toFixed(0)} mm`
  const haar = mode === 'haar'
  const inUse = hd.colour.target ? `${t('Manual')} ${hd.colour.target}`
    : hd.colour.profile ? `${t('Profile colour')} (${hd.colour.profile.name})`
      : haar ? t('None named — the cards stay plain') : t("HairDeck's own")

  return (
    <>
      {haar ? null : (
        <Group title={t('Placement')}>
          <Slider label={t('Forward shift')} value={Math.round(cur.forward_m * 1000)}
            shown={mm(cur.forward_m) + (touched.forward_m ? '' : autoMark(p.forward_m !== null))}
            min={-Math.round(lim.forward_m * 1000)} max={Math.round(lim.forward_m * 1000)} step={1} disabled={off}
            title={t('Moves the hair forward (+) or back (−). The cyan line in the preview is this shift, the ruler beside it has a tick per centimetre.')}
            onChange={(v) => edit({ forward_m: v / 1000 })} onFocus={() => onRuler('forward')} onBlur={() => onRuler(null)}
            onAuto={autoOf('forward_m')} autoLabel={autoLabel} autoTitle={autoTitle} />
          <Slider label={t('Up / down')} value={Math.round((cur.up_m ?? 0) * 1000)}
            shown={mm(cur.up_m ?? 0) + (touched.up_m ? '' : autoMark(p.up_m !== null))}
            min={-Math.round(lim.up_m * 1000)} max={Math.round(lim.up_m * 1000)} step={1} disabled={off}
            title={t('Moves the hair up (+) or down (−). The cyan line in the preview is this shift, the ruler beside it has a tick per centimetre. Automatic = no shift.')}
            onChange={(v) => edit({ up_m: v / 1000 })} onFocus={() => onRuler('up')} onBlur={() => onRuler(null)}
            onAuto={autoOf('up_m')} autoLabel={autoLabel} autoTitle={autoTitle} />
          <Slider label={t('Forward tilt')} value={cur.tilt_deg}
            shown={`${cur.tilt_deg.toFixed(1)}°` + (touched.tilt_deg ? '' : autoMark(p.tilt_deg !== null))}
            min={lim.tilt_deg[0]} max={lim.tilt_deg[1]} step={0.5} disabled={off}
            title={t('Pitches the hair forward (+, up to 30°) or back (−, up to 15°) about the point the fit turned it about. Automatic brings the front hairline to the brow line.')}
            onChange={(v) => edit({ tilt_deg: v })} onAuto={autoOf('tilt_deg')} autoLabel={autoLabel} autoTitle={autoTitle} />
          <Slider label={t('Hair width')} value={cur.width_scale}
            shown={`${cur.width_scale.toFixed(2)}×` + (touched.width_scale ? '' : autoMark(p.width_scale !== null))}
            min={lim.width_scale[0]} max={lim.width_scale[1]} step={0.05} disabled={off}
            title={t('Scales how far the hair reaches out beyond the sides of the head; 1 = as generated. The hairline stays.')}
            onChange={(v) => edit({ width_scale: v })} onAuto={autoOf('width_scale')} autoLabel={autoLabel} autoTitle={autoTitle} />
          <div style={BTN_ROW}>
            <button type="button" className="ga-btn ga-btn-sm" disabled={off || !placement}
              title={t('Saves the placement — nothing runs')}
              onClick={() => { if (placement) void post('placement', { forward_m: sent('forward_m'),
                tilt_deg: sent('tilt_deg'), width_scale: sent('width_scale'), up_m: sent('up_m') }) }}>
              {t('Save')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={off || (!manual && !placement)}
              title={t('Back to automatic — saved at once, nothing runs')}
              onClick={() => { if (manual) void post('placement', { forward_m: null, tilt_deg: null, width_scale: null,
                up_m: null })
                else { setPlacement(null); setTouched({}) } }}>
              {t('Automatic')}
            </button>
          </div>
          {placement ? <span className="ga-hint" style={{ fontSize: 10 }}>
            {t('Preview only (without the push-out) — Save stores it, Re-fit applies it ({cost})')
              .replace('{cost}', jobsLabel(info.step_jobs?.fit ?? 0, t))}</span>
            : placementDue ? <span style={DUE}>{placementDue}</span> : null}
        </Group>
      )}

      <Group title={t('Colour')}>
        <div style={BTN_ROW}>
          <input type="color" value={colour ?? colourStored} disabled={off} aria-label={t('Hair colour')}
            style={{ width: 34, height: 22, padding: 0, border: 'none', background: 'none' }}
            onChange={(e) => setColour(e.target.value.toLowerCase())} />
          <button type="button" className="ga-btn ga-btn-sm" disabled={off || !colour || colour === hd.colour.target}
            title={t('Saves the colour — nothing runs')}
            onClick={() => { if (colour) void post('colour', { hex: colour }) }}>{t('Save')}</button>
          <button type="button" className="ga-btn ga-btn-sm" disabled={off || (!hd.colour.target && !colour)}
            title={t('Back to automatic — saved at once, nothing runs')}
            onClick={() => { if (hd.colour.target) void post('colour', { hex: '' }); else setColour(null) }}>
            {t('Automatic')}
          </button>
        </div>
        <span className="ga-hint" style={{ fontSize: 10 }}
          title={!haar && hd.colour.auto ? `${t("HairDeck's own")} ${hd.colour.auto}` : undefined}>
          {t('In use')}: {hd.colour.target ? <Swatch hex={hd.colour.target} /> : null} {inUse}
        </span>
        {colour ? <span className="ga-hint" style={{ fontSize: 10 }}>{t('Preview only — Save keeps it')}</span>
          : colourDue ? <span style={DUE}>{colourDue}</span> : null}
      </Group>

      {haar && cutPanel ? (
        <Group title={t('Cut')}>
          <label className="ga-model3d-slider" style={{ gap: 0, fontSize: 10 }}
            title={t('Where every strand ends: the whole length, a maximum length from the root, or a height on the body. The preview cuts live; Save keeps it, Re-fit applies it (no hub job).')}>
            <span>{t('Length')}</span>
            <select className="ga-input" value={cutMode} disabled={off} aria-label={t('Length')}
              style={{ fontSize: 11, padding: '1px 2px' }}
              onChange={(e) => {
                const v = e.target.value
                if (v === 'full') editCut({}, 'max_cm')
                else if (v === 'max') {
                  const fallback = Math.min(cutLimits.max_cm[1], Math.max(cutLimits.max_cm[0], 40))
                  setCut(normaliseCut({ max_cm: cutCur.max_cm ?? fallback, ends_cm: cutCur.ends_cm }))
                } else setCut(normaliseCut({ at: v.slice(3), ends_cm: cutCur.ends_cm }))
              }}>
              <option value="full">{t('Full length')}</option>
              <option value="max">{t('Max length')}</option>
              <optgroup label={t('Ends at')}>
                {(cutPanel.at ?? []).map((at) => (
                  <option key={at} value={`at:${at}`}>{landmarkTitle(at)}</option>
                ))}
              </optgroup>
            </select>
          </label>
          {cutMode === 'max' ? (
            <Slider label={t('Max length')} value={cutCur.max_cm ?? 40} shown={`${cutCur.max_cm ?? 40} cm`}
              min={cutLimits.max_cm[0]} max={cutLimits.max_cm[1]} step={1} disabled={off}
              title={t('Every strand is cut at this length from its root (along the strand); shorter strands stay.')}
              onChange={(v) => editCut({ max_cm: v })} />
          ) : null}
          <Slider label={t('Ends')} value={cutCur.ends_cm ?? autoEnds}
            shown={`${cutCur.ends_cm ?? autoEnds} cm` + (cutCur.ends_cm == null ? ` ${t('auto')}` : '')}
            min={cutLimits.ends_cm[0]} max={cutLimits.ends_cm[1]} step={0.5} disabled={off}
            title={t('How long the soft tip of each strand is: shorter removes more of the thin tail (a blunter cut), longer keeps wispier ends. Auto = {n} cm.').replace('{n}', String(autoEnds))}
            onChange={(v) => editCut({ ends_cm: v })} />
          <div style={BTN_ROW}>
            <button type="button" className="ga-btn ga-btn-sm" disabled={off || !cut || cutEqual(cut, cutSaved)}
              title={t('Saves the cut — nothing runs')}
              onClick={() => { if (cut) void post('cut', cutPostBody(cut)) }}>
              {t('Save')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={off || (!Object.keys(cutSaved).length && !cut)}
              title={t('Back to automatic — saved at once, nothing runs')}
              onClick={() => { if (Object.keys(cutSaved).length) void post('cut', cutPostBody({}))
                else setCut(null) }}>
              {t('Automatic')}
            </button>
          </div>
          <span className="ga-hint" style={{ fontSize: 10 }}>
            {t('In use')}: {cutPanel.built ? cutLabel(cutPanel.built, autoEnds, t) : t('not cut yet — the next fit cuts it')}
          </span>
          {cut && !cutEqual(cut, cutSaved)
            ? <span className="ga-hint" style={{ fontSize: 10 }}>{cutLive ? t('Preview only — Save keeps it')
              : t('No live preview for this fit — Save, then Re-fit shows it')}</span>
            : cutDue ? <span style={DUE}>{cutDue}</span> : null}
        </Group>
      ) : null}

      {chains ? (
        <Group title={t('Motion')}>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11, cursor: 'pointer' }}
            title={haar ? t('Swing on: every strand swings with motion. Saved at once — nothing runs, nothing is due.')
              : t('Swing on: the hair swings with motion but may touch the shoulders more. Saved at once — nothing runs; Re-fit then binds the hair to its spring chains (no hub job).')}>
            <input type="checkbox" checked={chains.swing}
              disabled={off || (!haar && chains.fitted && chains.count === 0 && !chains.swing)}
              onChange={(e) => { void post('motion', { swing: e.target.checked, stiffness: chains.stiffness }) }} />
            {t('Swing')}
            {haar ? null : (
              <span className="ga-hint" style={{ fontSize: 10 }}>
                {chains.fitted ? (chains.count ? t('{n} spring chains').replace('{n}', String(chains.count))
                  : t('no spring chains')) : t('chains after the next fit')}
              </span>
            )}
          </label>
          {swingDue ? <span style={DUE}>{swingDue}</span> : null}
          <Slider label={t('Stiffness')} value={stiffness ?? chains.stiffness}
            shown={`${(stiffness ?? chains.stiffness).toFixed(1)}×`} min={chains.limits[0]} max={chains.limits[1]}
            step={0.1} disabled={off || previewSwings === 'swing_off'}
            title={t('Higher stiffness springs back faster. It changes the motion only — nothing is re-fitted.')}
            onChange={(v) => setStiffness(v)} />
          <div style={BTN_ROW}>
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={off || stiffness === null || Math.abs(stiffness - chains.stiffness) < 1e-9}
              title={t('Saves the stiffness — it acts on the motion at once, nothing is due')}
              onClick={() => { if (stiffness !== null) void post('motion', { swing: chains.swing, stiffness }) }}>
              {t('Save')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={off || (chains.stiffness === 1 && stiffness === null)}
              onClick={() => { if (chains.stiffness !== 1) void post('motion', { swing: chains.swing, stiffness: null })
                else setStiffness(null) }}>
              {t('Reset')}
            </button>
          </div>
          <span className="ga-hint" style={{ fontSize: 10 }}>
            {previewSwings === 'swings' && strandIssue ? strandIssue : t(STRAND_PREVIEW_HINTS[previewSwings])}
          </span>
        </Group>
      ) : null}
    </>
  )
}
