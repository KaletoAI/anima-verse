# Pair scene — one running-scene layer for free pairs and furniture pairs

Date 2026-11-22 · status: design, awaiting approval

## Intent

A pair animation should feel like a scene that develops, not a loop that plays until someone presses Stop.
A package decides how a scene develops (a gauge, a pace, a closing clip); the core gives it the levers. Today
those levers exist only for furniture pair actions (`prop_action_engine`: `prop_action.active` tick, meters,
hold, finale clip, `begin_finale`) and free pair poses (`interaction_engine`) have none of them — the same
scene runs differently depending on whether a sofa is involved. This design moves the levers into ONE core
module used by both, and adds three new ones: a playback **tempo**, live **channel readouts** reported by the 3D
client (with a server estimate when no client is open), and a pose's **lead role**.

## Goals

- One core module (`app/core/pair_scene.py`, name the builder's) that owns, per running pair interaction
  (free OR furniture): the periodic tick to packages, the tempo, the finale clip of one member, "end after N
  seconds", the hold toggle and the meters row. `prop_action_engine` and `interaction_engine` call it; neither
  keeps its own copy.
- **Tempo**: a factor 0.2..1 per interaction that scales the pair clip's playback. 1 = the clip's own speed
  (the 1x of the Poses → Places preview) and the maximum. The core does not decide it: a package provider answers
  it each tick; without a provider the tempo is 1 (today's behaviour).
- **Channel readouts to the server**: client3d already computes `channelReadout` per frame
  (`packages/scene-render/src/channelReadout.ts`). It reports a ≤1 Hz summary per (interaction, receiver,
  channel, entering) to the server; the server keeps the latest per key and hands it to packages on the tick.
- **Readout estimate without a client**: when no report is fresher than a few seconds, the core estimates the
  same summary from (a) the two figures' collision records (channel depth + rest radius, entering part length +
  surface radius) and (b) a per-clip insertion profile measured once in the Poses tab and stored in the clip
  sidecar. Exact only with a client; an estimate otherwise (user decision 2026-11-22: "A with B as estimate").
- **Lead role** on pose catalog entries (multi-person poses): which clip role "drives" the scene. Pre-filled for
  existing entries; packages read it. Empty = the role `role_gender` assigns to the gender a package names;
  the core's own fallback is role "a".
- **Narration of pair start / switch / end leaves the chat**: the lines are still perceived (characters and the
  storyteller know), but the player chat does not show them. A package's own narration (a storyteller reaction)
  stays visible.
- **Places preview** (Game-Admin → Poses → Places): no state picker any more. Each extension group with named
  poses gets a pose picker (rest + its named poses), pre-selected from a per-group package field
  (`preview_pose`). The base body is the default body when it is built. (User decision 2026-11-22.)

## Non-goals

- No gauge, no stat, no thresholds in the core. Core names stay neutral (tempo, readout, finale, lead role).
  Everything that gives these meaning lives in a package (see the package spec in the private packs repo).
- No change to invitation, approach, consent or furniture seating logic.
- No change to the furniture finale's existing behaviour for packages that do not use the new levers.

## Anti-goals

- A second copy of the scene rules in either engine (the reason for this design).
- A client deciding game state: the client only REPORTS measurements; the server keeps the gauge and the tempo.
- Content of the private packs in this repo's code, comments, docs or commits.

## Constraints

- "The server computes, clients render" (docs/schnittstellen-3d.md): tempo and clip phase come from the server;
  both renderers (client3d and the admin preview via `@anima/scene-render`) apply them the same way.
- Clip phase with a variable tempo: the server integrates a clip clock (`clip_s += Δreal · tempo`) per
  interaction and sends `clip_s` + `tempo`; clients advance `clip_s` locally by `dt · tempo` and snap as
  today (PAIR_SNAP_S). Same id + same clip must NOT restart the blend (`npcs.ts adoptInteraction`).
- Animation time is REAL time (E1); the tick's gauge time is GAME time (as `prop_action.active` today).
- Profile locks, sync_topics recipients and the default-deny auth rules apply to the new route.
- A readout report is accepted only from a client whose user may see that interaction (same room as its avatar,
  or an admin), at most ~1/s per key; anything else is dropped silently.

## Approaches considered

1. **Free pairs become furniture runs without furniture** — everything inherited, but invitation/approach/
   reaction/memory of free pairs would have to move; very large and risky.
2. **A shared scene module both engines use (chosen, user 2026-11-22)** — the rules exist once; engines keep
   their own start/stop/consent logic and only report "running" and ask the module for tempo/finale.
3. **A copy of the furniture mechanics for free pairs** — fast, but two copies drift (it happened before with
   the place geometry).

## Decided parts of the how

- Tick: one periodic job iterates live pair interactions (free and furniture) and emits ONE hook, e.g.
  `pair_scene.active(interaction_id, members, roles, pose_key, lead_role, delta_game_s, readouts)`. The
  furniture `prop_action.active` either becomes this or is emitted from it — builder's call, no duplicate
  ticking.
- Tempo provider: `pair_scene.tempo(interaction_id, …) -> float | None`, clamped to [0.2, 1].
- Finale: `begin_finale` / finale payload (`finale` block, `loop_count` cycles of the clip, § A8c) move into
  the shared module and work for free pairs too; "end the interaction N seconds after the finale" is a core
  call a package may make.
- Narration: pair start / switch / end lines get a perception flag that keeps them out of `/play/messages`
  (and Game-Admin chat views) while they stay in the perception stream the prompts read.
- The finale repeat count is the clip's sidecar `loop_count`; today its field only shows when "Loop" is ticked
  (Poses → clip library) — make it visible for finale clips without the loop switch.
- Places preview: the 0.2x default and the place-memory fixes landed already (e6104d8eb).

## Calls made after the builder check (correctable)

- **Scope**: the module covers every running pose interaction a package ticks today — free pairs, furniture
  pairs, furniture solo actions and groups — so `prop_action.active` does not survive as a second tick. Tempo
  applies to any of them (solo: the one person leads); a group has one lead role.
- **Lead role pre-fill**: the core fills nothing itself. It asks a package provider (e.g.
  `pose.lead_role_default(pose_key, clip roles, role_gender)`) for each multi-person pose without a lead role and
  stores the answer; the role decides for the pose's own animation clip (its `animation` kind's sidecar).
  Without a provider or an answer: role "a".
- **Readout radius**: the readout gains the entering part's largest surface radius inside the channel
  (`partRadiusM`), so "not filled" (r < R) is measurable; `stretchM` stays as it is.
- **No measurement** (no report, no estimate possible — e.g. no collision record): the package gets no readout
  for that key and treats its factors as neutral.
- **Finale timing**: the finale clip plays at a tempo the package gives with `begin_finale` (default 1; the
  package uses 0.5 — user decision 2026-11-22: the closing clip at full speed is too fast); its real length is clip length × cycles /
  tempo. "End N seconds later" counts from the moment the finale clip has fully played (all `loop_count` cycles).
- **Which narration leaves the chat** (user 2026-11-22): only the start / switch / end lines, and only for poses a
  package marks as such (a provider, e.g. `pair_scene.quiet_narration(pose_key) -> bool`). Invitations,
  approaches, refusals and reactions stay visible; harmless pair poses keep all their lines.

## Left to the builder

Module and hook names, the report endpoint path and payload shape, the estimate's exact formula (documented in
the module docstring and derived by hand in a smoke, CLAUDE.md), how the insertion profile is measured and
stored in the sidecar, the migration that pre-fills the lead role, the perception flag's name, the UI for the
per-group pose picker and the lead-role field (rendered generically like the other pose fields).
