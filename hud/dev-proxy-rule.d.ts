/**
 * Types for `dev-proxy-rule.js`.
 *
 * The rule itself stays plain JavaScript so `node` — and with it
 * `scripts/smoke_vite_proxy.py` — can import it without a build step; this
 * file only makes it typed for `vite.config.ts`.
 */
export declare const ENTRIES: string[]
/** The path Vite serves for `url`, or `null` when it belongs to the backend. */
export declare const viteDevTarget: (url: string) => string | null
