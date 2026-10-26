using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
using AnimaNative.Terrain;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The terrain streaming of ground.ts (<see cref="TerrainStream"/>) on simulated camera paths, against a fake server
/// that answers batches. Every expectation is derived BY HAND in the test's comment from the rules of
/// client3d/src/scene/ground.ts + heightTiles.ts (want set = indexed tiles whose 256 m square lies within 560 m of the
/// anchor by box distance, nearest first, ties by ordinal key; 64 height keys / 16 mask keys per request; LRU 96 that
/// never drops a wanted tile; a moved signature drops a batch, re-takes an index or reloads the relief).
///
/// Distances used throughout: an anchor in the CENTRE of tile k (x = 256k + 128) has box distance 0 to tile k,
/// 256·1 − 128 = 128 to k ± 1, 384 to k ± 2 and 640 to k ± 3 — so per axis the want set is k − 2 … k + 2
/// (640 > 560), and a diagonal (±2, ±2) is √(2 · 384²) = 543.06 ≤ 560 (in), (±2, ±3) is out.
/// </summary>
public class TerrainStreamTests
{
    // ---- the fake server ----------------------------------------------------------------------------------------

    private sealed class FakeServer : IWorldSource
    {
        public List<string> Index = new();
        public string HeightSig = "h1";
        public bool StatsComplete = true;
        public Dictionary<string, JsonObject> Stats = new();
        public Func<string, double> HeightOf = _ => 0;
        /// <summary>A batch answers under this sig (null = the current one).</summary>
        public string? TileSigOverride;
        public HashSet<string> WrongOrigin = new();
        public bool FailTiles;
        public List<string> LayerIndex = new();
        public string LayerSig = "L1";
        public string? LayerBatchSig;
        public string LayerIndexSig = "L1";
        public readonly List<string> Log = new();

        private static string K((int Tx, int Tz) k) => $"{k.Tx},{k.Tz}";

        public Task<JsonDocument> GetHeightfieldAsync()
        {
            Log.Add("height-index");
            var o = new JsonObject
            {
                ["origin_x"] = 0, ["origin_z"] = 0, ["step_m"] = 256, ["rows"] = 2, ["cols"] = 2,
                ["heights"] = new JsonArray(new JsonArray(0, 0), new JsonArray(0, 0)),
                ["sig"] = HeightSig, ["tile_m"] = 256, ["tile_step_m"] = 2,
                ["tiles"] = new JsonArray(Index.Select(k => (JsonNode)JsonValue.Create(k)!).ToArray()),
                ["mip_levels_m"] = new JsonArray(4, 8, 16, 32, 64),
                ["tile_stats"] = new JsonObject(), ["tile_stats_complete"] = StatsComplete,
            };
            return Task.FromResult(JsonDocument.Parse(o.ToJsonString()));
        }

        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys)
        {
            Log.Add("tiles " + string.Join(";", keys.Select(K)));
            if (FailTiles) return Task.FromException<JsonDocument>(new ApiException(503, "/play/heightfield/tiles"));
            var tiles = new JsonObject();
            foreach (var k in keys)
            {
                var key = K(k);
                if (!Index.Contains(key)) continue;
                double h = HeightOf(key);
                tiles[key] = new JsonObject
                {
                    ["origin_x"] = WrongOrigin.Contains(key) ? k.Tx * 256 + 2 : k.Tx * 256, ["origin_z"] = k.Tz * 256,
                    ["rows"] = 2, ["cols"] = 2, ["heights"] = new JsonArray(new JsonArray(h, h), new JsonArray(h, h)),
                    ["stats"] = new JsonObject { ["min"] = h, ["max"] = h, ["err"] = new JsonArray(0, 0, 0, 0, 0) },
                };
            }
            var o = new JsonObject { ["sig"] = TileSigOverride ?? HeightSig, ["tile_m"] = 256, ["step_m"] = 2, ["tiles"] = tiles };
            return Task.FromResult(JsonDocument.Parse(o.ToJsonString()));
        }

        public Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys)
        {
            Log.Add("stats " + string.Join(";", keys.Select(K)));
            var stats = new JsonObject();
            foreach (var k in keys)
            {
                var key = K(k);
                if (!Index.Contains(key)) continue;
                stats[key] = Stats.TryGetValue(key, out var s) ? s.DeepClone()
                    : new JsonObject { ["min"] = 0, ["max"] = 0, ["err"] = new JsonArray(0, 0, 0, 0, 0) };
            }
            return Task.FromResult(JsonDocument.Parse(new JsonObject { ["sig"] = HeightSig, ["tile_stats"] = stats }.ToJsonString()));
        }

        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys)
        {
            Log.Add(keys.Count == 0 ? "mask-index" : "masks " + string.Join(";", keys));
            var o = new JsonObject
            {
                ["tile_m"] = 256, ["id_step_m"] = 1, ["sd_step_m"] = 0.5, ["sd_band_m"] = 8, ["sd_zero"] = 128,
                ["sd_codes_per_m"] = 15.875, ["layers"] = new JsonArray(),
            };
            if (keys.Count == 0)
            {
                o["sig"] = LayerIndexSig;
                o["tile_keys"] = new JsonArray(LayerIndex.Select(k => (JsonNode)JsonValue.Create(k)!).ToArray());
            }
            else
            {
                o["sig"] = LayerBatchSig ?? LayerSig;
                var tiles = new JsonObject();
                foreach (var k in keys.Where(LayerIndex.Contains)) tiles[k] = new JsonObject { ["uniform"] = 1 };
                o["tiles"] = tiles;
            }
            return Task.FromResult(JsonDocument.Parse(o.ToJsonString()));
        }

        public Task<JsonDocument> GetWorldMapAsync() => throw new NotSupportedException();
        public Task<JsonDocument> GetLocations3dAsync() => throw new NotSupportedException();
        public Task<JsonDocument?> GetLocationSceneAsync(string locationId) => throw new NotSupportedException();
        public Task<byte[]> GetBytesAsync(string url) => throw new NotSupportedException();
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => throw new NotSupportedException();
        public Task<JsonDocument> GetAnimationClipsAsync() => throw new NotSupportedException();
        public Task<JsonDocument> GetTerrainAsync() => throw new NotSupportedException();
        public Task<JsonDocument> GetSurfaceTexturesAsync() => throw new NotSupportedException();
    }

    private static List<string> Strip(int lo, int hi) => Enumerable.Range(lo, hi - lo + 1).Select(i => $"{i},0").ToList();

    /// <summary>A square index, z-major (the server's payload order: row 0 west to east, then row 1, …).</summary>
    private static List<string> Square(int lo, int hi)
        => Enumerable.Range(lo, hi - lo + 1).SelectMany(z => Enumerable.Range(lo, hi - lo + 1).Select(x => $"{x},{z}")).ToList();

    /// <summary>The server's relief with the boot ring at (x, z) loaded the way WorldBuilder loads it.</summary>
    private static async Task<WorldHeight> BootHeight(FakeServer server, double x, double z)
    {
        using var hf = await server.GetHeightfieldAsync();
        var height = new WorldHeight(HeightfieldOverview.Parse(hf.RootElement));
        foreach (var batch in HeightTiles.TileBatches(height.IndexedTilesNear(x, z, HeightTiles.RadiusM)))
        {
            using var doc = await server.GetHeightTilesAsync(batch);
            height.AddTiles(HeightTile.ParseBatch(doc.RootElement));
        }
        return height;
    }

    /// <summary>A stream on <see cref="BootHeight"/>, seeded at (x, z), the request log cleared.</summary>
    private static async Task<TerrainStream> Boot(FakeServer server, double x, double z, int? cacheMax = null)
    {
        var height = await BootHeight(server, x, z);
        var stream = new TerrainStream(server, height, _ => { }) { Inline = true, CacheMax = cacheMax ?? HeightTiles.CacheMax };
        stream.Seed("", "t1", x, z);
        server.Log.Clear();
        return stream;
    }

    private static double Centre(int k) => 256 * k + 128;

    // ---- height tiles ---------------------------------------------------------------------------------------------

    /// <summary>
    /// A 30 × 30 index, boot at (128, 128) — the centre of tile 0,0, so only k = 0, 1, 2 per axis exist on the near side:
    /// (0,0) d² 0; (0,1), (1,0) 128² = 16 384 (ordinal "0,1" &lt; "1,0"); (1,1) 2·128² = 32 768; (0,2), (2,0) 384² =
    /// 147 456; (1,2), (2,1) 384² + 128² = 163 840; (2,2) 2·384² = 294 912 ≤ 560² = 313 600 → nine tiles, one request
    /// (≤ 64) in exactly this order.
    /// </summary>
    [Fact]
    public async Task BootRingIsTheNineNearestInOrder()
    {
        var server = new FakeServer { Index = Square(0, 29) };
        using var hf = await server.GetHeightfieldAsync();
        var height = new WorldHeight(HeightfieldOverview.Parse(hf.RootElement));
        var keys = height.IndexedTilesNear(128, 128, HeightTiles.RadiusM).Select(k => $"{k.Tx},{k.Tz}");
        Assert.Equal("0,0 0,1 1,0 1,1 0,2 2,0 1,2 2,1 2,2", string.Join(" ", keys));
    }

    /// <summary>
    /// The camera target walks a 1-row strip (tiles 0,0 … 199,0) one tile at a time from the centre of tile 2 to the
    /// centre of tile 120. Want at k = tiles k − 2 … k + 2 (see the class comment). The boot ring at k = 2 is 0 … 4; each
    /// step to k + 1 wants exactly one new tile, k + 3 → one request of one key per step, nearest-first trivially:
    /// "tiles 5,0", "tiles 6,0", …, "tiles 122,0" = 118 requests. Held after step k: 0 … k + 2, i.e. k + 3 tiles, until
    /// that passes 96 at k = 94; from then on each step evicts the oldest unwanted tile. The LRU order: every step
    /// touches its five wanted tiles, so the untouched front is 0, 1, 2, … in key order → after k = 120:
    /// 120 + 3 − 96 = 27 evictions, exactly tiles 0 … 26; held = 27 … 122 (96).
    /// </summary>
    [Fact]
    public async Task WalkingAStripEvictsTheOldestBeyondNinetySix()
    {
        var server = new FakeServer { Index = Strip(0, 199) };
        var stream = await Boot(server, Centre(2), 128);
        Assert.Equal(5, stream.Height.Tiles.Count);
        for (int k = 3; k <= 120; k++)
        {
            await stream.SetAnchor(Centre(k), 128);
            Assert.Equal(Math.Min(k + 3, 96), stream.Height.Tiles.Count);
        }
        Assert.Equal(118, server.Log.Count);
        Assert.Equal("tiles 5,0", server.Log[0]);
        Assert.Equal("tiles 122,0", server.Log[^1]);
        Assert.All(server.Log, l => Assert.Matches(@"^tiles \d+,0$", l));
        Assert.Equal(27, stream.Counters.TilesEvicted);
        var held = stream.Height.Tiles.Select(t => t.Key.Tx).OrderBy(x => x).ToList();
        Assert.Equal(Enumerable.Range(27, 96), held);
        Assert.Equal(118, stream.Counters.HeightBatches);
    }

    /// <summary>
    /// A tile border crossing is the only immediate occasion: moving inside tile 5 (x 1280 … 1535) asks nothing; one
    /// metre over the border (x = 1536, tile 6) asks for the new rim. At x = 1536 the want set: tile 6 d 0, tile 5 d 0
    /// (the anchor is on the shared edge, box distance 0), tile 7 256, tile 4 256, tile 8 512, tile 3 512, tile 9 768
    /// (out), tile 2 768 (out) → 3 … 8; the boot at the centre of tile 5 held 3 … 7 → one request "tiles 8,0".
    /// </summary>
    [Fact]
    public async Task OnlyACrossedBorderAsksAtOnce()
    {
        var server = new FakeServer { Index = Strip(0, 20) };
        var stream = await Boot(server, Centre(5), 128);
        await stream.SetAnchor(1290, 128);
        await stream.SetAnchor(1530, 100);
        Assert.Empty(server.Log);
        await stream.SetAnchor(1536, 128);
        Assert.Equal(new[] { "tiles 8,0" }, server.Log);
    }

    /// <summary>
    /// <c>HEIGHT_TILE_CACHE_MAX</c> below the want set (a check's setting): the five wanted tiles of a strip anchor all
    /// stay even though the cap is 4 — dropping one would refetch it in the same breath. Boot at k = 2 holds 0 … 4;
    /// the move to k = 3 takes 5 → six held, order 0, (touched) 1… : evict while over 4 and not wanted → only tile 0
    /// (not wanted at k = 3) goes → five held, one eviction.
    /// </summary>
    [Fact]
    public async Task AWantedTileIsNeverEvicted()
    {
        var server = new FakeServer { Index = Strip(0, 20) };
        var stream = await Boot(server, Centre(2), 128, cacheMax: 4);
        await stream.SetAnchor(Centre(3), 128);
        Assert.Equal(new[] { 1, 2, 3, 4, 5 }, stream.Height.Tiles.Select(t => t.Key.Tx).OrderBy(x => x));
        Assert.Equal(1, stream.Counters.TilesEvicted);
    }

    /// <summary>The LRU front is the oldest WANTED, not the oldest fetched: a tile re-wanted moves to the back.</summary>
    [Fact]
    public void TouchMovesAHeldTileToTheBack()
    {
        using var ov = JsonDocument.Parse("""{"heights": [[0, 0], [0, 0]], "step_m": 256, "tile_m": 256, "tiles": ["0,0", "1,0", "2,0"]}""");
        var h = new WorldHeight(HeightfieldOverview.Parse(ov.RootElement));
        using var t = JsonDocument.Parse("""
            {"sig": "", "step_m": 2, "tiles": {"0,0": {"origin_x": 0, "origin_z": 0, "heights": [[1, 1], [1, 1]]},
             "1,0": {"origin_x": 256, "origin_z": 0, "heights": [[2, 2], [2, 2]]}, "2,0": {"origin_x": 512, "origin_z": 0, "heights": [[3, 3], [3, 3]]}}}
            """);
        h.AddTiles(HeightTile.ParseBatch(t.RootElement));
        h.Touch((0, 0));
        h.Touch((9, 9));
        Assert.Equal(new[] { (1, 0), (2, 0), (0, 0) }, h.LruOrder);
        var snap = h.Snapshot();
        Assert.True(h.RemoveTile((1, 0)));
        Assert.False(h.RemoveTile((1, 0)));
        Assert.Equal(3, snap.Tiles.Count);   // the snapshot is a copy
        Assert.Equal(2, snap.GroundAt(300, 10));
        Assert.Equal(0, h.GroundAt(300, 10));   // evicted → the overview
        Assert.Equal(new[] { (2, 0), (0, 0) }, h.LruOrder);
    }

    /// <summary>
    /// A batch answering under another <c>height_sig</c> (the relief was replaced while it was in flight) is dropped
    /// whole, and the missing keys stay wanted: the next idle poll asks for the same keys again and takes them.
    /// A tile whose origin is not its key's square (tile 4: origin 1026 instead of 1024) is dropped on its own.
    /// </summary>
    [Fact]
    public async Task AStaleBatchIsDroppedAndAWrongOriginTileToo()
    {
        var server = new FakeServer { Index = Strip(0, 20) };
        var stream = await Boot(server, Centre(1), 128);   // holds 0 … 3
        server.TileSigOverride = "h0";
        await stream.SetAnchor(Centre(2), 128);            // wants 0 … 4 → "tiles 4,0", answered under h0
        Assert.Equal(new[] { "tiles 4,0" }, server.Log);
        Assert.Equal(1, stream.Counters.HeightBatchesDropped);
        Assert.False(stream.Height.HasTile((4, 0)));
        server.TileSigOverride = null;
        server.WrongOrigin.Add("4,0");
        Assert.False(await stream.SyncAsync("t1", "h1"));   // idle poll: the loaders run again
        Assert.Equal(new[] { "tiles 4,0", "tiles 4,0" }, server.Log);
        Assert.Equal(1, stream.Counters.TilesDropped);
        Assert.False(stream.Height.HasTile((4, 0)));
        server.WrongOrigin.Clear();
        await stream.SyncAsync("t1", "h1");
        Assert.True(stream.Height.HasTile((4, 0)));
        Assert.Equal(1, stream.Counters.HeightBatches);
    }

    /// <summary>A failed request keeps what stands; the missing keys stay wanted and the idle poll fetches them.</summary>
    [Fact]
    public async Task AFailedBatchIsRetriedByTheIdlePoll()
    {
        var server = new FakeServer { Index = Strip(0, 20) };
        var stream = await Boot(server, Centre(1), 128);
        server.FailTiles = true;
        int rebuilds = 0;
        stream.FieldChanged = () => { rebuilds++; return Task.CompletedTask; };
        await stream.SetAnchor(Centre(2), 128);
        Assert.Equal(1, stream.Counters.FailedBatches);
        Assert.Equal(0, rebuilds);
        server.FailTiles = false;
        await stream.SyncAsync("t1", "h1");
        Assert.True(stream.Height.HasTile((4, 0)));
        Assert.Equal(1, rebuilds);
    }

    /// <summary>
    /// Every taken batch re-drapes ONCE and bumps the height revision ONCE (the re-datum of the locations hangs on it):
    /// the anchor jumps from the centre of tile 2 to the centre of tile 10 — want 8 … 12, all missing, one request with
    /// the nearest first: 10 (0), 9 and 11 (128; "11,0" &lt; "9,0" ordinal), 12 and 8 (384; "12,0" &lt; "8,0").
    /// </summary>
    [Fact]
    public async Task AJumpIsOneNearestFirstBatchAndOneRebuild()
    {
        var server = new FakeServer { Index = Strip(0, 20), HeightOf = k => int.Parse(k.Split(',')[0]) };
        var stream = await Boot(server, Centre(2), 128);
        int rev = stream.Height.Revision, rebuilds = 0;
        stream.FieldChanged = () => { rebuilds++; return Task.CompletedTask; };
        await stream.SetAnchor(Centre(10), 128);
        Assert.Equal(new[] { "tiles 10,0;11,0;9,0;12,0;8,0" }, server.Log);
        Assert.Equal(1, rebuilds);
        Assert.Equal(rev + 1, stream.Height.Revision);
        Assert.Equal(10, stream.Height.GroundAt(Centre(10), 128));
    }

    // ---- statistics -----------------------------------------------------------------------------------------------

    /// <summary>
    /// A 30 × 30 index (900 tiles, payload order z-major: "0,0", "1,0", …, "29,0", "0,1", …) whose overview says
    /// <c>tile_stats_complete: false</c> and carries none. The boot ring at (128, 128) holds nine tiles with their
    /// statistics, so 891 are missing → batches of 64 in index order: 13 × 64 + 59 = 891 → 14 requests; the first is
    /// the first 64 index keys without the held ones: row 0 minus 0,0 1,0 2,0 = 27, row 1 minus 0,1 1,1 2,1 = 27, row 2
    /// minus 0,2 1,2 2,2 = the first 10 of 27 → 3,0 … 29,0, 3,1 … 29,1, 3,2 … 12,2. The level errors follow: tile 29,29
    /// reports err [0.5, 1, 2, 4, 8] (mip 4, 8, 16, 32, 64 m) → at base step 2 the ladder levels 1 … 5 are 4 … 64 m →
    /// errors [0, 0.5, 1, 2, 4, 8] once its batch (the last) is in.
    /// </summary>
    [Fact]
    public async Task StatsFillWalksTheIndexInBatchesOf64()
    {
        var server = new FakeServer { Index = Square(0, 29), StatsComplete = false };
        server.Stats["29,29"] = new JsonObject { ["min"] = 0, ["max"] = 9, ["err"] = new JsonArray(0.5, 1, 2, 4, 8) };
        var stream = await Boot(server, 128, 128);
        int changed = 0;
        stream.StatsChanged = () => changed++;
        await stream.StartStatsFill();
        Assert.Equal(14, server.Log.Count);
        var first = Enumerable.Range(3, 27).Select(x => $"{x},0").Concat(Enumerable.Range(3, 27).Select(x => $"{x},1"))
                              .Concat(Enumerable.Range(3, 10).Select(x => $"{x},2"));
        Assert.Equal("stats " + string.Join(";", first), server.Log[0]);
        Assert.Equal(64, server.Log[0].Split(';').Length);
        Assert.Equal(59, server.Log[^1].Split(';').Length);
        Assert.Equal(900, stream.Height.Stats.Count);
        Assert.Equal(14, changed);
        Assert.Equal(891, stream.Counters.StatsTaken);
        var field = TerrainField.Build(stream.Height, 128, 128, null, new double[] { 0, 0, 7680, 7680 });
        Assert.Equal(new[] { 0, 0.5, 1, 2, 4, 8 }, field.LevelErrorM);
    }

    /// <summary>
    /// The fill steps aside for the picture: the anchor moved to a tile whose want set is not held yet (the centre of
    /// tile 10,10 of a 30 × 30 index), so <c>groundBusy</c> is true and the fill waits (one idle wait) — the wait lets
    /// the tile loader run first, and only then does the first statistics request go out.
    /// </summary>
    [Fact]
    public async Task StatsFillWaitsWhileTheGroundIsBusy()
    {
        var server = new FakeServer { Index = Square(0, 29), StatsComplete = false };
        var height = await BootHeight(server, 128, 128);
        TerrainStream? s = null;
        int waits = 0;
        s = new TerrainStream(server, height, _ => { })
        {
            Inline = true,
            // The idle wait is where the tile loader gets its turn.
            Delay = async _ => { waits++; await s!.RefreshTilesAsync(); },
        };
        // Seeded at the centre of tile 10,10, whose ring nobody has loaded yet (the loader is "about to run").
        s.Seed("", "t1", Centre(10), Centre(10));
        server.Log.Clear();
        Assert.True(s.GroundBusy());
        await s.StartStatsFill();
        Assert.Equal(1, waits);
        Assert.StartsWith("tiles 10,10;", server.Log[0]);
        Assert.StartsWith("stats ", server.Log[1]);
    }

    // ---- signatures -----------------------------------------------------------------------------------------------

    /// <summary>
    /// A new <c>height_sig</c> on the poll: the overview is refetched, the tiles are thrown away with the old relief
    /// (revision + 1), the host re-drapes on the new overview, the areas rebuild once, and the anchor forgets its tile —
    /// the next tick (same point!) refetches the ring under the new signature. The same poll again changes nothing.
    /// </summary>
    [Fact]
    public async Task ANewHeightSigReloadsTheRelief()
    {
        var server = new FakeServer { Index = Strip(0, 20), HeightOf = _ => 1 };
        var stream = await Boot(server, Centre(5), 128);
        int rev = stream.Height.Revision, applied = 0, areas = 0, rebuilds = 0;
        stream.HeightApplied = ov => { applied++; Assert.Equal("h2", ov.Sig); return Task.CompletedTask; };
        stream.AreasRebuild = () => { areas++; return Task.CompletedTask; };
        stream.FieldChanged = () => { rebuilds++; return Task.CompletedTask; };
        server.HeightSig = "h2";
        server.HeightOf = _ => 6;
        Assert.True(await stream.SyncAsync("t1", "h2"));
        Assert.Equal(new[] { "height-index" }, server.Log);
        Assert.Equal((1, 1, rev + 1, 0), (applied, areas, stream.Height.Revision, stream.Height.Tiles.Count));
        Assert.Equal("h2", stream.LoadedHeightSig);
        await stream.SetAnchor(Centre(5), 128);
        Assert.Equal("tiles 5,0;4,0;6,0;3,0;7,0", server.Log[1]);
        Assert.Equal(6, stream.Height.GroundAt(Centre(5), 128));
        Assert.Equal(1, rebuilds);
        Assert.False(await stream.SyncAsync("t1", "h2"));
        Assert.Equal(1, stream.Counters.HeightReloads);
    }

    /// <summary>
    /// A new <c>terrain_sig</c>: the terrain reload is the host's; the areas rebuild after it. A failed reload (null)
    /// advances nothing, so the next poll with the same signature asks again; a successful one advances to the
    /// signature the host reports.
    /// </summary>
    [Fact]
    public async Task ANewTerrainSigReloadsUntilItSucceeds()
    {
        var server = new FakeServer { Index = Strip(0, 20) };
        var stream = await Boot(server, Centre(5), 128);
        int reloads = 0, areas = 0;
        bool fail = true;
        stream.TerrainReload = () => { reloads++; return Task.FromResult(fail ? null : "t2"); };
        stream.AreasRebuild = () => { areas++; return Task.CompletedTask; };
        Assert.False(await stream.SyncAsync("t2", "h1"));
        Assert.Equal(("t1", 1, 0), (stream.LoadedTerrainSig, reloads, areas));
        fail = false;
        Assert.True(await stream.SyncAsync("t2", "h1"));
        Assert.Equal(("t2", 2, 1), (stream.LoadedTerrainSig, reloads, areas));
        Assert.False(await stream.SyncAsync("t2", "h1"));
        Assert.Equal(2, reloads);
    }

    // ---- layer masks ----------------------------------------------------------------------------------------------

    /// <summary>
    /// Masks over a 21 × 21 index, anchor in the centre of tile 10,10 → the 25 tiles 8 … 12 × 8 … 12 (the class
    /// comment's per-axis rule; the four corners at 543 m are in). Order by d², ties ordinal:
    ///   0: 10,10 · 16 384: 10,11 10,9 11,10 9,10 · 32 768: 11,11 11,9 9,11 9,9 · 147 456: 10,12 10,8 12,10 8,10 ·
    ///   163 840: 11,12 11,8 12,11 12,9 8,11 8,9 9,12 9,8 · 294 912: 12,12 12,8 8,12 8,8.
    /// 16 per request → the first 16, then the other 9; one window per batch (16, then 25 tiles).
    /// Then one tile east (centre of 11,10): want 9 … 13 × 8 … 12 → missing column 13 in its own order: 13,10 (384²),
    /// 13,11 13,9 (384² + 128²; "13,11" &lt; "13,9"), 13,12 13,8 (2·384²) → one request; column 8 (5 tiles) leaves the
    /// window before it is repacked.
    /// </summary>
    [Fact]
    public async Task MaskTilesStreamSixteenPerBatchAndLeaveWithTheWantSet()
    {
        var server = new FakeServer { Index = Strip(0, 0), LayerIndex = Square(0, 20) };
        var stream = await Boot(server, Centre(10), Centre(10));
        using (var idx = await server.GetTerrainLayersAsync(Array.Empty<string>()))
            stream.SeedLayers(LayerCut.ParseIndex(idx.RootElement), Array.Empty<KeyValuePair<string, LayerTile>>());
        server.Log.Clear();
        var windows = new List<int>();
        stream.LayerWindowChanged = (tiles, fmt) => { windows.Add(tiles.Count); return Task.CompletedTask; };
        await stream.RefreshLayerTilesAsync();
        Assert.Equal(new[]
        {
            "masks 10,10;10,11;10,9;11,10;9,10;11,11;11,9;9,11;9,9;10,12;10,8;12,10;8,10;11,12;11,8;12,11",
            "masks 12,9;8,11;8,9;9,12;9,8;12,12;12,8;8,12;8,8",
        }, server.Log);
        Assert.Equal(new[] { 16, 25 }, windows);
        server.Log.Clear();
        await stream.SetAnchor(Centre(11), Centre(10));
        Assert.Equal(new[] { "masks 13,10;13,11;13,9;13,12;13,8" }, server.Log);
        Assert.Equal(new[] { 16, 25, 25 }, windows);
        Assert.Equal(5, stream.Counters.LayerTilesDropped);
        Assert.DoesNotContain(stream.LayerTiles, t => t.Key.StartsWith("8,", StringComparison.Ordinal));
        var win = LayerCut.Pack(stream.LayerTiles, stream.LayerFormat!)!;
        Assert.Equal((9 * 256.0, 8 * 256.0, 5 * 256), (win.OriginX, win.OriginZ, win.IdSize));
    }

    /// <summary>
    /// A mask batch answering under another cut (a room floor moved; <c>terrain_sig</c> did not): the batch is dropped,
    /// the index is refetched ONCE, and only an index that really names another cut is handed to the host. An index
    /// that still names the held cut is ignored.
    /// </summary>
    [Fact]
    public async Task AMaskBatchUnderAnotherCutReindexes()
    {
        var server = new FakeServer { Index = Strip(0, 0), LayerIndex = Square(0, 20) };
        var stream = await Boot(server, Centre(10), Centre(10));
        using (var idx = await server.GetTerrainLayersAsync(Array.Empty<string>()))
            stream.SeedLayers(LayerCut.ParseIndex(idx.RootElement), Array.Empty<KeyValuePair<string, LayerTile>>());
        var moved = new List<string>();
        stream.LayerIndexMoved = i => { moved.Add(i.Format.Sig); return Task.CompletedTask; };
        server.LayerBatchSig = "L2";
        server.Log.Clear();
        await stream.RefreshLayerTilesAsync();
        await stream.Reindex;
        Assert.Equal(2, server.Log.Count);
        Assert.Equal("mask-index", server.Log[1]);
        Assert.Empty(moved);                 // the index still says L1: nothing to take
        Assert.Empty(stream.LayerTiles);
        server.LayerIndexSig = "L2";
        await stream.RefreshLayerTilesAsync();
        await stream.Reindex;
        Assert.Equal(new[] { "L2" }, moved);
        Assert.Equal(1, stream.Counters.Reindexes);
    }

    // ---- helpers --------------------------------------------------------------------------------------------------

    /// <summary>Three requests while one build runs fold into ONE follow-up build; each caller's task completes.</summary>
    [Fact]
    public async Task RebuildRequestsCoalesce()
    {
        var gate = new TaskCompletionSource();
        int started = 0;
        var c = new Coalescer(async () => { started++; if (started == 1) await gate.Task; });
        var a = c.RequestAsync();
        var b = c.RequestAsync();
        var d = c.RequestAsync();
        var e = c.RequestAsync();
        Assert.True(c.Busy);
        Assert.Equal(1, started);
        gate.SetResult();
        await Task.WhenAll(a, b, d, e);
        Assert.Equal(2, c.Runs);
        Assert.False(c.Busy);
        await c.RequestAsync();
        Assert.Equal(3, c.Runs);
    }

    /// <summary>
    /// The probe: frames 5 (idle), 30 (streaming), 12 (the stream just ended — still counted, the upload lands here),
    /// 40 (idle) → 4 frames, max 40, streaming frames 2 (30 and 12), streaming max 30.
    /// </summary>
    [Fact]
    public void ProbeCountsTheFrameAfterTheStreamEnds()
    {
        var p = new StreamProbe();
        p.Frame(5, false);
        p.Frame(30, true);
        p.Frame(12, false);
        p.Frame(40, false);
        Assert.Equal((4, 40.0, 2, 30.0), (p.Frames, p.MaxMs, p.StreamFrames, p.StreamMaxMs));
    }
}
