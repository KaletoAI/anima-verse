/**
 * B-T4 NEU: client3d guards fail on a241a8aa: its separate timer doubles
 * the core cadence and its fetch applies results before generation checks.
 * apply_after_gen: resync during request 1 drops it; only request 2 applies,
 * so the callback count is 1 and the applied result is 2 (hand-derived).
 * All cases NEU: pollCore.ts and syncHub.ts are absent on a241a8aa.
 * Hand-derived oracles (fetch duration = 100 ms):
 * dirty: initial + one pending signal = 2 requests. intervals: connected scene
 * waits 20s, disconnected waits 5s. budget: starts 0,3000,6000 for signals
 * 0,300,3500; one_endpoint: presence+scene is one signal, no poll before 20s.
 * trailing_consumed: refresh at 1000 consumes the timer due at 3000.
 * first_connect: generation 0, initial 0 + resync trailing at 5000.
 * reconnect/resync_in_stream/resync_idle: each later resync increments once,
 * signals once, and an idle scene starts once (no extra before 20s).
 * untopiced_entry: only state signals it, once per binding change.
 * gen_inflight: old completion is dropped, exactly one new fetch reaches both.
 * strict_mode: unsubscribe/resubscribe shares the running request, only live cb.
 * hidden_burst: five signals yield zero hidden fetches and one visible fetch.
 * gen_replay: invalidated cached data cannot reach a new subscriber.
 * bye: no reconnect in 120s, fallback interval 5s. closed_reconnect: new source
 * after 5s. refresh_inflight: resolves after request 2, never after request 1.
 * interval_raise: removing the 5s subscriber leaves the 30s interval.
 * suspend_wake/dead/twice: one 35s grace after suspension; frames reset it.
 * Additional NEU guards: latest fetcher, synchronous failures, error backoff,
 * runHidden, restart with a pending retry, malformed frames and listener cleanup.
 * listener_cleanup: a two-topic listener fires once per matching frame, zero
 * after unsubscribe. bye_restart: an explicit restart opens exactly one source.
 *
 * POLL SCHEDULE (shared/test-vectors/poll_schedule.json, also read by the native
 * client's C# tests; labels start with the tag below):
 * [P1] pollIntervalMs(base, spacing, f) = max(spacing, min(base*f, max(base, 60000))).
 *   a) worldmap3d without push (3000, 3000, 1): min(3000, 60000) = 3000, max(3000, 3000) = 3000
 *   b) with push the base is pushedIntervalMs (6000, 3000, 1) -> 6000
 *   c) one failure (3000, 3000, 2): 6000      d) (3000, 3000, 64): 192000 -> 60000
 *   e) (5000, 0, 8): 40000                    f) (5000, 0, 16): 80000 -> 60000
 *   g) (120000, 0, 4): min(480000, max(120000, 60000) = 120000) = 120000 — slow stays slow
 *   h) (1000, 5000, 1): max(5000, 1000) = 5000 — the spacing wins
 *   i) badges (20000, 20000, 1): 20000
 * [P2] nextErrorFactor(f, ok) = ok ? 1 : min(2f, 64):
 *   (1, fail) 2; (32, fail) 64; (64, fail) min(128, 64) = 64; (8, ok) 1; (1, ok) 1; (64, ok) 1.
 */
import { readFileSync } from "node:fs";
import { loadVectors, runVectors } from "../shared/test-vectors/vectors.mjs";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const unhandled = [];
process.on("unhandledRejection", error => unhandled.push(error));
const require_ = createRequire(import.meta.url);
const esbuild = require_("../frontend/node_modules/esbuild");
async function load(n) {
  const r = await esbuild.build({ entryPoints: [`packages/player-ui/src/${n}.ts`], bundle: true, write: false, format: "esm", platform: "neutral", logLevel: "silent" });
  return import(`data:text/javascript;base64,${Buffer.from(r.outputFiles[0].text).toString("base64")}`);
}
const { createPollCore } = await load("pollCore");
const { createSyncHub } = await load("syncHub");
const { SYNC_ENDPOINTS: S } = await load("syncEndpoints");
{
  const { pollIntervalMs, nextErrorFactor } = await load("pollCore");
  const { passed, failed } = runVectors(loadVectors("poll_schedule"), { pollIntervalMs, nextErrorFactor });
  assert.equal(failed, 0, `${failed} poll schedule vector(s) failed`);
  console.log(`PASS poll_schedule_vectors (${passed} cases)`);
}
function fixture() {
  let t = 0, hidden = false, id = 0;
  const timers = new Map(), sources = [], starts = [], data = [];
  const timer = (fn, ms) => {
    timers.set(++id, { fn, at: t + ms });
    return id;
  };
  const flush = async () => {
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };
  async function advance(ms) {
    const end = t + ms;
    await flush();
    for (; ; ) {
      const n = [...timers].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!n) break;
      t = n[1].at;
      timers.delete(n[0]);
      n[1].fn();
      await flush();
    }
    t = end;
    await flush();
  }
  async function suspend(ms) {
    t += ms;
    await flush();
    for (; ; ) {
      const n = [...timers].filter(([, v]) => v.at <= t).sort((a, b) => a[1].at - b[1].at)[0];
      if (!n) break;
      timers.delete(n[0]);
      n[1].fn();
      await flush();
    }
    await flush();
  }
  class Source {
    readyState = 0;
    onopen = null;
    onerror = null;
    onmessage = null;
    listeners = new Map();
    addEventListener(type, fn) {
      this.listeners.set(type, fn);
    }
    close() {
      this.readyState = 2;
    }
    open() {
      this.readyState = 1;
      this.onopen?.({});
    }
    msg(o) {
      this.onmessage?.({ data: JSON.stringify(o) });
    }
    bye() {
      this.listeners.get("bye")?.();
    }
    fail(closed) {
      this.readyState = closed ? 2 : 0;
      this.onerror?.({});
    }
  }
  const hub = createSyncHub({ open: (url) => {
    assert.equal(url, "/events/sync");
    const s = new Source();
    sources.push(s);
    return s;
  }, setTimeout: timer, now: () => t });
  const core = createPollCore({ now: () => t, hidden: () => hidden, setTimeout: timer, clearTimeout: (h) => timers.delete(h) }, hub);
  const fetcher = () => {
    const n = starts.push(t);
    return new Promise((r) => timer(() => r(n), 100));
  };
  const sub = (spec = S.scene, cb = (d, e) => data.push([d, e]), fetch = fetcher) => core.subscribe("x", fetch, spec, cb);
  return { hub, core, starts, data, sources, sub, advance, suspend, hidden: (v) => hidden = v, source: () => sources.at(-1) };
}
async function test(n, fn) {
  await fn(fixture());
  console.log("PASS " + n);
}
// NEU / REGRESSION hand-derived oracles: remounts start at the 5s budget, not the 30s poll.
// A throwing callback cannot suppress delivery, refresh settlement or request 3.
// Inactive refreshes resolve void even before a stale running request completes.
await test("remount_after_invalidate", async f => {
  const off = f.sub(S.self);
  await f.advance(100);
  off();
  f.hub.invalidateBinding();
  f.sub(S.self);
  await f.advance(4899);
  assert.deepEqual(f.starts, [0]);
  await f.advance(101);
  assert.deepEqual(f.starts, [0, 5000]);
  assert.equal(f.data.at(-1)[0], 2);
});
await test("remount_trailing", async f => {
  const off = f.sub(S.self);
  await f.advance(100);
  f.core.signal("x");
  off();
  await f.advance(900);
  f.sub(S.self);
  await f.advance(3999);
  assert.deepEqual(f.starts, [0]);
  await f.advance(101);
  assert.deepEqual(f.starts, [0, 5000]);
});
await test("subscriber_throws", async f => {
  const original = console.error;
  const errors = [];
  console.error = (...args) => errors.push(args);
  try {
    f.sub({ intervalMs: 5000 }, () => { throw Error("subscriber failure"); });
    f.sub({ intervalMs: 5000 });
    let done = false;
    f.core.refresh("x").then(() => done = true);
    await f.advance(100);
    f.core.signal("x");
    await f.advance(100);
    assert.equal(done, true);
    assert.deepEqual(f.starts, [0, 100, 200]);
    await f.advance(100);
    assert.deepEqual(f.data.map(x => x[0]), [1, 2, 3]);
    assert.equal(errors.length, 3);
    // Cached replay is isolated too.
    const off = f.sub({ intervalMs: 5000 }, () => { throw Error("replay failure"); });
    off();
    assert.equal(errors.length, 4);
  } finally { console.error = original; }
});
await test("refresh_orphaned", async f => {
  const off = f.sub(S.self);
  await f.advance(100);
  let captured = false, queued = false;
  f.core.refresh("x").then(() => captured = true);
  f.core.refresh("x").then(() => queued = true);
  off();
  await f.advance(0);
  assert.deepEqual([captured, queued], [true, true]);
  f.hub.invalidateBinding();
  await f.advance(100);
  assert.deepEqual(f.starts, [0, 100]);
});
await test("dirty", async (f) => {
  f.sub({ intervalMs: 5e3 });
  f.core.signal("x");
  f.core.signal("x");
  await f.advance(200);
  assert.deepEqual(f.starts, [0, 100]);
});
await test("intervals", async (f) => {
  f.sub();
  f.source().open();
  f.source().msg({ resync: true });
  await f.advance(5e3);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 5000]);
  await f.advance(15e3);
  f.core.tick();
  await f.advance(100);
  f.source().fail(false);
  await f.advance(4900);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 5000, 25000]);
});
await test("budget", async (f) => {
  f.sub(S.worldmap3d);
  await f.advance(300);
  f.core.signal("x");
  await f.advance(3200);
  f.core.signal("x");
  await f.advance(2500);
  assert.deepEqual(f.starts, [0, 3e3, 6e3]);
});
await test("one_endpoint", async (f) => {
  f.sub();
  f.source().open();
  f.source().msg({ resync: true });
  await f.advance(1e4);
  f.source().msg({ topics: ["presence", "scene"], resync: false });
  await f.advance(19999);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 5000, 1e4]);
});
await test("trailing_consumed", async (f) => {
  f.sub(S.worldmap3d);
  await f.advance(300);
  f.core.signal("x");
  await f.advance(700);
  const p = f.core.refresh("x");
  await f.advance(100);
  await p;
  await f.advance(1900);
  assert.deepEqual(f.starts, [0, 1e3]);
});
await test("first_connect", async (f) => {
  f.sub();
  f.source().open();
  f.source().msg({ resync: true });
  assert.equal(f.hub.generation(), 0);
  await f.advance(5100);
  assert.deepEqual(f.starts, [0, 5e3]);
});
for (const n of ["reconnect", "resync_in_stream", "resync_idle"]) await test(n, async (f) => {
  f.sub();
  f.source().open();
  f.source().msg({ resync: true });
  await f.advance(3e4);
  if (n === "reconnect") {
    f.source().fail(false);
    f.source().open();
  }
  f.source().msg({ resync: true });
  assert.equal(f.hub.generation(), 1);
  await f.advance(19999);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 5e3, 3e4]);
});
await test("untopiced_entry", async (f) => {
  f.sub({ intervalMs: 5e3 });
  f.hub.invalidateBinding();
  await f.advance(200);
  assert.deepEqual(f.starts, [0, 100]);
  f.hub.start();
  f.source().msg({ resync: true });
  await f.advance(100);
  f.source().msg({ resync: true });
  await f.advance(100);
  assert.deepEqual(f.starts, [0, 100, 300]);
});
await test("gen_inflight", async (f) => {
  f.sub({ intervalMs: 5e3 });
  f.hub.invalidateBinding();
  f.sub({ intervalMs: 5e3 });
  await f.advance(100);
  assert.deepEqual(f.data, []);
  assert.deepEqual(f.starts, [0, 100]);
  await f.advance(100);
  assert.deepEqual(f.data, [[2, null], [2, null]]);
});
await test("strict_mode", async (f) => {
  let old = 0, live = 0;
  const off = f.sub(S.scene, () => old++);
  off();
  f.sub(S.scene, () => live++);
  await f.advance(100);
  assert.deepEqual([f.starts.length, old, live], [1, 0, 1]);
});
await test("hidden_burst", async (f) => {
  f.sub();
  await f.advance(1e4);
  f.hidden(true);
  for (let i = 0; i < 5; i++) f.core.signal("x");
  f.core.tick();
  assert.deepEqual(f.starts, [0]);
  f.hidden(false);
  f.core.visible();
  await f.advance(100);
  assert.deepEqual(f.starts, [0, 1e4]);
});
await test("gen_replay", async (f) => {
  f.sub();
  await f.advance(100);
  f.hub.invalidateBinding();
  const d = [];
  f.sub(S.scene, (x) => d.push(x));
  assert.deepEqual(d, []);
  await f.advance(5e3);
  assert.deepEqual(d, [2]);
});
await test("bye", async (f) => {
  f.sub();
  f.source().open();
  f.source().bye();
  await f.advance(5e3);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 5e3]);
  await f.advance(115e3);
  assert.equal(f.sources.length, 1);
  assert.equal(f.hub.connected(), false);
});
await test("closed_reconnect", async (f) => {
  f.sub();
  f.source().fail(true);
  await f.advance(4999);
  assert.equal(f.sources.length, 1);
  await f.advance(1);
  assert.equal(f.sources.length, 2);
});
await test("refresh_inflight", async (f) => {
  f.sub();
  let done = false;
  const p = f.core.refresh("x").then(() => done = true);
  await f.advance(100);
  assert.equal(done, false);
  await f.advance(100);
  await p;
  assert.equal(f.data.at(-1)[0], 2);
});
await test("interval_raise", async (f) => {
  const off = f.sub({ intervalMs: 5e3 });
  f.sub({ intervalMs: 3e4 });
  off();
  await f.advance(5e3);
  f.core.tick();
  assert.deepEqual(f.starts, [0]);
  await f.advance(25e3);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 3e4]);
});
await test("latest_fetcher", async (f) => {
  f.sub();
  f.sub(S.scene, () => {
  }, async () => 99);
  await f.advance(100);
  await f.core.refresh("x");
  assert.equal(f.data.at(-1)[0], 99);
});
await test("runHidden", async (f) => {
  f.hidden(true);
  f.sub(S.worldmap3d);
  await f.advance(3e3);
  f.core.tick();
  assert.deepEqual(f.starts, [0, 3e3]);
});
await test("restart_pending_retry", async (f) => {
  f.sub();
  const old = f.source();
  old.fail(true);
  f.hub.restart();
  const current = f.source();
  old.open();
  old.bye();
  current.open();
  current.msg({ resync: true });
  for (let i = 0; i < 8; i++) { current.listeners.get("ping")(); await f.advance(15000); }
  assert.equal(f.sources.length, 2);
  assert.equal(f.hub.connected(), true);
  current.onmessage({ data: "invalid" });
});
await test("sync_error_backoff", async (f) => {
  let calls = 0;
  f.sub({ intervalMs: 5e3 }, () => {
  }, () => {
    calls++;
    throw Error("offline");
  });
  await f.advance(5e3);
  f.core.tick();
  assert.equal(calls, 1);
  await f.advance(5e3);
  f.core.tick();
  await f.advance(0);
  assert.equal(calls, 2);
});
await test("listener_cleanup", async f => {
  let calls = 0;
  const off = f.hub.onTopics(["presence", "scene"], () => calls++);
  f.source().msg({ topics: ["presence", "scene"] });
  assert.equal(calls, 1);
  off();
  f.source().msg({ resync: true });
  f.source().msg({ topics: ["presence"] });
  assert.equal(calls, 1);
});
await test("bye_restart", async f => {
  f.sub();
  f.source().open();
  f.source().bye();
  f.hub.restart();
  f.source().open();
  f.source().msg({ resync: true });
  for (let i = 0; i < 8; i++) { f.source().listeners.get("ping")(); await f.advance(15000); }
  assert.equal(f.sources.length, 2);
  assert.equal(f.hub.connected(), true);
});
await test("apply_after_gen", async f => {
  const applied = [];
  f.sub(S.worldmap3d, (data, error) => {
    if (error) throw error;
    applied.push(data);
  });
  f.source().msg({ resync: true });
  f.source().msg({ resync: true });
  await f.advance(100);
  assert.deepEqual(applied, []);
  await f.advance(3000);
  assert.deepEqual(applied, [2]);
});
// NEU review oracles: restart clears replay synchronously; headers are insufficient.
await test("restart_generation", async f => {
  f.sub(S.self);
  await f.advance(100);
  f.hub.restart();
  assert.equal(f.hub.generation(), 1);
  const replay = [];
  f.sub(S.self, x => replay.push(x));
  assert.deepEqual(replay, []);
  await f.advance(5000);
  assert.deepEqual(replay, [2]);
});
// NEU: a request from the previous identity never delivers after restart.
await test("restart_inflight", async f => {
  f.sub(S.self);
  f.hub.restart();
  await f.advance(100);
  assert.deepEqual(f.data, []);
  await f.advance(5000);
  assert.deepEqual(f.data, [[2, null]]);
});
const authGate = readFileSync("frontend/src/lib/AuthGate.tsx", "utf8");
assert.match(authGate, /onSuccess=\{\(u\) => \{ syncHub\(\)\.restart\(\); setUser\(u\)/);
await test("delivery_deadline", async f => {
  f.sub();
  const old = f.source();
  old.open();
  assert.equal(f.hub.connected(), false);
  old.msg({ resync: true });
  assert.equal(f.hub.connected(), true);
  await f.advance(34000);
  old.open(); // Headers alone must not extend the last-frame deadline.
  await f.advance(999);
  assert.equal(f.hub.connected(), true);
  await f.advance(1);
  assert.equal(f.hub.connected(), false);
  assert.equal(old.readyState, 2);
  await f.advance(5000);
  assert.equal(f.sources.length, 2);
  await f.advance(35000 + 10000);
  assert.equal(f.sources.length, 3);
});
// NEU: wake at 610000 grants grace; a frame resets the deadline to 645000, retry at 650000.
await test("suspend_wake", async f => {
  f.sub(); const s = f.source(); s.open(); s.msg({ resync: true });
  await f.advance(10000);
  await f.suspend(600000); // 610000 - 0 > 45000 grants one fresh window.
  assert.equal(s.readyState, 1); assert.equal(f.sources.length, 1); assert.equal(f.hub.connected(), true);
  s.msg({ resync: true }); // Queued native reconnect resync resets the normal deadline.
  await f.advance(34999); assert.equal(f.hub.connected(), true);
  await f.advance(1); assert.equal(s.readyState, 2); assert.equal(f.hub.connected(), false);
  await f.advance(5000); assert.equal(f.sources.length, 2);
});
// NEU: wake at 600000 grants grace until 635000; no frame means close, retry at 640000.
await test("suspend_dead", async f => {
  f.sub(); const s = f.source(); s.open(); s.msg({ resync: true });
  await f.suspend(600000);
  assert.equal(f.sources.length, 1); assert.equal(s.readyState, 1);
  await f.advance(34999); assert.equal(s.readyState, 1);
  await f.advance(1); assert.equal(s.readyState, 2);
  await f.advance(5000); assert.equal(f.sources.length, 2);
});
// NEU: grace armed at 600000 fires at 1200000; late=true closes, retry at 1205000.
await test("suspend_twice", async f => {
  f.sub(); const s = f.source(); s.open(); s.msg({ resync: true });
  await f.suspend(600000);
  assert.equal(f.sources.length, 1); assert.equal(s.readyState, 1);
  await f.suspend(600000);
  assert.equal(s.readyState, 2); assert.equal(f.hub.connected(), false);
  await f.advance(5000); assert.equal(f.sources.length, 2);
});
// NEU: [0,60000) has at most 60000/oldInterval starts under 100ms signals.
for (const [key, spec] of Object.entries(S)) await test("sustained_" + key, async f => {
  assert.ok(spec.minSpacingMs >= spec.intervalMs);
  f.sub(spec);
  f.source().msg({ resync: true });
  for (let t = 100; t < 60000; t += 100) {
    await f.advance(100);
    f.source().listeners.get("ping")();
    f.source().msg({ topics: spec.topics });
    f.core.tick();
  }
  assert.ok(f.starts.length <= Math.ceil(60000 / spec.intervalMs), JSON.stringify(f.starts));
});
const main = readFileSync("client3d/src/main.ts", "utf8");
assert.doesNotMatch(main, /setInterval\([^;]*WORLDMAP_POLL_MS/);
assert.match(main, /pollCore\(\)\.subscribe\('c3d-worldmap',\s*fetchWorldMap,\s*SYNC_ENDPOINTS\.worldmap3d/);
assert.equal((main.match(/void pollCore\(\)\.refresh\('c3d-worldmap'\)/g) ?? []).length, 2);
assert.doesNotMatch(main, /pollWorldMap\s*\(/);
const fetchBody = main.match(/async function fetchWorldMap\(\)[^{]*\{([\s\S]*?)\n  \}/)?.[1];
assert.ok(fetchBody, "side-effect-free fetchWorldMap exists");
assert.doesNotMatch(fetchBody, /applyWorldMap|reconcileAvatarPos|lastMap\s*=|syncLocations/);
assert.match(main, /if \(user\.username !== username\) \{[\s\S]*?location\.reload\(\);\s*\} else \{\s*syncHub\(\)\.restart\(\);/);
console.log("PASS client3d_worldmap_guards");
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(unhandled, [], "no unhandledRejection");
console.log("sync client: all cases passed");
