/**
 * PlanMarkerStrip — the selected MARKER: a place a figure stands, sits or lies
 * in, and everything that decides how it stands there.
 *
 * The dials fall into three groups. WHERE — move by click, or the two metre
 * sliders (metres from the room's min corner, or from the anchor pin on the
 * yard; § A13a). HOW MANY — a bench seats several, so `capacity` slots line up
 * `spacing_m` apart along `slot_axis`; the SERVER composes those slots
 * (payload `markers[].slots`), the plan shows one dot. HOW the figure is held
 * — facing, height offset, and the two lean axes a slope needs, because the
 * compass alone cannot say that a figure is not upright.
 *
 * THE PREVIEW POSE IS VIEW STATE, never stored. It is keyed by marker id, so a
 * marker saved before ids existed gets one minted into the draft on the first
 * click — otherwise the preview, which reads the payload's id, could not find
 * the marker it belongs to.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { groupLabel, newId, posesInGroup } from './placeTypes'
import type { PoseCatalog } from './placeTypes'
import { rM } from './planGeometry'
import type { PlanMode } from './PlanToolbar'
import type { RoomLayout } from './worldTypes'

type Marker = NonNullable<RoomLayout['markers']>[number]

/** Facing per contract: 0 = south, 90 = east, 180 = north, 270 = west;
 *  unset = the client's face-the-neighbours default. */
const FACING: Record<number, string> = { 0: 'S', 90: 'E', 180: 'N', 270: 'W' }

interface Props {
  marker: Marker
  /** Index in the room's `markers`, for the human-readable number. */
  index: number
  /** The pose catalog — the marker's place type and its poses. */
  catalog: PoseCatalog
  /** Min corner of the shape the marker belongs to, and its size: the two
   *  position sliders span exactly it. */
  origin: [number, number]
  size: { w: number; d: number }
  /** The selected shape is the YARD — the sliders then measure from the
   *  anchor pin, and the tooltips say so. */
  ground: boolean
  mode: PlanMode
  onMode: (next: PlanMode) => void
  /** Preview pose per marker id (view only). */
  previewPose: Record<string, string>
  onPreviewPose?: (markerId: string, pose: string) => void
  /** Merge a patch into this marker, or remove it when null is passed. */
  onPatch: (patch: Partial<Marker> | null) => void
}

export function PlanMarkerStrip({
  marker, index, catalog, origin, size, ground, mode, onMode,
  previewPose, onPreviewPose, onPatch,
}: Props) {
  const { t } = useI18n()
  const fac = marker.rotation
  const capacity = marker.capacity || 1
  const moving = mode === 'marker-move'
  const poses = posesInGroup(catalog, marker.group)
  const poseIdx = Math.max(0, poses.indexOf(
    (marker.id && previewPose[marker.id]) || poses[0]))
  const setPreview = (pose: string) => {
    const id = marker.id || newId()
    if (!marker.id) onPatch({ id })
    onPreviewPose?.(id, pose)
  }

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>
        🎯 {index + 1} · {groupLabel(catalog.groups, marker.group)}
        {capacity > 1 ? ` ×${capacity}` : ''}:
      </span>
      <button
        type="button"
        className={`ga-btn ga-btn-sm${moving ? ' ga-btn-primary' : ''}`}
        onClick={() => onMode(moving ? '' : 'marker-move')}
        title={t('Then click inside the room to move this marker there.')}
      >
        ✥ {moving ? t('Click into the room…') : t('Move')}
      </button>
      {/* Fine X/Y correction after the coarse mouse placement — METRES from
          the room's min corner (v6 Nr. 2). */}
      <SliderInput
        label="X"
        ariaLabel={t('Marker position X (m)')}
        title={ground
          ? t('Fine-tune the marker position: metres east of the anchor pin (negative = west).')
          : t('Fine-tune the marker position: metres from the room’s west edge.')}
        min={origin[0]}
        max={origin[0] + size.w}
        step={0.01}
        value={marker.at[0]}
        onChange={(v) => onPatch({ at: [rM(v), marker.at[1]] })}
        unit="m"
        sliderWidth={100}
        inputWidth={74}
      />
      <SliderInput
        label="Y"
        ariaLabel={t('Marker position Y (m)')}
        title={ground
          ? t('Fine-tune the marker position: metres south of the anchor pin (negative = north).')
          : t('Fine-tune the marker position: metres from the room’s north edge.')}
        min={origin[1]}
        max={origin[1] + size.d}
        step={0.01}
        value={marker.at[1]}
        onChange={(v) => onPatch({ at: [marker.at[0], rM(v)] })}
        unit="m"
        sliderWidth={100}
        inputWidth={74}
      />
      <SliderInput
        label="🧭"
        ariaLabel={t('Marker facing (°)')}
        title={t('Facing of the figure (0 south, 90 east, 180 north, 270 west; — = face the neighbours).')}
        min={0}
        max={359}
        step={1}
        value={fac}
        fallback={0}
        clearable
        placeholder="—"
        onChange={(v) => onPatch({ rotation: v })}
        onClear={() => onPatch({ rotation: undefined })}
        sliderWidth={120}
        inputWidth={62}
        readback={(
          <span style={{ minWidth: 34 }}>
            {fac !== undefined && FACING[fac] ? FACING[fac] : ''}
          </span>
        )}
      >
        {fac !== undefined ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => onPatch({ rotation: undefined })}
            title={t('Back to default: face the neighbours.')}
          >
            ↺
          </button>
        ) : null}
      </SliderInput>
      {/* A place with room for several: the SERVER composes `capacity` slots
          `spacing_m` apart across the facing (payload `markers[].slots`); the
          plan shows one dot, the preview one figure per slot. */}
      <SliderInput
        label={t('Capacity')}
        ariaLabel={t('Marker capacity (figures)')}
        title={t('How many figures this place takes — a bench seats several. The slots line up in a row; the slot axis says which way it runs.')}
        min={1}
        max={8}
        step={1}
        value={capacity}
        onChange={(v) => {
          const cap = Math.max(1, Math.min(8, Math.round(v)))
          onPatch(cap > 1
            ? { capacity: cap }
            : { capacity: undefined, spacing_m: undefined,
                slot_axis: undefined })
        }}
        sliderWidth={80}
        inputWidth={52}
      />
      {capacity > 1 ? (
        <SliderInput
          label={t('Spacing')}
          ariaLabel={t('Marker slot spacing (m)')}
          title={t('Distance between neighbouring slots in metres (0.6 = a bench seat).')}
          min={0.2}
          max={3}
          step={0.05}
          value={marker.spacing_m ?? 0.6}
          onChange={(v) => onPatch({ spacing_m: rM(v) })}
          unit="m"
          sliderWidth={90}
          inputWidth={62}
        />
      ) : null}
      {/* WHICH WAY THE ROW RUNS. 90° — across the facing — is right for
          everyone who sits or stands: their shoulders are the narrow side. A
          LYING pose turns the body across the facing instead, so the same 90°
          row runs down the body and two sleepers land head-to-foot; 0° puts
          them side by side. */}
      {capacity > 1 ? (
        <SliderInput
          label={t('Slot axis')}
          ariaLabel={t('Marker slot axis (degrees off the facing)')}
          title={t('Which way the row of slots runs, in degrees off the facing. 90 = across it — right for sitting and standing, where the shoulders are the narrow side. 0 = along it, which is what a bed wants: a lying figure already lies across its facing, so a 90° row would stack the sleepers head-to-foot instead of side by side.')}
          min={0}
          max={180}
          step={5}
          value={marker.slot_axis ?? 90}
          onChange={(v) => onPatch(
            { slot_axis: Math.max(0, Math.min(180, Math.round(v))) })}
          unit="°"
          sliderWidth={90}
          inputWidth={62}
        />
      ) : null}
      {poses.length ? (
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('Which pose of this place type the preview figures play — view only, nothing is stored. Every slot shows it; a pair pose seats both halves around the marker.')}>
          <span className="ga-hint">{t('Preview pose')}</span>
          <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => setPreview(poses[(poseIdx + poses.length - 1) % poses.length])}>
            ◀
          </button>
          <span className="ga-hint">{poses[poseIdx]} ({poseIdx + 1}/{poses.length})</span>
          <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => setPreview(poses[(poseIdx + 1) % poses.length])}>
            ▶
          </button>
        </span>
      ) : null}
      <SliderInput
        label={t('Height offset (m)')}
        ariaLabel={t('Marker height offset (m)')}
        title={t('Additive to the seat height the client samples under the marker.')}
        min={-1}
        max={1}
        step={0.01}
        value={marker.offset_y ?? 0}
        onChange={(v) => onPatch({ offset_y: v === 0 ? undefined : v })}
        sliderWidth={120}
        inputWidth={74}
      />
      {/* Lean axes: a figure on a slope is not upright, and the compass alone
          cannot say that. Applied after the facing, in the figure's own
          frame. */}
      {([['tilt', '⤢', t('Tilt (°): head up (+) or down (−) — for lying or leaning figures.')],
        ['roll', '⤡', t('Roll (°): lean sideways — right (+) or left (−).')]] as const)
        .map(([key, icon, hint]) => (
          <SliderInput
            key={key}
            label={icon}
            ariaLabel={hint}
            title={hint}
            min={-90}
            max={90}
            step={1}
            value={marker[key] ?? 0}
            onChange={(v) => onPatch({ [key]: v === 0 ? undefined : v })}
            unit="°"
            sliderWidth={100}
            inputWidth={62}
          />
        ))}
      <button
        type="button"
        className="ga-btn ga-btn-sm ga-btn-danger"
        onClick={() => onPatch(null)}
        title={t('Remove this marker')}
      >
        × {t('Remove')}
      </button>
    </div>
  )
}
