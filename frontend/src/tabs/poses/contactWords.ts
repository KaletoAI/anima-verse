import type { ContactTarget } from '@anima/scene-render'

/** The UI word of a contact target. */
export function targetWordOf(t: (s: string) => string, x: ContactTarget): string {
  switch (x) {
    case 'channel': return t('channel')
    case 'hand_left': return t('left hand')
    case 'hand_right': return t('right hand')
    case 'head_front': return t('head front point')
    default: return t('none')
  }
}

