/**
 * PlanPropStrip — the selected PROP placement: everything one does to a piece
 * of furniture once it is on the plan.
 *
 * Five groups of dials, in the order one reaches for them. WHAT it is called
 * (the LABEL, which is what the LLM and the marker chips say — "armchair by
 * the window"). WHERE it stands (X/Y in metres from the shape's min corner, or
 * location-local metres on the yard; § A13a) and which way it faces. HOW HIGH
 * it sits — a free offset, or "place on top", which asks the SERVER for the
 * surface height so plan, preview and 3D client cannot each arrive at their
 * own answer. WHETHER IT IS CUT: half a table against a wall is this table
 * with a plane through it, not a second library entry. And SCATTER, which
 * turns one placement into an anchor that throws copies over the area.
 *
 * THE STACK COUNTER IS NOT DECORATION. A stack is invisible on the plan — the
 * top footprint covers the rest — so "2/3 here" is the only thing that says
 * there is anything else under the cursor, and it makes the cycling click
 * discoverable instead of a secret.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { PropVariantPicker } from './PropVariantPicker'
import { fmtM, rM } from './planGeometry'
import type { RoomPropPlacement } from './worldTypes'

interface Props {
  placement: RoomPropPlacement
  /** Index in the room's `props` — the stack counter reads it. */
  index: number
  /** The prop's display name, when its dimensions are loaded. */
  name?: string
  /** Min corner of the shape the prop stands in, and its size: the two
   *  position sliders span exactly it. */
  origin: [number, number]
  size: { w: number; d: number }
  /** The shape is the YARD — the sliders measure from the anchor pin then. */
  ground: boolean
  /** Indices of everything standing on this exact spot, ascending (later
   *  placement = topmost), the selection included. Length 1 = no stack. */
  stackHits: number[]
  /** Ask the server where the top surface underneath is, and sit on it.
   *  Absent = nothing underneath, and the button says so. */
  onPlaceOnTop?: () => void
  /** Merge a patch into this placement, or remove it when null is passed. */
  onPatch: (patch: Partial<RoomPropPlacement> | null) => void
}

export function PlanPropStrip({
  placement, index, name, origin, size, ground, stackHits, onPlaceOnTop,
  onPatch,
}: Props) {
  const { t } = useI18n()
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>
        🪑 {name || placement.prop_id}:
      </span>
      {/* What the LLM calls this place — names the placement's markers in
          chips and prompts. ≤ 60 chars, the server trims the rest. */}
      <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('A name for this placement as a PLACE — the LLM and the marker chips call it that. Empty = the prop’s own name.')}>
        {t('Label')}
        <input
          type="text"
          className="ga-input"
          maxLength={60}
          style={{ width: 200 }}
          value={placement.label || ''}
          placeholder={t('e.g. armchair by the window — what the LLM calls this place')}
          onChange={(e) => onPatch({ label: e.target.value.slice(0, 60) || undefined })}
        />
      </label>
      {stackHits.length > 1 ? (
        <span
          className="ga-hint"
          title={t('Click the same spot again to select the next prop in this stack.')}
          style={{ border: '1px solid #444c56', borderRadius: 10,
                   padding: '1px 7px', cursor: 'help' }}
        >
          {t('{n}/{N} here')
            .replace('{n}', String(stackHits.indexOf(index) + 1))
            .replace('{N}', String(stackHits.length))}
        </span>
      ) : null}
      {/* Position in METRES from the shape's min corner (v6 Nr. 2), so the
          slider runs over its own box and the readback is a length one can
          measure against the 1.70 m figure on the plan. */}
      <SliderInput
        label="X"
        ariaLabel={t('Prop position X (m)')}
        title={ground
          ? t('Fine-tune the position: metres east of the anchor pin (negative = west).')
          : t('Fine-tune the position: metres from the room’s west edge.')}
        min={origin[0]}
        max={origin[0] + size.w}
        step={0.01}
        value={placement.at[0]}
        onChange={(v) => onPatch({ at: [rM(v), placement.at[1]] })}
        unit="m"
        sliderWidth={100}
        readback={<span style={{ minWidth: 52 }}>{fmtM(placement.at[0])} m</span>}
      />
      <SliderInput
        label="Y"
        ariaLabel={t('Prop position Y (m)')}
        title={ground
          ? t('Fine-tune the position: metres south of the anchor pin (negative = north).')
          : t('Fine-tune the position: metres from the room’s north edge.')}
        min={origin[1]}
        max={origin[1] + size.d}
        step={0.01}
        value={placement.at[1]}
        onChange={(v) => onPatch({ at: [placement.at[0], rM(v)] })}
        unit="m"
        sliderWidth={100}
        readback={<span style={{ minWidth: 52 }}>{fmtM(placement.at[1])} m</span>}
      />
      <SliderInput
        label="↻"
        ariaLabel={t('Prop yaw (°)')}
        title={t('Yaw in degrees — free values; R while placing steps 90°.')}
        min={0}
        max={359.5}
        step={0.5}
        fineStep={0.1}
        value={placement.yaw || 0}
        onChange={(v) => onPatch({ yaw: v || undefined })}
        unit="°"
        sliderWidth={120}
        inputWidth={68}
      />
      <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Vertical offset in metres, additive to the floor (e.g. a picture on the wall).')}>
        ↕ m
        <input
          type="number" min={-5} max={5} step={0.05}
          value={placement.offset_y ?? 0}
          onChange={(e) => {
            const v = Math.round((parseFloat(e.target.value) || 0) * 1000) / 1000
            onPatch({ offset_y: v || undefined })
          }}
          style={{ width: 70 }}
          className="ga-input"
        />
      </label>
      {/* Set it down ON the piece it stands over — the teapot onto the table.
          The button is OFFERED by the same footprint test that picks a prop
          out of a stack here; the height itself is the SERVER's answer
          (`POST /world/props/stack-y`, `props.stack_offset_y`). */}
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        disabled={!onPlaceOnTop}
        title={onPlaceOnTop
          ? t('Set this prop down on the top surface of the prop underneath it (the topmost one, if several).')
          : t('Nothing underneath: move the prop over another one first.')}
        onClick={() => onPlaceOnTop?.()}
      >
        ⬒ {t('Place on top')}
      </button>
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        disabled={!placement.offset_y}
        title={t('Back down onto the floor — clears the vertical offset.')}
        onClick={() => onPatch({ offset_y: undefined })}
      >
        ⬓ {t('Place on floor')}
      </button>
      {/* DEPTH CUT (§ B2 addendum 2026-08-23): how much of the prop's depth
          survives. 100 % = uncut and the placement stores no key at all. The
          plane is the SERVER's (`cut_plane` on the scene spec); this dial only
          says how much and from which side. */}
      <SliderInput
        label="✂"
        ariaLabel={t('Depth cut (%)')}
        title={t('Cut the prop across its depth: how many percent of it remain. 100 = whole prop. The cut face stays open, so put it against a wall.')}
        min={5}
        max={100}
        step={5}
        value={Math.round((placement.cut_keep ?? 1) * 100)}
        onChange={(v) => onPatch({
          cut_keep: v >= 100 ? undefined : Math.round(v) / 100,
          cut_side: v >= 100 ? undefined : (placement.cut_side || 'back'),
        })}
        unit="%"
        sliderWidth={100}
        inputWidth={62}
      />
      {placement.cut_keep && placement.cut_keep < 1 ? (
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          title={t('Which half remains: “front” is the top of the footprint on the plan, “back” the bottom — turned with the prop’s yaw.')}
          onClick={() => onPatch({
            cut_side: placement.cut_side === 'front' ? 'back' : 'front',
          })}
        >
          {placement.cut_side === 'front' ? t('Keep front') : t('Keep back')}
        </button>
      ) : null}
      {/* Scatter (v5.2 Nr. 12): a placement property — this anchor throws
          `scatter_count` copies over the room from its own seed; spacing alone
          rules the density (0 = may overlap). */}
      <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={ground
          ? t('Scatter: throw copies of THIS prop over the yard. The placement stays as the anchor; positions come from the seed and stay inside the location boundary — the rooms, the entrances and the markers stay clear.')
          : t('Scatter: throw copies of THIS prop over the room area. The placement stays as the anchor; positions come from the seed — the road, openings and markers stay clear.')}>
        <input
          type="checkbox"
          checked={!!placement.scatter_count}
          onChange={(e) => onPatch(e.target.checked
            ? { scatter_count: 10,
                scatter_seed: crypto.getRandomValues(new Uint32Array(1))[0] }
            : { scatter_count: undefined, scatter_seed: undefined,
                scatter_spacing_m: undefined })}
        />
        <span>{t('Scatter')}</span>
      </label>
      {placement.scatter_count ? (
        <>
          <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Number of scattered copies (Σ 120 per room; the anchor is extra).')}>
            n
            <input
              type="number" min={1} max={120} step={1}
              value={placement.scatter_count}
              onChange={(e) => {
                const v = Math.round(parseFloat(e.target.value) || 0)
                if (v >= 1) onPatch({ scatter_count: Math.min(120, v) })
              }}
              style={{ width: 62 }}
              className="ga-input"
            />
          </label>
          <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Minimum centre distance between the copies in metres — the whole density rule. 0 = they may overlap (a forest’s crowns do).')}>
            ↔ m
            <input
              type="number" min={0} max={5} step={0.1}
              value={placement.scatter_spacing_m ?? 0}
              onChange={(e) => {
                const v = Math.round((parseFloat(e.target.value) || 0) * 100) / 100
                onPatch({ scatter_spacing_m: v > 0 ? Math.min(5, v) : undefined })
              }}
              style={{ width: 62 }}
              className="ga-input"
            />
          </label>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            title={t('Reroll — a new seed gives a new arrangement.')}
            onClick={() => onPatch({
              scatter_seed: crypto.getRandomValues(new Uint32Array(1))[0] })}
          >
            🎲
          </button>
        </>
      ) : null}
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        onClick={() => onPatch(null)}
      >
        × {t('Remove')}
      </button>
      {/* Which model variant THIS placement shows — a dial like the others
          beside it, so it belongs in the same strip. */}
      <PropVariantPicker
        propId={placement.prop_id}
        variant={placement.variant}
        onVariant={(v) => onPatch({ variant: v })}
      />
    </div>
  )
}
