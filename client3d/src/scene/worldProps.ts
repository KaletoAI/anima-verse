/**
 * worldProps — die EINZELN gesetzten Props der Weltebene (§ A9a).
 *
 * Ein Findling an der Wegkreuzung, ein Wegweiser auf dem Grat, eine Bank in
 * der Wildnis. Die gemalte Fläche nebenan (§ A9, `meta.scatter`) sagt, wie
 * DICHT ein Boden etwas wachsen lässt — eine Statistik; nur diese Liste kann
 * „DIESER Stein, HIER, so gedreht" sagen.
 *
 * Der Unterschied zur Streu, und der ganze Grund für ein eigenes Modul:
 *
 *  - **Einzelne Objekte statt `InstancedMesh`.** Es sind höchstens 500 je Welt
 *    (Server-Grenze), jedes mit eigenem Yaw, eigenem Lift und womöglich eigener
 *    Variante — eine Instanz-Matrix bringt hier nichts, sie kostet nur einen
 *    zweiten Weg durch dieselbe Geometrie. (Instancing ab einer Schwelle ist
 *    ausdrücklich vertagt.)
 *  - **`place()` statt `groundedGeometry`.** Ein Welt-Prop läuft durch dieselbe
 *    Vertrags-Routine wie ein Szenen-Prop (§ B2): Orientierungs-Fix, messen,
 *    UNIFORM auf `max_m` skalieren, Yaw als Eltern-Drehung, Unterkante auf
 *    `bottom_y`. Damit ist eine Bank draußen so groß wie dieselbe Bank drinnen.
 *
 * Der BODEN kommt von hier, nicht vom Server: `bottom_y = heightAt(x, z) +
 * offset_y + ground_offset_m` mit demselben Sampler, auf dem die Streu steht
 * (§ A9a; `worldPropBottom`). Bewegt sich das Relief, wird nur die Höhe
 * nachgezogen — kein Neuaufbau.
 *
 * Reine Deko: kein Nav, keine Kollision, kein Fog (der Block kommt ungefiltert).
 */
import * as THREE from 'three';
import { pickModelVariant, placeModelSpec } from '@anima/scene-render';
import type { SceneModelSpec } from '@anima/scene-render';
import { loadGlb } from './propAssets';
import { instanceTier, SCATTER_LOD_DEFAULTS } from './scatterLod';
import type { InstanceTier, ScatterLodCfg } from './scatterLod';
import { SubmergedGhost } from './submergedGhost';
import { ghostCutY, ghostWaterLevel } from '../game/walk';
import type { WorldWater } from './tiles';
import { waterInside } from './waterShade';
import type { WorldPropSpec } from '../types';

/**
 * Wie viel weiter ein HANDGESETZTES Prop seine Stufen behält als ein
 * gestreutes.
 *
 * Die Streu-Bänder (35 m / 45 m / 120 m) sind für Büschel und Bäume gemacht,
 * von denen tausende im Bild stehen: dort ist früh Schluss, weil die Menge
 * kostet. Ein Welt-Prop ist eine LANDMARKE, es gibt höchstens 500 davon, und
 * eine Landmarke, die auf 120 m verschwindet, ist keine. Ein Faktor auf die
 * gespeicherten Distanzen statt eigener Zahlen, damit die
 * Sichtweiten-Einstellung des Spielers weiter durchschlägt.
 */
export const WORLD_PROP_LOD_SCALE = 3;

/**
 * Die Unterkante EINER Zeile über der bereits gesampelten Bodenhöhe (§ A9a).
 *
 * Drei Summanden, und jeder gehört jemand anderem: der Boden dem Relief, die
 * `offset_y` DIESER Platzierung und `ground_offset_m` dem PROP — ein Stamm
 * ohne Wurzelteller steckt überall gleich tief in der Erde, im Raum wie hier
 * draußen. Der Server schickt den Schlüssel nur, wenn er nicht 0 ist.
 *
 * Eigene Funktion, weil sie an ZWEI Stellen gebraucht wird (beim Einhängen und
 * beim Nachziehen des Reliefs) und der Smoke sie gegen Handzahlen prüft —
 * zwei Abschriften derselben Summe wären genau die Stelle, an der eine von
 * beiden den dritten Summanden verpasst.
 */
export function worldPropBottom(wp: WorldPropSpec, groundY: number): number {
  const off = Number(wp.offset_y);
  const sink = Number(wp.ground_offset_m);
  return groundY + (Number.isFinite(off) ? off : 0)
    + (Number.isFinite(sink) ? sink : 0);
}

/** Die Streu-Distanzen, auf Landmarken-Maß gebracht. Exportiert, weil der
 *  Smoke sie gegen handgerechnete Zahlen prüft (§ B5a). */
export const worldPropLodCfg = (base: ScatterLodCfg): ScatterLodCfg => ({
  nearM: base.nearM * WORLD_PROP_LOD_SCALE,
  farM: base.farM * WORLD_PROP_LOD_SCALE,
  cullM: base.cullM * WORLD_PROP_LOD_SCALE,
});

interface PropRecord {
  spec: WorldPropSpec;
  /** Das eingehängte Objekt (null, solange nichts geladen ist). */
  node: THREE.Group | null;
  /** Unterkante, mit der `node` platziert wurde — Basis der Relief-Nachführung. */
  placedBottom: number;
  /** URL, die `node` zeigt, und die zuletzt GEWÜNSCHTE (siehe `mount`). */
  shownUrl: string;
  wantedUrl: string;
  tier: InstanceTier;
  /** Der Unterwasser-Geist dieses Props (`scene/submergedGhost.ts`), oder null
   *  solange nichts steht. Er gehört dem NODE: ein Tier-Wechsel wirft das Mesh
   *  weg und damit den Geist, der nächste Mount baut ihn neu. */
  ghost: SubmergedGhost | null;
}

export interface WorldPropsLayer {
  /** Die Gruppe, die in die Szene gehängt wird (Welt-Koordinaten). */
  group: THREE.Group;
  /**
   * Den Block des Weltkarten-Payloads übernehmen. `sig` ist
   * `world_props_sig`; ist sie unverändert, kostet der Aufruf einen
   * String-Vergleich und nichts weiter.
   */
  sync(specs: readonly WorldPropSpec[] | undefined, sig: string): void;
  /** LOD-Takt: welche Stufe jedes Prop bei dieser Kamera zeigt. */
  tick(camera: THREE.Vector3): void;
  /** Das Relief hat sich bewegt — Höhen nachziehen, sonst nichts. */
  redrape(): void;
  /** Die Sichtweiten-Einstellung des Spielers (dieselbe wie für die Streu). */
  setLod(cfg: ScatterLodCfg): void;
  dispose(): void;
}

/** Die Platzierungs-Spec EINES Welt-Props (§ B2). `measure` ist hier fest
 *  `xyz`: das Payload sagt es mit, aber ein Prop wird an seiner größten Kante
 *  gemessen, und ein abweichender String wäre eine zweite Skalierungsregel. */
export function worldPropSceneSpec(wp: WorldPropSpec,
                                  bottomY: number): SceneModelSpec {
  return {
    role: 'prop',
    id: wp.prop_id,
    level: 0,
    variants: wp.variants || {},
    ...(wp.model_variants ? { model_variants: wp.model_variants } : {}),
    ...(typeof wp.variant === 'number' ? { variant: wp.variant } : {}),
    fix_euler: wp.fix_euler || { x: 0, y: 0, z: 0 },
    yaw_deg: wp.yaw_deg || 0,
    max_m: wp.max_m || 1,
    measure: 'xyz',
    anchor: [wp.x, wp.z],
    bottom_y: bottomY,
  };
}

/** Alles, was eine Zeile ZEIGT — ändert sich davon nichts, bleibt das Objekt
 *  stehen. Die Position gehört NICHT dazu: sie ist eine Verschiebung, kein
 *  Neuaufbau (siehe `redrape`). */
function shapeKey(wp: WorldPropSpec): string {
  return [wp.prop_id, wp.max_m, wp.yaw_deg,
    wp.fix_euler?.x, wp.fix_euler?.y, wp.fix_euler?.z,
    wp.variant ?? '', JSON.stringify(wp.variants || {})].join('|');
}

/**
 * @param heightAt the world ground under a point, in metres
 * @param waterAt  the DRAWN water over that point — level AND the signed
 *                 distance to the authored outline (`ground.waterGhostAt`), the
 *                 raster twin of `heightAt`. It decides nothing but the
 *                 underwater ghost: a prop whose base stands under the local
 *                 water level, INSIDE that outline, is redrawn tinted below the
 *                 waterline, so a sunken crate or a jetty post is visible
 *                 through the opaque surface. The outline half is not optional:
 *                 the level is dilated 4 m past it, so a level-only gate ghosts
 *                 props on the dry bank. A layer built without the sampler
 *                 simply has no ghosts.
 */
export function createWorldProps(
  heightAt: (x: number, z: number) => number,
  waterAt?: (x: number, z: number) => WorldWater,
): WorldPropsLayer {
  const group = new THREE.Group();
  group.name = 'world-props';
  const records = new Map<string, PropRecord>();
  let cfg = worldPropLodCfg(SCATTER_LOD_DEFAULTS);
  let loadedSig = '';
  let disposed = false;

  /** The water over ONE prop's base, or null where it stands dry — the one
   *  gate of the underwater ghost (`walk.ghostCutY`, `scene/submergedGhost`).
   *  It asks the SAME pair the terrain shades by: the level, and
   *  `waterInside(sd)` (`walk.ghostWaterLevel`), because the level is dilated
   *  4 m past the authored outline and reading it as a mask ghosts a prop that
   *  stands on the bank. It is asked at PLACEMENT time and on every beat that
   *  re-seats a placement, never per frame: a world prop does not move, and what
   *  moves under it (the height field and the water raster) arrives exactly on
   *  those beats. */
  function ghostLevelOf(rec: PropRecord, bottom: number): number | null {
    if (!waterAt) return null;
    const ww = waterAt(rec.spec.x, rec.spec.z);
    return ghostCutY(bottom, ghostWaterLevel(ww.level, waterInside(ww.sd)));
  }

  function drop(rec: PropRecord): void {
    if (!rec.node) return;
    group.remove(rec.node);
    // The ghost first: its materials are its own, and its registration is what
    // isolation toggle 22 walks. Its GEOMETRY is the node's and is disposed
    // with the node below.
    rec.ghost?.dispose();
    rec.ghost = null;
    // Die Quelle kommt aus dem GLB-Cache und wird von `placeModelSpec`
    // geklont — hier hängt also eine eigene Kopie, deren Geometrien und
    // Materialien niemand sonst benutzt.
    rec.node.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      m.geometry?.dispose();
      const mat = m.material;
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
      else mat?.dispose();
    });
    rec.node = null;
    rec.shownUrl = '';
  }

  /** Eine Stufe anfordern. „Der letzte WUNSCH gewinnt, nie die letzte
   *  ANTWORT": zwei schnelle Distanzwechsel dürfen nicht dazu führen, dass das
   *  spät eintreffende erste Mesh das späte zweite überschreibt. */
  function mount(rec: PropRecord, url: string): void {
    if (!url || rec.wantedUrl === url) return;
    rec.wantedUrl = url;
    const near = new THREE.Vector3(rec.spec.x, 0, rec.spec.z);
    void loadGlb(url, near).then((obj) => {
      if (disposed || !obj) return;
      // Steht die Zeile noch, und ist DIESE URL noch die gewünschte?
      if (records.get(rec.spec.id) !== rec || rec.wantedUrl !== url) return;
      const bottom = worldPropBottom(rec.spec, heightAt(rec.spec.x, rec.spec.z));
      // `clone: true`, weil `loadGlb` seine Szene über den URL-Cache teilt;
      // `clip: false`, weil ein Welt-Prop in keiner Raumhülle steht.
      const node = placeModelSpec(THREE, obj, worldPropSceneSpec(rec.spec, bottom),
        { clone: true, clip: false });
      drop(rec);
      // Wo die Routine das Objekt hingesetzt hat — Bezugspunkt jeder späteren
      // Verschiebung (`redrapeOne` addiert Differenzen, statt neu zu messen).
      node.userData.anchorX = rec.spec.x;
      node.userData.anchorZ = rec.spec.z;
      rec.node = node;
      rec.placedBottom = bottom;
      rec.shownUrl = url;
      // …and here is where a SUNKEN prop gets its second draw. Right after the
      // seat, on the very bottom that was just computed: a crate on a lake bed
      // is invisible without it, because the water surface IS the opaque
      // terrain since K-A. Dry ground builds nothing at all.
      rec.ghost = new SubmergedGhost(node);
      rec.ghost.set(ghostLevelOf(rec, bottom));
      node.visible = rec.tier !== 2;
      group.add(node);
    });
  }

  function sync(specs: readonly WorldPropSpec[] | undefined, sig: string): void {
    if (disposed) return;
    const list = Array.isArray(specs) ? specs : [];
    // Die Signatur deckt den FERTIGEN Block ab (§ A9a) — bewegt sie sich
    // nicht, hat sich weder eine Platzierung noch ein Mesh geändert.
    if (sig && sig === loadedSig && records.size === list.length) return;
    loadedSig = sig;
    const seen = new Set<string>();
    for (const wp of list) {
      if (!wp || typeof wp.id !== 'string') continue;
      if (!Number.isFinite(wp.x) || !Number.isFinite(wp.z)) continue;
      seen.add(wp.id);
      const cur = records.get(wp.id);
      if (!cur) {
        records.set(wp.id, {
          spec: wp, node: null, placedBottom: 0, shownUrl: '', wantedUrl: '',
          ghost: null,
          // Als „low" hereinkommen und vom LOD-Takt einsortieren lassen: der
          // Takt weiß, wo die Kamera steht, dieser Poll nicht.
          tier: 1,
        });
        continue;
      }
      const reshape = shapeKey(cur.spec) !== shapeKey(wp);
      cur.spec = wp;
      if (reshape) {
        // Ein anderes Prop, eine andere Größe, ein anderer Yaw: neu bauen.
        drop(cur);
        cur.wantedUrl = '';
      } else {
        // Nur verschoben — das ist eine Translation, kein Neuaufbau.
        redrapeOne(cur);
      }
    }
    for (const [id, rec] of Array.from(records)) {
      if (seen.has(id)) continue;
      drop(rec);
      records.delete(id);
    }
  }

  function redrapeOne(rec: PropRecord): void {
    if (!rec.node) return;
    const bottom = worldPropBottom(rec.spec, heightAt(rec.spec.x, rec.spec.z));
    // `placeModelSpec` hat die Unterkante auf `placedBottom` gesetzt und dabei
    // die eigene Bounding-Box eingerechnet; die DIFFERENZ trägt das mit, ohne
    // erneut messen zu müssen.
    rec.node.position.x += rec.spec.x - rec.node.userData.anchorX;
    rec.node.position.z += rec.spec.z - rec.node.userData.anchorZ;
    rec.node.position.y += bottom - rec.placedBottom;
    rec.node.userData.anchorX = rec.spec.x;
    rec.node.userData.anchorZ = rec.spec.z;
    rec.placedBottom = bottom;
    // The prop moved (a new relief, a moved row), so the water over its base is
    // a new question — this is the second of the two beats the ghost is gated
    // on. A prop lifted out of a lake loses its ghost here; one the rising
    // relief pushed under keeps the same meshes and only the cut moves.
    rec.ghost?.set(ghostLevelOf(rec, bottom));
  }

  function redrape(): void {
    for (const rec of records.values()) redrapeOne(rec);
  }

  function tick(camera: THREE.Vector3): void {
    if (disposed) return;
    for (const rec of records.values()) {
      const dx = rec.spec.x - camera.x;
      const dz = rec.spec.z - camera.z;
      const d = Math.hypot(dx, dz);
      const tier = instanceTier(d, rec.tier, cfg);
      rec.tier = tier;
      if (tier === 2) {
        if (rec.node) rec.node.visible = false;
        continue;
      }
      if (rec.node) rec.node.visible = true;
      // EINE Routine für die Auflösung, geteilt mit jedem anderen Verbraucher
      // (§ B2-Nachtrag): erst die Variante über `variant`, dann die Stufe
      // daraus. Kein Renderer würfelt hier und keiner rechnet den Index nach.
      mount(rec, pickModelVariant(rec.spec, tier === 0 ? 'full' : 'low'));
    }
  }

  return {
    group,
    sync,
    tick,
    redrape,
    setLod(next: ScatterLodCfg) { cfg = worldPropLodCfg(next); },
    dispose() {
      disposed = true;
      for (const rec of records.values()) drop(rec);
      records.clear();
      group.parent?.remove(group);
    },
  };
}
