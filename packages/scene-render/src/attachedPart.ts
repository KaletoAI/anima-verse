/**
 * THE ATTACHED PART ALONE (Ruling A129.9) — which triangles of a skinned body belong to its attached part, so a
 * preview can hide the partner's body and keep only the part (the extension group) visible.
 *
 * A triangle belongs to the part when EVERY one of its three vertices carries at least `share` of its skin weight on
 * the part's bones (the bones of the motion groups that carry an op: `partBoneNames`). Pure: the caller hands the
 * skin index/weight arrays (4 influences per vertex, three.js layout) and the triangle index; the answer is the
 * filtered index, in the original order. `scripts/smoke_attached_part.mjs` derives its numbers by hand.
 */

/** Default: at least half of a vertex's skin weight on the part's bones. */
export const PART_WEIGHT_SHARE = 0.5

/** The part's bones: every bone of a motion group whose `op` is set (hair groups carry none). */
export function partBoneNames(groups: Readonly<Record<string, { bones: readonly string[]; op?: string | null }>>): Set<string> {
  const out = new Set<string>()
  for (const g of Object.values(groups)) if (g.op) for (const b of g.bones) out.add(b)
  return out
}

/** The triangles (index triples) whose three vertices all weigh ≥ `share` on `partBones` (skeleton bone indices). */
export function attachedPartIndex(index: ArrayLike<number>, skinIndex: ArrayLike<number>, skinWeight: ArrayLike<number>,
  partBones: ReadonlySet<number>, share = PART_WEIGHT_SHARE): number[] {
  const vertexShare = (v: number) => {
    let w = 0, all = 0
    for (let k = 0; k < 4; k++) {
      const x = skinWeight[v * 4 + k]
      all += x
      if (partBones.has(skinIndex[v * 4 + k])) w += x
    }
    return all > 0 ? w / all : 0
  }
  const memo = new Map<number, boolean>()
  const inPart = (v: number) => {
    let hit = memo.get(v)
    if (hit === undefined) { hit = vertexShare(v) >= share; memo.set(v, hit) }
    return hit
  }
  const out: number[] = []
  for (let t = 0; t + 2 < index.length; t += 3) {
    const a = index[t], b = index[t + 1], c = index[t + 2]
    if (inPart(a) && inPart(b) && inPart(c)) out.push(a, b, c)
  }
  return out
}
