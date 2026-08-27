/**
 * THE PURE HALF OF THE POLYGON FACE PICK (spec-picture-props.md D5, ruling R1).
 *
 * Marking a key surface by hand is a SIGHT gesture: the admin draws a polygon
 * on the front view and the client turns it into the triangles the server has
 * to re-material. The geometry truth (the fitted plane, the planar UVs, the
 * material) stays on the server — this file only decides WHICH triangles were
 * meant, and it does it with two rules that can be checked without a browser:
 *
 *   1. `alignMeshLayout` — the flat triangle index the server speaks (R1) runs
 *      over the meshes sorted by NAME, triangles in buffer order within each.
 *      Before a single index is sent, the loaded three.js meshes have to BE
 *      that list: same names, same triangle counts, same order. A model that
 *      disagrees (regenerated since the last split) gets no indices at all —
 *      a mismatched index does not mark the wrong panel, it marks a random
 *      strip of the mesh.
 *   2. `pointInPolygon` — the crossing test the polygon itself is read with.
 *
 * Neither touches three.js, which is the point: the viewer does the projection
 * and the occlusion raycast (both need a live camera), these two are checkable
 * with `node`.
 */

import type { MeshLayoutEntry } from './propTypes'

/**
 * Do the LOADED meshes match the layout the server split against?
 *
 * Both lists must already be in R1 order (sorted by name). Equal length, equal
 * names, equal triangle counts — anything else means the mesh moved under the
 * area list and the polygon tool has to refuse.
 *
 * An EMPTY layout is a mismatch too: it is what a prop answers before its
 * first detection run, and there is no order to speak in yet.
 */
export function alignMeshLayout(loaded: MeshLayoutEntry[] | null | undefined,
                                layout: MeshLayoutEntry[] | null | undefined): boolean {
  if (!loaded?.length || !layout?.length) return false
  if (loaded.length !== layout.length) return false
  return loaded.every((m, i) => m.name === layout[i].name
    && m.tri_count === layout[i].tri_count)
}

/** Meshes in the R1 order — by name, ties kept in load order (a stable sort,
 *  so two nodes of the same name never swap between two runs). */
export function sortByName<T extends { name: string }>(meshes: T[]): T[] {
  return [...meshes].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
}

/** One entry of the R1 order: the name the SERVER knows it by, and the loaded
 *  meshes that make it up (indices into the load-order list, in that order). */
export interface MeshGroup {
  name: string
  members: number[]
}

/**
 * ONE loaded mesh, described by the glTF NODE it belongs to — everything the
 * R1 order needs and nothing three.js-shaped, so the grouping below can be
 * checked without a browser.
 */
export interface LoadedPrimitive {
  /** WHICH node — any stable key; the loader's node index where there is one.
   *  Two primitives of the same node share it, two nodes never do. */
  nodeKey: string
  /** The node's EXPORTED name, unsanitised: that is what Blender named the
   *  object and therefore what the server's `mesh_layout` lists. */
  name: string
  /** Primitive index inside the node's mesh — the order the triangles are
   *  concatenated in. */
  primitive: number
}

/**
 * THE LOADED MESHES AS THE SERVER COUNTS THEM (R1).
 *
 * The server counts per BLENDER OBJECT, which is per glTF NODE. three does not:
 *
 *   · a glTF mesh with several materials — exactly what a prop looks like once
 *     ONE area has been split off — arrives as one three `Mesh` PER PRIMITIVE
 *     under a `Group`, so two objects where Blender has one;
 *   · the names do not match either. GLTFLoader reserves the NODE's name first
 *     (`loadNode`: `createUniqueName(nodeDef.name)`) and then names every
 *     primitive `createUniqueName(meshDef.name)`, so node `Frame` with mesh
 *     `Frame` yields children `Frame_1` and `Frame_2` — and where the mesh
 *     DATA is called something else (`Cube`, `mesh_0`) the children carry that
 *     instead of the object name the server knows;
 *   · `createUniqueName` runs `PropertyBinding.sanitizeNodeName`, which strips
 *     `. : / [ ]` and replaces whitespace, so a Blender object `Frame.001` is
 *     `Frame001` in three and would never compare equal.
 *
 * So the name is taken from the NODE, never from the three object, and the
 * primitives of one node are folded back together in primitive order. That IS
 * the R1 sequence: same triangles, same flat index, and a layout that can be
 * compared to the server's. Without it the polygon tool would refuse from the
 * first split onwards — precisely when a correction is wanted.
 */
export function meshLayoutOf(meshes: LoadedPrimitive[]): MeshGroup[] {
  const byNode = new Map<string, { name: string; members: number[] }>()
  meshes.forEach((mesh, i) => {
    const group = byNode.get(mesh.nodeKey)
    if (group) group.members.push(i)
    else byNode.set(mesh.nodeKey, { name: mesh.name, members: [i] })
  })
  for (const group of byNode.values()) {
    // Primitive order, load order as the tie-break — `parent.children` is
    // already in primitive order, so this only guards a loader that ever
    // hands them over differently.
    group.members.sort((a, b) => (meshes[a].primitive - meshes[b].primitive) || (a - b))
  }
  // Sorted by NAME, like everything else in R1.
  return sortByName([...byNode.values()])
}

/**
 * Where the flat index of mesh `i`'s triangles starts — the sum of every
 * earlier mesh's triangle count.
 */
export function meshIndexBase(layout: MeshLayoutEntry[], meshIndex: number): number {
  let base = 0
  for (let i = 0; i < meshIndex && i < layout.length; i++) base += layout[i].tri_count
  return base
}

/**
 * Is (x, y) inside the polygon? Crossing-number test, boundary undefined (a
 * point exactly on an edge may fall either way — a triangle centre landing on
 * a hand-drawn line is a coin toss the admin cannot see anyway).
 *
 * The polygon is a closed ring: the last point connects back to the first, and
 * it is read in whatever units the caller uses (this tool: canvas pixels).
 */
export function pointInPolygon(x: number, y: number,
                               poly: Array<[number, number]>): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]
    const [xj, yj] = poly[j]
    // The half-open rule on y (`>` on one side, `<=` on the other) is what
    // stops a vertex exactly at the test height from being counted twice.
    if ((yi > y) !== (yj > y)
        && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

/** Shoelace area in the polygon's own units — a degenerate scribble (a
 *  double-click that dropped two points on the same spot) encloses nothing and
 *  must not be sent as a selection. */
export function polygonArea(poly: Array<[number, number]>): number {
  let s = 0
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    s += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1])
  }
  return Math.abs(s) / 2
}
