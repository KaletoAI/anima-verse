using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 50: channel timing, late answers and ownership use a duration clock, never wall time.</summary>
public sealed class PositionChannelTests
{
    private static PositionAnswer Answer(string body, int status = 200)
    { using var doc = JsonDocument.Parse(body); return new(status, doc.RootElement.Clone()); }

    [Fact]
    public void WalkingReportsEvery330MsAndOneFinalPoint()
    {
        double now = 0;
        var sent = new List<PositionReport>();
        var channel = new PositionChannel((p, _) => { sent.Add(p); return Task.FromResult(Answer("{\"ok\":true}")); }, () => now, "test-session");
        for (int i = 1; i <= 200; i++) { now = i * 10; channel.Tick(new P2(now / 1000, 0), true); }
        now = 2310; channel.Tick(new P2(2, 0), false);
        now = 3000; channel.Tick(new P2(2, 0), false);
        Assert.Equal(7, sent.Count);
        for (int i = 0; i < 6; i++) { Assert.Equal((i + 1) * 330, sent[i].t_ms); Assert.Equal(i + 1, sent[i].seq); }
        Assert.Equal(2, sent[6].x);
        Assert.False(channel.Dirty);
    }

    [Fact]
    public async Task SingleFlightReservesCancelAndIgnoresAnswerBelowFloor()
    {
        double now = 330;
        var pending = new TaskCompletionSource<PositionAnswer>();
        var sent = new List<PositionReport>();
        var channel = new PositionChannel((p, _) => { sent.Add(p); return sent.Count == 1 ? pending.Task : Task.FromResult(Answer("{\"ok\":true}")); }, () => now, "test-session");
        int adopted = 0; channel.Adopted += _ => adopted++;
        channel.Tick(new P2(1,0), true);
        channel.ApplyDriver(new DriverPayload(true,"j1",null));
        channel.Input(new P2(1,0));
        Assert.Equal(DriverKind.CANCELLING, channel.Driver.Kind);
        Assert.Single(sent);
        pending.SetResult(Answer("{\"ok\":true}"));
        await channel.WhenIdle;
        Assert.Equal(2, sent.Count);
        Assert.Equal(2, sent[1].seq);
        Assert.Equal(1, adopted);
        channel.ApplyDriver(new DriverPayload(true,"j1",2));
        Assert.Equal(DriverKind.PLAYER, channel.Driver.Kind);
        Assert.True(channel.Suppressed("j1"));
    }

    [Fact]
    public void ThrottleAndNetworkFailureStayDirtyAndRefusalKeepsServerSentence()
    {
        double now = 330;
        int calls = 0;
        var channel = new PositionChannel((_, _) => ++calls == 1 ? Task.FromResult(Answer("{\"ok\":false,\"throttled\":true}"))
            : Task.FromResult(Answer("{\"detail\":{\"message\":\"Keep out.\",\"reason\":\"locked\",\"pos\":{\"x\":0,\"z\":0}}}",409)), () => now, "test-session");
        var messages = new List<string>(); channel.Toast += messages.Add;
        channel.Tick(new P2(1,0), true); Assert.True(channel.Dirty);
        now = 660; channel.Tick(new P2(1,0), false);
        Assert.Equal(new[] { "Keep out." }, messages);
        now = 990; channel.Tick(new P2(1,0), true); Assert.Single(messages);
        now = 4661; channel.Tick(new P2(1,0), true); Assert.Equal(2, messages.Count);
        var broken = new PositionChannel((_, _) => Task.FromException<PositionAnswer>(new InvalidOperationException()), () => now);
        broken.Tick(new P2(1,0),true); Assert.True(broken.Dirty);
    }
    /// <summary>Task 67 #1: HTTP refusals/throttles finish preparation; transport failure alone aborts it.</summary>
    [Theory]
    [InlineData(200, "{\"ok\":false,\"throttled\":true}")]
    [InlineData(200, "{\"ok\":false,\"stale\":true}")]
    [InlineData(409, "{\"detail\":{\"reason\":\"too_far\",\"pos\":{\"x\":0,\"z\":0}}}")]
    [InlineData(403, "{\"detail\":{\"reason\":\"locked\",\"pos\":{\"x\":0,\"z\":0}}}")]
    public async Task PropPreparationAllowsHttpAnswersAndAppliesCorrections(int status, string body)
    {
        int calls = 0, corrections = 0;
        using var channel = new PositionChannel((_, _) => Task.FromResult(++calls == 1
            ? Answer("{\"ok\":false,\"throttled\":true}") : Answer(body, status)), () => 1000);
        channel.Corrected += p => { Assert.Equal(new P2(0, 0), p); corrections++; };
        channel.Tick(new P2(1, 0), true);
        await channel.PreparePropActionAsync(new P2(1, 0), false);
        Assert.Equal(2, calls);
        Assert.Equal(status >= 400 ? 1 : 0, corrections);
        Assert.Equal(status < 400, channel.Dirty);
    }

    /// <summary>Task 67 #1: pace the final report after the previous answer, including a slow flight.</summary>
    [Fact]
    public async Task PropPreparationWaitsOutServerThrottleAfterInFlightAnswer()
    {
        var watch = System.Diagnostics.Stopwatch.StartNew();
        var first = new TaskCompletionSource<PositionAnswer>();
        var sent = new List<double>();
        using var channel = new PositionChannel((_, _) => {
            sent.Add(watch.Elapsed.TotalMilliseconds);
            return sent.Count == 1 ? first.Task : Task.FromResult(Answer("{\"ok\":true}"));
        }, () => 1000 + watch.Elapsed.TotalMilliseconds);
        channel.Tick(new P2(0, 0), true);
        channel.Tick(new P2(1, 0), true);
        var preparing = channel.PreparePropActionAsync(new P2(1, 0), false);
        double repliedAt = watch.Elapsed.TotalMilliseconds;
        first.SetResult(Answer("{\"ok\":true}"));
        await preparing;
        Assert.Equal(2, sent.Count);
        Assert.True(sent[1] - repliedAt >= 245, $"final report followed answer by {sent[1] - repliedAt}ms");
    }

    /// <summary>Task 67 #4: a safety gate raised during the current flight also fences the reserved final point.</summary>
    [Fact]
    public async Task PropPreparationKeepsSafetyGateWhileDraining()
    {
        var first = new TaskCompletionSource<PositionAnswer>();
        int calls = 0;
        bool safe = true;
        using var channel = new PositionChannel((_, _) => { calls++; return first.Task; }, () => 1000)
            { CanReport = () => safe };
        channel.Tick(new P2(0, 0), true);
        channel.Tick(new P2(1, 0), true);
        var preparing = channel.PreparePropActionAsync(new P2(1, 0), false);
        safe = false;
        first.SetResult(Answer("{\"ok\":true}"));
        await preparing;
        Assert.Equal(1, calls);
        Assert.True(channel.Dirty);
    }

    [Fact]
    public async Task PropPreparationStillFailsOnTransportError()
    {
        using var channel = new PositionChannel((_, _) => Task.FromException<PositionAnswer>(new InvalidOperationException("offline")), () => 1000);
        channel.Tick(new P2(1, 0), true);
        await Assert.ThrowsAsync<InvalidOperationException>(() => channel.PreparePropActionAsync(new P2(1, 0), false));
    }
}
