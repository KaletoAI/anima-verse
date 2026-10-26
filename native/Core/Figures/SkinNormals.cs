using System;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>
/// Skinned normals under non-uniform bone scale (packages/scene-render/src/skinnedNormals.ts).
///
/// Godot 4.7.2's skinning compute shader (servers/rendering/renderer_rd/shaders/skeleton.glsl) does
/// <c>normal = normalize((vec4(normal, 0.0) * m).xyz)</c> — the blended skin matrix itself; three's stock chunk does the
/// same and the browser patches it to <c>inverse(transpose(mat3(skinMatrix)))</c>. The secondary motion scales bones
/// non-uniformly (girth, length, squash, flatten), so the stock normal tilts towards the stretched axis.
///
/// The native fix runs in the figure's vertex shader, AFTER Godot's skinning: it gets the stock normal
/// n' = normalize(M n) and the same blended M (per-bind linear parts as a uniform, the vertex's BONE_INDICES/WEIGHTS),
/// and since n ∝ M⁻¹ n', the browser's M⁻ᵀ n ∝ M⁻ᵀ M⁻¹ n' = (M Mᵀ)⁻¹ n' (<see cref="Correct"/>). (M Mᵀ)⁻¹ is
/// symmetric positive definite, so the corrected normal never flips to the other side of the surface.
/// </summary>
public static class SkinNormals
{
    /// <summary>Godot's (and stock three's) skinned normal: normalize(M n).</summary>
    public static V3 Stock(Affine m, V3 n) => m.ApplyLinear(n).Normalized();

    /// <summary>The browser's skinned normal: normalize(M⁻ᵀ n).</summary>
    public static V3 Browser(Affine m, V3 n)
    {
        var inv = m.Inverted();
        // (M⁻¹)ᵀ n: row i of M⁻¹ᵀ is column i of M⁻¹.
        return new V3(inv.Xx * n.X + inv.Xy * n.Y + inv.Xz * n.Z,
                      inv.Yx * n.X + inv.Yy * n.Y + inv.Yz * n.Z,
                      inv.Zx * n.X + inv.Zy * n.Y + inv.Zz * n.Z).Normalized();
    }

    /// <summary>The native shader's step: from the stock normal to the browser's, normalize((M Mᵀ)⁻¹ n').</summary>
    public static V3 Correct(Affine m, V3 stock)
    {
        var l = m with { Ox = 0, Oy = 0, Oz = 0 };
        var mmt = l.Times(Transpose(l));
        return mmt.Inverted().ApplyLinear(stock).Normalized();
    }

    public static Affine Transpose(Affine m)
        => new(m.Xx, m.Yx, m.Zx, m.Xy, m.Yy, m.Zy, m.Xz, m.Yz, m.Zz, 0, 0, 0);

    /// <summary>The angle between the stock and the browser normal of <paramref name="n"/>, degrees.</summary>
    public static double ErrorDeg(Affine m, V3 n) => Stock(m, n).AngleTo(Browser(m, n)) * 180 / Math.PI;

    /// <summary>
    /// The largest stock error over all normals: 2·atan(σmax/σmin) − 90° for the singular values of M (in the plane of
    /// the extreme singular vectors, a normal at 45° to both is turned towards the stretched axis by that much; any
    /// other direction less). Uniform scale or rotation: 0.
    /// </summary>
    public static double MaxErrorDeg(Affine m)
    {
        var (lo, hi) = SingularRange(m);
        if (lo <= 0) return 90;
        return (2 * Math.Atan(hi / lo) - Math.PI / 2) * 180 / Math.PI;
    }

    /// <summary>The smallest and largest singular value of the linear part (eigenvalues of MᵀM by Jacobi sweeps).</summary>
    public static (double Min, double Max) SingularRange(Affine m)
    {
        var l = m with { Ox = 0, Oy = 0, Oz = 0 };
        var t = Transpose(l).Times(l);
        double[,] a =
        {
            { t.Xx, t.Yx, t.Zx },
            { t.Xy, t.Yy, t.Zy },
            { t.Xz, t.Yz, t.Zz },
        };
        for (int sweep = 0; sweep < 50; sweep++)
        {
            double off = a[0, 1] * a[0, 1] + a[0, 2] * a[0, 2] + a[1, 2] * a[1, 2];
            if (off < 1e-30) break;
            for (int p = 0; p < 2; p++)
                for (int q = p + 1; q < 3; q++)
                {
                    if (Math.Abs(a[p, q]) < 1e-300) continue;
                    double theta = (a[q, q] - a[p, p]) / (2 * a[p, q]);
                    double tt = Math.Sign(theta == 0 ? 1 : theta) / (Math.Abs(theta) + Math.Sqrt(theta * theta + 1));
                    double c = 1 / Math.Sqrt(tt * tt + 1), s = tt * c;
                    for (int k = 0; k < 3; k++)
                    {
                        double akp = a[k, p], akq = a[k, q];
                        a[k, p] = c * akp - s * akq;
                        a[k, q] = s * akp + c * akq;
                    }
                    for (int k = 0; k < 3; k++)
                    {
                        double apk = a[p, k], aqk = a[q, k];
                        a[p, k] = c * apk - s * aqk;
                        a[q, k] = s * apk + c * aqk;
                    }
                }
        }
        double e0 = Math.Max(0, a[0, 0]), e1 = Math.Max(0, a[1, 1]), e2 = Math.Max(0, a[2, 2]);
        return (Math.Sqrt(Math.Min(e0, Math.Min(e1, e2))), Math.Sqrt(Math.Max(e0, Math.Max(e1, e2))));
    }

    /// <summary>
    /// The per-bind linear parts as the shader's <c>uniform mat3 skin_linear[N]</c> array: Godot's std140 fill reads 9
    /// floats per mat3 as three COLUMNS (material_storage.cpp, TYPE_MAT3 arrays), so column-major here.
    /// </summary>
    public static float[] PackColumns(Affine[] skin, int capacity)
    {
        var data = new float[capacity * 9];
        for (int i = 0; i < capacity; i++)
        {
            var m = i < skin.Length ? skin[i] : Affine.Identity;
            data[i * 9 + 0] = (float)m.Xx; data[i * 9 + 1] = (float)m.Xy; data[i * 9 + 2] = (float)m.Xz;
            data[i * 9 + 3] = (float)m.Yx; data[i * 9 + 4] = (float)m.Yy; data[i * 9 + 5] = (float)m.Yz;
            data[i * 9 + 6] = (float)m.Zx; data[i * 9 + 7] = (float)m.Zy; data[i * 9 + 8] = (float)m.Zz;
        }
        return data;
    }
}
