// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing './icons'; the implementation lives in
// @anima/player-ui.
export { Icon, type IconName } from '@anima/player-ui'
