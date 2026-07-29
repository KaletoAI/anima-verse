// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing '../i18n/I18nProvider'; the implementation lives in
// @anima/player-ui so client3d's HUD can use the identical provider.
export { I18nProvider, useI18n } from '@anima/player-ui'
