# residency_gen

- Origin: `client3d/scripts/smoke_residency_gen.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/ResidencyVectorTests.cs`
- Vectors: `shared/test-vectors/residency.json`

## Derivation

```text
/** NEU: residency.ts and SceneLibrary.forget absent on a241a8aa.
 * Canonical source for residency.json, op sequences [1]..[18].
 * Each op group yields one snapshot; expectations select state fields and exact
 * incremental up/down calls (mount/unmount decisions). No implicit flush occurs.
 * [1] up_down: gone->far->near mounts twice; near->far->gone unmounts twice.
 * [2] retarget_mid_await: near requested, gone before completion; one rollback,
 * no published resident and no retry. [3] flip_flop: gone then far invalidates
 * the first up; one rollback, one replacement up, final far/version 1.
 * [4] rebuild_during_shell: invalidate version 1, replace with version 2 at far.
 * [5], [9], [10] rebuild_at_near / settled_waits_rebuild / hasJob: initial
 * want queues a job synchronously; settled leaves near/version 1 with no job.
 * Rebuild downs near then far, awaits the new shell (gone, no live version,
 * hasJob=true, settled waiter unresolved), then ups far->near at version 2;
 * precisely one waiter resolves. No stale shell is kept.
 * [6], [7] drop_during_fetch / drop_during_mount: the driver's opaque awaited
 * up aborts once, ends gone with no live/timer. Real fetch/mount cleanup is
 * distinguished separately in the main-adapter integration cases below.
 * [8] rediscover_after_drop: aborted version 1 cleans up before version 2 up;
 * final far/version 2, one resident, one rollback, no retry.
 * [11] fetch_retry: failure leaves gone, hasJob=false and timer 5000 ms;
 * firing that timer without another want performs one new up and reaches far.
 * [12] queue_max: five far requests with ascending priorities, each gated;
 * exactly ids 0/1 enter first, max concurrent mounts=2, release yields 2/3/4
 * in order and five live residents, all jobs false.
 * [13] cancelled_retry_settled: failed up arms 5000 ms; want gone cancels it,
 * resolves both settled waiters, deletes the entry; rebuilding is then inert.
 * [14] sweep_forgotten: forget X before reply -> no cache/publication.
 * [15] sweep_forget_unstarted: while X awaits, forget Y; publish only X and
 * never fetch Y. [16] forget_then_request: forgotten X's old reply cannot
 * publish; fresh request publishes fresh once. [17] reverse reply order:
 * fresh first remains fresh after the old reply; same one publication.
 * [18] request_dedup: two requests share a promise and one fetch; both return
 * the same new signature, published exactly once.
 * Pins are renderer adapter state rather than driver state: the independent
 * current/travel owners and boot release assertions stay inline below.
 *
 * Hand oracles: gone->near needs two up steps; near->gone two down steps.
 * Invalidated steps roll back once, never publish ready. Five jobs on max=2
 * never exceed two mounts. Failed fetch retries at 5000 ms without retarget.
 * Rebuild tears down both stages and builds version 2, preserving near target;
 * settled waits for queued rebuild, hasJob includes queued and running work.
 * Drop invalidates fetch/mount, never retries; rediscovery waits for old cleanup.
 * Epoch snapshots reject forgotten replies in either order, and skip B when
 * forgotten while sweep waits for A. Duplicate requests share one promise.
 * Main adapter cases below run extracted production functions with stub I/O:
 * no_scene reaches ready without mounts; stale details never publish ready;
 * arrival_moves places on Y and opens Y before requesting its full tiers;
 * open_arrival_tiers/tick_during_promotion keep full until ready, height updates
 * still execute. Source guards cover the adapter wiring, not rendered pixels.
 */
```
