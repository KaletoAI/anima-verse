using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;

namespace AnimaNative.Water;

/// <summary>
/// Water surfaces inside props and dioramas (scene payload v18, § B2 <c>water.regions[]</c>) — the pure half of
/// <c>client3d/src/scene/propWaterMath.ts</c> (<c>pointInRegion</c>, <c>waterRegionAt</c>, checked against
/// <c>shared/test-vectors/prop_water.json</c>) and of <c>packages/scene-render/src/propWater.ts</c>
/// (<c>buildPropWater</c>: one flat sheet per region at <c>y + lift</c>, the shared surface water look, still water).
/// </summary>
public static class PropWater
{
    /// <summary>The ring test of <c>propWaterMath.ts</c>: even-odd crossing, and a point ON a segment (1e-9) is inside —
    /// for an outline AND for a hole (so a hole's boundary is dry).</summary>
    public static bool PointInRing(double x, double z, IReadOnlyList<P2> ring)
    {
        bool inside = false;
        int n = ring.Count;
        for (int i = 0; i < n; i++)
        {
            var (ax, az) = (ring[i].X, ring[i].Z);
            var (bx, bz) = (ring[(i + n - 1) % n].X, ring[(i + n - 1) % n].Z);
            double cross = (x - ax) * (bz - az) - (z - az) * (bx - ax);
            if (Math.Abs(cross) < 1e-9 && x >= Math.Min(ax, bx) - 1e-9 && x <= Math.Max(ax, bx) + 1e-9
                && z >= Math.Min(az, bz) - 1e-9 && z <= Math.Max(az, bz) + 1e-9) return true;
            if ((az > z) != (bz > z) && x < (bx - ax) * (z - az) / (bz - az) + ax) inside = !inside;
        }
        return inside;
    }

    /// <summary><c>pointInRegion(region, x, z)</c>: inside the outline and in none of its holes.</summary>
    public static bool PointInRegion(SceneWaterRegion region, double x, double z)
        => PointInRing(x, z, region.Outline) && !region.Holes.Any(h => PointInRing(x, z, h));

    /// <summary>
    /// <c>waterRegionAt(specs, x, z, liftOf)</c>: the HIGHEST mirror over (x, z) among every region of every spec (a tie
    /// keeps the first), with the spec's lift added to the mirror and the bed; null where no region covers the point.
    /// The caller selects the storey and the frame, as for the baked surfaces.
    /// </summary>
    public static WaterHit? WaterRegionAt(IEnumerable<SceneModelSpec> specs, double x, double z,
                                          Func<SceneModelSpec, double>? liftOf = null)
    {
        WaterHit? best = null;
        foreach (var spec in specs)
            foreach (var region in spec.Water)
            {
                if (!PointInRegion(region, x, z)) continue;
                double lift = liftOf?.Invoke(spec) ?? 0;
                double y = region.Y + lift;
                if (best is not { } b || y > b.Y) best = new WaterHit(y, region.BedY + lift, region.SwimFromM);
            }
        return best;
    }

    /// <summary>
    /// The sheet of one region in its parent's frame (<c>buildPropWater</c>: <c>ShapeGeometry</c> of (x, −z) turned −90°
    /// about x — the bare-face plate of the recipe, so the same triangulation), at y = 0; the caller stands it at
    /// <c>y + lift</c>. Empty when the outline does not triangulate.
    /// </summary>
    public static MeshData Sheet(SceneWaterRegion region)
        => RecipeGeometry.Plate(new ScenePlate(0, region.Outline.Select(p => (p.X, p.Z)).ToArray(),
                                               region.Holes.Select(h => h.Select(p => (p.X, p.Z)).ToArray()).ToArray(), 0, 0));

    /// <summary>
    /// The sheet's albedo in linear working space: <c>surfaceMaterial</c> sets the colour from the tint STRING (three's
    /// <c>Color(hex)</c>: sRGB decoded), and the water patch then mixes 25 % of <c>hex3(tint)</c> — the bytes / 255,
    /// used as they are — back in (<c>mix(uTint, diffuse, mix(1, map_strength 0.75, mask 1))</c>). A tint that is not
    /// <c>#rrggbb</c> is #3f7fb8 for both halves here (three would read a named CSS colour; the payload sends hex).
    /// </summary>
    public static (double R, double G, double B) Albedo(string? tint)
    {
        var raw = WaterShade.TintRgb(tint);
        static double Lin(double c) => c <= 0.04045 ? c * 0.0773993808 : Math.Pow(c * 0.9478672986 + 0.0521327014, 2.4);
        return (0.25 * raw.R + 0.75 * Lin(raw.R), 0.25 * raw.G + 0.75 * Lin(raw.G), 0.25 * raw.B + 0.75 * Lin(raw.B));
    }

    /// <summary>The surface look of a still water sheet (<c>surfaceFinish</c> for class water + the patch's defaults):
    /// roughness 0.08, metalness 0.15, wave 1.6 m, speed 0.05 m/s, sky share 0.55.</summary>
    public const double Roughness = 0.08, Metalness = 0.15, WaveM = 1.6, Speed = 0.05, SkyMix = 0.55;
}
