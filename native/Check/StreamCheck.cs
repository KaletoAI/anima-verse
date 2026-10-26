using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Terrain;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check stream</c> (part of every <c>--check</c>, Task 24): the terrain streaming of the real client — the
/// <see cref="TerrainStreamer"/> on a world built by <see cref="WorldBuilder"/> — against a fake server that answers
/// height, statistics and mask batches for a strip of ten tiles. Every number is derived BY HAND in
/// native/fixtures/README.md "Terrain streaming"; the policy itself (<see cref="TerrainStream"/>) is unit-tested in
/// <c>dotnet test</c> (TerrainStreamTests). This checks the wiring:
///
///   S0 the boot ring and the masks the build fetched; S1 the statistics fill of the capped overview and the level
///   errors it moves; the poll's world frame; S2/S3 two camera-target moves along the strip: the batches in order, the
///   LRU (cap 4 here) and what it evicts, the near window, the fine height under the target, the mask window repacked
///   with the want-set filter, the height revision; S4 a new <c>height_sig</c>: the relief reloaded, the far pyramid
///   rebuilt, the ring refetched, the statistics refilled, and every location re-datumed (the Task 17 hook, live); S5 a
///   new <c>terrain_sig</c>: a new ground on the terrain; S6 a mask batch under another cut: the re-index; the probe.
/// </summary>
public static class StreamCheck
{
    private const int Strip = 10;

    /// <summary>The fixture world, with the relief and the masks of a ten-tile strip answered by hand-made batches.</summary>
    private sealed class StreamSource : IWorldSource
    {
        private readonly FixtureSource _f;
        private readonly JsonObject _layerIndex;
        public double Lift;
        public string HeightSig = "s1", TerrainSig = "t1", LayerCut = "L1";
        public readonly List<string> Log = new();

        public StreamSource(FixtureSource f, string fixtures)
        {
            _f = f;
            _layerIndex = JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures, "terrain_layers.json")))!.AsObject();
        }

        private static IEnumerable<string> Keys => Enumerable.Range(0, Strip).Select(k => $"{k},0");

        public Task<JsonDocument> GetHeightfieldAsync()
        {
            Log.Add("height-index");
            var row = new JsonArray(Enumerable.Repeat(0, 12).Select(_ => (JsonNode)JsonValue.Create(Lift)!).ToArray());
            var o = new JsonObject
            {
                ["origin_x"] = -256, ["origin_z"] = -256, ["step_m"] = 256, ["rows"] = 4, ["cols"] = 12,
                ["heights"] = new JsonArray(Enumerable.Range(0, 4).Select(_ => (JsonNode)row.DeepClone()).ToArray()),
                ["sig"] = HeightSig, ["tile_m"] = 256, ["tile_step_m"] = 2,
                ["tiles"] = new JsonArray(Keys.Select(k => (JsonNode)JsonValue.Create(k)!).ToArray()),
                ["mip_levels_m"] = new JsonArray(4, 8, 16, 32, 64),
                ["tile_stats"] = new JsonObject(), ["tile_stats_complete"] = false,
            };
            return Task.FromResult(JsonDocument.Parse(o.ToJsonString()));
        }

        private JsonObject StatOf(int k)
        {
            double h = k + Lift;
            return new JsonObject
            {
                ["min"] = h, ["max"] = h,
                ["err"] = k == 9 ? new JsonArray(0.5, 1, 2, 4, 8) : new JsonArray(0, 0, 0, 0, 0),
            };
        }

        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys)
        {
            Log.Add("tiles " + string.Join(";", keys.Select(k => $"{k.Tx},{k.Tz}")));
            var tiles = new JsonObject();
            foreach (var (tx, tz) in keys.Where(k => k.Tz == 0 && k.Tx is >= 0 and < Strip))
            {
                double h = tx + Lift;
                tiles[$"{tx},{tz}"] = new JsonObject
                {
                    ["origin_x"] = tx * 256, ["origin_z"] = 0, ["rows"] = 2, ["cols"] = 2,
                    ["heights"] = new JsonArray(new JsonArray(h, h), new JsonArray(h, h)), ["stats"] = StatOf(tx),
                };
            }
            var o = new JsonObject { ["sig"] = HeightSig, ["tile_m"] = 256, ["step_m"] = 2, ["tiles"] = tiles };
            return Task.FromResult(JsonDocument.Parse(o.ToJsonString()));
        }

        public Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys)
        {
            Log.Add("stats " + string.Join(";", keys.Select(k => $"{k.Tx},{k.Tz}")));
            var stats = new JsonObject();
            foreach (var (tx, tz) in keys.Where(k => k.Tz == 0 && k.Tx is >= 0 and < Strip)) stats[$"{tx},{tz}"] = StatOf(tx);
            return Task.FromResult(JsonDocument.Parse(new JsonObject { ["sig"] = HeightSig, ["tile_stats"] = stats }.ToJsonString()));
        }

        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys)
        {
            Log.Add(keys.Count == 0 ? "mask-index" : "masks " + string.Join(";", keys));
            var o = (JsonObject)_layerIndex.DeepClone();
            o["sig"] = LayerCut;
            o["tile_m"] = 256;
            if (keys.Count == 0) o["tile_keys"] = new JsonArray(Keys.Select(k => (JsonNode)JsonValue.Create(k)!).ToArray());
            else
            {
                o.Remove("tile_keys");
                o.Remove("overview");
                var tiles = new JsonObject();
                foreach (var k in keys.Where(Keys.Contains))
                    tiles[k] = new JsonObject { ["origin_x"] = int.Parse(k.Split(',')[0]) * 256, ["origin_z"] = 0, ["uniform"] = 1 };
                o["tiles"] = tiles;
            }
            return Task.FromResult(JsonDocument.Parse(o.ToJsonString()));
        }

        public async Task<JsonDocument> GetTerrainAsync()
        {
            Log.Add("terrain");
            using var doc = await _f.GetTerrainAsync();
            var o = JsonNode.Parse(doc.RootElement.GetRawText())!.AsObject();
            o["sig"] = TerrainSig;
            return JsonDocument.Parse(o.ToJsonString());
        }

        public Task<JsonDocument> GetWorldMapAsync() => _f.GetWorldMapAsync();
        public Task<JsonDocument> GetLocations3dAsync() => _f.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string locationId) => _f.GetLocationSceneAsync(locationId);
        public Task<byte[]> GetBytesAsync(string url) => _f.GetBytesAsync(url);
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => _f.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync() => _f.GetAnimationClipsAsync();
        public Task<JsonDocument> GetSurfaceTexturesAsync() => _f.GetSurfaceTexturesAsync();
    }

    /// <summary>A worldmap poll answer: the signatures and a frame reaching over the strip.</summary>
    private static JsonElement Map(string terrainSig, string heightSig)
        => JsonDocument.Parse(new JsonObject
        {
            ["terrain_sig"] = terrainSig, ["height_sig"] = heightSig,
            ["world_bounds"] = new JsonObject { ["min_x"] = -104, ["min_z"] = -203, ["max_x"] = 2600, ["max_z"] = 134 },
        }.ToJsonString()).RootElement.Clone();

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var src = new StreamSource(new FixtureSource(fixtures), fixtures);
        var world = new Node3D { Name = "StreamWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(src, line => GD.Print("[check-stream] " + line), strict: true);
        try
        {
            var stats = await builder.BuildAsync(world, "harbour");
            var height = builder.Height!;
            var term = builder.Terrain!;
            term.AutoUpdate = false;

            // S0 the boot ring round the anchor (64, 128): tiles 0 (d 0), 1 (192), 2 (448); 3 is at 704.
            Expect("S0 anchor", stats.Anchor.X == 64 && stats.Anchor.Z == 128, $"{stats.Anchor.Position()}");
            Expect("S0 boot tiles", src.Log.Contains("tiles 0,0;1,0;2,0") && height.Tiles.Count == 3, string.Join(" | ", src.Log));
            Expect("S0 boot masks", src.Log.Contains("masks 0,0;1,0;2,0"), string.Join(" | ", src.Log));
            Expect("S0 boot revision 1", height.Revision == 1, $"{height.Revision}");
            src.Log.Clear();

            var anchor = new Vector3(64, 0, 128);
            var st = new TerrainStreamer(builder, src, () => anchor, line => GD.Print("[check-stream] " + line),
                                         "s1", "t1", stats.Anchor.X, stats.Anchor.Z, water: true, cacheMax: 4);
            st.AnchorFollows = false;
            world.AddChild(st);
            await st.SettleAsync(30, 0.3);

            // S1 the fill: 10 indexed, 3 known → "stats 3,0;…;9,0"; tile 9's err → levels 1…5 = 0.5, 1, 2, 4, 8.
            Expect("S1 one stats request", src.Log.SequenceEqual(new[] { "stats 3,0;4,0;5,0;6,0;7,0;8,0;9,0" }), string.Join(" | ", src.Log));
            Expect("S1 all statistics", height.Stats.Count == Strip, $"{height.Stats.Count}");
            Expect("S1 level errors", term.Field.LevelErrorM.SequenceEqual(new[] { 0, 0.5, 1, 2, 4, 8 }), string.Join(",", term.Field.LevelErrorM));
            Expect("S1 the boot field", term.Field.NearRect!.SequenceEqual(new double[] { -512, -512, 1280, 768 }), string.Join(",", term.Field.NearRect!));
            // The poll with unchanged signatures: no reload; the frame becomes world_bounds ± 60.
            Expect("S1 idle poll", !await st.Sync(Map("t1", "s1")), "");
            Expect("S1 frame", term.Field.Extent.SequenceEqual(new double[] { -164, -263, 2660, 194 }), string.Join(",", term.Field.Extent));
            src.Log.Clear();

            // S2 the target to (1000, 128): want 3 (0), 4 (24), 2 (232), 5 (280), 1 (488), 6 (536) → missing 3, 4, 5, 6.
            anchor = new Vector3(1000, 0, 128);
            await st.Stream.SetAnchor(1000, 128);
            await st.SettleAsync(30, 0.3);
            Expect("S2 requests", src.Log.SequenceEqual(new[] { "tiles 3,0;4,0;5,0;6,0", "masks 3,0;4,0;5,0;6,0" }), string.Join(" | ", src.Log));
            Expect("S2 LRU 4: 0,0 evicted, the six wanted stay", Held(height) == "1,2,3,4,5,6" && st.Stream.Counters.TilesEvicted == 1,
                   $"{Held(height)} evicted {st.Stream.Counters.TilesEvicted}");
            Expect("S2 near window", term.Field.NearRect!.SequenceEqual(new double[] { -26, -514, 2022, 766 }), string.Join(",", term.Field.NearRect!));
            Expect("S2 fine ground under the target", height.GroundAt(1000, 128) == 3, $"{height.GroundAt(1000, 128)}");
            Expect("S2 revision 2, one build", height.Revision == 2 && st.FieldBuilds == 1, $"{height.Revision} / {st.FieldBuilds}");
            var win = builder.Ground!.Window!;
            Expect("S2 mask window 1 … 6", win.OriginX == 256 && win.OriginZ == 0 && win.IdSize == 1536 && Masks(st) == "1,2,3,4,5,6",
                   $"({win.OriginX}, {win.OriginZ}) {win.IdSize} [{Masks(st)}]");
            Expect("S2 the field kept the frame", term.Field.Extent.SequenceEqual(new double[] { -164, -263, 2660, 194 }), string.Join(",", term.Field.Extent));
            src.Log.Clear();

            // S3 the target to (2000, 128): want 7 (0), 8 (48), 6 (208), 9 (304), 5 (464) → missing 7, 8, 9.
            anchor = new Vector3(2000, 0, 128);
            await st.Stream.SetAnchor(2000, 128);
            await st.SettleAsync(30, 0.3);
            Expect("S3 requests", src.Log.SequenceEqual(new[] { "tiles 7,0;8,0;9,0", "masks 7,0;8,0;9,0" }), string.Join(" | ", src.Log));
            Expect("S3 LRU: 2, 1, 3, 4 evicted", Held(height) == "5,6,7,8,9" && st.Stream.Counters.TilesEvicted == 5,
                   $"{Held(height)} evicted {st.Stream.Counters.TilesEvicted}");
            Expect("S3 near window", term.Field.NearRect!.SequenceEqual(new double[] { 974, -514, 3022, 766 }), string.Join(",", term.Field.NearRect!));
            Expect("S3 fine ground", height.GroundAt(2000, 128) == 7 && height.Revision == 3, $"{height.GroundAt(2000, 128)} rev {height.Revision}");
            win = builder.Ground!.Window!;
            Expect("S3 mask window 5 … 9", win.OriginX == 1280 && win.IdSize == 1280 && Masks(st) == "5,6,7,8,9"
                   && st.Stream.Counters.LayerTilesDropped == 5, $"({win.OriginX}) {win.IdSize} [{Masks(st)}] dropped {st.Stream.Counters.LayerTilesDropped}");
            src.Log.Clear();

            // S4 a new height_sig: every height 5 m higher.
            var house = builder.Slots["loc-house"];
            var yard = builder.Slots["loc-yard"];
            float houseY = house.Group.Position.Y, yardY = yard.Group.Position.Y;
            src.Lift = 5;
            src.HeightSig = "s2";
            Expect("S4 reload ran", await st.Sync(Map("t1", "s2")), "");
            Expect("S4 relief reset", height.Tiles.Count == 0 && height.Revision == 4 && st.Stream.LoadedHeightSig == "s2"
                   && term.Field.Near is null && term.Field.Far!.Data[0] == 5, $"tiles {height.Tiles.Count} rev {height.Revision}");
            await st.Stream.SetAnchor(2000, 128);
            await st.SettleAsync(30, 0.3);
            Expect("S4 requests", src.Log.SequenceEqual(new[] { "height-index", "tiles 7,0;8,0;6,0;9,0;5,0", "stats 0,0;1,0;2,0;3,0;4,0" }),
                   string.Join(" | ", src.Log));
            Expect("S4 the new fine ground", height.GroundAt(2000, 128) == 12 && height.Revision == 5, $"{height.GroundAt(2000, 128)} rev {height.Revision}");
            var tick = builder.TickModels(new Vector3(64, 30, 168));
            Expect("S4 house and yard re-datumed by +5", tick.Redatumed == 2 && Math.Abs(house.Group.Position.Y - (houseY + 5)) < 1e-5
                   && Math.Abs(yard.Group.Position.Y - (yardY + 5)) < 1e-5,
                   $"redatumed {tick.Redatumed}, house {houseY} → {house.Group.Position.Y}, yard {yardY} → {yard.Group.Position.Y}");
            int redatumed = tick.Redatumed;
            src.Log.Clear();

            // S5 a new terrain_sig: a new ground for the target (masks 7, 8, 6, 9, 5 in want order).
            var oldGround = builder.Ground;
            src.TerrainSig = "t2";
            Expect("S5 reload ran", await st.Sync(Map("t2", "s2")), "");
            Expect("S5 requests", src.Log.SequenceEqual(new[] { "terrain", "mask-index", "masks 7,0;8,0;6,0;9,0;5,0" }), string.Join(" | ", src.Log));
            Expect("S5 a new ground on the terrain", builder.Ground != oldGround && term.Materials.Dry == builder.Ground!.Material
                   && st.Stream.LoadedTerrainSig == "t2", st.Stream.LoadedTerrainSig ?? "null");
            src.Log.Clear();
            Expect("S5 the same poll again", !await st.Sync(Map("t2", "s2")) && !src.Log.Contains("terrain"), string.Join(" | ", src.Log));
            await st.SettleAsync(30, 0.3);
            src.Log.Clear();

            // S6 back to (1000, 128) while the masks were re-cut (L2): the batch is dropped, the index re-taken.
            src.LayerCut = "L2";
            anchor = new Vector3(1000, 0, 128);
            await st.Stream.SetAnchor(1000, 128);
            await st.Stream.Reindex;
            await st.SettleAsync(30, 0.3);
            Expect("S6 requests", src.Log.SequenceEqual(new[]
                   {
                       "tiles 3,0;4,0;2,0;1,0", "masks 3,0;4,0;2,0;1,0", "mask-index", "terrain", "masks 3,0;4,0;2,0;5,0;1,0;6,0",
                   }), string.Join(" | ", src.Log));
            Expect("S6 re-indexed", builder.Ground!.Format.Sig == "L2" && st.Stream.LayerSig == "L2" && st.Stream.Counters.Reindexes == 1
                   && Masks(st) == "1,2,3,4,5,6", $"{builder.Ground.Format.Sig} [{Masks(st)}]");
            Expect("S6 LRU: 7, 8, 9 evicted", Held(height) == "1,2,3,4,5,6" && st.Stream.Counters.TilesEvicted == 8,
                   $"{Held(height)} evicted {st.Stream.Counters.TilesEvicted}");
            Expect("S6 near window", term.Field.NearRect!.SequenceEqual(new double[] { -26, -514, 2022, 766 }), string.Join(",", term.Field.NearRect!));
            Expect("probe saw the streaming", st.Session.StreamFrames > 0, st.Session.Summary());
            return $"stream[fill 7, S2 4/4 evicted 1, S3 3/3 evicted 4, height reload + redatum {redatumed}, ground reload, re-index; "
                   + $"{st.FieldBuilds} builds, {st.MaskWindows} mask windows]";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static string Held(WorldHeight h) => string.Join(",", h.Tiles.Select(t => t.Key.Tx).OrderBy(x => x));

    private static string Masks(TerrainStreamer st)
        => string.Join(",", st.Stream.LayerTiles.Select(t => int.Parse(t.Key.Split(',')[0])).OrderBy(x => x));

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"stream {what}: {detail}");
    }
}
