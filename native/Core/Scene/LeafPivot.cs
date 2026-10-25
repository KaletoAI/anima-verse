using System;
using AnimaNative.Overview;

namespace AnimaNative.Scene;

/// <summary>An orientation fix in DEGREES as <c>fix_euler</c> carries it; an absent axis is null (= 0).</summary>
public readonly record struct FixDeg(double? X, double? Y, double? Z);

/// <summary>A door leaf's hinge: pivot point and unit axis in RAW model space.</summary>
public readonly record struct LeafPivotSpec(Vec3 Point, Vec3 Axis);

/// <summary>
/// The DOOR LEAF's hinge pivot (ruling R13), a port of packages/scene-render/src/leafPivot.ts, checked
/// against shared/test-vectors/scene_models.json [L]. Rule stated in the FIXED frame (min x, min y, centre z
/// of the turned leaf box), mapped back with R⁻¹ = Rᵀ; the axis is Rᵀ·(0, 1, 0).
/// </summary>
public static class LeafPivot
{
    private static double Deg(double? v) => (v is { } d && d != 0 && !double.IsNaN(d) ? d : 0) * Math.PI / 180;

    /// <summary>R = Ry · Rx · Rz for the fix (three's Euler 'YXZ', degrees) — the same matrix <c>place()</c> turns by.</summary>
    public static Mat3 FixMatrix(FixDeg? fix)
    {
        double a = Math.Cos(Deg(fix?.X)), b = Math.Sin(Deg(fix?.X));
        double c = Math.Cos(Deg(fix?.Y)), d = Math.Sin(Deg(fix?.Y));
        double e = Math.Cos(Deg(fix?.Z)), f = Math.Sin(Deg(fix?.Z));
        return new Mat3(c * e + d * f * b, d * e * b - c * f, a * d,
                        a * f, a * e, -b,
                        c * f * b - d * e, d * f + c * e * b, a * c);
    }

    private static double Clean(double v) => Math.Abs(v) < 1e-12 ? 0 : v;

    public static LeafPivotSpec Compute(Vec3 min, Vec3 max, FixDeg? fix)
    {
        var r = FixMatrix(fix);
        var rt = r.Transpose();
        double minX = double.PositiveInfinity, minY = double.PositiveInfinity, minZ = double.PositiveInfinity, maxZ = double.NegativeInfinity;
        foreach (var x in new[] { min.X, max.X })
            foreach (var y in new[] { min.Y, max.Y })
                foreach (var z in new[] { min.Z, max.Z })
                {
                    var p = r.Apply(new Vec3(x, y, z));
                    if (p.X < minX) minX = p.X;
                    if (p.Y < minY) minY = p.Y;
                    if (p.Z < minZ) minZ = p.Z;
                    if (p.Z > maxZ) maxZ = p.Z;
                }
        var point = rt.Apply(new Vec3(minX, minY, (minZ + maxZ) / 2));
        var axis = rt.Apply(new Vec3(0, 1, 0));
        return new LeafPivotSpec(new Vec3(Clean(point.X), Clean(point.Y), Clean(point.Z)),
                                 new Vec3(Clean(axis.X), Clean(axis.Y), Clean(axis.Z)));
    }
}
