import type { Object3D } from 'three'

/** Shared by existing and subsequently streamed water effects. */
export const waterExtrasUniform = { value: 1 }

export function setWaterExtrasEnabled(on: boolean): void {
  waterExtrasUniform.value = on ? 1 : 0
}

/** Compose the graphics switch with the owner's tier/storey visibility. No
 * registry or frame sweep: ordinary visibility writes retain their own state,
 * and three's traversal skips the effect before rendering it. */
export function gateWaterExtra<T extends Object3D>(object: T): T {
  let wanted = object.visible
  Object.defineProperty(object, 'visible', {
    configurable: true, enumerable: true,
    get: () => wanted && waterExtrasUniform.value > 0,
    set: (on: boolean) => { wanted = on },
  })
  return object
}
