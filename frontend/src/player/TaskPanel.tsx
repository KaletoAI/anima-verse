// Thin path alias after the move to the shared package (plan-3d-game stage 6).
// Frontend modules keep importing './TaskPanel'; the implementation lives in
// @anima/player-ui so the 3D client's HUD shows the identical panel.
export { TaskPanel } from '@anima/player-ui'
