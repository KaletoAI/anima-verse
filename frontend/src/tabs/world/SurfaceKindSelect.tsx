/**
 * SurfaceKindSelect — ONE way to pick a surface-texture kind, everywhere on
 * the floor-plan tab: the storey's floor and wall, and the two shell surfaces
 * of a room.
 *
 * WHAT IT SHOWS IS THE TILE, NOT A PICTOGRAM. The level pickers used to carry
 * 🟫 and 🧱 in front of them — two coloured squares that name a category and
 * say nothing about the chosen texture, sitting next to each other where the
 * difference matters most. The icon here is the kind's OWN image
 * (`SurfaceKind.url`, served by GET /assets/surface-textures/{file}), so the
 * field answers "what does this storey look like" without opening the list;
 * the WORD next to it ("Floor" / "Wall") carries the category the emoji was
 * trying to. Nothing chosen leaves an empty frame, which reads as "not set"
 * rather than as a texture nobody recognises.
 *
 * Purely presentational — the caller owns the value and the list.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { useEnlarge } from '../../components/ZoomButton'
import type { SurfaceKind } from './worldTypes'

interface Props {
  /** The word in front of the field — the category the swatch cannot say
   *  ("Floor", "Wall"). Translated here, so hand in the English source. */
  label: string
  /** Currently stored kind ('' = nothing chosen). A kind the list no longer
   *  offers stays selectable, so a texture removed from the library does not
   *  silently reset a location on the next save. */
  value: string
  kinds: SurfaceKind[]
  onChange: (kind: string) => void
  /** First entry of the list — what "nothing chosen" MEANS here, which
   *  differs per slot ("global kind", "plain shell colour", "default"). */
  emptyLabel: string
  /** Tooltip of the whole field: what the pick does in the scene. */
  title?: string
  /** Width of the label column in px — keeps a column of these aligned. */
  labelWidth?: number
}

export function SurfaceKindSelect({
  label, value, kinds, onChange, emptyLabel, title, labelWidth = 38,
}: Props) {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  const thumb = kinds.find((s) => s.kind === value)?.url
  return (
    <label
      className="ga-surface-pick"
      title={title}
    >
      <span style={{ width: labelWidth, flex: '0 0 auto' }}>{t(label)}</span>
      {thumb ? (
        <img
          className="ga-list-thumb ga-surface-swatch"
          alt=""
          src={thumb}
          {...enlarge({ src: thumb, alt: value, caption: value },
                      { width: 20, height: 20 })}
        />
      ) : (
        <span className="ga-surface-swatch ga-surface-swatch--empty" aria-hidden />
      )}
      <select
        className="ga-input"
        style={{ flex: 1, minWidth: 0 }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{t(emptyLabel)}</option>
        {kinds.map((s) => (
          <option key={s.kind} value={s.kind}>{s.name}</option>
        ))}
        {value && !kinds.some((s) => s.kind === value) ? (
          <option value={value}>{value}</option>
        ) : null}
      </select>
    </label>
  )
}
