using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using Godot;

namespace AnimaNative.World;

/// <summary>One entry of <c>GET /assets/surface-textures</c> as the recipe materials read it.</summary>
public sealed record SurfaceEntry(string Kind, string? Url, double SizeM, JsonElement? Material);

/// <summary>
/// The surface library for the RECIPE primitives (client3d/src/scene/tiles.ts <c>setSurfaceTextures</c> +
/// <c>preloadSurfaceTexture</c> + <c>surfaceFor</c>): kind → image as a tiling texture (mipmaps, anisotropic,
/// repeat) plus its world tile size (<c>size_m || 3</c>) and its <c>material</c> declaration. Images load once
/// per kind, on demand (<see cref="PreloadAsync"/> — what <c>mountShell</c> awaits before it builds); a kind
/// whose image failed answers null, like the browser's empty cache slot.
/// </summary>
public sealed class SurfaceLibrary
{
    private readonly Dictionary<string, SurfaceEntry> _entries = new();
    private readonly ConcurrentDictionary<string, Task<ImageTexture?>> _textures = new();
    private readonly IWorldSource _source;
    private readonly Action<string> _log;

    public int Loaded => _textures.Values.Count(t => t.IsCompletedSuccessfully && t.Result is not null);
    public int Failed => _textures.Values.Count(t => t.IsCompleted && (!t.IsCompletedSuccessfully || t.Result is null));

    private SurfaceLibrary(IWorldSource source, Action<string> log)
    {
        _source = source;
        _log = log;
    }

    public static async Task<SurfaceLibrary> LoadAsync(IWorldSource source, Action<string> log)
    {
        var lib = new SurfaceLibrary(source, log);
        try
        {
            using var doc = await source.GetSurfaceTexturesAsync();
            var root = doc.RootElement;
            var list = root.ValueKind == JsonValueKind.Array ? root.EnumerateArray() : Json.Arr(root, "textures");
            foreach (var t in list)
            {
                if (t.ValueKind != JsonValueKind.Object) continue;
                var kind = Json.Str(t, "kind").ToLowerInvariant();
                if (kind.Length == 0) continue;
                var url = Json.Str(t, "url");
                double size = Json.Num(t, "size_m");
                JsonElement? mat = t.TryGetProperty("material", out var m) && m.ValueKind == JsonValueKind.Object
                    ? m.Clone() : null;
                lib._entries[kind] = new SurfaceEntry(kind, url.Length > 0 ? url : null, size != 0 ? size : 3, mat);
            }
        }
        catch (Exception e)
        {
            // getSurfaceTextures: any failure is an empty library — every primitive wears its style colour.
            log($"recipe: surface library unavailable ({e.Message}) — style colours only");
        }
        return lib;
    }

    public SurfaceEntry? Entry(string? kind)
        => _entries.TryGetValue((kind ?? "").ToLowerInvariant(), out var e) ? e : null;

    /// <summary>Start (once) and await the images of these kinds — <c>preloadSurfaceTexture</c>.</summary>
    public Task PreloadAsync(IEnumerable<string> kinds)
        => Task.WhenAll(kinds.Select(k => k.ToLowerInvariant()).Distinct()
                             .Where(k => Entry(k)?.Url is not null)
                             .Select(k => _textures.GetOrAdd(k, Load)));

    private async Task<ImageTexture?> Load(string kind)
    {
        try
        {
            var bytes = await _source.GetBytesAsync(Entry(kind)!.Url!);
            var img = await Task.Run(() =>
                {
                    using var parse = (_source as AnimaApi)?.Measurements.Time("texture", "parse");
                    return Decode(bytes);
                });
            return ImageTexture.CreateFromImage(img);
        }
        catch (Exception e)
        {
            _log($"recipe: surface '{kind}' failed ({e.Message}) — primitives of that kind wear the style colour");
            return null;
        }
    }

    /// <summary>PNG/JPEG/WebP → RGBA8 with mipmaps, at the source size (the browser uploads the image as is).</summary>
    public static Image Decode(byte[] bytes)
    {
        var img = new Image();
        Error err;
        if (bytes.Length > 8 && bytes[0] == 0x89 && bytes[1] == (byte)'P') err = img.LoadPngFromBuffer(bytes);
        else if (bytes.Length > 3 && bytes[0] == 0xFF && bytes[1] == 0xD8) err = img.LoadJpgFromBuffer(bytes);
        else if (bytes.Length > 12 && bytes[0] == (byte)'R' && bytes[8] == (byte)'W') err = img.LoadWebpFromBuffer(bytes);
        else throw new FormatException("not a PNG, JPEG or WebP image");
        if (err != Error.Ok || img.IsEmpty()) throw new FormatException($"image decode failed ({err})");
        if (img.IsCompressed()) img.Decompress();
        img.Convert(Image.Format.Rgba8);
        img.GenerateMipmaps();
        return img;
    }

    /// <summary>
    /// <c>surfaceFor(kind, use)</c>: floors fall back to the global <c>floor</c> kind, walls do not; only a kind
    /// whose image has LOADED answers.
    /// </summary>
    public (ImageTexture Texture, double SizeM)? SurfaceFor(string? kind, bool floor)
    {
        var chain = floor ? new[] { kind ?? "", "floor" } : new[] { kind ?? "" };
        foreach (var c in chain)
        {
            var key = c.ToLowerInvariant();
            if (_entries.TryGetValue(key, out var e) && _textures.TryGetValue(key, out var t)
                && t.IsCompletedSuccessfully && t.Result is { } tex)
                return (tex, e.SizeM);
        }
        return null;
    }

    /// <summary><c>surfaceMaterialSpec(kind)</c>: the library's <c>material</c> declaration, null = matte.</summary>
    public JsonElement? MaterialSpec(string? kind) => Entry(kind)?.Material;
}
