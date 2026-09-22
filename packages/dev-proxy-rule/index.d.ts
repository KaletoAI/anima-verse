/**
 * Types for `index.js`.
 *
 * The rule itself stays plain JavaScript so `node` — and with it
 * `scripts/smoke_vite_proxy.py` — can import it without a build step; this
 * file only makes it typed for the two `vite.config.ts`.
 */
export declare const VITE_PREFIXES: string[]
export declare function htmlEntryMap(
  entries: string[],
  aliases?: Record<string, string>,
): Record<string, string>
export declare function publicPaths(publicDir: URL | string): Set<string>
/** The rule for one app: the path Vite serves, or `null` for the backend. */
export declare function createDevTarget(options: {
  publicDir: URL | string
  entries: string[]
  aliases?: Record<string, string>
}): (url: string) => string | null
