using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Embody;

/// <summary>Task 47: collide.ts reduced wall line in the caller's XZ frame.</summary>
public readonly record struct WallSegment(double Ax, double Az, double Bx, double Bz);

/// <summary>
/// Task 47 (E7-T2), collide.ts: free-end doorway ease, conservative capsule push-out and sliding.
/// The result never crosses a wall and never reduces clearance below min(radius, original clearance).
/// Narrow corridors need not achieve full radius clearance; shared/test-vectors/collide.json.
/// </summary>
public static class Collide
{
    public const double BodyRadiusM = 0.25, DoorEaseM = 0.12;
    private const double Eps = 1e-9, ClearTol = 1e-6, JointTol = 0.01, MaxEaseShare = 0.4;
    private const int PushPasses = 8;
    public static double BodyRadius(double k) => BodyRadiusM * (double.IsFinite(k) && k > 0 ? k : 1);

    /// <summary>Only this storey's finite nonzero walls; lintels and leaves leave a walkable gap, glass still blocks.</summary>
    public static List<WallSegment> WallSegments(ScenePayload? payload, int level, P2 origin = default)
    {
        var raw = new List<WallSegment>();
        foreach (var w in payload?.Walls ?? new List<SceneWall>())
        {
            if (w.Level != level || w.Lintel || w.Leaf) continue;
            var s = new WallSegment(origin.X + w.From.X, origin.Z + w.From.Z, origin.X + w.To.X, origin.Z + w.To.Z);
            if (!double.IsFinite(s.Ax) || !double.IsFinite(s.Az) || !double.IsFinite(s.Bx) || !double.IsFinite(s.Bz)) continue;
            if (double.Hypot(s.Bx - s.Ax, s.Bz - s.Az) < Eps) continue;
            raw.Add(s);
        }
        double k = payload?.K ?? 1;
        double ease = DoorEaseM * (double.IsFinite(k) && k > 0 ? k : 1);
        var ends = raw.SelectMany(s => new[] { new P2(s.Ax, s.Az), new P2(s.Bx, s.Bz) }).ToList();
        bool Shared(double x, double z) => ends.Count(e => double.Hypot(e.X - x, e.Z - z) <= JointTol) > 1;
        return raw.Select(s =>
        {
            double dx = s.Bx - s.Ax, dz = s.Bz - s.Az, len = double.Hypot(dx, dz);
            double cut = Math.Min(ease, len * MaxEaseShare), ux = dx / len, uz = dz / len;
            double a = Shared(s.Ax, s.Az) ? 0 : cut, b = Shared(s.Bx, s.Bz) ? 0 : cut;
            return new WallSegment(s.Ax + ux * a, s.Az + uz * a, s.Bx - ux * b, s.Bz - uz * b);
        }).ToList();
    }

    private static P2 ClosestOn(P2 p, WallSegment s)
    {
        double dx = s.Bx - s.Ax, dz = s.Bz - s.Az, len2 = dx * dx + dz * dz;
        if (len2 < Eps) return new(s.Ax, s.Az);
        double t = Math.Clamp(((p.X - s.Ax) * dx + (p.Z - s.Az) * dz) / len2, 0, 1);
        return new(s.Ax + dx * t, s.Az + dz * t);
    }
    private static double Cross(double ax, double az, double bx, double bz) => ax * bz - az * bx;

    /// <summary>Collinear overlap counts; contact only at the origin does not freeze a server-corrected figure.</summary>
    private static bool SegmentsCross(P2 p0, P2 p1, WallSegment s)
    {
        double rx = p1.X - p0.X, rz = p1.Z - p0.Z, sx = s.Bx - s.Ax, sz = s.Bz - s.Az;
        double denom = Cross(rx, rz, sx, sz), qpx = s.Ax - p0.X, qpz = s.Az - p0.Z;
        if (Math.Abs(denom) < Eps)
        {
            if (Math.Abs(Cross(qpx, qpz, rx, rz)) > Eps) return false;
            double r2 = rx * rx + rz * rz;
            if (r2 < Eps) return false;
            double t0 = (qpx * rx + qpz * rz) / r2, t1 = t0 + (sx * rx + sz * rz) / r2;
            double lo = Math.Max(0, Math.Min(t0, t1)), hi = Math.Min(1, Math.Max(t0, t1));
            return hi > Eps && lo <= hi + Eps;
        }
        double t = Cross(qpx, qpz, sx, sz) / denom, u = Cross(qpx, qpz, rx, rz) / denom;
        return t > Eps && t <= 1 + Eps && u >= -Eps && u <= 1 + Eps;
    }
    private static WallSegment? FirstCrossed(P2 from, P2 to, IReadOnlyList<WallSegment> segments)
    {
        if (double.Hypot(to.X - from.X, to.Z - from.Z) < Eps) return null;
        foreach (var s in segments) if (SegmentsCross(from, to, s)) return s;
        return null;
    }
    private static P2 SlideAlong(P2 from, P2 to, WallSegment s)
    {
        double dx = s.Bx - s.Ax, dz = s.Bz - s.Az, len = double.Hypot(dx, dz);
        if (len < Eps) return from;
        double ux = dx / len, uz = dz / len, along = (to.X - from.X) * ux + (to.Z - from.Z) * uz;
        return new(from.X + ux * along, from.Z + uz * along);
    }
    private static double MinDistance(P2 p, IReadOnlyList<WallSegment> segments)
    {
        double best = double.PositiveInfinity;
        foreach (var s in segments)
        {
            var c = ClosestOn(p, s);
            best = Math.Min(best, double.Hypot(p.X - c.X, p.Z - c.Z));
        }
        return best;
    }
    private static P2 PushOut(P2 start, IReadOnlyList<WallSegment> segments, double radius, P2 hint)
    {
        var p = start;
        for (int pass = 0; pass < PushPasses; pass++)
        {
            bool moved = false;
            foreach (var s in segments)
            {
                var c = ClosestOn(p, s);
                double dx = p.X - c.X, dz = p.Z - c.Z, d = double.Hypot(dx, dz);
                if (d >= radius - Eps) continue;
                double nx, nz;
                if (d > Eps) { nx = dx / d; nz = dz / d; }
                else
                {
                    double ux = s.Bx - s.Ax, uz = s.Bz - s.Az, len = double.Hypot(ux, uz);
                    if (len == 0) len = 1;
                    nx = uz / len; nz = -ux / len;
                    if ((hint.X - c.X) * nx + (hint.Z - c.Z) * nz < 0) { nx = -nx; nz = -nz; }
                }
                p = new(c.X + nx * radius, c.Z + nz * radius);
                moved = true;
            }
            if (!moved) break;
        }
        return p;
    }

    /// <summary>Try the pushed goal, plain slide, then origin; guard both the origin lift and each candidate against tunnelling.</summary>
    public static P2 ClampAgainstWalls(P2 from, P2 to, IReadOnlyList<WallSegment> segments, double radius)
    {
        if (segments.Count == 0) return to;
        double fromClear = MinDistance(from, segments);
        var lifted = PushOut(from, segments, radius, to);
        var basis = FirstCrossed(from, lifted, segments) is null
            && MinDistance(lifted, segments) >= Math.Min(radius, fromClear) - ClearTol ? lifted : from;
        double need = Math.Min(radius, MinDistance(basis, segments));
        var slid = to;
        for (int pass = 0; pass < 2; pass++)
        {
            var hit = FirstCrossed(basis, slid, segments);
            if (hit is null) break;
            slid = SlideAlong(basis, slid, hit.Value);
        }
        foreach (var candidate in new[] { PushOut(slid, segments, radius, basis), slid, basis })
        {
            if (FirstCrossed(basis, candidate, segments) is not null) continue;
            if (MinDistance(candidate, segments) < need - ClearTol) continue;
            return candidate;
        }
        return basis;
    }
}
