using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Figures;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The figure runtime rules that are view state, not spec (no shared vector — e5-inventory § 3.3), checked against
/// hand derivations from the browser constants: tier hysteresis 25/35 (main.ts <c>FIGURE_TIER_NEAR/FAR</c>, npcs.ts
/// <c>tickFigureTiers</c>), the focus queue (game/focusQueue.ts), the stand-in paces and the action table
/// (figures.ts <c>Figure.play</c>, <c>CLIP_SYNONYMS</c>), the set chain (<c>clipsFor</c>).
/// </summary>
public class FigureRuntimeRulesTests
{
    /// <summary>
    /// From full: 30 (band, keep) → full, 24 (&lt; 25) → full, 30 → full, 36 (&gt; 35) → low; then 30 → low (keep),
    /// 25 (not &lt; 25) → low, 24.9 → full, 35 (not &gt; 35) → full, 35.1 → low. The player-driven figure is always full.
    /// </summary>
    [Fact]
    public void TierHysteresisByHand()
    {
        var seq = new[] { 30, 24, 30, 36, 30, 25, 24.9, 35, 35.1 };
        var want = new[] { "Full", "Full", "Full", "Low", "Low", "Low", "Full", "Full", "Low" };
        var tier = FigureTier.Full;
        var got = new List<string>();
        foreach (var d in seq)
        {
            tier = FigureTiers.Next(tier, d);
            got.Add(tier.ToString());
        }
        Assert.Equal(want, got);
        Assert.Equal(FigureTier.Full, FigureTiers.Next(FigureTier.Low, 500, playerDriven: true));
        Assert.Equal(1.0, FigureTiers.TickS);
    }

    /// <summary>Stand-in paces: idle family missing → 0.1, run family missing → 1.5, otherwise 1 (by family).</summary>
    [Theory]
    [InlineData("idle", "", 0.1)]
    [InlineData("idle", "stand-relaxed", 0.1)]
    [InlineData("idle", "idle-loop", 1)]
    [InlineData("", "walk", 0.1)]          // an empty kind is the idle family
    [InlineData("run", "walk", 1.5)]
    [InlineData("run-fast", "run", 1)]     // run-cmu served from run counts as the real thing
    [InlineData("run", "", 1.5)]
    [InlineData("walk", "stand-relaxed", 1)]
    public void StandInPace(string want, string chosen, double pace)
        => Assert.Equal(pace, ClipLibraryRules.StandInPace(want, chosen));

    /// <summary>
    /// Clip names [Stand-Relaxed, walk, waiting, reading]: lower-cased actions in order, then the aliases — idle via
    /// 'stand' (⊂ stand-relaxed; no exact or substring 'idle'), walk is literal, run/sit/lie/dance/wave find nothing
    /// ('waiting' contains none of their needles). A later clip of the same lower-cased name replaces the clip, keeps
    /// the place.
    /// </summary>
    [Fact]
    public void ActionTableByHand()
    {
        var actions = ClipLibraryRules.BindActions(new[] { "Stand-Relaxed", "walk", "waiting", "reading" });
        Assert.Equal(new[] { ("stand-relaxed", "Stand-Relaxed"), ("walk", "walk"), ("waiting", "waiting"), ("reading", "reading"),
                             ("idle", "Stand-Relaxed") }, actions);
        var dup = ClipLibraryRules.BindActions(new[] { "Walk", "sit", "walk", "sleeping" });
        Assert.Equal(new[] { ("walk", "walk"), ("sit", "sit"), ("sleeping", "sleeping"), ("lie", "sleeping") }, dup);
    }

    /// <summary>Set chain [female] + '': per kind the first file along it; a kind only in another set is skipped.</summary>
    [Fact]
    public void SetChainByHand()
    {
        var sources = new List<ClipSourceEntry>
        {
            new("walk", "", "w"), new("walk", "female", "wf"), new("sit", "male", "sm"), new("idle", "", "i"), new("idle", "female", "if"),
        };
        var index = ClipLibraryRules.CommitInListOrder(sources, sources.Select(s => s.Url).ToList(), new UrlOps());
        Assert.Equal(new[] { "walk/female", "sit/male", "idle/female" },
                     ClipLibraryRules.ClipsFor(index, new[] { "female", "male" }).Select(x => $"{x.Kind}/{x.Set}"));
        Assert.Equal(new[] { "walk/", "idle/" }, ClipLibraryRules.ClipsFor(index, null).Select(x => $"{x.Kind}/{x.Set}"));
    }

    private sealed class UrlOps : IClipCommitOps<string>
    {
        public void SetFlags(string c, ClipSourceEntry s) { }
        public bool IsPair(string kind) => false;
        public object? PairRoot(string c) => null;
        public string Rename(string c, string kind) => c;
    }

    /// <summary>
    /// Width 1, six jobs pushed in one pass: the avatar first whatever its distance, then by distance (3, 1, 2 → 1,
    /// 2, 3), a tie by submission order, NaN as ∞ last; never more than the width at once.
    /// </summary>
    [Fact]
    public void FocusQueueOrderByHand() => SingleThread.Run(FocusQueueOrderBody);

    private static async Task FocusQueueOrderBody()
    {
        var queue = new FocusQueue(1);
        var order = new List<string>();
        int running = 0, peak = 0;
        Task Push(string name, double d, bool avatar = false) => queue.Push(new FocusJob(() => d, async () =>
        {
            lock (order) { order.Add(name); peak = Math.Max(peak, ++running); }
            await Task.Yield();
            lock (order) running--;
        }, name, avatar));
        var all = new[] { Push("nan", double.NaN), Push("far", 3), Push("near", 1), Push("avatar", 9, avatar: true), Push("mid", 2), Push("mid2", 2) };
        await Task.WhenAll(all);
        Assert.Equal(new[] { "avatar", "near", "mid", "mid2", "far", "nan" }, order);
        Assert.Equal(1, peak);
    }

    /// <summary>Width 3: at most three run at once, the three nearest first; a cancelled job never runs.</summary>
    [Fact]
    public void FocusQueueWidthAndCancel() => SingleThread.Run(FocusQueueWidthBody);

    private static async Task FocusQueueWidthBody()
    {
        var queue = new FocusQueue(3);
        var gate = new TaskCompletionSource();
        var order = new List<string>();
        int running = 0, peak = 0;
        Task<bool> Push(string name, double d) => queue.Push(new FocusJob(() => d, async () =>
        {
            lock (order) { order.Add(name); peak = Math.Max(peak, ++running); }
            await gate.Task;
            lock (order) running--;
        }, name));
        var jobs = new List<Task<bool>> { Push("a", 1), Push("b", 2), Push("c", 3), Push("nan", double.NaN), Push("d", 4) };
        for (int i = 0; i < 10; i++) await Task.Yield();
        Assert.Equal(3, queue.Active);
        jobs.Add(Push("x", 0.5));   // waits behind the three running ones
        Assert.True(queue.Cancel("x"));
        gate.SetResult();
        var done = await Task.WhenAll(jobs);
        Assert.Equal(3, peak);
        Assert.Equal(new[] { "a", "b", "c", "d", "nan" }, order);
        Assert.False(done[^1]);
    }
}

/// <summary>
/// Runs an async test body on ONE thread with a posting synchronisation context — the model of Godot's main thread
/// (and the browser's event loop) the <see cref="FocusQueue"/> is written for: continuations queue up behind the
/// synchronous code that scheduled them, never beside it.
/// </summary>
internal sealed class SingleThread : System.Threading.SynchronizationContext
{
    private readonly System.Collections.Concurrent.BlockingCollection<(System.Threading.SendOrPostCallback, object?)> _queue = new();

    public override void Post(System.Threading.SendOrPostCallback d, object? state) => _queue.Add((d, state));

    public static void Run(Func<Task> body)
    {
        var previous = Current;
        var ctx = new SingleThread();
        SetSynchronizationContext(ctx);
        try
        {
            var task = body();
            task.ContinueWith(_ => ctx._queue.CompleteAdding(), TaskScheduler.Default);
            foreach (var (d, state) in ctx._queue.GetConsumingEnumerable()) d(state);
            task.GetAwaiter().GetResult();
        }
        finally { SetSynchronizationContext(previous); }
    }
}
