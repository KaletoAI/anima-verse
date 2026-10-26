using System;

namespace AnimaNative.Sky;

/// <summary>The light's view basis (<c>lightBasis</c>): unit x, y and z (z = towards the light).</summary>
public readonly record struct LightBasis((double X, double Y, double Z) X, (double X, double Y, double Z) Y,
                                         (double X, double Y, double Z) Z);

/// <summary>
/// The texel-snapped shadow centre of the browser's sun (<c>client3d/src/scene/shadowSnap.ts</c>): the orthographic
/// shadow box of ±70 m at 2048² follows the camera target, its centre rounded to whole shadow texels in the light's
/// plane so the shadow edges do not crawl. Depth is not snapped.
/// </summary>
public static class ShadowSnap
{
    /// <summary><c>SHADOW_HALF_M</c> / <c>SHADOW_MAP_PX</c>.</summary>
    public const double HalfM = 70;
    public const int MapPx = 2048;

    /// <summary><c>shadowTexelM</c>: the box's world width over the map's pixels; no pixels = 0.</summary>
    public static double TexelM(double halfM = HalfM, double mapPx = MapPx)
        => !(mapPx > 0) ? 0 : 2 * halfM / mapPx;

    private static double Dot((double X, double Y, double Z) a, (double X, double Y, double Z) b)
        => a.X * b.X + a.Y * b.Y + a.Z * b.Z;

    private static (double X, double Y, double Z) Cross((double X, double Y, double Z) a, (double X, double Y, double Z) b)
        => (a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);

    private static double Hypot((double X, double Y, double Z) v) => Math.Sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z);

    private static (double X, double Y, double Z) Normalize((double X, double Y, double Z) v)
    {
        double len = Hypot(v);
        return !(len > 0) ? (0, 0, 1) : (v.X / len, v.Y / len, v.Z / len);
    }

    /// <summary><c>lightBasis(offset)</c>: three's <c>lookAt</c> written out; straight overhead falls back to +Z as up.</summary>
    public static LightBasis Basis((double X, double Y, double Z) offset)
    {
        var z = Normalize(offset);
        var x = Cross((0, 1, 0), z);
        if (Hypot(x) < 1e-3) x = Cross((0, 0, 1), z);
        var xn = Normalize(x);
        return new LightBasis(xn, Cross(z, xn), z);
    }

    /// <summary><c>snapShadowCentre</c>: the target moved in the light plane onto the nearest whole texel (JS round).</summary>
    public static (double X, double Y, double Z) SnapCentre((double X, double Y, double Z) target,
                                                           (double X, double Y, double Z) offset,
                                                           double halfM = HalfM, double mapPx = MapPx)
    {
        double texel = TexelM(halfM, mapPx);
        if (!(texel > 0)) return target;
        var b = Basis(offset);
        double u = Dot(target, b.X), v = Dot(target, b.Y);
        double du = Scatter.Js.Round(u / texel) * texel - u;
        double dv = Scatter.Js.Round(v / texel) * texel - v;
        return (target.X + du * b.X.X + dv * b.Y.X,
                target.Y + du * b.X.Y + dv * b.Y.Y,
                target.Z + du * b.X.Z + dv * b.Y.Z);
    }
}
