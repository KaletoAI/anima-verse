using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>A 3×3 rotation, row-major (<c>M[r, c]</c>), applied to column vectors.</summary>
public readonly record struct Mat3(double M00, double M01, double M02, double M10, double M11, double M12,
                                   double M20, double M21, double M22)
{
    public static readonly Mat3 Identity = new(1, 0, 0, 0, 1, 0, 0, 0, 1);

    public Vec3 Apply(Vec3 v) => new(M00 * v.X + M01 * v.Y + M02 * v.Z,
                                     M10 * v.X + M11 * v.Y + M12 * v.Z,
                                     M20 * v.X + M21 * v.Y + M22 * v.Z);

    public Mat3 Transpose() => new(M00, M10, M20, M01, M11, M21, M02, M12, M22);

    public static Mat3 operator *(Mat3 a, Mat3 b) => new(
        a.M00 * b.M00 + a.M01 * b.M10 + a.M02 * b.M20, a.M00 * b.M01 + a.M01 * b.M11 + a.M02 * b.M21, a.M00 * b.M02 + a.M01 * b.M12 + a.M02 * b.M22,
        a.M10 * b.M00 + a.M11 * b.M10 + a.M12 * b.M20, a.M10 * b.M01 + a.M11 * b.M11 + a.M12 * b.M21, a.M10 * b.M02 + a.M11 * b.M12 + a.M12 * b.M22,
        a.M20 * b.M00 + a.M21 * b.M10 + a.M22 * b.M20, a.M20 * b.M01 + a.M21 * b.M11 + a.M22 * b.M21, a.M20 * b.M02 + a.M21 * b.M12 + a.M22 * b.M22);

    public static Mat3 RotX(double a) => new(1, 0, 0, 0, Math.Cos(a), -Math.Sin(a), 0, Math.Sin(a), Math.Cos(a));
    public static Mat3 RotY(double a) => new(Math.Cos(a), 0, Math.Sin(a), 0, 1, 0, -Math.Sin(a), 0, Math.Cos(a));
    public static Mat3 RotZ(double a) => new(Math.Cos(a), -Math.Sin(a), 0, Math.Sin(a), Math.Cos(a), 0, 0, 0, 1);

    /// <summary>three's intrinsic 'XYZ' Euler (radians): Rx·Ry·Rz — a point turns about Z, then Y, then X.</summary>
    public static Mat3 EulerXyz(double x, double y, double z) => RotX(x) * RotY(y) * RotZ(z);

    /// <summary>three's 'YXZ' Euler (radians): Ry·Rx·Rz — the model orientation fix.</summary>
    public static Mat3 EulerYxz(double x, double y, double z) => RotY(y) * RotX(x) * RotZ(z);
}

/// <summary>Size, centre position and yaw of a wall box (<c>wallTransform</c>).</summary>
public readonly record struct WallXf(Vec3 Size, Vec3 Position, double Yaw);

/// <summary>The shape-plane rings of a plate and the turn that lays the plane into world XZ (<c>plateShape</c>).</summary>
public sealed record PlateShapeResult(bool Solid, double RotationX, P2[] Outline, P2[][] Holes);

/// <summary>A placeholder box: size, the offset that puts its origin at the bottom centre, and its bounds.</summary>
public readonly record struct PlaceholderBoxResult(Vec3 Size, Vec3 Offset, Vec3 Min, Vec3 Max);

/// <summary>
/// The Three-free primitive transforms of the contract (§ B1), a port of
/// packages/scene-render/src/primitiveMath.ts, checked against shared/test-vectors/scene_primitives.json.
/// Coordinates stay in payload-local metres.
/// </summary>
public static class PrimitiveMath
{
    /// <summary>
    /// <c>wallTransform</c>: box size (length, height, thickness), centre and the yaw −atan2(dz, dx) — under
    /// rotation.y = θ the box's +x axis points along (cos θ, 0, −sin θ), which must be the segment direction.
    /// </summary>
    public static WallXf WallTransform(SceneWall wall)
    {
        double dx = wall.To.X - wall.From.X, dz = wall.To.Z - wall.From.Z;
        return new WallXf(new Vec3(double.Hypot(dx, dz), wall.Height, wall.Thickness),
            new Vec3((wall.From.X + wall.To.X) / 2, wall.BaseY + wall.Height / 2, (wall.From.Z + wall.To.Z) / 2),
            -Math.Atan2(dz, dx));
    }

    /// <summary>three's BoxGeometry face order px, nx, py, ny, pz, nz: the metres each face's u and v span.</summary>
    public static (double U, double V)[] BoxFaceExtents(double width, double height, double depth)
        => new[] { (depth, height), (depth, height), (width, depth), (width, depth), (width, height), (width, height) };

    /// <summary><c>boxFaceUVs</c>: each face's own extent over the tile size; no texture keeps 0..1 (1, 1).</summary>
    public static (double U, double V)[] BoxFaceUVs(double width, double height, double depth, double tileM)
        => BoxFaceExtents(width, height, depth).Select(f => tileM > 0 ? (f.U / tileM, f.V / tileM) : (1.0, 1.0)).ToArray();

    /// <summary><c>extraRotation</c>: the XYZ Euler of an extra in radians, (0, 0, 0) without one.</summary>
    public static Vec3 ExtraRotation(SceneExtra extra)
    {
        const double d = Math.PI / 180;
        if (extra.Rotation is not { } r) return new Vec3(0, 0, 0);
        double At(int i) => i < r.Length ? r[i] : double.NaN;
        return new Vec3(At(0) * d, At(1) * d, At(2) * d);
    }

    /// <summary>The extra's rotation as a matrix: three's intrinsic XYZ = Rx·Ry·Rz.</summary>
    public static Mat3 ExtraMatrix(SceneExtra extra)
    {
        var r = ExtraRotation(extra);
        return Mat3.EulerXyz(r.X, r.Y, r.Z);
    }

    /// <summary>
    /// <c>extraCorners</c>: the given local points (default: the 8 corners, x low/high, then y, then z) turned
    /// by the XYZ Euler (a point turns Z, then Y, then X) and moved to the centre — through
    /// <see cref="ExtraMatrix"/>, the very matrix the renderer turns the box by, so the vectors pin it.
    /// </summary>
    public static List<Vec3> ExtraCorners(SceneExtra extra, IReadOnlyList<Vec3>? points = null)
    {
        var m = ExtraMatrix(extra);
        var local = points ?? (from x in new[] { -1, 1 } from y in new[] { -1, 1 } from z in new[] { -1, 1 }
                               select new Vec3(x * extra.Size[0] / 2, y * extra.Size[1] / 2, z * extra.Size[2] / 2)).ToList();
        return local.Select(p =>
        {
            var r = m.Apply(p);
            return new Vec3(r.X + extra.Center[0], r.Y + extra.Center[1], r.Z + extra.Center[2]);
        }).ToList();
    }

    /// <summary>
    /// <c>plateShape</c>: a body (thickness &gt; 0) keeps (x, z) and turns +90° about x (the extrusion then runs
    /// downward), a bare face mirrors to (x, −z) and turns −90° — outline AND holes; a ring under 3 points is dropped.
    /// </summary>
    public static PlateShapeResult PlateShape(ScenePlate plate)
    {
        bool solid = plate.Thickness > 0;
        P2[] Ring(IEnumerable<(double X, double Z)> pts) => pts.Select(p => new P2(p.X, solid ? p.Z : -p.Z)).ToArray();
        return new PlateShapeResult(solid, solid ? Math.PI / 2 : -Math.PI / 2, Ring(plate.Outline),
            plate.Holes.Where(h => h.Length >= 3).Select(Ring).ToArray());
    }

    /// <summary><c>placeholderBox</c>: each dimension at least 1 cm, origin at the bottom face's centre.</summary>
    public static PlaceholderBoxResult PlaceholderBox(double w, double d, double h)
    {
        w = JsMax(w, 0.01); h = JsMax(h, 0.01); d = JsMax(d, 0.01);
        return new PlaceholderBoxResult(new Vec3(w, h, d), new Vec3(0, h / 2, 0), new Vec3(-w / 2, 0, -d / 2), new Vec3(w / 2, h, d / 2));
    }

    private static double JsMax(double a, double b) => double.IsNaN(a) ? a : Math.Max(a, b);
}
