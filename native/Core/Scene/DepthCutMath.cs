using System;
using AnimaNative.Overview;

namespace AnimaNative.Scene;

/// <summary>A world plane <c>normal · p + constant = 0</c>.</summary>
public readonly record struct CutPlaneData(Vec3 Normal, double Constant);

/// <summary>
/// <c>cutPlaneData</c> (packages/scene-render/src/depthCutMath.ts): the payload's cut plane, normal normalised,
/// carried into the world through a column-major frame matrix (normals by the inverse transpose = cofactors / det).
/// Checked against shared/test-vectors/scene_models.json [D].
/// </summary>
public static class DepthCutMath
{
    private static double Hypot3(double x, double y, double z) => Math.Sqrt(x * x + y * y + z * z);

    public static CutPlaneData? CutPlane(Vec3? normal, double constant, double[]? matrix = null)
    {
        if (normal is not { } nn) return null;
        double length = Hypot3(nn.X, nn.Y, nn.Z);
        if (length * length < 1e-9) return null;
        double[] n = { nn.X / length, nn.Y / length, nn.Z / length };
        if (matrix is null) return new CutPlaneData(new Vec3(n[0], n[1], n[2]), constant);
        var m = matrix;
        double[] c =
        {
            m[5] * m[10] - m[9] * m[6], m[9] * m[2] - m[1] * m[10], m[1] * m[6] - m[5] * m[2],
            m[8] * m[6] - m[4] * m[10], m[0] * m[10] - m[8] * m[2], m[4] * m[2] - m[0] * m[6],
            m[4] * m[9] - m[8] * m[5], m[8] * m[1] - m[0] * m[9], m[0] * m[5] - m[4] * m[1],
        };
        double det = m[0] * c[0] + m[4] * c[1] + m[8] * c[2];
        if (det == 0) return new CutPlaneData(new Vec3(0, 0, 0), 0);
        var w = new double[3];
        for (int i = 0; i < 3; i++) w[i] = (c[i * 3] * n[0] + c[i * 3 + 1] * n[1] + c[i * 3 + 2] * n[2]) / det;
        double l = Hypot3(w[0], w[1], w[2]);
        var normalW = new Vec3(w[0] / l, w[1] / l, w[2] / l);
        double[] p = { -constant * n[0], -constant * n[1], -constant * n[2] };
        var world = new double[3];
        for (int i = 0; i < 3; i++) world[i] = m[i] * p[0] + m[i + 4] * p[1] + m[i + 8] * p[2] + m[i + 12];
        return new CutPlaneData(normalW, -(normalW.X * world[0] + normalW.Y * world[1] + normalW.Z * world[2]));
    }
}
