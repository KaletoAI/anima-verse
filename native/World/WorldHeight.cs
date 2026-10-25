using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The world ground as the client holds it: the coarse overview plus whichever
/// 2 m tiles were loaded. <see cref="GroundAt"/> reads the fine tile under a
/// point when it is there and the overview otherwise — what the browser's
/// <c>worldGroundAt</c> does for a location's datum.
///
/// The BENCH ANCHOR does not use this: it reads the overview only (see
/// <see cref="Anchor"/>), exactly like the browser bench, so that loading
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

/// <summary>Where the bench (S2) and the start camera are centred. Coordinates in world metres.</summary>
public sealed record AnchorInfo(double X, double Y, double Z, string? LocationId, string Source)
{
    public static readonly AnchorInfo Origin = new(0, 0, 0, null, "world origin");

    public Vector3 Position => new((float)X, (float)Y, (float)Z);
}

/// <summary>
/// THE bench anchor rule — a line-for-line port of <c>pickBenchAnchor</c>
/// (client3d/src/bench/benchAnchor.ts, checked by
/// client3d/scripts/smoke_bench_anchor.mjs; the same cases run in
/// <c>--check</c>). The world build (start camera, tile ring) and the bench run
/// use this one implementation.
///
///   • rows = the location rows of the CURRENT <c>/play/worldmap</c> snapshot
///     (authoritative for placement); a row without a name borrows the
///     <c>/world/locations</c> name (<c>nameOf</c>);
///   • <c>--goto</c> (trimmed; empty = none): an exact id, case-insensitive,
///     anywhere in the list beats a case-insensitive name substring;
///     unknown or unplaced (pos null/non-finite) → error;
///   • no goto → the avatar's current location (worldmap
///     <c>characters[name == avatar].location_id</c>) if placed → else the
///     world origin (no height sampled);
///   • y = <c>heightAt(x, z)</c> — the bench passes the <c>/play/heightfield</c>
///     OVERVIEW, bilinear and border-clamped (the browser's
///     <c>sampleWorldHeight</c>), never the 2 m tiles, so loading tiles never
///     moves the anchor.
/// </summary>
public static class Anchor
{
    /// <summary>The browser's <c>heightSource</c> label, minus its bench suffix.</summary>
    public const string OverviewSource = "/play/heightfield overview: sampleWorldHeight (bilinear, border-clamped)";
    /// <summary>The label of the bench run — identical to the browser's string.</summary>
    public const string BenchSource = OverviewSource + ", frozen at run start";

    /// <summary><c>isPlaced</c>: <c>pos_x</c>/<c>pos_z</c> null or non-finite = unplaced.</summary>
    public static bool IsPlaced(LocationInfo row)
        => row.PosX is double x && double.IsFinite(x) && row.PosZ is double z && double.IsFinite(z);

    /// <summary><c>matchGoto</c>: exact id (case-insensitive) first, then the name substring.</summary>
    public static LocationInfo? MatchGoto(IReadOnlyList<LocationInfo> rows, string gotoQuery,
                                          Func<string, string?>? nameOf = null)
    {
        var q = gotoQuery.ToLowerInvariant();
        return rows.FirstOrDefault(r => r.Id.ToLowerInvariant() == q)
               ?? rows.FirstOrDefault(r =>
               {
                   var name = !string.IsNullOrEmpty(r.Name) ? r.Name : nameOf?.Invoke(r.Id) ?? "";
                   return name.ToLowerInvariant().Contains(q, StringComparison.Ordinal);
               });
    }

    /// <summary><c>pickBenchAnchor</c>.</summary>
    public static AnchorInfo Pick(string? gotoQuery, IReadOnlyList<LocationInfo> rows, Func<string, string?>? nameOf,
                                  string? currentId, Func<double, double, double> heightAt, string heightSource)
    {
        var q = gotoQuery?.Trim();
        bool hasGoto = !string.IsNullOrEmpty(q);
        var row = hasGoto
            ? MatchGoto(rows, q!, nameOf)
            : !string.IsNullOrEmpty(currentId) ? rows.FirstOrDefault(r => r.Id == currentId) : null;
        if (hasGoto && (row is null || !IsPlaced(row)))
            throw new InvalidOperationException($"Bench goto location is unknown or unplaced: {q}");
        if (row is null || !IsPlaced(row)) return AnchorInfo.Origin;
        double x = row.PosX!.Value, z = row.PosZ!.Value;
        return new AnchorInfo(x, heightAt(x, z), z, row.Id, heightSource);
    }

    /// <summary>The avatar's current location id from a worldmap payload (browser: <c>characters.find(name === avatar)</c>).</summary>
    public static string? AvatarLocation(JsonElement worldmap)
    {
        var avatar = Json.Str(worldmap, "avatar");
        if (avatar.Length == 0) return null;
        foreach (var c in Json.Arr(worldmap, "characters"))
            if (c.ValueKind == JsonValueKind.Object && Json.Str(c, "name") == avatar)
            {
                var id = Json.Str(c, "location_id");
                return id.Length > 0 ? id : null;
            }
        return null;
    }

    /// <summary>
    /// The wiring both callers use: rows and avatar from <paramref name="worldmap"/>,
    /// names from the view=3d <paramref name="details"/>, y from the overview grid.
    /// </summary>
    public static AnchorInfo FromWorld(JsonElement worldmap, IReadOnlyList<LocationInfo> details, HeightGrid overview,
                                       string? gotoQuery, string heightSource = OverviewSource)
    {
        var rows = LocationInfo.ParseList(worldmap);
        var names = new Dictionary<string, string>();
        foreach (var d in details) names.TryAdd(d.Id, d.Name);
        return Pick(gotoQuery, rows, id => names.TryGetValue(id, out var n) && n.Length > 0 ? n : null,
                    AvatarLocation(worldmap), overview.Sample, heightSource);
    }
}
