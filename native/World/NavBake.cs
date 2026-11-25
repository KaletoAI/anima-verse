using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Nav;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// Bakes the storey meshes of one location's navigation source (plan 2026-11-25-client-ausfuehrung-e2, decision 1)
/// with Godot's own bakers. Polygon mode: the 2D baker on the storey outlines, its result turned into a 3D mesh and
/// lifted to the storey height (or the terrain outside the room hulls, decision 7). Voxel mode: the floors as
/// triangles and the obstacles as projected obstructions through the 3D (Recast) baker. Hand derivations:
/// native/fixtures/README.md, section "Nav world"; check: <c>--check nav</c>.
/// </summary>
public static class NavBake
{
    /// <summary>
    /// One mesh per storey, parallel to <c>src.Storeys</c>. <paramref name="groundAt"/> (world x, z → world y) is the
    /// terrain under a follow-ground storey; null keeps every vertex on the storey's floor height.
    /// Await it on the main thread: the bake callbacks arrive there, inside the navigation server's sync.
    /// </summary>
    public static async Task<NavigationMesh[]> BakeStoreysAsync(NavSourceData src, NavBakeParams p, Func<double, double, double>? groundAt)
    {
        var bakes = src.Storeys.Select(s => p.Mode == NavBakeMode.Polygon ? BakePolygonAsync(s, p, groundAt) : BakeVoxelAsync(s, p, groundAt));
        return await Task.WhenAll(bakes);
    }

    /// <summary>
    /// The threshold rectangle as its own mesh: the quad as a one-polygon <see cref="NavigationPolygon"/>, turned into 3D
    /// the same way as a polygon-mode storey (so its winding matches the storey meshes it is welded to), at <c>t.Y</c>.
    /// </summary>
    public static NavigationMesh ThresholdMesh(NavThreshold t, NavBakeParams p)
    {
        var poly = new NavigationPolygon { CellSize = (float)p.CellSize };
        poly.SetVertices(t.Quad.Select(q => new Vector2((float)q.X, (float)q.Z)).ToArray());
        poly.AddPolygon(Enumerable.Range(0, t.Quad.Length).ToArray());
        return Lift(poly.GetNavigationMesh(), p, (_, _) => t.Y);
    }

    private static async Task<NavigationMesh> BakePolygonAsync(NavStoreySource s, NavBakeParams p, Func<double, double, double>? groundAt)
    {
        var data = new NavigationMeshSourceGeometryData2D();
        foreach (var floor in s.Floors)
        {
            data.AddTraversableOutline(Flat(floor.Outline));
            foreach (var hole in floor.Holes) data.AddObstructionOutline(Flat(hole));
        }
        foreach (var ob in s.Obstacles.Where(o => Blocks(s, o, p)))
            data.AddObstructionOutline(Flat(ob.Outline));
        var poly = new NavigationPolygon { AgentRadius = (float)p.AgentRadius, CellSize = (float)p.CellSize };
        var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        NavigationServer2D.BakeFromSourceGeometryDataAsync(poly, data, Callable.From(() => done.TrySetResult(true)));
        await done.Task;
        return Lift(poly.GetNavigationMesh(), p, (x, z) => HeightAt(s, groundAt, x, z));
    }

    private static async Task<NavigationMesh> BakeVoxelAsync(NavStoreySource s, NavBakeParams p, Func<double, double, double>? groundAt)
    {
        var data = new NavigationMeshSourceGeometryData3D();
        foreach (var floor in s.Floors)
        {
            var faces = FloorFaces(floor, (x, z) => HeightAt(s, groundAt, x, z));
            if (faces.Length > 0) data.AddFaces(faces, Transform3D.Identity);
        }
        foreach (var ob in s.Obstacles.Where(o => Blocks(s, o, p)))
        {
            var outline = ob.Outline.Select(q => new Vector3((float)q.X, (float)ob.BottomY, (float)q.Z)).ToArray();
            data.AddProjectedObstruction(outline, (float)ob.BottomY, (float)(ob.TopY - ob.BottomY), false);
        }
        var mesh = new NavigationMesh
        {
            AgentRadius = (float)p.AgentRadius,
            AgentHeight = (float)p.AgentHeight,
            AgentMaxClimb = (float)p.AgentMaxClimb,
            AgentMaxSlope = (float)p.AgentMaxSlopeDeg,
            CellSize = (float)p.CellSize,
            CellHeight = (float)p.CellHeight,
        };
        var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        NavigationServer3D.BakeFromSourceGeometryDataAsync(mesh, data, Callable.From(() => done.TrySetResult(true)));
        await done.Task;
        return mesh;
    }

    /// <summary>An obstacle counts when its height band reaches into the walking space above the storey floor.</summary>
    private static bool Blocks(NavStoreySource s, NavObstacle o, NavBakeParams p)
        => o.TopY > s.FloorY + p.AgentMaxClimb && o.BottomY < s.FloorY + p.AgentHeight;

    /// <summary>Decision 7: inside a room hull (or without terrain) the storey floor, outside it the terrain.</summary>
    private static double HeightAt(NavStoreySource s, Func<double, double, double>? groundAt, double x, double z)
    {
        if (!s.FollowGround || groundAt is null) return s.FloorY;
        foreach (var hull in s.Hulls)
            if (SceneView.PointInPolygon(x, z, hull)) return s.FloorY;
        return groundAt(x, z);
    }

    /// <summary>
    /// The 2D bake result (vertices (x, 0, z)) as a fresh mesh with every vertex lifted to <paramref name="yAt"/> and the
    /// map's cell size / height, so the region matches its map.
    /// </summary>
    private static NavigationMesh Lift(NavigationMesh flat, NavBakeParams p, Func<double, double, double> yAt)
    {
        var verts = flat.GetVertices();
        for (int i = 0; i < verts.Length; i++)
            verts[i] = new Vector3(verts[i].X, (float)yAt(verts[i].X, verts[i].Z), verts[i].Z);
        var mesh = new NavigationMesh
        {
            CellSize = (float)p.CellSize,
            CellHeight = (float)p.CellHeight,
            AgentRadius = (float)p.AgentRadius,
            AgentHeight = (float)p.AgentHeight,
            AgentMaxClimb = (float)p.AgentMaxClimb,
            AgentMaxSlope = (float)p.AgentMaxSlopeDeg,
        };
        mesh.SetVertices(verts);
        for (int i = 0; i < flat.GetPolygonCount(); i++) mesh.AddPolygon(flat.GetPolygon(i));
        return mesh;
    }

    /// <summary>
    /// A floor with its holes as walkable triangles for the Recast baker: <see cref="Earcut"/> on the outline plus holes,
    /// every triangle put into Godot's front-face winding seen from above, cross(v1 − v0, v2 − v0).y &lt; 0 (Godot reverses
    /// it for Recast; measured with 4.7.2: the other winding bakes no polygon at all).
    /// </summary>
    private static Vector3[] FloorFaces(NavFloor floor, Func<double, double, double> yAt)
    {
        var rings = new List<P2[]> { floor.Outline };
        rings.AddRange(floor.Holes);
        var coords = new List<double>();
        var holeStarts = new List<int>();
        int count = 0;
        foreach (var ring in rings)
        {
            if (coords.Count > 0) holeStarts.Add(count);
            foreach (var q in ring) { coords.Add(q.X); coords.Add(q.Z); count++; }
        }
        var tris = Earcut.Triangulate(coords, holeStarts);
        var faces = new Vector3[tris.Count];
        Vector3 At(int i) => new((float)coords[2 * i], (float)yAt(coords[2 * i], coords[2 * i + 1]), (float)coords[2 * i + 1]);
        for (int t = 0; t + 2 < tris.Count; t += 3)
        {
            var a = At(tris[t]);
            var b = At(tris[t + 1]);
            var c = At(tris[t + 2]);
            if ((b - a).Cross(c - a).Y > 0) (b, c) = (c, b);
            faces[t] = a;
            faces[t + 1] = b;
            faces[t + 2] = c;
        }
        return faces;
    }

    private static Vector2[] Flat(IEnumerable<P2> ring) => ring.Select(q => new Vector2((float)q.X, (float)q.Z)).ToArray();
}
