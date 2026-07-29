// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing './usePolling'; the implementation lives in
// @anima/player-ui so client3d's HUD can use the identical poll hook.
export { usePoll, type UsePollOptions, type UsePollResult } from '@anima/player-ui'
