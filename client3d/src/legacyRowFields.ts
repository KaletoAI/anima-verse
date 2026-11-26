/** Row fields the server stopped sending in plan E3 Task 8 (a furniture
 *  approach is an order now, § A11b). The browser scene still reads them —
 *  always absent — until plan E3 Task 13 deletes client3d; they live here so
 *  the shared HUD types no longer carry them. */
import type {} from '@anima/hud/types';

/** Visibility-filtered remaining motion, never another character's full journey. */
export interface MapLocalApproach {
  floor_y?: number | null;
  journey_id: string;
  room_id: string;
  waypoints: [number, number][];
  progress_m: number;
  walked_m: number;
  remaining_m: number;
  paces_m_s_real: (number | null)[] | null;
  starts_in_s: number | null;
}

/** Public physical entry only; no execution, consent, or target identity. */
export interface MapPropActionEntry {
  kind: string;
  pose_key: string;
  access: { x: number; y: number; z: number; yaw: number };
  anchor: { x: number; y: number; z: number; yaw: number };
  /** Authoritative body-root offset in metres; anchor.y already subtracts it. */
  root_offset: number;
  /** The entry clip's REAL length, and the real seconds already played as of
   *  this poll — entries run on the server's motion clock (real time,
   *  independent of the game-speed factor, § A11). */
  duration_s: number;
  elapsed_s: number;
  /** Entry seconds per real second: 1 while it plays, 0 frozen/paused. */
  clock_rate: number;
  height_cm: number;
  role: string | null;
  /** Motion-clock second the entry began — identity only, never timing. */
  started_s: number;
}

declare module '@anima/hud/types' {
  interface MapCharacter {
    local_approach?: MapLocalApproach | null;
    prop_action_entry?: MapPropActionEntry | null;
  }
}
