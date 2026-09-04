// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Game-Admin modules import the shared lightbox from here; the ONE host is
// mounted in main.tsx (the opener is a module singleton, so a second provider
// would render the overlay twice).
export { LightboxProvider, useLightbox, openLightbox } from '@anima/player-ui'
export type { LightboxItem } from '@anima/player-ui'
