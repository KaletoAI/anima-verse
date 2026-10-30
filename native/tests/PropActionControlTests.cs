using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Props;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 57: production preparation/mutation lifecycle; refuses writes and stale reads without releasing input.</summary>
public class PropActionControlTests
{
    private sealed class Transport : HttpMessageHandler
    {
        public Func<HttpRequestMessage,Task<string>> Reply=_=>Task.FromResult("{\"incoming\":[],\"outgoing\":[],\"current\":[],\"recent_results\":[]}");
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage req,CancellationToken ct)
            =>new(HttpStatusCode.OK) { Content=new StringContent(await Reply(req),Encoding.UTF8,"application/json") };
    }
    [Fact]
    public async Task StartupWaitsForStateAndWorldBeforeManualReports()
    {
        var transport=new Transport(); var state=new TaskCompletionSource<string>(); var world=new TaskCompletionSource();
        transport.Reply=_=>state.Task; using var api=new AnimaApi("http://fixture/",transport);
        using var control=new PropActionControl(api,()=>0) { RefreshWorld=()=>world.Task };
        Assert.True(control.Paused);
        var refresh=control.RefreshAsync(); Assert.True(control.Paused);
        state.SetResult("{\"current\":[],\"outgoing\":[]}"); await Task.Yield(); Assert.True(control.Paused);
        world.SetResult(); await refresh; Assert.False(control.Paused);
    }
    [Fact]
    public async Task PreparationAwaitsRealAndFinalWritesAndAllowsHttpRefusal()
    {
        var writes=new List<TaskCompletionSource<PositionAnswer>>(); var points=new List<PositionReport>();
        var finalStarted = new TaskCompletionSource();
        double now = 1000;
        using var channel=new PositionChannel((r,_)=>{ points.Add(r); var t=new TaskCompletionSource<PositionAnswer>(); writes.Add(t); if(writes.Count==2) finalStarted.TrySetResult(); return t.Task; },()=>now,"fixture");
        channel.Tick(new P2(0,0),true);
        channel.Tick(new P2(1,0),true);
        var preparing=channel.PreparePropActionAsync(new P2(1,0),false);
        Assert.True(channel.ReportsPaused); Assert.False(preparing.IsCompleted);
        writes[0].SetResult(Answer()); await finalStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
        Assert.Equal(2,points.Count); Assert.Equal(1,points[1].x); Assert.False(preparing.IsCompleted);
        writes[1].SetResult(Answer()); await preparing;
        Assert.True(channel.ReportsPaused);
        channel.ReportsPaused=false; now = 2000;
        channel.Tick(new P2(2,0),true);
        var refused=channel.PreparePropActionAsync(new P2(2,0),false);
        writes[^1].SetResult(Answer(409));
        await refused;
    }
    private static PositionAnswer Answer(int status=200) =>new(status,System.Text.Json.JsonSerializer.SerializeToElement(new { ok=status==200 }));
    [Fact]
    public async Task CorrelatedCompletionNeedsFreshStateAndWorldBeforeResumeEvenOnRefusal()
    {
        var transport=new Transport(); using var api=new AnimaApi("http://fixture/",transport);
        var writes=new TaskCompletionSource(); var world=new TaskCompletionSource();
        using var control=new PropActionControl(api,()=>0) { PrepareWrites=()=>writes.Task, RefreshWorld=()=>world.Task };
        var prepare=control.PrepareAsync("hud:1"); Assert.True(control.Paused); Assert.False(prepare.IsCompleted);
        writes.SetResult(); await prepare; Assert.True(control.Paused);
        world.SetResult(); await control.ChangedAsync("unrelated"); Assert.True(control.Paused);
        world=new TaskCompletionSource();
        var changed=control.ChangedAsync("hud:1"); Assert.True(control.Paused);
        world.SetResult(); await changed; Assert.False(control.Paused);
        var notifications=new List<string?>(); control.NotifyChanged+=notifications.Add;
        var error=await Assert.ThrowsAsync<InvalidOperationException>(()=>control.MutateAsync(()=>throw new InvalidOperationException("refused")));
        Assert.Equal("refused",error.Message); Assert.Single(notifications); Assert.False(control.Paused);
    }
    [Fact]
    public async Task EarlierStateCannotReleaseNewPreparation()
    {
        var transport=new Transport(); var state=new TaskCompletionSource<string>();
        transport.Reply=_=>state.Task; using var api=new AnimaApi("http://fixture/",transport);
        using var control=new PropActionControl(api,()=>0);
        await control.PrepareAsync("a"); var changed=control.ChangedAsync("a"); await control.PrepareAsync("b");
        state.SetResult("{\"current\":[],\"outgoing\":[]}"); await changed; Assert.True(control.Paused);
        await control.ChangedAsync("b"); Assert.False(control.Paused);
    }
    /// <summary>B1: an accepted cancel is final without a state or world read; the answer owns the release.</summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task AcceptedReleaseNeedsNoStateOrWorldRefresh(bool failWorld)
    {
        var transport = new Transport();
        transport.Reply = req => req.Method == HttpMethod.Post ? Task.FromResult("{\"status\":\"cancelled\"}")
            : failWorld ? Task.FromResult("{\"current\":[],\"outgoing\":[]}")
            : Task.FromException<string>(new InvalidOperationException("state offline"));
        using var api = new AnimaApi("http://fixture/", transport);
        using var control = new PropActionControl(api, () => 0)
            { RefreshWorld = () => Task.FromException(new InvalidOperationException("view changed")) };
        var errors = new List<string>(); control.RefreshFailed += errors.Add;
        int resets = 0;
        await control.ReleaseAsync("run", "journey", () => resets++);
        Assert.Equal(1, resets);
        Assert.Empty(errors);
        Assert.True(control.ManualGate.Withdrawn("journey"));
        Assert.False(control.Paused);
        transport.Reply = _ => Task.FromResult("{\"current\":[],\"outgoing\":[]}");
        control.RefreshWorld = () => Task.CompletedTask;
        await control.RefreshAsync();
        Assert.False(control.Paused);
    }

    [Fact]
    public async Task KnownMutationFailureReleasesInputEvenWhenRefreshFails()
    {
        var transport = new Transport { Reply = _ => Task.FromException<string>(new InvalidOperationException("refresh failed")) };
        using var api = new AnimaApi("http://fixture/", transport);
        using var control = new PropActionControl(api, () => 0);
        var error = await Assert.ThrowsAsync<InvalidOperationException>(() => control.MutateAsync(
            () => Task.FromException<System.Text.Json.JsonDocument>(new InvalidOperationException("mutation failed"))));
        Assert.Equal("mutation failed", error.Message);
        Assert.False(control.Paused);
    }
}
