/**
 * Which figures may run their hair per strand this frame (strand-hair spec
 * § 6.2.2): the candidate list `pickStrandFigures` (`@anima/scene-render`)
 * admits from. Pure — no three, no DOM — so a node smoke checks it
 * (`scripts/smoke_client_strand_wiring.mjs`); `NpcManager.tickStrandHair`
 * feeds it the figures of the frame.
 *
 * A figure is a CANDIDATE when it is drawn at the full tier (the distance tier
 * carries no strand binding), its strand handle is ready (record loaded and
 * bound — `Figure.prepareStrandHair`) and it is not the camera's own body in
 * first person (the shrunk head hides the hair there). Everyone else keeps the
 * spring chains or today's skin.
 */
import type { StrandCandidate } from './hairSimMath';

/** What the budget needs to know of one figure. */
export interface StrandFigureView {
  name: string;
  /** World position of the figure (its root). */
  position: { x: number; y: number; z: number };
  tier: 'full' | 'low';
  /** A bound strand handle exists (record loaded, the mesh carries the binding). */
  hasRecord: boolean;
  /** The camera's own body in first person. */
  firstPerson: boolean;
  /** `StrandHair.costMs`: the measured (or estimated) sim + rebuild ms per frame. */
  costMs: number;
  /** Runs per strand now (the hysteresis of `pickStrandFigures`). */
  running: boolean;
}

/** The candidates among `figures` with their camera distance, in input order. */
export function strandCandidates(figures: Iterable<StrandFigureView>,
  cameraPos: { x: number; y: number; z: number }): StrandCandidate[] {
  const out: StrandCandidate[] = [];
  for (const f of figures) {
    if (f.tier !== 'full' || !f.hasRecord || f.firstPerson) continue;
    const distance = Math.hypot(f.position.x - cameraPos.x, f.position.y - cameraPos.y, f.position.z - cameraPos.z);
    out.push({ name: f.name, distance, costMs: f.costMs, running: f.running });
  }
  return out;
}
