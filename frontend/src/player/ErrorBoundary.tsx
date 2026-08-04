// Thin path alias after the move to the shared package (plan-3d-game stage 6).
// Frontend modules keep importing './ErrorBoundary'; the implementation lives
// in @anima/player-ui so the 3D HUD can wrap its panels in the same boundary.
export { ErrorBoundary } from '@anima/player-ui'
