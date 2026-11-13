/**
 * FieldFigure — the Figure tab (template tab `figure_tab`, section `figure`,
 * humanoid only; plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
 * Task 10, spec "The UI" + "Rules for the buttons", ruling 8).
 *
 * One preview, one Build:
 * - the preview is the figure DELIVERED now (`served_url`, the interim rule
 *   applied — never a half step);
 * - the status line (`headerLine`: "Status: up to date" or "2 changes · Build
 *   (7 hub jobs)"), the ONE primary button Build (POST …/figure/build, its
 *   cost on it, disabled with its reason written under it — a running Build
 *   is no disable, a click queues the next one) and the "Build
 *   automatically" checkbox (POST …/figure/auto-build); what the Build would
 *   run, collapsed;
 * - "Worn now (outfit …)": the worn hairstyle first (its name · its mode · ↗Hairstyles — Task 14, where
 *   hairstyles are worn, made and set), then every worn piece — name · mode ·
 *   ↗Wardrobe (the mode lives on the item and is edited there, ruling P4) ·
 *   state ("✓ ready", "⏳ mesh · 3 hub jobs" + "in the body until its own
 *   mesh is ready" — ruling A11, an in-body piece "shown painted until
 *   ready", "left out: …", "failed — reason" with Retry = the Build, "Fit refused
 *   — reason" with its single steps Re-fit (POST …/figure/refit {item_id}: an
 *   automatic, CPU-only Build) and Regenerate mesh (POST …/garments/{item}/run
 *   {step: "mesh", force, chain}) — Ruling A23); an own-mesh
 *   piece's details open its chain dialog (GarmentPieceDialog — a WORN
 *   piece's only entry, the Wardrobe hides its "Mesh steps"; opened here
 *   without its "Run all", Ruling 10a); a closable piece has the toggle
 *   Closed / Open under its mode (PieceStateToggle, the one piece-state
 *   route, saved at once — Task 11b), and an own-mesh closable piece, under
 *   Details, the single action that builds its OTHER state's mesh
 *   ("Build the open mesh — 6 hub jobs", POST …/garments/{item}/run
 *   {state}; the Build only ever makes the worn state's);
 * - "Body:" (plain body · shape · texture), one line on the base body with
 *   "Open Base body tab" (its views, model, face and rig steps and their
 *   settings live in the Base body tab since Task UI1 — FieldBaseBody) and the
 *   stored bodies and textures collapsed (FigureStored, Delete).
 *
 * Nothing here starts a chain except Build and Retry (both POST
 * …/figure/build — a manual Build, which retries a cached chain failure,
 * ruling 7a) and the other state's single action. Every humanoid is on the
 * figure pipeline (Ruling A13 — the "Use base body pipeline" switch is gone);
 * one without a plain body yet keeps the model it has and the button reads
 * "Build base body (N hub jobs)" with NO_BASE_BODY_NOTE under it. Polls GET
 * …/figure while a Build runs (useFigure).
 */
import { useCallback, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from './Model3DViewer'
import { GarmentPieceDialog, PieceStateToggle } from './WardrobeGarment'
import { FigureStored } from './FigureStored'
import { useFigure } from './useFigure'
import {
  BUILD_DEFERRED_NOTE, BUILD_RUNNING_NOTE, BUILD_STATUS, ESTIMATE_NOTE, HAIR_MODE_LABELS, MESH_MODE_LABELS, NO_BASE_BODY_NOTE, baseBodyLine, bodyLine,
  buildButton, changeLine, hairState, headerLine, noBaseBody, stateMeshAction, wornState,
} from './figureModel'
import type { FigurePayload, FigureWornRow, HairMode, PieceState } from './figureModel'

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
const CELL: CSSProperties = { padding: '4px 6px', verticalAlign: 'top' }

/** A collapsed block whose content mounts only while open (no fetch, no poll while closed). */
function Collapsed({ summary, children }: { summary: string; children: () => ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <details open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary style={{ cursor: 'pointer' }}>{summary}</summary>
      {open ? <div style={{ marginTop: 6 }}>{children()}</div> : null}
    </details>
  )
}

const noop = () => undefined

export function FieldFigure({ character, onOpenWardrobe, onOpenHairstyles, onOpenBaseBody }: {
  character: string
  /** Opens the Wardrobe tab, where the modes are edited. */
  onOpenWardrobe?: () => void
  /** Opens the Hairstyles tab (Task 14), where the hairstyles and their modes are edited. */
  onOpenHairstyles?: () => void
  /** Opens the Base body tab (the plain body's views, model, face and rig, and their settings). */
  onOpenBaseBody?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { data, error, startPoll } = useFigure(character)
  const [posting, setPosting] = useState(false)
  const [openPiece, setOpenPiece] = useState<{ id: string; name: string } | null>(null)

  const post = useCallback(async (path: string, body: unknown, ok?: (d: Record<string, unknown>) => void) => {
    if (posting) return
    setPosting(true)
    try {
      const d = await apiPost<Record<string, unknown>>(`/characters/${enc}/${path}`, body)
      ok?.(d)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      startPoll(300)
    }
  }, [enc, posting, startPoll, t, toast])

  const build = useCallback(() => post('figure/build', {}, (d) => {
    const status = String(d.status || '')
    toast(t(BUILD_STATUS[status] || status), 'success')
  }), [post, t, toast])

  const reload = useCallback(() => startPoll(0), [startPoll])

  /** Ruling A23 b: a piece whose fit on the body shape was refused — fit it again (CPU), or make its mesh anew. */
  const refit = useCallback((row: FigureWornRow) => post('figure/refit', { item_id: row.item_id }, (d) => {
    const status = String(d.status || '')
    toast(t(BUILD_STATUS[status] || status), 'success')
  }), [post, t, toast])
  const regenerateMesh = useCallback((row: FigureWornRow) => post(
    `garments/${encodeURIComponent(row.item_id)}/run`, { step: 'mesh', force: true, chain: true }, (d) => {
      toast(d.started ? t('Started') : t('Queued'), 'success')
    }), [post, t, toast])

  /** The other state's own mesh of a worn closable piece: its chain alone (queued behind the character's
   *  garment runs), never the Build. */
  const buildStateMesh = useCallback((row: FigureWornRow, state: PieceState) => post(
    `garments/${encodeURIComponent(row.item_id)}/run`, { state }, (d) => {
      toast(d.started ? t('Started') : t('Queued'), 'success')
    }), [post, t, toast])

  if (!data) {
    return error ? <div className="ga-hint" style={ERROR_STYLE}>{error}</div>
      : <div className="ga-hint">{t('Loading…')}</div>
  }
  // Every humanoid is on the pipeline (Ruling A13) except a temporary NPC (A13a): its model comes from the T-pose.
  if (!data.humanoid) return <div className="ga-hint">{t('The figure is for humanoid characters only.')}</div>
  if (!data.pipeline) {
    return <div className="ga-hint">{t('A temporary NPC has no figure — its 3D model is made from its T-pose picture.')}</div>
  }

  return (
    <div className="ga-split ga-split-views ga-split-figure">
      <div className="ga-split-col">
        {/* The figure gets the wider column and no tilt toolbar (user 2026-11-13): the canvas fills the column. */}
        {data.served_url ? (
          <Model3DViewer key={data.served_url} url={data.served_url} format="glb" height={600} />
        ) : (
          <div className="ga-hint" style={{ height: 200, display: 'flex', alignItems: 'center',
            justifyContent: 'center', border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
            {t('No figure yet — Build makes it')}
          </div>
        )}
      </div>
      <div className="ga-split-col">
        <FigureHeader data={data} posting={posting} onBuild={build}
          onAutoBuild={(enabled) => { void post('figure/auto-build', { enabled }) }} />
        <WornTable data={data} character={character} busy={posting} onRetry={build} onOpenWardrobe={onOpenWardrobe}
          onOpenHairstyles={onOpenHairstyles}
          onOpenPiece={(id, name) => setOpenPiece({ id, name })} onStateMesh={buildStateMesh} onChanged={reload}
          onRefit={refit} onRegenerateMesh={regenerateMesh} />
        <BodySection data={data} character={character} onChanged={reload} onOpenBaseBody={onOpenBaseBody} />
      </div>
      {openPiece ? (
        <GarmentPieceDialog character={character} itemId={openPiece.id} name={openPiece.name} noRunAll
          onStatus={noop} onClose={() => { setOpenPiece(null); reload() }} />
      ) : null}
    </div>
  )
}

function FigureHeader({ data, posting, onBuild, onAutoBuild }: {
  data: FigurePayload
  posting: boolean
  onBuild: () => void
  onAutoBuild: (enabled: boolean) => void
}) {
  const { t } = useI18n()
  const button = buildButton(data, t)
  const running = data.build.running
  const step = data.build.step
  const failed = Object.entries(data.build.failed || {})
  const steps = data.cost.steps
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <strong>{headerLine(data.status, data.changes.length, data.cost.hub_jobs, t)}</strong>
        <button type="button" className="ga-btn ga-btn-primary" disabled={posting || !!button.disabled}
          title={t(data.cost.note)} onClick={onBuild}>
          {button.label}
        </button>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
          title={t('Outfit changes, a new body or a piece that became ready start the Build by themselves; such a Build never makes or refreshes the base body — only a Build you start does. Off: they only collect as changes until you click Build. Never stops a running Build.')}>
          <input type="checkbox" checked={data.auto_build} disabled={posting}
            onChange={(e) => onAutoBuild(e.target.checked)} />
          <span>{t('Build automatically')}</span>
        </label>
      </div>
      {button.disabled ? <div className="ga-hint">{button.disabled}</div>
        : data.cost.hub_jobs ? <div className="ga-hint">{t(ESTIMATE_NOTE)}</div> : null}
      {noBaseBody(data) && !running ? <div className="ga-hint">{t(NO_BASE_BODY_NOTE)}</div> : null}
      {running ? (
        <div className="ga-hint">
          {step ? `${t('Running')}: ${step.index && step.count ? `${step.index}/${step.count} ` : ''}${step.label}` : t('Running')}
          {' — '}{t(BUILD_RUNNING_NOTE)}
        </div>
      ) : null}
      {!running && data.build.deferred ? <div className="ga-hint">{t(BUILD_DEFERRED_NOTE)}</div> : null}
      {data.changes.length ? (
        <div className="ga-hint">
          {data.changes.map((c) => changeLine(c, t)).join(' · ')}
        </div>
      ) : null}
      {!running && failed.length ? (
        <div className="ga-hint" style={ERROR_STYLE}>
          {failed.map(([name, f]) => `${name}: ${f.error}`).join(' · ')}
        </div>
      ) : null}
      {steps.length ? (
        <details>
          <summary style={{ cursor: 'pointer' }} className="ga-hint">{t('What the Build runs')}</summary>
          <ol style={{ margin: '4px 0 0 18px', padding: 0 }} className="ga-hint">
            {steps.map((s, i) => (
              <li key={`${s.name}:${s.item_id}:${i}`}>
                {s.label}
                {s.jobs === null ? ` — ${t('cost unknown')}` : s.jobs ? ` — ${s.jobs === 1 ? t('1 hub job')
                  : t('{n} hub jobs').replace('{n}', String(s.jobs))}` : ''}
                {s.manual ? ` — ${t(s.manual)}` : ''}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  )
}

function WornTable({ data, character, busy, onRetry, onOpenWardrobe, onOpenHairstyles, onOpenPiece, onStateMesh,
  onChanged, onRefit, onRegenerateMesh }: {
  data: FigurePayload
  character: string
  busy: boolean
  onRetry: () => void
  onOpenWardrobe?: () => void
  onOpenHairstyles?: () => void
  onOpenPiece: (itemId: string, name: string) => void
  /** Build the other open / closed state's own mesh of a piece. */
  onStateMesh: (row: FigureWornRow, state: PieceState) => void
  /** A piece was toggled open / closed: reload. */
  onChanged: () => void
  /** Ruling A23 b: the single steps of a piece whose fit on the body shape was refused. */
  onRefit: (row: FigureWornRow) => void
  onRegenerateMesh: (row: FigureWornRow) => void
}) {
  const { t } = useI18n()
  const wardrobe = onOpenWardrobe ? (
    <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenWardrobe}
      title={t('The mode is set in the Wardrobe')}>↗ {t('Wardrobe')}</button>
  ) : null
  const hairstyles = onOpenHairstyles ? (
    <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenHairstyles}
      title={t('Hairstyles are worn, made and set in the Hairstyles tab')}>↗ {t('Hairstyles')}</button>
  ) : null
  const retry = (
    <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onRetry}
      title={t('Runs the Build: the failed step again, then what depends on it')}>{t('Retry')}</button>
  )
  const title = data.outfit ? t('Worn now (outfit “{name}”)').replace('{name}', data.outfit) : t('Worn now')
  const hair = data.hair
  const hairCell = hair ? hairState(hair, t) : null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span className="ga-fieldset-title" style={{ margin: 0 }}>{title}</span>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <tbody>
          {hair && hairCell ? (
            <tr style={{ borderTop: '1px solid var(--border, #30363d)' }}>
              <td style={CELL}>{hair.name || t('Hair')}</td>
              <td style={CELL}>{t(HAIR_MODE_LABELS[hair.mode as HairMode] || hair.mode)}</td>
              <td style={CELL}>{hairstyles}</td>
              <td style={CELL}>
                <div style={hair.state === 'failed' ? ERROR_STYLE : undefined}>{hairCell.text}</div>
                {hairCell.sub ? <div className="ga-hint">{hairCell.sub}</div> : null}
                {hair.state === 'failed' ? retry : null}
              </td>
            </tr>
          ) : null}
          {data.worn.map((row) => {
            const cell = wornState(row, t)
            const note = row.note && !row.interim && !row.in_body_until && row.state !== 'left_out'
              && row.state !== 'failed' && row.state !== 'fit_refused' ? row.note : ''
            const other: PieceState | null = row.piece_state ? (row.piece_state === 'open' ? 'closed' : 'open') : null
            return (
              <tr key={row.item_id} style={{ borderTop: '1px solid var(--border, #30363d)' }}>
                <td style={CELL}>
                  <div>{row.name}</div>
                  {row.mode === 'own_mesh' ? (
                    <button type="button" className="ga-btn ga-btn-sm" aria-haspopup="dialog"
                      onClick={() => onOpenPiece(row.item_id, row.name)}>{t('Details')}</button>
                  ) : null}
                  {row.mode === 'own_mesh' && other ? (
                    row.other_state_jobs === 0 ? (
                      <div className="ga-hint">{stateMeshAction(other, 0, t)}</div>
                    ) : (
                      <div>
                        <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                          title={t('Only this piece’s chain; the Build makes only the worn state’s mesh')}
                          onClick={() => onStateMesh(row, other)}>
                          {stateMeshAction(other, row.other_state_jobs, t)}
                        </button>
                      </div>
                    )
                  ) : null}
                </td>
                <td style={CELL}>
                  <div>{t(MESH_MODE_LABELS[row.mode] || row.mode)}</div>
                  {row.piece_state ? (
                    <PieceStateToggle character={character} itemId={row.item_id} state={row.piece_state}
                      autoBuild={data.auto_build} disabled={busy} onChanged={onChanged} />
                  ) : null}
                </td>
                <td style={CELL}>{wardrobe}</td>
                <td style={CELL}>
                  <div style={row.state === 'failed' || row.state === 'fit_refused' ? ERROR_STYLE : undefined}>
                    {cell.text}
                  </div>
                  {cell.sub ? <div className="ga-hint">{cell.sub}</div> : null}
                  {note ? <div className="ga-hint">{t(note)}</div> : null}
                  {row.state === 'failed' ? retry : null}
                  {row.state === 'fit_refused' ? (
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => onRefit(row)}
                        title={t('Fits the piece on the body shape again (CPU, no hub job), then assembles the figure')}>
                        {t('Re-fit')}
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                        onClick={() => onRegenerateMesh(row)}
                        title={t('Makes the piece’s mesh anew (1 hub job), then fits it')}>
                        {t('Regenerate mesh')}
                      </button>
                    </div>
                  ) : null}
                </td>
              </tr>
            )
          })}
          {!data.worn.length && !hair ? (
            <tr><td style={CELL} className="ga-hint">{t('Nothing worn')}</td></tr>
          ) : null}
        </tbody>
      </table>
    </div>
  )
}

function BodySection({ data, character, onChanged, onOpenBaseBody }: {
  data: FigurePayload
  character: string
  onChanged: () => void
  onOpenBaseBody?: () => void
}) {
  const { t } = useI18n()
  if (!data.body) return null
  const names = (state: string) => data.worn.filter((r) => r.mode === state && r.state !== 'left_out').map((r) => r.name)
  const shapeNames = [...(data.hair?.mode === 'body' ? [t('hair')] : []), ...names('in_body')]
  const plainNote = data.changes.find((c) => c.key === 'body')?.note
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div>
        <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Body')}:</span>{' '}
        {bodyLine(data.body, shapeNames, names('painted'), t)}
      </div>
      {plainNote ? <div className="ga-hint">{t(plainNote)}</div> : null}
      <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 8 }}>
        <span className="ga-hint">{baseBodyLine(data.body.plain.state, t)}</span>
        {onOpenBaseBody ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}>{t('Open Base body tab')}</button>
        ) : null}
      </div>
      <Collapsed summary={t('Stored bodies and textures')}>
        {() => <FigureStored character={character} onDeleted={onChanged} />}
      </Collapsed>
    </div>
  )
}
