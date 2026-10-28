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
}
