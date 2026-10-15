import type { EndpointSpec } from './pollCore';

/** Per-endpoint budgets shared by push signals and periodic polling. */
export const SYNC_ENDPOINTS = {
  scene: { intervalMs: 5000, pushedIntervalMs: 20000, minSpacingMs: 5000, topics: ['presence', 'scene'] },
  others: { intervalMs: 5000, pushedIntervalMs: 20000, minSpacingMs: 5000, topics: ['presence'] },
  notices: { intervalMs: 5000, pushedIntervalMs: 30000, minSpacingMs: 5000, topics: ['notices'] },
  badges: { intervalMs: 20000, pushedIntervalMs: 30000, minSpacingMs: 5000, topics: ['notices'] },
  self: { intervalMs: 5000, pushedIntervalMs: 30000, minSpacingMs: 5000, topics: ['self'] },
  belongings: { intervalMs: 5000, pushedIntervalMs: 30000, minSpacingMs: 5000, topics: ['self'] },
  mind: { intervalMs: 10000, pushedIntervalMs: 30000, minSpacingMs: 5000, topics: ['self'] },
  worldmapPlayer: { intervalMs: 10000, pushedIntervalMs: 20000, minSpacingMs: 3000, topics: ['presence', 'world'] },
  worldmap3d: { intervalMs: 3000, pushedIntervalMs: 6000, minSpacingMs: 3000, topics: ['presence', 'world'], runHidden: true },
} satisfies Record<string, EndpointSpec>;
