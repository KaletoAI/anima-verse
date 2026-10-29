using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 63 / E10-T2: real API and restartable disk store; instance-owned transport/state/directories
/// catch missing revalidation, batch-shaped keys, cross-signature reuse and publication of raced responses.</summary>
public sealed class JsonCacheTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "anima-json-cache-" + Guid.NewGuid().ToString("N"));
    private DiskCache Store() => new(_root, new Uri("https://fixture.test"));
    private AnimaApi Api(Server server) => new("https://fixture.test", server, Store());
    public void Dispose() { if (Directory.Exists(_root)) Directory.Delete(_root, true); }

    private sealed class Server : HttpMessageHandler
    {
        public string Height = "h1", Layers = "l1", Terrain = "t1", Scene = "s1", Epoch = "process1";
        public string? BatchSig;
        public string Policy = "no-cache";
        public HttpStatusCode SceneStatus = HttpStatusCode.OK;
        public bool SceneEtag = true;
        public readonly List<string> Requests = new();
        public readonly List<string> Conditionals = new();
        public readonly TaskCompletionSource Entered = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public readonly TaskCompletionSource Release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public bool HoldBatch;
        public string? OmitKey;
        public int Count(string path) => Requests.Count(r => r.Split('?')[0] == path);
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage req, CancellationToken ct)
        {
            string path = req.RequestUri!.AbsolutePath;
            Requests.Add(req.RequestUri.PathAndQuery);
            string conditional = string.Join(",", req.Headers.IfNoneMatch);
            if (conditional.Length > 0) Conditionals.Add(conditional);
            bool scene = path.EndsWith("/scene", StringComparison.Ordinal);
            var status = scene && SceneStatus != HttpStatusCode.OK ? SceneStatus
                : scene && SceneEtag && conditional == "\"" + Scene + "\"" ? HttpStatusCode.NotModified : HttpStatusCode.OK;
            var res = new HttpResponseMessage(status);
            res.Headers.TryAddWithoutValidation("Cache-Control", Policy);
            res.Headers.TryAddWithoutValidation("Set-Cookie", "av_session=SECRET_SESSION");
            if (scene && SceneEtag) res.Headers.TryAddWithoutValidation("ETag", "\"" + Scene + "\"");
            if (scene) { res.Content = new StringContent(JsonSerializer.Serialize(new { revision = Scene })); return res; }
            string sig = path.Contains("heightfield", StringComparison.Ordinal) ? Height : path == "/play/terrain-layers" ? Layers : Terrain;
            string query = Uri.UnescapeDataString(req.RequestUri.Query);
            bool batch = query.StartsWith("?keys=", StringComparison.Ordinal);
            var keys = batch ? query[6..].Split(',').Select(k => k.Replace(':', ',')).ToArray() : Array.Empty<string>();
            if (batch && HoldBatch) { Entered.TrySetResult(); await Release.Task; }
            if (batch) sig = BatchSig ?? sig;
            object payload = path == "/play/worldmap" ? new { height_sig = Height, terrain_sig = Terrain, locations_rev = Epoch }
                : scene ? new { revision = Scene } : new Dictionary<string, object>
                {
                    ["sig"] = sig, ["tile_m"] = 32, ["step_m"] = 2, ["layers"] = new[] { new { kind = "grass", index = 0 } },
                    [path.EndsWith("/stats", StringComparison.Ordinal) ? "tile_stats" : "tiles"] = keys.Where(k => k != OmitKey).ToDictionary(k => k,
                        k => new { marker = sig + ":" + k }),
                };
            res.Content = new StringContent(JsonSerializer.Serialize(payload));
            return res;
        }
    }

    private static async Task Index(AnimaApi api)
    {
        using var map = await api.GetWorldMapAsync();
        using var height = await api.GetHeightfieldAsync();
        using var layers = await api.GetTerrainLayersAsync(Array.Empty<string>());
    }
    private static Task<JsonDocument> Batch(AnimaApi api, string kind, params int[] xs) => kind switch
    {
        "tiles" => api.GetHeightTilesAsync(xs.Select(x => (x, 0)).ToArray()),
        "stats" => api.GetHeightTileStatsAsync(xs.Select(x => (x, 0)).ToArray()),
        _ => api.GetTerrainLayersAsync(xs.Select(x => $"{x},0").ToArray()),
    };
    private static string Endpoint(string kind) => kind == "masks" ? "/play/terrain-layers" : "/play/heightfield/" + kind;

    [Fact]
    public async Task SceneRestartRevalidatesAndChangedFingerprintReplacesExactlyOneScene()
    {
        var server = new Server { Policy = "public, max-age=31536000, immutable" };
        using (var api = Api(server)) { using var a = await api.GetLocationSceneAsync("a"); using var b = await api.GetLocationSceneAsync("b"); }
        server.Epoch = "process2";
        using (var api = Api(server))
        {
            using var map = await api.GetWorldMapAsync();
            using var a = await api.GetLocationSceneAsync("a");
            Assert.Equal("s1", a!.RootElement.GetProperty("revision").GetString());
            Assert.Single(server.Conditionals);
            server.Scene = "s2";
            using var changed = await api.GetLocationSceneAsync("a");
            Assert.Equal("s2", changed!.RootElement.GetProperty("revision").GetString());
        }
        Assert.Equal(2, Store().Count);
        Assert.DoesNotContain("SECRET_SESSION", File.ReadAllText(Path.Combine(Store().DirectoryPath, "index.json")));
    }

    [Theory]
    [InlineData("tiles")]
    [InlineData("stats")]
    [InlineData("masks")]
    public async Task RestartUsesPerTileKeysAcrossReorderedAndPartiallyCachedBatches(string kind)
    {
        var server = new Server();
        using (var api = Api(server)) { await Index(api); using var batch = await Batch(api, kind, 0, 1); }
        server.Epoch = "process2";
        int before = server.Count(Endpoint(kind));
        using (var api = Api(server))
        {
            await Index(api);
            using var hit = await Batch(api, kind, 1, 0);
            Assert.Equal(before + (kind == "masks" ? 1 : 0), server.Count(Endpoint(kind)));
            using var partial = await Batch(api, kind, 1, 2);
            string field = kind == "stats" ? "tile_stats" : "tiles";
            Assert.Equal(new[] { "1,0", "2,0" }, partial.RootElement.GetProperty(field).EnumerateObject().Select(p => p.Name));
            Assert.EndsWith("?keys=2%3A0", server.Requests.Last());
            using var metadata = JsonDocument.Parse(partial.RootElement.GetRawText());
            Assert.Equal(32, metadata.RootElement.GetProperty("tile_m").GetInt32());
        }
    }

    [Fact]
    public async Task HeightChangeRefetchesOnlyHeightDataAndNeverUsesLocationsEpoch()
    {
        var server = new Server();
        using (var api = Api(server))
        {
            await Index(api);
            using var tiles = await Batch(api, "tiles", 0);
            using var stats = await Batch(api, "stats", 0);
            using var masks = await Batch(api, "masks", 0);
            using var terrain = await api.GetTerrainAsync();
        }
        server.Height = "h2"; server.Epoch = "process2";
        using (var api = Api(server))
        {
            await Index(api);
            using var tiles = await Batch(api, "tiles", 0);
            using var stats = await Batch(api, "stats", 0);
            using var masks = await Batch(api, "masks", 0);
            using var terrain = await api.GetTerrainAsync();
            Assert.Equal("h2:0,0", tiles.RootElement.GetProperty("tiles").GetProperty("0,0").GetProperty("marker").GetString());
        }
        Assert.Equal(2, server.Count("/play/heightfield/tiles"));
        Assert.Equal(2, server.Count("/play/heightfield/stats"));
        Assert.Equal(3, server.Count("/play/terrain-layers")); // two indexes, one mask batch
        Assert.Equal(1, server.Count("/play/terrain"));
    }

    [Theory]
    [InlineData("tiles")]
    [InlineData("stats")]
    [InlineData("masks")]
    public async Task MismatchingOrMissingBatchSignatureIsMemoryOnly(string kind)
    {
        var server = new Server { BatchSig = "newer" };
        using var api = Api(server);
        await Index(api);
        using var newer = await Batch(api, kind, 0);
        Assert.Equal("newer", newer.RootElement.GetProperty("sig").GetString());
        Assert.Equal(0, Store().Count);
        server.BatchSig = "";
        using var missing = await Batch(api, kind, 0);
        Assert.Equal(0, Store().Count);
    }

    [Theory]
    [InlineData("tiles")]
    [InlineData("stats")]
    [InlineData("masks")]
    public async Task IndexMovesDuringRequestDoNotPublishTheOldBatch(string kind)
    {
        var server = new Server { HoldBatch = true };
        using var api = Api(server);
        await Index(api);
        var pending = Batch(api, kind, 0);
        await server.Entered.Task;
        server.Height = "h2"; server.Layers = "l2";
        await Index(api);
        server.Release.TrySetResult();
        using var old = await pending;
        Assert.Equal(0, Store().Count);
    }

    [Fact]
    public async Task TerrainUsesWorldmapSignatureAndRejectsMismatchingResponse()
    {
        var server = new Server();
        using var api = Api(server);
        await Index(api);
        using var first = await api.GetTerrainAsync();
        using var hit = await api.GetTerrainAsync();
        Assert.Equal(1, server.Count("/play/terrain"));
        server.Terrain = "t2";
        using var map = await api.GetWorldMapAsync();
        server.Terrain = "newer";
        using var mismatch = await api.GetTerrainAsync();
        Assert.Equal("newer", mismatch.RootElement.GetProperty("sig").GetString());
        Assert.Equal(1, Store().Count);
        using var again = await api.GetTerrainAsync();
        Assert.Equal(3, server.Count("/play/terrain"));
    }

    [Theory]
    [InlineData(HttpStatusCode.NotFound)]
    [InlineData(HttpStatusCode.Unauthorized)]
    public async Task SceneErrorsNeverServeTheOldBody(HttpStatusCode status)
    {
        var server = new Server();
        using var api = Api(server);
        using var first = await api.GetLocationSceneAsync("a");
        server.SceneStatus = status;
        int unauthorized = 0; api.Unauthorized += () => unauthorized++;
        if (status == HttpStatusCode.NotFound) Assert.Null(await api.GetLocationSceneAsync("a"));
        else Assert.Equal(401, (await Assert.ThrowsAsync<ApiException>(() => api.GetLocationSceneAsync("a"))).Status);
        Assert.Equal(status == HttpStatusCode.Unauthorized ? 1 : 0, unauthorized);
    }

    [Fact]
    public async Task NoIndexOrNoStoreNeverCreatesSignatureEntries()
    {
        var server = new Server();
        using var api = Api(server);
        using var noIndex = await Batch(api, "tiles", 0);
        using var terrain = await api.GetTerrainAsync();
        Assert.Equal(0, Store().Count);
        await Index(api); server.Policy = "no-store";
        using var noStore = await Batch(api, "tiles", 0);
        using var scene = await api.GetLocationSceneAsync("a");
        Assert.Equal(0, Store().Count);
    }

    [Fact]
    public async Task ChangedLayerAndTerrainSignaturesFetchTheirOwnDataOnly()
    {
        var server = new Server();
        using var api = Api(server);
        await Index(api);
        using var tiles = await Batch(api, "tiles", 0);
        using var firstMasks = await Batch(api, "masks", 0);
        using var firstTerrain = await api.GetTerrainAsync();
        server.Layers = "l2"; server.Terrain = "t2";
        await Index(api);
        using var keptTiles = await Batch(api, "tiles", 0);
        using var newMasks = await Batch(api, "masks", 0);
        using var newTerrain = await api.GetTerrainAsync();
        Assert.Equal("l2", newMasks.RootElement.GetProperty("sig").GetString());
        Assert.Equal("t2", newTerrain.RootElement.GetProperty("sig").GetString());
        Assert.Equal(1, server.Count("/play/heightfield/tiles"));
        Assert.Equal(4, server.Count("/play/terrain-layers"));
        Assert.Equal(2, server.Count("/play/terrain"));
    }

    [Theory]
    [InlineData("tiles")]
    [InlineData("stats")]
    [InlineData("masks")]
    public async Task PartialHitNeverMixesTwoSignaturesAndMissingKeysAreNotNegativeCached(string kind)
    {
        var server = new Server { OmitKey = "1,0" };
        using var api = Api(server);
        await Index(api);
        using var first = await Batch(api, kind, 0, 1);
        server.OmitKey = null;
        using var retry = await Batch(api, kind, 0, 1);
        Assert.EndsWith("?keys=1%3A0", server.Requests.Last());
        server.BatchSig = "newer";
        using var mismatch = await Batch(api, kind, 0, 2);
        string field = kind == "stats" ? "tile_stats" : "tiles";
        Assert.Equal("newer", mismatch.RootElement.GetProperty("sig").GetString());
        Assert.Equal(2, mismatch.RootElement.GetProperty(field).EnumerateObject().Count());
        Assert.All(mismatch.RootElement.GetProperty(field).EnumerateObject(), p =>
            Assert.StartsWith("newer:", p.Value.GetProperty("marker").GetString()));
        Assert.Equal(2, Store().Count);
    }

    [Fact]
    public async Task PollInvalidatesHeightReuseUntilTheNewOverviewArrives()
    {
        var server = new Server();
        using var api = Api(server);
        await Index(api);
        using var first = await Batch(api, "tiles", 0);
        server.Height = "h2";
        using var map = await api.GetWorldMapAsync();
        using var moved = await Batch(api, "tiles", 0);
        Assert.Equal("h2", moved.RootElement.GetProperty("sig").GetString());
        Assert.Equal(1, Store().Count);
        using var overview = await api.GetHeightfieldAsync();
        using var nowCurrent = await Batch(api, "tiles", 0);
        Assert.Equal(3, server.Count("/play/heightfield/tiles"));
        Assert.Equal(2, Store().Count);
    }

    [Fact]
    public async Task SceneWithoutValidatorDropsPriorEntryAndNoStore304DropsBody()
    {
        var server = new Server();
        using var api = Api(server);
        using var first = await api.GetLocationSceneAsync("a");
        server.SceneEtag = false;
        using var unvalidated = await api.GetLocationSceneAsync("a");
        Assert.Equal(0, Store().Count);
        server.SceneEtag = true;
        using var restored = await api.GetLocationSceneAsync("a");
        server.Policy = "no-store";
        using var noStore304 = await api.GetLocationSceneAsync("a");
        Assert.Equal("s1", noStore304!.RootElement.GetProperty("revision").GetString());
        Assert.Equal(0, Store().Count);
    }


    [Fact]
    public async Task PollDiscoversChangedFloorMasksWithoutTerrainChangeOrExplicitReindex()
    {
        var server = new Server();
        using var api = Api(server);
        await Index(api);
        using var first = await Batch(api, "masks", 0);
        server.Layers = "room-floor-changed";
        using var poll = await api.GetWorldMapAsync(); // terrain_sig remains t1
        using var returnedToTile = await Batch(api, "masks", 0);
        Assert.Equal("room-floor-changed", returnedToTile.RootElement.GetProperty("sig").GetString());
        Assert.Equal("room-floor-changed:0,0", returnedToTile.RootElement.GetProperty("tiles")
            .GetProperty("0,0").GetProperty("marker").GetString());
        Assert.Equal(4, server.Count("/play/terrain-layers")); // two live indexes, two different mask cuts
    }

    [Fact]
    public async Task SlowDiskPublicationNeverSynchronouslyBlocksThePollCaller()
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        int clockReads = 0;
        var cache = new DiskCache(_root, new Uri("https://fixture.test"), now: () =>
        {
            // First read computes response policy; the second happens inside real DiskCache.Store.
            if (Interlocked.Increment(ref clockReads) == 2) { entered.Set(); release.Wait(); }
            return DateTimeOffset.Parse("2026-10-29T12:00:00Z");
        });
        using var api = new AnimaApi("https://fixture.test", new Server(), cache);
        await Index(api);
        var writing = api.GetTerrainAsync();
        var returned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Task? polling = null;
        bool returnedWithoutDisk = false;
        try
        {
            Assert.True(await Task.Run(() => entered.Wait(TimeSpan.FromSeconds(5))), "terrain publication must reach the disk store");
            polling = Task.Run(async () =>
            {
                var pending = api.GetWorldMapAsync();
                returned.TrySetResult(); // the async API must return control before waiting for disk publication
                using var map = await pending;
            });
            returnedWithoutDisk = await Task.WhenAny(returned.Task, Task.Delay(2000)) == returned.Task;
        }
        finally
        {
            release.Set();
            using var terrain = await writing;
            if (polling is not null) await polling;
        }
        Assert.True(returnedWithoutDisk, "poll caller blocked synchronously behind cache filesystem writes");
    }

}
