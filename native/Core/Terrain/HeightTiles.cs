using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace AnimaNative.Terrain;

/// <summary>
/// Which fine tiles the client wants (<c>client3d/src/scene/heightTiles.ts</c>) and the tile key rule
/// (<c>tileKeyAt</c>, <c>packages/scene-render/src/worldHeight.ts</c>) — one want set for the height tiles and the
/// layer mask tiles, checked against <c>shared/test-vectors/height_tiles.json</c>.
/// </summary>
public static class HeightTiles
{
    /// <summary><c>HEIGHT_TILE_RADIUS_M</c> = <c>FOG_FAR_M</c> + 40: the load radius around the anchor.</summary>
    public const double RadiusM = Sky.Fog.FarM + 40;
    /// <summary><c>HEIGHT_TILE_CACHE_MAX</c>: how many tiles the LRU keeps (a wanted tile is never evicted).</summary>
    public const int CacheMax = 96;
    /// <summary><c>HEIGHT_TILE_BATCH_MAX</c>: keys per <c>/play/heightfield/tiles</c> request (the server's cap).</summary>
    public const int BatchMax = 64;
    private const int MaxTilesPerAxis = 64;

    /// <summary>
    /// <c>wantedTiles</c>: every INDEXED tile whose square comes within <paramref name="radiusM"/> of (x, z) — box
    /// distance, not the centre — nearest first, ties in ordinal key order; the key comes from <see cref="TileKeyAt"/>
    /// at the square's centre. No tile size, a negative radius, an empty index or more than 64 tiles per axis = none.
    /// </summary>
    public static List<string> WantedTiles(IReadOnlySet<string> index, double tileM, double x, double z,
                                           double radiusM = RadiusM)
    {
        var none = new List<string>();
        if (!(tileM > 0) || !(radiusM >= 0) || index.Count == 0) return none;
        if (!double.IsFinite(x) || !double.IsFinite(z)) return none;
        double firstX = Math.Floor((x - radiusM) / tileM), lastX = Math.Floor((x + radiusM) / tileM);
        double firstZ = Math.Floor((z - radiusM) / tileM), lastZ = Math.Floor((z + radiusM) / tileM);
        if (lastX - firstX > MaxTilesPerAxis || lastZ - firstZ > MaxTilesPerAxis) return none;
        double reach = radiusM * radiusM;
        var hits = new List<(string Key, double D2)>();
        for (double tz = firstZ; tz <= lastZ; tz += 1)
        {
            double dz = Math.Max(Math.Max(tz * tileM - z, 0), z - (tz + 1) * tileM);
            for (double tx = firstX; tx <= lastX; tx += 1)
            {
                double dx = Math.Max(Math.Max(tx * tileM - x, 0), x - (tx + 1) * tileM);
                double d2 = dx * dx + dz * dz;
                if (d2 > reach) continue;
                var key = TileKeyAt(tileM, (tx + 0.5) * tileM, (tz + 0.5) * tileM);
                if (!index.Contains(key)) continue;
                hits.Add((key, d2));
            }
        }
        hits.Sort((a, b) => a.D2 != b.D2 ? a.D2.CompareTo(b.D2) : string.CompareOrdinal(a.Key, b.Key));
        return hits.Select(h => h.Key).ToList();
    }

    /// <summary><c>tileBatches</c>: the keys in request-sized runs, order kept; a size below 1 counts as 1.</summary>
    public static List<List<T>> TileBatches<T>(IReadOnlyList<T> keys, double max = BatchMax)
    {
        int size = max > 0 ? (int)Math.Floor(max) : 1;
        var batches = new List<List<T>>();
        for (int i = 0; i < keys.Count; i += size) batches.Add(keys.Skip(i).Take(size).ToList());
        return batches;
    }

    /// <summary><c>tileKeyAt</c>: <c>"floor(x / tileM),floor(z / tileM)"</c>; no tile size = "".</summary>
    public static string TileKeyAt(double tileM, double x, double z)
        => !(tileM > 0) ? "" : Key(Math.Floor(x / tileM), Math.Floor(z / tileM));

    /// <summary>A key as a JS template literal prints two integers (<c>`${tx},${tz}`</c>): −0 prints as "0".</summary>
    public static string Key(double tx, double tz)
        => string.Create(CultureInfo.InvariantCulture, $"{tx + 0.0},{tz + 0.0}");
}
