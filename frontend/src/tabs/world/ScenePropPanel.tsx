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
          {run ? <RunStrip run={run} /> : null}
        </div>
      ) : null}
    </>
  )
}

/** The picture strip + the readouts of ONE run.
 *
 * Four frames, and the outer two are a PAIR: `before` is the source image of
 * the variant this spot showed until the run — copied into the run directory
 * at trigger time, because a run that refines that very variant overwrites the
 * original a moment later — and `after` is the cutout the new mesh was built
 * from. Same kind of picture on both ends, so the comparison is a comparison.
 */
function RunStrip({ run }: { run: SceneAssetRun }) {
  const { t } = useI18n()
  const band = run.checks.px_ratio_band || []
  const prev = run.previous_variant
  const shots: Array<{ url?: string; label: string; note: string; empty?: string }> = [
    { url: run.files.before, label: t('Before'),
      note: typeof prev === 'number'
        ? t('variant {n}, what this spot showed').replace('{n}', String(prev + 1))
        : t('what this spot showed'),
      // Not "not reached": this frame was never part of the run. The spot
      // simply had no picture to show — a first generation, or a variant whose
      // mesh was uploaded.
      empty: t('no earlier picture') },
    { url: run.files.context, label: t('Context render'),
      note: t('the spot as Blender sees it') },
    { url: run.files.edit, label: t('Edit result'),
      note: `${run.path || '—'} · ${run.backend || '—'}` },
    { url: run.files.cutout, label: t('After (cutout + mesh)'),
      note: run.checks.mesh_ok
        ? `✓ ${num(run.checks.mesh_height_m)} m · ${run.checks.mesh_backend || '—'}`
        : `⚠ ${run.checks.mesh_error || t('no mesh')}` },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {shots.map((s) => (
          <div key={s.label} style={{ width: 150 }}>
            {s.url ? (
              <a href={s.url} target="_blank" rel="noreferrer">
                <img
                  src={s.url}
                  alt={s.label}
                  style={{ width: 150, height: 150, objectFit: 'contain',
                           background: 'rgba(127,127,127,0.14)', borderRadius: 4 }}
                />
              </a>
            ) : (
              <div style={{ width: 150, height: 150, borderRadius: 4,
                            background: 'rgba(127,127,127,0.14)',
                            display: 'flex', alignItems: 'center',
                            justifyContent: 'center', fontSize: '0.8em',
                            opacity: 0.7 }}>
                {s.empty || t('not reached')}
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
