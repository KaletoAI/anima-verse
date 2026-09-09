// Thin path alias: the implementation lives in @anima/player-ui so the player
// panels and client3d's HUD format times of day exactly like the admin does.
export {
  DEFAULT_CLOCK, asTimeFormat, formatDate, formatDateTime, formatGameTime,
  formatTime, sameZoneDay, clockSettings, loadClockSettings, applyClockSettings,
  useClockSettings,
} from '@anima/player-ui'
export type { ClockSettings, TimeFormat } from '@anima/player-ui'
