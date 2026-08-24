/**
 * The performance readout of the 3D client (Etappe 5,
 * `development_instructions/plan-3d-lod-und-betreten.md`).
 *
 * A normal display in the game picture, not a diagnostic tool: no URL
 * parameter, no developer mode — it is on or off in the game menu, and it
 * updates while you play. The `?debug3d=1` overlay (`src/debug3d.ts`) is
 * explicitly NOT the place for this (user 2026-08-04) and stays what it is: a
 * remote probe for a single tile.
 *
 * Presentational only. It subscribes to the perf store of `bus.ts` — its own
 * store with its own listeners, so these three-per-second updates re-render
 * this block and nothing else in the HUD. `main.ts` decides WHEN to measure
 * and `game/perfstats.ts` does the arithmetic; nothing is computed here.
 *
 * The tier line is the point of the whole display: it says whether the
 * resolution choice is doing anything. Without it one sees that a picture got
 * cheaper but not why.
 */
import { useSyncExternalStore } from 'react';
import { useI18n } from '@anima/player-ui';
import { getPerfStats, subscribePerfStats } from './bus';

/** Grouped digits in the viewer's locale ("1,234,567" / "1.234.567"). Exact
 *  numbers, never rounded to "1.2M": these are read to compare one view
 *  against another, and a rounded figure hides the very change that is being
 *  looked for. */
const num = (n: number) => Math.round(n).toLocaleString();

function Row({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? 'hud-perf-row wide' : 'hud-perf-row'}>
      <span className="hud-perf-label">{label}</span>
      <span className="hud-perf-value">{value}</span>
    </div>
  );
}

export function PerfOverlay() {
  const { t } = useI18n();
  const stats = useSyncExternalStore(subscribePerfStats, getPerfStats);
  // Nothing measured yet (the first tick is up to a second away) — show the
  // frame instead of popping in, so switching it on has an immediate answer.
  const dash = '—';
  return (
    <div className="hud-perf" aria-live="off">
      <Row label={t('FPS')} value={stats ? String(Math.round(stats.fps)) : dash} />
      <Row label={t('Draw calls')} value={stats ? num(stats.calls) : dash} />
      <Row label={t('Triangles')} value={stats ? num(stats.triangles) : dash} />
      <Row label={t('Vertices')} value={stats ? num(stats.vertices) : dash} />
      <Row label={t('Geometries / textures')}
        value={stats ? `${num(stats.geometries)} / ${num(stats.textures)}` : dash} wide />
      <Row label={t('Models full / low')}
        value={stats ? `${num(stats.tiers.full)} / ${num(stats.tiers.low)}` : dash} wide />
      {/* The scatter's two stages, side by side — the near prop MESHES against
          the far BILLBOARDS. One line each for what they submit, because the
          two are made cheaper in opposite ways: the meshes by drawing fewer or
          coarser trees (triangles), the billboards by drawing fewer or smaller
          quads (pixels). A single scatter figure cannot tell the two apart,
          and hiding the whole layer only says that it is expensive. */}
      <Row label={t('Scatter inst. mesh / imp.')}
        value={stats
          ? `${num(stats.scatter.mesh.instances)} / ${num(stats.scatter.impostor.instances)}`
          : dash} wide />
      <Row label={t('Scatter tri mesh / imp.')}
        value={stats
          ? `${num(stats.scatter.mesh.triangles)} / ${num(stats.scatter.impostor.triangles)}`
          : dash} wide />
      <Row label={t('Scatter calls / LOD pass')}
        value={stats
          ? `${num(stats.scatter.mesh.calls + stats.scatter.impostor.calls)}`
            + ` / ${stats.scatterLodMs.toFixed(1)} ms`
          : dash} wide />
    </div>
  );
}
