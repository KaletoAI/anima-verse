// Budget fields of the free-mode panel: an empty field means the server
// default, token budgets are typed and shown in thousands.

/** A positive integer from a text field, or undefined (empty / invalid). */
export function posInt(raw: string): number | undefined {
  const n = parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : undefined
}

/** A token budget typed in thousands ("500" = 500k) as plain tokens, or
 *  undefined (empty / invalid) — the server then applies its default. */
export function kToTokens(raw: string): number | undefined {
  const k = posInt(raw)
  return k === undefined ? undefined : k * 1000
}

/** Plain tokens shown in thousands, half up: 1499 → "1k", 2000000 → "2,000k". */
export function tokensK(n: number): string {
  return Math.round(n / 1000).toLocaleString() + 'k'
}
