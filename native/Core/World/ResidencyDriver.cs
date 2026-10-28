using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Sync;
using ResidencyRing = AnimaNative.World.Ring;

namespace AnimaNative.World;

/// <summary>The adapter owns rollback; an aborted step must leave its source ring intact (Task 44 / RS).</summary>
public enum ResidencyStep { Ok, Aborted, Failed }

/// <summary>
/// Task 44 / E6-T4: import-free residency.ts lifecycle port. Each id walks gone ↔ far ↔ near, with
/// generation invalidation across awaits, mounted-payload teardown, and a tail covering the ENTIRE old
/// lifecycle before rediscovery can mount. Settled includes rebuilds and retries; HasJob excludes retry
/// waits. Use on one synchronization context, as FocusQueue and TimerQueue require. Adapters check alive
/// after asynchronous work and roll back before returning Aborted; only a committed near step publishes ready.
/// </summary>
public sealed class ResidencyDriver<P>
{
    private sealed class Entry
    {
        public required string Id;
        public required P Payload, Mounted;
        public ResidencyRing Ring = ResidencyRing.Gone, Target;
        public int Gen, Failures;
        public bool Stale, Dropped;
        public Task? Job, Previous;
        public object? Retry;
        public required Func<double> Distance;
        public readonly List<TaskCompletionSource> Waiters = new();
        public readonly TaskCompletionSource Finished = new();
    }

    private static readonly double[] RetryMs = { 5000, 10000, 20000, 40000, 60000 };
    private readonly HashSet<Task> _jobs = new();
    private readonly Dictionary<string, Entry> _entries = new();
    private readonly Dictionary<string, Task> _tails = new();
    private readonly Func<string, P, ResidencyRing, Func<bool>, Task<ResidencyStep>> _up;
    private readonly Action<string, P, ResidencyRing> _down;
    private readonly FocusQueue _queue;
    private readonly ISyncClock _timers;

    public ResidencyDriver(Func<string, P, ResidencyRing, Func<bool>, Task<ResidencyStep>> up,
        Action<string, P, ResidencyRing> down, FocusQueue queue, ISyncClock timers)
        => (_up, _down, _queue, _timers) = (up, down, queue, timers);

    private static int Rank(ResidencyRing r) => r switch { ResidencyRing.Gone => 0, ResidencyRing.Far => 1, _ => 2 };
    public ResidencyRing Ring(string id) => _entries.TryGetValue(id, out var e) ? e.Ring : ResidencyRing.Gone;
    public ResidencyRing Target(string id) => _entries.TryGetValue(id, out var e) ? e.Target : ResidencyRing.Gone;
    /// <summary>The current pass only; boot waits for work without waiting through a retry delay.</summary>
    public Task CurrentJob(string id) => _entries.GetValueOrDefault(id)?.Job ?? Task.CompletedTask;
    public bool HasJob(string id) => _entries.TryGetValue(id, out var e) && e.Job is not null;

    /// <summary>Drain active passes (including dropped predecessors and immediate follow-ups), excluding retry delays.</summary>
    public async Task WhenIdle()
    {
        while (_jobs.Count > 0) await Task.WhenAll(_jobs.ToArray());
    }

    public Task Settled(string id)
    {
        if (!_entries.TryGetValue(id, out var e) || (e.Job is null && !e.Stale && e.Ring == e.Target)) return Task.CompletedTask;
        var waiter = new TaskCompletionSource();
        e.Waiters.Add(waiter);
        return waiter.Task;
    }

    public void Want(string id, P payload, ResidencyRing target, Func<double> distance)
    {
        if (!_entries.TryGetValue(id, out var e) || e.Dropped)
        {
            if (target == ResidencyRing.Gone) return;
            e = new Entry { Id = id, Payload = payload, Mounted = payload, Target = target, Distance = distance,
                            Previous = _tails.GetValueOrDefault(id) };
            _tails[id] = e.Finished.Task;
            _entries[id] = e;
        }
        else
        {
            e.Payload = payload;
            e.Distance = distance;
            e.Gen++;
            if (e.Target != target) { ClearRetry(e); e.Target = target; }
        }
        if (e.Retry is null && (e.Ring != e.Target || e.Stale)) Schedule(e);
        FinalizeEntry(e);
    }

    public void Rebuild(string id, P payload)
    {
        if (!_entries.TryGetValue(id, out var e) || e.Dropped) return;
        e.Payload = payload; e.Gen++; e.Stale = true;
        ClearRetry(e); Schedule(e);
    }

    public void Drop(string id)
    {
        if (!_entries.TryGetValue(id, out var e)) return;
        e.Gen++; e.Dropped = true; e.Target = ResidencyRing.Gone;
        ClearRetry(e);
        if (e.Ring != e.Target || e.Stale) Schedule(e);
        FinalizeEntry(e);
    }

    private void ClearRetry(Entry e)
    {
        if (e.Retry is not null) _timers.ClearTimeout(e.Retry);
        e.Retry = null;
    }

    private void FinalizeEntry(Entry e)
    {
        if (e.Job is not null || e.Stale || e.Ring != e.Target) return;
        if (e.Ring == ResidencyRing.Gone)
        {
            if (_entries.GetValueOrDefault(e.Id) == e) _entries.Remove(e.Id);
            if (_tails.GetValueOrDefault(e.Id) == e.Finished.Task) _tails.Remove(e.Id);
            e.Finished.TrySetResult();
        }
        var waiters = e.Waiters.ToArray(); e.Waiters.Clear();
        foreach (var w in waiters) w.TrySetResult();
    }

    private void Schedule(Entry e)
    {
        if (e.Job is not null) return;
        var finish = new TaskCompletionSource();
        e.Job = finish.Task; _jobs.Add(finish.Task);
        _ = Run(e, finish);
    }

    private async Task Run(Entry e, TaskCompletionSource finish)
    {
        // A successor waiting on an old mount must not consume one of the two queue slots.
        if (e.Previous is not null) await e.Previous;
        int? failedGen = null;
        await _queue.Push(new FocusJob(() => e.Distance(), async () =>
        {
            while (true)
            {
                if (e.Stale || e.Dropped)
                {
                    while (e.Ring != ResidencyRing.Gone) Down(e);
                    e.Stale = false;
                    if (e.Dropped) break;
                }
                if (e.Ring == e.Target) break;
                if (Rank(e.Ring) > Rank(e.Target)) { Down(e); continue; }
                int gen = e.Gen;
                var payload = e.Payload;
                var from = e.Ring;
                bool Alive() => _entries.GetValueOrDefault(e.Id) == e && !e.Dropped && e.Gen == gen;
                ResidencyStep result;
                try { result = await _up(e.Id, payload, from, Alive); }
                catch { result = ResidencyStep.Failed; }
                if (result == ResidencyStep.Failed)
                {
                    if (Alive()) { failedGen = e.Gen; break; }
                    continue;
                }
                if (result == ResidencyStep.Aborted) continue;
                e.Mounted = payload;
                e.Ring = from == ResidencyRing.Gone ? ResidencyRing.Far : ResidencyRing.Near;
                e.Failures = 0;
            }
        }, $"ring:{e.Id}"));
        e.Job = null;
        if (e.Stale || e.Ring != e.Target)
        {
            if (failedGen == e.Gen && !e.Stale && !e.Dropped && Rank(e.Target) > Rank(e.Ring))
            {
                var ms = RetryMs[Math.Min(e.Failures++, RetryMs.Length - 1)];
                e.Retry = _timers.SetTimeout(() => { e.Retry = null; Schedule(e); }, ms);
            }
            else Schedule(e);
        }
        FinalizeEntry(e);
        _jobs.Remove(finish.Task);
        finish.TrySetResult();
    }

    private void Down(Entry e)
    {
        var from = e.Ring;
        _down(e.Id, e.Mounted, from);
        e.Ring = from == ResidencyRing.Near ? ResidencyRing.Far : ResidencyRing.Gone;
    }
}
