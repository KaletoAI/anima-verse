using System;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>
/// The three.js vector / quaternion / matrix operations the secondary motion uses (packages/scene-render/src/
/// secondaryMotion.ts), on the core's double-precision <see cref="V3"/>, <see cref="Quat"/> and <see cref="Affine"/>,
/// with three's exact edge rules (normalize of a zero vector, <c>setFromUnitVectors</c> of opposite vectors,
/// <c>slerp</c>'s small-angle lerp, <c>invert</c> of a singular matrix). Every matrix three builds there is affine, so a
/// 3 × 4 <see cref="Affine"/> carries it exactly.
/// </summary>
public static class MotionMath
{
    public static double Dot(this V3 a, V3 b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
    public static V3 Cross(this V3 a, V3 b) => new(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);
    public static double LengthSq(this V3 v) => v.X * v.X + v.Y * v.Y + v.Z * v.Z;
    public static double Length(this V3 v) => Math.Sqrt(v.LengthSq());

    /// <summary>three <c>normalize()</c>: divide by the length, a zero vector stays zero.</summary>
    public static V3 Normalized(this V3 v)
    {
        double l = v.Length();
        return l == 0 ? v : v * (1 / l);
    }

    public static double DistanceTo(this V3 a, V3 b) => (a - b).Length();
    public static double DistanceToSquared(this V3 a, V3 b) => (a - b).LengthSq();

    /// <summary>three <c>Vector3.angleTo</c>: π/2 for a zero vector.</summary>
    public static double AngleTo(this V3 a, V3 b)
    {
        double d = Math.Sqrt(a.LengthSq() * b.LengthSq());
        if (d == 0) return Math.PI / 2;
        return Math.Acos(Math.Clamp(a.Dot(b) / d, -1, 1));
    }

    /// <summary>three <c>clampLength(min, max)</c>.</summary>
    public static V3 ClampLength(this V3 v, double min, double max)
    {
        double l = v.Length();
        double d = l == 0 ? 1 : l;
        return v * (1 / d) * Math.Max(min, Math.Min(max, l));
    }

    public static V3 Lerp(this V3 a, V3 b, double t) => new(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t, a.Z + (b.Z - a.Z) * t);

    public static double Component(this V3 v, int i) => i switch { 0 => v.X, 1 => v.Y, _ => v.Z };

    /// <summary>three <c>applyMatrix4</c> of an affine matrix (w = 1).</summary>
    public static V3 Apply(this Affine m, V3 p)
        => new(m.Xx * p.X + m.Yx * p.Y + m.Zx * p.Z + m.Ox, m.Xy * p.X + m.Yy * p.Y + m.Zy * p.Z + m.Oy,
               m.Xz * p.X + m.Yz * p.Y + m.Zz * p.Z + m.Oz);

    /// <summary>The linear part only (a direction).</summary>
    public static V3 ApplyLinear(this Affine m, V3 d)
        => new(m.Xx * d.X + m.Yx * d.Y + m.Zx * d.Z, m.Xy * d.X + m.Yy * d.Y + m.Zy * d.Z, m.Xz * d.X + m.Yz * d.Y + m.Zz * d.Z);

    /// <summary>three <c>transformDirection(m)</c>: the linear part, normalised.</summary>
    public static V3 TransformDirection(this V3 d, Affine m) => m.ApplyLinear(d).Normalized();

    /// <summary>three <c>applyAxisAngle(axis, angle)</c>.</summary>
    public static V3 ApplyAxisAngle(this V3 v, V3 axis, double angle) => Quat.FromAxisAngle(axis, angle).Rotate(v);

    public static V3 Position(this Affine m) => new(m.Ox, m.Oy, m.Oz);
    public static Affine WithPosition(this Affine m, V3 p) => m with { Ox = p.X, Oy = p.Y, Oz = p.Z };

    /// <summary><c>a.multiply(b)</c> = a · b.</summary>
    public static Affine Mul(this Affine a, Affine b) => a.Times(b);

    /// <summary>three <c>Matrix4.invert()</c> (zero matrix when singular).</summary>
    public static Affine Inverted(this Affine m) => RigMath.Inverse(m);

    public static Affine RotationOf(Quat q) => RigMath.Compose(V3.Zero, q, new V3(1, 1, 1));
    public static Affine TranslationOf(V3 t) => Affine.Translation(t.X, t.Y, t.Z);

    /// <summary>A pure 3 × 3 linear map from its elements m[row, col].</summary>
    public static Affine Linear(double[,] m)
        => new(m[0, 0], m[1, 0], m[2, 0], m[0, 1], m[1, 1], m[2, 1], m[0, 2], m[1, 2], m[2, 2], 0, 0, 0);

    /// <summary>three's column-major <c>Matrix4.elements</c> (16 numbers, last row 0 0 0 1).</summary>
    public static double[] Elements(this Affine m)
        => new[] { m.Xx, m.Xy, m.Xz, 0, m.Yx, m.Yy, m.Yz, 0, m.Zx, m.Zy, m.Zz, 0, m.Ox, m.Oy, m.Oz, 1 };

    public static Affine FromElements(double[] e)
        => new(e[0], e[1], e[2], e[4], e[5], e[6], e[8], e[9], e[10], e[12], e[13], e[14]);

    // ---- quaternions ----------------------------------------------------------------------------------------------

    public static double Dot(this Quat a, Quat b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z + a.W * b.W;

    /// <summary>three <c>Quaternion.normalize()</c>: a zero quaternion becomes the identity.</summary>
    public static Quat ThreeNormalized(this Quat q)
    {
        double l = Math.Sqrt(q.Dot(q));
        if (l == 0) return Quat.Identity;
        l = 1 / l;
        return new Quat(q.X * l, q.Y * l, q.Z * l, q.W * l);
    }

    /// <summary>three <c>setFromUnitVectors(from, to)</c> (both assumed normalised).</summary>
    public static Quat FromUnitVectors(V3 from, V3 to)
    {
        double r = from.Dot(to) + 1;
        Quat q;
        if (r < 1e-8)
            q = Math.Abs(from.X) > Math.Abs(from.Z) ? new Quat(-from.Y, from.X, 0, 0) : new Quat(0, -from.Z, from.Y, 0);
        else
            q = new Quat(from.Y * to.Z - from.Z * to.Y, from.Z * to.X - from.X * to.Z, from.X * to.Y - from.Y * to.X, r);
        return q.ThreeNormalized();
    }

    /// <summary>three <c>Quaternion.angleTo</c>.</summary>
    public static double AngleTo(this Quat a, Quat b) => 2 * Math.Acos(Math.Abs(Math.Clamp(a.Dot(b), -1, 1)));

    /// <summary>three <c>Quaternion.slerp(qb, t)</c> (r185: lerp + normalize above dot 0.9995).</summary>
    public static Quat Slerp(this Quat a, Quat b, double t)
    {
        double x = b.X, y = b.Y, z = b.Z, w = b.W;
        double dot = a.Dot(b);
        if (dot < 0)
        {
            x = -x; y = -y; z = -z; w = -w;
            dot = -dot;
        }
        double s = 1 - t;
        if (dot < 0.9995)
        {
            double theta = Math.Acos(dot), sin = Math.Sin(theta);
            s = Math.Sin(s * theta) / sin;
            t = Math.Sin(t * theta) / sin;
            return new Quat(a.X * s + x * t, a.Y * s + y * t, a.Z * s + z * t, a.W * s + w * t);
        }
        return new Quat(a.X * s + x * t, a.Y * s + y * t, a.Z * s + z * t, a.W * s + w * t).ThreeNormalized();
    }
}
