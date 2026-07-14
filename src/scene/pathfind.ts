import * as THREE from 'three';
import { CELL, gridToWorld } from './tiles';

/**
 * Wegfindung auf dem Karten-Grid: NPCs sollen um Gebäude herumlaufen statt
 * hindurch. Begehbar sind Zellen mit `passable` (Straßen, Wald, Wiesen) sowie
 * Start- und Zielzelle selbst (dort steht ja das Gebäude, das sie betreten).
 * Leere Zellen (keine Location) sind ebenfalls begehbar — sonst wären Orte am
 * Kartenrand unerreichbar.
 */
export class PathGrid {
  private blocked = new Set<string>();
  private known = new Set<string>();

  constructor(cells: Array<{ x: number; y: number; passable: boolean }>) {
    for (const c of cells) {
      const key = `${c.x},${c.y}`;
      this.known.add(key);
      if (!c.passable) this.blocked.add(key);
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

    const h = (x: number, y: number) => Math.hypot(x - bx, y - by);
    const open = new Map<string, { x: number; y: number; g: number; f: number }>();
    const cameFrom = new Map<string, string>();
    const gScore = new Map<string, number>([[start, 0]]);
    open.set(start, { x: ax, y: ay, g: 0, f: h(ax, ay) });

    let guard = 0;
    while (open.size && guard++ < 4000) {
      // Knoten mit kleinstem f
      let bestKey = '';
      let best = { x: 0, y: 0, g: 0, f: Infinity };
      for (const [k, n] of open) if (n.f < best.f) { bestKey = k; best = n; }
      if (bestKey === goal) break;
      open.delete(bestKey);

      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          if (!dx && !dy) continue;
          const nx = best.x + dx, ny = best.y + dy;
          const nkey = `${nx},${ny}`;
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
          cameFrom.set(nkey, bestKey);
          open.set(nkey, { x: nx, y: ny, g, f: g + h(nx, ny) });
        }
      }
    }

    if (!cameFrom.has(goal)) return [];

    const cells: Array<[number, number]> = [];
    let cur = goal;
    while (cur !== start) {
      const [cx, cy] = cur.split(',').map(Number);
      cells.push([cx, cy]);
      cur = cameFrom.get(cur)!;
    }
    cells.reverse();

    // Kollineare Zwischenpunkte entfernen (weniger Wegpunkte = weichere Wege)
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

  /** Zellkoordinaten eines Weltpunkts. */
  static cellOf(p: THREE.Vector3): { x: number; y: number } {
    return { x: Math.round(p.x / CELL), y: Math.round(p.z / CELL) };
  }
}
