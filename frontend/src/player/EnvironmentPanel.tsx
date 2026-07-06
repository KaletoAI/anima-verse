/**
 * EnvironmentPanel — room background + present characters as
 * **freely movable and scalable expression figures** (current pose/expression).
 * plan-room-conversation phase 2.
 *
 * Background:  GET /world/locations/{id}/background?room=&hour=&file=<bg_id>
 *              (file pins the concrete image → positions stick to exactly it).
 * Expression:  GET /characters/{name}/outfit-expression?fallback=default
 * Positions:   GET/PUT /play/figures  (per character {x,y,scale}; x/y as
 *              fractions 0..1 = anchor = image bottom edge/center, scale =
 *              size factor). Server-side coupled to room + background image
 *              (bg_id) + expression image hash and stored in the character
 *              data → applies to all players. When room, background or image
 *              changes, positions are reloaded.
 *
 * Figures are dragged with the mouse inside the panel (moving) and resized
 * with the mouse wheel over the figure; the panel itself only drags via its
 * header, so no conflict.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../lib/api'

interface PresentChar { name: string; avatar_url: string; expr_version?: string }
interface Pos { x: number; y: number; scale: number }

const exprUrl = (name: string, version?: string) =>
  `/characters/${encodeURIComponent(name)}/outfit-expression?fallback=default`
  + (version ? `&v=${encodeURIComponent(version)}` : '')
const SCALE_MIN = 0.3
const SCALE_MAX = 2.0
const FIG_BASE_H = 70  // figure height in % of the stage at scale = 1
// How deep the stage edge may cut into a figure before the drag stops:
// 0.5 = up to half the figure may leave the stage on each side (trial value).
// The bottom-center anchor means x∈[0,1] already equals exactly this bound
// horizontally; vertically it grants half-figure slack below the bottom edge
// and keeps at least half the figure visible at the top (previously a figure
// could vanish entirely above the top and became ungrabbable).
const FIG_OVERHANG = 0.5
const clampScale = (v: number) => Math.max(SCALE_MIN, Math.min(SCALE_MAX, v))

export function EnvironmentPanel({
  locationId, roomId, locationName, roomName, present, avatarName,
  avatarExprVersion, bgVersion, bgId,
}: {
  locationId: string
  roomId: string
  locationName: string
  roomName: string
  present: PresentChar[]
  avatarName: string
  avatarExprVersion?: string
  bgVersion?: string
  bgId?: string
}) {
  const { t } = useI18n()
  const bgUrl = locationId
    ? `/world/locations/${encodeURIComponent(locationId)}/background`
      + `?room=${encodeURIComponent(roomId)}&hour=${new Date().getHours()}`
      + (bgId ? `&file=${encodeURIComponent(bgId)}` : '')
      + (bgVersion ? `&v=${encodeURIComponent(bgVersion)}` : '')
    : ''
  const [bgOk, setBgOk] = useState(true)
  useEffect(() => { setBgOk(true) }, [bgUrl])
  // Show the usage hint only until the first interaction (drag/resize).
  const [interacted, setInteracted] = useState(false)

  // "Rendered" view: one server-composed image (room + present characters)
  // instead of background + draggable figures. Manual trigger only — the
  // server caches per scene signature, ⟳ forces a fresh render.
  const [mode, setMode] = useState<'live' | 'rendered'>(() =>
    localStorage.getItem('play-scene-mode') === 'rendered' ? 'rendered' : 'live')
  const [renderSig, setRenderSig] = useState('')
  const [renderNonce, setRenderNonce] = useState(0)  // cache-buster after force
  const [rendering, setRendering] = useState(false)
  const [renderErr, setRenderErr] = useState('')
  const [renderWarn, setRenderWarn] = useState('')
  const requestRender = useCallback(async (force: boolean) => {
    setRendering(true)
    setRenderErr('')
    setRenderWarn('')
    try {
      const d = await apiPost<{ sig?: string; warning?: string }>('/play/scene-render', { force })
      setRenderSig(d.sig || '')
      setRenderWarn(d.warning || '')
      setRenderNonce((n) => n + 1)
    } catch (e) {
      setRenderErr((e as Error).message)
    } finally {
      setRendering(false)
    }
  }, [])
  const switchMode = useCallback((m: 'live' | 'rendered') => {
    setMode(m)
    localStorage.setItem('play-scene-mode', m)
    if (m === 'rendered') void requestRender(false)
  }, [requestRender])
  // Panel mounted directly in rendered mode (persisted choice) → render once.
  useEffect(() => {
    if (mode === 'rendered' && !renderSig && !rendering) void requestRender(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const stageRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState<Record<string, Pos>>({})
  const posRef = useRef(pos)
  posRef.current = pos
  const bgIdRef = useRef(bgId || '')
  bgIdRef.current = bgId || ''
  const dragRef = useRef<{
    name: string; rect: DOMRect; dx: number; dy: number
    // Figure box size as fractions of the stage — measured at drag start,
    // needed for the FIG_OVERHANG boundary in onMove.
    fw: number; fh: number
  } | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Default anchors of all currently shown figures — so wheel/drag can also
  // materialize a never-moved figure correctly (x/y taken from the default).
  const defaultsRef = useRef<Record<string, Pos>>({})

  // Load positions — anew whenever the room, background (bg_id) OR a figure's
  // expression image changes: the server returns the anchors matching
  // (room, bg_id, image hash); if an entry is missing the default applies below.
  const figSig = [
    locationId, roomId, bgId || '', avatarExprVersion || '',
    ...present.filter((c) => c.name !== avatarName).map((c) => `${c.name}:${c.expr_version || ''}`),
  ].join('|')
  useEffect(() => {
    apiGet<{ positions?: Record<string, Pos> }>(
      `/play/figures?bg=${encodeURIComponent(bgId || '')}`)
      .then((d) => setPos(d?.positions || {})).catch(() => { /* ignore */ })
  }, [figSig])

  const persist = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      apiPut('/play/figures', { positions: posRef.current, bg: bgIdRef.current })
        .catch(() => { /* ignore */ })
    }, 500)
  }, [])

  const onMove = useCallback((e: PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    // Subtract the grab offset (dx/dy) → figure stays under the cursor, no jump.
    const rawX = (e.clientX - d.dx - d.rect.left) / d.rect.width
    const rawY = (e.clientY - d.dy - d.rect.top) / d.rect.height
    // Boundary: the stage edge may cut up to FIG_OVERHANG into the figure.
    // Anchor is the figure's bottom center, so per axis:
    //   x: center offset from the edge ≥ width·(0.5 − OVERHANG)  (= [0,1] at 0.5)
    //   y: anchor from ‑half height above the top edge (keeps half visible)
    //      down to half height below the bottom edge.
    const xPad = d.fw * (0.5 - FIG_OVERHANG)
    const x = Math.max(xPad, Math.min(1 - xPad, rawX))
    const y = Math.max(d.fh * (1 - FIG_OVERHANG), Math.min(1 + FIG_OVERHANG * d.fh, rawY))
    setPos((p) => {
      const prev = p[d.name] || defaultsRef.current[d.name]
      return { ...p, [d.name]: { x, y, scale: prev?.scale ?? 1 } }
    })
  }, [])
  const onUp = useCallback(() => {
    if (!dragRef.current) return
    dragRef.current = null
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    setInteracted(true)
    persist()
  }, [onMove, persist])
  const startDrag = useCallback((e: React.PointerEvent, name: string, p: Pos) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    // Current figure anchor in px + offset to the grab point
    const anchorX = rect.left + p.x * rect.width
    const anchorY = rect.top + p.y * rect.height
    // Figure box size relative to the stage for the overhang boundary.
    const figRect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    dragRef.current = {
      name, rect, dx: e.clientX - anchorX, dy: e.clientY - anchorY,
      fw: figRect.width / rect.width, fh: figRect.height / rect.height,
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [onMove, onUp])

  // Mouse wheel over a figure → resize. Non-passive listener on the stage so
  // preventDefault works (no page scroll). Hit detection via data-fig attribute.
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onWheel = (e: WheelEvent) => {
      const el = (e.target as HTMLElement)?.closest('[data-fig]') as HTMLElement | null
      if (!el || !el.dataset.fig) return
      e.preventDefault()
      setInteracted(true)
      const name = el.dataset.fig
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
      setPos((p) => {
        const cur = p[name] || defaultsRef.current[name]
        if (!cur) return p
        return { ...p, [name]: { ...cur, scale: clampScale((cur.scale ?? 1) * factor) } }
      })
      persist()
    }
    stage.addEventListener('wheel', onWheel, { passive: false })
    return () => stage.removeEventListener('wheel', onWheel)
  }, [persist])

  // Default position: evenly spread along the bottom edge, scale = 1
  const defaultPos = (index: number, count: number): Pos => ({
    x: count <= 1 ? 0.5 : 0.12 + (0.76 * index) / (count - 1),
    y: 0.92, scale: 1,
  })

  // The avatar (you) is shown as a figure too — like any present character.
  const others = present.filter((c) => c.name !== avatarName)
  const figures: PresentChar[] = avatarName
    ? [{ name: avatarName, avatar_url: '', expr_version: avatarExprVersion }, ...others]
    : others
  // Provide defaults for all currently shown figures (for wheel/drag).
  defaultsRef.current = Object.fromEntries(
    figures.map((c, i) => [c.name, defaultPos(i, figures.length)]))

  return (
    <div ref={stageRef} style={{
      position: 'relative', height: '100%', overflow: 'hidden',
      background: 'var(--bg, #0d1117)', touchAction: 'none',
    }}>
      {bgUrl && bgOk && (
        <img src={bgUrl} alt="" onError={() => setBgOk(false)}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
      )}

      {/* Rendered mode: the composed scene image covers the whole stage. */}
      {mode === 'rendered' && renderSig && (
        <img src={`/play/scene-render/image?sig=${encodeURIComponent(renderSig)}&n=${renderNonce}`}
          alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
      )}
      {mode === 'rendered' && (rendering || renderErr || !renderSig) && (
        <span style={{
          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
          fontSize: '0.85em', background: 'rgba(0,0,0,0.6)', color: renderErr ? '#f88' : '#fff',
          padding: '4px 10px', borderRadius: 6, maxWidth: '85%', textAlign: 'center',
        }}>
          {rendering ? t('Rendering scene…') : (renderErr || t('No rendered scene yet.'))}
        </span>
      )}
      {/* Non-blocking hint (e.g. backend has too few reference slots). */}
      {mode === 'rendered' && !rendering && renderWarn && (
        <span style={{
          position: 'absolute', bottom: 28, left: 8, right: 8, fontSize: '0.72em',
          background: 'rgba(0,0,0,0.6)', color: '#f0c674', padding: '3px 8px',
          borderRadius: 6, textAlign: 'center',
        }}>{renderWarn}</span>
      )}

      {/* View toggle: Live (draggable figures) vs. Rendered (composed image). */}
      <div style={{ position: 'absolute', top: 8, right: 8, zIndex: 5, display: 'flex', gap: 4 }}>
        {(['live', 'rendered'] as const).map((m) => (
          <button key={m} onClick={() => switchMode(m)}
            style={{
              fontSize: '0.72em', padding: '2px 8px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.25)',
              background: mode === m ? 'var(--accent, #6aa9ff)' : 'rgba(0,0,0,0.45)',
              color: '#fff',
            }}>
            {m === 'live' ? t('Live') : t('Rendered')}
          </button>
        ))}
        {mode === 'rendered' && (
          <button onClick={() => requestRender(true)} disabled={rendering}
            title={t('Re-render scene')} aria-label={t('Re-render scene')}
            style={{
              fontSize: '0.72em', padding: '2px 8px', borderRadius: 6,
              cursor: rendering ? 'wait' : 'pointer',
              border: '1px solid rgba(255,255,255,0.25)',
              background: 'rgba(0,0,0,0.45)', color: '#fff',
            }}>⟳</button>
        )}
      </div>

      {mode === 'live' && others.length === 0 && (
        <span style={{
          position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
          opacity: 0.6, fontSize: '0.8em', background: 'rgba(0,0,0,0.45)', color: '#fff',
          padding: '2px 8px', borderRadius: 6,
        }}>{t('Nobody else here.')}</span>
      )}

      {mode === 'live' && !interacted && figures.length > 0 && (
        <span className="player-hint-pill" style={{ top: 8, left: 8 }}>
          {t('Drag to move · scroll to resize')}
        </span>
      )}

      {mode === 'live' && figures.map((c, i) => {
        const p = pos[c.name] || defaultPos(i, figures.length)
        const isAvatar = c.name === avatarName
        return (
          <div key={c.name} data-fig={c.name}
            onPointerDown={(e) => startDrag(e, c.name, p)}
            title={isAvatar ? `${c.name} (${t('you')})` : c.name}
            style={{
              position: 'absolute', left: `${p.x * 100}%`, top: `${p.y * 100}%`,
              transform: 'translate(-50%, -100%)',
              height: `${FIG_BASE_H * (p.scale ?? 1)}%`,
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'flex-end', cursor: 'grab', touchAction: 'none', userSelect: 'none',
            }}>
            <img src={exprUrl(c.name, c.expr_version)} alt={c.name} draggable={false}
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
              style={{ maxHeight: '100%', maxWidth: `${200 * (p.scale ?? 1)}px`, objectFit: 'contain', pointerEvents: 'none', filter: 'drop-shadow(0 2px 6px rgba(0,0,0,0.55))' }} />
            <span style={{
              fontSize: '0.68em', color: '#fff',
              background: isAvatar ? 'var(--accent, #6aa9ff)' : 'rgba(0,0,0,0.55)',
              padding: '0 5px', borderRadius: 4, marginTop: 2, whiteSpace: 'nowrap',
            }}>{c.name}</span>
          </div>
        )
      })}

      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0, padding: '4px 10px',
        background: 'linear-gradient(transparent, rgba(0,0,0,0.7))',
        color: '#fff', fontSize: '0.85em', fontWeight: 600, pointerEvents: 'none',
      }}>
        {roomName || locationName || '—'}
        {roomName && locationName && roomName !== locationName
          ? <span style={{ fontWeight: 400, opacity: 0.75 }}> · {locationName}</span> : null}
      </div>
    </div>
  )
}
