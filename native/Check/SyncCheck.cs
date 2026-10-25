using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Sync;
using AnimaNative.World;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c> section "sync" (Task 10): the boot stages the REAL world build reports, the start's retry, and the
/// connection state of the world-map poll — offline, against native/fixtures. Expected values by hand:
///   • the build reports world → scenes → tiles in that order; at <c>world</c> no scene and no height tile was asked
///     for yet; at <c>scenes</c> every start-ring recipe was (3 placed locations, none out of reach — README
///     "Locations": locations=3 gone=0), and building the tiles asks for none again;
///   • a heightfield that fails once with a 503 shows the note "retry 1 s" (attempt 0: 1000 · 2⁰ ms), clears it on
///     the second attempt, and the boot data arrive; a 401 is not retried (one attempt, the exception passes);
///   • the poll over the fixture map: a good fetch → connection ok, clock "" (worldmap.json has no game_time);
///     a failing fetch → lost (once); the next good one → ok again. Polls at 0, 3 s (fails), 9 s (factor 2 → 6 s).
/// </summary>
public static class SyncCheck
{
    /// <summary>The build's hooks plus what was asked for when each stage was reported.</summary>
    public sealed class BuildProbe
    {
        public BootTracker Boot { get; } = new(() => 0);
        public Dictionary<string, (int Scenes, int Tiles)> At { get; } = new();

        public WorldBuilder.BuildHooks Hooks(FixtureSource source) => new()
        {
            Stage = stage =>
            {
                At[stage] = (source.SceneRequests.Count, source.TileRequests.Count);
                Boot.Report(stage);
            },
        };
    }

    public static async Task<string> RunAsync(FixtureSource source, BuildProbe probe, string dir)
    {
        Expect("boot order", string.Join(",", probe.Boot.Order) == "world,scenes,tiles", string.Join(",", probe.Boot.Order));
        Expect("world before any scene", probe.At["world"] == (0, 0), $"{probe.At["world"]}");
        Expect("scenes primed", probe.At["scenes"].Scenes == 3, $"{probe.At["scenes"]}");
        Expect("tiles from the primed recipes", probe.At["tiles"].Scenes == 3, $"{probe.At["tiles"]}");
        Expect("boot percent", probe.Boot.Progress.Percent == 50 && probe.Boot.Progress.Label == "visible",
               $"{probe.Boot.Progress}");

        // The start's retry around the real boot-data fetch.
        var flaky = new FlakySource(new FixtureSource(dir), fail: new ApiException(503, "/play/heightfield"));
        var builder = new WorldBuilder(flaky, _ => { }, strict: true);
        var notes = new List<string>();
        var data = await BootRetry.RunAsync(() => builder.FetchBootDataAsync(), AnimaApi.IsAuthError,
                                            s => notes.Add($"retry {s}"), () => notes.Add("clear"), _ => Task.CompletedTask);
        Expect("retry notes", string.Join(";", notes) == "retry 1;clear", string.Join(";", notes));
        Expect("boot data after a retry", flaky.HeightfieldCalls == 2 && data.Map.ValueKind == JsonValueKind.Object,
               $"calls={flaky.HeightfieldCalls}");
        var denied = new FlakySource(new FixtureSource(dir), fail: new ApiException(401, "/play/heightfield"));
        var b401 = new WorldBuilder(denied, _ => { }, strict: true);
        bool passed = false;
        try
        {
            await BootRetry.RunAsync(() => b401.FetchBootDataAsync(), AnimaApi.IsAuthError, _ => { }, () => { },
                                     _ => Task.CompletedTask);
        }
        catch (ApiException e) when (e.Status == 401) { passed = true; }
        Expect("401 not retried", passed && denied.HeightfieldCalls == 1, $"calls={denied.HeightfieldCalls}");

        // The poll's connection state over the fixture map.
        var clock = new ManualClock();
        var timers = new TimerQueue(() => clock.Ms);
        var poll = new PollScheduler(timers, null);
        var conn = new ConnectionState();
        var published = new List<string>();
        int n = 0;
        var fixtures = new FixtureSource(dir);
        poll.Subscribe<JsonElement>("c3d-worldmap", async () =>
        {
            int i = n++;
            if (i == 1) throw new InvalidOperationException("fixture outage");
            using var doc = await fixtures.GetWorldMapAsync();
            return doc.RootElement.Clone();
        }, PollSpec.Worldmap3d, (map, error) =>
        {
            if (error is not null) { if (conn.Lost()) published.Add("lost"); }
            else if (conn.Ok(ConnectionState.ClockOf(map))) published.Add($"ok '{conn.Clock}'");
        });
        for (int t = 1; t <= 10; t++)
        {
            clock.Set(t * 1000);
            timers.Pump();
            poll.Tick();
        }
        Expect("connection", string.Join(";", published) == "lost;ok ''", string.Join(";", published));
        Expect("poll count", n == 3, $"{n} polls in 10 s");
        return "sync boot=world,scenes,tiles retry=1s connection=lost→ok polls=3";
    }

    private static void Expect(string what, bool ok, string got)
    {
        if (!ok) throw new Exception($"sync: {what}: got {got}");
    }

    /// <summary>The fixture source whose heightfield fails ONCE with the given exception.</summary>
    private sealed class FlakySource : IWorldSource
    {
        private readonly FixtureSource _f;
        private readonly Exception _fail;
        public int HeightfieldCalls { get; private set; }
        public FlakySource(FixtureSource f, Exception fail) { _f = f; _fail = fail; }
        public Task<JsonDocument> GetHeightfieldAsync()
            => ++HeightfieldCalls == 1 ? Task.FromException<JsonDocument>(_fail) : _f.GetHeightfieldAsync();
        public Task<JsonDocument> GetWorldMapAsync() => _f.GetWorldMapAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys) => _f.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync() => _f.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string id) => _f.GetLocationSceneAsync(id);
        public Task<byte[]> GetBytesAsync(string url) => _f.GetBytesAsync(url);
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => _f.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync() => _f.GetAnimationClipsAsync();
        public Task<JsonDocument> GetTerrainAsync() => _f.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys) => _f.GetTerrainLayersAsync(keys);
        public Task<JsonDocument> GetSurfaceTexturesAsync() => _f.GetSurfaceTexturesAsync();
    }
}
