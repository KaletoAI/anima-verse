using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Overview;

namespace AnimaNative.Sync;

/// <summary>
/// The push side the scheduler listens to — <c>HubLike</c> of pollCore.ts, implemented by
/// <see cref="SyncStream"/>.
/// </summary>
public interface ISyncHub
{
    /// <summary>The stream is up (the polls stretch to their pushed interval).</summary>
    bool Connected { get; }
    /// <summary>Bumped by every resync after the first: results fetched under an older generation are dropped.</summary>
    int Generation { get; }
    IDisposable OnTopics(IReadOnlyCollection<string> topics, Action fn);
    IDisposable OnState(Action fn);
}

/// <summary>
/// <c>EndpointSpec</c> of pollCore.ts: the base interval, the interval while the push stream is connected,
/// the minimum spacing between two starts, and the push topics that trigger an early fetch.
/// </summary>
public sealed record PollSpec(double IntervalMs, double? PushedIntervalMs = null, double? MinSpacingMs = null,
                              IReadOnlyList<string>? Topics = null, bool RunHidden = false)
{
    /// <summary><c>SYNC_ENDPOINTS.worldmap3d</c> (packages/player-ui/src/syncEndpoints.ts).</summary>
    public static readonly PollSpec Worldmap3d = new(3000, 6000, 3000, new[] { "presence", "world" }, RunHidden: true);
}

/// <summary>
/// Port of <c>createPollCore</c> (packages/player-ui/src/pollCore.ts) — the browser's polling state machine:
///   • the host ticks it every <see cref="PollSchedule.TickMs"/>; an entry is fetched when
///     <c>now − lastStart ≥ interval</c>, interval = <see cref="PollSchedule.IntervalMs"/>(base, minSpacing,
///     errorFactor) with base = the pushed interval while the hub is connected;
///   • the error factor doubles per failure up to 64 and goes back to 1 on success;
///   • single-flight: one request per entry at a time;
///   • a matching push topic (<see cref="Signal"/>) fetches at once — but never sooner than minSpacing after the
///     last start: a trailing timer covers the rest;
///   • a hub generation change (a resync) drops every cached result, discards results of requests that were in
///     flight, and refetches.
/// Not ported: <c>refresh(key)</c> with its waiters and the hidden-page handling (<c>hidden()</c>/<c>visible()</c>)
/// — the native client has no refresh caller and its only entry (<see cref="PollSpec.Worldmap3d"/>) runs hidden.
/// Single-threaded: call it, complete the fetch tasks and pump the clock from one thread.
/// </summary>
public sealed class PollScheduler
{
    private sealed class Sub
    {
        public required Func<Task<object?>> Fetcher;
        public required PollSpec Spec;
        public required Action<object?, Exception?> Cb;
    }

    private sealed class Entry
    {
        public readonly List<Sub> Subs = new();
        public double LastStart = double.NegativeInfinity;
        public Task? InFlight;
        public bool Dirty;
        public object? Trailing;
        public double ErrorFactor = 1;
        public object? LastData;
        public Exception? LastError;
        public bool HasData;
        public int DataGen;
        public IDisposable? OffTopics;
    }

    private readonly ISyncClock _env;
    private readonly ISyncHub? _hub;
    private readonly Dictionary<string, Entry> _entries = new();
    private int _gen;

    public PollScheduler(ISyncClock env, ISyncHub? hub)
    {
        _env = env;
        _hub = hub;
        _gen = Generation();
        hub?.OnState(OnHubState);
    }

    private int Generation() => _hub?.Generation ?? 0;

    private static double Spacing(Entry e) => Math.Max(0, e.Subs.Count == 0 ? 0 : e.Subs.Max(s => s.Spec.MinSpacingMs ?? 0));

    private double Interval(Entry e)
    {
        double b = e.Subs.Min(s => _hub?.Connected == true ? s.Spec.PushedIntervalMs ?? s.Spec.IntervalMs : s.Spec.IntervalMs);
        return PollSchedule.IntervalMs(b, Spacing(e), e.ErrorFactor);
    }

    /// <summary>The interval the entry is polled at right now (ms), or null for an unknown/empty key.</summary>
    public double? IntervalMs(string key)
        => _entries.TryGetValue(key, out var e) && e.Subs.Count > 0 ? Interval(e) : null;

    /// <summary>The entry's current error factor (1 after a success).</summary>
    public double ErrorFactor(string key) => _entries.TryGetValue(key, out var e) ? e.ErrorFactor : 1;

    /// <summary>A request of the entry is running.</summary>
    public bool InFlight(string key) => _entries.TryGetValue(key, out var e) && e.InFlight is not null;

    private void CancelTrailing(Entry e)
    {
        if (e.Trailing is not null) _env.ClearTimeout(e.Trailing);
        e.Trailing = null;
    }

    private static void Notify(Sub s, Entry e)
    {
        try { s.Cb(e.LastData, e.LastError); }
        catch (Exception) { /* pollCore logs "Polling subscriber failed" and goes on; the subscriber logs its own */ }
    }

    private void SignalEntry(Entry e)
    {
        e.Dirty = true;
        if (e.Subs.Count == 0) return;
        if (e.InFlight is not null) return;
        double delay = e.LastStart + Spacing(e) - _env.Now();
        if (delay <= 0) { Run(e); return; }
        if (e.Trailing is null)
            e.Trailing = _env.SetTimeout(() =>
            {
                e.Trailing = null;
                SignalEntry(e);
            }, delay);
    }

    private void Run(Entry e)
    {
        if (e.InFlight is not null) return;
        var sub = e.Subs.LastOrDefault();
        if (sub is null) return;
        CancelTrailing(e);
        e.Dirty = false;
        e.LastStart = _env.Now();
        int startedGen = Generation();
        Task<object?> fetched;
        try { fetched = sub.Fetcher(); }
        catch (Exception ex) { fetched = Task.FromException<object?>(ex); }
        // The marker goes in BEFORE the continuation can run: a fetch that completed synchronously would
        // otherwise clear InFlight first and then be overwritten by it (JS promises never run inline).
        var done = new TaskCompletionSource(TaskCreationOptions.None);
        e.InFlight = done.Task;
        fetched.ContinueWith(t => Complete(e, t, startedGen, done), CancellationToken.None,
                             TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
    }

    private void Complete(Entry e, Task<object?> t, int startedGen, TaskCompletionSource done)
    {
        bool current = Generation() == startedGen;
        if (current)
        {
            if (t.IsCompletedSuccessfully)
            {
                e.LastData = t.Result;
                e.LastError = null;
                e.HasData = true;
                e.DataGen = startedGen;
                e.ErrorFactor = PollSchedule.NextErrorFactor(e.ErrorFactor, true);
            }
            else
            {
                e.LastError = t.Exception?.InnerException ?? t.Exception ?? (Exception)new TaskCanceledException();
                e.DataGen = startedGen;
                e.ErrorFactor = PollSchedule.NextErrorFactor(e.ErrorFactor, false);
            }
        }
        e.InFlight = null;
        if (Generation() != startedGen) e.Dirty = true;
        else
            foreach (var s in e.Subs.ToList())
                if (e.Subs.Contains(s)) Notify(s, e);
        done.TrySetResult();
        if (e.Dirty) SignalEntry(e);
    }

    private void Bind(Entry e)
    {
        e.OffTopics?.Dispose();
        var topics = e.Subs.SelectMany(s => s.Spec.Topics ?? Array.Empty<string>()).Distinct().ToList();
        e.OffTopics = topics.Count > 0 && _hub is not null ? _hub.OnTopics(topics, () => SignalEntry(e)) : null;
    }

    private void OnHubState()
    {
        int next = Generation();
        if (next == _gen) return;   // intervals are computed from the live hub state
        _gen = next;
        foreach (var e in _entries.Values)
        {
            e.LastData = null;
            e.LastError = null;
            e.HasData = false;
            e.Dirty = true;
            if (!e.Subs.Any(s => s.Spec.Topics is { Count: > 0 })) SignalEntry(e);
        }
    }

    /// <summary>
    /// <c>subscribe(key, fetcher, spec, cb)</c>: cb gets <c>(data, null)</c> after a good request and
    /// <c>(lastData, error)</c> after a failed one. A first subscriber fetches at once. Dispose to leave.
    /// </summary>
    public IDisposable Subscribe<T>(string key, Func<Task<T>> fetcher, PollSpec spec, Action<T?, Exception?> cb)
    {
        if (!_entries.TryGetValue(key, out var e))
        {
            e = new Entry { DataGen = _gen };
            _entries[key] = e;
        }
        var sub = new Sub
        {
            // Boxed WITHOUT an await: the result stays on the thread that completed the fetch (the host's).
            Fetcher = () => fetcher().ContinueWith(
                t => t.IsCompletedSuccessfully ? (object?)t.Result
                     : throw (t.Exception?.InnerException ?? t.Exception ?? (Exception)new TaskCanceledException()),
                CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default),
            Spec = spec,
            Cb = (d, err) => cb(d is T t ? t : default, err),
        };
        e.Subs.Add(sub);
        Bind(e);
        if (e.DataGen == Generation() && (e.HasData || e.LastError is not null)) Notify(sub, e);
        if (e.InFlight is null && (e.Dirty || !e.HasData || e.DataGen != Generation())) SignalEntry(e);
        return new Leave(() =>
        {
            e.Subs.Remove(sub);
            Bind(e);
            if (e.Subs.Count == 0)
            {
                if (e.Trailing is not null) e.Dirty = true;
                CancelTrailing(e);
            }
        });
    }

    /// <summary><c>signal(key)</c>: fetch as soon as the minimum spacing allows.</summary>
    public void Signal(string key)
    {
        if (_entries.TryGetValue(key, out var e)) SignalEntry(e);
    }

    /// <summary><c>tick()</c>: start every entry whose interval has run out. The host calls it every second.</summary>
    public void Tick()
    {
        foreach (var e in _entries.Values.ToList())
        {
            if (e.Subs.Count == 0 || e.InFlight is not null || _env.Now() - e.LastStart < Interval(e)) continue;
            Run(e);
        }
    }

    private sealed class Leave : IDisposable
    {
        private Action? _fn;
        public Leave(Action fn) => _fn = fn;
        public void Dispose() => Interlocked.Exchange(ref _fn, null)?.Invoke();
    }
}
