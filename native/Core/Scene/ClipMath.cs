using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;

namespace AnimaNative.Scene;

/// <summary>
/// The CPU twin of the room clip and the area cutouts' fragment parity test (packages/scene-render/src/clipMath.ts),
/// including its half-open boundary rule and the inclusive padding distance; checked against
/// shared/test-vectors/scene_models.json [C].
/// </summary>
public static class ClipMath
{
    public const int ClipPointLimit = 64, CutoutPolygonLimit = 16;

    public static List<P2> ClipOutlinePoints(IReadOnlyList<P2>? outline) => (outline ?? Array.Empty<P2>()).Take(ClipPointLimit).ToList();

    public static List<List<P2>> CutoutPolygons(IEnumerable<IReadOnlyList<P2>>? outlines)
        => (outlines ?? Enumerable.Empty<IReadOnlyList<P2>>()).Select(ClipOutlinePoints).Where(p => p.Count >= 3)
            .Take(CutoutPolygonLimit).ToList();

    public static bool ClipPointInside(P2 point, IReadOnlyList<P2> outline)
    {
        bool inside = false;
        var prev = outline[^1];
        foreach (var cur in outline)
        {
            if ((cur.Z > point.Z) != (prev.Z > point.Z)
                && point.X < (prev.X - cur.X) * (point.Z - cur.Z) / (prev.Z - cur.Z) + cur.X) inside = !inside;
            prev = cur;
        }
        return inside;
    }

    /// <summary>The room clip keeps what is inside; an outline under 3 points clips nothing.</summary>
    public static bool ClipKeepsPoint(P2 point, IReadOnlyList<P2> outline)
    {
        var points = ClipOutlinePoints(outline);
        return points.Count < 3 || ClipPointInside(point, points);
    }

    /// <summary><c>cutoutPadding</c>: a declared positive finite padding (model metres) times the world scale, else 0.</summary>
    public static double CutoutPadding(double? declared, double maxWorldScale)
        => declared is { } d && double.IsFinite(d) && d > 0 ? d * maxWorldScale : 0;

    /// <summary><c>cutoutDiscardsPoint</c>: inside ANY polygon, or within <paramref name="padding"/> of one of its edges.</summary>
    public static bool CutoutDiscardsPoint(P2 point, IEnumerable<IReadOnlyList<P2>> outlines, double padding = 0, bool enabled = true)
    {
        if (!enabled) return false;
        foreach (var poly in CutoutPolygons(outlines))
        {
            if (ClipPointInside(point, poly)) return true;
            if (!(padding > 0)) continue;
            var prev = poly[^1];
            foreach (var cur in poly)
            {
                double dx = cur.X - prev.X, dz = cur.Z - prev.Z;
                double t = Math.Max(0, Math.Min(1, ((point.X - prev.X) * dx + (point.Z - prev.Z) * dz) / Math.Max(dx * dx + dz * dz, 1e-8)));
                double x = point.X - (prev.X + t * dx), z = point.Z - (prev.Z + t * dz);
                if (x * x + z * z <= padding * padding) return true;
                prev = cur;
            }
        }
        return false;
    }
}
