using System;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using Godot;

namespace AnimaNative.Scatter;

/// <summary>The first mesh of a prop GLB, as the browser instances it.</summary>
public sealed class PropMeshData
{
    public required Vector3[] Vertices;
    public Vector3[]? Normals;
    public Vector2[]? Uvs;
    public required int[] Indices;
    public Material? Material;
    public int Triangles => Indices.Length > 0 ? Indices.Length / 3 : Vertices.Length / 3;
}

/// <summary>Task 37 (E4-T2): worker-built geometry and clearance bounds; the main thread only makes the scatter
/// shader and places the instances. The material is the first glTF surface's, as before.</summary>
public sealed record GroundedPropMesh(ArrayMesh Mesh, Aabb Bounds, Material? Material, int Triangles);

/// <summary>
/// Prop GLB → the geometry a scatter entry instances (<c>mountUrl</c> + <c>groundedGeometry</c> in
/// client3d/src/scene/ground.ts):
///
///   · the browser takes the FIRST <c>THREE.Mesh</c> of the file in depth-first order — for a glTF mesh
///     with several primitives that is its first primitive only — so this takes surface 0 of the first
///     glTF node with a mesh (pre-order over the scene's root nodes), with the node's world transform
///     inside the file baked into the vertices;
///   · then <c>propGroundFit</c>: uniform scale to the target height, lifted so the lowest point is y = 0.
///
/// Read from Godot's glTF STATE (ImporterMesh arrays — CPU data, so it also works on the headless dummy
/// renderer), and built into a plain <see cref="ArrayMesh"/> WITHOUT Godot's automatic mesh LODs — the
/// browser draws the full triangle count at every distance, and so does this (no favour for Godot).
/// </summary>
public static class PropMesh
{
    /// <summary>Task 37 (E4-T2): decode, parse, first-mesh walk and transform bake in one worker turn (resource and
    /// array work only, Task 35b; no scene nodes). Once per URL — every height grounds the same parse.</summary>
    public static async Task<PropMeshData?> ParseAsync(IWorldSource source, string url)
    {
        var bytes = await source.GetBytesAsync(url);
        return await Task.Run(() =>
                {
                    using var parse = (source as AnimaApi)?.Measurements.Time("scene GLB", "parse");
                    return Extract(GlbLoader.Prepare(bytes), url);
                });
    }

    /// <summary>Task 37 (E4-T2): grounding and the <see cref="ArrayMesh"/> for one target height, on a worker.</summary>
    public static Task<GroundedPropMesh> GroundAsync(PropMeshData data, double targetH)
        => Task.Run(() =>
        {
            var (mesh, bounds) = Grounded(data, targetH);
            return new GroundedPropMesh(mesh, bounds, data.Material, data.Triangles);
        });

    /// <summary><see cref="ParseAsync"/> then <see cref="GroundAsync"/> (null = no mesh in the file).</summary>
    public static async Task<GroundedPropMesh?> LoadAsync(IWorldSource source, string url, double targetH)
        => await ParseAsync(source, url) is { } data ? await GroundAsync(data, targetH) : null;

    /// <summary>Resource-only glTF parse and first-mesh extraction; runs on the worker (Task 37, E4-T2).</summary>
    public static PropMeshData? Extract(byte[] plainGlb, string label)
    {
        var doc = new GltfDocument();
        var state = new GltfState();
        var err = doc.AppendFromBuffer(plainGlb, "", state);
        if (err != Error.Ok) throw new InvalidOperationException($"GLTF import of {label} failed: {err}");
        var nodes = state.GetNodes();
        var meshes = state.GetMeshes();
        int meshIndex = -1;
        var xf = Transform3D.Identity;

        bool Visit(int i, Transform3D parent)
        {
            if (i < 0 || i >= nodes.Count) return false;
            var n = nodes[i];
            var world = parent * n.Xform;
            if (n.Mesh >= 0) { meshIndex = n.Mesh; xf = world; return true; }
            foreach (int c in n.Children)
                if (Visit(c, world)) return true;
            return false;
        }

        foreach (int r in state.RootNodes)
            if (Visit(r, Transform3D.Identity)) break;
        if (meshIndex < 0 || meshIndex >= meshes.Count) return null;
        var im = meshes[meshIndex].Mesh;
        if (im is null || im.GetSurfaceCount() == 0) return null;
        var arrays = im.GetSurfaceArrays(0);
        var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        if (verts.Length == 0) return null;
        var normals = arrays[(int)Mesh.ArrayType.Normal].VariantType == Variant.Type.Nil
            ? null : arrays[(int)Mesh.ArrayType.Normal].AsVector3Array();
        var uvs = arrays[(int)Mesh.ArrayType.TexUV].VariantType == Variant.Type.Nil
            ? null : arrays[(int)Mesh.ArrayType.TexUV].AsVector2Array();
        var index = arrays[(int)Mesh.ArrayType.Index].VariantType == Variant.Type.Nil
            ? Array.Empty<int>() : arrays[(int)Mesh.ArrayType.Index].AsInt32Array();
        var nbasis = xf.Basis.Inverse().Transposed();
        for (int i = 0; i < verts.Length; i++) verts[i] = xf * verts[i];
        if (normals is { Length: > 0 })
            for (int i = 0; i < normals.Length; i++) normals[i] = (nbasis * normals[i]).Normalized();
        return new PropMeshData
        {
            Vertices = verts,
            Normals = normals is { Length: > 0 } ? normals : null,
            Uvs = uvs is { Length: > 0 } ? uvs : null,
            Indices = index,
            Material = im.GetSurfaceMaterial(0),
        };
    }

    /// <summary><c>groundedGeometry</c>: scaled to <paramref name="targetH"/>, lowest point at 0. Returns the
    /// mesh and its bounds (the bounds feed the clearance ledger, <c>noteSpread</c>).</summary>
    public static (ArrayMesh Mesh, Aabb Bounds) Grounded(PropMeshData d, double targetH)
    {
        float minY = float.PositiveInfinity, maxY = float.NegativeInfinity;
        foreach (var v in d.Vertices) { minY = Math.Min(minY, v.Y); maxY = Math.Max(maxY, v.Y); }
        var (scale, offsetY) = ScatterMath.GroundFit(minY, maxY, targetH);
        var verts = new Vector3[d.Vertices.Length];
        var min = new Vector3(float.PositiveInfinity, float.PositiveInfinity, float.PositiveInfinity);
        var max = -min;
        for (int i = 0; i < verts.Length; i++)
        {
            var v = d.Vertices[i];
            var p = new Vector3((float)(v.X * scale), (float)(v.Y * scale + offsetY), (float)(v.Z * scale));
            verts[i] = p;
            min = min.Min(p);
            max = max.Max(p);
        }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = verts;
        if (d.Normals is not null && d.Normals.Length == verts.Length) arrays[(int)Mesh.ArrayType.Normal] = d.Normals;
        if (d.Uvs is not null && d.Uvs.Length == verts.Length) arrays[(int)Mesh.ArrayType.TexUV] = d.Uvs;
        if (d.Indices.Length > 0) arrays[(int)Mesh.ArrayType.Index] = d.Indices;
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        return (mesh, new Aabb(min, max - min));
    }

    /// <summary>The built-in tuft: three's <c>ConeGeometry(0.22, h, 5)</c> with its base at y = 0 — five side
    /// triangles + five base triangles (10), wound clockwise for Godot.</summary>
    public static ArrayMesh Cone(double radius, double h, int segments = 5)
    {
        var verts = new System.Collections.Generic.List<Vector3>();
        var normals = new System.Collections.Generic.List<Vector3>();
        var idx = new System.Collections.Generic.List<int>();
        float r = (float)radius, hh = (float)h;
        var apex = new Vector3(0, hh, 0);
        for (int s = 0; s < segments; s++)
        {
            double a0 = s * 2 * Math.PI / segments, a1 = (s + 1) * 2 * Math.PI / segments;
            var p0 = new Vector3((float)(r * Math.Sin(a0)), 0, (float)(r * Math.Cos(a0)));
            var p1 = new Vector3((float)(r * Math.Sin(a1)), 0, (float)(r * Math.Cos(a1)));
            var n = (p1 - apex).Cross(p0 - apex).Normalized();
            int b = verts.Count;
            verts.AddRange(new[] { apex, p1, p0 });
            normals.AddRange(new[] { n, n, n });
            idx.AddRange(new[] { b, b + 1, b + 2 });
            b = verts.Count;
            verts.AddRange(new[] { Vector3.Zero, p0, p1 });
            normals.AddRange(new[] { Vector3.Down, Vector3.Down, Vector3.Down });
            idx.AddRange(new[] { b, b + 1, b + 2 });
        }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = verts.ToArray();
        arrays[(int)Mesh.ArrayType.Normal] = normals.ToArray();
        arrays[(int)Mesh.ArrayType.Index] = idx.ToArray();
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        return mesh;
    }
}
