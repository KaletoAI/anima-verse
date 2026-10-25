using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The world ground as the client holds it: the coarse overview plus whichever
/// 2 m tiles were loaded. <see cref="GroundAt"/> reads the fine tile under a
/// point when it is there and the overview otherwise — what the browser's
/// <c>worldGroundAt</c> does for a location's datum.
///
/// The BENCH ANCHOR does not use this: it reads the overview only (see
/// <see cref="Anchor"/>), exactly like Task S0's browser bench, so that loading
/// tiles never moves the anchor.
/// </summary>
public sealed class WorldHeight
{
    public HeightfieldOverview Overview { get; }
    private readonly Dictionary<(int, int), HeightTile> _tiles = new();

    public WorldHeight(HeightfieldOverview overview) => Overview = overview;

    public IReadOnlyCollection<HeightTile> Tiles => _tiles.Values;

    public void AddTiles(IEnumerable<HeightTile> tiles)
    {
        foreach (var t in tiles) _tiles[t.Key] = t;
    }

    public bool HasTile((int, int) key) => _tiles.ContainsKey(key);

    public (int Tx, int Tz) TileKeyAt(double x, double z)
        => ((int)Math.Floor(x / Overview.TileM), (int)Math.Floor(z / Overview.TileM));

    public double GroundAt(double x, double z)
        => _tiles.TryGetValue(TileKeyAt(x, z), out var t) ? t.Grid.Sample(x, z) : Overview.Grid.Sample(x, z);

    /// <summary>
    /// Index tiles whose 256 m square comes within <paramref name="radius"/> of
    /// (x, z) — the nearest point of the square, not its centre.
    /// </summary>
    public List<(int Tx, int Tz)> IndexedTilesNear(double x, double z, double radius)
    {
        double m = Overview.TileM;
        return Overview.TileIndex
            .Where(k =>
            {
                double dx = Math.Max(Math.Max(k.Tx * m - x, 0), x - (k.Tx + 1) * m);
                double dz = Math.Max(Math.Max(k.Tz * m - z, 0), z - (k.Tz + 1) * m);
                return dx * dx + dz * dz <= radius * radius;
            })
            .OrderBy(k => k.Tx).ThenBy(k => k.Tz)
            .ToList();
    }
}

/// <summary>Where the bench (S2) and the start camera are centred.</summary>
public sealed record AnchorInfo(Vector3 Position, string? LocationId, string Source);

public static class Anchor
{
    /// <summary>
    /// THE anchor rule of Task S0 (client3d/src/main.ts, <c>initBench</c> env):
    /// <c>--goto</c> is lower-cased; the FIRST location of
    /// <c>/world/locations?view=3d</c> (in payload order) whose id equals it
    /// (case-insensitive) or whose name contains it wins. Its position is
    /// <c>pos_x/pos_z</c>, y = the <c>/play/heightfield</c> OVERVIEW sampled
    /// bilinearly and border-clamped (<c>sampleWorldHeight</c>). An unknown or
    /// unplaced <c>--goto</c> is an error, as in the browser. Without
    /// <c>--goto</c>: the world origin (0, 0, 0).
    ///
    /// The position comes from the <c>/play/worldmap</c> row of that id: the
    /// view=3d rows carry no <c>pos_x/pos_z</c> at all (§ A1.3,
    /// <c>VIEW_3D_FIELDS</c>), the world map is authoritative for placement —
    /// the same merge the browser's <c>placeableOf</c> does. A location the
    /// world map does not list (fogged) or lists without a point is "unplaced".
    ///
    /// Deliberate difference to the browser: it falls back to the AVATAR's
    /// location when no goto is given; this skeleton has no avatar yet and uses
    /// the origin (task brief S1a). Bench runs pass <c>--goto</c>/<c>&amp;goto=</c>.
    /// </summary>
    public static AnchorInfo Resolve(IReadOnlyList<LocationInfo> details, IReadOnlyList<LocationInfo> mapRows,
                                     HeightGrid overview, string? gotoQuery)
    {
        if (string.IsNullOrWhiteSpace(gotoQuery))
            return new AnchorInfo(Vector3.Zero, null, "world origin");
        var q = gotoQuery.ToLowerInvariant();
        bool Match(LocationInfo l) => l.Id.ToLowerInvariant() == q
                                      || l.Name.ToLowerInvariant().Contains(q, StringComparison.Ordinal);
        var hit = details.FirstOrDefault(Match) ?? mapRows.FirstOrDefault(Match);
        var placed = hit is null ? null : mapRows.FirstOrDefault(r => r.Id == hit.Id);
        if (placed is null || !placed.IsPlaced)
            throw new InvalidOperationException($"Bench goto location is unknown or unplaced: {gotoQuery}");
        double x = placed.PosX!.Value, z = placed.PosZ!.Value;
        return new AnchorInfo(new Vector3((float)x, (float)overview.Sample(x, z), (float)z), placed.Id,
                              "/play/heightfield overview: bilinear, border-clamped");
    }
}
