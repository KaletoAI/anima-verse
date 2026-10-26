using System;

namespace AnimaNative.Figures;

/// <summary>A double-precision 3-vector for pose data (three's <c>Vector3</c> semantics).</summary>
public readonly record struct V3(double X, double Y, double Z)
{
    public static readonly V3 Zero = new(0, 0, 0);
    public static V3 operator +(V3 a, V3 b) => new(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
    public static V3 operator -(V3 a, V3 b) => new(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
    public static V3 operator *(V3 a, double s) => new(a.X * s, a.Y * s, a.Z * s);
    public double[] ToArray() => new[] { X, Y, Z };
}

/// <summary>
/// A double-precision quaternion with three.js' conventions (<c>x, y, z, w</c>):
/// <c>a * b</c> is <c>a.multiply(b)</c> (b applied first), <see cref="Inverse"/> is
/// three's <c>invert()</c> (the conjugate — the operands are unit quaternions),
/// <see cref="Rotate"/> is <c>Vector3.applyQuaternion</c>.
/// </summary>
public readonly record struct Quat(double X, double Y, double Z, double W)
{
    public static readonly Quat Identity = new(0, 0, 0, 1);

    /// <summary>three <c>Quaternion.multiplyQuaternions(a, b)</c>.</summary>
    public static Quat operator *(Quat a, Quat b) => new(
        a.X * b.W + a.W * b.X + a.Y * b.Z - a.Z * b.Y,
        a.Y * b.W + a.W * b.Y + a.Z * b.X - a.X * b.Z,
        a.Z * b.W + a.W * b.Z + a.X * b.Y - a.Y * b.X,
        a.W * b.W - a.X * b.X - a.Y * b.Y - a.Z * b.Z);

    /// <summary>three <c>invert()</c>: the conjugate.</summary>
    public Quat Inverse() => new(-X, -Y, -Z, W);

    /// <summary>three <c>setFromAxisAngle(axis, angle)</c> (axis assumed normalised).</summary>
    public static Quat FromAxisAngle(V3 axis, double angle)
    {
        double half = angle / 2, s = Math.Sin(half);
        return new Quat(axis.X * s, axis.Y * s, axis.Z * s, Math.Cos(half));
    }

    /// <summary>three <c>Vector3.applyQuaternion(this)</c>.</summary>
    public V3 Rotate(V3 v)
    {
        double tx = 2 * (Y * v.Z - Z * v.Y), ty = 2 * (Z * v.X - X * v.Z), tz = 2 * (X * v.Y - Y * v.X);
        return new V3(v.X + W * tx + Y * tz - Z * ty, v.Y + W * ty + Z * tx - X * tz, v.Z + W * tz + X * ty - Y * tx);
    }

    public Quat Normalized()
    {
        double l = Math.Sqrt(X * X + Y * Y + Z * Z + W * W);
        return l == 0 ? Identity : new Quat(X / l, Y / l, Z / l, W / l);
    }

    public double[] ToArray() => new[] { X, Y, Z, W };
}
