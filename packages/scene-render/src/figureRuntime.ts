/**
 * THE PER-FIGURE RUNTIME (Ruling A110, spec
 * `docs/superpowers/specs/2026-11-16-poses-tab-redesign-design.md` § 4): the
 * part of a figure's frame that the 3D client and the Game-Admin preview run
 * identically. Extracted from client3d's `Figure`, which now WRAPS it — the
 * game keeps its mixer, bridges, travel, lift, height, first person and LOD
 * around it; the admin preview drives a bare mixer around the same runtime.
 *
 * What it owns (per figure, created from the instance the owner shows):
 *  - the secondary motion (`createSecondaryMotion`), with the extension-tip
 *    collision (`setCollision`) and the motion payload re-configured by `rev`
 *    (hair chains dropped while the strands run, `withoutHairGroups`);
 *  - the GPU garment push (`createGarmentCollision`, per-figure material clones);
 *  - the per-strand hair (`createStrandHair` on the record `loadStrandRecord`
 *    hands in; `prepareStrandHair` / `setStrandHair`);
 *  - the partner binding: own capsules (`bindCollision`) and channels
 *    (`bindChannels`) as OTHER figures read them, bound lazily on the instance
 *    shown now (`frameFigure`, `partnerSnapshot`);
 *  - the channel openings around what occupies its channels
 *    (`bindChannelOpening`, `applyChannelOpenings`).
 *
 * THE TWO-PHASE FRAME (cross-person collision spec Part 1, `partnerFrame.ts`,
 * `frameLoop.ts`): the owner poses the figure (phase A — mixer, placement, foot
 * fixes) and then calls `poseStep`, which records what phase B needs and
 * configures the motion (it solves nothing). After EVERY figure posed,
 * `runFigureFrame` plans partners, snapshots them once and calls
 * `updateSecondary` (phase B: strands, then secondary motion) per figure.
 * Secondary motion never runs inside phase A.
 *
 * `three` is a parameter, never an import (package rule).
 */
import type { Object3D, Vector3 } from 'three'
import { createSecondaryMotion, withoutHairGroups } from './secondaryMotion'
import type { SecondaryMotion, SecondaryMotionPayload } from './secondaryMotion'
import { createGarmentCollision } from './garmentCollision'
import type { GarmentCollision } from './garmentCollision'
import { createStrandHair } from './hairSim'
import type { StrandHair } from './hairSim'
import { STRAND_LIMITS } from './hairSimMath'
import type { HairStrandRecord } from './hairSimMath'
import { bindCollision, COLLISION_VERSION } from './collision'
import type { CapsuleNow, CollisionBinding, CollisionPayload } from './collision'
import { bindChannels } from './channels'
import { bindChannelOpening } from './channelOpening'
import type { ChannelOpeningBinding, OpeningSegment } from './channelOpening'
import { bodySphere, consumerPartnerCapsules, reachSphere, snapshotPartner } from './partnerContact'
import type { PartnerSnapshot, Sphere } from './partnerContact'
import type { FrameFigure } from './partnerFrame'

type Three = typeof import('three')

export interface FigureRuntimeOptions {
  /** The figure's root (the owner places and turns it); its first child is the instance shown. */
  root: Object3D
  /** The shared model template the instance was cloned from (rest data for the secondary motion). */
  template?: Object3D
  /** The motion payload NOW — read every `poseStep`, a new `rev` reconfigures. */
  motion: () => SecondaryMotionPayload | undefined
  /** The body's collision payload (capsules, channels); null = none. */
  collision: CollisionPayload | null | undefined
  /** The tier the model was loaded at: only `full` runs strands; `low` steps the motion as far. */
  tier: 'full' | 'low'
  /** A sphere about the root holding the bound body in its bind pose (metres) — the frame plan's prefilter. */
  bindRadius: number
  /** The model the instance came from has been retired (a swap is in progress): bind nothing new. */
  retired?: () => boolean
}

/** One of this figure's channels as the last opening pass left it: `radius` = the largest occupying segment's
 *  radius × its chain's weight (metres; the surface opens to it plus `OPENING_MARGIN_M`), `applied` = recomputed
 *  this frame (the budget may defer it), `maxPush` = the largest vertex push of the last apply (metres). */
export interface OpeningInspection { channel: string; radius: number; segments: number; applied: boolean; maxPush: number }

/** `FigureRuntime.inspect()` — see there. Capsules/channels in world space. */
export interface FigureInspection {
  capsules: { id: string; region: string; now: CapsuleNow }[]
  channels: { id: string; o: [number, number, number]; u: [number, number, number]; r: number; depth: number;
    funnel: number; coneDeg: number }[]
  /** This figure's chains engaged in a PARTNER's channel: weight w and the chain's largest segment radius (metres). */
  engaged: { partner: string; channel: string; w: number; radius: number }[]
  openings: OpeningInspection[]
}

/** The phase-B outputs of one figure the frame loop reads (`frameLoop.ts`). */
export type ChannelOccupants = ReturnType<SecondaryMotion['channelOccupants']>

export class FigureRuntime {
  readonly secondary: SecondaryMotion
  private readonly three: Three
  private readonly root: Object3D
  private readonly motionNow: () => SecondaryMotionPayload | undefined
  private readonly collisionPayload: CollisionPayload | null
  private readonly retired: () => boolean
  readonly tier: 'full' | 'low'
  readonly bindRadius: number
  private garmentCollision: GarmentCollision | null
  private secondaryRev?: string
  private secondaryTime = performance.now()
  private readonly secondaryPosition: Vector3
  private readonly secondaryNextPosition: Vector3
  private readonly frameScratch: Vector3
  private secondaryPlaced = false
  private readonly secondaryFar: boolean
  /** Phase A's record for phase B (null = nothing posed since the last phase B; several phase A calls add up). */
  private pendingSecondary: { realDelta: number; frozen: boolean; far: boolean } | null = null
  private disposed = false

  /** Hands the strand record (undefined = still loading, null = none). Set by the owner after construction. */
  loadStrandRecord?: () => HairStrandRecord | null | undefined
  private strand: StrandHair | null = null
  private strandRefused = false
  private strandOn = false
  /** A first-person body hides its hair: strands stay off while set. */
  private strandBlocked = false

  private partnerBinding: CollisionBinding | null = null
  private partnerBoundOn: Object3D | null = null
  private partnerRefused = false
  private partnerChannels: ReturnType<typeof bindChannels> = null
  private openings = new Map<string, ChannelOpeningBinding | null>()
  private openingsOn: Object3D | null = null
  /** What the last opening pass put on each of this figure's channels (`inspect`): per occupied channel. */
  private openingState = new Map<string, OpeningInspection>()
  private strandPartners = false
  private gpuPartners = false

  constructor(three: Three, opts: FigureRuntimeOptions) {
    this.three = three
    this.root = opts.root
    this.motionNow = opts.motion
    this.collisionPayload = opts.collision ?? null
    this.retired = opts.retired ?? (() => false)
    this.tier = opts.tier
    this.bindRadius = opts.bindRadius
    this.secondaryPosition = new three.Vector3()
    this.secondaryNextPosition = new three.Vector3()
    this.frameScratch = new three.Vector3()
    const motion = this.motionNow()
    this.secondary = createSecondaryMotion(three, this.root, motion, opts.template)
    // Extension-bone tips kept outside the same capsules (CPU, a few tips); inert without a driven link.
    this.secondary.setCollision(opts.collision ?? undefined)
    this.secondaryRev = motion?.rev
    // Garments pushed out of the body's capsules on the GPU. Null (inert) without a garment or capsules.
    // The patched materials are clones owned by THIS runtime; `dispose` frees them.
    const inst = this.instance
    this.garmentCollision = inst ? createGarmentCollision(three, inst, opts.collision) : null
    this.secondaryFar = opts.tier === 'low'
  }

  /** The instance shown now (the root's first child). */
  private get instance(): Object3D | null {
    return this.root.children[0] ?? null
  }

  /** Explicit placement reset: the motion starts from the current pose. */
  reset(): void {
    this.secondary.reset()
    this.secondaryPlaced = false
    this.secondaryTime = performance.now()
  }

  /** END OF PHASE A: the pose is final. Configures the motion (a new `rev`, strands on/off), resets it on a root
   *  jump > 2 m, and records the real time for phase B. `realDelta` defaults to the wall clock since the last call. */
  poseStep(options: { frozen?: boolean; far?: boolean; realDelta?: number } = {}): void {
    const now = performance.now()
    const realDelta = options.realDelta ?? (now - this.secondaryTime) / 1000
    this.secondaryTime = now
    // A figure whose hair runs per strand solves no hair chain.
    const base = this.motionNow()
    const motion = this.strandOn ? withoutHairGroups(base) : base
    if (this.secondaryRev !== motion?.rev) {
      this.secondary.configure(motion)
      this.secondaryRev = motion?.rev
    }
    const position = this.root.getWorldPosition(this.secondaryNextPosition)
    // Safety net for owners that replace placement directly: >2 m is a jump.
    if (this.secondaryPlaced && position.distanceTo(this.secondaryPosition) > 2) this.secondary.reset()
    this.secondaryPosition.copy(position)
    this.secondaryPlaced = true
    const pending = this.pendingSecondary
    this.pendingSecondary = {
      realDelta: (pending?.realDelta ?? 0) + realDelta,
      frozen: !!options.frozen,
      far: options.far ?? this.secondaryFar,
    }
  }

  /** PHASE B: the strand hair and the secondary motion on this frame's final pose, against `partners` (snapshot
   *  before any phase B ran; `[]` = none). `interaction`: the running pair interaction this figure is in — a
   *  partner's channel engages only within the same one. A no-op without a pending phase A; frozen still runs it,
   *  frozen. True when it stepped. */
  updateSecondary(partners: readonly PartnerSnapshot[], interaction: { id: string } | null = null): boolean {
    const pending = this.pendingSecondary
    if (!pending) return false
    this.pendingSecondary = null
    if (this.disposed) return false
    if (this.strandOn && this.strand) {
      if (partners.length) {
        this.strand.setPartners(consumerPartnerCapsules('hair', partners))
        this.strandPartners = true
      } else if (this.strandPartners) {
        this.strand.setPartners(null)
        this.strandPartners = false
      }
      this.root.updateMatrixWorld(true)
      this.strand.update(pending.realDelta, { frozen: pending.frozen })
    }
    this.secondary.update(pending.realDelta, { frozen: pending.frozen, far: pending.far, partners, interaction })
    return true
  }

  /** What occupies the PARTNERS' channels from this figure's chains, as last rendered (Ruling A102). */
  channelOccupants(): ChannelOccupants {
    return this.disposed ? [] : this.secondary.channelOccupants()
  }

  private dropOpenings(): void {
    for (const binding of this.openings.values()) binding?.dispose()
    this.openings.clear()
    this.openingsOn = null
  }

  /** THE OPENING (Ruling A102/A102b), after every figure's phase B: the other figures' chains engaged in THIS
   *  figure's channels open its surface — each segment's radius × w. An unoccupied channel is restored; an
   *  occupied one is recomputed only when it `changed`, and only while `budget` lasts (one per recompute/bind). */
  applyChannelOpenings(occupants: readonly { channel: string; w: number; segments: readonly OpeningSegment[] }[],
    budget: { left: number } = { left: Infinity }): void {
    const before = this.openingState
    this.openingState = new Map()
    if (!occupants.length && !this.openings.size) return
    const inst = this.instance
    const channels = this.partnerChannels
    if (this.disposed || this.retired() || !channels || !inst || (this.openingsOn && this.openingsOn !== inst)) {
      this.dropOpenings()
      if (this.disposed || this.retired() || !channels || !inst) return
    }
    this.openingsOn = inst
    channels.update()
    for (const ch of channels.channels) {
      const segments: OpeningSegment[] = []
      for (const occ of occupants) {
        if (occ.channel !== ch.id) continue
        for (const seg of occ.segments) segments.push({ a: seg.a, b: seg.b, r: seg.r * occ.w })
      }
      let binding = this.openings.get(ch.id)
      if (!segments.length) { binding?.restore(); continue }
      const state: OpeningInspection = { channel: ch.id, radius: Math.max(...segments.map(seg => seg.r)),
        segments: segments.length, applied: false, maxPush: before.get(ch.id)?.maxPush ?? 0 }
      this.openingState.set(ch.id, state)
      if (binding === undefined) {
        if (!(budget.left > 0)) continue
        budget.left--
        binding = bindChannelOpening(this.three, inst, ch)
        this.openings.set(ch.id, binding)
      }
      if (!binding || !binding.changed(ch, segments) || !(budget.left > 0)) continue
      budget.left--
      state.maxPush = binding.apply(ch, segments).maxPush
      state.applied = true
    }
  }

  /** Read-only view of the cross-person state as the last frame left it (the Library preview's Collision/Channels
   *  overlay, the equality smoke): this figure's partner capsules and channels in the world NOW (recomputed from the
   *  current bones, the ones a partner engages), the chains it has engaged in partners' channels and what the last
   *  opening pass did on its own channels. Null without a bindable collision payload. */
  inspect(): FigureInspection | null {
    const binding = this.boundPartner()
    if (!binding) return null
    const channels = this.partnerChannels
    channels?.update()
    const v = (p: readonly number[]): [number, number, number] => [p[0], p[1], p[2]]
    return {
      capsules: binding.capsules.map(e => ({ id: e.capsule.id, region: e.capsule.region,
        now: { a: v(e.now.a), b: v(e.now.b), r: e.now.r } })),
      channels: (channels?.channels ?? []).map(ch => ({ id: ch.id, o: v(ch.o), u: v(ch.u), r: ch.r, depth: ch.depth,
        funnel: ch.funnel, coneDeg: ch.coneDeg })),
      engaged: this.channelOccupants().map(o => ({ partner: o.partner, channel: o.channel, w: o.w,
        radius: o.segments.length ? Math.max(...o.segments.map(seg => seg.r)) : 0 })),
      openings: [...this.openingState.values()].map(o => ({ ...o })),
    }
  }

  /** The partner binding on the instance shown now, its capsules recomputed from the current bones. */
  private boundPartner(update = true): CollisionBinding | null {
    if (this.disposed || this.retired()) {
      this.partnerBinding = null
      this.partnerBoundOn = null
      this.partnerChannels = null
      return null
    }
    if (this.partnerRefused || !this.collisionPayload) return null
    const inst = this.instance
    if (!inst) return null
    if (this.partnerBoundOn !== inst) {
      this.partnerBinding = bindCollision(this.three, inst, this.collisionPayload)
      this.partnerBoundOn = this.partnerBinding ? inst : null
      this.partnerChannels = this.partnerBinding ? bindChannels(this.three, inst, this.collisionPayload) : null
      if (!this.partnerBinding) {
        this.partnerRefused = true
        return null
      }
    }
    // The bones are read in the world: the placement of the frame (owner, root, instance) first.
    this.root.updateWorldMatrix(true, false)
    this.root.updateMatrixWorld(true)
    if (update) this.partnerBinding!.update()
    return this.partnerBinding
  }

  /** This figure for the frame plan (`planPartnerFrame`); null without a bindable collision payload and for a
   *  retired model. `name` / `members` are the owner's. */
  frameFigure(name = '', members: readonly string[] = []): FrameFigure | null {
    const payload = this.collisionPayload
    if (this.disposed || this.retired() || this.partnerRefused || !payload
      || payload.version !== COLLISION_VERSION || !payload.capsules?.length) return null
    const at = this.root.getWorldPosition(this.frameScratch)
    const lever = this.secondary.reach()
    const reader = !!this.pendingSecondary && !this.pendingSecondary.far
      && (lever > 0 || this.strandOn || this.hasHairPush)
    let body: Sphere | null | undefined
    const bodyNow = () => {
      if (body === undefined) {
        const binding = this.boundPartner()
        body = binding ? bodySphere(binding.capsules.map(entry => entry.now)) : null
      }
      return body
    }
    return {
      name, members, reader, lever,
      root: [at.x, at.y, at.z],
      bindRadius: this.bindRadius,
      body: bodyNow,
      reach: () => {
        const b = bodyNow()
        return b ? reachSphere(b, lever, this.hairSpheres()) : null
      },
    }
  }

  /** The GPU-pushed hair meshes' world spheres and the per-strand hair's rows, as last stepped. */
  private hairSpheres(): Sphere[] {
    const spheres: Sphere[] = []
    for (const entry of this.garmentCollision?.entries ?? []) {
      if (entry.sphere && !this.strandRuns(entry.mesh)) spheres.push(entry.sphere)
    }
    if (this.strandOn && this.strand) {
      const rows = this.strand.targets
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
      for (let i = 0; i + 2 < rows.length; i += 3) {
        for (let d = 0; d < 3; d++) {
          lo[d] = Math.min(lo[d], rows[i + d])
          hi[d] = Math.max(hi[d], rows[i + d])
        }
      }
      if (lo[0] <= hi[0]) {
        const c: [number, number, number] = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
        spheres.push({ c, r: Math.hypot(hi[0] - c[0], hi[1] - c[1], hi[2] - c[2]) })
      }
    }
    return spheres
  }

  /** This figure's capsules and channels as a partner reads them in phase B; null when unbindable. */
  partnerSnapshot(interaction: { id: string; kind: string } | null, name = ''): PartnerSnapshot | null {
    const binding = this.boundPartner(false)
    if (!binding) return null
    const snap = snapshotPartner(name, binding, interaction)
    const channels = this.partnerChannels
    if (!channels) return snap
    channels.update()
    // A copy: the next update puts fresh objects into the binding's slots, this frame's snapshot keeps its own.
    return { ...snap, channels: [...channels.channels] }
  }

  private strandRuns(mesh: Object3D): boolean {
    return this.strandOn && !!this.strand && this.strand.mesh === mesh
  }

  /** The figure's hair meshes are pushed on the GPU (a hair entry the per-strand hair has not taken over). */
  get hasHairPush(): boolean {
    return !!this.garmentCollision?.entries.some(entry => entry.kind === 'hair' && !this.strandRuns(entry.mesh))
  }

  /** The partner capsules the GPU hair push reads at render time; null or `[]` = none. */
  setGpuPartners(capsules: readonly CapsuleNow[] | null): void {
    const any = !!capsules?.length
    if (!any && !this.gpuPartners) return
    this.gpuPartners = any
    this.garmentCollision?.setPartners(any ? capsules : null)
  }

  get strandHair(): StrandHair | null { return this.strand }
  get strandRunning(): boolean { return this.strandOn }
  /** Measured (or estimated) strand ms per frame; the whole budget without a handle. */
  get strandCostMs(): number { return this.strand?.costMs ?? STRAND_LIMITS.budgetMs }

  /** Bind the strand record once it has loaded (the first call starts the download): true when a handle is ready.
   *  False without a record, at the distance tier, or for good when record and mesh do not belong together. */
  prepareStrandHair(): boolean {
    if (this.strand) return true
    if (this.strandRefused || this.tier !== 'full' || !this.loadStrandRecord) return false
    const record = this.loadStrandRecord()
    if (record === undefined) return false
    const inst = this.instance
    const handle = record && inst ? createStrandHair(this.three, inst, record) : null
    if (!handle) {
      this.strandRefused = true
      if (record) {
        console.warn(`[figures] ${record.item_id}: the hair mesh does not carry the strand binding of record`
          + ` ${record.fit_sha256.slice(0, 12)} — the hair stays on its chains`)
      }
      return false
    }
    this.strand = handle
    return true
  }

  /** Strands off for good while `blocked` (a first-person body); switching it on switches the strands off. */
  setStrandBlocked(blocked: boolean): void {
    this.strandBlocked = blocked
    if (blocked) this.setStrandHair(false)
  }

  /** Per-strand hair on/off (on only with a ready handle and not blocked): the hair leaves the GPU push and the
   *  chains while it runs, both come back when it stops. */
  setStrandHair(on: boolean): void {
    const want = on && !!this.strand && !this.strandBlocked
    if (want === this.strandOn || !this.strand) return
    this.strandOn = want
    this.strand.setEnabled(want)
    this.garmentCollision?.excludeMesh(this.strand.mesh, want)
  }

  /** The runtime's own resources: openings, the partner binding, the motion, the strand clone, the garment
   *  material clones. The template's geometry and materials are NOT among them. */
  dispose(): void {
    this.disposed = true
    this.dropOpenings()
    this.pendingSecondary = null
    this.partnerBinding = null
    this.partnerBoundOn = null
    this.partnerChannels = null
    this.secondary.dispose()
    // The strand handle first: it puts the template's geometry back and frees its clone; then the materials.
    this.strand?.dispose()
    this.strand = null
    this.strandOn = false
    this.garmentCollision?.dispose()
    this.garmentCollision = null
  }
}

/** Build the runtime for one figure (module docstring). */
export function createFigureRuntime(three: Three, opts: FigureRuntimeOptions): FigureRuntime {
  return new FigureRuntime(three, opts)
}
