/**
 * thumbs — the ONE place that turns a full-size image URL into a thumbnail URL
 * (UI-8).
 *
 * A gallery tile is 72-100 CSS px, the file behind it is a 1024x1536 render of
 * 1-4 MB. The backend serves a scaled WebP under `/thumbs` + the original path
 * (`app/routes/thumbnails.py`); this helper builds that URL so no component
 * has to know the shape.
 *
 * RULES
 * - Only the widths the server accepts exist (`THUMB_WIDTHS`); anything else
 *   is a 400 there, so `thumbWidth()` always snaps UP to a real bucket.
 * - A URL the server has no thumbnail route for is returned UNCHANGED — that
 *   is the safe fallback (e.g. `/characters/x/outfit-expression`, a data: URL,
 *   an already-absolute foreign URL).
 * - The lightbox / detail view keeps the ORIGINAL url. Never route a full view
 *   through here.
 */

/** The width buckets `app/core/thumbnails.py` accepts, ascending. */
export const THUMB_WIDTHS = [96, 192, 384] as const

/** The exact URL shapes `app/routes/thumbnails.py` mirrors. Matched as whole
 *  paths, not as prefixes: `/world/locations/{id}/model` starts the same way
 *  as a gallery image and has no thumbnail route. */
const THUMBABLE = [
  /^\/characters\/[^/]+\/images\/[^/]+$/,      // incl. .../images/profile
  /^\/world\/locations\/[^/]+\/gallery\/[^/]+$/,
  /^\/inventory\/items\/[^/]+\/image$/,
]

/** The device pixel ratio, clamped — a 3x phone would otherwise always land
 *  on the largest bucket for a 48 px icon. */
function dpr(): number {
  const raw = typeof window !== 'undefined' ? window.devicePixelRatio : 1
  if (!raw || !isFinite(raw) || raw < 1) return 1
  return Math.min(raw, 2)
}

/**
 * The smallest bucket that still covers `cssWidth` CSS pixels on this screen.
 * Falls back to the largest bucket when even that is too small (the tile is
 * then slightly soft — still far better than the multi-megabyte original).
 */
export function thumbWidth(cssWidth: number): number {
  const need = Math.ceil(Math.max(1, cssWidth) * dpr())
  for (const w of THUMB_WIDTHS) if (w >= need) return w
  return THUMB_WIDTHS[THUMB_WIDTHS.length - 1]
}

/**
 * The thumbnail URL for a full-size image URL, or the input unchanged when the
 * server has no thumbnail route for it.
 *
 * `width` is a bucket (use `thumbWidth(cssPx)`); an existing query string on
 * the input is dropped — a cache-busting `?t=` belongs on the original, and
 * the thumbnail is already keyed by the source's mtime.
 */
export function thumbUrl(url: string, width: number): string {
  if (!url) return url
  const path = url.split('?')[0].split('#')[0]
  if (!THUMBABLE.some((re) => re.test(path))) return url
  return `/thumbs${path}?w=${width}`
}
