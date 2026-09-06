/**
 * PlanModelPlacement — where the selected room's DIORAMA stands inside it:
 * two metre sliders, a height offset and the shell clip. Mirrors the prop
 * strip, because it is the same question asked about a bigger object.
 *
 * SHELL CLIP (§ B1): a real-size diorama may be bigger than the floor plan it
 * belongs to. With the clip on, the renderer cuts it at the room hull — the
 * DRAWN polygon, not just the rectangle — and looking into a cut edge shows
 * the room's inside, because there is no cap surface. An outdoor room has no
 * hull, so the server ignores the flag there and the checkbox stays away.
 *
 * "Render walls" used to stand here and was therefore invisible until a room
 * HAD a diorama — while a wall-less zone is exactly a room that has none
 * (E5 inventory 1a). It lives in the side panel now, with the room's other
 * shell properties.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { clamp, rM } from './planGeometry'
import type { PlacedLayout } from './worldTypes'

interface Props {
  /** The selected room's layout — it has a rectangle and a model. */
  layout: PlacedLayout
  onPatch: (patch: Partial<PlacedLayout>) => void
}

export function PlanModelPlacement({ layout: lay, onPatch }: Props) {
  const { t } = useI18n()
  // Absent = centred, which in metres is (w/2, d/2).
  const at = lay.model_at || [lay.w / 2, lay.d / 2]
  const setAt = (axis: 0 | 1, v: number) => {
    const next: [number, number] = [at[0], at[1]]
    next[axis] = rM(clamp(v, 0, axis === 0 ? lay.w : lay.d))
    onPatch({ model_at: next })
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>
        ⌂ {t('Model placement')}:
      </span>
      {(['X', 'Y'] as const).map((label, axis) => (
        <SliderInput
          key={label}
          label={label}
          ariaLabel={t('Room model anchor')}
          title={t('Anchor of the room model: metres from the room’s min corner.')}
          min={0}
          max={axis === 0 ? lay.w : lay.d}
          step={0.01}
          value={at[axis]}
          onChange={(v) => setAt(axis as 0 | 1, v)}
          unit="m"
          sliderWidth={110}
          style={{ gap: 4 }}
        />
      ))}
      <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Height offset of the MODEL in real metres, relative to the room floor — negative sinks it.')}>
        {t('Model height (m)')}
        <input className="ga-input" type="number" step={0.05}
          style={{ width: 78 }}
          value={lay.model_offset_y ?? 0}
          onChange={(e) => {
            const v = Number(e.target.value)
            onPatch({
              model_offset_y: Number.isFinite(v) && v !== 0 ? v : undefined,
            })
          }} />
      </label>
      {!lay.always_visible ? (
        <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
          title={t('Cut the model at the room hull: everything sticking out over the floor plan is hidden (the drawn polygon counts, not just the rectangle). Looking into a cut edge shows the room’s inside — there is no cap surface.')}>
          <input type="checkbox"
            checked={!!lay.clip_model}
            onChange={(e) => onPatch({
              clip_model: e.target.checked ? true : undefined,
            })} />
          {t('Clip model to room bounds')}
        </label>
      ) : null}
      <button type="button" className="ga-btn ga-btn-sm"
        title={t('Back to the centred default placement.')}
        onClick={() => onPatch({
          model_at: undefined, model_offset_y: undefined,
        })}>
        ↺
      </button>
    </div>
  )
}
