/**
 * ScenePropPanel — "Generate in scene" for ONE selected prop placement, plus
 * the picture strip of its newest run and the placement's variant picker.
 *
 * The UI half of the scene-asset pipeline (plan-assets-im-szenenkontext.md
 * Etappe 4 Punkt 6, backend `app/core/scene_asset.py` /
 * `app/routes/scene_asset.py`). It sits in the floor-plan editor's placement
 * strip, next to the yaw and height dials, because the pipeline works on
 * exactly what those dials describe: THIS placement, in THIS room.
 *
 * Two things it deliberately does NOT hide:
 *
 * 1. The pipeline reads the SAVED world. A placement that only exists in the
 *    editor draft is invisible to it, and a run's own writes (variant, yaw,
 *    sink) would be overwritten by the next Save of a stale draft. So the
 *    button is disabled while the location has unsaved changes, and it says
 *    so instead of failing at the server.
 * 2. A failed run keeps its pictures. The checks read out as numbers with
 *    their band beside them and the core's own failure sentences below —
 *    findings are numeric here (§ B5a), and a picture is the illustration.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { LightboxProvider, openLightbox } from '../../player/Lightbox'
import { useToast } from '../../lib/Toast'

/** One run as `routes/scene_asset._summary` builds it. */
export interface SceneAssetRun {
  stamp: string
  ok: boolean
  subject: string
  seconds: number
  backend: string
  path: string
  seed: number | null
  attempts: number
  variant: number | null
  stored_variant: number | null
  /** Stage the run stands at (or last stood at) — the core's own vocabulary,
   *  see `STAGE_ORDER`. Empty on a record written before this existed. */
  stage?: string
  /** The stage that STOPPED the run, empty when nothing did. */
  failed_stage?: string
  /** The core's own sentence for that stop — written to be read, not
   *  re-worded here. */
  failure_reason?: string
  /** The record has no `finished_at`: the run never got to write one, so its
   *  process died somewhere in `stage`. */
  unfinished?: boolean
  /** A configuration remark the run wants to make (e.g. it had to edit the
   *  whole plate for want of an inpaint backend) — not a failure. */
  backend_note?: string
  /** STORE index of the variant this spot showed BEFORE the run — the
   *  "before" half of the comparison. null = the prop had no meshed variant
   *  yet (a first generation). */
  previous_variant: number | null
  failures: string[]
  checks: {
    px_ratio?: number | null
    px_ratio_band?: Array<number | null>
    contact_ratio?: number | null
    contact_ratio_min?: number | null
    yaw_deg?: number | null
    offset_y?: number | null
    sank_m?: number | null
    suggest_level?: { slope_m?: number; threshold_m?: number } | null
    mesh_ok?: boolean | null
    mesh_height_m?: number | null
    mesh_backend?: string | null
    mesh_error?: string | null
  }
  files: Record<string, string>
}

interface StatusBody {
  running: boolean
  prop_id: string
  last_run: SceneAssetRun | null
}

interface VariantEntry {
  index: number
  active: boolean
  primary: boolean
  has_model: boolean
}

/** How often the status is polled while a run is out (ms). */
const POLL_MS = 4000

/** A number, or an em dash — a missing check must not read as 0. */
const num = (v: number | null | undefined, digits = 2): string =>
  (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—')

export function ScenePropPanel({
  locationId, roomId, index, propId, unsaved, variant, onVariant, onApplied,
}: {
  locationId: string
  roomId: string
  /** Index of the placement in the room's `layout.props`. */
  index: number
  propId: string
  /** The location draft carries unsaved changes — the pipeline cannot see it. */
  unsaved: boolean
  /** Stored `variant` of the placement (undefined = the primary one). */
  variant?: number
  /** Writes the variant into the DRAFT — the strip's other dials do the same,
   *  so one Save persists all of them consistently. */
  onVariant: (value: number | undefined) => void
  /** A run finished and wrote variant/yaw/offset into the STORED world —
   *  the editor reloads the location so its draft stops being stale. */
  onApplied: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [status, setStatus] = useState<StatusBody | null>(null)
  const [variants, setVariants] = useState<VariantEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  // Was the last poll a running one? The transition running -> idle is what
  // tells the editor to reload — polling alone never sees the run finish.
  const wasRunning = useRef(false)
  // The finish handler rides in a ref, so `poll` depends on the TARGET alone.
  // A parent that hands in a fresh closure every render would otherwise
  // restart the polling effect on every render.
  const finished = useRef<(run: SceneAssetRun | null) => void>(() => {})
  finished.current = (run) => {
    onApplied()
    toast(run?.ok ? t('Scene asset done') : t('Scene asset failed'),
          run?.ok ? 'success' : 'error')
  }

  const target = `location_id=${encodeURIComponent(locationId)}`
    + `&room_id=${encodeURIComponent(roomId)}&placement_index=${index}`

  const poll = useCallback(() => {
    let stale = false
    apiGet<StatusBody>(`/world/scene-asset/status?${target}`)
      .then((d) => {
        if (stale) return
        setStatus(d)
        if (wasRunning.current && !d.running) {
          wasRunning.current = false
          // The run wrote into the stored world; the draft has to catch up.
          finished.current(d.last_run)
        }
        wasRunning.current = d.running
      })
      .catch(() => { if (!stale) setStatus(null) })
    return () => { stale = true }
  }, [target])

  useEffect(() => {
    wasRunning.current = false
    return poll()
  }, [poll])

  // While a run is out the status is the only thing that moves — poll it.
  useEffect(() => {
    if (!status?.running) return
    const id = window.setInterval(() => { poll() }, POLL_MS)
    return () => window.clearInterval(id)
  }, [status?.running, poll])

  // The prop's model variants — the picker's options. Only ACTIVE variants
  // that HAVE a mesh can be shown: those are the ones the scene payload lists,
  // and a placement's `variant` is a position in exactly that list.
  useEffect(() => {
    let stale = false
    if (!propId) { setVariants([]); return }
    apiGet<{ variants?: VariantEntry[] }>(
      `/world/props/${encodeURIComponent(propId)}/variants`)
      .then((d) => { if (!stale) setVariants(d.variants || []) })
      .catch(() => { if (!stale) setVariants([]) })
    return () => { stale = true }
  }, [propId, status?.last_run?.stamp])

  const usable = variants.filter((v) => v.active && v.has_model)

  // Picking a variant writes BOTH ways, and that is not redundancy: the draft
  // keeps the plan and the 3D preview honest right now, and the stored world
  // is what the scene payload renders from. `update_prop_placement` behind
  // the route is the very writer the pipeline uses, sanitiser included. With
  // unsaved changes around, the immediate write is skipped — the placement may
  // not exist on the server yet, and Save carries the same value anyway.
  const pickVariant = useCallback((value: number | undefined) => {
    onVariant(value)
    if (unsaved) return
    apiPost('/world/scene-asset/placement', {
      location_id: locationId, room_id: roomId, placement_index: index,
      variant: value ?? 0,
    }).catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [onVariant, unsaved, locationId, roomId, index, t, toast])

  const generate = useCallback(async () => {
    setBusy(true)
    try {
      await apiPost('/world/scene-asset/generate', {
        location_id: locationId, room_id: roomId, placement_index: index,
      })
      wasRunning.current = true
      setStatus((prev) => (prev ? { ...prev, running: true }
        : { running: true, prop_id: propId, last_run: null }))
      setOpen(true)
      toast(t('Generating in scene — this takes a few minutes.'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [locationId, roomId, index, propId, t, toast])

  const run = status?.last_run || null
  const running = !!status?.running

  return (
    <>
      <button
        type="button"
        className={`ga-btn ga-btn-sm${running ? ' ga-btn-primary' : ''}`}
        disabled={busy || running || unsaved}
        onClick={() => { void generate() }}
        title={unsaved
          ? t('Save the location first — the pipeline renders the STORED world, so an unsaved placement does not exist for it yet.')
          : t('Render this very spot, let an image model draw the object into the picture, cut it out and rebuild it as a mesh at its declared height. The result becomes a new model variant of the prop and this placement points at it.')}
      >
        {running ? '⏳' : '🎬'} {t('Generate in scene')}
      </button>

      {/* The variant a placement SHOWS — completes the placement side of the
          model-variant feature (E2.3a). The value is a POSITION in the prop's
          active meshes, which is what the scene payload resolves it against. */}
      {usable.length > 1 ? (
        <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
          title={t('Which of the prop’s model variants THIS placement shows. 1 is the primary one — the mesh every consumer gets by default.')}>
          {t('Variant')}
          <select
            className="ga-input"
            style={{ width: 90 }}
            value={variant ?? 0}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10) || 0
              pickVariant(v > 0 ? v : undefined)
            }}
          >
            {usable.map((_, pos) => (
              <option key={pos} value={pos}>
                {pos === 0 ? `★ ${t('primary')}` : `v${pos + 1}`}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {run || running ? (
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          onClick={() => setOpen((v) => !v)}
          title={t('Show the newest scene-asset run: what this spot showed before, the context render, the edit result, the cutout it was meshed from, and every check.')}
        >
          {open ? '▾' : '▸'} {run
            ? (run.ok ? `✓ ${t('Scene run')}` : `⚠ ${t('Scene run')}`)
            : t('Scene run')}
        </button>
      ) : null}

      {open && (run || running) ? (
        <div style={{ flexBasis: '100%', display: 'flex', flexDirection: 'column',
                      gap: 6, marginTop: 4 }}>
          {running ? (
            <span className="ga-hint">
              {t('Rendering the spot, drawing the object, meshing it — a few minutes. The picture strip below is the previous run until this one lands.')}
            </span>
          ) : null}
          {/* The lightbox host lives HERE, with the only pictures in this
              panel: it is a module singleton that portals to document.body,
              so it escapes the editor's transformed panels — the reason a
              picture must never be a plain link out of the admin. */}
          {run ? (
            <LightboxProvider>
              <RunStrip run={run} />
            </LightboxProvider>
          ) : null}
        </div>
      ) : null}
    </>
  )
}

/** The stages a run walks, in order — the core's own vocabulary
 *  (`app/core/scene_asset.py`). The strip needs the ORDER to tell "this stage
 *  failed" from "this stage was never reached". */
const STAGE_ORDER = ['plate', 'mask', 'backend', 'insert', 'cutout', 'mesh',
                     'place', 'done']

const stageAt = (stage?: string) =>
  STAGE_ORDER.indexOf((stage || '').trim().toLowerCase())

/** The picture strip + the readouts of ONE run.
 *
 * Four frames, and the outer two are a PAIR: `before` is the source image of
 * the variant this spot showed until the run — copied into the run directory
 * at trigger time, because a run that refines that very variant overwrites the
 * original a moment later — and `after` is the cutout the new mesh was built
 * from. Same kind of picture on both ends, so the comparison is a comparison.
 *
 * AN EMPTY FRAME EXPLAINS ITSELF (user finding 2026-08-21: "nicht erreicht"
 * and "kein mesh" with nothing to go on). Each frame belongs to a STAGE of the
 * chain, and the run record says which stage it stopped at and why — so a
 * missing picture reads as "the run stopped here, because …" or "never
 * reached, the run stopped at …" instead of two bare words. Nothing is guessed
 * from the pictures: the state comes from `stage` / `failed_stage` /
 * `failure_reason` / `unfinished` in the payload.
 */
function RunStrip({ run }: { run: SceneAssetRun }) {
  const { t } = useI18n()
  const band = run.checks.px_ratio_band || []
  const prev = run.previous_variant
  // Readable names for the core's stage keys — the strip must never print a
  // raw identifier at the user.
  const stageName = (stage?: string): string => {
    const key = (stage || '').trim().toLowerCase()
    if (key === 'plate') return t('context render')
    if (key === 'mask') return t('mask')
    if (key === 'backend') return t('backend choice')
    if (key === 'insert') return t('drawing the object in')
    if (key === 'cutout') return t('cutout')
    if (key === 'mesh') return t('meshing')
    if (key === 'place') return t('placement')
    if (key === 'done') return t('done')
    return key || t('unknown')
  }
  /** Why a frame of stage `stage` has no picture — one sentence, always. */
  const emptyWhy = (stage: string): string => {
    const reason = (run.failure_reason || '').trim()
    if (run.failed_stage) {
      const mine = stageAt(stage)
      const stop = stageAt(run.failed_stage)
      if (mine === stop) {
        return reason
          ? t('Failed here — {why}').replace('{why}', reason)
          : t('Failed here.')
      }
      if (mine > stop) {
        const line = t('Not reached — the run stopped at “{stage}”.')
          .replace('{stage}', stageName(run.failed_stage))
        return reason ? `${line} ${reason}` : line
      }
      return t('Missing — the run passed this stage but wrote no picture.')
    }
    if (run.unfinished) {
      return t('Interrupted — the run was at “{stage}” and never finished.')
        .replace('{stage}', stageName(run.stage))
    }
    return t('Not produced — this run wrote no picture for this stage.')
  }
  /** The mesh line under the last frame: reached and good, reached and bad, or
   *  never reached at all — three different states, three different lines. */
  const meshNote = (): string => {
    if (run.checks.mesh_ok) {
      return `✓ ${num(run.checks.mesh_height_m)} m · ${run.checks.mesh_backend || '—'}`
    }
    if (run.checks.mesh_error) return `⚠ ${run.checks.mesh_error}`
    if (run.failed_stage && stageAt(run.failed_stage) < stageAt('mesh')) {
      return `⚠ ${t('No mesh — the run stopped at “{stage}” before meshing.')
        .replace('{stage}', stageName(run.failed_stage))}`
    }
    if (run.unfinished) {
      return `⚠ ${t('No mesh — the run was interrupted before it finished.')}`
    }
    return `⚠ ${t('No mesh — meshing produced none and reported no error.')}`
  }
  const shots: Array<{ url?: string; label: string; note: string
                       stage: string; empty?: string }> = [
    { url: run.files.before, label: t('Before'), stage: 'plate',
      note: typeof prev === 'number'
        ? t('variant {n}, what this spot showed').replace('{n}', String(prev + 1))
        : t('what this spot showed'),
      // Not a stage state: this frame was never part of the run. The spot
      // simply had no picture to show — a first generation, or a variant whose
      // mesh was uploaded.
      empty: t('No earlier picture — this spot had none to show (a first generation, or an uploaded mesh).') },
    { url: run.files.context, label: t('Context render'), stage: 'plate',
      note: t('the spot as Blender sees it') },
    { url: run.files.edit, label: t('Edit result'), stage: 'insert',
      note: `${run.path || '—'} · ${run.backend || '—'}` },
    { url: run.files.cutout, label: t('After (cutout + mesh)'), stage: 'cutout',
      note: meshNote() },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* What the strip IS — the feature explains its own purpose instead of
          leaving four unlabelled pictures to do it. */}
      <span className="ga-hint" style={{ fontSize: '0.76em' }}>
        {t('The record of ONE “generate in scene” run, left to right: what this spot showed before, the context render Blender made of it, the edit an image model drew into that render, and the cutout the new mesh variant was built from. Click a picture to enlarge it.')}
      </span>
      {run.backend_note ? (
        <span className="ga-hint" style={{ fontSize: '0.76em' }}>
          ℹ {run.backend_note}
        </span>
      ) : null}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {shots.map((s) => (
          <div key={s.label} style={{ width: 150 }}>
            {s.url ? (
              // The in-app viewer, never a link: the artefact route serves the
              // PNG inline, and a plain <a> would still leave the admin for a
              // browser tab. `openLightbox` portals to document.body.
              <button
                type="button"
                onClick={() => openLightbox({ src: s.url, alt: s.label })}
                title={t('Enlarge')}
                style={{ padding: 0, border: 0, background: 'none',
                         cursor: 'zoom-in', display: 'block' }}
              >
                <img
                  src={s.url}
                  alt={s.label}
                  style={{ width: 150, height: 150, objectFit: 'contain',
                           background: 'rgba(127,127,127,0.14)', borderRadius: 4 }}
                />
              </button>
            ) : (
              <div style={{ width: 150, height: 150, borderRadius: 4,
                            background: 'rgba(127,127,127,0.14)',
                            display: 'flex', alignItems: 'center',
                            justifyContent: 'center', textAlign: 'center',
                            padding: 8, fontSize: '0.74em', lineHeight: 1.35,
                            opacity: 0.8 }}>
                {s.empty || emptyWhy(s.stage)}
              </div>
            )}
            <div style={{ fontSize: '0.78em', fontWeight: 600 }}>{s.label}</div>
            <div className="ga-hint" style={{ fontSize: '0.74em' }}>{s.note}</div>
          </div>
        ))}
      </div>

      {/* The numbers a human judges by — each with the band it is judged
          against, so a value alone never has to be looked up elsewhere. */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: '0.78em' }}>
        <span title={t('Height of the drawn object relative to the height its own footprint projects to. Outside the band it is a failed edit, not a small object.')}>
          {t('Drawn size')}: <b>{num(run.checks.px_ratio)}×</b>
          {' '}({t('band')} {num(band[0], 2)}–{num(band[1], 2)})
        </span>
        <span title={t('Fraction of the nine footprint samples that touch the ground after the sink. Below the minimum the object hovers or sinks into the terrain.')}>
          {t('Contact')}: <b>{num(run.checks.contact_ratio)}</b>
          {' '}({t('min')} {num(run.checks.contact_ratio_min)})
        </span>
        <span title={t('Yaw the plate camera implies and the vertical offset the contact check settled on — both written onto the placement.')}>
          {t('Yaw')}: <b>{num(run.checks.yaw_deg, 1)}°</b> · {t('Offset')}:{' '}
          <b>{num(run.checks.offset_y, 3)} m</b>
          {run.checks.sank_m ? ` (${t('sank')} ${num(run.checks.sank_m, 3)} m)` : ''}
        </span>
        <span title={t('Which backend drew the object, along which path (inpaint keeps the surroundings pixel-identical, img2img redraws the frame), on which seed, and how many attempts the bounded refinement loop needed.')}>
          {run.backend || '—'} · {run.path || '—'} · {t('seed')}{' '}
          {run.seed ?? '—'} · {run.attempts} {t('attempt(s)')} · {num(run.seconds, 1)} s
        </span>
        {run.ok && run.stored_variant !== null && run.stored_variant !== undefined ? (
          <span title={t('The mesh landed in this model variant of the prop and the placement now points at it.')}>
            ✓ {t('uses variant {n}').replace('{n}', String(run.stored_variant + 1))}
          </span>
        ) : null}
      </div>

      {/* WHERE the run ended, in one line — the frames say it per picture,
          this says it for the run. A finished, successful run says nothing:
          the ✓ above is the statement. */}
      {run.failed_stage ? (
        <span style={{ fontSize: '0.78em' }}>
          ⚠ {t('The run stopped at “{stage}”.').replace('{stage}', stageName(run.failed_stage))}
          {run.failure_reason ? ` ${run.failure_reason}` : ''}
        </span>
      ) : run.unfinished ? (
        <span style={{ fontSize: '0.78em' }}>
          ⚠ {t('The run never finished — its process ended while it was at “{stage}”. Start it again.')
            .replace('{stage}', stageName(run.stage))}
        </span>
      ) : null}

      {run.failures.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.78em' }}>
          {run.failures.map((f, i) => <li key={i}>⚠ {f}</li>)}
        </ul>
      ) : null}
      {run.checks.suggest_level ? (
        <span className="ga-hint" style={{ fontSize: '0.78em' }}>
          {t('The ground under this spot drops {a} m across the footprint (threshold {b} m) — sinking cannot flatten a slope; level the terrain here or move the placement.')
            .replace('{a}', num(run.checks.suggest_level.slope_m, 3))
            .replace('{b}', num(run.checks.suggest_level.threshold_m, 2))}
        </span>
      ) : null}
    </div>
  )
}
