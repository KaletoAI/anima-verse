/**
 * WardrobeGarment — the 3D side of outfit pieces in the Wardrobe (plans
 * docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md Task 5,
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 9).
 *
 * Every outfit piece has ONE mode on its ITEM (`outfit_piece.mesh_mode`), the
 * same for every wearer: Own mesh (a finished mesh fitted on top), Painted (on
 * the body's texture) or In the body (meshed as part of the body). Per row:
 * the mode select (MeshModeSelect — saved at once, spends nothing; disabled
 * for a non-humanoid, the only character off the figure pipeline; leaving Own mesh while its mesh and fits are
 * stored asks first in an in-app confirmation — Ruling A63: the next cleanup removes them, and the confirmation
 * names the files and the hub jobs switching back costs, GET /inventory/items/{item}/own-mesh-files), after a
 * change the wearers line (WearersLine —
 * "worn by K characters now" and one "Build for them (cost)"), and for an
 * own-mesh piece its status chip (server: `garment_set.piece_status`) and
 * "Mesh steps", which opens the piece's dialog (GarmentPieceDialog): the
 * clothing chain (worn → piece-only → cut-outs → mesh → fit) as a compact grid
 * — thumbnails, one gate icon per image with the chips in its tooltip,
 * Regenerate per view — beside the fitted preview with its freshness badge,
 * its fit numbers and the step overview (ModelSteps).
 *
 * Open / closed (Task 11b, spec Addendum A): next to the mode the item flag
 * "Can be worn open" (ClosableCheckbox — the whole outfit_piece PUT like the
 * mode, spends nothing; disabled for footwear with the reason under it) and,
 * on a WORN closable row, the toggle Closed / Open (PieceStateToggle — the
 * one piece-state route, saved at once; "then Build runs automatically" under
 * it when that is on). An own-mesh piece has one mesh per state; the worn
 * state's is built by the Build, the other only by its single action in the
 * Figure tab's piece details.
 *
 * Backend: GET /characters/{n}/garments (overview: pipeline, the mode of every
 * held/worn piece, row status incl. the pieces it is fitted over, worn pieces
 * over each other), GET /characters/{n}/garments/{item} (the dialog, polled
 * while a step runs — useGarment), POST /characters/{n}/garments/{item}/run
 * {step?, view?, force?} (a run behind the character's other garment runs is
 * queued; the click answers on its button and tile — useGarmentRun), GET + PUT
 * /inventory/items/{item} (the mode; the PUT replaces the whole outfit_piece,
 * so it is read first), GET /inventory/items/{item}/wearers + POST
 * …/build-wearers (the wearers line).
 *
 * A footwear piece (a shoe or a boot) shows the shoe source steps and the fit
 * (FootwearSteps) and, on the right, the SHOD PREVIEW: the base model with
 * the fitted shoes (`preview_url`) under the fit's `foot_pose`, played in
 * the stand / walk / sit clips of the library (kinds idle / walk / sit,
 * height groups ground / ground / seat); POST …/footwear/width-cap saves the
 * width cap the slider sets.
 *
 * Ruling A36: the material select of an own-mesh piece (MaterialSelect — "Auto (→ Leather)" or a preset, saved at
 * once on the ITEM like the mode; it spends no hub job and makes no new fit: the figures that wear the piece are
 * re-assembled on the CPU, which the line under it names after a change).
 *
 * Ruling A37: "Use this" under every stored attempt of the clothing grid — POST
 * …/garments/{item}/images/{step}/{view}/attempts/{n}/use (0 jobs; a refused attempt becomes "Accepted by you").
 *
 * Above the preview of clothing and footwear, the body switch (FitBodySwitch, Ruling A31): one button per body
 * the piece was fitted on, the selected body's model (GET …/garments/{item}/fits/{body}/model — a refused fit
 * with the failing region marked), and Accept / Undo accept of a refused fit.
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut, setPieceState } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useClockSettings } from '../../lib/clockFormat'
import { GarmentFailure, GateChips, RefitNotice, RunButton, RunStatusLine } from './GarmentSteps'
import { GarmentStepGrid } from './GarmentStepGrid'
import type { ImageStepSpec } from './GarmentSteps'
import { FOOTWEAR_STEP_LABELS, ROW, WARN_STYLE, footwearRunPlan, meshNotReadyText, pieceViewDueText } from './garmentStyle'
import type { ChipSpec, GarmentRunBody } from './garmentStyle'
import { FootwearSteps } from './FootwearSteps'
import { Model3DViewer } from './Model3DViewer'
import { FitBodySwitch } from './FitBodySwitch'
import { FitSettings } from './FitSettings'
import { ModelSteps } from './ModelSteps'
import type { ModelStep } from './ModelSteps'
import { footwearOf, garmentRunning, useGarment, useGarmentRun } from './useGarment'
import type {
  GarmentItemInfo, GarmentView, ItemWearers, PieceMaterial, PieceMaterialInfo, PieceStatus, PieceViewChoice,
  PieceViewInfo,
} from './useGarment'
import {
  AUTO_BUILD_NOTE, BUILD_STATUS, MESH_MODES, MESH_MODE_HINTS, MESH_MODE_LABELS, PIECE_STATES, PIECE_STATE_LABELS,
  bodyWords, closableDisabled, leavesOwnMesh, refitSlot, showBodySwitch, switchOffWarning, wearersLine,
} from './figureModel'
import type { FitBody, MeshMode, OwnMeshFiles, PieceState } from './figureModel'
import { chainRunAll } from './baseBodyModel'

/** A piece worn in slot feet alone is footwear (`garment_set.garment_kind_of`): a shoe or a boot (boots spec
 *  2026-11-11 § 15). */
const OWN_MESH_SHOE_HINT = 'Made once per item from the item image; fitted onto each wearer on the CPU. Shoes, ankle boots and knee-high boots; sandals and open shoes are not supported yet; socks stay painted.'

const STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  worn: 'Worn views',
  ghost: 'Piece-only views',
  cutout: 'Cut-outs',
  mesh: 'Mesh',
  fit: 'Fit',
  // Footwear (the row chip of a shoe while it runs).
  source: 'Item image',
  empty: 'Empty shoe',
  insole: 'Insole',
}

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Piece description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  fit_algorithm_updated: 'Fit algorithm updated',
  // Ruling A47: the sleeves or the fit allowance changed (the fit re-runs on the CPU, 0 hub jobs).
  fit_settings_changed: 'Fit settings changed',
  // Footwear (garment_footwear.info).
  item_image_changed: 'Item image changed',
  source_version_changed: 'Older source version',
  analysis_updated: 'Older analysis version',
}

/** The shod preview's poses: the library clip KIND each plays and its height group. */
const PREVIEW_POSES: Array<{ key: string; label: string; kind: string; group: 'ground' | 'seat' }> = [
  { key: 'stand', label: 'Stand', kind: 'idle', group: 'ground' },
  { key: 'walk', label: 'Walk', kind: 'walk', group: 'ground' },
  { key: 'sit', label: 'Sit', kind: 'sit', group: 'seat' },
]

/** One solo clip per kind out of GET /assets/animation-clips — a set-less clip first, then the female
 *  set, then any (the pick of the admin previews). */
function libraryClips(clips: Array<{ kind: string; role?: string; set?: string; url: string }>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const { kind } of PREVIEW_POSES) {
    const of = clips.filter((c) => c.kind === kind && !c.role)
    const pick = of.find((c) => !c.set) || of.find((c) => c.set === 'female') || of[0]
    if (pick) out[kind] = pick.url
  }
  return out
}

const STATE_LABELS: Record<PieceStatus['state'], string> = {
  running: 'Generating…',
  fitted: 'Fitted',
  mesh: 'Mesh ready',
  images: 'Images ready',
  missing: 'Not made yet',
}

// Record keys: garment_gates.worn_gate / ghost_clothing_gate, garment_fit.clothing_metrics.
// The clothing image records are fractions of the figure height, not pixels.
const WORN_CHIPS: ChipSpec[] = [
  { key: 'garment_share', label: 'Piece area', scale: 100, unit: '%', digits: 1 },
  { key: 'outside_dRGB', label: 'Colour change outside the piece', scale: 1, unit: '', digits: 2 },
  { key: 'outside_xor', label: 'Outline change outside the piece', scale: 100, unit: '%', digits: 2 },
  { key: 'head_garment', label: 'Head changed', scale: 100, unit: '%', digits: 1, gatedKey: 'head_gated' },
]

const GHOST_CHIPS: ChipSpec[] = [
  { key: 'top_dy', label: 'Top offset', scale: 100, unit: '%', digits: 2 },
  { key: 'centre_dx', label: 'Centre offset', scale: 100, unit: '%', digits: 2 },
  { key: 'w_ratio', label: 'Width ratio', scale: 1, unit: '', digits: 3 },
  { key: 'skin_left', label: 'Skin left', scale: 100, unit: '%', digits: 2 },
  { key: 'outside', label: 'Outside the worn piece', scale: 100, unit: '%', digits: 1 },
  // Ruling A46: how far a part the worn piece does not have reaches past it (a fraction of the figure height).
  { key: 'added_reach', label: 'Added part reach', scale: 100, unit: '%', digits: 1 },
  { key: 'neck_fill', label: 'Neckline filled', scale: 100, unit: '%', digits: 0 },
  // The correction applied before the gate (garment_images._register); the offsets
  // above are its residual. Fractions of the figure height / a factor.
  { key: 'reg_shift', label: 'Registration shift', scale: 100, unit: '%', digits: 2 },
  { key: 'reg_scale', label: 'Registration scale', scale: 1, unit: '', digits: 3 },
]

const FIT_CHIPS: ChipSpec[] = [
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'deep_push_share', label: 'Pushed > 3 cm', scale: 100, unit: '%', digits: 1 },
  { key: 'largest_component_share', label: 'Largest part', scale: 100, unit: '%', digits: 1 },
  { key: 'rigged_inside_share', label: 'Inside the body', scale: 100, unit: '%', digits: 2 },
  // Ruling A47: stretched strips where the sleeves were laid onto the arm (gated).
  { key: 'sleeve_shards', label: 'Stretched strips', scale: 1, unit: '', digits: 0 },
  // Reported, not gated.
  { key: 'sleeve_skin_left_cm2', label: 'Skin in left sleeve', scale: 1, unit: 'cm²', digits: 1 },
  { key: 'sleeve_skin_right_cm2', label: 'Skin in right sleeve', scale: 1, unit: 'cm²', digits: 1 },
  { key: 'torso_tight_share', label: 'Trunk closer than 1.5 cm', scale: 100, unit: '%', digits: 0 },
  { key: 'rigged_clearance_p1_m', label: 'Clearance (p1)', scale: 1000, unit: 'mm', digits: 1 },
]

const IMAGE_STEPS: ImageStepSpec[] = [
  { step: 'worn', chips: WORN_CHIPS },
  { step: 'ghost', chips: GHOST_CHIPS },
  { step: 'cutout' },
]

const CHIP: CSSProperties = {
  display: 'inline-block', fontSize: '0.7em', padding: '1px 6px', borderRadius: 8,
  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%',
}

/** The row chip: running, in the body / missing (and why), or how far the chain got. */
export function PieceStatusChip({ status, name }: { status: PieceStatus; name: string }) {
  const { t } = useI18n()
  const progress = t(STATE_LABELS[status.state] || status.state)
  let text = progress
  let color = 'rgba(255,255,255,0.25)'
  if (status.state === 'running') {
    // Waiting behind the character's other garment runs: "Queued", not "Generating…".
    text = status.step === 'queued'
      ? t('Queued')
      : `${progress} ${t(STEP_LABELS[status.step || ''] || status.step || '')}`.trim()
    color = 'var(--accent, #6aa9ff)'
  } else if (status.in_body) {
    text = `${t('In the body until its own mesh is ready')}: ${t(status.reason || '')}`
    color = 'var(--warning, #d29922)'
  } else if (status.missing) {
    // Mesh mode: not painted into the outfit body, so not shown until the mesh is accepted.
    text = meshNotReadyText(t, name, status.reason)
    color = 'var(--warning, #d29922)'
  } else if (status.state === 'fitted') {
    color = 'var(--success, #3fb950)'
    // Layered over the worn pieces under it (garment_layers); one without a fit is painted on.
    if (status.over?.length) text = t('Fitted over {items}').replace('{items}', status.over.join(', '))
    if (status.without?.length) text += ` · ${t('without {items}').replace('{items}', status.without.join(', '))}`
  }
  return (
    <span style={{ ...CHIP, border: `1px solid ${color}` }} title={`${text} · ${progress}`}>{text}</span>
  )
}

/** The mode select of one outfit piece (ruling 3): Own mesh · Painted · In the
 *  body, saved at once on the ITEM (every wearer) and spending nothing — the
 *  PUT replaces the whole outfit_piece, so the stored one is read first and
 *  only `mesh_mode` changes. Leaving Own mesh with stored own-mesh files waits for the confirmation (Ruling A63,
 *  `switchOffWarning`): Cancel keeps the mode, "Switch anyway" saves it. For a non-humanoid (off the figure pipeline —
 *  every humanoid is on it) it is disabled with the reason under it. `onChanged` gets the saved mode (the row then shows its
 *  wearers line). */
export function MeshModeSelect({ itemId, mode, pipeline, disabled, feet = false, onChanged }: {
  itemId: string
  mode: MeshMode
  /** The character is on the figure pipeline (`GET …/garments` pipeline) — every humanoid is. */
  pipeline: boolean
  disabled?: boolean
  /** A piece worn in slot feet alone: a rigid shoe (its own-mesh hint). */
  feet?: boolean
  onChanged: (mode: MeshMode) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  /** The open confirmation (Ruling A63): the mode asked for and what the switch hands to the cleanup. */
  const [ask, setAsk] = useState<{ next: MeshMode; title: string; message: string } | null>(null)
  const url = `/inventory/items/${encodeURIComponent(itemId)}`
  const save = async (next: MeshMode) => {
    setBusy(true)
    try {
      const { item } = await apiGet<{ item: { outfit_piece?: Record<string, unknown> } }>(url)
      await apiPut(url, { outfit_piece: { ...(item.outfit_piece || {}), mesh_mode: next } })
      onChanged(next)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const choose = async (next: MeshMode) => {
    if (busy || next === mode) return
    if (leavesOwnMesh(mode, next)) {
      // Leaving Own mesh hands its stored mesh and fits to the next cleanup: the server counts them first, and
      // the switch waits for "Switch anyway" when there are any (the select keeps the mode until then).
      setBusy(true)
      let info: OwnMeshFiles | null = null
      let error = ''
      try {
        info = await apiGet<OwnMeshFiles>(`${url}/own-mesh-files`)
      } catch (e) {
        error = (e as Error).message || String(e)
      } finally {
        setBusy(false)
      }
      const warning = switchOffWarning(mode, next, info, error, t)
      if (warning) {
        setAsk({ next, ...warning })
        return
      }
    }
    await save(next)
  }
  const hint = [t(MESH_MODE_HINTS[mode]), mode === 'own_mesh' && feet ? t(OWN_MESH_SHOE_HINT) : '',
    t('Applies to every wearer; 2D images stay unchanged. Changing it spends nothing.')].filter(Boolean).join(' ')
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75em' }} title={hint}>
        <span style={{ opacity: 0.7 }}>{t('Mode')}</span>
        <select className="ga-input" style={{ width: 'auto', padding: '1px 4px', fontSize: '1em' }}
          value={mode} disabled={!pipeline || disabled || busy} aria-label={t('Mode')}
          onChange={(e) => { void choose(e.target.value as MeshMode) }}>
          {MESH_MODES.map((m) => <option key={m} value={m}>{t(MESH_MODE_LABELS[m])}</option>)}
        </select>
      </label>
      {!pipeline ? (
        <span className="ga-hint" style={{ fontSize: '0.7em' }}>
          {t('Only humanoid characters that are not temporary NPCs use modes')}
        </span>
      ) : null}
      <ConfirmDialog open={ask !== null} title={ask?.title || ''} message={ask?.message || ''}
        confirmLabel={t('Switch anyway')} danger
        onConfirm={() => { const next = ask?.next; setAsk(null); if (next) void save(next) }}
        onClose={() => setAsk(null)} />
    </span>
  )
}

const MATERIAL_LABELS: Record<PieceMaterial, string> = {
  auto: 'Auto', leather: 'Leather', denim: 'Denim', knit: 'Knit', cotton: 'Cotton', rubber: 'Rubber', metal: 'Metal',
}
const MATERIAL_HINT = 'How the own mesh shines: Auto guesses it from the name and description; a preset sets fixed roughness and shine. A change re-assembles the figure on the CPU — no hub job, no new fit.'
const MATERIAL_ORDER: PieceMaterial[] = ['auto', 'leather', 'denim', 'cotton', 'knit', 'rubber', 'metal']

/** The material select of an own-mesh piece (Ruling A36): "Auto (→ Leather)" — the preset the item's words
 *  guess, or "Auto (generated)" when none matches and the generator's roughness map stays — or a fixed preset.
 *  Saved at once on the ITEM (every wearer; the PUT replaces the whole outfit_piece, so the stored one is read
 *  first and only `material` changes). It runs nothing: no hub job, no new fit — a change of the preset it takes
 *  effect as re-assembles the wearers' figures on the CPU when they are next shown; the line under it says so
 *  before the change and names the wearers after it. */
export function MaterialSelect({ itemId, material, disabled, onChanged }: {
  itemId: string
  material: PieceMaterialInfo
  disabled?: boolean
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [due, setDue] = useState<string | null>(null)
  const effective = (c: PieceMaterial) => (c === 'auto' ? material.guess : c)
  const autoLabel = material.guess
    ? t('Auto (→ {material})').replace('{material}', t(MATERIAL_LABELS[material.guess]))
    : t('Auto (generated)')
  const choose = async (next: PieceMaterial) => {
    if (busy || next === material.choice) return
    setBusy(true)
    try {
      const url = `/inventory/items/${encodeURIComponent(itemId)}`
      const { item } = await apiGet<{ item: { outfit_piece?: Record<string, unknown> } }>(url)
      await apiPut(url, { outfit_piece: { ...(item.outfit_piece || {}), material: next } })
      if (effective(next) === effective(material.choice)) {
        setDue(t('Same look as before — nothing to re-assemble'))
      } else {
        const wearers = await apiGet<ItemWearers>(`${url}/wearers`).catch(() => null)
        const names = (wearers?.wearers || []).map((w) => w.name)
        setDue(names.length
          ? t('Now due: re-assembly on the CPU for {names} — 0 hub jobs, runs when the figure is next shown')
            .replace('{names}', names.join(', '))
          : t('Nobody wears it now — applies when it is worn'))
      }
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const hint = t(MATERIAL_HINT)
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75em' }} title={hint}>
        <span style={{ opacity: 0.7 }}>{t('Material')}</span>
        <select className="ga-input" style={{ width: 'auto', padding: '1px 4px', fontSize: '1em' }}
          value={material.choice} disabled={disabled || busy} aria-label={t('Material')}
          onChange={(e) => { void choose(e.target.value as PieceMaterial) }}>
          {MATERIAL_ORDER.map((m) => (
            <option key={m} value={m}>{m === 'auto' ? autoLabel : t(MATERIAL_LABELS[m])}</option>
          ))}
        </select>
      </label>
      <span className="ga-hint" style={{ fontSize: '0.7em' }}>
        {due ?? t('Change: CPU re-assembly · 0 hub jobs')}
      </span>
    </span>
  )
}

/** Closed / Open of a WORN closable piece (spec Addendum A): one click saves it at once through the one
 *  piece-state route (like an equip: history, the automatic Build). An own-mesh piece shows its other state's
 *  mesh once that is built (until then painted, "its open mesh"). Under it "then Build runs automatically"
 *  when Build automatically is on — else nothing: the Figure tab's "N changes" says it. */
export function PieceStateToggle({ character, itemId, state, autoBuild, disabled, onChanged }: {
  character: string
  itemId: string
  state: PieceState
  /** Build automatically is on for the character. */
  autoBuild: boolean
  disabled?: boolean
  onChanged: (state: PieceState) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const choose = async (next: PieceState) => {
    if (busy || next === state) return
    setBusy(true)
    try {
      await setPieceState(character, itemId, next)
      onChanged(next)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span role="group" aria-label={t('Worn open or closed')} style={{ display: 'inline-flex', gap: 2, fontSize: '0.75em' }}
        title={t('How the piece is worn now — saved at once, like putting it on')}>
        {PIECE_STATES.map((s) => (
          <button key={s} type="button" className={`ga-btn ga-btn-sm${s === state ? ' ga-btn-primary' : ''}`}
            aria-pressed={s === state} disabled={disabled || busy} onClick={() => { void choose(s) }}>
            {t(PIECE_STATE_LABELS[s])}
          </button>
        ))}
      </span>
      {autoBuild ? <span className="ga-hint" style={{ fontSize: '0.7em' }}>{t(AUTO_BUILD_NOTE)}</span> : null}
    </span>
  )
}

/** The item flag "Can be worn open" (spec Addendum A), next to the mode: saved at once on the ITEM — the PUT
 *  replaces the whole outfit_piece, so the stored one is read first and only `closable` changes; spends
 *  nothing. Footwear has no open/closed state: disabled with the reason under it. `namesState`: the piece's
 *  description already says open or closed (ruling A6) — a hint, no automatic edit. */
export function ClosableCheckbox({ itemId, closable, slots, namesState = false, disabled, onChanged }: {
  itemId: string
  closable: boolean
  slots: readonly string[]
  namesState?: boolean
  disabled?: boolean
  onChanged: (closable: boolean) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const reason = closableDisabled(slots)
  const save = async (next: boolean) => {
    if (busy || next === closable) return
    setBusy(true)
    try {
      const url = `/inventory/items/${encodeURIComponent(itemId)}`
      const { item } = await apiGet<{ item: { outfit_piece?: Record<string, unknown> } }>(url)
      await apiPut(url, { outfit_piece: { ...(item.outfit_piece || {}), closable: next } })
      onChanged(next)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75em', cursor: 'pointer' }}
        title={t('A jacket, coat or shirt that can be worn open: its wearers get a Closed / Open toggle. Applies to every wearer; changing it spends nothing.')}>
        <input type="checkbox" checked={closable && !reason} disabled={!!reason || disabled || busy}
          onChange={(e) => { void save(e.target.checked) }} />
        <span>{t('Can be worn open')}</span>
      </label>
      {reason ? <span className="ga-hint" style={{ fontSize: '0.7em' }}>{t(reason)}</span> : null}
      {!reason && closable && namesState ? (
        <span className="ga-hint" style={{ fontSize: '0.7em' }}>
          {t('The description already says open/closed — the toggle adds to it')}
        </span>
      ) : null}
    </span>
  )
}

/** The labels of the steps one Build would run, collapsed (what "Build" spends, before the click). */
export function BuildSteps({ summary, steps }: { summary: string; steps: string[] }) {
  const { t } = useI18n()
  if (!steps.length) return null
  return (
    <details style={{ fontSize: '0.72em' }}>
      <summary className="ga-hint" style={{ cursor: 'pointer' }}>{summary}</summary>
      <ul style={{ margin: '2px 0 0 0', paddingLeft: 18 }}>
        {steps.map((s, i) => <li key={i} className="ga-hint">{t(s)}</li>)}
      </ul>
    </details>
  )
}

/** The line under a piece whose mode was just changed (ruling 3): "worn by K
 *  characters now" (each wearer with its pending changes), ONE "Build for
 *  them (cost)" button — one Build per wearer, POST
 *  /inventory/items/{id}/build-wearers — and the reason under it when there
 *  is nobody to build for. What each wearer's Build runs is listed collapsed
 *  (a plain body made with older prompts and a "failed — Retry" piece
 *  included: a manual Build runs them). */
export function WearersLine({ itemId, version }: {
  itemId: string
  /** Bumped by the row on every mode change: the line reloads. */
  version: number
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [data, setData] = useState<ItemWearers | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const url = `/inventory/items/${encodeURIComponent(itemId)}`
  const load = useCallback(async () => {
    try {
      setData(await apiGet<ItemWearers>(`${url}/wearers`))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [url])
  useEffect(() => { void load() }, [load, version])
  if (error) return <div className="ga-hint" style={{ ...WARN_STYLE, fontSize: '0.72em' }}>{error}</div>
  if (!data) return <div className="ga-hint" style={{ fontSize: '0.72em' }}>{t('Loading…')}</div>
  const line = wearersLine(data.wearers.length, data.cost.hub_jobs)
  const build = async () => {
    setBusy(true)
    try {
      const d = await apiPost<{ started: Record<string, string> }>(`${url}/build-wearers`, {})
      const parts = Object.entries(d.started || {}).map(([name, status]) => `${name}: ${t(BUILD_STATUS[status] || status)}`)
      toast(parts.join(' · ') || t('Nobody wears it now'), 'success')
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const who = data.wearers.map((w) => `${w.name} (${w.changes === 1 ? t('1 change')
    : t('{n} changes').replace('{n}', String(w.changes))})`).join(', ')
  const plural = (n: number) => (n === 1 ? t('worn by 1 character now') : t('worn by {n} characters now')
    .replace('{n}', String(n)))
  const jobs = (n: number | null) => (n === null ? t('cost unknown')
    : n === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(n)))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: '0.75em' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span>{plural(data.wearers.length)}{who ? `: ${who}` : ''}</span>
        {line.button ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} title={t(data.cost.note)}
            onClick={() => { void build() }}>
            {t('Build for them ({cost})').replace('{cost}', jobs(data.cost.hub_jobs))}
          </button>
        ) : null}
      </div>
      {line.reason ? <span className="ga-hint">{t(line.reason)}</span> : null}
      {data.wearers.map((w) => (
        <BuildSteps key={w.name} steps={w.steps}
          summary={t('{name}: what the Build runs ({cost})').replace('{name}', w.name).replace('{cost}', jobs(w.hub_jobs))} />
      ))}
    </div>
  )
}

/** The body switch's empty viewer: a body whose refusal came before attempts were kept (Ruling A31). */
const NO_ATTEMPT_KEPT = 'No fit kept for this body — Re-fit in the Figure tab fits it again and keeps it (CPU only)'
/** Ruling A50b: in the Wardrobe the dialog has the body's own Re-fit. */
const NO_ATTEMPT_KEPT_HERE = 'No fit kept for this body — Re-fit on this body fits it and keeps it (CPU only)'

/** The steps dialog of one own-mesh piece: a wide modal (portal to
 *  document.body) — top bar with the piece, its ONE status (state, queue
 *  place or running step), Run all and close; left the chain as a compact
 *  grid (GarmentStepGrid), right the fitted preview with its fit numbers,
 *  the failure and the hints. Escape or a click beside it closes it; a run
 *  goes on without it (the row chip keeps showing it). Opened from the
 *  Figure tab (`noRunAll`) it has no Run all: there only Build and Retry
 *  start chains (Ruling 10a). */
export function GarmentPieceDialog({ character, itemId, name, onStatus, onClose, noRunAll = false }: {
  character: string
  itemId: string
  /** The piece's display name. */
  name: string
  /** The row chip follows the dialog's polls. */
  onStatus: (itemId: string, status: PieceStatus) => void
  onClose: () => void
  /** Hide "Run all" (the Figure tab: its Build runs the chain). */
  noRunAll?: boolean
}) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const url = character && itemId ? `/characters/${enc}/garments/${encodeURIComponent(itemId)}` : null
  const { info, startPoll } = useGarment<GarmentItemInfo & { steps?: ModelStep[] }>(url)
  const { feedback, start, cancel } = useGarmentRun(character, itemId, info, startPoll)

  useEffect(() => { if (info?.status) onStatus(itemId, info.status) }, [info, itemId, onStatus])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const garment = info?.garment ?? null
  // Kind footwear: the shoe source steps of the item (garment_footwear.info), not the clothing chain.
  const footwear = footwearOf(info)
  // The shod preview's pose and the library clips it plays (one fetch per footwear dialog).
  const [pose, setPose] = useState('stand')
  const [clips, setClips] = useState<Record<string, string>>({})
  const isFootwear = !!footwear
  useEffect(() => {
    if (!isFootwear) return
    let live = true
    apiGet<{ clips?: Array<{ kind: string; role?: string; set?: string; url: string }> }>('/assets/animation-clips')
      .then((d) => { if (live) setClips(libraryClips(d.clips || [])) })
      .catch(() => { if (live) setClips({}) })
    return () => { live = false }
  }, [isFootwear])
  const runState = footwear ?? garment
  const stepLabels = footwear ? FOOTWEAR_STEP_LABELS : STEP_LABELS
  // What a default run of the shoe would run and what it costs (server step list).
  const footwearPlan = footwear ? footwearRunPlan(footwear, t) : ''
  // Rule R1 (Task UI1): the label carries what Run all runs now; nothing due → "Everything is current".
  const runAll = chainRunAll(info?.run, t)
  const running = garmentRunning(info)
  // Ruling A58: while the piece's run is in its mesh job, nothing is disabled because of the job — the kept meshes'
  // "Use this" and Re-fit run beside it (CPU), every other run click queues behind it.
  const meshJob = garment?.steps.mesh?.job ?? null
  const busy = feedback.pending !== null || (running && !meshJob)
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  /** The width cap (null = the default) is SAVED on its own (Task UI2, rule R3): nothing runs; the fit's
   *  fingerprint changes, so the fit row shows it as due and Run all — or the row's Re-fit — re-fits (local). */
  const onWidthCap = async (cap: number | null) => {
    try {
      await apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/footwear/width-cap`, { cap })
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    startPoll(0)
  }
  /** Ruling A37, "Use this": a stored attempt becomes the view's image — 0 jobs; the toast names what is due now
   *  (the server's estimate after the click). */
  const [using, setUsing] = useState(false)
  const onUse = async (step: string, view: GarmentView, attempt: number) => {
    if (using) return
    setUsing(true)
    try {
      const d = await apiPost<{ changed: boolean; user_accepted: boolean;
        follow_up: { hub_jobs: number | null; note: string } }>(
        `/characters/${enc}/garments/${encodeURIComponent(itemId)}/images/${step}/${view}/attempts/${attempt}/use`, {})
      const due = d.follow_up.hub_jobs == null ? t('cost unknown')
        : t('Now due: {note}').replace('{note}', d.follow_up.note)
      toast(`${d.user_accepted ? t('Accepted by you') : t('In use')} · ${due}`, 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setUsing(false)
    }
    startPoll(0)
  }
  /** Ruling A58, "Use this mesh": a kept mesh becomes the piece's mesh and its fit starts on the CPU — 0 hub jobs; also
   *  while a mesh job runs (its result then stays a kept mesh). */
  const onMeshUse = async (slot: number) => {
    if (using) return
    setUsing(true)
    try {
      const d = await apiPost<{ user_accepted: boolean; during_job: boolean; fit: { beside?: boolean; queued?: boolean } }>(
        `/characters/${enc}/garments/${encodeURIComponent(itemId)}/mesh/attempts/${slot}/use`, {})
      toast([
        d.user_accepted ? t('Accepted by you') : t('In use'),
        d.fit?.queued ? t('the fit queues (CPU, 0 hub jobs)') : t('fitting on the CPU (0 hub jobs)'),
        d.during_job ? t('the running job’s result will stay a kept mesh') : '',
      ].filter(Boolean).join(' · '), 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setUsing(false)
    }
    startPoll(0)
  }
  /** Ruling A46, "Piece-only views from": SAVED on its own — nothing runs; the toast names what is due now (the
   *  view, its cut-out, the mesh and the fit; Run all or the Build makes them). */
  const onPieceView = async (view: GarmentView, choice: PieceViewChoice) => {
    if (using) return
    setUsing(true)
    try {
      const d = await apiPost<{ piece_views: Partial<Record<GarmentView, PieceViewInfo>> | null }>(
        `/characters/${enc}/garments/${encodeURIComponent(itemId)}/piece-views`, { view, choice })
      const due = d.piece_views?.[view]?.due || []
      toast(`${t('Saved')} · ${due.length ? `${t('Now due')}: ${pieceViewDueText(due, t)}` : t('nothing becomes due')}`,
        'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setUsing(false)
    }
    startPoll(0)
  }
  // "Fetch finished job…" on the mesh row: the shoe source's own route for footwear.
  const meshFetchUrl = info?.pipeline && itemId
    ? `/characters/${enc}/garments/${encodeURIComponent(itemId)}/${footwear ? 'footwear/mesh' : 'mesh'}/fetch` : null
  const onMeshFetched = () => startPoll(0)
  const previewPose = PREVIEW_POSES.find((p) => p.key === pose) || PREVIEW_POSES[0]
  const fit = garment?.steps.fit
  const fitRecord = fit && fit.status !== 'missing' ? fit.metrics : null
  // Ruling A31: the body switch — which body the preview shows, the piece as last fitted there.
  const bodies: FitBody[] = (info as { bodies?: FitBody[] } | null)?.bodies || []
  const [bodyKey, setBodyKey] = useState('plain')
  const switchOn = showBodySwitch(bodies)
  const shownBody = switchOn ? bodies.find((b) => b.key === bodyKey) || bodies[0] : null
  // Ruling A50: with a body shape selected, Re-fit fits on THAT body (the plain body's fit first when it is due)
  // and every button says which body; the numbers beside the plain body's settings are named as the plain body's.
  const refitBody = shownBody?.body || ''
  const refitOn = refitBody && shownBody ? bodyWords(shownBody.label, t) : ''
  // Ruling A50b: under a selected body shape the fit row, the chips and the fit settings box show THAT body's fit
  // (its sleeve resolution, widening, chips, build time) — never the plain body's; the settings stay per piece.
  const shapeFit = refitBody && shownBody ? { name: refitOn, status: shownBody.status, fit: shownBody.fit ?? null }
    : null
  const numbersOf = shapeFit ? refitOn : switchOn ? t('Plain body') : ''
  const settingsInfo = shapeFit ? shapeFit.fit?.fit_settings ?? null : garment?.fit_settings ?? null
  const chipRecord = shapeFit ? shapeFit.fit?.metrics ?? null : fitRecord
  // A body shape's fit is judged without the placement push gates (`fit_body`, server `clothing_gates`).
  const fitLimits = shapeFit ? info?.limits?.fit_body ?? info?.limits?.fit : info?.limits?.fit
  const onRunFit = (run: GarmentRunBody, slot?: string) =>
    onRun(refitBody && run.step === 'fit' ? { ...run, body: refitBody } : run, slot)
  const bodySwitch = switchOn ? (
    <FitBodySwitch character={character} itemId={itemId} bodies={bodies} selected={shownBody?.key || 'plain'}
      onSelect={setBodyKey} onChanged={() => startPoll(0)} feedback={feedback} refitDisabled={busy}
      onRefit={noRunAll ? undefined : (b) => onRun({ step: 'fit', force: true, body: b }, refitSlot(b))} />
  ) : null
  /** The model the viewer shows: the selected body's (the plain body's accepted fit = the piece's own preview). */
  const viewed = (own: { url: string | null | undefined; builtAt: string | null | undefined; footPose?: unknown }) =>
    shownBody && (shownBody.key !== 'plain' || shownBody.status !== 'accepted')
      ? { url: shownBody.url, builtAt: shownBody.built_at, footPose: shownBody.foot_pose }
      : { url: own.url || null, builtAt: own.builtAt || null, footPose: own.footPose }

  const shoeView = viewed({ url: footwear?.preview_url, builtAt: footwear?.preview_built_at,
    footPose: footwear?.foot_pose })
  const pieceView = viewed({ url: garment?.preview_url, builtAt: garment?.preview_built_at })

  let body: ReactNode
  if (!info) {
    body = <div className="ga-hint">{t('Loading…')}</div>
  } else if (!info.pipeline) {
    body = <div className="ga-hint">{t('Own meshes are for humanoid characters that are not temporary NPCs')}</div>
  } else if (footwear) {
    body = (
      <div className="ga-garment-dialog-body">
        <div className="ga-garment-dialog-col">
          {footwear.stale_reasons.length ? (
            <div style={{ ...ROW, gap: 8, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE} title={t('The shown shoe stays in use until the new one is made.')}>
                {footwear.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              </span>
              <RunButton feedback={feedback} slot="stale" disabled={busy} onClick={() => onRun({}, 'stale')}
                title={[footwearPlan, t('The shown shoe stays in use until the new one is made.')].filter(Boolean).join('\n')}
                label={t('Regenerate')} />
              {footwearPlan ? <span className="ga-hint" style={{ flexBasis: '100%' }}>{footwearPlan}</span> : null}
            </div>
          ) : null}
          <FootwearSteps info={footwear} limits={info.limits || {}} busy={busy} feedback={feedback} onRun={onRun}
            onWidthCap={(cap) => { void onWidthCap(cap) }} meshFetchUrl={meshFetchUrl}
            onMeshFetched={onMeshFetched} />
        </div>
        <div className="ga-garment-dialog-col">
          {bodySwitch}
          {shoeView.url ? (
            <>
              <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }} role="group"
                aria-label={t('Preview pose')}>
                {PREVIEW_POSES.map((p) => (
                  <button key={p.key} type="button"
                    className={`ga-btn ga-btn-sm${p.key === previewPose.key ? ' ga-btn-primary' : ''}`}
                    aria-pressed={p.key === previewPose.key}
                    disabled={!clips[p.kind]}
                    title={clips[p.kind] ? undefined
                      : t('No “{kind}” clip in the library').replace('{kind}', p.kind)}
                    onClick={() => setPose(p.key)}>
                    {t(p.label)}
                  </button>
                ))}
                <span className="ga-hint">{t("Shod base model with the fit's foot pose")}</span>
                {footwear.fits?.[0]?.split?.is_boot ? (
                  <span className="ga-hint"
                    title={t('Four nodes per pair: per side the foot part and the shaft (triangles each)')}>
                    {t('Boot: rigid foot part and a shaft on the shin, per side')}
                  </span>
                ) : null}
              </div>
              <Model3DViewer key={shoeView.url} url={shoeView.url} format="glb" height={430}
                freshness={shoeView.url === footwear.preview_url ? footwear.preview_freshness : null}
                builtAt={shoeView.builtAt} footPose={shoeView.footPose as typeof footwear.foot_pose}
                clipUrl={clips[previewPose.kind] || ''} clipGroup={previewPose.group} />
            </>
          ) : (
            <div className="ga-step-grid-empty" style={{ width: '100%', height: 120 }}>
              {shownBody && shownBody.key !== 'plain' ? t(noRunAll ? NO_ATTEMPT_KEPT : NO_ATTEMPT_KEPT_HERE) : t('No fitted mesh yet')}
            </div>
          )}
          {info.steps?.length ? <ModelSteps steps={info.steps} /> : null}
          <GarmentFailure garment={footwear} stepLabels={FOOTWEAR_STEP_LABELS} />
          {info.status.missing && !running ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {meshNotReadyText(t, info.name || name, info.status.reason)}
            </div>
          ) : null}
          <div className="ga-hint">{t(OWN_MESH_SHOE_HINT)}</div>
        </div>
      </div>
    )
  } else {
    body = (
      <div className="ga-garment-dialog-body">
        <div className="ga-garment-dialog-col">
          {/* A fit-settings change alone is shown (with its CPU-only Re-fit) in the fit settings beside the viewer. */}
          {garment && garment.stale_reasons.some((r) => r !== 'fit_settings_changed') ? (
            <div style={{ ...ROW, gap: 8, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE} title={t('The previous mesh stays in use until the new one is fitted.')}>
                {garment.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              </span>
              <RunButton feedback={feedback} slot="stale" disabled={busy} onClick={() => onRun({}, 'stale')}
                title={t('The previous mesh stays in use until the new one is fitted.')}
                label={t('Regenerate')} />
            </div>
          ) : null}
          <RefitNotice garment={garment} feedback={feedback} busy={busy} onRun={onRun} />
          <GarmentStepGrid
            garment={garment}
            imageSteps={IMAGE_STEPS}
            stepLabels={STEP_LABELS}
            limits={{ ...(info.limits || {}), fit: fitLimits }}
            fitChips={FIT_CHIPS}
            busy={busy || using}
            imageUseBusy={busy || using || running}
            onMeshUse={(slot) => { void onMeshUse(slot) }}
            onRun={onRunFit}
            refitOn={refitOn}
            shownFit={shapeFit}
            feedback={feedback}
            viewRuns={info.view_runs}
            useRuns={info.use_runs}
            onUse={(step, view, attempt) => { void onUse(step, view, attempt) }}
            onPieceView={(view, choice) => { void onPieceView(view, choice) }}
            meshFetchUrl={meshFetchUrl}
            onMeshFetched={onMeshFetched}
            pieceName={info.name || name}
            meshAllowance={garment?.fit_settings ? { character, itemId, info: garment.fit_settings, busy,
              onSaved: () => startPoll(0) } : null}
          />
        </div>
        <div className="ga-garment-dialog-col">
          {bodySwitch}
          {pieceView.url ? (
            <Model3DViewer key={pieceView.url} url={pieceView.url} format="glb" height={430}
              freshness={pieceView.url === garment?.preview_url ? garment?.preview_freshness : null}
              builtAt={pieceView.builtAt}
              statusPanel={info.steps?.length ? <ModelSteps steps={info.steps} /> : undefined} />
          ) : (
            <>
              <div className="ga-step-grid-empty" style={{ width: '100%', height: 120 }}>
                {shownBody && shownBody.key !== 'plain' ? t(noRunAll ? NO_ATTEMPT_KEPT : NO_ATTEMPT_KEPT_HERE) : t('No fitted mesh yet')}
              </div>
              {info.steps?.length ? <ModelSteps steps={info.steps} /> : null}
            </>
          )}
          {settingsInfo ? (
            <FitSettings character={character} itemId={itemId} info={settingsInfo} busy={busy}
              feedback={feedback} onRun={onRunFit} onSaved={() => startPoll(0)} noRunAll={noRunAll}
              numbersOf={numbersOf} refitOn={refitOn} />
          ) : shapeFit && garment?.fit_settings ? (
            <div style={{ ...ROW, gap: 8, padding: '6px 8px', border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
              <span>{refitOn}: {t('Not fitted yet on this body')}</span>
              {noRunAll ? <span className="ga-hint">{t('The next Build refits it.')}</span> : (
                <RunButton feedback={feedback} slot="fitsettings" disabled={busy}
                  title={t('Fits the piece on the selected body shape again on the CPU — 0 hub jobs. The plain body is fitted first when its fit is due.')}
                  label={`${t('Re-fit (0 hub jobs)')} · ${refitOn}`}
                  onClick={() => onRunFit({ step: 'fit', force: true }, 'fitsettings')} />
              )}
            </div>
          ) : null}
          {numbersOf && chipRecord ? (
            <div className="ga-hint" style={{ ...ROW, gap: 6 }}>
              {numbersOf}:<GateChips specs={FIT_CHIPS} record={chipRecord} limits={fitLimits} />
            </div>
          ) : <GateChips specs={FIT_CHIPS} record={chipRecord} limits={fitLimits} />}
          {!shapeFit && fit?.low && fit.low.ok === false ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {t('Distance tier failed — the full piece is used')}: {fit.low.error}
            </div>
          ) : null}
          <GarmentFailure garment={garment} stepLabels={STEP_LABELS} />
          {info.status.in_body && !running ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {t('Until its own mesh is ready, the figure has this piece in its body shape.')}
            </div>
          ) : null}
          {info.status.missing && !running ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {meshNotReadyText(t, info.name || name, info.status.reason)}
            </div>
          ) : null}
          <div className="ga-hint">
            {t('Pushed out of the body\'s collision capsules when moving (viewer: “Garment collision”); worn over another own-mesh piece, it is fitted over it.')}
          </div>
        </div>
      </div>
    )
  }

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal ga-garment-dialog" role="dialog" aria-modal="true"
        aria-label={`${t('Mesh steps')} · ${name}`}>
        <div className="ga-modal-header ga-garment-dialog-head">
          <span className="ga-garment-dialog-title" title={name}>{name}</span>
          <div style={{ flex: '1 1 auto', minWidth: 0, fontWeight: 400 }}>
            {running || feedback.pending !== null
              ? <RunStatusLine garment={runState} feedback={feedback} stepLabels={stepLabels} bare
                onCancel={() => { void cancel() }} />
              : info?.status ? <PieceStatusChip status={info.status} name={info.name || name} /> : null}
          </div>
          {info?.pipeline && !noRunAll ? (
            <RunButton
              feedback={feedback}
              slot="all"
              primary
              disabled={busy || !garment || runAll.disabled}
              title={[t('Runs every step that is missing or out of date'), info.run?.note || '', footwearPlan,
                meshJob ? t('queues behind the running job') : ''].filter(Boolean).join('\n')}
              onClick={() => onRun({}, 'all')}
              label={runAll.label}
            />
          ) : null}
          <button type="button" className="ga-modal-close" aria-label={t('Close')} onClick={onClose}>×</button>
        </div>
        {body}
      </div>
    </div>,
    document.body,
  )
}
