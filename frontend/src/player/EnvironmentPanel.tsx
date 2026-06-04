/**
 * EnvironmentPanel — Raum-Hintergrund + anwesende Charaktere als
 * **frei verschieb- und skalierbare Expression-Figuren** (aktuelle Pose/Ausdruck).
 * plan-room-conversation Phase 2.
 *
 * Hintergrund:  GET /world/locations/{id}/background?room=&hour=&file=<bg_id>
 *               (file pinnt das konkrete Bild → Positionen haften an genau ihm).
 * Expression:   GET /characters/{name}/outfit-expression?fallback=default
 * Positionen:   GET/PUT /play/figures  (pro Character {x,y,scale}; x/y als
 *               Bruchteile 0..1 = Standpunkt = Bild-Unterkante/Mitte, scale =
 *               Größenfaktor). Serverseitig gekoppelt an Raum + Hintergrundbild
 *               (bg_id) + Expression-Bild-Hash und in den Character-Daten
 *               gespeichert → gilt für alle Spieler. Wechselt Raum, Hintergrund
 *               oder Bild, werden die Positionen neu geladen.
 *
 * Figuren werden mit der Maus innerhalb des Panels gezogen (Verschieben) und mit
 * dem Mausrad über der Figur in der Größe verändert; der Panel selbst zieht nur
 * über seine Kopfzeile, also kein Konflikt.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPut } from '../lib/api'

interface PresentChar { name: string; avatar_url: string; expr_version?: string }
interface Pos { x: number; y: number; scale: number }

const exprUrl = (name: string, version?: string) =>
  `/characters/${encodeURIComponent(name)}/outfit-expression?fallback=default`
  + (version ? `&v=${encodeURIComponent(version)}` : '')
const clamp = (v: number) => Math.max(0, Math.min(1, v))
const SCALE_MIN = 0.3
const SCALE_MAX = 2.0
const FIG_BASE_H = 70  // Figurenhöhe in % der Stage bei scale = 1
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

  const stageRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState<Record<string, Pos>>({})
  const posRef = useRef(pos)
  posRef.current = pos
  const bgIdRef = useRef(bgId || '')
  bgIdRef.current = bgId || ''
  const dragRef = useRef<{ name: string; rect: DOMRect; dx: number; dy: number } | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Default-Standpunkte aller aktuell gezeigten Figuren — damit Mausrad/Drag auch
  // eine noch nie bewegte Figur korrekt materialisieren (x/y vom Default holen).
  const defaultsRef = useRef<Record<string, Pos>>({})

  // Positionen laden — neu, sobald sich Raum, Hintergrund (bg_id) ODER das
  // Expression-Bild einer Figur ändert: der Server liefert die Standpunkte passend
  // zu (Raum, bg_id, Bild-Hash); fehlt ein Eintrag, greift unten der Default.
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
    // Greif-Offset (dx/dy) abziehen → Figur bleibt unter dem Cursor, kein Sprung.
    const x = clamp((e.clientX - d.dx - d.rect.left) / d.rect.width)
    const y = clamp((e.clientY - d.dy - d.rect.top) / d.rect.height)
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
    persist()
  }, [onMove, persist])
  const startDrag = useCallback((e: React.PointerEvent, name: string, p: Pos) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    // aktueller Standpunkt der Figur in px + Offset zum Greifpunkt
    const anchorX = rect.left + p.x * rect.width
    const anchorY = rect.top + p.y * rect.height
    dragRef.current = { name, rect, dx: e.clientX - anchorX, dy: e.clientY - anchorY }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [onMove, onUp])

  // Mausrad über einer Figur → Größe ändern. Non-passiver Listener auf der Stage,
  // damit preventDefault greift (kein Seiten-Scroll). Treffer per data-fig-Attribut.
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onWheel = (e: WheelEvent) => {
      const el = (e.target as HTMLElement)?.closest('[data-fig]') as HTMLElement | null
      if (!el || !el.dataset.fig) return
      e.preventDefault()
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

  // Default-Position: gleichmäßig entlang der Unterkante, scale = 1
  const defaultPos = (index: number, count: number): Pos => ({
    x: count <= 1 ? 0.5 : 0.12 + (0.76 * index) / (count - 1),
    y: 0.92, scale: 1,
  })

  // Avatar (du selbst) wird mit als Figur gezeigt — wie ein anwesender Character.
  const others = present.filter((c) => c.name !== avatarName)
  const figures: PresentChar[] = avatarName
    ? [{ name: avatarName, avatar_url: '', expr_version: avatarExprVersion }, ...others]
    : others
  // Defaults für alle aktuell gezeigten Figuren bereitstellen (für Wheel/Drag).
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

      {others.length === 0 && (
        <span style={{
          position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
          opacity: 0.6, fontSize: '0.8em', background: 'rgba(0,0,0,0.45)', color: '#fff',
          padding: '2px 8px', borderRadius: 6,
        }}>{t('Nobody else here.')}</span>
      )}

      {figures.map((c, i) => {
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
