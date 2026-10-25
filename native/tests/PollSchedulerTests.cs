using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Sync;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="PollScheduler"/> (port of packages/player-ui/src/pollCore.ts) on a simulated clock. Every expected
/// time is derived by hand from the rules in the comments — never recorded from a run.
///
/// The harness: a <see cref="ManualClock"/> + <see cref="TimerQueue"/>; <c>Sim.RunTo</c> advances to the next
/// event (a pending timer's due time, or the next whole second) and calls <c>Tick()</c> on every whole second,
/// like the host's 1-s timer started at t = 0. Timers fire before the tick of the same instant.
/// </summary>
public class PollSchedulerTests
{
    /// <summary>A fake hub: the tests flip <see cref="Connected"/>, bump the generation, fire topics.</summary>
    private sealed class FakeHub : ISyncHub
    {
        private readonly List<(IReadOnlyCollection<string> Topics, Action Fn)> _topics = new();
        private readonly List<Action> _states = new();
        public bool Connected { get; private set; }
        public int Generation { get; private set; }

        public IDisposable OnTopics(IReadOnlyCollection<string> topics, Action fn)
        {
            var l = (topics, fn);
            _topics.Add(l);
            return new Gone(() => _topics.Remove(l));
        }

        public IDisposable OnState(Action fn)
        {
            _states.Add(fn);
            return new Gone(() => _states.Remove(fn));
        }

        public void SetConnected(bool v)
        {
            Connected = v;
            foreach (var s in _states.ToList()) s();
        }

        /// <summary>syncHub's <c>invalidate()</c>: generation + state + every listener.</summary>
        public void Invalidate()
        {
            Generation++;
            foreach (var s in _states.ToList()) s();
            foreach (var (_, fn) in _topics.ToList()) fn();
        }

        public void Topic(string t)
        {
            foreach (var (topics, fn) in _topics.ToList())
                if (topics.Contains(t)) fn();
        }

        private sealed class Gone : IDisposable
        {
            private readonly Action _fn;
            public Gone(Action fn) => _fn = fn;
            public void Dispose() => _fn();
        }
    }

    /// <summary>Simulated host: clock, timers, 1-s ticks, and the fetches as hand-completed tasks.</summary>
    private sealed class Sim
    {
        public readonly ManualClock Clock = new();
        public readonly TimerQueue Timers;
        public readonly FakeHub Hub = new();
        public readonly PollScheduler Core;
        /// <summary>Start time of every fetch (ms).</summary>
        public readonly List<double> Starts = new();
        public readonly List<TaskCompletionSource<string>> Pending = new();
        public readonly List<(string? Data, Exception? Error)> Calls = new();
        /// <summary>null: the fetch stays open (the test completes it); else completed at once with this outcome.</summary>
        public Func<int, bool?> AutoOk = _ => null;

        public Sim(bool withHub = true)
        {
            Timers = new TimerQueue(() => Clock.Ms);
            Core = new PollScheduler(Timers, withHub ? Hub : null);
        }

        public void Subscribe(PollSpec? spec = null)
            => Core.Subscribe("w", Fetch, spec ?? PollSpec.Worldmap3d, (d, e) => Calls.Add((d, e)));

        private Task<string> Fetch()
        {
            int n = Starts.Count;
            Starts.Add(Clock.Ms);
            var outcome = AutoOk(n);
            if (outcome == true) return Task.FromResult($"map{n}");
            if (outcome == false) return Task.FromException<string>(new InvalidOperationException($"fail{n}"));
            var tcs = new TaskCompletionSource<string>();
            Pending.Add(tcs);
            return tcs.Task;
        }

        /// <summary>
        /// Advance to <paramref name="until"/> ms, event by event: a pending timer fires at its due time, and
        /// Tick() runs on every whole second (the host's 1-s timer, started at t = 0).
        /// </summary>
        public void RunTo(double until)
        {
            while (true)
            {
                Timers.Pump();
                double nextTick = Math.Floor(Clock.Ms / 1000) * 1000 + 1000;
                double next = Math.Min(nextTick, Timers.NextDue ?? double.PositiveInfinity);
                if (next > until)
                {
                    Clock.Set(until);
                    Timers.Pump();
                    return;
                }
                Clock.Set(next);
                Timers.Pump();
                if (Clock.Ms % 1000 == 0 && next == nextTick) Core.Tick();
            }
        }
    }

    [Fact]
    public void FirstSubscriberFetchesAtOnce()
    {
        var sim = new Sim { AutoOk = _ => true };
        sim.Subscribe();
        Assert.Equal(new double[] { 0 }, sim.Starts);
        Assert.Single(sim.Calls);
        Assert.Equal("map0", sim.Calls[0].Data);
        Assert.Null(sim.Calls[0].Error);
        // A synchronously completed fetch must not leave the entry "in flight" (the JS never runs inline).
        Assert.False(sim.Core.InFlight("w"));
    }

    /// <summary>
    /// Without push the worldmap polls every 3000 ms: start at 0, the tick at 3000 sees now − 0 = 3000 ≥ 3000.
    /// </summary>
    [Fact]
    public void PollsEveryThreeSecondsWithoutPush()
    {
        var sim = new Sim(withHub: false) { AutoOk = _ => true };
        sim.Subscribe();
        sim.RunTo(9500);
        Assert.Equal(new double[] { 0, 3000, 6000, 9000 }, sim.Starts);
    }

    /// <summary>
    /// The brief's backoff sequence. run0 at 0 succeeds (factor 1 → interval 3000); every later run fails:
    /// factor 2 → 6000, 4 → 12000, 8 → 24000, 16 → 48000, 32 → min(96000, max(3000, 60000)) = 60000,
    /// 64 → 60000. Gaps: 3, 6, 12, 24, 48, 60, 60 s → starts 0, 3, 9, 21, 45, 93, 153, 213 s. A success at
    /// 213 s resets the factor to 1: the next start is 216 s.
    /// </summary>
    [Fact]
    public void BackoffDoublesToTheMinuteAndResetsOnSuccess()
    {
        var sim = new Sim(withHub: false) { AutoOk = n => n == 0 || n >= 7 };
        sim.Subscribe();
        sim.RunTo(216_500);
        var gaps = sim.Starts.Zip(sim.Starts.Skip(1), (a, b) => (b - a) / 1000).ToArray();
        Assert.Equal(new double[] { 0, 3000, 9000, 21000, 45000, 93000, 153000, 213000, 216000 }, sim.Starts);
        Assert.Equal(new double[] { 3, 6, 12, 24, 48, 60, 60, 3 }, gaps);
        Assert.Equal(1, sim.Core.ErrorFactor("w"));
        // Every failed run told the subscriber with the error and the LAST GOOD data (pollCore keeps lastData).
        Assert.All(sim.Calls.Skip(1).Take(6), c => Assert.Equal(("map0", true), (c.Data, c.Error is not null)));
    }

    /// <summary>
    /// The scheduler's interval equals the shared vectors' answers for the worldmap: [P1a] 3000 without push,
    /// [P1b] 6000 with push, [P1c] 6000 after one failure, [P1d] 60000 at factor 64.
    /// </summary>
    [Fact]
    public void IntervalsAgreeWithTheSharedVectors()
    {
        var vectors = VectorFile.Load("poll_schedule").Cases.Where(c => c.Fn == "pollIntervalMs")
                                .ToDictionary(c => c.Label[..5], c => VectorCompare.Num(c.Expect));
        var sim = new Sim { AutoOk = n => n == 0 };
        sim.Subscribe();
        Assert.Equal(vectors["[P1a]"], sim.Core.IntervalMs("w"));
        sim.Hub.SetConnected(true);
        Assert.Equal(vectors["[P1b]"], sim.Core.IntervalMs("w"));
        sim.Hub.SetConnected(false);
        sim.RunTo(3000);   // run1 fails: factor 2
        Assert.Equal(vectors["[P1c]"], sim.Core.IntervalMs("w"));
        sim.RunTo(400_000);   // factor saturates at 64
        Assert.Equal(64, sim.Core.ErrorFactor("w"));
        Assert.Equal(vectors["[P1d]"], sim.Core.IntervalMs("w"));
    }

    /// <summary>With the stream connected the base is the pushed 6000 ms: starts 0, 6000, 12000.</summary>
    [Fact]
    public void PushStretchesTheIntervalToSixSeconds()
    {
        var sim = new Sim { AutoOk = _ => true };
        sim.Hub.SetConnected(true);
        sim.Subscribe();
        sim.RunTo(14_000);
        Assert.Equal(new double[] { 0, 6000, 12000 }, sim.Starts);
    }

    /// <summary>
    /// A topic fetches at once, but never sooner than minSpacing (3000) after the last start: run at 0, topic at
    /// 1000 → delay 0 + 3000 − 1000 = 2000 → the trailing timer starts the fetch at 3000. A second topic at 1500
    /// joins the same timer (one trailing timer). With push connected (6000) the next tick-driven run would have
    /// been 6000. A topic at 4500 is 1500 after the 3000 start → trailing at 6000; a topic at 9500 (last start
    /// 6000, 3500 ago) runs at once.
    /// </summary>
    [Fact]
    public void TopicFetchesAtOnceButKeepsTheMinimumSpacing()
    {
        var sim = new Sim { AutoOk = _ => true };
        sim.Hub.SetConnected(true);
        sim.Subscribe();
        sim.RunTo(1000);
        sim.Hub.Topic("presence");
        sim.RunTo(1500);
        sim.Hub.Topic("world");
        sim.Hub.Topic("notices");   // not subscribed: nothing
        sim.RunTo(4500);
        Assert.Equal(new double[] { 0, 3000 }, sim.Starts);
        sim.Hub.Topic("presence");
        sim.RunTo(9500);
        // 6000: the trailing timer; the tick at 9000 sees 9000 − 6000 = 3000 < 6000 → nothing.
        Assert.Equal(new double[] { 0, 3000, 6000 }, sim.Starts);
        sim.Hub.Topic("world");
        Assert.Equal(new double[] { 0, 3000, 6000, 9500 }, sim.Starts);
    }

    /// <summary>
    /// Single flight: the fetch started at 0 stays open; ticks at 3000..5000 start nothing; a topic at 4200 only
    /// marks the entry dirty. Completed at 5500, the dirty entry signals: 0 + 3000 − 5500 &lt; 0 → a run at 5500.
    /// </summary>
    [Fact]
    public void OneRequestAtATimeAndADirtyEntryRefetchesAfterIt()
    {
        var sim = new Sim();
        sim.Subscribe();
        sim.RunTo(4200);
        sim.Hub.Topic("presence");
        sim.RunTo(5500);
        Assert.Equal(new double[] { 0 }, sim.Starts);
        sim.Pending[0].SetResult("a");
        Assert.Equal(new double[] { 0, 5500 }, sim.Starts);
        Assert.Equal("a", sim.Calls.Single().Data);
    }

    /// <summary>
    /// A resync while a request is in flight: the result fetched under generation 0 is DROPPED (no callback),
    /// and the entry refetches. Run at 0, invalidate at 1000 (dirty — in flight), completion at 1200 → the
    /// generation differs → dirty → signal: 0 + 3000 − 1200 = 1800 → trailing run at 3000. Its answer is
    /// delivered.
    /// </summary>
    [Fact]
    public void ResyncDiscardsTheResultInFlightAndRefetches()
    {
        var sim = new Sim();
        sim.Subscribe();
        sim.RunTo(1000);
        sim.Hub.Invalidate();
        sim.RunTo(1200);
        sim.Pending[0].SetResult("stale");
        Assert.Empty(sim.Calls);
        Assert.Equal(new double[] { 0 }, sim.Starts);
        sim.RunTo(3000);
        Assert.Equal(new double[] { 0, 3000 }, sim.Starts);
        sim.Pending[1].SetResult("fresh");
        Assert.Equal("fresh", sim.Calls.Single().Data);
    }

    /// <summary>
    /// A resync between polls (nothing in flight): the cached result goes, the topic listener of the entry signals
    /// it — last start 0, invalidate at 2000 → trailing run at 3000, which the tick at 3000 would have started
    /// anyway; at 7000 (last 3000, push off) → nothing extra before the tick at 6000.
    /// </summary>
    [Fact]
    public void ResyncBetweenPollsRefetchesWithinTheSpacing()
    {
        var sim = new Sim { AutoOk = _ => true };
        sim.Subscribe();
        sim.RunTo(2000);
        sim.Hub.Invalidate();
        sim.RunTo(6500);
        Assert.Equal(new double[] { 0, 3000, 6000 }, sim.Starts);
        Assert.Equal(3, sim.Calls.Count);
    }

    /// <summary>A fetcher that throws synchronously counts as a failed request (factor 2), not as a crash.</summary>
    [Fact]
    public void AThrowingFetcherIsAFailure()
    {
        var clock = new ManualClock();
        var core = new PollScheduler(new TimerQueue(() => clock.Ms), null);
        var calls = new List<Exception?>();
        core.Subscribe<string>("w", () => throw new InvalidOperationException("boom"), PollSpec.Worldmap3d, (_, e) => calls.Add(e));
        Assert.IsType<InvalidOperationException>(Assert.Single(calls));
        Assert.Equal(2, core.ErrorFactor("w"));
        Assert.False(core.InFlight("w"));
    }

    /// <summary>Leaving stops the polls: no start after the subscription is disposed.</summary>
    [Fact]
    public void UnsubscribedEntriesStop()
    {
        var clock = new ManualClock();
        var timers = new TimerQueue(() => clock.Ms);
        var core = new PollScheduler(timers, null);
        int starts = 0;
        var sub = core.Subscribe("w", () => { starts++; return Task.FromResult(1); }, PollSpec.Worldmap3d, (_, _) => { });
        sub.Dispose();
        for (int t = 1; t <= 10; t++)
        {
            clock.Set(t * 1000);
            core.Tick();
        }
        Assert.Equal(1, starts);
    }
}
