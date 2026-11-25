/**
 * The words and numbers of a body shape view's Regenerate (round 2026-11-25, ShapeViewRegenerate): the view names,
 * the image jobs where no payload names them and the confirmation's cost sentence.
 */

export const SHAPE_VIEW_LABELS: Record<string, string> = {
  front: 'Front', back: 'Back', left: 'Left side', right: 'Right side',
}

/** Image jobs of one view's Regenerate where no payload names them (the Dressed views): the server's
 *  `base_body.shape_view_jobs_of` — the front is one edit, a back or side view the turn plus the draft (Ruling A175). */
export const SHAPE_VIEW_JOBS: Record<string, number> = { front: 1, back: 2, left: 2, right: 2 }

/** The confirmation's sentence: what the Regenerate spends. */
export function shapeViewCost(jobs: number, t: (s: string) => string): string {
  return (jobs === 1 ? t('Costs 1 image job.') : t('Costs {n} image jobs.').replace('{n}', String(jobs))) + ' '
    + t('The body shape changes with it, so the next Build meshes it anew (hub jobs for the mesh, the face and the rig).')
}
