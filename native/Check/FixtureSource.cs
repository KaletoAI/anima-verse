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
///   urls.json         → payload URL → file: a name in fixtures/, or
///                       <c>repo:&lt;path&gt;</c> = a file of the repository read
///                       in place (clips, a character GLB — nothing copied)
///   model3d.json      → GET /characters/&lt;name&gt;/model3d (name → answer;
///                       null or absent = 404)
///   animation_clips.json → GET /assets/animation-clips
/// </summary>
public sealed class FixtureSource : IWorldSource
{
    private readonly string _dir;
    private readonly Dictionary<string, string> _urls;

    public List<string> TileRequests { get; } = new();
    public List<string> ByteRequests { get; } = new();
    public List<string> ModelRequests { get; } = new();

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
        ByteRequests.Add(url);
        if (!_urls.TryGetValue(url, out var file))
            throw new ApiException(404, url.Split('?')[0], "no fixture for this URL");
        return Task.FromResult(File.ReadAllBytes(Resolve(file)));
    }

    public Task<JsonDocument?> GetCharacterModelAsync(string name)
    {
        ModelRequests.Add(name);
        using var all = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(_dir, "model3d.json")));
        if (!all.RootElement.TryGetProperty(name, out var answer) || answer.ValueKind == JsonValueKind.Null)
            return Task.FromResult<JsonDocument?>(null);
        return Task.FromResult<JsonDocument?>(JsonDocument.Parse(answer.GetRawText()));
    }

    public Task<JsonDocument> GetAnimationClipsAsync() => Doc("animation_clips.json");

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
