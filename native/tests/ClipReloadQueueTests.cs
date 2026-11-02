using System;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Sync;
using Xunit;

namespace AnimaNative.Tests;

public class ClipReloadQueueTests
{
    [Fact]
    public async Task BurstDebouncesAndInFlightPushesCoalesce()
    {
        double now = 0;
        var clock = new TimerQueue(() => now);
        int calls = 0;
        var first = new TaskCompletionSource();
        var followUp = new TaskCompletionSource();
        using var queue = new ClipReloadQueue(clock, () =>
        {
            if (++calls == 1) return first.Task;
            followUp.SetResult();
            return Task.CompletedTask;
        },
            e => throw new Exception("Unexpected failure", e));
        queue.Push();
        now = 500; clock.Pump(); queue.Push();
        now = 1000; clock.Pump(); Assert.Equal(0, calls);
        now = 1500; clock.Pump(); Assert.Equal(1, calls);
        queue.Push(); queue.Push(); queue.Push();
        now = 2500; clock.Pump(); Assert.Equal(1, calls);
        first.SetResult();
        await followUp.Task;
        Assert.Equal(2, calls);
    }

    [Fact]
    public void FollowUpWaitsForQuietPeriodAfterFastCompletion()
    {
        double now = 0;
        var clock = new TimerQueue(() => now);
        int calls = 0;
        ClipReloadQueue? queue = null;
        using var disposable = queue = new ClipReloadQueue(clock, () =>
        {
            if (++calls == 1) queue!.Push();
            return Task.CompletedTask;
        }, _ => { });
        queue.Push();
        now = 1000; clock.Pump();
        Assert.Equal(1, calls);
        now = 1999; clock.Pump(); Assert.Equal(1, calls);
        now = 2000; clock.Pump(); Assert.Equal(2, calls);
    }

    [Fact]
    public void FailureDoesNotBlockLaterReload()
    {
        double now = 0;
        var clock = new TimerQueue(() => now);
        int calls = 0, failures = 0;
        using var queue = new ClipReloadQueue(clock,
            () => ++calls == 1 ? Task.FromException(new InvalidOperationException()) : Task.CompletedTask,
            _ => failures++);
        queue.Push(); now = 1000; clock.Pump();
        queue.Push(); now = 2000; clock.Pump();
        Assert.Equal(2, calls);
        Assert.Equal(1, failures);
    }

    [Fact]
    public void DisposeCancelsPendingReload()
    {
        double now = 0;
        var clock = new TimerQueue(() => now);
        int calls = 0;
        var queue = new ClipReloadQueue(clock, () => { calls++; return Task.CompletedTask; }, _ => { });
        queue.Push(); queue.Dispose();
        now = 2000; clock.Pump();
        Assert.Equal(0, calls);
    }
}
