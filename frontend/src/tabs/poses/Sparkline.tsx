/**
 * Sparkline — the hip-height profile of a mocap take as a tiny inline SVG.
 *
 * The catalog measures 40 points of `hips_rel` per take (root height over the
 * actor's leg length; ~0.9 standing, low means sitting or lying). That curve is
 * what tells a browsing eye "stands up in the middle", "lies down at the end",
 * "steady walk" apart at a glance — one look per row instead of reading five
 * numbers.
 *
 * The vertical scale is FIXED to 0…1.15 on purpose, not normalised per take: a
 * per-take scale would make a dead-flat standing take look as dramatic as a
 * real stand-up, and every row would lie about a different range. Values above
 * the range are clamped, so a jump only flattens at the top.
 *
 * `from`/`to` (seconds, together with `duration`) shade the window an import
 * would keep — the orientation the import form's start/end fields need.
 */
const MIN_V = 0
const MAX_V = 1.15

export function Sparkline({
  values,
  width = 120,
  height = 26,
  from,
  to,
  duration,
  title,
}: {
  values: number[]
  width?: number
  height?: number
  /** window start in seconds (needs `duration`) */
  from?: number
  /** window end in seconds (needs `duration`) */
  to?: number
  duration?: number
  title?: string
}) {
  if (!values?.length) return null
  const n = values.length
  const y = (v: number) => {
    const c = Math.min(MAX_V, Math.max(MIN_V, v))
    return height - ((c - MIN_V) / (MAX_V - MIN_V)) * height
  }
  const points = values
    .map((v, i) => `${((i / Math.max(1, n - 1)) * width).toFixed(2)},${y(v).toFixed(2)}`)
    .join(' ')
  // The standing line (0.9) is the reference the posture rule uses — drawing it
  // makes "below standing" readable without a legend.
  const standing = y(0.9)

  const hasWindow =
    duration && duration > 0 && (from !== undefined || to !== undefined)
  const x0 = hasWindow ? (Math.max(0, from ?? 0) / duration!) * width : 0
  const x1 = hasWindow
    ? (Math.min(duration!, to ?? duration!) / duration!) * width
    : width

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={title || 'hip height'}
      style={{ display: 'block', overflow: 'visible' }}
    >
      {title ? <title>{title}</title> : null}
      {hasWindow ? (
        <>
          <rect x={0} y={0} width={width} height={height} fill="rgba(0,0,0,0.28)" />
          <rect
            x={Math.min(x0, x1)}
            y={0}
            width={Math.max(1, Math.abs(x1 - x0))}
            height={height}
            fill="rgba(88,166,255,0.16)"
          />
        </>
      ) : null}
      <line
        x1={0}
        y1={standing}
        x2={width}
        y2={standing}
        stroke="rgba(255,255,255,0.18)"
        strokeWidth={1}
      />
      <polyline
        points={points}
        fill="none"
        stroke="#58a6ff"
        strokeWidth={1.2}
        strokeLinejoin="round"
      />
      {hasWindow ? (
        <>
          <line x1={x0} y1={0} x2={x0} y2={height} stroke="#3fb950" strokeWidth={1.5} />
          <line x1={x1} y1={0} x2={x1} y2={height} stroke="#f78166" strokeWidth={1.5} />
        </>
      ) : null}
    </svg>
  )
}
