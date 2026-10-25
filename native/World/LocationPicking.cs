using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The location pick of the overview — engine.ts <c>pickLocation</c>: the ray through the pointer against
/// the resident tile groups (<c>engine.setPickables(residency → tile.group)</c>), nearest hit first, its
/// location id the answer (<c>userData.locationId</c> up the parents). Here every mesh under a built
/// location's group (<see cref="LocationSlot.Group"/>: building models, outdoor and open-interior specs,
/// recipe primitives, the far shell, placeholders) answers that location's id. Nothing else is a target:
/// terrain, world props, scatter and figures are not in the browser's pickables either, so a building
/// behind a hill is picked through the hill there and here. A terrain-only area (forest, lake …) has no
/// geometry of its own since "One ground" — its tile group holds only what its scene recipe draws — so a
/// click on its bare ground is a click on nothing, in the browser and here.
///
/// TECHNIQUE (Task 9 Step 0, numbers in the report): no physics bodies. Per mesh instance the world AABB
/// is cached once (locations do not move; a dropped location loses its entries), the ray is tested against
/// those boxes in C#, and only a mesh whose box it meets is asked for triangles: Godot's own
/// <see cref="TriangleMesh"/> (C++ BVH) of the mesh resource, built lazily on the first such hit and cached
/// by the <see cref="Mesh"/> itself (<c>Mesh::generate_triangle_mesh</c>), so instances of one GLB share it.
/// The ray goes into the mesh's local frame; the hit comes back out and is measured in world metres.
/// Differences to three.js, both without effect on WHICH location answers: Godot's triangle test is
/// two-sided (three culls back faces of FrontSide materials), and only SHOWN meshes answer here: the mount keeps
/// a closed location's interior, an open one's faded roof, an occluded neighbour and the idle half of a cutout
/// pair as hidden nodes (Task 15), and the pick skips every mesh that is not visible in the tree — three's
/// raycaster ignores <c>visible</c>, but those meshes sit inside the same location's other geometry, and the
/// spike (Task 9) showed only what was shown.
/// </summary>
public sealed class LocationPicking
{
    private sealed class Entry
    {
        public required MeshInstance3D Mesh;
        public required Transform3D World;
        public required Transform3D Inverse;
        public required Vec3 Min, Max;
        public TriangleMesh? Triangles;
        public bool Failed;
    }

    private sealed class Cached
    {
        public required Node3D Group;
        public required List<Entry> Entries;
        public required Vec3 Min, Max;
    }

    private readonly WorldBuilder _builder;
    private readonly Dictionary<string, Cached> _cache = new();

    /// <summary>Counters of the last query (for the check and the report).</summary>
    public int LastBoxTests { get; private set; }
    public int LastTriangleQueries { get; private set; }
    public double LastMs { get; private set; }

    public LocationPicking(WorldBuilder builder)
    {
        _builder = builder;
        builder.Dropped += slot => _cache.Remove(slot.Loc.Id);
    }

    /// <summary>The nearest location hit by the ray (world space) and its distance in metres, or null.</summary>
    public (string Id, double Distance)? Pick(Vec3 origin, Vec3 dir)
    {
        var sw = Stopwatch.StartNew();
        LastBoxTests = LastTriangleQueries = 0;
        string? bestId = null;
        double best = double.PositiveInfinity;
        double dirLen = Math.Sqrt(dir.X * dir.X + dir.Y * dir.Y + dir.Z * dir.Z);
        if (dirLen == 0) return null;
        var o = new Vector3((float)origin.X, (float)origin.Y, (float)origin.Z);
        var d = new Vector3((float)(dir.X / dirLen), (float)(dir.Y / dirLen), (float)(dir.Z / dirLen));
        var dn = new Vec3(d.X, d.Y, d.Z);
        foreach (var slot in _builder.Slots.Values)
        {
            // Only what is shown answers: a closed location's interior, a faded roof, an occluded neighbour and the
            // whole-or-cut half of a model that is not up are hidden nodes (the mount keeps them; the pick skips them).
            if (!GodotObject.IsInstanceValid(slot.Group) || !slot.Group.Visible) continue;
            var c = Entries(slot);
            if (c is null) continue;
            LastBoxTests++;
            if (RayMath.RayBox(origin, dn, c.Min, c.Max) is not double groupT || groupT >= best) continue;
            foreach (var e in c.Entries)
            {
                if (!GodotObject.IsInstanceValid(e.Mesh) || !e.Mesh.IsVisibleInTree()) continue;
                LastBoxTests++;
                if (RayMath.RayBox(origin, dn, e.Min, e.Max) is not double boxT || boxT >= best) continue;
                if (Hit(e, o, d) is double t && t < best)
                {
                    best = t;
                    bestId = slot.Loc.Id;
                }
            }
        }
        LastMs = sw.Elapsed.TotalMilliseconds;
        return bestId is null ? null : (bestId, best);
    }

    /// <summary>The ray (unit direction) against one mesh's triangles: the world distance, or null.</summary>
    private double? Hit(Entry e, Vector3 o, Vector3 d)
    {
        if (e.Failed || !GodotObject.IsInstanceValid(e.Mesh) || e.Mesh.Mesh is not { } mesh) return null;
        if (e.Triangles is null)
        {
            e.Triangles = mesh.GenerateTriangleMesh();
            if (e.Triangles is null) { e.Failed = true; return null; }
        }
        LastTriangleQueries++;
        return MeshRay.Query(e.Triangles, e.World, e.Inverse, o, d);
    }

    /// <summary>The cached mesh list of a location (rebuilt when its group changed), null without meshes.</summary>
    private Cached? Entries(LocationSlot slot)
    {
        if (_cache.TryGetValue(slot.Loc.Id, out var c) && c.Group == slot.Group) return c.Entries.Count > 0 ? c : null;
        if (!GodotObject.IsInstanceValid(slot.Group) || !slot.Group.IsInsideTree()) return null;
        var entries = new List<Entry>();
        double minX = double.PositiveInfinity, minY = minX, minZ = minX;
        double maxX = double.NegativeInfinity, maxY = maxX, maxZ = maxX;
        foreach (var mi in Walk(slot.Group).OfType<MeshInstance3D>())
        {
            // The flat overlays (door marks) never catch the ray (main.ts: mesh.raycast = () => {}).
            if (mi.Mesh is not { } mesh || mi.HasMeta(LocationFade.OverlayMeta)) continue;
            var xf = mi.GlobalTransform;
            var box = xf * mesh.GetAabb();
            var lo = box.Position;
            var hi = box.End;
            entries.Add(new Entry
            {
                Mesh = mi, World = xf, Inverse = xf.AffineInverse(),
                Min = new Vec3(lo.X, lo.Y, lo.Z), Max = new Vec3(hi.X, hi.Y, hi.Z),
            });
            minX = Math.Min(minX, lo.X); minY = Math.Min(minY, lo.Y); minZ = Math.Min(minZ, lo.Z);
            maxX = Math.Max(maxX, hi.X); maxY = Math.Max(maxY, hi.Y); maxZ = Math.Max(maxZ, hi.Z);
        }
        c = new Cached { Group = slot.Group, Entries = entries, Min = new Vec3(minX, minY, minZ), Max = new Vec3(maxX, maxY, maxZ) };
        _cache[slot.Loc.Id] = c;
        return entries.Count > 0 ? c : null;
    }

    /// <summary>Mesh instances and triangles under every built location (for the report's numbers).</summary>
    public (int Meshes, int Triangles) Census()
    {
        int meshes = 0, tris = 0;
        var seen = new HashSet<ulong>();
        foreach (var slot in _builder.Slots.Values)
        {
            if (Entries(slot) is not { } c) continue;
            foreach (var e in c.Entries)
            {
                meshes++;
                if (e.Mesh.Mesh is not { } m || !seen.Add(m.GetInstanceId())) continue;
                for (int s = 0; s < m.GetSurfaceCount(); s++)
                {
                    var arrays = m.SurfaceGetArrays(s);
                    var idx = arrays[(int)Mesh.ArrayType.Index].AsInt32Array();
                    tris += idx.Length > 0 ? idx.Length / 3 : arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array().Length / 3;
                }
            }
        }
        return (meshes, tris);
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }
}

/// <summary>The triangle test of one mesh instance, shared by the location and the figure picks.</summary>
public static class MeshRay
{
    /// <summary>
    /// The ray (world, unit <paramref name="d"/>) against the mesh's triangles as they are stored (no skinning):
    /// the world distance of the nearest hit, or null. <see cref="Mesh.GenerateTriangleMesh"/> builds Godot's
    /// BVH once per mesh resource and keeps it in the mesh.
    /// </summary>
    public static double? Static(MeshInstance3D mi, Vector3 o, Vector3 d)
    {
        if (mi.Mesh is not { } mesh || mesh.GenerateTriangleMesh() is not { } tri) return null;
        var xf = mi.GlobalTransform;
        return Query(tri, xf, xf.AffineInverse(), o, d);
    }

    /// <summary>The ray in the mesh's local frame, the hit back in world metres.</summary>
    public static double? Query(TriangleMesh tri, Transform3D world, Transform3D inverse, Vector3 o, Vector3 d)
    {
        var res = tri.IntersectRay(inverse * o, inverse.Basis * d);
        if (res.Count == 0 || !res.ContainsKey("position")) return null;
        var hit = world * res["position"].AsVector3();
        return (hit - o).Length();
    }
}
