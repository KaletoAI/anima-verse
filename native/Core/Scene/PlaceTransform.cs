using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>One mesh's local AABB and its optional column-major (glTF) matrix into the unrotated source frame.</summary>
public sealed record MeshBox(Vec3 Min, Vec3 Max, double[]? Matrix = null);

/// <summary>What <see cref="PlaceTransform.Compute"/> answers: the four transforms of the § B2 chain.</summary>
public readonly record struct PlaceResult(Vec3 FixPos, Vec3 FitScale, double OuterScale, Vec3 OuterPos);

/// <summary>
/// THE placement arithmetic of the contract (§ B2), a port of <c>placeTransform</c>
/// (packages/scene-render/src/placeTransform.ts), checked against shared/test-vectors/scene_place.json:
///
///   outer (anchor/bottom_y, uniform scale)
///     └ yaw (rotation.y = +rad(yaw_deg), § A1.1 sign)
///         └ fit (non-uniform scale, <c>measure: "fit"</c> only)
///             └ fix (orientation fix, Euler YXZ = Ry·Rx·Rz, position = <see cref="PlaceResult.FixPos"/>)
///                 └ source
///
/// The measuring frame is the 8 corners of every mesh box (each through its own matrix), the object size is
/// measured under the fix ROUNDED to 90°, the seating datum under the exact fix.
/// </summary>
public static class PlaceTransform
{
    private static double Rad(double v) => (double.IsNaN(v) ? 0 : v) * Math.PI / 180;

    /// <summary>Euler YXZ: R_y R_x R_z, so roll acts first (radians).</summary>
    public static Vec3 Rotate(Vec3 p, double x, double y, double z)
    {
        double a = p.X * Math.Cos(z) - p.Y * Math.Sin(z);
        double b = p.X * Math.Sin(z) + p.Y * Math.Cos(z);
        double c = b * Math.Sin(x) + p.Z * Math.Cos(x);
        return new Vec3(a * Math.Cos(y) + c * Math.Sin(y), b * Math.Cos(x) - p.Z * Math.Sin(x), -a * Math.Sin(y) + c * Math.Cos(y));
    }

    private readonly record struct Bounds(Vec3 Min, Vec3 Size, Vec3 Centre);

    private static Bounds Measure(IReadOnlyList<Vec3> ps)
    {
        double[] min = { double.PositiveInfinity, double.PositiveInfinity, double.PositiveInfinity };
        double[] max = { double.NegativeInfinity, double.NegativeInfinity, double.NegativeInfinity };
        foreach (var p in ps)
        {
            double[] v = { p.X, p.Y, p.Z };
            for (int i = 0; i < 3; i++) { min[i] = Math.Min(min[i], v[i]); max[i] = Math.Max(max[i], v[i]); }
        }
        bool any = ps.Count > 0;
        return new Bounds(new Vec3(min[0], min[1], min[2]),
            any ? new Vec3(max[0] - min[0], max[1] - min[1], max[2] - min[2]) : new Vec3(0, 0, 0),
            any ? new Vec3((max[0] + min[0]) / 2, (max[1] + min[1]) / 2, (max[2] + min[2]) / 2) : new Vec3(0, 0, 0));
    }

    /// <summary>The 8 corners of every box, each through its matrix (homogeneous divide like three's applyMatrix4).</summary>
    public static List<Vec3> Corners(IEnumerable<MeshBox> boxes)
    {
        var points = new List<Vec3>();
        foreach (var box in boxes)
            foreach (var x in new[] { box.Min.X, box.Max.X })
                foreach (var y in new[] { box.Min.Y, box.Max.Y })
                    foreach (var z in new[] { box.Min.Z, box.Max.Z })
                    {
                        var m = box.Matrix;
                        if (m is null) { points.Add(new Vec3(x, y, z)); continue; }
                        double w = 1 / (m[3] * x + m[7] * y + m[11] * z + m[15]);
                        points.Add(new Vec3((m[0] * x + m[4] * y + m[8] * z + m[12]) * w,
                                            (m[1] * x + m[5] * y + m[9] * z + m[13]) * w,
                                            (m[2] * x + m[6] * y + m[10] * z + m[14]) * w));
                    }
        return points;
    }

    public static PlaceResult Compute(SceneModelSpec spec, IReadOnlyList<MeshBox> meshBoxes)
    {
        var points = Corners(meshBoxes);
        // JS Math.round: a tie (±45°) goes towards +∞, like the browser.
        double SnapJs(double v) => Rad(JsRound(Js.Or(v, 0) / 90) * 90);
        var snapped = (X: SnapJs(spec.FixX), Y: SnapJs(spec.FixY), Z: SnapJs(spec.FixZ));
        var actual = (X: Rad(spec.FixX), Y: Rad(spec.FixY), Z: Rad(spec.FixZ));
        var sObj = Measure(points.Select(p => Rotate(p, snapped.X, snapped.Y, snapped.Z)).ToList()).Size;
        double yaw = Rad(spec.YawDeg);
        var sYaw = Measure(points.Select(p => Rotate(Rotate(p, snapped.X, snapped.Y, snapped.Z), 0, yaw, 0)).ToList()).Size;
        var fixedPts = points.Select(p => Rotate(p, actual.X, actual.Y, actual.Z)).ToList();
        var b = Measure(fixedPts);
        bool fit = spec.Measure == "fit";
        var fixPos = new Vec3(fit ? -b.Min.X : -b.Centre.X, fit ? -b.Min.Y : -b.Centre.Y, -b.Centre.Z);
        double sizeW = spec.SizeM is { Length: >= 1 } s0 ? s0[0] : double.NaN;
        double sizeH = spec.SizeM is { Length: >= 2 } s1 ? s1[1] : double.NaN;
        double sx = Js.Or(sizeW, 1) / Js.Or(sObj.X, 1);
        var fitScale = fit ? new Vec3(sx, Js.Or(sizeH, 1) / Js.Or(sObj.Y, 1), sx) : new Vec3(1, 1, 1);
        double extent = Js.Or(spec.Measure == "yawed_xz" ? Math.Max(sYaw.X, sYaw.Z)
            : spec.Measure == "xz" ? Math.Max(sObj.X, sObj.Z)
            : Math.Max(sObj.X, Math.Max(sObj.Y, sObj.Z)), 1);
        double outerScale = fit ? 1 : Js.Or(spec.MaxM, 1) / extent;
        var bottom = Measure(fixedPts.Select(p =>
        {
            var q = Rotate(new Vec3((p.X + fixPos.X) * fitScale.X, (p.Y + fixPos.Y) * fitScale.Y, (p.Z + fixPos.Z) * fitScale.Z), 0, yaw, 0);
            return new Vec3(q.X * outerScale, q.Y * outerScale, q.Z * outerScale);
        }).ToList()).Min.Y;
        return new PlaceResult(fixPos, fitScale, outerScale, new Vec3(spec.AnchorX, spec.BottomY - bottom, spec.AnchorZ));
    }

    /// <summary>JS <c>Math.round</c>.</summary>
    internal static double JsRound(double x) => JsSemantics.Round(x);
}
