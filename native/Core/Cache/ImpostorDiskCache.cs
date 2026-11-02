using System;
using System.IO;
using System.Linq;
using AnimaNative.Scatter;

namespace AnimaNative.Cache;

public sealed record ImpostorPixels(int Size, ImpostorFrame Frame, byte[] RgbaMips);

/// <summary>Task 91: finished RGBA8 mip chains in the client's existing origin store, budget, LRU and clear tree.
/// Unversioned URLs stay session-only: without a response identity a persistent hit could hide changed content.</summary>
public sealed class ImpostorDiskCache(DiskCache store, int bakeVersion = ImpostorDiskCache.BakeCodeVersion)
{
    /// <summary>Bump for ANY bake change: geometry, camera, materials/shaders, lighting, readback or mip generation.</summary>
    public const int BakeCodeVersion = 1;
    private const int Magic = 0x314D5049; // IPM1, little endian.

    public static string? Key(string url, int size, int version = BakeCodeVersion)
    {
        if (!Uri.TryCreate(new Uri("https://cache.invalid"), url, out var uri)
            || !uri.Query.TrimStart('?').Split('&').Any(p => p.StartsWith("v=", StringComparison.Ordinal) && p.Length > 2)) return null;
        return "derived:impostor:" + DerivedKeys.Of(version, size, url);
    }

    public ImpostorPixels? Read(string url, int size)
    {
        string? key = Key(url, size, bakeVersion);
        if (key is null || store.Read(key) is not { } hit) return null;
        try
        {
            using var input = new BinaryReader(new MemoryStream(hit.Body, writable: false));
            if (input.ReadInt32() != Magic || input.ReadInt32() != size) return null;
            var frame = new ImpostorFrame(input.ReadDouble(), input.ReadDouble());
            int count = input.ReadInt32();
            if (!ValidFrame(frame) || count != MipBytes(size) || input.BaseStream.Length - input.BaseStream.Position != count) return null;
            return new(size, frame, input.ReadBytes(count));
        }
        catch (EndOfStreamException) { return null; }
    }

    public void Store(string url, ImpostorPixels bake)
    {
        string? key = Key(url, bake.Size, bakeVersion);
        if (key is null) return;
        if (!ValidFrame(bake.Frame) || bake.RgbaMips.Length != MipBytes(bake.Size)) throw new ArgumentException("Invalid impostor pixels");
        using var output = new MemoryStream();
        using (var writer = new BinaryWriter(output, System.Text.Encoding.UTF8, leaveOpen: true))
        {
            writer.Write(Magic); writer.Write(bake.Size);
            writer.Write(bake.Frame.SpanH); writer.Write(bake.Frame.Aspect);
            writer.Write(bake.RgbaMips.Length); writer.Write(bake.RgbaMips);
        }
        store.Store(key, output.ToArray(), null, new HttpCachePolicy(true, true, DateTimeOffset.MaxValue, "immutable"));
    }

    private static bool ValidFrame(ImpostorFrame f) => double.IsFinite(f.SpanH) && f.SpanH > 0 && double.IsFinite(f.Aspect) && f.Aspect > 0;
    private static int MipBytes(int size)
    {
        if (size < 1 || size > 4096 || (size & (size - 1)) != 0) return -1;
        int bytes = 0;
        for (int n = size; n > 0; n /= 2) bytes += n * n * 4;
        return bytes;
    }
}
