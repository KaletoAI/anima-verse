using System;

namespace AnimaNative.Overview;

/// <summary>
/// A 3 × 4 affine transform (rotation/scale columns + origin), double precision: <c>p' = B·p + O</c>.
/// The core's stand-in for Godot's <c>Transform3D</c> (the scene converts at its edge).
/// </summary>
public readonly record struct Affine(
    double Xx, double Xy, double Xz,   // column X (the image of +X)
    double Yx, double Yy, double Yz,   // column Y
    double Zx, double Zy, double Zz,   // column Z
    double Ox, double Oy, double Oz)   // origin
{
    public static readonly Affine Identity = new(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0);

    public static Affine Translation(double x, double y, double z) => Identity with { Ox = x, Oy = y, Oz = z };

    /// <summary>Rotation by <paramref name="rad"/> about +Y (right-handed: +X turns towards −Z).</summary>
    public static Affine RotationY(double rad)
    {
        double c = Math.Cos(rad), s = Math.Sin(rad);
        return new Affine(c, 0, -s, 0, 1, 0, s, 0, c, 0, 0, 0);
    }

    public Vec3 Apply(double x, double y, double z)
        => new(Xx * x + Yx * y + Zx * z + Ox, Xy * x + Yy * y + Zy * z + Oy, Xz * x + Yz * y + Zz * z + Oz);

    /// <summary><c>this · other</c>: apply <paramref name="other"/> first.</summary>
    public Affine Times(Affine o)
    {
        var me = this;
        Vec3 Col(double x, double y, double z)
            => new(me.Xx * x + me.Yx * y + me.Zx * z, me.Xy * x + me.Yy * y + me.Zy * z, me.Xz * x + me.Yz * y + me.Zz * z);
        var cx = Col(o.Xx, o.Xy, o.Xz);
        var cy = Col(o.Yx, o.Yy, o.Yz);
        var cz = Col(o.Zx, o.Zy, o.Zz);
        var org = Apply(o.Ox, o.Oy, o.Oz);
        return new Affine(cx.X, cx.Y, cx.Z, cy.X, cy.Y, cy.Z, cz.X, cz.Y, cz.Z, org.X, org.Y, org.Z);
    }
}

/// <summary>
/// Ray tests of the scene picking — the parts of three.js <c>Raycaster</c> the native picks need:
/// a ray against a box (the coarse prefilter), a sphere (the figure prefilter) and triangles
/// (three's <c>Ray.intersectTriangle</c> with <c>backfaceCulling = false</c>, i.e. a DoubleSide mesh —
/// see the report for FrontSide). Rays start at <c>o</c> and run along <c>d</c> (any length; the answers are
/// ray parameters t, the hit is <c>o + t·d</c>), hits behind the origin do not count.
/// No shared vector (three.js is not a module of this repository); native/tests/RayMathTests.cs derives
/// every case by hand.
/// </summary>
public static class RayMath
{
    /// <summary>Slab test: the entry parameter (0 when the origin is inside), or null for a miss.</summary>
    public static double? RayBox(Vec3 o, Vec3 d, Vec3 min, Vec3 max)
    {
        double tmin = 0, tmax = double.PositiveInfinity;
        if (!Slab(o.X, d.X, min.X, max.X, ref tmin, ref tmax)) return null;
        if (!Slab(o.Y, d.Y, min.Y, max.Y, ref tmin, ref tmax)) return null;
        if (!Slab(o.Z, d.Z, min.Z, max.Z, ref tmin, ref tmax)) return null;
        return tmin;
    }

    private static bool Slab(double o, double d, double lo, double hi, ref double tmin, ref double tmax)
    {
        if (d == 0) return o >= lo && o <= hi;
        double t1 = (lo - o) / d, t2 = (hi - o) / d;
        if (t1 > t2) (t1, t2) = (t2, t1);
        tmin = Math.Max(tmin, t1);
        tmax = Math.Min(tmax, t2);
        return tmin <= tmax;
    }

    /// <summary>Does the ray meet the sphere (centre <paramref name="c"/>, radius <paramref name="r"/>) at t ≥ 0?</summary>
    public static bool RaySphere(Vec3 o, Vec3 d, Vec3 c, double r)
    {
        double ox = o.X - c.X, oy = o.Y - c.Y, oz = o.Z - c.Z;
        double a = d.X * d.X + d.Y * d.Y + d.Z * d.Z;
        if (a == 0) return false;
        double b = ox * d.X + oy * d.Y + oz * d.Z;   // half of the linear term
        double cc = ox * ox + oy * oy + oz * oz - r * r;
        if (cc <= 0) return true;                       // the origin is inside
        if (b > 0) return false;                        // outside and pointing away
        return b * b - a * cc >= 0;
    }

    /// <summary>
    /// Möller–Trumbore, both faces: the parameter t &gt; 0 of the hit with triangle (a, b, c), or null.
    /// A ray in the triangle's plane counts as a miss (three answers null there too).
    /// </summary>
    public static double? RayTriangle(Vec3 o, Vec3 d, Vec3 a, Vec3 b, Vec3 c)
        => RayTriangle(o.X, o.Y, o.Z, d.X, d.Y, d.Z, a.X, a.Y, a.Z, b.X, b.Y, b.Z, c.X, c.Y, c.Z);

    public static double? RayTriangle(double ox, double oy, double oz, double dx, double dy, double dz,
                                      double ax, double ay, double az, double bx, double by, double bz,
                                      double cx, double cy, double cz)
    {
        double e1x = bx - ax, e1y = by - ay, e1z = bz - az;
        double e2x = cx - ax, e2y = cy - ay, e2z = cz - az;
        double px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
        double det = e1x * px + e1y * py + e1z * pz;
        if (Math.Abs(det) < 1e-12) return null;
        double inv = 1 / det;
        double tx = ox - ax, ty = oy - ay, tz = oz - az;
        double u = (tx * px + ty * py + tz * pz) * inv;
        if (u < 0 || u > 1) return null;
        double qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
        double v = (dx * qx + dy * qy + dz * qz) * inv;
        if (v < 0 || u + v > 1) return null;
        double t = (e2x * qx + e2y * qy + e2z * qz) * inv;
        return t > 0 ? t : null;
    }

    /// <summary>
    /// The nearest hit over an indexed triangle list (<paramref name="xyz"/> = x, y, z per vertex; three
    /// indices per triangle): the smallest t, or null. The brute-force loop three.js runs over a mesh.
    /// </summary>
    public static double? NearestTriangle(Vec3 o, Vec3 d, ReadOnlySpan<float> xyz, ReadOnlySpan<int> indices)
    {
        double best = double.PositiveInfinity;
        for (int i = 0; i + 2 < indices.Length; i += 3)
        {
            int a = indices[i] * 3, b = indices[i + 1] * 3, c = indices[i + 2] * 3;
            var t = RayTriangle(o.X, o.Y, o.Z, d.X, d.Y, d.Z, xyz[a], xyz[a + 1], xyz[a + 2],
                                xyz[b], xyz[b + 1], xyz[b + 2], xyz[c], xyz[c + 1], xyz[c + 2]);
            if (t is double tt && tt < best) best = tt;
        }
        return double.IsPositiveInfinity(best) ? null : best;
    }
}

/// <summary>
/// Linear blend skinning on the CPU — what the GPU does to a skinned mesh, for the figure pick
/// (three.js <c>SkinnedMesh.raycast</c> skins every vertex it tests the same way):
/// <c>p = Σₖ wₖ · Mₖ · v</c> over the vertex's bone slots, with Mₖ the bind's skinning matrix
/// (Godot: /// <c>skeleton.GetBoneGlobalPose(bone) · skin.GetBindPose(bind)</c>, composed by the caller; the result is in
/// the mesh's own space, so the caller moves the RAY into that space instead of every vertex out of it).
/// Slots with weight 0 are skipped and the weights are used as stored (Godot normalises them at import) —
/// exactly the sum the skinning shader forms, so a vertex without any weight lands on the mesh origin there too.
/// </summary>
public static class Skinning
{
    /// <param name="rest">x, y, z per vertex (bind pose, mesh space)</param>
    /// <param name="bones">bind index per slot, <paramref name="slots"/> per vertex</param>
    /// <param name="weights">weight per slot</param>
    /// <param name="matrices">the skinning matrix per bind index</param>
    /// <param name="output">x, y, z per vertex, skinned</param>
    public static void Apply(ReadOnlySpan<float> rest, ReadOnlySpan<int> bones, ReadOnlySpan<float> weights, int slots,
                             ReadOnlySpan<Affine> matrices, Span<float> output)
    {
        int n = rest.Length / 3;
        for (int v = 0; v < n; v++)
        {
            double x = rest[v * 3], y = rest[v * 3 + 1], z = rest[v * 3 + 2];
            double sx = 0, sy = 0, sz = 0;
            for (int k = 0; k < slots; k++)
            {
                float w = weights[v * slots + k];
                if (w <= 0) continue;
                int b = bones[v * slots + k];
                if ((uint)b >= (uint)matrices.Length) continue;
                var p = matrices[b].Apply(x, y, z);
                sx += w * p.X;
                sy += w * p.Y;
                sz += w * p.Z;
            }
            output[v * 3] = (float)sx;
            output[v * 3 + 1] = (float)sy;
            output[v * 3 + 2] = (float)sz;
        }
    }
}
