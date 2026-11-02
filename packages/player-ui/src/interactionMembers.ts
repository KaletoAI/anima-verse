/** Who takes part in a running interaction, as the server states it
 *  (§ A8a): clip role ("a".."e") → character name, the character itself
 *  included. A pair has two roles; a group (G2c) up to five. */
export type InteractionMembers = Record<string, string>

/** Everyone in `members` except `self`, in role order. */
export function othersIn(members: InteractionMembers | undefined, self: string): string[] {
  const all = members || {}
  return Object.keys(all).sort().map((role) => all[role]).filter((name) => !!name && name !== self)
}

/** Whether `name` is one of the `members`. */
export function isMember(members: InteractionMembers | undefined, name: string): boolean {
  return !!name && Object.values(members || {}).includes(name)
}
