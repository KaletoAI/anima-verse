using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// ONE import per GLB URL (client3d/src/scene/propAssets.ts <c>leaseGlb</c>: buildings, dioramas, props and
/// door/window models share one cache keyed by URL). Every placement gets a <see cref="Node.Duplicate"/> of
/// the template — meshes and materials are shared resources, exactly like three's <c>clone(true)</c>.
/// A URL that failed stays failed for the session (the browser retries 3 times, then gives up).
/// </summary>
public sealed class ModelCache
{
    public sealed record Template(Node3D Root, GlbCounts Counts, bool Compressed, int Bytes, string Url);

    private readonly IWorldSource _source;
    private readonly Dictionary<string, Task<Template?>> _loads = new();
    private readonly Action<string> _log;

    public int Loaded { get; private set; }
    public int Failed { get; private set; }
    public long Bytes { get; private set; }

    public ModelCache(IWorldSource source, Action<string> log)
    {
        _source = source;
        _log = log;
    }

    /// <summary>The template of a URL (null = not loadable). Main-thread continuation: the import creates nodes.</summary>
    public Task<Template?> GetAsync(string url)
    {
        if (!_loads.TryGetValue(url, out var task)) _loads[url] = task = Load(url);
        return task;
    }

    private async Task<Template?> Load(string url)
    {
        try
        {
            var bytes = await _source.GetBytesAsync(url);
            bool compressed = GlbMeshoptDecoder.IsCompressed(bytes);
            var plain = await Task.Run(() => GlbLoader.Prepare(bytes));
            var (root, counts) = GlbLoader.Import(plain, url);
            Loaded++;
            Bytes += bytes.Length;
            return new Template(root, counts, compressed, bytes.Length, url);
        }
        catch (Exception e)
        {
            Failed++;
            _log($"model {url} not loadable: {e.Message}");
            return null;
        }
    }

    public static Node3D Instance(Template t) => (Node3D)t.Root.Duplicate();

    /// <summary>Free the templates (they never enter the tree); the placed duplicates go with their scene.</summary>
    public void FreeAll()
    {
        foreach (var task in _loads.Values)
            if (task.IsCompletedSuccessfully && task.Result is { } t && GodotObject.IsInstanceValid(t.Root))
                t.Root.Free();
        _loads.Clear();
    }
}
