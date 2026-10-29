using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 63 / E10-T2: fixture HTTP for the real world-build cache check. Indexes stay live;
/// scene ETags are content fingerprints. The fixture's old worldmap lacks terrain_sig, supplied here
/// from terrain.json as the live server does. All state belongs to one check invocation.</summary>
internal sealed class JsonCacheCheck(FixtureSource source)
{
    private readonly Dictionary<string, int> _requests = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> _bodies = new(StringComparer.Ordinal);
    public readonly List<string> TileKeys = new();
    public string? HeightSig;
    public string Epoch = "boot1";
    public string? ChangedScene;
    public bool NewerTileBatch;
    public int Scene304;
    public int Requests(string kind) => _requests.GetValueOrDefault(kind);
    public int Bodies(string kind) => _bodies.GetValueOrDefault(kind);

    /// <summary>Use production JSON and byte paths for the two builds; unrelated small fixture methods stay local.</summary>
    internal sealed class Source(AnimaApi api, IWorldSource other) : IWorldSource
    {
        public Task<JsonDocument> GetWorldMapAsync() => api.GetWorldMapAsync();
        public Task<JsonDocument> GetHeightfieldAsync() => api.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys) => api.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys) => api.GetHeightTileStatsAsync(keys);
        public Task<JsonDocument?> GetLocationSceneAsync(string id) => api.GetLocationSceneAsync(id);
        public Task<JsonDocument> GetTerrainAsync() => api.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys) => api.GetTerrainLayersAsync(keys);
        public Task<byte[]> GetBytesAsync(string url) => api.GetBytesAsync(url);
        public Task<JsonDocument> GetLocations3dAsync() => other.GetLocations3dAsync();
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => other.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync() => other.GetAnimationClipsAsync();
        public Task<JsonDocument> GetSurfaceTexturesAsync() => other.GetSurfaceTexturesAsync();
    }

    public async Task<HttpResponseMessage> AnswerAsync(HttpRequestMessage req)
    {
        string path = req.RequestUri!.AbsolutePath;
        string[]? keys = req.RequestUri.Query.Length == 0 ? null
            : Uri.UnescapeDataString(req.RequestUri.Query[6..]).Split(',').Select(k => k.Replace(':', ',')).ToArray();
        var pairs = keys?.Select(k => { var p = k.Split(','); return (int.Parse(p[0]), int.Parse(p[1])); }).ToArray();
        string kind;
        JsonDocument? doc;
        switch (path)
        {
            case "/play/worldmap":
                kind = "map";
                using (var map = await source.GetWorldMapAsync())
                using (var terrain = await source.GetTerrainAsync())
                    doc = Rewrite(map.RootElement, new Dictionary<string, object>
                    {
                        ["height_sig"] = HeightSig ?? map.RootElement.GetProperty("height_sig").GetString()!,
                        ["terrain_sig"] = terrain.RootElement.GetProperty("sig").GetString()!, ["locations_rev"] = Epoch,
                    });
                break;
            case "/play/heightfield": kind = "height-index"; doc = await source.GetHeightfieldAsync(); break;
            case "/play/heightfield/tiles":
                kind = "tiles"; TileKeys.AddRange(keys!); doc = await source.GetHeightTilesAsync(pairs!); break;
            case "/play/heightfield/stats": kind = "stats"; doc = await source.GetHeightTileStatsAsync(pairs!); break;
            case "/play/terrain-layers": kind = keys is null ? "layer-index" : "masks";
                doc = await source.GetTerrainLayersAsync(keys ?? Array.Empty<string>()); break;
            case "/play/terrain": kind = "terrain"; doc = await source.GetTerrainAsync(); break;
            default:
                if (!path.StartsWith("/play/locations/", StringComparison.Ordinal) || !path.EndsWith("/scene", StringComparison.Ordinal))
                    return new(HttpStatusCode.NotFound);
                kind = "scenes";
                doc = await source.GetLocationSceneAsync(Uri.UnescapeDataString(path.Split('/')[3]));
                if (doc is not null && path == ChangedScene)
                { var previous = doc; using (previous) doc = Rewrite(previous.RootElement, new() { ["cache_probe"] = "changed scene" }); }
                break;
        }
        _requests[kind] = Requests(kind) + 1;
        if (doc is null) return new(HttpStatusCode.NotFound);
        using (doc)
        {
            if (HeightSig is not null && (kind is "height-index" or "tiles" or "stats"))
            { using var changed = Rewrite(doc.RootElement, new() { ["sig"] = HeightSig }); return Reply(changed.RootElement); }
            if (NewerTileBatch && kind == "tiles")
            { using var newer = Rewrite(doc.RootElement, new() { ["sig"] = "newer-than-overview" }); return Reply(newer.RootElement); }
            return Reply(doc.RootElement);
        }
        HttpResponseMessage Reply(JsonElement root)
        {
            byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(root);
            string etag = "\"" + Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() + "\"";
            bool same = kind == "scenes" && req.Headers.IfNoneMatch.Any(e => e.ToString() == etag);
            var res = new HttpResponseMessage(same ? HttpStatusCode.NotModified : HttpStatusCode.OK);
            if (kind == "scenes") res.Headers.TryAddWithoutValidation("ETag", etag);
            res.Headers.TryAddWithoutValidation("Cache-Control", "no-cache");
            if (same) Scene304++;
            else { _bodies[kind] = Bodies(kind) + 1; res.Content = new ByteArrayContent(bytes); }
            return res;
        }
    }

    private static JsonDocument Rewrite(JsonElement root, Dictionary<string, object> overrides)
    {
        var properties = root.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value);
        foreach (var (key, value) in overrides) properties[key] = value;
        return JsonDocument.Parse(JsonSerializer.SerializeToUtf8Bytes(properties));
    }

    /// <summary>Task 63 acceptance after the two actual builds: statistics warm reuse, a height-only change,
    /// one changed scene, and a newer-than-index tile response in its own empty cache.</summary>
    public async Task ProveChanges(string root, Uri origin, HttpMessageHandler transport, Action<bool, string> expect)
    {
        using var overview = await source.GetHeightfieldAsync();
        var pairs = overview.RootElement.GetProperty("tiles").EnumerateArray().Select(k =>
        { var p = k.GetString()!.Split(','); return (int.Parse(p[0]), int.Parse(p[1])); }).ToArray();
        using (var api = new AnimaApi(origin.ToString(), transport, new DiskCache(root, origin)))
        {
            using var index = await api.GetHeightfieldAsync();
            using var first = await api.GetHeightTileStatsAsync(pairs);
        }
        int stats = Requests("stats"), tiles = Requests("tiles"), masks = Requests("masks"), terrainRequests = Requests("terrain");
        using (var api = new AnimaApi(origin.ToString(), transport, new DiskCache(root, origin)))
        {
            using var index = await api.GetHeightfieldAsync();
            using var warm = await api.GetHeightTileStatsAsync(pairs.Reverse().ToArray());
            expect(Requests("stats") == stats, "restart statistics uses per-tile signature keys");
        }
        HeightSig = "fixture-height-changed";
        TileKeys.Clear();
        using (var api = new AnimaApi(origin.ToString(), transport, new DiskCache(root, origin)))
        {
            using var map = await api.GetWorldMapAsync();
            using var index = await api.GetHeightfieldAsync();
            using var layerIndex = await api.GetTerrainLayersAsync(Array.Empty<string>());
            using var newTiles = await api.GetHeightTilesAsync(pairs);
            using var newStats = await api.GetHeightTileStatsAsync(pairs);
            using var warmTerrain = await api.GetTerrainAsync();
            var wantedMasks = layerIndex.RootElement.GetProperty("tile_keys").EnumerateArray().Select(k => k.GetString()!).ToArray();
            foreach (var batch in wantedMasks.Chunk(AnimaNative.Ground.LayerCut.BatchMax))
            {
                // Only the masks actually requested by the world build are warm (far-away index keys stay cold).
                var built = batch.Where(k => source.LayerRequests.Any(r => r.Split(';').Contains(k))).ToArray();
                if (built.Length > 0) { using var warmMasks = await api.GetTerrainLayersAsync(built); }
            }
            expect(Requests("tiles") == tiles + 1 && TileKeys.SequenceEqual(pairs.Select(k => $"{k.Item1},{k.Item2}")),
                "changed height_sig fetches exactly the requested tiles");
            expect(Requests("stats") == stats + 1, "changed height_sig refetches height statistics");
            expect(Requests("masks") == masks && Requests("terrain") == terrainRequests,
                "height-only change preserves mask and terrain cache");
            var scenes = source.SceneRequests.Distinct().Where(id => File.Exists(Path.Combine(source.Dir, "scene_" + id + ".json"))).ToArray();
            ChangedScene = "/play/locations/" + scenes[0] + "/scene";
            int sceneBodies = Bodies("scenes"), conditional = Scene304;
            foreach (var id in scenes) { using var scene = await api.GetLocationSceneAsync(id); }
            expect(Bodies("scenes") == sceneBodies + 1 && Scene304 == conditional + scenes.Length - 1,
                "changed fingerprint fetches exactly one scene; others return 304");
        }
        int changedTiles = TileKeys.Count;
        HeightSig = null;
        NewerTileBatch = true;
        var guard = new DiskCache(Path.Combine(root, "guard"), origin);
        using (var api = new AnimaApi(origin.ToString(), transport, guard))
        {
            using var index = await api.GetHeightfieldAsync();
            using var newer = await api.GetHeightTilesAsync(pairs);
            expect(newer.RootElement.GetProperty("sig").GetString() == "newer-than-overview", "mismatch remains available in memory");
            expect(guard.Count == 0 && guard.Bytes == 0, "newer-than-sig guard stores nothing");
        }
        GD.Print($"cache JSON changes: height tiles={changedTiles} stats=1 masks=0 terrain=0 scene=1 guard entries={guard.Count}");
    }
}
