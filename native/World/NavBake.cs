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
/// with Godot's 2D baker on the storey outlines; the result is turned into a 3D mesh and lifted to the storey height
/// (or the terrain outside the room hulls, decision 7). The polygon bake won the measurement against the voxel (Recast)
/// bake (decision 9, docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md). Hand derivations:
/// native/fixtures/README.md, section "Nav world"; checks: <c>--check nav</c>, <c>--check navcompare</c>.
/// </summary>
public static class NavBake
{
    /// <summary>
    /// One mesh per storey, parallel to <c>src.Storeys</c>. <paramref name="groundAt"/> (world x, z → world y) is the
    /// terrain under a follow-ground storey; null keeps every vertex on the storey's floor height.
    /// Await it on the main thread: the bake callbacks arrive there, inside the navigation server's sync.
    /// </summary>
    public static async Task<NavigationMesh[]> BakeStoreysAsync(NavSourceData src, NavBakeParams p, Func<double, double, double>? groundAt)
        => await Task.WhenAll(src.Storeys.Select(s => BakeAsync(s, p, groundAt)));

    /// <summary>
    /// The same bake as <see cref="BakeStoreysAsync"/>, synchronous on the calling thread (<c>--check navcompare</c>):
    /// <paramref name="bakeMs"/> is the time spent inside Godot's synchronous bake calls only — not the source
    /// preparation, not a server sync (review W7: the async callback arrives with the frame).
    /// </summary>
    public static NavigationMesh[] BakeStoreys(NavSourceData src, NavBakeParams p, Func<double, double, double>? groundAt, out double bakeMs)
    {
        var watch = new System.Diagnostics.Stopwatch();
        var meshes = new NavigationMesh[src.Storeys.Count];
        for (int i = 0; i < meshes.Length; i++)
        {
            var s = src.Storeys[i];
            var (poly, data) = Input(s, p);
            watch.Start();
            NavigationServer2D.BakeFromSourceGeometryData(poly, data);
            watch.Stop();
            meshes[i] = Lift(poly.GetNavigationMesh(), p, (x, z) => HeightAt(s, groundAt, x, z));
        }
        bakeMs = watch.Elapsed.TotalMilliseconds;
        return meshes;
    }

    /// <summary>
    /// The threshold rectangle as its own mesh: the quad as a one-polygon <see cref="NavigationPolygon"/>, turned into 3D
    /// the same way as a storey (so its winding matches the storey meshes it is welded to), at <c>t.Y</c>.
    /// </summary>
    public static NavigationMesh ThresholdMesh(NavThreshold t, NavBakeParams p)
    {
        var poly = new NavigationPolygon { CellSize = (float)p.CellSize };
        poly.SetVertices(t.Quad.Select(q => new Vector2((float)q.X, (float)q.Z)).ToArray());
        poly.AddPolygon(Enumerable.Range(0, t.Quad.Length).ToArray());
        return Lift(poly.GetNavigationMesh(), p, (_, _) => t.Y);
    }

    private static async Task<NavigationMesh> BakeAsync(NavStoreySource s, NavBakeParams p, Func<double, double, double>? groundAt)
    {
        var (poly, data) = Input(s, p);
        var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        NavigationServer2D.BakeFromSourceGeometryDataAsync(poly, data, Callable.From(() => done.TrySetResult(true)));
        await done.Task;
        return Lift(poly.GetNavigationMesh(), p, (x, z) => HeightAt(s, groundAt, x, z));
    }

    /// <summary>The storey outlines as 2D source geometry and the empty polygon the 2D baker fills.</summary>
    private static (NavigationPolygon, NavigationMeshSourceGeometryData2D) Input(NavStoreySource s, NavBakeParams p)
    {
        var data = new NavigationMeshSourceGeometryData2D();
        foreach (var floor in s.Floors)
        {
            data.AddTraversableOutline(Flat(floor.Outline));
            foreach (var hole in floor.Holes) data.AddObstructionOutline(Flat(hole));
        }
        foreach (var ob in s.Obstacles.Where(o => Blocks(s, o, p)))
            data.AddObstructionOutline(Flat(ob.Outline));
        return (new NavigationPolygon { AgentRadius = (float)p.AgentRadius, CellSize = (float)p.CellSize }, data);
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

    private static Vector2[] Flat(IEnumerable<P2> ring) => ring.Select(q => new Vector2((float)q.X, (float)q.Z)).ToArray();
}
