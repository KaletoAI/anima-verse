# Hub jobs that survive a restart

Long AI-hub jobs — character meshes, rigs, face corrections, reference upscales, prop and location
meshes and their low variants, Instagram and video-skill animations, pose animations — run for
minutes on the gateway, and the gateway finishes them whether or not Anima is still listening. Since
`feat/hub-job-resume`, a restart of Anima no longer loses that work: the result is collected after
the start and processed exactly as if nothing had happened. Nothing is submitted a second time.

Design and decisions: `docs/superpowers/specs/2026-10-13-hub-job-resume-design.md` (§ 0 is binding).

## The operation record

`app/core/hub_ops.py` keeps one row per job chain in the world's `world.db` (table `hub_ops`) and a
durable directory `<world>/hub_ops/<op_id>/`:

- **Frozen inputs** — signature, backend pick, budgets, file names and copies of the input files
  (T-pose, source image, views, the mesh to rig or shrink). A resume never reads the world's
  current state: a character that changed clothes in between still gets the mesh of the outfit the
  job was started for.
- **Stage state** — every hub stage goes `claimed → posting → submitted → collected`, local stages
  are `done` with their result. The stage functions are the same for the normal run and the resume;
  they skip what the record says is done.
- **Intermediate results** live in the record's directory (the staging dir of a run dies with the
  process): the unrigged mesh before its rig, the corrected face source with its replacement mask,
  a downloaded result before it is published.
- **Lifetime** — created after the preprocessing, deleted once the result is published. A failure is
  stored first, then the record is deleted.
- **Claim** — a partial unique index on `subject` (the existing double-start key of each kind) means
  a second start of the same work is refused (`HubOpBusy`) instead of becoming a second hub job.

| Kind | Stages | Entry |
|---|---|---|
| `character_mesh` | mesh → checkpoint (static mesh published) → rig → publish | `model3d.generate_for_current_outfit` |
| `character_rerig` | rig → publish | `model3d.rerig_model` |
| `face_retexture` | upscale → face → bake → rig → publish | `model3d.face_retexture_model` |
| `prop_mesh`, `prop_shrink` | mesh / shrink → publish | `props._generate`, `props._shrink` |
| `location_mesh`, `location_shrink` | mesh / shrink → publish | `location_model3d._generate`, `_shrink` |
| `video_instagram`, `video_character` | video → publish | Instagram animate, video skill |
| `pose_animation` | animation → convert → `awaiting_choice` | `pose_animation._handle` |

The service methods (`generate_mesh`, `generate_rig`, `generate_mesh_variant`,
`generate_face_retexture`, `upscale_image`, `generate_video`, `generate_mesh_animation`) take a
`hub_stage`. A stage with a job recorded by an earlier process is **collected** through the
backend's `attach()` — no routing, no POST, no GPU slot, no master switch — and post-processed like
a fresh result. Without a stage everything behaves as before.

## Who continues

- **Queue tasks** (`npc_assets`, `outfit_combos`, `improvement_step`, `pose_animation`) own the
  records their handler creates. The queue runs the handler again after a restart, and the entry
  point finds its open record and resumes it with the frozen inputs. If the task ends without
  getting back to its record (a handler that considers the published static mesh done), the record
  continues on its own thread. A cancelled task cancels its hub jobs.
- **Threads** (admin buttons, Instagram, the video skill) are continued by the **resumer**,
  `hub_ops.start_resumer()`, started in the server lifespan after the handler registration and
  before the AgentLoop and the queue workers. It takes the in-process guards of the operations it
  continues synchronously, so an auto-mesh hook started right after it sees those targets as busy.
- For task records the resumer **collects the running job right away**, also while the task's queue
  is paused, so the gateway's 24 h retention cannot run out under a waiting task.
- Every resumed operation gets its own row in the task list, labelled `… — collecting after
  restart`; the interrupted row of the previous process says which row took over. That row is
  exempt from the 20-minute stale reaper, and cancelling it cancels the hub job.

## Lost jobs

`HubJobLost` (`app/imagegen/base.py`, text starts with `Hub job lost:`) ends an operation when its
job cannot be collected: the gateway answers 404 (three times) or 410, or 401/403 (the job is not
readable with this backend's key), the job failed or was cancelled on the gateway, the recorded
backend is gone or points to another gateway, the job is older than 24 h, a job still queued or
running is past its time budget, its results cannot be downloaded, or the stage ran on a backend
without a hub job protocol (a third-party video API, a local upscaler) — there is no job to
collect, and submitting again could pay for the same work twice. An unreachable gateway (connection error, 5xx) is **not** lost: it is polled with up to
30 s between attempts until the 24 h are over.

`HubJobLost` is terminal in every layer: the backend runner neither cools the backend down nor wraps
it into a re-route, the task queue does not retry it, an improvement step is skipped at once, and a
lost reference upscale ends the face correction. **A lost job is never submitted again
automatically.** Inside a queue task the record stays as a tombstone until the task is over, so a
re-run handler meets the same verdict instead of starting the work anew. Independent automatic
producers (the auto-mesh hook after a T-pose render, a standing improvement's next scan) may still
treat the asset as missing later — that is their own decision, not a resubmission.

## The submission gap

Between the gateway accepting a POST and the job id being stored there is a short window. A restart
inside it leaves the stage in `posting`; the resume ends that operation as lost, and the gateway
job — if the gateway took it — runs orphaned. This is accepted by decision; the gateway is
unchanged.

## Limits

- A restart longer than the gateway's job retention (24 h) loses the job.
- The video skill cannot deliver its chat answer after a restart; the video still lands in the
  gallery.
- A crash in the seconds of the local publish repeats the publish; gallery paths are fixed before
  they are written, so no second file appears.
- A pose animation whose task is gone cannot continue (its candidates live in the task row); its job
  is cancelled. The shared puppet / reference rig is used by path, not frozen per job.
- A queue task whose queue stays paused keeps its record — and with it its target — claimed until
  the task runs (its job is collected right away, though). A manual start of the same work is
  refused meanwhile.

## Retained legacy prop meshes

Older persisted `prop_mesh` records may lack a stable variant UUID. They are
not published into whichever variant happens to occupy the old numeric index.
Already submitted provider results are collected where possible, and the
operation, inputs, outputs and provider handle are retained for explicit repair.
A deferred legacy operation releases its running subject claim without
cancelling paid work.

In Props → Modell & Varianten, inspect the retained job, select the intended
current variant and explicitly confirm assignment. The save/cancel barrier and
a fresh UUID/revision check apply before publication. This reuses the existing
work: it does not submit another render, overwrite the target source image or
charge for a new provider job. Existing mesh gallery history remains available.
If collection/publication still fails, the legacy operation stays deferred for
another manual attempt instead of being deleted. New UUID-bearing operations
retain normal terminal error handling; explicit cancellation is unchanged.

Check: `scripts/smoke_hub_job_resume.py` (fake hub, simulated restart).

In Props → Model & Variants, **Older generation results** is collapsed by default.
**Discard** asks for confirmation in the admin UI and calls the admin-only
`POST /world/props/{id}/generation-repairs/{op_id}/dismiss` route. The existing
journal marks the deferred record with `state.dismissed_at`; the repair listing
excludes it, explicit reassignment refuses it, and restart recovery skips it.
The operation record, staged inputs/results, provider handle and gallery files
are retained for traceability. Discard does not submit or cancel a provider job.
Check: `scripts/smoke_prop_generation_concurrency.py` (temporary storage).
