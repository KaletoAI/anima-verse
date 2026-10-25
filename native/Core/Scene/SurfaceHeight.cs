using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Scene;

/// <summary>A model's baked walkable surface (spec-surface-height § 4/6): a lattice in the fixed model frame, cm over box_min.y.</summary>
public sealed record SceneSurface(double Step, P2 Origin, int Cols, int Rows, double?[] Values,
                                  Vec3 BoxMin, Vec3 BoxMax, Vec3 ExtentSnapped);

/// <summary>The placement numbers the sampling inverts; absent numbers are NaN (JS <c>undefined</c>).</summary>
public sealed record SurfacePlacement(P2 Anchor, double YawDeg, double BottomY, double MaxM, string Measure);

/// <summary>A placed surface with the terrain lift it carries now.</summary>
public sealed record PlacedSurface(string Id, SurfacePlacement Spec, SceneSurface Surface, double Lift, double Level, string RoomId);

/// <summary>
/// <c>surfaceHeightAt</c>/<c>highestSurfaceAt</c> (packages/scene-render/src/surface.ts) — the exact inverse
/// of <c>place()</c> into the lattice, bilinear, null outside or next to a null node. Checked against
/// shared/test-vectors/scene_models.json [H].
/// </summary>
public static class SurfaceHeight
{
    private static double ExtentOf(SceneSurface s, string measure)
        => measure == "xyz" ? Math.Max(s.ExtentSnapped.X, Math.Max(s.ExtentSnapped.Y, s.ExtentSnapped.Z))
                            : Math.Max(s.ExtentSnapped.X, s.ExtentSnapped.Z);

    /// <summary><c>surfaceScale</c>: <c>max_m</c> over the snapped extent.</summary>
    public static double Scale(SceneSurface s, SurfacePlacement spec) => Js.Or(spec.MaxM, 1) / Js.Or(ExtentOf(s, spec.Measure), 1);

    public static double? At(SceneSurface surface, SurfacePlacement spec, double x, double z, double lift = 0)
    {
        double s = Scale(surface, spec);
        double cx = (surface.BoxMin.X + surface.BoxMax.X) / 2, cz = (surface.BoxMin.Z + surface.BoxMax.Z) / 2;
        double qx = x - spec.Anchor.X, qz = z - spec.Anchor.Z;
        double th = Js.Or(spec.YawDeg, 0) * Math.PI / 180;
        double c = Math.Cos(th), sn = Math.Sin(th);
        double lx = qx * c - qz * sn, lz = qx * sn + qz * c;
        double u = (lx / s + cx - surface.Origin.X) / surface.Step;
        double v = (lz / s + cz - surface.Origin.Z) / surface.Step;
        int cols = surface.Cols, rows = surface.Rows;
        if (!(u >= 0 && u <= cols - 1 && v >= 0 && v <= rows - 1)) return null;
        int i0 = cols > 1 ? Math.Min((int)Math.Floor(u), cols - 2) : 0;
        int j0 = rows > 1 ? Math.Min((int)Math.Floor(v), rows - 2) : 0;
        double fu = u - i0, fv = v - j0;
        int i1 = Math.Min(i0 + 1, cols - 1), j1 = Math.Min(j0 + 1, rows - 1);
        double? Val(int k) => k >= 0 && k < surface.Values.Length ? surface.Values[k] : null;
        if (Val(j0 * cols + i0) is not { } a || Val(j0 * cols + i1) is not { } b
            || Val(j1 * cols + i0) is not { } cc || Val(j1 * cols + i1) is not { } d) return null;
        double top = a + (b - a) * fu, bot = cc + (d - cc) * fu;
        double val = top + (bot - top) * fv;
        return Js.Or(spec.BottomY, 0) + lift + (s * val) / 100;
    }

    /// <summary>The highest answering surface, each sampled with its OWN lift; null when none answers.</summary>
    public static double? Highest(IEnumerable<PlacedSurface> list, double x, double z)
    {
        double? best = null;
        foreach (var p in list)
        {
            var y = At(p.Surface, p.Spec, x, z, p.Lift);
            if (y is { } v && (best is null || v > best)) best = v;
        }
        return best;
    }
}
