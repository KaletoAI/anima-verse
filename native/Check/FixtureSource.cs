using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
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
///   urls.json         → payload URL → GLB file name
/// </summary>
public sealed class FixtureSource : IWorldSource
{
    private readonly string _dir;
    private readonly Dictionary<string, string> _urls;

    public List<string> TileRequests { get; } = new();

    public FixtureSource(string dir)
    {
        _dir = dir;
        _urls = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(Path.Combine(dir, "urls.json")))
                ?? new Dictionary<string, string>();
    }

    private Task<JsonDocument> Doc(string file) => Task.FromResult(JsonDocument.Parse(File.ReadAllBytes(Path.Combine(_dir, file))));

    public Task<JsonDocument> GetWorldMapAsync() => Doc("worldmap.json");
    public Task<JsonDocument> GetHeightfieldAsync() => Doc("heightfield.json");
    public Task<JsonDocument> GetLocations3dAsync() => Doc("locations.json");

    public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys)
    {
        if (keys.Count == 0 || keys.Count > AnimaApi.HeightTileBatchMax)
            throw new ArgumentOutOfRangeException(nameof(keys));
        var wanted = keys.Select(k => $"{k.Tx},{k.Tz}").ToHashSet();
        TileRequests.AddRange(wanted);
        using var all = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(_dir, "tiles.json")));
        var root = all.RootElement;
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
        return Task.FromResult(JsonDocument.Parse(JsonSerializer.Serialize(answer)));
    }

    public Task<JsonDocument?> GetLocationSceneAsync(string locationId)
    {
        var path = Path.Combine(_dir, $"scene_{locationId}.json");
        return Task.FromResult(File.Exists(path) ? JsonDocument.Parse(File.ReadAllBytes(path)) : null);
    }

    public Task<byte[]> GetBytesAsync(string url)
    {
        if (!_urls.TryGetValue(url, out var file))
            throw new ApiException(404, url.Split('?')[0], "no fixture for this URL");
        return Task.FromResult(File.ReadAllBytes(Path.Combine(_dir, file)));
    }
}
