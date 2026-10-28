using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AnimaNative.Embody;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 47: async ownership/lifecycle branches not expressible in the synchronous shared-vector adapters.</summary>
public class EmbodyStateTests
{
    [Fact]
    public async Task ManualCancellationCoalescesAndWithdrawsOnlyAfterSuccess()
    {
        var gate = new ManualPropGate();
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        int calls = 0;
        var first = gate.Cancel("run-1", "J1", () => { calls++; return release.Task; });
        Assert.True(gate.Pending);
        Assert.False(gate.Withdrawn("J1"));
        var second = gate.Cancel("run-2", "J2", () => { calls++; return Task.CompletedTask; });
        Assert.Same(first, second);
        release.SetResult();
        await first;
        Assert.Equal(1, calls);
        Assert.False(gate.Pending);
        Assert.True(gate.Withdrawn("J1"));
        Assert.False(gate.Withdrawn("J2"));
        Assert.False(gate.Withdrawn(null));
        Assert.False(gate.Withdrawn(""));
    }

    [Fact]
    public async Task FailedCancellationDoesNotWithdrawAndCanRetryWithoutAJourney()
    {
        var gate = new ManualPropGate();
        await Assert.ThrowsAsync<InvalidOperationException>(() => gate.Cancel("run", "J", () => Task.FromException(new InvalidOperationException("refused"))));
        Assert.False(gate.Pending);
        Assert.False(gate.Withdrawn("J"));
        await gate.Cancel("run", null, () => Task.CompletedTask);
        Assert.False(gate.Pending);
        Assert.False(gate.Withdrawn(null));
        await gate.Cancel("run", "J", () => Task.CompletedTask);
        Assert.True(gate.Withdrawn("J"));
    }

    [Fact]
    public void SnapReplacesOnlyApproachAndTeleportPinsAndWaitsForGeometry()
    {
        var deps = new ReadyDeps();
        var state = new ReadinessState { ApproachPin = "A", PendingSnap = new(1, 2, "B") };
        var snap = new PendingSnap(3, 4, "C");
        Readiness.HoldSnap(deps, state, snap);
        Assert.Equal(new[] { "release:A:approach", "release:B:teleport", "pin:C:teleport" }, deps.Calls);
        Assert.Null(state.ApproachPin);
        Assert.Same(snap, state.PendingSnap);
        Assert.False(Readiness.TrySnap(deps, snap));
        deps.Ready = true;
        Assert.True(Readiness.TrySnap(deps, snap));
        Readiness.ClearSnap(deps, state);
        Readiness.ClearSnap(deps, state);
        Assert.Null(state.PendingSnap);
        Assert.Equal("release:C:teleport", deps.Calls[3]);
        Assert.Equal(4, deps.Calls.Count);
    }

    [Theory]
    [InlineData(true, true, true, false, true)]
    [InlineData(false, true, true, false, false)]
    [InlineData(true, false, true, false, false)]
    [InlineData(true, true, false, false, false)]
    public async Task EntryAlwaysReleasesItsPin(bool exists, bool valid, bool ready, bool progress, bool expected)
    {
        var deps = new EntryDeps { ExistsValue = exists, Valid = valid, Ready = ready, Progress = progress };
        Assert.Equal(expected, await Readiness.EnterWhenReady(deps, "A", "request"));
        Assert.Equal("request:A", deps.Calls[0]);
        Assert.Equal(1, deps.SettledCount);
        Assert.Equal("release:A:entry", deps.Calls[^1]);
    }

    [Fact]
    public async Task EntryRetriesUntilReadyAndReleasesAfterAnException()
    {
        var deps = new EntryDeps { ReadyOnSecond = true };
        Assert.True(await Readiness.EnterWhenReady(deps, "A", "request"));
        Assert.Equal(2, deps.SettledCount);
        var broken = new EntryDeps { Throw = true };
        await Assert.ThrowsAsync<InvalidOperationException>(() => Readiness.EnterWhenReady(broken, "B", "request"));
        Assert.Equal("release:B:entry", broken.Calls[^1]);
    }

    private sealed class ReadyDeps : IReadinessDeps
    {
        public bool Ready;
        public List<string> Calls = new();
        public string? PlaceAt(double x, double z) => null;
        public bool IsReady(string id) => Ready;
        public void Pin(string id, string owner) => Calls.Add($"pin:{id}:{owner}");
        public void Release(string id, string owner) => Calls.Add($"release:{id}:{owner}");
    }
    private sealed class EntryDeps : IEntryDeps
    {
        public bool ExistsValue = true, Valid = true, Ready, Progress = true, ReadyOnSecond, Throw;
        public int SettledCount;
        public List<string> Calls = new();
        public void RequestNear(string id) => Calls.Add("request:" + id);
        public void Release(string id, string owner) => Calls.Add($"release:{id}:{owner}");
        public Task Settled(string id) { Calls.Add("settled:" + id); SettledCount++; return Throw ? Task.FromException(new InvalidOperationException("build")) : Task.CompletedTask; }
        public Task Sleep(int ms) { Calls.Add("sleep:" + ms); return new TaskCompletionSource().Task; }
        public bool IsReady(string id) => Ready || ReadyOnSecond && SettledCount >= 2;
        public bool StillValid(string key) { Calls.Add("valid:" + key); return Valid; }
        public bool Exists(string id) => ExistsValue;
        public bool CanProgress(string id) => Progress;
    }
}
