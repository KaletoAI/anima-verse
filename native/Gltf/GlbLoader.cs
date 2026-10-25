using System;
using Godot;

namespace AnimaNative.Gltf;

/// <summary>Vertex/index totals of an imported GLB, summed over every surface.</summary>
public readonly record struct GlbCounts(int Meshes, int Surfaces, int Vertices, int Indices);

/// <summary>
/// Runtime GLB import: Meshopt decode (when compressed), then Godot's
/// <c>GLTFDocument.AppendFromBuffer</c> + <c>GenerateScene</c>.
/// </summary>
public static class GlbLoader
{
    /// <summary>Decode on the calling thread (pure C# + native lib; safe off the main thread).</summary>
    public static byte[] Prepare(byte[] glb) => GlbMeshoptDecoder.Decode(glb);

    /// <summary>
    /// Import an already prepared (uncompressed) GLB. Main thread: it creates
    /// nodes and resources. Throws with the Godot error code on failure.
    /// </summary>
    public static (Node3D Root, GlbCounts Counts) Import(byte[] plainGlb, string label)
    {
        var doc = new GltfDocument();
        var state = new GltfState();
        var err = doc.AppendFromBuffer(plainGlb, "", state);
        if (err != Error.Ok) throw new InvalidOperationException($"GLTF import of {label} failed: {err}");
        var counts = Count(state);
        var node = doc.GenerateScene(state) as Node3D
                   ?? throw new InvalidOperationException($"GLTF scene of {label} is empty");
        node.Name = "Glb";
        return (node, counts);
    }

    /// <summary>
    /// Counts from the parsed glTF state (ImporterMesh surfaces — CPU data, so
    /// this also works under <c>--headless</c> where the renderer is a dummy).
    /// </summary>
    public static GlbCounts Count(GltfState state)
    {
        int meshes = 0, surfaces = 0, vertices = 0, indices = 0;
        foreach (var gm in state.GetMeshes())
        {
            var mesh = gm.Mesh;
            if (mesh is null) continue;
            meshes++;
            for (int s = 0; s < mesh.GetSurfaceCount(); s++)
            {
                surfaces++;
                var arrays = mesh.GetSurfaceArrays(s);
                var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
                var idx = arrays[(int)Mesh.ArrayType.Index].AsInt32Array();
                vertices += verts.Length;
                indices += idx.Length;
            }
        }
        return new GlbCounts(meshes, surfaces, vertices, indices);
    }
}
