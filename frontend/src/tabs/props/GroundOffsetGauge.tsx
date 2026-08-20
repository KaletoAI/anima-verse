/**
 * GroundOffsetGauge — the visible reference for the prop's GROUND OFFSET dial.
 *
 * A metre value without a visible scale means something different to the user
 * than to the system (user directive 2026-07-28), so the dial gets its own
 * side elevation: the ground as a line, the prop's own box seated at the
 * dialled offset, a 1.70 m person standing beside it at TRUE SCALE, a metre
 * ruler in the dial's own unit, and the number itself written at the distance
 * it means.
 *
 * The figure never scales with anything — it is the constant the rest is read
 * against. The prop box is the prop's REAL width and height (the three dims of
 * the library record), so how deep 20 cm is depends on whether the object is a
 * fir or a footstool, which is exactly the judgement the dial needs.
 *
 * Pure SVG and pure arithmetic — no three.js, no payload, nothing to load: the
 * gauge is drawn from the same numbers the field commits.
 */
import { useI18n } from '../../i18n/I18nProvider'

/** The reference person, in metres. Never scaled, never configurable — it is
 *  the same 1.70 m the scene payload states for every figure (§ A3). */
const FIGURE_M = 1.7

const BOX_W = 300
const BOX_H = 160
const PAD_TOP = 14
const PAD_BOTTOM = 14
/** Where the figure stands and where the prop stands, in px from the left. */
const FIGURE_X = 44
const PROP_X = 132

export interface GroundOffsetGaugeProps {
  /** The dialled offset in metres — negative sinks the prop. */
  offsetM: number
  /** The prop's real footprint width and height in metres (the box drawn). */
  widthM: number
  heightM: number
}

/** Ruler spacing: whole metres for a tall scene, 0.5 m for a small one, 0.1 m
 *  for a footstool — a ruler nobody can count is not a ruler. */
function tickStep(spanM: number): number {
  if (spanM > 6) return 2
  if (spanM > 2.5) return 1
  if (spanM > 0.8) return 0.5
  return 0.1
}

export function GroundOffsetGauge({ offsetM, widthM, heightM }: GroundOffsetGaugeProps) {
  const { t } = useI18n()
  const off = Number.isFinite(offsetM) ? offsetM : 0
  const h = Number.isFinite(heightM) && heightM > 0 ? heightM : 1
  const w = Number.isFinite(widthM) && widthM > 0 ? widthM : 1
  // What the picture has to hold: the taller of figure and seated prop above
  // the ground, and whatever hangs below it.
  const topM = Math.max(FIGURE_M, off + h, 0.2)
  const botM = Math.min(0, off, -0.05)
  const spanM = topM - botM
  const scale = (BOX_H - PAD_TOP - PAD_BOTTOM) / spanM
  const yOf = (m: number) => PAD_TOP + (topM - m) * scale
  const groundY = yOf(0)

  const step = tickStep(spanM)
  const ticks: number[] = []
  for (let m = Math.ceil(botM / step) * step; m <= topM + 1e-9; m += step) {
    ticks.push(Math.round(m * 1000) / 1000)
  }

  // The box: real width, capped so a 40 m wall does not push the picture out
  // of the panel — the HEIGHT is never capped, because that is the axis the
  // dial moves and a lie there would defeat the whole gauge.
  const boxW = Math.min(w * scale, BOX_W - PROP_X - 16)
  const boxTop = yOf(off + h)
  const boxBottom = yOf(off)
  const figTop = yOf(FIGURE_M)
  const figH = groundY - figTop
  const label = `${off > 0 ? '+' : ''}${off.toFixed(2)} m`

  const muted = 'var(--text-muted, #8b949e)'
  const border = 'var(--border, #30363d)'
  const accent = 'var(--accent, #58a6ff)'

  return (
    <svg width="100%" viewBox={`0 0 ${BOX_W} ${BOX_H}`} role="img"
      style={{ maxWidth: BOX_W, display: 'block' }}
      aria-label={t('Side view: the prop at the dialled ground offset, beside a 1.70 m person.')}>
      {/* Soil — everything below the ground line. */}
      <defs>
        <pattern id="gog-soil" width="6" height="6" patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke={border} strokeWidth="1" />
        </pattern>
      </defs>
      <rect x="0" y={groundY} width={BOX_W} height={Math.max(0, BOX_H - groundY)}
        fill="url(#gog-soil)" opacity="0.5" />

      {/* The ruler, in the dial's own unit. */}
      {ticks.map((m) => (
        <g key={m}>
          <line x1="26" y1={yOf(m)} x2={BOX_W} y2={yOf(m)} stroke={border}
            strokeWidth="1" strokeDasharray={m === 0 ? '' : '2 4'} opacity={m === 0 ? 1 : 0.7} />
          <text x="24" y={yOf(m) + 3} textAnchor="end" fontSize="8" fill={muted}>
            {step < 1 ? m.toFixed(1) : String(m)}
          </text>
        </g>
      ))}

      {/* The 1.70 m person, standing ON the ground line, never scaled with
          anything else in the picture. */}
      <g>
        <circle cx={FIGURE_X} cy={figTop + figH * 0.09} r={Math.max(2, figH * 0.075)}
          fill={muted} />
        <rect x={FIGURE_X - Math.max(2, figH * 0.09)} y={figTop + figH * 0.19}
          width={Math.max(4, figH * 0.18)} height={figH * 0.81}
          rx={Math.max(1, figH * 0.05)} fill={muted} opacity="0.75" />
        <text x={FIGURE_X} y={figTop - 4} textAnchor="middle" fontSize="8" fill={muted}>
          {t('1.70 m')}
        </text>
      </g>

      {/* The prop, seated at the dialled offset. */}
      <rect x={PROP_X} y={boxTop} width={boxW} height={Math.max(1, boxBottom - boxTop)}
        fill={accent} opacity="0.28" stroke={accent} strokeWidth="1.2" />
      <text x={PROP_X + boxW / 2} y={boxTop - 4} textAnchor="middle" fontSize="8" fill={muted}>
        {`${w.toFixed(2)} × ${h.toFixed(2)} m`}
      </text>

      {/* The number, written at the distance it means. */}
      {Math.abs(off) > 0.001 ? (
        <g>
          <line x1={PROP_X - 12} y1={groundY} x2={PROP_X - 12} y2={boxBottom}
            stroke={accent} strokeWidth="1.4" />
          <line x1={PROP_X - 17} y1={boxBottom} x2={PROP_X - 7} y2={boxBottom}
            stroke={accent} strokeWidth="1.4" />
          <text x={PROP_X - 20} y={(groundY + boxBottom) / 2 + 3} textAnchor="end"
            fontSize="9" fill={accent}>{label}</text>
        </g>
      ) : (
        <text x={PROP_X - 8} y={groundY - 4} textAnchor="end" fontSize="9" fill={muted}>
          {t('on the ground')}
        </text>
      )}
    </svg>
  )
}
