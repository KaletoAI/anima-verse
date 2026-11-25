using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Nav;
using AnimaNative.Overview;

namespace AnimaNative.Tests;

/// <summary>
/// A hand-checkable <see cref="IPathProvider"/>: the walkable area is a union of axis-aligned rectangles minus
/// axis-aligned rectangular holes (an eroded piece of furniture), all on one height <see cref="MeshY"/>.
/// <see cref="Closest"/> is the exact nearest walkable point in xz (the query's y is ignored, the answer carries
/// <see cref="MeshY"/> + <see cref="ClosestYOffset"/>); <see cref="Query"/> returns a registered answer for a
/// (from, to) pair, otherwise the straight line with both owners 0.
/// </summary>
public sealed class FakePathProvider : IPathProvider
{
    public readonly record struct Rect(double X0, double Z0, double X1, double Z1);

    private const double MatchEps = 1e-6;
    private readonly List<Rect> _mesh = new();
    private readonly List<Rect> _holes = new();
    private readonly List<(Vec3 From, Vec3 To, NavPath Path)> _answers = new();

    public double MeshY { get; init; }

    /// <summary>Added to every <see cref="Closest"/> answer's y (a mesh on another storey).</summary>
    public double ClosestYOffset { get; init; }

    public List<(Vec3 From, Vec3 To)> Queries { get; } = new();

    public bool Ready => true;

    public FakePathProvider Mesh(double x0, double z0, double x1, double z1)
    {
        _mesh.Add(new Rect(x0, z0, x1, z1));
        return this;
    }

    public FakePathProvider Hole(double x0, double z0, double x1, double z1)
    {
        _holes.Add(new Rect(x0, z0, x1, z1));
        return this;
    }

    public FakePathProvider Answer(Vec3 from, Vec3 to, IReadOnlyList<Vec3> points, IReadOnlyList<ulong> owners, double length)
    {
        _answers.Add((from, to, new NavPath(points, owners, length)));
        return this;
    }

    public NavPath Query(Vec3 from, Vec3 to)
    {
        Queries.Add((from, to));
        foreach (var a in _answers)
            if (Near(a.From, from) && Near(a.To, to))
                return a.Path;
        double len = Math.Sqrt(Sq(to.X - from.X) + Sq(to.Y - from.Y) + Sq(to.Z - from.Z));
        return new NavPath(new[] { from, to }, new ulong[] { 0, 0 }, len);
    }

    public Vec3 Closest(Vec3 p)
    {
        var candidates = new List<(double X, double Z)>();
        foreach (var r in _mesh)
            candidates.Add((Math.Clamp(p.X, r.X0, r.X1), Math.Clamp(p.Z, r.Z0, r.Z1)));
        foreach (var h in _holes)
        {
            // Projections onto the four hole edges.
            double cx = Math.Clamp(p.X, h.X0, h.X1), cz = Math.Clamp(p.Z, h.Z0, h.Z1);
            candidates.Add((cx, h.Z0));
            candidates.Add((cx, h.Z1));
            candidates.Add((h.X0, cz));
            candidates.Add((h.X1, cz));
        }
        double best = double.PositiveInfinity, bx = p.X, bz = p.Z;
        foreach (var (x, z) in candidates)
        {
            if (!Walkable(x, z)) continue;
            double d = Sq(x - p.X) + Sq(z - p.Z);
            if (d < best) { best = d; bx = x; bz = z; }
        }
        return new Vec3(bx, MeshY + ClosestYOffset, bz);
    }

    private bool Walkable(double x, double z)
        => _mesh.Any(r => x >= r.X0 && x <= r.X1 && z >= r.Z0 && z <= r.Z1)
           && !_holes.Any(h => x > h.X0 && x < h.X1 && z > h.Z0 && z < h.Z1);

    private static bool Near(Vec3 a, Vec3 b)
        => Math.Abs(a.X - b.X) < MatchEps && Math.Abs(a.Y - b.Y) < MatchEps && Math.Abs(a.Z - b.Z) < MatchEps;

    private static double Sq(double v) => v * v;
}
