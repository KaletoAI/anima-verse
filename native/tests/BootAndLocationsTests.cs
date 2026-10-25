using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Sync;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="BootTracker"/> / <see cref="BootRetry"/> (client3d/src/game/boot.ts, main.ts <c>retryBoot</c>),
/// <see cref="LocationsCache"/> / <see cref="LocationsSync"/> (api.ts <c>getLocations3d</c>, main.ts
/// <c>syncLocations</c>) and <see cref="ConnectionState"/> (main.ts <c>applyWorldMap</c> + the poll's error branch).
/// </summary>
public class BootAndLocationsTests
{
    private static JsonElement J(string json) => JsonDocument.Parse(json).RootElement.Clone();

    // ---- boot ---------------------------------------------------------------------------------------

    /// <summary>
    /// Six stages, one step = round(100/6 · n): 17, 33, 50, 67, 83, 100. The label is the first missing stage; the
    /// state lists the done ones in display order whatever the order of reporting; a repeat changes nothing.
    /// </summary>
    [Fact]
    public void StagesCountAndLabelLikeBootTs()
    {
        double now = 1000;
        var boot = new BootTracker(() => now);
        int changes = 0;
        boot.Changed += () => changes++;
        var percents = new List<int>();
        foreach (var stage in new[] { "world", "scenes", "tiles", "visible", "figures", "arrival" })
        {
            now += 250;
            boot.Report(stage);
            percents.Add(boot.Progress.Percent);
        }
        Assert.Equal(new[] { 17, 33, 50, 67, 83, 100 }, percents);
        Assert.Equal("ready", boot.Progress.Label);
        boot.Report("tiles");
        Assert.Equal(6, changes);
        Assert.Equal(500, boot.TimeOf("scenes"));   // 1000 → 1500: ms since construction

        var other = new BootTracker(() => 0);
        other.Report("figures");
        Assert.Equal(17, other.Progress.Percent);
        Assert.Equal("world", other.Progress.Label);
        Assert.Throws<ArgumentException>(() => other.Report("ground"));
    }

    /// <summary>Notes: an equal note publishes nothing; the HUD JSON is <c>{state, report}</c> of bus.ts <c>HudBoot</c>.</summary>
    [Fact]
    public void NotesDedupeAndTheHudShape()
    {
        var boot = new BootTracker(() => 0);
        int changes = 0;
        boot.Changed += () => changes++;
        boot.SetNote(BootNote.Retry(4));
        boot.SetNote(BootNote.Retry(4));
        Assert.Equal(1, changes);
        boot.SetNote(BootNote.Retry(8));
        boot.SetNote(BootNote.Characters);
        boot.SetNote(BootNote.Characters);
        boot.SetNote(null);
        boot.SetNote(null);
        Assert.Equal(4, changes);
        boot.SetNote(BootNote.Retry(15));
        boot.Report("world");
        var hud = boot.ToHud();
        Assert.Equal("{\"percent\":17,\"label\":\"scenes\",\"note\":{\"kind\":\"retry\",\"seconds\":15},\"stages\":[\"world\"]}",
                     hud["state"]!.ToJsonString());
        var report = hud["report"]!.AsObject();
        Assert.Equal(0.0, report["stages"]!["world"]!.GetValue<double>());
        Assert.Null(report["stages"]!["arrival"]);
        Assert.Equal(9, report["phases"]!.AsObject().Count);
        Assert.Null(report["longTasks"]);
        Assert.Equal("{\"kind\":\"failed\"}", BootNote.Failed.ToJson().ToJsonString());
    }

    /// <summary>
    /// <c>min(15000, 1000 · 2^min(attempt, 4))</c>: attempts 0..6 → 1, 2, 4, 8, 15, 15, 15 s (2^4 = 16 s is over the
    /// cap). The loop waits those, shows the seconds, clears the note on success.
    /// </summary>
    [Fact]
    public async Task BootRetryBacksOffAndClears()
    {
        Assert.Equal(new double[] { 1000, 2000, 4000, 8000, 15000, 15000, 15000 },
                     Enumerable.Range(0, 7).Select(BootRetry.DelayMs));
        int calls = 0;
        var waits = new List<double>();
        var notes = new List<int>();
        bool cleared = false;
        var result = await BootRetry.RunAsync(() =>
            {
                calls++;
                return calls < 6 ? Task.FromException<int>(new InvalidOperationException("500")) : Task.FromResult(42);
            }, AnimaApi.IsAuthError, s => notes.Add(s), () => cleared = true,
            ms => { waits.Add(ms); return Task.CompletedTask; });
        Assert.Equal(42, result);
        Assert.Equal(new double[] { 1000, 2000, 4000, 8000, 15000 }, waits);
        Assert.Equal(new[] { 1, 2, 4, 8, 15 }, notes);
        Assert.True(cleared);
    }

    /// <summary>A 401 is not retried natively: the session is gone, the boot ends with it (the login comes back).</summary>
    [Fact]
    public async Task BootRetryGivesUpOnAuth()
    {
        int calls = 0;
        await Assert.ThrowsAsync<ApiException>(() => BootRetry.RunAsync<int>(() =>
            {
                calls++;
                throw new ApiException(401, "/play/worldmap");
            }, AnimaApi.IsAuthError, _ => { }, () => { }, _ => Task.CompletedTask));
        Assert.Equal(1, calls);
        Assert.False(AnimaApi.IsAuthError(new ApiException(403, "/play/worldmap")));
    }

    // ---- locations ----------------------------------------------------------------------------------

    /// <summary>
    /// The conditional GET: the first request has no If-None-Match; 200 caches body + ETag; the next request sends
    /// that ETag; a 304 answers the CACHED body with ITS ETag; a 304 with nothing cached is an error.
    /// </summary>
    [Fact]
    public async Task ConditionalFetchKeepsTheCacheOn304()
    {
        var sent = new List<string?>();
        var answers = new Queue<ConditionalAnswer>(new[]
        {
            new ConditionalAnswer(200, "\"r1\"", J("{\"locations\":[{\"id\":\"a\"}]}")),
            new ConditionalAnswer(304, "\"r1\"", null),
            new ConditionalAnswer(200, "W/\"r2\"", J("{\"locations\":[]}")),
        });
        var cache = new LocationsCache(etag => { sent.Add(etag); return Task.FromResult(answers.Dequeue()); });
        var first = await cache.GetAsync();
        var second = await cache.GetAsync();
        Assert.Same(first, second);
        var third = await cache.GetAsync();
        Assert.Equal(new string?[] { null, "\"r1\"", "\"r1\"" }, sent);
        Assert.Equal("W/\"r2\"", third.Etag);

        var empty = new LocationsCache(_ => Task.FromResult(new ConditionalAnswer(304, "", null)));
        await Assert.ThrowsAsync<InvalidOperationException>(() => empty.GetAsync());
    }

    /// <summary>Single flight: two callers while one request is open share it.</summary>
    [Fact]
    public async Task ConditionalFetchIsSingleFlight()
    {
        var tcs = new TaskCompletionSource<ConditionalAnswer>();
        var cache = new LocationsCache(_ => tcs.Task);
        var a = cache.GetAsync();
        var b = cache.GetAsync();
        Assert.Same(a, b);
        Assert.Equal(1, cache.Requests);
        tcs.SetResult(new ConditionalAnswer(200, "\"x\"", J("{}")));
        await a;
        _ = await cache.GetAsync().ContinueWith(t => t);   // a new request after the first completed
        Assert.Equal(2, cache.Requests);
    }

    /// <summary>
    /// The revision: <c>W/</c> and the quotes go. Data is applied when forced or when the ETag changed; the
    /// revision follows every answer; a failed request keeps everything.
    /// </summary>
    [Fact]
    public async Task SyncAppliesOnChangeOrForce()
    {
        Assert.Equal("abc", LocationsSync.RevOf("W/\"abc\""));
        Assert.Equal("abc", LocationsSync.RevOf("\"abc\""));
        Assert.Equal("abc", LocationsSync.RevOf("abc"));
        Assert.Equal("", LocationsSync.RevOf("\""));
        var answers = new Queue<Func<ConditionalAnswer>>(new Func<ConditionalAnswer>[]
        {
            () => new ConditionalAnswer(304, "\"r1\"", null),
            () => new ConditionalAnswer(304, "\"r1\"", null),
            () => throw new InvalidOperationException("server away"),
            () => new ConditionalAnswer(200, "W/\"r2\"", J("{\"locations\":[]}")),
        });
        var cache = new LocationsCache(_ => Task.FromResult(answers.Dequeue()()));
        // Seeded like the boot: the cache already holds r1 (the boot's own request through it).
        var applied = new List<string>();
        var boot = new LocationsCache(_ => Task.FromResult(new ConditionalAnswer(200, "\"r1\"", J("{\"locations\":[]}"))));
        var sync0 = new LocationsSync(boot, l => applied.Add(l.Etag));
        sync0.Seed(await boot.GetAsync());
        Assert.Equal("r1", sync0.Rev);
        Assert.False(sync0.Differs("r1"));
        Assert.True(sync0.Differs("r2"));
        Assert.True(sync0.Differs(null));

        var sync = new LocationsSync(cache, l => applied.Add(l.Etag));
        // A 304 without a cached body is an error → nothing applied, revision kept.
        await sync.SyncAsync();
        Assert.Empty(applied);
        Assert.Equal("", sync.Rev);
        await sync.SyncAsync(force: true);   // second 304, still no cache: error again
        await sync.SyncAsync();              // server away
        Assert.Empty(applied);
        await sync.SyncAsync();              // 200 r2 → applied (new ETag)
        Assert.Equal(new[] { "W/\"r2\"" }, applied);
        Assert.Equal("r2", sync.Rev);
    }

    /// <summary>A forced sync applies an unchanged ETag again (a new location appeared in the poll).</summary>
    [Fact]
    public async Task ForcedSyncReappliesTheSameEtag()
    {
        var cache = new LocationsCache(etag => Task.FromResult(etag is null
            ? new ConditionalAnswer(200, "\"r1\"", J("{\"locations\":[]}"))
            : new ConditionalAnswer(304, "\"r1\"", null)));
        int applied = 0;
        var sync = new LocationsSync(cache, _ => applied++);
        sync.Seed(await cache.GetAsync());
        await sync.SyncAsync();
        Assert.Equal(0, applied);
        await sync.SyncAsync(force: true);
        Assert.Equal(1, applied);
        Assert.Equal("r1", LocationsSync.MapRev(J("{\"locations_rev\":\"r1\"}")));
        Assert.Null(LocationsSync.MapRev(J("{\"locations_rev\":5}")));
        Assert.Null(LocationsSync.MapRev(J("{}")));
    }

    // ---- connection + clock -------------------------------------------------------------------------

    /// <summary>
    /// Publish only on change: ok+clock once, the same clock again → nothing, a failure → 'lost' once, the next
    /// good poll → ok with the (same) clock. The clock is <c>label_display ?? label ?? ''</c> — an EMPTY
    /// label_display is kept (JS <c>??</c> falls through on null/missing only).
    /// </summary>
    [Fact]
    public void ConnectionPublishesOnlyChanges()
    {
        var c = new ConnectionState();
        Assert.True(c.Ok("Day 3, 08:00"));
        Assert.False(c.Ok("Day 3, 08:00"));
        Assert.True(c.Lost());
        Assert.False(c.Lost());
        Assert.Equal("lost", c.Connection);
        Assert.True(c.Ok("Day 3, 08:00"));
        Assert.True(c.Ok("Day 3, 08:01"));
        Assert.Equal("Spring 2, 08:00", ConnectionState.ClockOf(J("{\"game_time\":{\"label_display\":\"Spring 2, 08:00\",\"label\":\"x\"}}")));
        Assert.Equal("x", ConnectionState.ClockOf(J("{\"game_time\":{\"label_display\":null,\"label\":\"x\"}}")));
        Assert.Equal("", ConnectionState.ClockOf(J("{\"game_time\":{\"label_display\":\"\",\"label\":\"x\"}}")));
        Assert.Equal("", ConnectionState.ClockOf(J("{\"game_time\":{}}")));
        Assert.Equal("", ConnectionState.ClockOf(J("{}")));
    }
}
