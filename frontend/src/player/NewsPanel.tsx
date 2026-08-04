// Thin path alias after the move to the shared package (plan-3d-game stage 6).
// Frontend modules keep importing './NewsPanel'; the implementation lives in
// @anima/player-ui so the 3D client's HUD shows the identical panel.
export { NewsPanel } from '@anima/player-ui'
