/**
 * THE TWO-PHASE FIGURE FRAME, the planning half (cross-person collision spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` Part 1,
 * "Update order and lag"; plan ruling R8):
 *
 *  - phase A: every figure poses (`Figure.update` — mixer, placement, height,
 *    foot pose, bridge; no secondary motion);
 *  - between the phases `planPartnerFrame` decides, per READER, which other
 *    figures it reads this frame, and `NpcManager.tickSecondary` snapshots
 *    each selected partner ONCE, before any solve;
 *  - phase B: each reader's strand hair and secondary motion run against its
 *    partners' snapshots (`Figure.updateSecondary`), so the result does not
 *    depend on the order the figures are visited in.
 *
 * The plan is pure — the figures it is handed say where they stand and give
 * their spheres on demand. A pair is first tested on the ROOT distance:
 * |root_r − root_p| ≤ bindRadius_r + lever_r + bindRadius_p +
 * `PARTNER_PREFILTER_SLACK_M`. Only a pair that passes asks `body()` /
 * `reach()` (which bind a figure's capsules lazily and read them in the
 * current frame); the sphere test of `selectPartners` then decides. A figure
 * that is not a reader gets no entry; a reader without a candidate gets `[]`.
 */
import { PARTNER_MAX, PARTNER_PREFILTER_SLACK_M, selectPartners } from '@anima/scene-render';
import type { Sphere, Vec3 } from '@anima/scene-render';

/** One figure as the frame plan sees it (`Figure.frameFigure`). */
export interface FrameFigure {
  name: string;
  /** The figure root's world position (its feet). */
  root: Vec3;
  /** A sphere about `root` that holds the figure's bound body in its bind pose (metres). */
  bindRadius: number;
  /** Reads partners this frame: posed in phase A, not in the far tier, with a driven link or a hair push. */
  reader: boolean;
  /** The longest driven lever beyond the body (metres; 0 without one). */
  lever: number;
  /** The members of the figure's running pair interaction (they rank first). */
  members: readonly string[];
  /** The body sphere in the current frame (binds lazily); null when the capsules cannot be bound. */
  body(): Sphere | null;
  /** The reach sphere in the current frame; null when the capsules cannot be bound. */
  reach(): Sphere | null;
}

function distance(p: Vec3, q: Vec3): number {
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}

/**
 * The partners per reader for this frame (module docstring): reader name →
 * the selected partner names, members of its pair interaction first, then the
 * smallest gap, at most `max`. Each figure's `body()` and `reach()` are asked
 * at most once, and only for a pair that passed the root prefilter.
 */
export function planPartnerFrame(figures: readonly FrameFigure[], max = PARTNER_MAX): Map<string, string[]> {
  const plan = new Map<string, string[]>();
  const bodies = new Map<FrameFigure, Sphere | null>();
  const bodyOf = (f: FrameFigure): Sphere | null => {
    if (!bodies.has(f)) bodies.set(f, f.body());
    return bodies.get(f) ?? null;
  };
  for (const reader of figures) {
    if (!reader.reader) continue;
    const near = figures.filter(p => p !== reader && p.name !== reader.name
      && distance(reader.root, p.root) <= reader.bindRadius + reader.lever + p.bindRadius + PARTNER_PREFILTER_SLACK_M);
    const reach = near.length ? reader.reach() : null;
    if (!reach) { plan.set(reader.name, []); continue; }
    const candidates: { name: string; body: Sphere }[] = [];
    for (const p of near) {
      const body = bodyOf(p);
      if (body) candidates.push({ name: p.name, body });
    }
    plan.set(reader.name, candidates.length ? selectPartners(reach, new Set(reader.members), candidates, max) : []);
  }
  return plan;
}
