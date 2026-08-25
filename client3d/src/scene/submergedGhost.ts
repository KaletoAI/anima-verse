import * as THREE from 'three';
import { waterTintRgb } from './waterShade';

/**
 * THE UNDERWATER GHOST — the second draw that gives anything standing in water
 * a body below the waterline (finding H3, 2026-08-25; extended from figures to
 * placed OBJECTS by the user decision of the same day).
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * Since Wasser v2 K-A the water surface IS the terrain, and the terrain is
 * OPAQUE. Everything whose base stands under a water level is therefore cut
 * clean off at the waterline: below it the depth test against the ground is
 * lost and nothing is ever drawn. A figure in a river does not read as "wading",
 * it reads as buried — and a crate on the lake bed, a jetty post, a fish prop
 * simply is not there at all.
 *
 * ── THE FIX, AND WHY IT IS A SECOND DRAW AND NOT TRANSPARENCY ───────────────
 * Making the water itself transparent would mean sorting it against every
 * figure, every prop and every other water pixel in the world — a second,
 * blended pass over the whole terrain, which is exactly what K-A deleted. The
 * cheap and local answer is to draw the OBJECT twice: once normally, and once
 * more with `depthFunc: GreaterDepth`, which draws ONLY where the normal pass
 * LOST the depth test — i.e. only the part hidden behind something, which for a
 * thing standing in water is the submerged part. The ghost writes no depth,
 * carries the water's own tint at {@link WATER_GHOST_OPACITY}, and being
 * `transparent` it renders after every opaque object, the terrain included.
 *
 * ── WHY THE GHOST CUTS ITSELF OFF AT THE WATERLINE ──────────────────────────
 * `GreaterDepth` alone says "draw where the normal pass lost the depth test",
 * and an object loses that test against more than the water: it loses it
 * against ITSELF. At a pixel where an arm stands in front of the torso — or a
 * crate's near face in front of its far one — the depth buffer holds the near
 * surface, so the far one is GREATER and the ghost paints a blue patch onto the
 * dry half, which is precisely the half that must look normal.
 *
 * So the fragment discards everything above `uGhostCutY`, the WORLD Y of the
 * water surface handed in by {@link SubmergedGhost.set}. Below that line the
 * object is hidden by the opaque water anyway, so a self-overlap there is ghost
 * over ghost and invisible; above it there is now no second draw at all. The
 * two conditions compose exactly right at the shore, where the drawn surface
 * ramps BELOW the nominal level (finding G1): a shin — or a crate corner —
 * standing in front of the ramp still fails GreaterDepth and keeps its ordinary
 * look.
 *
 * ── WHAT IT COSTS, AND WHO PAYS ─────────────────────────────────────────────
 * The ghost meshes SHARE the original geometry and — for a rigged figure — the
 * original `THREE.Skeleton`, so the animation drives both without a second
 * mixer, a second clone or a second bone texture; only the materials are new,
 * and every one of them compiles into ONE program
 * (`customProgramCacheKey`). They are built lazily on the first submersion and
 * hidden, never destroyed, afterwards: a figure wading in and out of a ford, or
 * a prop whose lake drains and fills, must not rebuild geometry. A dry object
 * costs one comparison per gate call and not a byte of GPU memory.
 *
 * ── WHERE THE GATE LIVES, AND WHY IT IS NOT IN HERE ─────────────────────────
 * This module owns the MESHES; WHEN a ghost is wanted is the caller's, through
 * the one pure decision `game/walk.ghostCutY(baseY, waterLevel)`:
 *  - FIGURES ask every frame (`scene/npcs.ts`, the bed and the mirror the walk
 *    loop reads anyway) — a figure moves, so its gate has to.
 *  - PLACED OBJECTS ask at PLACEMENT time and on every beat that re-lifts a
 *    placement (`scene/worldProps.ts` mount + redrape, `scene/sceneRecipe.ts`
 *    mount + `reliftScene` + tier swap). A prop does not move on its own; what
 *    moves under it is the height field and the water raster, and those arrive
 *    on exactly those beats.
 *  - INSTANCED SCATTER IS OUT OF SCOPE and deliberately so: the ghost is one
 *    second mesh per object, which is the wrong shape for a density field of
 *    thousands of tufts. A wood standing in a swamp needs a per-instance
 *    submerged flag in the scatter's own buffers, not this.
 *
 * ── THE ONE ARTEFACT, NAMED ─────────────────────────────────────────────────
 * "Behind something" is not "behind water": a gated object that stands behind a
 * building would show its ghost through the wall. The gate is what keeps that
 * rare — only something whose base really stands under a water level gets a
 * ghost at all — and such a thing is in the open by definition. Isolation
 * toggle 22 ("Water off") takes every ghost with it, for the same reason it
 * takes the lift and the shading: without a water surface there is nothing for
 * the ghost to be behind.
 */
export const WATER_GHOST_OPACITY = 0.4;

/** Toggle 22's reach into every ghost there is (`debug3d.ts`). Module state and
 *  not a per-object flag: the switch is world-wide, and something created while
 *  it is on must come up ghost-less too. */
let ghostOff = false;

/** Every ghost that currently exists, so toggle 22 reaches the ones that are
 *  already standing. A figure re-gates itself every frame and would correct
 *  itself anyway; a PLACED object is gated once when it is mounted and would
 *  keep a ghost the switch has just turned off. Entries leave on `dispose`,
 *  which is why both owners of a ghost call it (`Figure.dispose`,
 *  `worldProps.drop`, `sceneRecipe.unmountScene` / the tier swap). */
const live = new Set<SubmergedGhost>();

/** Isolation toggle 22 — hide every underwater ghost in the world at once. */
export function setWaterGhostOff(off: boolean): void {
  if (off === ghostOff) return;
  ghostOff = off;
  for (const g of live) g.reapply();
}

/** What toggle 22 stands at. Exported for the smokes, which have to be able to
 *  put the switch back after they have flipped it. */
export function waterGhostOff(): boolean {
  return ghostOff;
}

let anchorWarned = false;
function warnGhostAnchor(): void {
  if (anchorWarned) return;
  anchorWarned = true;
  console.warn('[submergedGhost] the underwater ghost found no shader anchor —'
    + ' the waterline cut is not compiled in (three chunk renamed?)');
}

/**
 * ONE object's underwater ghost: build it lazily, show it while the caller says
 * there is water over the base, cut it at the waterline.
 *
 * The root may be a whole `THREE.Group` (a figure, a placed prop with several
 * parts) — every mesh under it gets its twin, hung as a CHILD of the mesh it
 * doubles with no transform of its own, so the world matrix is the original's
 * bit for bit and a hidden or moved original takes its ghost along for free.
 */
export class SubmergedGhost {
  private readonly root: THREE.Object3D;
  private readonly meshes: THREE.Mesh[] = [];
  private built = false;
  private shown = false;
  /** The waterline the CALLER last asked for; `null` = dry. Kept apart from
   *  `shown`, because toggle 22 may hide a ghost the caller still wants. */
  private level: number | null = null;
  /** The world Y every ghost material of this object cuts itself off at — ONE
   *  uniform object shared by all of them, so a gate writes the waterline once
   *  instead of once per mesh. */
  private readonly cut = { value: 0 };

  constructor(root: THREE.Object3D) {
    this.root = root;
    live.add(this);
  }

  /**
   * WHERE THE WATER STANDS OVER THIS OBJECT — the one call that switches the
   * ghost on and off. `null` means dry; a number is the WORLD Y of the water
   * surface over the object's own base.
   *
   * The DECISION is the caller's (`walk.ghostCutY`); this only owns the meshes.
   * The level itself is needed and not merely a boolean — see the module
   * docstring for what the ghost cuts itself off at.
   *
   * Cheap on the dry path on purpose: something that has never been in water
   * builds nothing at all.
   */
  set(waterLevel: number | null): void {
    this.level = waterLevel !== null && Number.isFinite(waterLevel)
      ? waterLevel : null;
    this.reapply();
  }

  /** Re-decide visibility from the level the caller asked for and the state of
   *  toggle 22. Called by `set` and by the toggle itself. */
  reapply(): void {
    const want = this.level !== null && !ghostOff;
    // The waterline first, and OUTSIDE the early-out below: a ghost that is
    // already standing still has to follow a rising lake.
    if (want) this.cut.value = this.level as number;
    if (want === this.shown) return;
    this.shown = want;
    if (want && !this.built) this.build();
    for (const g of this.meshes) g.visible = want;
  }

  /** How many second draws stand — 0 while the object has never been in water.
   *  The red probe of `client3d/scripts/smoke_world_props.mjs` reads it: a dry
   *  prop must build nothing. */
  get count(): number {
    return this.meshes.length;
  }

  /** The world Y the ghosts cut themselves off at (diagnostic / smoke). */
  get cutY(): number {
    return this.cut.value;
  }

  /** Whether the second draw is on right now (diagnostic / smoke). */
  get visible(): boolean {
    return this.shown;
  }

  /** The ghost meshes themselves — for the smokes, which have to read the
   *  material state the whole trick consists of. */
  get parts(): readonly THREE.Mesh[] {
    return this.meshes;
  }

  /**
   * Give the ghost up: unhook it from the scene graph and drop its materials.
   * NOT the geometry — that belongs to the original and is still drawn.
   *
   * Called wherever the object itself goes (a removed NPC, a dropped world
   * prop, an unmounted scene, a tier swap): without it the entry in `live`
   * would keep the whole object alive for the toggle's sake.
   */
  dispose(): void {
    live.delete(this);
    for (const g of this.meshes) {
      g.parent?.remove(g);
      const mat = g.material;
      if (Array.isArray(mat)) for (const m of mat) m.dispose();
      else mat?.dispose();
    }
    this.meshes.length = 0;
    this.built = false;
    this.shown = false;
  }

  /** One ghost per mesh under the root, sharing its geometry and (rigged) its
   *  skeleton. Runs at most once per object, the first time it is in water. */
  private build(): void {
    this.built = true;
    const source: THREE.Mesh[] = [];
    this.root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) source.push(m);
    });
    for (const src of source) {
      const ghost = this.twin(src);
      ghost.castShadow = false;
      ghost.receiveShadow = false;
      // Whatever the original was culled by, the ghost is: they share one
      // geometry and one world matrix, so a different answer would be a second
      // draw appearing where the first one does not (a skinned figure carries
      // `frustumCulled = false` because its bounds do not follow the pose).
      ghost.frustumCulled = src.frustumCulled;
      // After the terrain by virtue of being transparent, and after the
      // object's own draw by virtue of this — the ghost is a correction on top
      // of the normal pass, never a thing that stands on its own.
      ghost.renderOrder = 2;
      ghost.visible = false;
      // A CHILD of the mesh it doubles, with no transform of its own: the world
      // matrix is then the original's, bit for bit, which is what the shared
      // bind matrix assumes.
      src.add(ghost);
      this.meshes.push(ghost);
    }
  }

  /** The doubled mesh of ONE source mesh, with the ghost materials on it.
   *  A SkinnedMesh is doubled as one — same skeleton object, so the mixer that
   *  poses the original poses this one in the same breath. */
  private twin(src: THREE.Mesh): THREE.Mesh {
    // PER SOURCE MATERIAL, not just the first: a GLB prop is routinely one
    // geometry with several material groups, and a single ghost material would
    // paint the wrong texture over all but one of them.
    const mats = Array.isArray(src.material) ? src.material : [src.material];
    const ghostMats = mats.map((m) => this.material(m as THREE.Material));
    const material: THREE.Material | THREE.Material[] =
      Array.isArray(src.material) ? ghostMats : ghostMats[0];
    const skin = src as THREE.SkinnedMesh;
    if (skin.isSkinnedMesh) {
      const s = new THREE.SkinnedMesh(skin.geometry, material);
      s.bindMode = skin.bindMode;
      // The SAME skeleton object: no second bone texture is uploaded.
      s.bind(skin.skeleton, skin.bindMatrix);
      return s;
    }
    return new THREE.Mesh(src.geometry, material);
  }

  /** ONE ghost material from one source material. */
  private material(src: THREE.Material | undefined): THREE.MeshBasicMaterial {
    const tint = waterTintRgb(undefined);
    const std = src as THREE.MeshStandardMaterial | undefined;
    const cut = this.cut;
    const mat = new THREE.MeshBasicMaterial({
      // The object's own texture, MULTIPLIED by the water tint — a silhouette
      // alone reads as a shadow, the tinted texture reads as a body seen
      // through water. setRGB and not setHex: these are the very numbers the
      // water shader writes into `look0.rgb`, i.e. already working-space.
      map: std?.map ?? null,
      color: new THREE.Color().setRGB(tint[0], tint[1], tint[2]),
      transparent: true,
      opacity: WATER_GHOST_OPACITY,
      // DRAW ONLY WHERE THE NORMAL PASS LOST — the whole trick. And write no
      // depth, so the ghost can never occlude anything itself.
      depthFunc: THREE.GreaterDepth,
      depthWrite: false,
      side: std?.side ?? THREE.FrontSide,
      // A cutout leaf is a cutout leaf under water too: without this the ghost
      // of a foliage prop is a stack of opaque tinted quads.
      alphaTest: std?.alphaTest ?? 0,
    });
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uGhostCutY = cut;
      // A three upgrade that renames either chunk would leave the cut out and
      // the ghost would bleed over the dry half — say so rather than shipping
      // the artefact silently.
      if (!shader.vertexShader.includes('#include <fog_vertex>')
          || !shader.fragmentShader.includes('#include <clipping_planes_fragment>')) {
        warnGhostAnchor();
      }
      // The world Y of the (skinned) vertex: `transformed` carries the pose by
      // the time <fog_vertex> runs (skinning writes it), and modelMatrix takes
      // it to world space — the very two lines three's own <worldpos_vertex>
      // uses, spelled here because that chunk is compiled out unless an envmap
      // or a shadow asks for it.
      shader.vertexShader = `varying float vGhostY;\n${shader.vertexShader}`
        .replace('#include <fog_vertex>',
          '#include <fog_vertex>\n\tvGhostY = ( modelMatrix * vec4( transformed, 1.0 ) ).y;');
      shader.fragmentShader = `varying float vGhostY;\nuniform float uGhostCutY;\n${shader.fragmentShader}`
        .replace('#include <clipping_planes_fragment>',
          '#include <clipping_planes_fragment>\n\tif ( vGhostY > uGhostCutY ) discard;');
    };
    // One program for every ghost in the world, however many things wade.
    mat.customProgramCacheKey = () => 'av-water-ghost';
    return mat;
  }
}
