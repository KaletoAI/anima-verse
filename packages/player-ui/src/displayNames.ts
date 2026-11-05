/**
 * The avatar's view of a person — display-only secrecy of a disguised
 * character (`app/core/identity_view.py::player_view`).
 *
 * The player payloads keep every KEY and URL on the real name (`name`,
 * `present[]`, `meta.speaker`, `/characters/<name>/…`), and that is what a
 * client posts back. What it PRINTS comes from the server's view instead:
 * `display_name` on an entry, a `display_names` map beside a list of keys,
 * `meta.speaker_shown` / `meta.addressees_shown` on a scene line. A
 * `portrait_url` replaces the real portrait of a person whose disguise the
 * avatar is not in on — present but `''` means "show the no-portrait
 * placeholder", absent means "today's portrait".
 */

/** What to print for the real key `name`: the server's shown name, else the key. */
export function shownName(displayNames: Record<string, string> | null | undefined, name: string): string {
  return (displayNames && displayNames[name]) || name
}

/** The portrait override for `name`: `undefined` = none (use the real
 *  portrait), `''` = the placeholder, otherwise the persona portrait URL. */
export function portraitOverride(portraitUrls: Record<string, string> | null | undefined,
  name: string): string | undefined {
  if (!portraitUrls || !Object.prototype.hasOwnProperty.call(portraitUrls, name)) return undefined
  return portraitUrls[name] || ''
}
