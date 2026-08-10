import * as THREE from 'three';
import { CELL } from '../game/gridLegacy';

/** The grid world's cell anchor, kept alive here alone: `tiles.ts` builds
 *  footprints now (E4 task 3) and no longer maps cells to the world.
 *  TODO(E4 task 5): this whole module is up for deletion — E4 has no client
 *  A* ("Luftlinie + Wand-Gleiten"), so `pathfind.ts` is expected to be
 *  orphaned by then. */
function gridToWorld(gx: number, gy: number): THREE.Vector3 {
  return new THREE.Vector3(gx * CELL, 0, gy * CELL);
}

/**
 * Wegfindung auf dem Karten-Grid: NPCs sollen um Gebäude herumlaufen statt
 * hindurch. Begehbar sind Zellen mit `passable` (Straßen, Wald, Wiesen) sowie
 * Start- und Zielzelle selbst (dort steht ja das Gebäude, das sie betreten).
 * Leere Zellen (keine Location) sind ebenfalls begehbar — sonst wären Orte am
 * Kartenrand unerreichbar.
 *
 * Drei Härtungen, damit die Suche den Main-Thread nicht blockiert (der
 * NPC-Poll ruft sie jede Sekunde je Figur auf):
 *
 * 1. **Binär-Heap** statt Linear-Scan über die offene Liste — der Scan war
 *    O(n) pro Knoten und damit O(n²) über die Suche.
 * 2. **Suchraum-Begrenzung**: leere Zellen sind begehbar, also lief die Suche
 *    bei einem UNERREICHBAREN Ziel ins Nichts, bis der `guard` griff. Jetzt
 *    begrenzt eine BBox um Start/Ziel (plus Rand), geschnitten mit den
 *    Kartengrenzen, den Raum — unerreichbar wird dadurch schnell erkannt.
 * 3. **Ergebnis-Cache** je (Start, Ziel), inklusive der Fehlschläge. Das Grid
 *    ist unveränderlich (bei Weltänderungen baut main.ts ein neues), also
 *    braucht der Cache keine Versionierung.
 */

/** Zusätzlicher Rand um die Start/Ziel-BBox, damit Umwege möglich bleiben. */
const SEARCH_MARGIN = 6;
/** Obergrenze des Ergebnis-Caches (FIFO); Karten haben ~50 Orte. */
const CACHE_MAX = 4000;

interface PathNode { key: string; x: number; y: number; g: number; f: number }

/** Weg aus cameFrom zurückverfolgen und kollineare Zwischenpunkte entfernen
 *  (weniger Wegpunkte = weichere Wege). Unverändert gegenüber der
 *  Vorversion — nur aus findPath herausgezogen. */
function rebuild(start: string, goal: string,
                 cameFrom: Map<string, string>): THREE.Vector3[] {
  const cells: Array<[number, number]> = [];
  let cur = goal;
  while (cur !== start) {
    const [cx, cy] = cur.split(',').map(Number);
    cells.push([cx, cy]);
    const prev = cameFrom.get(cur);
    if (!prev) return [];        // Kette gerissen (darf nicht vorkommen)
    cur = prev;
  }
  cells.reverse();

  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < cells.length; i++) {
    const prev = cells[i - 1], cell = cells[i], next = cells[i + 1];
    if (prev && next) {
      const d1x = cell[0] - prev[0], d1y = cell[1] - prev[1];
      const d2x = next[0] - cell[0], d2y = next[1] - cell[1];
      if (d1x === d2x && d1y === d2y) continue;   // gerade Strecke
    }
    pts.push(gridToWorld(cell[0], cell[1]));
  }
  return pts;
}

/** Min-Heap über f. Veraltete Einträge werden beim Pop verworfen (lazy
 *  deletion), das ist billiger als eine Decrease-Key-Operation. */
class MinHeap {
  private a: PathNode[] = [];

  get size(): number {
    return this.a.length;
  }

  push(n: PathNode): void {
    const a = this.a;
    a.push(n);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p].f <= a[i].f) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }

  pop(): PathNode | undefined {
    const a = this.a;
    if (!a.length) return undefined;
    const top = a[0];
    const last = a.pop()!;
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < a.length && a[l].f < a[m].f) m = l;
        if (r < a.length && a[r].f < a[m].f) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

export class PathGrid {
  private blocked = new Set<string>();
  private known = new Set<string>();
  /** Kartengrenzen der bekannten Zellen — begrenzen den Suchraum. */
  private minX = 0; private maxX = 0; private minY = 0; private maxY = 0;
  /** Ergebnis-Cache je (Start -> Ziel); leeres Array = nachweislich kein Weg. */
  private cache = new Map<string, THREE.Vector3[]>();
  /** Diagnose des letzten Laufs (Abnahme/Debug): expandierte Knoten. */
  lastExpanded = 0;

  constructor(cells: Array<{ x: number; y: number; passable: boolean }>) {
    let first = true;
    for (const c of cells) {
      const key = `${c.x},${c.y}`;
      this.known.add(key);
      if (!c.passable) this.blocked.add(key);
      if (first) {
        this.minX = this.maxX = c.x;
        this.minY = this.maxY = c.y;
        first = false;
      } else {
        if (c.x < this.minX) this.minX = c.x;
        if (c.x > this.maxX) this.maxX = c.x;
        if (c.y < this.minY) this.minY = c.y;
        if (c.y > this.maxY) this.maxY = c.y;
      }
    }
  }

  private walkable(x: number, y: number, from: string, to: string): boolean {
    const key = `${x},${y}`;
    if (key === from || key === to) return true;      // Start/Ziel immer erlaubt
    return !this.blocked.has(key);
  }

  /**
   * Weg von Zelle A nach B (A*, 8er-Nachbarschaft). Gibt Weltpunkte zurück
   * (Zellmitten); leer, wenn kein Weg existiert — dann läuft der NPC direkt.
   */
  findPath(ax: number, ay: number, bx: number, by: number): THREE.Vector3[] {
    const start = `${ax},${ay}`;
    const goal = `${bx},${by}`;
    if (start === goal) return [];

    const cacheKey = `${start}>${goal}`;
    const hit = this.cache.get(cacheKey);
    // Kopien herausgeben: die Aufrufer dürfen ihre Wegpunkte behalten und
    // verbrauchen, ohne den Cache zu verändern.
    if (hit) return hit.map((p) => p.clone());

    // Suchraum: BBox um Start/Ziel plus Rand, geschnitten mit den
    // Kartengrenzen (+1). Start und Ziel liegen per Konstruktion drin.
    const loX = Math.max(Math.min(ax, bx) - SEARCH_MARGIN, Math.min(this.minX - 1, ax, bx));
    const hiX = Math.min(Math.max(ax, bx) + SEARCH_MARGIN, Math.max(this.maxX + 1, ax, bx));
    const loY = Math.max(Math.min(ay, by) - SEARCH_MARGIN, Math.min(this.minY - 1, ay, by));
    const hiY = Math.min(Math.max(ay, by) + SEARCH_MARGIN, Math.max(this.maxY + 1, ay, by));
    const inBounds = (x: number, y: number) => x >= loX && x <= hiX && y >= loY && y <= hiY;
    // Backstop: doppelte Fläche des Suchraums — greift nur bei Denkfehlern,
    // die Begrenzung oben ist die eigentliche Schranke.
    const guardMax = 2 * (hiX - loX + 1) * (hiY - loY + 1);

    const h = (x: number, y: number) => Math.hypot(x - bx, y - by);
    const open = new MinHeap();
    const closed = new Set<string>();
    const cameFrom = new Map<string, string>();
    const gScore = new Map<string, number>([[start, 0]]);
    open.push({ key: start, x: ax, y: ay, g: 0, f: h(ax, ay) });

    let guard = 0;
    let reached = false;
    while (open.size && guard < guardMax) {
      const best = open.pop()!;
      // veralteter Heap-Eintrag (es gibt einen besseren Weg zu dieser Zelle)
      if (best.g > (gScore.get(best.key) ?? Infinity)) continue;
      if (closed.has(best.key)) continue;
      closed.add(best.key);
      guard++;
      if (best.key === goal) { reached = true; break; }

      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          if (!dx && !dy) continue;
          const nx = best.x + dx, ny = best.y + dy;
          if (!inBounds(nx, ny)) continue;
          const nkey = `${nx},${ny}`;
          if (closed.has(nkey)) continue;
          if (!this.walkable(nx, ny, start, goal)) continue;
          // Diagonale nur, wenn beide Nachbarn frei sind (keine Ecken schneiden)
          if (dx && dy) {
            if (!this.walkable(best.x + dx, best.y, start, goal)) continue;
            if (!this.walkable(best.x, best.y + dy, start, goal)) continue;
          }
          // unbekannte Zellen leicht bestrafen (lieber auf Wegen bleiben)
          const step = (dx && dy ? 1.414 : 1) * (this.known.has(nkey) ? 1 : 1.6);
          const g = best.g + step;
          if (g >= (gScore.get(nkey) ?? Infinity)) continue;
          gScore.set(nkey, g);
          cameFrom.set(nkey, best.key);
          open.push({ key: nkey, x: nx, y: ny, g, f: g + h(nx, ny) });
        }
      }
    }
    this.lastExpanded = guard;

    const result = reached && cameFrom.has(goal) ? rebuild(start, goal, cameFrom) : [];
    this.remember(cacheKey, result);
    return result.map((p) => p.clone());
  }

  private remember(key: string, path: THREE.Vector3[]): void {
    if (this.cache.size >= CACHE_MAX) {
      // FIFO: ältesten Eintrag verwerfen (Map hält Einfügereihenfolge)
      const oldest = this.cache.keys().next().value;
      if (oldest !== undefined) this.cache.delete(oldest);
    }
    this.cache.set(key, path);
  }

  /** Zellkoordinaten eines Weltpunkts. */
  static cellOf(p: THREE.Vector3): { x: number; y: number } {
    return { x: Math.round(p.x / CELL), y: Math.round(p.z / CELL) };
  }
}
