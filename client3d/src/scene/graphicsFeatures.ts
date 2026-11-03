import type * as THREE from 'three';
import { setMirrorsEnabled, setWaterExtrasEnabled } from '@anima/scene-render';
import type { GraphicsPrefs } from '../game/prefs';
import type { LightPool } from './lightPool';
import { setFogVeilGraphicsOff } from './fogVeil';
import { setWaterGhostGraphicsOff } from './submergedGhost';

/** The menu and startup share the same runtime path. All gates also cover
 * subsequently mounted objects; movement and water queries remain unchanged. */
export class GraphicsFeatures {
  private fog: THREE.Scene['fog'];
  constructor(private scene: THREE.Scene, private lights: LightPool,
    private backdrop: THREE.Object3D) {
    this.fog = scene.fog;
  }

  apply(prefs: GraphicsPrefs): void {
    setWaterExtrasEnabled(prefs.waterMirrors);
    setMirrorsEnabled(prefs.waterMirrors);
    setWaterGhostGraphicsOff(!prefs.waterMirrors);
    this.lights.setEnabled(prefs.lampLights);
    if (prefs.fogHorizon && !this.scene.fog) {
      this.scene.fog = this.fog;
      if (this.fog && this.scene.background && 'isColor' in this.scene.background) {
        this.fog.color.copy(this.scene.background as THREE.Color);
      }
    } else if (!prefs.fogHorizon && this.scene.fog) {
      this.fog = this.scene.fog;
      this.scene.fog = null;
    }
    this.backdrop.visible = prefs.fogHorizon;
    // The server already filters unknown places/figures. This veil is cosmetic.
    setFogVeilGraphicsOff(!prefs.fogHorizon);
  }
}
