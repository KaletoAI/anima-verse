# Cross-person collision and declared channels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hair and spring-driven extension chains never pass through another person (stage 1). A growing extension
chain may slide into a channel that a package declares on another body, but only inside a running pair interaction
(stage 2).

**Architecture:** Every rule lives once in `@anima/scene-render`, so the 3D client and the admin viewer run the same
code:
- partner selection, the per-consumer filters, the broad phase, the combined contact search and the hysteresis;
- the squeeze push and the partner block of the hair push, each as a TypeScript function with a GLSL twin;
- the channel guidance.

The server fits three new capsule kinds (collision v5 `appendage`, v6 `outer_trunk`) and resolves declared channels
into bind space (v7). The 3D client cuts each figure frame in two phases: phase A is the pose of every figure, phase
B is every figure's secondary motion against snapshots of its partners. The admin viewer gets a partner probe
(stage 1), and in stage 2 a channel overlay, a test rod and a store-only Channels panel. The first real channel is
declared in the private packs repo, as the last task.

**Tech Stack:** Python 3 / numpy (server fit, no Blender except the `inset_part` op), Blender 5.2 script
`app/blender/scripts/inset_part.py`, TypeScript `@anima/scene-render` (three injected), client3d (vanilla Three.js +
React HUD), React Game-Admin, and node smokes bundled with esbuild.

**Spec:** `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` (binding). It includes "Calls made by
the coordinating session", "User answers (2026-11-13)" and "Added 2026-11-13 — squeeze rule". The base contract is
`docs/schnittstellen-3d.md` "Collision capsules (`collision`)". The base design is
`docs/superpowers/specs/2026-11-08-collision-capsules-design.md`.

**Commission (user, 2026-11-14):** the channel belongs to the inset rig of the private pack (op `inset_part`). It runs
from the opening upward into the body. The op reports the `opening`, and the pack's region uses `from_rig`.

**Ledger:** create `.superpowers/sdd/2026-11-14-cross-person-collision/progress.md`. Record in it:
- the BASE of each task (the commit before it);
- the measured constants and the rulings;
- the smokes that were already red.

BASE of this plan: `aaf2fc349`.

## Global Constraints

**Versions and core rules**
- Version order: **CX1 = 5, outer trunk set = 6, channels = 7** (user answer 1). `app/core/collision.py` `VERSION`
  and `packages/scene-render/src/collision.ts` `COLLISION_VERSION` change in the SAME commit. That commit also
  rebuilds BOTH committed bundles (`static/game_admin/`, `static/client3d/`), so the two renderers always bump
  together.
- R1 / anti-goals: no core code, constant, comment, test fixture, UI label or commit message names a body part, a
  package or a skill. Channels are generic regions (`kind: channel`), ops are the core's generic names, and
  everything specific comes from a manifest. A fixture uses neutral ids only (`TestPart`, `chan`, `pkg:chan`). Only
  the packs-repo task names its own ids, and only as data.

**Smokes**
- A smoke is a standalone `scripts/smoke_*.py|mjs` with a `Usage:` docstring. Every expected number is derived BY
  HAND in its docstring, from the spec or from the plan's derivations below. A "fails on the old code" proof pins the
  task's BASE hash from the ledger, never `HEAD:`.
- A smoke makes 0 outbound requests and opens no world DB. Python smokes call `paths.init(<tmpdir>)` before any
  world-DB import. Importing `app.server` needs `STORAGE_DIR` and `INSTANCE_DIR` set to temp dirs. Node smokes bundle
  with esbuild and keep `three` external, the pattern of `scripts/smoke_client_strand_wiring.mjs`.

**Runtime rules**
- Disposal follows the ownership ledger. A mount frees only the geometries, materials and uniforms IT created:
  - every probe, channel or rod wireframe belongs to the viewer that drew it;
  - every patched material clone belongs to its `GarmentCollision` handle;
  - a figure's partner binding belongs to the figure and is dropped with the model it was bound on (it holds no GPU
    resource).
  Nothing frees a shared template.
- The 3D client builds no settings. All tuning UI lives in Game-Admin.

**Shared worktree and commits**
- Read-only against live data: never open a live `world.db`, never write under `worlds/`, never call `:8000`. The
  check scripts read COPIES of stored models and clips from the test-world clone (an Anima Divide copy). The copies go
  under `~/claude-out/cross-person/`, and their sha256 goes into the ledger. Hub-job budget: **0**.
- Commit path-scoped through a temp index with own hunks only:
  - `export GIT_INDEX_FILE=$(mktemp -u)`, `git read-tree HEAD`, `git apply --cached own.patch` (new files:
    `git add`);
  - `git commit -m …` without paths, then `unset GIT_INDEX_FILE`.
  - Never run `reset`, `--amend`, `stash` or `checkout`.
  - Never stage `shared/items/*`, `shared/config/model_capabilities.json` or
    `shared/templates/expression/expression_catalog.json`.
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Bundles: run `npm run build` in a clean detached worktree at the commit
  (`git worktree add --detach /tmp/cx-bundle <hash>`). Copy back only the changed files of `static/game_admin/` and
  `static/client3d/`, then remove the worktree.
- Type checks: `npm run build -w client3d` (its only type check), `cd frontend && npm run build`, and `npm run lint`
  from the root. Each task that changes exports of `@anima/scene-render` also updates
  `packages/scene-render/README.md` and runs `./.venv/bin/python scripts/smoke_docs_scene_render_readme.py`.

**UI**
- UI strings are English through `t()`. Their `shared/languages/de.json` keys are taken from the HEAD blob plus own
  keys. No `window.prompt/alert/confirm`. Modals use `createPortal` to `document.body`.
- Every Game-Admin control in this plan follows the 10-point checklist (memory
  `feedback_charakter_reiter_checkliste.md`), copied in full into Task 15:
  1. run-all + single-step buttons;
  2. Save never executes;
  3. only current flows;
  4. settings beside the viewer, live while dragging;
  5. 2–3 column grid, sub-tabs above ~8 rows;
  6. small, enlargeable images;
  7. measures with a reference;
  8. a traffic light per step with its reason, and "Built <time>";
  9. job cost before the click;
  10. English strings with de.json keys, no native dialogs.
  The task renders the tab headless with fixture data into `~/claude-out/cross-person/ui/` and ticks each point with
  its evidence.

**Constants**
- These are starting values. The builder sets the final ones from the check script of Task 9, and they are recorded
  in the ledger and in the constants' doc comments:

  | Constant | Value |
  |---|---|
  | `PARTNER_MAX` | 4 |
  | `PARTNER_COLLIDE_MAX` | 8 |
  | `PARTNER_PUSH_MAX_M` | 0.04 |
  | `PARTNER_HYST_M` | 0.003 |
  | `PARTNER_RELEASE_DEG_S` | 240 |
  | `PARTNER_PREFILTER_SLACK_M` | 1.0 |
  | `CHANNEL_BLEND_S` | 0.2 |
  | `CHANNEL_HYST_M` (h) | 0.005 |
  | `CHANNEL_HYST_DEG` (δ) | 10 |
  | `SQUEEZE_ROUNDS` | 3 |
  | `SQUEEZE_STEPS` | 16 |
  | `SQUEEZE_MIN_N` | 1e-3 |

## Review Focus

1. **Strand hair after a version bump.** Strand records store the capsule list with the version it was fitted at
   (`hair_strands.py:369`), and `hairSim.ts:179` binds `{version: record.capsules.version}`. The first bump (v5) would
   therefore make `bindCollision` return null and take every strand sim's colliders away silently. Expected: strands
   keep colliding. Their record's capsule list is their own currency (fit sha + scales). Tested in Task 1 Step 3.
2. **A covered outfit model that inherits the base body's record with channels.** Expected: no channel on that model
   (anti-goal "a channel that engages through clothing"). Exposure is identity, applied at fit AND relabel time, and
   is never deferred. Tested in Task 12 [5].
3. **A partner whose model is swapped mid-session** (retired model, a new signature, or a payload of an older version).
   Expected: that frame skips the partner. Its binding is rebuilt lazily on the live model, and nothing reads a
   retired instance. Tested in Task 7 [5].
4. **A pair interaction that ends, or a gate that fails, while a chain is engaged.** Expected: w ramps 1 → 0 over
   `CHANNEL_BLEND_S`, the chain is never snapped out, and the depth scale k returns to 1 with w. Tested in Task 14 [4].
5. **The Figure-tab poll right after a Channels Save.** The poll's `collision.ensure` refits stale records on read.
   Expected: a changed `channels_sig` alone is reported due and NOT applied by the poll (Save never executes). Only the
   explicit recompute, the whole-flow button and the Improvements queue apply it. Tested in Task 12 [6].

---

## Derivations used by the smokes (by hand; Python only re-checked the arithmetic)

**D1. Spec Part 3:** the turn is θ = 5.737°. With a 4° budget the tip ends 26.977 mm from the axis, so 3.02 mm stays
inside.

**D2. Spec Part 4:** these are the spec's own numbers:
- lever 0.104403 m at 16.699° from u;
- turn 5.655°, tip s = 0.05247;
- with r_c = 0.005: guided angle 8.260°, turn 8.439°;
- funnel R'(−0.02) = 0.031547;
- depth k = 0.8 cases, and the hysteresis cases at 0.023 / 0.026.

**D3. Squeeze, two-capsule fixture in the xz-plane.** Both capsules are vertical (axes parallel to y, y from 0 to 1):
- "T": axis through x = 0, z = 0, r = 0.10;
- "A": axis through x = 0.13, z = 0, r = 0.05.

The point lies at y = 0.5. n_i is the unit vector from capsule i's axis to the ORIGINAL point.

- **Case S1, inside both:** p = (0.09, 0.02).
  - d_T = 0.092195, n_T = (0.976187, 0.216930); d_A = 0.044721, n_A = (−0.894427, 0.447214).
  - N = normalize(n_T + n_A) = (0.122183, 0.992508).
  - Exit along N: t_T = 0.018666, t_A = 0.011942. "Outside both" is first true at t = 0.018666, giving
    q = (0.092281, 0.038526). There, d_T = 0.100000 and d_A = 0.053917.
  - Today's two sequential passes (T then A) end at (0.092223, 0.032756), which is 2.13 mm inside T: the last applied
    capsule wins.
- **Case S2, the spec's arm case:** p = (0.105, 0.02) lies inside A only (d_A = 0.032016; d_T = 0.106888).
  - Round 1: S = {A}. The exact radial push gives q1 = (0.090957, 0.031235), with d_T = 0.096170, so q1 is inside T.
  - Round 2: S = {A, T}, n_A = (−0.780869, 0.624695), n_T = (0.982339, 0.187112), N = (0.240868, 0.970558). The exit
    is t = 0.027283, giving q = (0.111572, 0.046480). There, d_A = 0.050000 and d_T = 0.120868: outside both.
  - Today: ends 0.91 mm inside T.
- **Case S3, degenerate:** p = (0.09, 0). Then n_T = −n_A, so |Σn| = 0 < `SQUEEZE_MIN_N`, and the ordinary passes
  apply: q = (0.08, 0).

Bisection runs `SQUEEZE_STEPS` = 16 steps on [0, 2·max r]. Resolution: 0.2/65536 m, so the tolerance is 0.01 mm.

**D4. Outer trunk on the existing ellipse ring:** x = 0.12 cos θ, z = 0.10 sin θ, θ uniform, front f = +z.
- The q-quantile of z is b·sin(π(q − ½)). At q = 0.98: F = B = 0.10·sin(0.48π) = 0.099803.
- Offset o = (F − B)/2 = 0 and r = (F + B)/2 = 0.099803.
- The same ring centred at z = +0.03 ("shifted" variant) gives F = 0.129803, B = 0.069803, o = 0.03, r = 0.099803,
  and `a_pos` = joint + (0, 0, 0.03). Tolerance 0.3 mm.

**D5. Opening on the `inset_part` round-sphere fixture** (`scripts/smoke_inset_part_blender.py`: sphere r 0.15 at
(0, 0, 1.02), Blender front −y, override `pocket.s0` .07):
- The chart's `s` is arc length on the sphere (scale 1), and s = 0.05 lies at the normal angle 72.534° (the docstring
  derivation there).
- Opening s = (0.07 + 0.094)/2 = 0.082, so φ = 72.534° + (0.032/0.15) rad = 84.757°.
- Blender point (0, −0.15 cos φ, 1.02 − 0.15 sin φ) = (0, −0.013706, 0.870627). The inward normal is
  (0, cos φ, sin φ).
- glTF bind space through (x, y, z)_gltf = (x, z, −y)_blender:
  - centre (0, 0.870627, 0.013706);
  - axis (0, 0.995817, −0.091372): mostly up, slightly back.
- Tolerance: 2 mm and 1° (0.5° profile rays).

**D6. Body and reach spheres.** Capsules A: (0,0,0)→(0,1,0), r 0.1. B: a = b = (0.5,1,0), r 0.05.
- Centre = the mean of the four endpoints = (0.25, 0.75, 0).
- r = max(0.790569 + 0.1, 0.353553 + 0.1, 0.353553 + 0.05) = 0.890569.
- Selection: the reader's reach is centred at (0,1,0) with r 1.0. Candidate body spheres (r 0.5) at x = 1.4 (member
  "m"), 0.5 ("a"), 1.0 ("b"), 1.2 ("c"), 1.5 ("d") and 3.0 ("e"). Their gaps: −0.1, −1.0, −0.5, −0.3, 0.0 and 1.5.
- Result: [m, a, b, c]. "e" is out of reach, and "d" is cut by `PARTNER_MAX` = 4.

**D7. Partner fade, GPU and CPU twin,** M = 0.04, partner sphere r 0.10:
- d = 0.08: depth 0.02 ≤ M, so the point goes to 0.10;
- d = 0.05: depth 0.05, f = (0.06 − 0.05)/0.02 = 0.5, push 0.025, so the point goes to 0.075;
- d = 0.03: depth 0.07 ≥ 1.5M, so it stays at 0.03.
- Release: `releasedAngle(prev 10°, want 0°, dt 1/60)` = 6°; (10, 8) = 8; (3, 0) = 0.

---

## File map

| File | Responsibility |
|---|---|
| `app/core/collision.py` | v5 `appendage` (CX1), v6 `outer_trunk` (end rule `"outer"`), `bind_pose_capsules`, `channels_current`, `ensure_path(apply_channels=)` |
| `app/core/collision_channels.py` (new) | stage 2: `body_frame`, `resolve_channels`, `channels_sig`, override validation, `wanted_channels` |
| `app/plugins/registry.py`, `app/plugins/loader.py` | `RegionSpec`, `BodySlotSpec.regions` |
| `app/core/extension_rig.py` | `region_declarations_for`; `motion_payload` groups carry `op` |
| `app/blender/scripts/inset_part.py` | `opening` build metric (core op) |
| `app/core/model3d.py` | `model3d_opts.collision_channels` option |
| `app/routes/characters.py` | `GET …/model3d/collision/bind-pose`, `POST …/model3d/collision/channels` (store only) |
| `app/routes/figure.py`, `app/core/model_overview.py`, `app/core/improvements/types/collision_capsules.py` | channel data and currency |
| `packages/scene-render/src/collision.ts` | version, regions, colours, `PARTNER_ONLY_REGIONS`, `CollisionPayload.channels` |
| `packages/scene-render/src/garmentCollision.ts` | `PushOptions` (squeeze, partners), GLSL twin, `setPartners` |
| `packages/scene-render/src/partnerContact.ts` (new) | spheres, selection, consumer filters, broad phase, `contactAnglePair`, `releasedAngle`, snapshots |
| `packages/scene-render/src/secondaryMotion.ts` | partner contact, channel engagement, `reach()` |
| `packages/scene-render/src/hairSim.ts` | version-free strand binding, `setPartners` |
| `packages/scene-render/src/partnerProbe.ts` (new) | probe capsule set + sweep (admin) |
| `packages/scene-render/src/channels.ts` (new) | `bindChannels`, guidance math, engagement, wireframe, rod, draft preview |
| `client3d/src/scene/partnerFrame.ts` (new) | pure per-frame partner plan |
| `client3d/src/scene/figures.ts`, `npcs.ts`, `client3d/src/figureTest.ts` | two-phase frame |
| `frontend/src/tabs/characters/CollisionScales.tsx` | `appendage`, `outer_trunk` sliders |
| `frontend/src/tabs/characters/PartnerProbeControls.tsx` (new), `ChannelRodControls.tsx` (new), `CollisionChannels.tsx` (new), `Model3DViewer.tsx`, `FieldBaseBody.tsx`, `FieldModel3D.tsx` | viewer and panel |
| `docs/schnittstellen-3d.md`, `docs/plugins.md`, `CLAUDE.md`, `packages/scene-render/README.md` | contract and docs |
| `../anima-verse-packs/packs/<pack>/plugin.yaml` | the first real channel (Task 17) |

---

## CX1

### Task 1: `appendage_chain` extension capsules (collision v5)

**Files:**
- Modify: `app/core/collision.py`:
  - `VERSION` 4 → 5;
  - add `"appendage"` to `REGIONS`;
  - `EXTENSION_CAPSULES["appendage_chain"]`;
  - a docstring paragraph "version 5";
  - `EXTENSION_MEASURED` lines.
- Modify: `packages/scene-render/src/collision.ts`: `COLLISION_VERSION` = 5 plus its version list, and
  `CAPSULE_REGION_COLORS.appendage`.
- Modify: `packages/scene-render/src/garmentCollision.ts` (`EXTENSION_REGIONS` gets `'appendage'`; update the
  `COLLIDE_MAX` budget comment).
- Modify: `packages/scene-render/src/hairSim.ts:179` (bind with `COLLISION_VERSION`).
- Modify: `frontend/src/tabs/characters/CollisionScales.tsx` (region `appendage`, label "Appendage", an extension
  region) and `shared/languages/de.json`.
- Modify: `docs/schnittstellen-3d.md` (the version line in "Collision capsules").
- Modify (literal `version: 4` → the imported `COLLISION_VERSION`, Python → `collision.VERSION`):
  `scripts/smoke_check_collision_payload.mjs`, `smoke_client_strand_wiring.mjs`, `smoke_collision_endpoints.mjs`,
  `smoke_extension_collision.mjs`, `smoke_garment_collision.mjs`, `smoke_hair_alpha_client.mjs`, `smoke_hair_sim.mjs`
  and `smoke_strand_hair_handle.mjs`. Later bumps then touch no smoke literal.
- Test: `scripts/smoke_collision_capsules.py` (new section [9]), `scripts/smoke_strand_hair_handle.mjs` (new case).

**Interfaces:**
- Produces:
  - `EXTENSION_CAPSULES["appendage_chain"] = (("appendage", Q_APPENDAGE, 0.0),)`, where `Q_APPENDAGE` comes from
    Step 1;
  - region `"appendage"` in `REGIONS`, `EXTENSION_REGIONS` and `CollisionScales`;
  - `COLLISION_VERSION === 5`.

- [ ] **Step 1: Measure.** Copy every stored full-tier model of the test-world clone whose sidecar `extension_rig`
  is `applied` with a `group_ops` value `appendage_chain` into `~/claude-out/cross-person/cx1/`.
  - For p50/p75/p90 (margin 0), measure each capsule surface's outside distance with the method of
    `EXTENSION_MEASURED` (3-mm voxels, dilate once, fill holes).
  - Pick the largest quantile that keeps every closed body within the 5-mm penetration threshold. The starting guess
    is p75, as `attached_part`.
  - Record the numbers under `EXTENSION_MEASURED` and in the ledger. If no such model exists, use p75, write
    "unmeasured, p75 as attached_part" there, and flag it in the ledger.
- [ ] **Step 2: Write the failing tests.**
  - `smoke_collision_capsules.py` [9] APPENDAGE: op `appendage_chain`, chain [TestApp1, TestApp2] in the body node:
    - TestApp1 (0, 0.9, 0.12) → TestApp2 (0, 0.9, 0.22);
    - a ring r 0.03 weighted TestApp1;
    - a ring r 0.025 from 0.22 to 0.30 weighted TestApp2.
  - [9] expected values. A ring has one distance, so every quantile equals its radius:
    - capsule `app:testapp1`: a TestApp1, b TestApp2, r 0.030, region `appendage`;
    - `app:testapp2`: tip rule, b_pos (0, 0.9, 0.267), r 0.025.
  - [9] scales and payload: scale `appendage` 1.2 gives r 0.036 and 0.030, with b_pos z = 0.22 + 0.072 − 0.030 =
    0.262. The payload version is 5.
  - `smoke_garment_collision.mjs`: `garmentCapsules('cloth', …)` keeps an `appendage` capsule, and
    `garmentCapsules('hair', …)` does not.
- [ ] **Step 3: Write the strand case (Review Focus 1)** in `smoke_strand_hair_handle.mjs`: a record whose
  `capsules.version` is 4 still binds its colliders after the bump (`capsuleIds` is non-empty and equals the v4 list).
  It fails at BASE `aaf2fc349` once `COLLISION_VERSION` is 5: run the smoke against a worktree of BASE with only the
  constant changed, and record that in the ledger.
- [ ] **Step 4: Run and see them fail.**
  - Run: `./.venv/bin/python scripts/smoke_collision_capsules.py`. Expected: FAIL [9] (no `appendage` capsules).
  - Run: `node scripts/smoke_strand_hair_handle.mjs`. Expected: PASS before the TS bump; FAIL after the bump without
    the `hairSim.ts` change.
- [ ] **Step 5: Implement** the server entry, region and version; `COLLISION_VERSION = 5`; `hairSim.ts`.
  - `bindCollision(three, root, {version: COLLISION_VERSION, capsules})`: the record's list is the strand's own
    frozen copy.
  - The `CollisionScales` slider shows only where the set has `appendage` capsules (the existing extension-region
    rule).
- [ ] **Step 6: Run every collision smoke** and see them pass: `smoke_collision_capsules.py`,
  `smoke_collision_scales_route.py`, `smoke_collision_endpoints.mjs`, `smoke_garment_collision.mjs`,
  `smoke_extension_collision.mjs`, `smoke_hair_chain_contact.mjs`, `smoke_strand_hair_handle.mjs`, `smoke_hair_sim.mjs`,
  `smoke_client_strand_wiring.mjs` and `smoke_check_collision_payload.mjs`. Also run
  `smoke_docs_schnittstellen_3d.py`. Expected: all PASS.
- [ ] **Step 7: Build both bundles and commit** with the message
  `feat(collision): appendage_chain gets its own extension capsules (collision v5)`.

## Stage 1 — partner contact (G1 + G2)

### Task 2: Partner-only outer trunk set (collision v6)

**Files:**
- Modify: `app/core/collision.py`:
  - `VERSION` 6;
  - `REGIONS` gets `"outer_trunk"`;
  - three table rows with end rule `"outer"`;
  - `FRONT_FROM = "LeftFoot"`, `FRONT_TO = "LeftToeBase"`;
  - the docstring paragraph "version 6 — OUTER TRUNK (partners only)";
  - `OUTER_MEASURED`.
- Modify: `packages/scene-render/src/collision.ts`: `COLLISION_VERSION = 6`, `PARTNER_ONLY_REGIONS`, and a colour.
- Modify: `packages/scene-render/src/secondaryMotion.ts` (`extensionCapsules` also drops `PARTNER_ONLY_REGIONS`).
- Modify: `packages/scene-render/src/garmentCollision.ts` (`CLOTH_EXCLUDED_REGIONS` gets `...PARTNER_ONLY_REGIONS`).
- Modify: `frontend/src/tabs/characters/CollisionScales.tsx` (region `outer_trunk`, label "Outer trunk (partners)",
  always shown) and `shared/languages/de.json`.
- Test: `scripts/smoke_collision_capsules.py` ([1], [3], [7] counts; new [10]), `scripts/smoke_garment_collision.mjs`,
  `scripts/smoke_extension_collision.mjs`, `scripts/smoke_hair_chain_contact.mjs`.

**Interfaces:**
- Produces:
  - capsules `outer_hips` (Hips→Spine1), `outer_spine` (Spine1→Spine2) and `outer_chest` (Spine2→Neck), region
    `outer_trunk`, with `a_pos`/`b_pos` set;
  - `export const PARTNER_ONLY_REGIONS: readonly string[] = ['outer_trunk']`.
- The OUTER rule, per segment a→b and the start bone's owned vertices:
  - axis e = unit(b − a);
  - front f = unit((toe − foot) − ((toe − foot)·e)e);
  - z_v = (v − a)·f, F = quantile(z, 0.98), B = quantile(−z, 0.98);
  - o = (F − B)/2;
  - r = ((F + B)/2·unit + margin)·scale (margin 0.0);
  - `a_pos` = a + o·f, `b_pos` = b + o·f.
  - A missing `LeftToeBase`/`LeftFoot` skips all three with "joint … missing".

- [ ] **Step 1: Measure** on read-only copies of five base bodies (those of `TORSO measured`) and record
  `OUTER_MEASURED`:
  - per segment, the median front/back profile distance (as in the TORSO block) against F/B at q ∈ {0.95, 0.98,
    0.99};
  - the share of the capsule surface more than 5 mm outside the body volume, sideways included.
  - Keep q = 0.98 unless another q has a lower outside share and stays within the front profile ±5 mm.
- [ ] **Step 2: Write the failing tests.**
  - `smoke_collision_capsules.py`: the fixture gets `LeftToeBase` (0.1, 0.02, 0.12). Then:
    - [1] has 17 capsules (14 + 3 outer);
    - `outer_hips` r 0.0998 ±0.3 mm, `a_pos` (0, 1.0, 0), `b_pos` (0, 1.2, 0);
    - `outer_spine` and `outer_chest` the same on their segments (D4).
  - [10] SHIFTED: torso rings centred at z = +0.03. `outer_spine` gets r 0.0998 and `a_pos` (0, 1.2, 0.03). Without
    `LeftToeBase`, three skipped entries with "joint LeftToeBase missing".
  - [3] `{"outer_trunk": 1.2}` gives the three outer radii × 1.2 (0.1198); every other radius is unchanged.
  - [7] the overview row says "17 capsules …" and lists `outer_trunk 10.0 cm`.
  - JS: neither `garmentCapsules('cloth'|'hair')`, `extensionCapsules` nor `hairChainCapsules` returns an
    `outer_trunk` capsule (one fixture capsule per region; assert the id lists).
- [ ] **Step 3: Run and see them fail.** Run: `./.venv/bin/python scripts/smoke_collision_capsules.py`. Expected: FAIL
  [1] (14 ≠ 17) and [10].
- [ ] **Step 4: Implement** the rule, `PARTNER_ONLY_REGIONS` and the filters. Set `COLLISION_VERSION = 6`.
- [ ] **Step 5: Run** the collision smokes listed in Task 1 Step 6. Expected: all PASS.
- [ ] **Step 6: Build both bundles and commit** with the message
  `feat(collision): a partner-only outer trunk set fitted to the front and back profile (collision v6)`.

### Task 3: The squeeze rule (shared push and GLSL twin, hair)

**Files:**
- Modify: `packages/scene-render/src/garmentCollision.ts`: `PushOptions`, `pushOutOfCapsules(p, capsules, weight,
  bindP, options)`, `COLLIDE_GLSL_*` under `#ifdef COLLIDE_SQUEEZE`, the define set for kind `hair` only, and the
  docstring "SQUEEZE".
- Modify: `packages/scene-render/src/secondaryMotion.ts` (`keepHairTipOutside` pushes with `{squeeze: true}`).
- Create: `scripts/smoke_collision_squeeze.mjs`.
- Modify: `scripts/smoke_garment_collision.mjs`. Its GLSL→JS rewrite may gain ONE rule, for local `float` arrays; the
  GLSL stays scalar statements.

**Interfaces:**
- Produces:
  - `export interface PushOptions { squeeze?: boolean; partners?: readonly CapsuleNow[] }` (`partners` is used from
    Task 6);
  - `export const SQUEEZE_ROUNDS = 3, SQUEEZE_STEPS = 16, SQUEEZE_MIN_N = 1e-3`;
  - `pushOutOfCapsules(p: Vec3, capsules: readonly CollideCapsule[], weight = 1, bindP?: Vec3,
    options?: PushOptions): Vec3`.
- The SQUEEZE rule (radii are the bind-capped radii):
  1. S = the capsules containing p. If S is empty, return p.
  2. Each round:
     - With |S| = 1 in round 1, take the exact radial push. Otherwise N = unit(Σ n_i(p)), where n_i(p) points from
       capsule i's closest axis point to the ORIGINAL p.
     - If |Σ n_i| < `SQUEEZE_MIN_N`, return the ordinary passes.
     - Find t by `SQUEEZE_STEPS` bisection steps on [0, 2·max r_S] for "p + tN is outside every capsule of S". If
       2·max r_S is not outside them all, return the ordinary passes.
     - q = p + t_hi·N. If q lies inside capsules not in S, add them to S and repeat (at most `SQUEEZE_ROUNDS`);
       otherwise return q.
  3. Without `squeeze`, the result is today's passes bit for bit.

- [ ] **Step 1: Write the failing test** `smoke_collision_squeeze.mjs`:
  - [1] D3 case S1: q = (0.092281, y 0.5, 0.038526) ±0.01 mm. Without squeeze: (0.092223, 0.5, 0.032756).
  - [2] D3 case S2: q = (0.111572, 0.5, 0.046480) ±0.01 mm. Without squeeze it ends 0.91 mm inside T.
  - [3] D3 case S3: (0.08, 0.5, 0).
  - [4] Inside one capsule only: identical to the push without squeeze.
  - [5] The GLSL string with `COLLIDE_SQUEEZE` gives the TS points to 1e-6 for [1]–[4].
  - [6] A non-hair garment's patched shader source has no `COLLIDE_SQUEEZE`; a hair garment's has it.
- [ ] **Step 2: Run** `node scripts/smoke_collision_squeeze.mjs`. Expected: FAIL (`PushOptions` missing).
- [ ] **Step 3: Implement** the rule in TS and GLSL. Hair chain tips use it in `keepHairTipOutside`.
- [ ] **Step 4: Run** `smoke_collision_squeeze.mjs`, `smoke_garment_collision.mjs`, `smoke_hair_chain_contact.mjs`
  and `smoke_strand_hair_handle.mjs`. Expected: PASS.
- [ ] **Step 5: Measure** the spec's case with `scripts/check_garment_collision.mjs`: Kira's model copy, "celebrating"
  at t = 18.525 s, the B11h area. Write p50/p90/max under the chest skin before and after into the ledger and into the
  garmentCollision docstring as `SQUEEZE_MEASURED`. The before values must reproduce 12.3 / 26.7 / 52.5 mm ±1 mm;
  otherwise stop and report.
- [ ] **Step 6: Commit** with the message
  `feat(collision): the squeeze rule — a hair point between two capsules leaves along their combined normal`.

### Task 4: Partner rules, pure (`partnerContact.ts`)

**Files:**
- Create: `packages/scene-render/src/partnerContact.ts`; export it from `index.ts` and list it in the README.
- Create: `scripts/smoke_partner_rules.mjs`.

**Interfaces:**
- Produces (all pure; `Sphere = { c: Vec3; r: number }`):
  - the starting constants `PARTNER_MAX`, `PARTNER_COLLIDE_MAX`, `PARTNER_PUSH_MAX_M`, `PARTNER_HYST_M`,
    `PARTNER_RELEASE_DEG_S` and `PARTNER_PREFILTER_SLACK_M` (Global Constraints);
  - `bodySphere(capsules: readonly CapsuleNow[]): Sphere | null`;
  - `reachSphere(body: Sphere, lever: number, hair?: readonly Sphere[]): Sphere`: the radius grows to
    max(r + lever, max over the hair spheres of |c_h − c| + r_h);
  - `selectPartners(reach: Sphere, members: ReadonlySet<string>, candidates: readonly { name: string; body: Sphere }[],
    max = PARTNER_MAX): string[]` (gap ≤ 0 counts; members first, then the smallest gap);
  - `partnerCapsules<T extends { capsule: { region: string } }>(consumer: 'hair' | 'extension', bound: readonly T[]): T[]`:
    - hair: every region;
    - extension: every region but `HAIR_ONLY_REGIONS`;
    - both drop region `torso` when the set has `outer_trunk` (ruling R7);
  - `broadPhase(joint: Vec3, lever: number, capsules: readonly CapsuleNow[]): number[]` (keep a capsule when its
    segment distance to the joint ≤ lever + r);
  - `contactAnglePair(depthAt: (angle: number) => [number, number], depth0: [number, number], limit: number):
    number | null`:
    - the smallest angle in (0, limit] that is outside both;
    - otherwise the angle with the smallest own depth, ties broken by the smallest partner depth;
    - null when no better than 0;
  - `releasedAngle(prevDeg: number, wantDeg: number, dt: number): number` = max(want, prev − `PARTNER_RELEASE_DEG_S`·dt,
    0);
  - `nearestCapsules(sphere: Sphere, capsules: readonly CapsuleNow[], max: number): number[]` (by segment distance to
    the centre minus r, ascending);
  - `interface PartnerCapsule { id: string; region: string; now: CapsuleNow }`;
  - `interface PartnerSnapshot { name: string; capsules: readonly PartnerCapsule[]; channels: readonly ChannelNow[];
    interaction: { id: string; kind: string } | null }`. `ChannelNow` is declared here as an empty-array type until
    Task 13; `channels` is `[]` in stage 1;
  - `snapshotPartner(name: string, binding: CollisionBinding, interaction: PartnerSnapshot['interaction']):
    PartnerSnapshot` (calls `binding.update()` once).

- [ ] **Step 1: Write the failing test** `smoke_partner_rules.mjs`:
  - [1] D6 body sphere (0.25, 0.75, 0) / 0.890569 ±1e-6.
  - [2] D6 selection [m, a, b, c].
  - [3] Reach with a lever of 0.3 has r = 1.190569. With lever 0 and a hair sphere at c + (0, −0.6, 0) of r 0.5 it
    has r = max(0.890569, 1.1) = 1.1.
  - [4] Broad phase: joint (0,0,0), lever 0.1. A capsule at x = 0.2 with r 0.05 is culled; at x = 0.14 it is kept.
  - [5] `contactAnglePair`:
    - own = max(0, θ − 8°), partner = max(0, 6° − θ), budget 10° → 6.00° ±0.02;
    - own = max(0, θ − 2°), partner = max(0, 6° − θ) → 2.00° ±0.02 (the own body wins);
    - D1 (partner only, depth from `pushOutOfCapsules`, full radius): 5.737° ±0.01; budget 4° → 4°.
  - [6] D7 `releasedAngle` values.
  - [7] Consumer filters on one capsule per region (torso, outer_trunk, chest_hair, shoulder_hair, arm):
    - hair → outer_trunk, chest_hair, shoulder_hair, arm (no torso);
    - extension → outer_trunk, arm;
    - without `outer_trunk` the torso is kept.
- [ ] **Step 2: Run** `node scripts/smoke_partner_rules.mjs`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `partnerContact.ts`.
- [ ] **Step 4: Run** it plus `smoke_docs_scene_render_readme.py`. Expected: PASS.
- [ ] **Step 5: Commit** with the message
  `feat(scene-render): partner selection, consumer filters and the combined contact search`.

### Task 5: Partner contact for hair and extension chains (CPU)

**Files:**
- Modify: `packages/scene-render/src/secondaryMotion.ts`:
  - the contract header gets the bullet "PARTNER CAPSULES": the reader/partner rule, no bind rule, push only, the
    own-wins tie-break, the hysteresis, and the one-frame lag of a partner's extension capsules;
  - `update` options and `contactTips`.
- Create: `scripts/smoke_partner_contact.mjs` (the spec's named smoke).

**Interfaces:**
- Consumes (Task 4): `PartnerSnapshot`, `partnerCapsules`, `broadPhase`, `contactAnglePair`, `releasedAngle`,
  `PARTNER_HYST_M`.
- Produces:
  - `SecondaryMotion.update(realDelta, options?: { frozen?: boolean; far?: boolean; partners?: readonly
    PartnerSnapshot[] })`;
  - `SecondaryMotion.reach(): number` (the longest driven lever, joint to tip, world metres at the current state
    `length`; 0 without links);
  - `contactTips()` rows gain `partner: string[]` (`"<partner>:<capsule id>"`).
- Behaviour:
  - Partner capsules join each link's contact at FULL radius (no bind factor), filtered by consumer (hair or
    extension).
  - The broad phase runs per chain against the chain root.
  - Own and partner capsules go through ONE `contactAnglePair`.
  - A partner capsule that pushed last frame tests with r + `PARTNER_HYST_M`.
  - The applied partner angle falls at most at `PARTNER_RELEASE_DEG_S`.
  - The spring state is never touched.
  - Without `partners`, or with an empty list, the path is today's and allocates nothing.

- [ ] **Step 1: Write the failing test** `smoke_partner_contact.mjs`. Fixture: Hips → `TestLink` joint at the origin,
  lever 0.10 along +x (its tip = the child joint at (0.10, 0, 0)), gravity 0.
  - [1] D1 integrated: the partner snapshot `p` holds capsule `c`, parallel to z through (0.10, −0.02), r 0.03.
    - With `max_deg` 25: after one update the tip has turned 5.737° ±0.02 toward +y, and
      `contactTips()[0].partner` = `['p:c']`.
    - With `max_deg` 4: the turn is 4°, and the tip is 3.02 ±0.02 mm inside.
  - [2] No bind rule: the same capsule with the bind factor wrongly applied would move nothing. Assert that the turn
    exists (that is the spec's assertion).
  - [3] Hysteresis: a tip 0.031 m from the axis of an r 0.03 capsule is not pushed on the first frame. After a frame
    in which that capsule pushed, it is pushed to 0.033.
  - [4] Release: a partner capsule removed after a frame at 10° gives 6° on the next frame at dt 1/60.
  - [5] Consumers:
    - a hair chain (`hair: true`) is pushed by a partner `chest_hair` capsule;
    - an extension chain is not;
    - both are pushed by a partner `outer_trunk` capsule;
    - own `outer_trunk` capsules never push.
  - [6] Inert: `partners: []` and no `partners` give bitwise-identical bone matrices over 60 frames.
  - [7] Own wins: an own capsule and a partner capsule that cannot both be cleared within the budget leave the tip
    outside the own capsule.
- [ ] **Step 2: Run** `node scripts/smoke_partner_contact.mjs`. Expected: FAIL (no partner option).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus `smoke_extension_collision.mjs`, `smoke_hair_chain_contact.mjs` and
  `smoke_collision_squeeze.mjs`. Expected: PASS.
- [ ] **Step 5: Commit** with the message
  `feat(secondary-motion): hair and extension chains are pushed out of partner capsules`.

### Task 6: GPU partner push of hair meshes and strand partners

**Files:**
- Modify: `packages/scene-render/src/garmentCollision.ts`:
  - the partner block under `#ifdef COLLIDE_PARTNER` (hair kind only): `uniform vec4 partnerA[
    PARTNER_COLLIDE_MAX ]`, `partnerB[…]`, `uniform int partnerCount`, `#define COLLIDE_PARTNER_PUSH_MAX`;
  - `PushOptions.partners` in the TS twin;
  - `GarmentCollision.setPartners`;
  - the docstring "PARTNERS (hair only)", which states that no other garment kind uses the block.
- Modify: `packages/scene-render/src/hairSim.ts` (`StrandHair.setPartners`).
- Create: `scripts/smoke_partner_hair_push.mjs`. Modify: `scripts/smoke_garment_collision.mjs` (twin equality with
  partners).

**Interfaces:**
- Consumes: `nearestCapsules`, `PARTNER_COLLIDE_MAX`, `PARTNER_PUSH_MAX_M` (Task 4); `PushOptions` (Task 3).
- Produces:
  - `GarmentCollision.setPartners(capsules: readonly CapsuleNow[] | null): void`: world space. In each hair mesh's
    `onBeforeRender`/`onBeforeShadow`, the `PARTNER_COLLIDE_MAX` nearest capsules to the mesh's world bounding sphere
    go into the mesh's frame. Only `partnerCount` changes: no recompile, and `customProgramCacheKey` is unchanged.
  - `StrandHair.setPartners(capsules: readonly CapsuleNow[] | null): void`: appends up to `PARTNER_COLLIDE_MAX`
    nearest capsules, without `bind`, to the sim's frame capsules (ruling R1).
- Push order in each pass: partner capsules first, then own. A partner radius is r' = d + (r − d)·f, with
  f = clamp((1.5M − depth)/(0.5M), 0, 1) (D7). Squeeze sets include partner capsules with f > 0.

- [ ] **Step 1: Write the failing test** `smoke_partner_hair_push.mjs`:
  - [1] D7 fade at d = 0.08, 0.05 and 0.03, in TS and in the GLSL run.
  - [2] Own wins: own sphere at (0.2, 0, 0) with r 0.12, partner sphere at the origin with r 0.10, point (0.09, 0, 0)
    → (0.08, 0, 0) with or without squeeze (degenerate).
  - [3] 12 partner capsules: the uniform holds the 8 nearest by `nearestCapsules`, and `partnerCount` is 8. Switching
    from 8 to 3 keeps the material's program cache key.
  - [4] A cloth garment has no `COLLIDE_PARTNER` define and its `setPartners` changes nothing.
  - [5] `dispose()` frees exactly the clones it made, partner uniforms included (the strand-hair smoke's counting
    pattern).
  - [6] A strand sim with `setPartners([sphere])` keeps its rows outside that sphere (pinned rows excepted) after 30
    steps, and does not without it.
- [ ] **Step 2: Run** `node scripts/smoke_partner_hair_push.mjs`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus `smoke_garment_collision.mjs`, `smoke_collision_squeeze.mjs`,
  `smoke_strand_hair_handle.mjs` and `smoke_hair_sim.mjs`. Expected: PASS.
- [ ] **Step 5: Commit** with the message
  `feat(garment-collision): hair meshes and strands are pushed out of partner capsules`.

### Task 7: The client's two-phase figure frame

**Files:**
- Create: `client3d/src/scene/partnerFrame.ts`.
- Modify: `client3d/src/scene/figures.ts`:
  - `update` = phase A, recording `pendingSecondary`;
  - the strand step and `secondary.update` move into `updateSecondary`;
  - a partner binding, dropped in `retireModels`/`dispose`.
- Modify: `client3d/src/scene/npcs.ts`:
  - `PairPlay` gets `kind: string` and `members: string[]` from `MapInteraction`;
  - `tick()` ends with `this.tickSecondary()`.
- Modify: `client3d/src/figureTest.ts` (calls `figure.updateSecondary([])` after `update`).
- Modify: `CLAUDE.md`. Add one sentence to the 3D-models paragraph: the two-phase frame exists so that partners are
  read on final poses, and secondary motion must never move back into `Figure.update`.
- Create: `scripts/smoke_partner_frame.mjs`.

**Interfaces:**
- Consumes: `bodySphere`, `reachSphere`, `selectPartners`, `snapshotPartner`, `PARTNER_PREFILTER_SLACK_M` (Task 4);
  `SecondaryMotion.update({partners})` and `reach()` (Task 5); `GarmentCollision.setPartners` and
  `StrandHair.setPartners` (Task 6).
- Produces, in `partnerFrame.ts`:
  - `interface FrameFigure { name: string; root: Vec3; bindRadius: number; reader: boolean; lever: number;
    members: readonly string[]; body(): Sphere | null; reach(): Sphere | null }`;
  - `planPartnerFrame(figures: readonly FrameFigure[], max = PARTNER_MAX): Map<string, string[]>`.
    - Prefilter: |root_r − root_p| ≤ bindRadius_r + lever_r + bindRadius_p + `PARTNER_PREFILTER_SLACK_M`.
    - `body()`/`reach()` are called ONLY for prefiltered pairs. A non-reader gets no entry. A reader without a
      candidate gets [].
- Produces, on `Figure`:
  - `updateSecondary(partners: readonly PartnerSnapshot[]): void`: a no-op without a pending phase A;
  - `frameFigure(): FrameFigure | null` (null without a collision payload);
  - `partnerSnapshot(interaction: { id: string; kind: string } | null): PartnerSnapshot | null`: binds lazily on the
    current instance, and returns null for a payload `bindCollision` refuses;
  - `setGpuPartners(capsules: readonly CapsuleNow[] | null): void`.
- `NpcManager.tickSecondary()`:
  1. plan;
  2. snapshot every selected partner ONCE, before any solve;
  3. `updateSecondary` for each pending figure;
  4. re-`update()` the partner bindings of figures selected by a hair-mesh reader;
  5. `setGpuPartners` with those (zero lag at render).

- [ ] **Step 1: Write the failing test** `smoke_partner_frame.mjs` (esbuild bundle of `partnerFrame.ts` + `figures.ts`,
  using the figure fixture of `smoke_client_strand_wiring.mjs`):
  - [1] `planPartnerFrame` on D6 positions gives `m, a, b, c` for the reader. A figure 30 m away never has `body()`
    called (spy counter 0).
  - [2] Phase A: after `figure.update(dt)` the driven bone matrices equal the pose before secondary. After
    `updateSecondary([])` they equal what the single `update` of BASE produced: bitwise, same fixture and dt, with
    BASE's `figures.ts` bundled from a worktree at the ledger's BASE hash.
  - [3] Order independence: two hair-chain figures 0.3 m apart. Visiting them A→B and B→A in phase B gives bitwise
    equal matrices.
  - [4] A lone reader and a far-tier reader take no snapshot and do no `bindCollision` (spies).
  - [5] Review Focus 3: after a model swap (`retireModels`), the next `partnerSnapshot` binds on the new instance. Its
    capsules' meshes are descendants of the live root, and a payload of version 5 gives null (the partner is skipped)
    without throwing.
  - [6] Frozen and `update(0, {frozen: true})` (the photo-held path) still run phase B with `frozen`.
- [ ] **Step 2: Run** `node scripts/smoke_partner_frame.mjs`. Expected: FAIL.
- [ ] **Step 3: Implement.** `PairPlay.members`/`kind` are taken in `adoptInteraction` (npcs.ts ~1374–1420).
- [ ] **Step 4: Run** it plus `smoke_client_strand_wiring.mjs`, `npm run build -w client3d` and
  `./.venv/bin/python scripts/smoke_docs_claude_md.py`. Expected: PASS.
- [ ] **Step 5: Build `static/client3d/` and commit** with the message
  `feat(client3d): a two-phase figure frame — secondary motion reads partner snapshots on final poses`. CLAUDE.md is
  gitignored, so it is not part of the commit; record the edit in the ledger.

### Task 8: Admin viewer partner probe

**Files:**
- Modify: `app/core/collision.py` (`bind_pose_capsules`).
- Modify: `app/routes/characters.py` (`GET /{character_name}/model3d/collision/bind-pose`).
- Create: `packages/scene-render/src/partnerProbe.ts`; export it and list it in the README.
- Create: `frontend/src/tabs/characters/PartnerProbeControls.tsx`.
- Modify: `frontend/src/tabs/characters/Model3DViewer.tsx`: the toggle "Partner probe"; the probe wireframes in the
  partner colour; `secondary.update({partners:[probe]})`; `garmentCollision.setPartners`; the contact readout lists
  `partner`.
- Modify: `shared/languages/de.json`.
- Test: `scripts/smoke_collision_capsules.py` [11], `scripts/smoke_partner_probe.mjs`, `scripts/check_model3d_ui.mjs`
  (headless screenshot).

**Interfaces:**
- Produces:
  - `collision.bind_pose_capsules(rigged_glb: bytes, record: dict) -> List[dict]`: each entry is
    `{id, region, a: [x,y,z], b: [x,y,z], r}`, the endpoints resolved in bind space (a joint = its bind position;
    `a_pos`/`b_pos` as given).
  - The route returns `{signature, capsules}` for the served full-tier model. It has `Depends(require_admin)`, 404
    without a record, and makes no write.
  - `probeCapsules(capsules: readonly { id: string; region: string; a: Vec3; b: Vec3; r: number }[], pose: { x: number;
    z: number; yaw: number }, mirror: boolean): PartnerCapsule[]` (mirror = x → −x, then yaw about +y, then
    translate).
  - `probeSweepOffset(t: number, speed: number, span: number): number` (a triangle wave in [−span, span] along the
    probe's facing).
  - The probe snapshot is `{name: 'probe', capsules, channels: [], interaction: null}`.
- Sources: "This body, mirrored" uses `BoundCapsule.bind` of the shown model. "Another character" uses the route.
  Controls: x/z in metres, yaw in degrees, Sweep on/off, speed (m/s), span (m). The controls sit beside the viewer and
  apply live (checklist 4). A metre value is shown against the figure itself and the viewer grid (checklist 7).

- [ ] **Step 1: Write the failing tests.**
  - [11] `bind_pose_capsules` on the fixture: `left_thigh` a (0.1, 0.95, 0), b (0.1, 0.5, 0); `head` b = its
    `b_pos`.
  - The route: 403 for a player and 200 for an admin (a TestClient with the temp storage of `smoke_auth_gate.py`'s
    pattern).
  - `smoke_partner_probe.mjs`: a capsule (0.1,0,0)→(0.1,1,0) mirrored → x −0.1. Yaw 90° with pose (1, 0, 2) puts its
    `a` at (1, 0, 2.1) (three's +y rotation maps +x to −z; mirrored −0.1 maps to +0.1 z).
    `probeSweepOffset`: speed 0.5, span 0.6 gives 0, 0.3, 0.6, 0.3, 0, −0.3 at t = 0, 0.6, 1.2, 1.8, 2.4, 3.0.
- [ ] **Step 2: Run** both smokes. Expected: FAIL.
- [ ] **Step 3: Implement** the server function, route, module, controls and viewer wiring. Every wireframe the probe
  draws is in the viewer's `disposers`.
- [ ] **Step 4: Run** the smokes, `cd frontend && npm run build`, `npm run lint`, and
  `node scripts/check_model3d_ui.mjs` with a fixture model. Save the screenshot to
  `~/claude-out/cross-person/ui/probe.png`, with the probe crossing the hair. Expected: PASS, and the readout lists
  `probe:<id>`.
- [ ] **Step 5: Build `static/game_admin/` and commit** with the message
  `feat(game-admin): a partner probe in the model viewer`.

### Task 9: Measurement check and the stage-1 contract

**Files:**
- Create: `scripts/check_partner_collision.mjs`.
- Modify: `docs/schnittstellen-3d.md` "Collision capsules": the subsection "Partner contact (cross-person)" (the
  selection rule, the two-phase frame, the consumer table with `outer_trunk`, the Part 3 rules, the squeeze, version
  6). Also the constants' doc comments with their final values.

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces:
  - `check_partner_collision.mjs --a <glb> --b <glb> --clip-a <clip> --clip-b <clip> [--sweep m/s] [--frames n]`,
    reading the COPIES under `~/claude-out/cross-person/check/`;
  - Output, per side with contact off/on:
    - hair vertices' depth inside the partner's capsules (p50/p90/max mm);
    - extension tip depth;
    - jitter = the frame-to-frame tip delta (p95 mm) against a constant-speed probe sweep;
    - ms per reader per frame (`performance.now`, and `game/perfstats.ts` naming).

- [ ] **Step 1: Copy** two stored models (one with HairDeck chains, one with an extension group) and one pair clip's
  two halves from the test-world clone. Record their sha256 values.
- [ ] **Step 2: Run** the check with the starting constants. Record the numbers.
- [ ] **Step 3: Tune.**
  - `PARTNER_HYST_M` and `PARTNER_RELEASE_DEG_S`: the smallest values whose jitter p95 is ≤ 1 mm at a 0.5 m/s sweep.
  - `PARTNER_PUSH_MAX_M`: the smallest value whose max hair depth inside the partner on the pair clip is no worse than
    the 0.04 m run.
  - `PARTNER_MAX` and `PARTNER_COLLIDE_MAX` stay unless the budget is broken.
  - The budget: ≤ 0.1 ms per reader per frame with four partners, and 0.00 ms added for a lone figure.
  - Re-run the smokes the constants touch: `smoke_partner_rules`, `smoke_partner_contact` and
    `smoke_partner_hair_push`. D1 and D3 are constant-free; D7 names M, so update D7 in its docstring if M changes.
- [ ] **Step 4: Write** the contract subsection. Run `./.venv/bin/python scripts/smoke_docs_schnittstellen_3d.py`.
  Expected: PASS.
- [ ] **Step 5: Rebuild the bundles if a constant changed, and commit** with the message
  `docs(3d): partner contact contract; check script and measured partner constants`.

## Stage 2 — channels (G3)

### Task 10: Region declarations and the op on motion groups

**Files:**
- Modify: `app/plugins/registry.py` (`RegionSpec`, `BodySlotSpec.regions`).
- Modify: `app/plugins/loader.py`: parse `regions:` after `rigs`. A malformed region logs an error and rejects the
  package (ruling R3).
- Modify: `app/core/extension_rig.py`:
  - extract the slot-condition match of `rig_groups_for` into `_rule_applies(slot, rule, values, profile,
    template_name, template, active_slots) -> bool`, used by both;
  - add `region_declarations_for`;
  - `motion_payload` groups get `"op"` (package groups only).
- Modify: `packages/scene-render/src/secondaryMotion.ts` (`MotionGroup.op?: string`).
- Create: `scripts/smoke_region_declarations.py`.

**Interfaces:**
- Produces:
  - `@dataclass RegionSpec(id: str, kind: str, bone: str, offset: List[float], axis: List[float], depth: float,
    radius: float, cone_deg: float, funnel: float, accepts_ops: List[str], min_length: float = 1.0,
    compress_min: float = 1.0, exposed_only: bool = True, interaction_kinds: Optional[List[str]] = None,
    from_rig: Optional[str] = None, templates: Any = None, applies_to: Dict[str, List[Any]] = {},
    attribute_params: Dict[str, Dict[str, Any]] = {})`.
  - `RegionSpec.parse(raw, attributes, rig_ids) -> RegionSpec`, which requires:
    - `kind == "channel"`;
    - `bone` a `BASE_JOINT_KEYS` joint;
    - `offset`/`axis` three finite numbers, the axis non-zero;
    - `depth`, `radius`, `funnel` finite and > 0;
    - `cone_deg` in (0, 60];
    - `accepts.ops` a non-empty list of non-empty strings;
    - `min_length` in [0.25, 4], `compress_min` in (0, 1];
    - `from_rig` ∈ `rig_ids`;
    - `attribute_params` keys ⊆ {radius, depth}, each `{attribute, values}` with declared options and finite
      positive numbers;
    - `templates`/`applies_to` by the rig rules.
  - `extension_rig.region_declarations_for(character_name: str, profile: Optional[dict] = None) -> List[dict]`: each
    entry is `{id: "<package>:<id>", slot, bone, offset, axis, depth, radius, cone_deg, funnel, accepts, min_length,
    compress_min, exposed_only, interaction_kinds, from_rig, covered_by}`, with radius/depth already multiplied by the
    attribute values. Exposure is NOT decided here (Task 12).
  - Motion groups carry `op` (the effective op, so `attached_part` where the mesh part turns the chain into one).

- [ ] **Step 1: Write the failing test** `smoke_region_declarations.py` (a temp package `pkgx` in a temp `plugins/`
  dir, neutral ids):
  - [1] A valid channel parses; `id` resolves to `pkgx:chan`.
  - [2] Each invalid field rejects the package (`discover_packages` result lacks `pkgx`, one error logged):
    `kind: tube`, `cone_deg` 0 / 61, `depth` −1, `accepts.ops` [], `bone: Nope`, `from_rig` not in the slot.
  - [3] `region_declarations_for` honours `templates`/`applies_to` like a rig.
  - [4] `attribute_params` radius {size: {s: 0.8, l: 1.2}} with slot value `l` gives radius × 1.2.
  - [5] `motion_payload` groups carry `op` (`appendage_chain` for a chain, `attached_part` with the mesh part on).
    Hair groups carry none.
- [ ] **Step 2: Run** `./.venv/bin/python scripts/smoke_region_declarations.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus `smoke_hair_motion_payload.py`, `smoke_motion_clothing_lift.py`,
  `smoke_plugin_private_imports.py` and `smoke_imports_resolve.py`. Expected: PASS.
- [ ] **Step 5: Commit** with the message
  `feat(plugins): body slots may declare channel regions; motion groups carry their op`.

### Task 11: The `inset_part` op reports its `opening` (core)

**Files:**
- Modify: `app/blender/scripts/inset_part.py`. Add `_gltf(v)` and the pure `opening_metric(prof, pn, S, s_mid, xm, Mi,
  Ni3)`. `build_part` returns `opening`.
- Modify: `scripts/smoke_inset_part_blender.py` (assert D5) and `scripts/smoke_inset_part_parameters.py` (an AST check
  of `opening_metric` on a synthetic profile).

**Interfaces:**
- Produces: the metric `"opening": {"centre": [x, y, z], "axis": [x, y, z]}`, in glTF bind space (the body's POSITION
  space).
  - `centre` = the undisplaced chart midline point at s = (`pocket.s0` + `pocket.s1`)/2 (`np.interp` over `S`, x =
    `xm`).
  - `axis` = the unit inward surface normal there (−`pn` interpolated).
  - Both go through `Mi` / `Ni3`, then (x, z, −y).
  - It is stored with the other metrics in `extension_rig.metrics[<group>]`.
  - No `PART_BUILDS` bump (ruling R9). A model built earlier has no `opening`.

- [ ] **Step 1: Write the failing tests.**
  - `smoke_inset_part_parameters.py`: `opening_metric` on a 3-point synthetic profile with identity matrices returns
    the interpolated point, with y/z swapped and sign-flipped.
  - `smoke_inset_part_blender.py` (round sphere): centre (0, 0.870627, 0.013706) ±2 mm; axis (0, 0.995817, −0.091372)
    within 1°; |axis| = 1 ±1e-6.
- [ ] **Step 2: Run** both. Expected: FAIL (no `opening`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both, plus `smoke_inset_part_pipeline.py`. Expected: PASS.
- [ ] **Step 5: Commit** with the message
  `feat(inset-part): the op reports its opening (centre and inward axis in bind space)`.

### Task 12: Server channel resolution (collision v7)

**Files:**
- Create: `app/core/collision_channels.py`.
- Modify: `app/core/collision.py`:
  - `VERSION` 7;
  - the docstring paragraphs "PARTNER CONTACT" (no payload change) and "CHANNELS (version 7)";
  - `refresh` / `ensure_path` / `ensure` / `recompute_character` resolve channels;
  - `channels_current`;
  - relabel filters by exposure.
- Modify: `app/core/model3d.py` (option `collision_channels`, validated by `collision_channels.validate_overrides`).
- Modify: `app/routes/characters.py`: `POST /{c}/model3d/collision/channels` stores only and returns
  `{channels, due}`; the existing `POST …/collision` passes `apply_channels=True`.
- Modify: `app/routes/figure.py` (`collision_channels`, `channel_declarations`).
- Modify: `app/core/model_overview.py` (the collision step says "due" with a reason when channels are not current).
- Modify: `app/core/improvements/types/collision_capsules.py` (`is_done` also needs `channels_current`; `apply` uses
  `apply_channels=True`).
- Modify: `packages/scene-render/src/collision.ts`:
  - `COLLISION_VERSION = 7`;
  - `CollisionPayload.channels?: ChannelRecord[]` and `channels_sig?: string`;
  - type `ChannelRecord` (the record below);
  - type `ChannelOverride { offset_mm: [number, number, number]; radius_scale: number; depth_scale: number;
    cone_deg: number }`.
- Create: `scripts/smoke_collision_channels.py`. Modify: `scripts/smoke_collision_capsules.py` (the version);
  `scripts/smoke_collision_scales_route.py`.

**Interfaces:**
- Consumes: `region_declarations_for` (Task 10); `extension_rig.metrics[rig].opening` (Task 11);
  `extension_rig.hides_exposed_detail`.
- Produces, in `collision_channels`:
  - `body_frame(joints: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]`:
    - `up` = unit(Head − Hips);
    - `side` = unit of (LeftArm − RightArm) with its component along `up` removed;
    - `front` = side × up, flipped if its dot with (LeftToeBase − LeftFoot) is < 0;
    - ValueError if a joint is missing.
  - `validate_overrides(raw: Any) -> Dict[str, Dict[str, Any]]`:
    - per channel id `{offset_mm: [side, up, front] each in [−50, 50], radius_scale in [0.5, 2], depth_scale in
      [0.5, 2], cone_deg in (0, 60]}`;
    - ValueError otherwise;
    - unknown ids are kept (the declaration may come back).
  - `character_overrides(character_name, *, profile=None) -> dict`.
  - `wanted_channels(character_name: str, path: Path, meta: dict, *, profile=None) -> Tuple[List[dict], str]`: the
    applicable declarations with resolved attributes, overrides and the opening, plus `channels_sig` =
    sha256(json(that list)). Exposure is NOT in the sig.
  - `resolve_channels(rigged_glb: bytes, capsules: List[dict], wanted: List[dict], *, exposed: Callable[[dict], bool])
    -> Tuple[List[dict], List[dict]]` returns `(channels, skipped)`. One record per exposed channel:
    `{id, kind:"channel", a, b, a_pos, b_pos, r, cone_deg, funnel, accepts, min_length, compress_min,
    interaction_kinds?, suppress, frame: {side, up, front}, placement: "rig"|"declared", applied: <override>}`.
    - `a` = `b` = the owning joint name as in the model.
    - `a_pos` = opening (rig) or joint + offset, plus `offset_mm`/1000 along the frame axes.
    - `b_pos` = `a_pos` + unit(axis)·depth·`depth_scale`; `r` = radius·`radius_scale`.
    - `suppress` = the capsule ids whose bind-pose segment comes within r_capsule + r of the channel segment
      `a_pos`→`b_pos`, plus every capsule whose `a` is the owning joint. Ordered as in the payload.
- Produces, in `collision`:
  - `channels_current(record: Any, channels_sig: str) -> bool`;
  - `ensure_path(character_name, path, *, scales=None, force=False, apply_channels=False)`. A record whose capsules are
    current but whose `channels_sig` differs is returned UNCHANGED unless `apply_channels` or `force` is set (ruling
    R4). Any capsule refit resolves channels too.
  - The relabel path (an inherited record) re-filters `channels` by THIS model's exposure. An exposed check is a
    `hides_exposed_detail([{exposed_only, covered_by}], meta.pieces, items)` per channel; a base model is exposed.
- Route: `POST /{c}/model3d/collision/channels` with body `{channels: {<id>: override}}`, `Depends(require_admin)`.
  It returns `{channels: stored, due: bool}`. It never fits.

- [ ] **Step 1: Write the failing test** `smoke_collision_channels.py`. The fixture body of `smoke_collision_capsules`
  plus `LeftToeBase`, a temp package declaring `pkgx:chan`: bone Hips, offset [0, −0.10, 0.05], axis [0, 1, 0], depth
  0.12, radius 0.02, cone 30, funnel 0.03, accepts [appendage_chain].
  - [1] `body_frame`: up (0,1,0), side (1,0,0), front (0,0,1).
  - [2] Declared placement:
    - `a_pos` = Hips (0, 1.0, 0) + (0, −0.10, 0.05) = (0, 0.90, 0.05);
    - `b_pos` = (0, 1.02, 0.05), r 0.02;
    - `suppress` = [hips, outer_hips] in payload order. Both start at Hips (the owning-joint rule), and the hips axis
      also lies 0.05 < 0.1 + 0.02 from the channel segment.
    - These are NOT listed:
      - `spine` / `outer_spine`: their closest point (0, 1.2, 0) lies sqrt(0.18² + 0.05²) = 0.186815 from the
        channel top, more than 0.1005 + 0.02;
      - the thighs: their axis at x = ±0.1, z = 0 overlaps the channel's y range at sqrt(0.1² + 0.05²) = 0.111803,
        more than 0.066 + 0.02.
  - [3] Rig placement: a sidecar metric `opening {centre [0, 0.88, 0.02], axis [0, 2, 0]}` gives `a_pos`
    (0, 0.88, 0.02), `b_pos` (0, 1.00, 0.02), `placement "rig"`.
  - [4] Override `{offset_mm [0, 10, −5], radius_scale 1.5, depth_scale 0.5, cone_deg 20}` gives `a_pos`
    (0, 0.91, 0.045), `b_pos` (0, 0.97, 0.045), r 0.03, cone 20.
  - [5] Review Focus 2: an outfit model whose `pieces` cover the slot inherits the base record (current capsules) and
    gets `channels == []`. The same outfit with `exposed_detail` keeps the channel.
  - [6] Review Focus 5: store an override through the route, then call `collision.ensure` (the poll). The record is
    unchanged, the overview step status is "due" with the reason "Channel settings changed — recompute to apply", and
    the Improvements `is_done` is False. `POST …/collision` then applies it and makes the step current.
  - [7] `validate_overrides` refuses 51 mm, `radius_scale` 0.4, `cone_deg` 0, and a non-dict.
  - [8] The payload version is 7. A record of version 6 is refitted on read (system staleness), channels included.
- [ ] **Step 2: Run** `./.venv/bin/python scripts/smoke_collision_channels.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Set `COLLISION_VERSION = 7` and the TS types.
- [ ] **Step 4: Run** it plus the collision smokes of Task 1 Step 6 and `smoke_auth_gate.py`. Expected: PASS.
- [ ] **Step 5: Build both bundles and commit** with the message
  `feat(collision): declared channels resolved into bind space (collision v7)`.

### Task 13: The shared guidance rule (`channels.ts`)

**Files:**
- Create: `packages/scene-render/src/channels.ts`; export it and list it in the README.
- Modify: `packages/scene-render/src/collision.ts` (`CAPSULE_REGION_COLORS.channel`, `.partner`).
- Modify: `packages/scene-render/src/partnerContact.ts` (`ChannelNow` is imported from `channels.ts`).
- Create: `scripts/smoke_channel_guidance.mjs` (the spec's named smoke).

**Interfaces:**
- Produces:
  - `interface ChannelNow { id: string; o: Vec3; u: Vec3; depth: number; r: number; coneDeg: number; funnel: number;
    accepts: readonly string[]; minLength: number; compressMin: number; kinds: readonly string[] | null;
    suppress: ReadonlySet<string> }`;
  - `bindChannels(three: Three, root: Object3D, payload: CollisionPayload | null | undefined): { channels: ChannelNow[];
    update(): void } | null` (the endpoint rule of `collision.ts`; r scales with `linearScale`);
  - `channelCoords(p: Vec3, ch: ChannelNow): { s: number; rho: number }`;
  - `inZone(s: number, rho: number, ch: ChannelNow, grow?: { h: number }): 'cylinder' | 'funnel' | null`;
  - `allowedRadius(s: number, ch: ChannelNow, rC: number): number`:
    - C: max(0, R − r_c);
    - Φ: max(0, R + (−s)·tan α − r_c);
  - `radialGuidanceAngle(joint: Vec3, tip: Vec3, ch: ChannelNow, rC: number): { angle: number; axis: Vec3 } | null`:
    the smallest turn about the joint, in the plane of the lever and the radial direction, that makes ρ = R';
  - `depthScale(sTip: number, sE: number, ch: ChannelNow, rC: number): number`:
    k = max(compressMin, (D − r_c − s_e)/(s_tip − s_e)) when s_tip > D − r_c, else 1;
  - `interface Engagement { engaged: boolean; w: number }`;
  - `stepEngagement(prev: Engagement, input: { gate: boolean; tipInZone: boolean; tipInGrownZone: boolean;
    leverAngleDeg: number }, ch: ChannelNow, dt: number): Engagement`:
    - engage when gate && tipInZone && leverAngle ≤ α;
    - release when !gate or !tipInGrownZone (grown by h = `CHANNEL_HYST_M` and δ = `CHANNEL_HYST_DEG`);
    - w ramps by dt/`CHANNEL_BLEND_S`;
  - `channelGate(group: { op?: string; length: number }, ch: ChannelNow, reader: { interaction: { id: string } | null },
    partner: PartnerSnapshot): boolean`:
    - accepted op;
    - length ≥ minLength;
    - the same interaction id;
    - kind ∈ kinds when kinds is set;
  - `suppressedIds(tip: Vec3, ch: ChannelNow): ReadonlySet<string>` (the record's set inside C; empty elsewhere);
  - `guideRod(ch: ChannelNow, rod: { length: number; radius: number; links: number; insertion: number;
    tiltDeg: number; budgetDeg: number }): { joints: Vec3[]; turnsDeg: number[]; k: number; pastBottomM: number;
    suppressed: string[] }` (the admin test rod, root to tip, w = 1);
  - `channelWireframe(three: Three, ch: ChannelNow, color: number): LineSegments` and
    `placeChannelWireframe(three, line, ch)` (cylinder + funnel cone; owns its geometry and material);
  - `previewChannel(record: ChannelRecord, applied: ChannelOverride, draft: ChannelOverride): ChannelRecord`:
    - shifts `a_pos`/`b_pos` by (draft − applied)·mm along `frame`;
    - scales r by `draft.radius_scale/applied.radius_scale`;
    - scales the depth along the axis by the depth-scale ratio;
    - replaces `cone_deg`;
  - the constants `CHANNEL_BLEND_S`, `CHANNEL_HYST_M` and `CHANNEL_HYST_DEG`.

- [ ] **Step 1: Write the failing test** `smoke_channel_guidance.mjs` with the spec's cases (D2: O = origin, u = +z,
  R 0.02, D 0.12, α 30°):
  - [1] Joint (0, 0, −0.05), tip (0.03, 0, 0.05): lever 0.104403, 16.699° from u. The turn is 5.655° ±0.005, and the
    tip ends at s = 0.05247 ±1e-5.
  - [2] r_c 0.005: guided angle 8.260°, turn 8.439°.
  - [3] Budget 4°: the caller's cap gives 4°, and the tip keeps ρ > R.
  - [4] Depth, s_e = 0:
    - s_tip 0.15 with `compress_min` 0.8 gives k = 0.8, tip at 0.12;
    - s_tip 0.16 gives k = 0.8, tip at 0.128, so 8 mm stays past the bottom;
    - `compress_min` 1.0 gives k = 1.
  - [5] Funnel: `allowedRadius(−0.02)` = 0.031547 ±1e-6.
  - [6] Hysteresis: engaged and leaving C to ρ 0.023 stays engaged; at ρ 0.026 it releases.
  - [7] Blend: from engage, w reaches 0.5 after 0.1 s and 1 after 0.2 s. A release from w = 1 reaches 0 after 0.2 s
    and never jumps.
  - [8] Suppression: a tip in C at (0, 0, 0.05) gives `suppress`. At s = −0.01 it gives the empty set.
  - [9] Gate:
    - a wrong op is false;
    - length 0.9 with min 1.0 is false;
    - another interaction id is false;
    - kinds ['k1'] with kind 'k2' is false;
    - all matching is true.
  - [10] `guideRod`: 1 link, length 0.15, radius 0, tilt 0, insertion 0.15 (root at s = 0, so s_e = 0) with
    `compress_min` 0.8 gives k 0.8, the tip at 0.12, and `pastBottomM` 0.
  - [11] `previewChannel`: `offset_mm` +10 up moves `a_pos` +0.01 along `frame.up`.
  - [12] `bindChannels` on a one-joint figure moved by (1, 0, 0) gives o = `a_pos` + (1, 0, 0) and depth = |b_pos −
    a_pos|.
- [ ] **Step 2: Run** `node scripts/smoke_channel_guidance.mjs`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus `smoke_docs_scene_render_readme.py`. Expected: PASS.
- [ ] **Step 5: Commit** with the message
  `feat(scene-render): the channel guidance rule — radial clamp, depth scale, engagement, suppression`.

### Task 14: Engagement in the solver and the client

**Files:**
- Modify: `packages/scene-render/src/secondaryMotion.ts`:
  - per entering chain and partner channel: the gate, engagement and w;
  - per link, after its dynamics: the radial guidance turn (× w, within the swing budget), then the contact turn with
    the `suppress` ids taken out of THAT partner's capsules while the tip is in C;
  - after the chain's last link: the depth scale k (blended 1 → k by w), applied to the levers of the links inside C,
    re-published in the same frame;
  - `contactTips` rows get `channel?: { id: string; w: number; k: number }`;
  - the contract header bullet "CHANNELS".
- Modify: `client3d/src/scene/figures.ts` (`partnerSnapshot` includes `bindChannels` output) and `npcs.ts` (the
  snapshot carries `{id, kind}` of the figure's `PairPlay`; the reader passes its own interaction).
- Modify: `scripts/check_partner_collision.mjs`: `--channels` reports the engaged time share, the ρ excess p95 and
  the past-bottom max.
- Create: `scripts/smoke_channel_engagement.mjs`.

**Interfaces:**
- Consumes: Task 13 (all of it); `MotionGroup.op`/`length` (Task 10); `PartnerSnapshot.channels`/`interaction`;
  `PairPlay.kind`/`members` (Task 7).
- Produces: `SecondaryMotion.update(realDelta, { frozen?, far?, partners?, interaction?: { id: string } | null })`.

- [ ] **Step 1: Write the failing test** `smoke_channel_engagement.mjs`. Fixture: a 3-link `appendage_chain` reader
  (op `appendage_chain`, length 1.0) and a partner snapshot with one channel (D2 geometry, moved so the funnel faces
  the chain), with the shared interaction `{id: 'i1', kind: 'k'}`.
  - [1] The chain advances into the funnel over 30 frames: it engages, `contactTips` names the channel, w reaches 1
    within `CHANNEL_BLEND_S`, and no link tip ends with ρ > R' + 1 mm while w = 1.
  - [2] Suppression: the partner's capsule listed in `suppress` does not push a tip inside C. An unlisted partner
    capsule still pushes.
  - [3] The reader's OWN channel (on its own payload) never engages.
  - [4] Review Focus 4: the interaction is removed (`interaction: null`) while engaged. w falls linearly to 0 over
    0.2 s, the per-frame tip delta stays ≤ the delta of the free swing + 1 mm, and k returns to 1.
  - [5] No interaction from the start, or length 0.9 < `min_length`: never engaged. The partner push then applies
    normally (the passer-by rule).
  - [6] A growing state `length` 1.0 → 1.4 while engaged: the tip's s stays ≤ D − r_c + (what `compress_min` cannot
    absorb), never folds, and the swing state is untouched (velocities unchanged).
- [ ] **Step 2: Run** `node scripts/smoke_channel_engagement.mjs`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus `smoke_partner_contact.mjs`, `smoke_partner_frame.mjs`, `smoke_extension_collision.mjs`
  and `npm run build -w client3d`. Then run `check_partner_collision.mjs --channels` on the copies with a synthetic
  channel added to copy B's payload (neutral id). Record the numbers in the ledger.
- [ ] **Step 5: Build `static/client3d/` and commit** with the message
  `feat(secondary-motion): chains enter declared channels inside a running pair interaction`.

### Task 15: Admin viewer channels and the Channels panel

**Files:**
- Create: `frontend/src/tabs/characters/CollisionChannels.tsx`, `frontend/src/tabs/characters/ChannelRodControls.tsx`.
- Modify: `frontend/src/tabs/characters/Model3DViewer.tsx` (the toggle "Channels" draws `channelWireframe` per channel;
  the toggle "Test rod" draws `guideRod` live with the suppressed capsules highlighted; both are in `disposers`).
- Modify: `frontend/src/tabs/characters/FieldBaseBody.tsx` and `FieldModel3D.tsx` (the panel beside
  `CollisionScales`).
- Modify: `shared/languages/de.json`.
- Modify: `scripts/check_base_body_ui.mjs` (fixture channel; screenshots).

**Interfaces:**
- Consumes: the route `POST …/model3d/collision/channels` and the figure info `collision_channels` /
  `channel_declarations` (Task 12); `previewChannel`, `guideRod`, `channelWireframe` and `bindChannels` (Task 13).
- Produces: `CollisionChannels({ character, collision, overrides, declarations, disabled, onPreview, onSaved })`.
  - It has the same preview contract as `CollisionScales`: `onPreview(payload)` hands the viewer a payload whose
    channels are `previewChannel` drafts.
  - Per channel: offset Side / Up / Front (mm, −50…50), Radius scale, Depth scale (0.5–2) and Cone (°).
  - Save stores only. The panel then shows the collision step's light and reason from the figure info ("Channel
    settings changed — recompute to apply") and a link to the step button "Recompute collision capsules" (0 jobs).
  - `ChannelRodControls`: channel picker, length (m), radius (m), links, insertion (m along the axis), tilt (°) and
    the readout: turn per link (°), k, past bottom (mm), suppressed ids, w.

- [ ] **Step 1: Copy the 10-point checklist** into the task brief verbatim. Each point is ticked with evidence in
  `~/claude-out/cross-person/ui/checklist.md`:
  1. **Run-all + single steps:** the Figure tab's whole flow runs the collision step and skips it when current, with
     the job count shown ("0 jobs", "Everything is current" at 0). The single step "Recompute collision capsules"
     also redoes a current one.
  2. **Save ≠ execute:** Save stores only. What is due next shows beside it.
  3. **Only current flows:** no legacy buttons, and no buttons of foreign flows (at most a link).
  4. **Settings beside the viewer:** compact and live while dragging (`onPreview`). The rod controls sit beside the
     viewer.
  5. **Space:** a 2–3 column grid with narrow short fields. More than ~8 field rows → one sub-tab per channel.
  6. **Images** small and enlargeable (none new here; the viewer keeps its size rule).
  7. **Measures with a reference:** mm/m sliders show the channel wire ON the figure, with the viewer grid and the
     1.70-m figure as scale. The rod's length is drawn.
  8. **Status:** a traffic light per step with the plain reason (which model, when, what it fixes). Each 3D preview
     shows "Built <time>". No invented short labels.
  9. **Cost before the click:** every button names its hub jobs ("no jobs").
  10. **Strings:** English with de.json keys, no native dialogs.
- [ ] **Step 2: Write the failing check.** `check_base_body_ui.mjs` renders the Figure tab headless with a fixture
  character whose figure info carries one channel (neutral id). It asserts:
  - the panel shows the fields;
  - Save sends `POST …/collision/channels` and NOT `POST …/collision`;
  - after Save the step shows "due";
  - the viewer toggles "Channels" and "Test rod" exist.
  Run `node scripts/check_base_body_ui.mjs`. Expected: FAIL.
- [ ] **Step 3: Implement** the panel, the rod controls and the viewer wiring.
- [ ] **Step 4: Run** the check, `cd frontend && npm run build`, `npm run lint`,
  `./.venv/bin/python scripts/smoke_no_native_dialogs.py` and `./.venv/bin/python scripts/smoke_i18n_orphans.py`.
  Save the screenshots (`channels.png`, `rod.png`, `due.png`) under `~/claude-out/cross-person/ui/`. Tick the
  checklist. Expected: PASS.
- [ ] **Step 5: Build `static/game_admin/` and commit** with the message
  `feat(game-admin): channels in the model viewer, a test rod, and a store-only Channels panel`.

### Task 16: Stage-2 docs

**Files:**
- Modify: `docs/schnittstellen-3d.md` "Collision capsules":
  - the subsection "Channels (version 7)": the payload shape of Task 12, the guidance rule as in spec Part 4 (frame,
    C, Φ, engagement, release, radial guidance, depth, suppression), the interaction condition, and Save ≠ execute;
  - the version line in the payload block (7).
- Modify: `docs/plugins.md` § "Body-Slots (Spezies-Pakete)": the reference `regions:` with every key of Task 10, its
  validation, `from_rig` + the `opening` metric (the ops that report it today: `inset_part`), and an example with
  neutral ids.
- Modify: `packages/scene-render/src/garmentCollision.ts` and `collision.ts` module docstrings, if Tasks 3/6/13 left
  them partial (the version list of `COLLISION_VERSION`: 5, 6, 7).

**Interfaces:** none (documentation).

- [ ] **Step 1: Write the sections.**
- [ ] **Step 2: Run** `./.venv/bin/python scripts/smoke_docs_schnittstellen_3d.py`,
  `./.venv/bin/python scripts/smoke_docs_scene_render_readme.py` and
  `./.venv/bin/python scripts/smoke_docs_claude_md.py`. Expected: PASS.
- [ ] **Step 3: Commit** with the message `docs: channels (collision v7) and the regions manifest reference`.

## The packs repo

### Task 17: The first real channel (packs repo, commit without push)

**Files:**
- Modify: `/home/dev/projekte/anima-verse-packs/packs/<pack>/plugin.yaml`: the body slot that declares the inset rig
  (rig id `genital_inset`, op `inset_part`, around lines 222–400) gets `regions:` next to its `rigs:`.

**Interfaces:**
- Consumes: `RegionSpec` (Task 10), the `opening` metric (Task 11), resolution (Task 12) and the viewer's Channels
  panel and test rod (Task 15).
- Produces: one region of `kind: channel` whose id is neutral (e.g. `inset_channel`), with:
  - `from_rig: genital_inset`;
  - `bone: Hips`;
  - the fallback `offset`/`axis`: the declared placement for models built before the metric, with the axis pointing
    up into the body;
  - `accepts: {ops: [appendage_chain, attached_part]}` (ruling R11);
  - `min_length: 1.0`, `exposed_only: true`;
  - `templates` and `applies_to` as the inset rig's;
  - starting `depth`, `radius`, `cone_deg`, `funnel` and `compress_min` from Step 2.

- [ ] **Step 1: Read** the slot (`sed -n 222,400p`) and copy the inset rig's `templates`/`applies_to`.
- [ ] **Step 2: Set the starting values** with the test rod.
  - Copy a stored model with the inset part built AFTER Task 11 (or the fixture of `smoke_inset_part_blender.py` if
    none exists) into `~/claude-out/cross-person/pack/`.
  - Run `check_partner_collision.mjs --channels --rod` against a temp copy of its payload with the declaration
    resolved by `collision_channels` (a one-off script under `~/claude-out/`, not committed).
  - Pick radius and depth so that a rod of the accepting chain's measured link radius engages at insertion 0, with
    k ≥ `compress_min` at full insertion.
  - Record the values in the ledger.
- [ ] **Step 3: Validate** with a one-off command (not committed): load the packs repo's manifest through
  `app.plugins.loader` in a temp `paths.init`, and print the parsed `RegionSpec`. Expected: parsed, no error. This
  plan commits no smoke that names the pack.
- [ ] **Step 4: Commit in the packs repo only, without pushing:** `git -C /home/dev/projekte/anima-verse-packs commit
  -m "<pack>: a channel region on the inset rig, placed from the op's opening" -- packs/<pack>/plugin.yaml`.
  Tell the coordinating session that the user's own tuning in the viewer (the Channels panel, per character) becomes
  the pack default as a one-line follow-up there.

---

## Rulings made by this plan (for the coordinating session)

- **R1:** the strand sim is not in the spec, but G1 and answer 2 require all hair. It gets the partner capsules
  (Task 6), and its binding ignores the record's capsule version (Task 1).
- **R2:** the version order is CX1 5, outer 6, channels 7, as the user answered. This overrides spec Part 4/5
  ("version 6").
- **R3:** a malformed region REJECTS the package. That follows the spec's explicit words and the `mesh_part`
  precedent, although malformed rigs are only dropped today.
- **R4:** the poll's `ensure` keeps refitting system staleness (version/sha/scales), but it never applies a
  `channels_sig` change. Exposure is identity: it is applied at fit and relabel time and is not part of
  `channels_sig`.
- **R5:** the panel's "up / out / front" is stored as `offset_mm: [side, up, front]` in the body frame.
- **R6:** the outer trunk slider joins `CollisionScales`, which still stores and recomputes. The spec defers aligning
  that panel.
- **R7:** for partner consumers, `outer_trunk` replaces `torso` (budget; the outer circle encloses the inside-skin
  torso capsules).
- **R8:** partner candidates pass a root-distance prefilter before any binding. The spec's current-frame sphere test
  stays the decisive test.
- **R9:** the `opening` metric is added to the core op without a `PART_BUILDS` bump. A bump would rebuild every inset
  base body and its outfits. Older models use the declared offset (`placement: "declared"`).
- **R10:** the squeeze applies to hair (GPU vertices of kind hair, and hair chain tips), not to cloth or extension
  tips.
- **R11:** the pack's channel accepts `appendage_chain` AND `attached_part`, because `rig_groups_for` turns the chain
  into `attached_part` when the mesh part is on.
- **R12:** the test rod gets a tilt slider, because the radial clamp needs a misaligned rod.
- **R13:** the probe needs bind-space endpoints of another character, so there is a new admin read route.
- **R14:** `PARTNER_PUSH_MAX_M` has no spec default. The starting value is 0.04 m, tuned in Task 9.
