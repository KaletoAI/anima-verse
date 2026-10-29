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

    private int _generation;
    public int Loaded { get; private set; }
    /// <summary>Template materials whose metalness <see cref="NeutralizeMaterials"/> took back to 0.</summary>
    public int Neutralized { get; private set; }
    public int Failed { get; private set; }
    public long Bytes { get; private set; }

    public ModelCache(IWorldSource source, Action<string> log)
    {
        _source = source;
        _log = log;
    }

    /// <summary>The template of a URL (null = not loadable). Task 37 (E4-T2): resource parsing runs on a worker;
    /// scene generation, material neutralisation and cache accounting resume on the main thread.</summary>
    public Task<Template?> GetAsync(string url)
    {
        if (!_loads.TryGetValue(url, out var task)) _loads[url] = task = Load(url);
        return task;
    }

    private async Task<Template?> Load(string url)
    {
        int generation = _generation;
        try
        {
            var bytes = await _source.GetBytesAsync(url);
            if (generation != _generation) return null;
            bool compressed = GlbMeshoptDecoder.IsCompressed(bytes);
            var (doc, state, counts) = await Task.Run(() =>
            {
                using var parse = (_source as AnimaApi)?.Measurements.Time("scene GLB", "parse");
                return GlbLoader.Parse(GlbLoader.Prepare(bytes), url);
            });
            // Task 44: world disposal invalidates late imports before a detached template node is generated.
            if (generation != _generation) { doc.Dispose(); state.Dispose(); return null; }
            Node3D root;
            using ((_source as AnimaApi)?.Measurements.Time("scene GLB", "generate"))
            using (Ui.HitchLog.Time("model generate"))
                root = GlbLoader.Generate(doc, state, url);
            Neutralized += NeutralizeMaterials(root);
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

    /// <summary>
    /// client3d/src/scene/glbMaterials.ts <c>neutralizeGltfMaterials</c>, run once per imported GLB (propAssets.ts runs
    /// it on load, before any placement): generated GLBs often leave <c>metallicFactor</c> unset, glTF's default is 1.0,
    /// and an untextured metal without an environment map renders almost black — it is meant as no metal at all.
    /// <see cref="MaterialLooks.NeutralizeLook"/> decides (vector-checked): untextured metalness above 0.5 → 0, a real
    /// metal-roughness texture keeps it. The browser then also hangs a neutral environment map at intensity 0.7 on the
    /// textured ones; Godot has no per-material environment map — those materials take the scene's reflections.
    /// The template's materials are changed IN PLACE (they are this GLB's own, shared by every placement of it, like the
    /// browser's lease). Returns how many materials went to 0.
    /// </summary>
    public static int NeutralizeMaterials(Node root)
    {
        int changed = 0;
        var seen = new HashSet<ulong>();
        foreach (var mi in Walk(root))
        {
            if (mi is not MeshInstance3D { Mesh: { } mesh } inst) continue;
            for (int s = 0; s < mesh.GetSurfaceCount(); s++)
            {
                if ((inst.GetSurfaceOverrideMaterial(s) ?? mesh.SurfaceGetMaterial(s)) is not BaseMaterial3D m) continue;
                if (!seen.Add(m.GetInstanceId())) continue;
                var look = Scene.MaterialLooks.NeutralizeLook(m.Metallic, m.MetallicTexture is not null, true);
                if (look.Metalness != m.Metallic)
                {
                    m.Metallic = (float)look.Metalness;
                    changed++;
                }
            }
        }
        return changed;
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }

    public static Node3D Instance(Template t)
    {
        using var hitch = Ui.HitchLog.Time("model instance");
        return (Node3D)t.Root.Duplicate();
    }

    /// <summary>Free the templates (they never enter the tree); the placed duplicates go with their scene.</summary>
    public void FreeAll()
    {
        _generation++;
        foreach (var task in _loads.Values)
            if (task.IsCompletedSuccessfully && task.Result is { } t && GodotObject.IsInstanceValid(t.Root))
                t.Root.Free();
        _loads.Clear();
    }
}
