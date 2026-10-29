using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.World;

namespace AnimaNative.Check;

/// <summary>
/// The offline <see cref="IWorldSource"/> of <c>--check</c>: answers from the
/// files in <c>native/fixtures/</c> exactly as the server would —
///   heightfield.json  → GET /play/heightfield
///   tiles.json        → GET /play/heightfield/tiles (only the requested keys)
///   worldmap.json     → GET /play/worldmap (location rows with placement)
///   locations.json    → GET /world/locations?view=3d (no positions)
///   scene_&lt;id&gt;.json   → GET /play/locations/&lt;id&gt;/scene (missing file = 404 = null)
///   urls.json         → payload URL → file: a name in fixtures/, or
///                       <c>repo:&lt;path&gt;</c> = a file of the repository read
///                       in place (clips, a character GLB — nothing copied)
///   model3d.json      → GET /characters/&lt;name&gt;/model3d (name → answer;
///                       null or absent = 404)
///   animation_clips.json → GET /assets/animation-clips
///   terrain.json      → GET /play/terrain (one painted wood with two scatter rows + a path over it)
///   terrain_layers.json        → GET /play/terrain-layers (the index)
///   terrain_layers_tiles.json  → GET /play/terrain-layers?keys=… (only the requested AND indexed keys,
///                                the format block and the table — like the server's batch_payload)
///   surface_textures.json      → GET /assets/surface-textures
///   explored.json              → GET /play/explored (absent = 404)
///   (tiles.json's per-tile <c>stats</c>) → GET /play/heightfield/stats (only the requested AND indexed keys)
/// </summary>
public sealed partial class FixtureSource : IWorldSource
{
    private readonly string _dir;
    /// <summary>Where a file this directory does not hold is read from (the S3c world borrows the ground files).</summary>
    private readonly string? _fallback;
    private readonly Dictionary<string, string> _urls;
    /// <summary>The two large merged files, parsed once (a real dump holds ~30 / ~200 MB of them).</summary>
    private readonly Dictionary<string, JsonDocument> _big = new();

    public string Dir => _dir;

    public List<string> TileRequests { get; } = new();
    /// <summary>Every <c>/play/heightfield/stats</c> call: the keys joined by ';'.</summary>
    public List<string> StatsRequests { get; } = new();

    /// <summary>
    /// Answer the large requests (tiles, stats, masks) on the thread pool, as a server answers off the client's thread —
    /// <c>--offline</c> sets it, so the streaming probe measures the client and not the fixture's own JSON work. The
    /// <c>--check</c> runs keep the synchronous answers.
    /// </summary>
    public bool OffThread { get; init; }

    private Task<T> Serve<T>(Func<T> answer) => OffThread ? Task.Run(answer) : Task.FromResult(answer());
    /// <summary>Every <c>/play/locations/{id}/scene</c> asked for.</summary>
    public List<string> SceneRequests { get; } = new();
    public List<string> ByteRequests { get; } = new();
    public List<string> ModelRequests { get; } = new();
    /// <summary>Every <c>/play/terrain-layers</c> call: "" for the index, else the keys joined by ';'.</summary>
    public List<string> LayerRequests { get; } = new();

    public FixtureSource(string dir, string? fallback = null)
    {
        _dir = dir;
        _fallback = fallback;
        _urls = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(Path.Combine(dir, "urls.json")))
                ?? new Dictionary<string, string>();
    }

    private Task<JsonDocument> Doc(string file) => Task.FromResult(JsonDocument.Parse(File.ReadAllBytes(PathOf(file))));

    /// <summary>The file in this directory, else in the fallback directory.</summary>
    private string PathOf(string file)
    {
        var own = Path.Combine(_dir, file);
        return File.Exists(own) || _fallback is null ? own : Path.Combine(_fallback, file);
    }

    /// <summary>Task 42: fixed Task 41 receipts, including poll 2; no wall-clock or model-load time in a check.</summary>
    public Task<JsonDocument> GetWorldMapAsync() => _propSteps.ValueKind == JsonValueKind.Array
        ? Task.FromResult(PropStep("GET", "/play/worldmap")) : GetWorldMapFileAsync("worldmap.json");
    public async Task<JsonDocument> GetWorldMapFileAsync(string file)
    {
        var doc = await Doc(file);
        _receipt = null;
        var path = PathOf("receipts.json");
        if (!File.Exists(path)) path = Path.Combine(_dir, "travel", "receipts.json");
        if (File.Exists(path))
        {
            using var stamps = JsonDocument.Parse(File.ReadAllBytes(path));
            if (stamps.RootElement.TryGetProperty(file, out var m))
                _receipt = new MapReceipt(Json.Num(m, "polledAt"), Json.Num(m, "headersAt"), Json.Num(m, "parsedAt"));
        }
        if (_receipt is not { } receipt) return doc;
        using (doc) return receipt.Attach(doc.RootElement);
    }
    private MapReceipt? _receipt;
    public MapReceipt? ReceiptOf(JsonElement root) => MapReceipt.FromMap(root);
    public double MonotonicMs => _receipt?.ParsedAt ?? 0;
    public Task<JsonDocument> GetHeightfieldAsync() => Doc("heightfield.json");
    public Task<JsonDocument> GetLocations3dAsync() => Doc("locations.json");

    public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys)
    {
        if (keys.Count == 0 || keys.Count > AnimaApi.HeightTileBatchMax)
            throw new ArgumentOutOfRangeException(nameof(keys));
        var wanted = keys.Select(k => $"{k.Tx},{k.Tz}").ToHashSet();
        lock (TileRequests) TileRequests.AddRange(wanted);
        return Serve(() => TilesAnswer(wanted));
    }

    private JsonDocument TilesAnswer(HashSet<string> wanted)
    {
        var root = Big("tiles.json").RootElement;
        var tiles = new Dictionary<string, JsonElement>();
        foreach (var p in root.GetProperty("tiles").EnumerateObject())
            if (wanted.Contains(p.Name)) tiles[p.Name] = p.Value;
        var answer = new Dictionary<string, object>
        {
            ["sig"] = root.GetProperty("sig").GetString() ?? "",
            ["tile_m"] = root.GetProperty("tile_m").GetDouble(),
            ["step_m"] = root.GetProperty("step_m").GetDouble(),
            ["tiles"] = tiles,
        };
        return JsonDocument.Parse(JsonSerializer.Serialize(answer));
    }

    /// <summary>The statistics of the requested indexed tiles, read off tiles.json (the same arithmetic the server caches).</summary>
    public Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys)
    {
        if (keys.Count == 0 || keys.Count > AnimaApi.HeightTileBatchMax)
            throw new ArgumentOutOfRangeException(nameof(keys));
        var wanted = keys.Select(k => $"{k.Tx},{k.Tz}").ToList();
        lock (StatsRequests) StatsRequests.Add(string.Join(";", wanted));
        return Serve(() =>
        {
            var root = Big("tiles.json").RootElement;
            var stats = new Dictionary<string, JsonElement>();
            foreach (var k in wanted)
                if (root.GetProperty("tiles").TryGetProperty(k, out var t) && t.TryGetProperty("stats", out var st)) stats[k] = st;
            var answer = new Dictionary<string, object> { ["sig"] = root.GetProperty("sig").GetString() ?? "", ["tile_stats"] = stats };
            return JsonDocument.Parse(JsonSerializer.Serialize(answer));
        });
    }

    /// <summary>A check's stand-in for a changed server scene: location id → the file answered from now on.</summary>
    public Dictionary<string, string> SceneFiles { get; } = new();

    public Task<JsonDocument?> GetLocationSceneAsync(string locationId)
    {
        SceneRequests.Add(locationId);
        var path = Path.Combine(_dir, SceneFiles.TryGetValue(locationId, out var file) ? file : $"scene_{locationId}.json");
        return Task.FromResult(File.Exists(path) ? JsonDocument.Parse(File.ReadAllBytes(path)) : null);
    }

    public Task<byte[]> GetBytesAsync(string url)
    {
        ByteRequests.Add(url);
        if (!_urls.TryGetValue(url, out var file))
            throw new ApiException(404, url.Split('?')[0], "no fixture for this URL");
        return Task.FromResult(File.ReadAllBytes(Resolve(file)));
    }

    /// <summary>A check's replacement model3d answer per character (raw JSON; "null" = no model), before model3d.json.</summary>
    public Dictionary<string, string> ModelAnswers { get; } = new();

    public Task<JsonDocument?> GetCharacterModelAsync(string name)
    {
        ModelRequests.Add(name);
        if (ModelAnswers.TryGetValue(name, out var raw))
            return Task.FromResult(raw == "null" ? null : (JsonDocument?)JsonDocument.Parse(raw));
        using var all = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(_dir, "model3d.json")));
        if (!all.RootElement.TryGetProperty(name, out var answer) || answer.ValueKind == JsonValueKind.Null)
            return Task.FromResult<JsonDocument?>(null);
        return Task.FromResult<JsonDocument?>(JsonDocument.Parse(answer.GetRawText()));
    }

    public Task<JsonDocument> GetAnimationClipsAsync() => Doc("animation_clips.json");

    public Task<JsonDocument> GetTerrainAsync() => Doc("terrain.json");

    public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys)
    {
        lock (LayerRequests) LayerRequests.Add(string.Join(";", keys));
        if (keys.Count == 0) return Doc("terrain_layers.json");
        if (keys.Count > Ground.LayerCut.BatchMax) throw new ArgumentOutOfRangeException(nameof(keys));
        var asked = keys.ToList();
        return Serve(() => LayersAnswer(asked));
    }

    private JsonDocument LayersAnswer(IReadOnlyList<string> keys)
    {
        using var index = JsonDocument.Parse(File.ReadAllBytes(PathOf("terrain_layers.json")));
        var indexed = index.RootElement.GetProperty("tile_keys").EnumerateArray().Select(k => k.GetString()).ToHashSet();
        var root = Big("terrain_layers_tiles.json").RootElement;
        var answer = new Dictionary<string, object>();
        foreach (var p in root.EnumerateObject())
            if (p.Name != "tiles") answer[p.Name] = p.Value;
        var tiles = new Dictionary<string, JsonElement>();
        foreach (var k in keys)
            if (indexed.Contains(k) && root.GetProperty("tiles").TryGetProperty(k, out var t)) tiles[k] = t;
        answer["tiles"] = tiles;
        return JsonDocument.Parse(JsonSerializer.Serialize(answer));
    }

    public Task<JsonDocument> GetSurfaceTexturesAsync() => Doc("surface_textures.json");

    /// <summary>Every <c>/play/explored</c> call.</summary>
    public int ExploredRequests { get; private set; }

    /// <summary><c>explored.json</c> → GET /play/explored; no file = 404 (a dump made before the veil).</summary>
    public Task<JsonDocument> GetExploredAsync()
    {
        ExploredRequests++;
        return File.Exists(PathOf("explored.json"))
            ? Doc("explored.json")
            : Task.FromException<JsonDocument>(new ApiException(404, "/play/explored", "no explored.json in " + _dir));
    }

    private JsonDocument Big(string file)
    {
        lock (_big)
        {
            if (!_big.TryGetValue(file, out var doc))
                _big[file] = doc = JsonDocument.Parse(File.ReadAllBytes(PathOf(file)),
                                                      new JsonDocumentOptions { MaxDepth = 256 });
            return doc;
        }
    }

    /// <summary>
    /// A fixture file, or with <c>repo:</c> a repository file: the repository
    /// root is the first directory above the fixtures (then above the working
    /// directory or the shell's <c>PWD</c> — for the exported binary started
    /// from inside the repo) that holds the path.
    /// </summary>
    public string Resolve(string file)
    {
        const string repo = "repo:";
        if (!file.StartsWith(repo, StringComparison.Ordinal)) return Path.Combine(_dir, file);
        var rel = file[repo.Length..];
        // An exported Godot binary runs with its own directory as the working
        // directory, so the shell's directory comes from PWD as well.
        var starts = new[] { _dir, Directory.GetCurrentDirectory(), System.Environment.GetEnvironmentVariable("PWD") ?? "" };
        foreach (var start in starts.Where(p => p.Length > 0))
            for (var d = new DirectoryInfo(Path.GetFullPath(start)); d is not null; d = d.Parent)
            {
                var candidate = Path.Combine(d.FullName, rel);
                if (File.Exists(candidate)) return candidate;
            }
        throw new FileNotFoundException($"repository file {rel} not found above {_dir} or the working directory");
    }
}
