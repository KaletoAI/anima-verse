// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing './EmptyState'; the implementation lives in
// @anima/player-ui.
export { EmptyState } from '@anima/player-ui'
