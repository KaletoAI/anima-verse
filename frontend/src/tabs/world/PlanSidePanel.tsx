/**
 * PlanSidePanel — the context column right of the floor plan. Everything that
 * belongs to the SELECTED room and is not a click tool lives here: room info
 * (name, rotation, always-visible), the animation-marker vocabulary + the
 * room's marker list, and the room shell's surface kinds. The 🪑 tool opens
 * the prop palette below them. Purely presentational — RoomLayoutEditor owns
 * the state and hands in the callbacks.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { PropsPalette } from './PropsPalette'
import type { PropFull } from '../props/propTypes'
import type { Room, RoomLayout, SurfaceKind } from './worldTypes'

/** A fresh uint32 scatter seed — reroll = new arrangement. */
const rollSeed = (): number => crypto.getRandomValues(new Uint32Array(1))[0]

/** The two shell surfaces a room may skin — mirrors layout.surfaces. */
const SURFACE_SLOTS: Array<{ key: 'floor' | 'wall'; label: string }> = [
  { key: 'floor', label: 'Floor' },
  { key: 'wall', label: 'Wall' },
]

interface PlanSidePanelProps {
  /** Selected room WITH a layout, or null. */
  room: Room | null
  /** Open animation-clip vocabulary — the marker tool drops this kind. */
  clipKinds: string[]
  markerKind: string
  onMarkerKind: (kind: string) => void
  markerSel: number | null
  onSelectMarker: (index: number | null) => void
  /** The 🎯 place tool — armed state + toggle (it lives HERE, next to the
   *  marker list it feeds, not in the left toolbar). */
  markerMode: boolean
  onArmMarker: () => void
  onAlwaysVisible: (value: boolean) => void
  /** Height offset of the ROOM in real metres (undefined = 0). */
  onFloorOffset: (value: number | undefined) => void
  /** Generic layout patch for the selected room — the scatter block writes
   *  the whole `scatter` object through it (undefined removes it). */
  onLayoutPatch: (patch: Partial<RoomLayout>) => void
  /** Prop library for the scatter selects (id + display name). */
  propOptions: Array<{ id: string; name: string }>
  /** Surface-texture kinds (deduplicated); url = thumbnail when one exists. */
  surfaceKinds: SurfaceKind[]
  onSurface: (key: 'floor' | 'wall', kind: string) => void
  /** "✨ Furnish" (plan-room-furnish.md): opens the job dialog. The state
   *  string ('' = no job) is shown as a badge so a running job is visible
   *  without opening it. */
  furnishState: string
  furnishDisabled: boolean
  furnishHint: string
  onFurnish: () => void
  /** No scale anchor — the marker tool is locked with the other tools that
   *  need a real-world size (the plan width). */
  noAnchor: boolean
  /** Prop palette open (🪑 tool) — independent of the room selection. */
  propsOpen: boolean
  onPickProp: (prop: PropFull) => void
  armedPropId: string
}

/** Job state → the badge next to the Furnish button. */
const FURNISH_BADGE: Record<string, string> = {
  selecting: '…',
  proposal_ready: '!',
  generating: '⚙',
  placing: '⚙',
  review_ready: '✓',
  error: '⚠',
}

export function PlanSidePanel({
  room, clipKinds, markerKind, onMarkerKind, markerSel, onSelectMarker,
  markerMode, onArmMarker, onAlwaysVisible, onFloorOffset,
  onLayoutPatch, propOptions, surfaceKinds, onSurface,
  furnishState, furnishDisabled, furnishHint, onFurnish,
  noAnchor, propsOpen, onPickProp, armedPropId,
}: PlanSidePanelProps) {
  const { t } = useI18n()
  const layout = room?.layout
  const markers = layout?.markers || []
  // Scatter (plan-area-detail-scenes.md): the panel edits the CONFIG only —
  // positions are computed server-side from the seed at compose time, so the
  // preview updates through the normal draft → scene-preview round trip.
  const scatterItems = layout?.scatter?.items || []
  const scatterTotal = scatterItems.reduce((s, it) => s + (it.count || 0), 0)
  const writeScatter = (items: Array<{ prop_id: string; count: number }>,
      spacing?: number | undefined) => {
    if (!items.length) {
      onLayoutPatch({ scatter: undefined })
      return
    }
    const spacingEff = spacing !== undefined ? spacing
      : layout?.scatter?.spacing_m
    onLayoutPatch({ scatter: {
      seed: layout?.scatter?.seed ?? rollSeed(),
      items,
      ...(spacingEff ? { spacing_m: spacingEff } : {}),
    } })
  }

  // Room-specific blocks — the palette below them is independent of the
  // selection (the 🪑 tool may be open with nothing selected).
  const roomBlock = !room || !layout ? (
    <span className="ga-hint">
      {t('Select a room on the plan — the tools work on it.')}
    </span>
  ) : (
    <>
      <div className="ga-plan-panel-title">{room.name || room.id}</div>
      <span className="ga-hint">
        {t('Rotation')}: {layout.rotation || 0}°
        {layout.outline?.length ? ` · ⬠ ${layout.outline.length}` : ''}
      </span>
      <label className="ga-check-row" style={{ fontSize: '0.82em' }}
        title={t('Marks an OUTDOOR room (terrace, garden, pool): shown permanently in the 3D client independent of the interior view, and it gets NO shell walls — only its floor plate.')}>
        <input
          type="checkbox"
          checked={!!layout.always_visible}
          onChange={(e) => onAlwaysVisible(e.target.checked)}
        />
        <span>{t('Outdoor room (always visible)')}</span>
      </label>

      {/* Where the ROOM sits, as opposed to a model inside it. It belongs to
          the room, not to a diorama — it used to live in the model-placement
          strip and was therefore invisible until a room HAD a model, which is
          exactly backwards for an outdoor zone laid onto a location model. */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Height offset of the ROOM in real metres, relative to its storey. Everything in the room moves with it: floor, walls, props, markers, exit and any model. Inside a building leave it at 0 — it is for rooms lying on a location model, where the terrain is not at storey level.')}>
        <span style={{ flex: 1 }}>{t('Room height (m)')}</span>
        <input
          className="ga-input"
          type="number"
          step={0.05}
          style={{ width: 78 }}
          value={layout.floor_offset_y ?? 0}
          onChange={(e) => {
            const v = Number(e.target.value)
            onFloorOffset(Number.isFinite(v) && v !== 0 ? v : undefined)
          }}
        />
      </label>

      {/* Scatter: n props of m kinds thrown over the room area from a
          persisted seed — the forest tool (plan-area-detail-scenes.md). */}
      <div className="ga-form-section-label" style={{ marginTop: 4 }}>
        {t('Scatter')}
        {scatterItems.length ? (
          <span style={{ fontWeight: 'normal', opacity: 0.75,
            color: scatterTotal > 120 ? 'var(--danger, #f85149)' : undefined }}>
            {' '}· {scatterTotal}/120
          </span>
        ) : null}
      </div>
      {scatterItems.map((it, i) => (
        <div key={i} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <select className="ga-input" style={{ flex: 1, minWidth: 80 }}
            value={it.prop_id}
            onChange={(e) => writeScatter(scatterItems.map((x, j) =>
              j === i ? { ...x, prop_id: e.target.value } : x))}>
            {propOptions.some((p) => p.id === it.prop_id) ? null : (
              <option value={it.prop_id}>{it.prop_id}</option>
            )}
            {propOptions.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <input className="ga-input" type="number" min={1} max={100}
            style={{ width: 58 }} value={it.count}
            onChange={(e) => {
              const v = Math.round(Number(e.target.value))
              if (Number.isFinite(v)) {
                writeScatter(scatterItems.map((x, j) =>
                  j === i ? { ...x, count: Math.min(100, Math.max(1, v)) } : x))
              }
            }} />
          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
            title={t('Remove')}
            onClick={() => writeScatter(scatterItems.filter((_, j) => j !== i))}>
            ✕
          </button>
        </div>
      ))}
      {scatterItems.length < 16 && propOptions.length ? (
        <select className="ga-input" value=""
          title={t('Add a prop kind to scatter over the room area.')}
          onChange={(e) => {
            if (e.target.value)
              writeScatter([...scatterItems, { prop_id: e.target.value, count: 10 }])
          }}>
          <option value="">+ {t('Add scatter prop…')}</option>
          {propOptions.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      ) : null}
      {scatterItems.length ? (
        <>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center',
            fontSize: '0.82em' }}
            title={t('Extra clearance between scattered props, on top of their own footprints.')}>
            <span style={{ flex: 1 }}>{t('Min spacing (m)')}</span>
            <input className="ga-input" type="number" min={0} max={5} step={0.1}
              style={{ width: 64 }} value={layout.scatter?.spacing_m ?? 0}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (Number.isFinite(v))
                  writeScatter(scatterItems, Math.min(5, Math.max(0, v)))
              }} />
            <button type="button" className="ga-btn ga-btn-sm"
              title={t('Reroll — a new seed gives a new arrangement.')}
              onClick={() => onLayoutPatch({ scatter: {
                ...(layout.scatter || { items: scatterItems }),
                items: scatterItems,
                seed: rollSeed(),
              } })}>
              🎲
            </button>
          </label>
          <span className="ga-hint">
            {t('Positions are computed from the seed — reroll for a new arrangement. Other rooms, openings and placed props stay clear.')}
          </span>
        </>
      ) : null}

      <button
        type="button"
        className={`ga-btn ga-btn-sm${furnishState ? ' ga-btn-primary' : ''}`}
        disabled={furnishDisabled}
        onClick={onFurnish}
        title={furnishHint}
      >
        ✨ {t('Furnish')}
        {furnishState ? ` ${FURNISH_BADGE[furnishState] || ''}` : ''}
      </button>

      <div className="ga-plan-panel-title"
        title={t('Surface-texture kinds for this room shell — the client skins floor and walls with them. Default = the global kind / the client fallback.')}>
        {t('Surfaces')}
      </div>
      {surfaceKinds.length || layout.surfaces ? SURFACE_SLOTS.map(({ key, label }) => {
        const cur = layout.surfaces?.[key] || ''
        const thumb = surfaceKinds.find((s) => s.kind === cur)?.url
        return (
          <label key={key} style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}>
            <span style={{ width: 32, flex: '0 0 auto' }}>{t(label)}</span>
            {thumb ? (
              <img className="ga-list-thumb" alt="" src={thumb}
                style={{ width: 20, height: 20 }} />
            ) : null}
            <select
              className="ga-input"
              style={{ flex: 1, minWidth: 0 }}
              value={cur}
              onChange={(e) => onSurface(key, e.target.value)}
            >
              <option value="">{t('— default —')}</option>
              {surfaceKinds.map((s) => (
                <option key={s.kind} value={s.kind}>{s.name}</option>
              ))}
              {/* A stored kind the library no longer offers stays selectable. */}
              {cur && !surfaceKinds.some((s) => s.kind === cur) ? (
                <option value={cur}>{cur}</option>
              ) : null}
            </select>
          </label>
        )
      }) : (
        <span className="ga-hint">
          {t('No surface textures yet — the Surface textures tab creates them.')}
        </span>
      )}

      {clipKinds.length ? (
        <>
          <div className="ga-plan-panel-title">{t('Markers')}</div>
          <div style={{ display: 'flex', gap: 4 }}>
            <select
              className="ga-input"
              style={{ flex: 1, minWidth: 0 }}
              value={markerKind}
              onChange={(e) => onMarkerKind(e.target.value)}
              title={t('Animation kind the 🎯 tool drops — the open clip vocabulary, nothing hardcoded.')}
            >
              {clipKinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${markerMode ? ' ga-btn-primary' : ''}`}
              disabled={noAnchor}
              onClick={onArmMarker}
              title={noAnchor
                ? t('Set the plan width (m) first')
                : t('Place a marker — then click inside the room; figures with this animation snap to it.')}
            >
              🎯
            </button>
          </div>
        </>
      ) : null}
      {markers.map((m, i) => (
        <button
          key={`${m.animation}-${i}`}
          type="button"
          className={`ga-btn ga-btn-sm${markerSel === i ? ' ga-btn-primary' : ''}`}
          style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          onClick={() => onSelectMarker(markerSel === i ? null : i)}
          title={t('Select this marker to adjust facing/height or remove it.')}
        >
          🎯 {i + 1} · {m.animation}
        </button>
      ))}
    </>
  )

  return (
    <div className="ga-plan-panel">
      {roomBlock}
      {propsOpen ? (
        <PropsPalette onPick={onPickProp} armedPropId={armedPropId} />
      ) : null}
    </div>
  )
}
