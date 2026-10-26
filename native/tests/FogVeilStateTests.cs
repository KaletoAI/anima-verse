using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Sky;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The veil's state (Task 26): the cells texture of <c>setFogVeilCells</c>, the A/B crossfade of <c>tickFogVeil</c>, the
/// strength of <c>pushAlpha</c> and main.ts <c>syncExplored</c> — every expectation derived by hand in the comments from
/// client3d/src/scene/fogVeil.ts and main.ts (the math under it is vector-checked in <see cref="FogVeilVectorTests"/>).
/// </summary>
public class FogVeilStateTests
{
    [Fact]
    public void CellsFillTheGridWithTheExploredTexels()
    {
        // Readable: (0,0), (2,1); "x" and "1,0 " (trailing blank) are refused by the strict parser.
        // Grid: x 0…2, z 0…1 plus one ring → cx0 = −1, cz0 = −1, cols = 2 − 0 + 1 + 2 = 5, rows = 1 − 0 + 1 + 2 = 4.
        // Texel (0,0): i = 1, j = 1 → 1·5 + 1 = 6; (2,1): i = 3, j = 2 → 2·5 + 3 = 13.
        var c = FogVeil.Cells(new[] { "0,0", "2,1", "x", "1,0 " });
        Assert.Equal(new FogGrid(-1, -1, 5, 4), c.Grid);
        Assert.Equal((5, 4), (c.Cols, c.Rows));
        Assert.Equal(20, c.Data.Length);
        var lit = Enumerable.Range(0, 20).Where(i => c.Data[i] != 0).ToArray();
        Assert.Equal(new[] { 6, 13 }, lit);
        Assert.Equal(255, c.Data[6]);
        Assert.Equal(2, c.Explored);
        Assert.Equal((-1.0, -1.0, 5.0, 4.0), c.Geom);
    }

    [Fact]
    public void NoReadableCellIsTheNeutralTexel()
    {
        Assert.Same(FogCells.Neutral, FogVeil.Cells(Array.Empty<string>()));
        Assert.Same(FogCells.Neutral, FogVeil.Cells(new[] { "a,b", "" }));
        Assert.Same(FogCells.Neutral, FogVeil.Cells(null));
        Assert.Equal((0.0, 0.0, 1.0, 1.0), FogCells.Neutral.Geom);
        Assert.Equal(new byte[1], FogCells.Neutral.Data);
    }

    private sealed class Rig
    {
        public readonly List<string> Retired = new();
        public int Made;
        public readonly FogVeilState<string> State;

        public Rig() => State = new FogVeilState<string>("neutral", _ => $"t{++Made}", t => Retired.Add(t));
    }

    [Fact]
    public void CrossfadeRunsOverPointSixSecondsThenSettles()
    {
        var r = new Rig();
        var s = r.State;
        Assert.Equal(("neutral", "neutral", 1.0), (s.A, s.B, s.Mix));
        s.SetCells(new[] { "0,0" });                       // grid (−1, −1, 3, 3)
        Assert.Equal(("neutral", "t1", 0.0), (s.A, s.B, s.Mix));
        Assert.Equal((-1.0, -1.0, 3.0, 3.0), s.GeomB);
        Assert.Equal((0.0, 0.0, 1.0, 1.0), s.GeomA);
        Assert.Equal(1, s.ExploredCells);
        Assert.True(s.Tick(0.3));                          // 0.3 / 0.6 = 0.5
        Assert.Equal(0.5, s.Mix, 12);
        Assert.Equal("neutral", s.A);
        Assert.True(s.Tick(0.3));                          // lands at 1: A takes B
        Assert.Equal(("t1", "t1", 1.0), (s.A, s.B, s.Mix));
        Assert.Equal(s.GeomB, s.GeomA);
        Assert.False(s.Tick(1));                           // settled: nothing moves
        Assert.Empty(r.Retired);                           // the neutral texel is never retired

        s.SetCells(new[] { "0,0", "1,0" });
        Assert.Equal(("t1", "t2"), (s.A, s.B));
        Assert.Empty(r.Retired);                           // t1 is still bound as A
        s.Tick(0.6);
        Assert.Equal(("t2", "t2"), (s.A, s.B));
        Assert.Equal(new[] { "t1" }, r.Retired);           // freed only when the fade is over
    }

    [Fact]
    public void ChangeDuringAFadeRestartsFromTheHalfShownState()
    {
        var r = new Rig();
        var s = r.State;
        s.SetCells(new[] { "0,0" });
        s.Tick(1);                                         // A = B = t1
        s.SetCells(new[] { "1,1" });                       // A t1, B t2
        s.Tick(0.3);                                       // half way
        s.SetCells(new[] { "2,2" });                       // A = the half-shown t2, B t3; the old A t1 goes now
        Assert.Equal(("t2", "t3", 0.0), (s.A, s.B, s.Mix));
        Assert.Equal(new[] { "t1" }, r.Retired);
        Assert.False(s.Tick(-1) && s.Mix > 0);             // a negative step does not advance
        Assert.Equal(0.0, s.Mix);
        s.SetCells(Array.Empty<string>());                 // the memory emptied: B is the neutral texel
        Assert.Equal(("t3", "neutral"), (s.A, s.B));
        Assert.Equal((0.0, 0.0, 1.0, 1.0), s.GeomB);
        s.Release();
        Assert.Equal(("neutral", "neutral", 1.0), (s.A, s.B, s.Mix));
        Assert.Equal(new[] { "t1", "t2", "t3" }, r.Retired);
    }

    [Fact]
    public void AlphaIsTheHeightRampTimesPointSevenTwoWhileFogged()
    {
        var s = new Rig().State;
        Assert.Equal(0, s.Alpha);                          // height 0 < 20 m
        s.SetCameraHeight(32.5);                           // t = 12.5 / 25 = 0.5 → smoothstep 0.5 → 0.36
        Assert.Equal(0.36, s.Alpha, 12);
        s.SetCameraHeight(45);
        Assert.Equal(0.72, s.Alpha, 12);
        s.SetCameraHeight(400);
        Assert.Equal(0.72, s.Alpha, 12);
        s.SetCameraHeight(20);
        Assert.Equal(0, s.Alpha);
        s.SetCameraHeight(double.NaN);                     // not finite → 0 m
        Assert.Equal(0, s.Alpha);
        s.SetCameraHeight(100);
        s.SetFogged(false);                                // the admin's "show all": no veil
        Assert.Equal(0, s.Alpha);
        s.SetFogged(true);
        Assert.Equal(0.72, s.Alpha, 12);
        s.SetDebugOff(true);
        Assert.Equal(0, s.Alpha);
        s.SetDebugOff(false);
        Assert.Equal(0.72, s.Alpha, 12);
    }

    private sealed class FakeServer
    {
        public int Calls;
        public Func<(IReadOnlyList<string>?, string?)> Answer = () => (new[] { "0,0" }, "1");
        public TaskCompletionSource? Gate;

        public async Task<(IReadOnlyList<string>? Cells, string? Sig)> Fetch()
        {
            Calls++;
            if (Gate is { } g) await g.Task;
            return Answer();
        }
    }

    [Fact]
    public async Task SyncFetchesOnlyWhenTheSignatureMoves()
    {
        var server = new FakeServer();
        var got = new List<string>();
        var fogged = new List<bool>();
        var sync = new ExploredSync(server.Fetch, c => got.Add(string.Join(";", c)), fogged.Add);
        server.Answer = () => (new[] { "0,0", "1,0" }, "3");   // the avatar walked on between poll and answer
        await sync.SyncAsync(true, "2");
        Assert.Equal((1, "3"), (server.Calls, sync.Sig));        // the SERVER's signature is kept
        Assert.Equal(new[] { "0,0;1,0" }, got);
        await sync.SyncAsync(true, "3");                          // unchanged: no request
        Assert.Equal(1, server.Calls);
        await sync.SyncAsync(false, "3");                         // every map sets the flag
        Assert.Equal(new[] { true, true, false }, fogged);
        await sync.SyncAsync(true, "");                           // no avatar: a memory of nothing, no request
        Assert.Equal((1, ""), (server.Calls, sync.Sig));
        Assert.Equal("", got[^1]);
    }

    [Fact]
    public async Task FailedFetchKeepsTheVeilAndRetriesAtTheNextMap()
    {
        var server = new FakeServer { Answer = () => throw new InvalidOperationException("HTTP 500") };
        var got = new List<string>();
        var log = new List<string>();
        var sync = new ExploredSync(server.Fetch, c => got.Add(string.Join(";", c)), _ => { }, log.Add);
        await sync.SyncAsync(true, "5");
        Assert.Equal((1, 1, (string?)null), (server.Calls, sync.Failures, sync.Sig));
        Assert.Empty(got);
        Assert.Single(log);
        server.Answer = () => (new[] { "4,4" }, null);            // an answer without a sig keeps the poll's
        await sync.SyncAsync(true, "5");
        Assert.Equal((2, "5"), (server.Calls, sync.Sig));
        Assert.Equal(new[] { "4,4" }, got);
    }

    [Fact]
    public void PayloadAndMapFieldsAreReadLikeTheBrowser()
    {
        using var ok = System.Text.Json.JsonDocument.Parse("{\"cells\": [\"1,2\", 7, \"-3,4\"], \"sig\": \"2\"}");
        var (cells, sig) = ExploredSync.Parse(ok.RootElement);
        Assert.Equal(new[] { "1,2", "-3,4" }, cells);              // a non-string entry is skipped
        Assert.Equal("2", sig);
        using var bare = System.Text.Json.JsonDocument.Parse("{}");
        Assert.Equal(((IReadOnlyList<string>?)null, (string?)null), ExploredSync.Parse(bare.RootElement));
        // map.fogged !== false: absent and true are fogged, only false is not; explored_sig ?? ''.
        using var m1 = System.Text.Json.JsonDocument.Parse("{\"explored_sig\": \"96\"}");
        using var m2 = System.Text.Json.JsonDocument.Parse("{\"fogged\": false, \"explored_sig\": null}");
        using var m3 = System.Text.Json.JsonDocument.Parse("{\"fogged\": true}");
        Assert.Equal((true, "96"), ExploredSync.OfMap(m1.RootElement));
        Assert.Equal((false, ""), ExploredSync.OfMap(m2.RootElement));
        Assert.Equal((true, ""), ExploredSync.OfMap(m3.RootElement));
    }

    [Fact]
    public async Task OneFetchAtATime()
    {
        var server = new FakeServer { Gate = new TaskCompletionSource() };
        var sync = new ExploredSync(server.Fetch, _ => { }, _ => { });
        var first = sync.SyncAsync(true, "1");
        await sync.SyncAsync(true, "2");                          // busy: skipped, not queued
        Assert.Equal(1, server.Calls);
        server.Gate.SetResult();
        await first;
        Assert.Equal("1", sync.Sig);
        await sync.SyncAsync(true, "2");                          // the next map picks the newer signature up
        Assert.Equal(2, server.Calls);
    }
}
