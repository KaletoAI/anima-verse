using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

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
    /// <summary>The overview of the relief held now; a new <c>height_sig</c> replaces it (<see cref="Reset"/>).</summary>
    public HeightfieldOverview Overview { get; private set; }
    private readonly Dictionary<(int, int), HeightTile> _tiles = new();
    /// <summary>
    /// The tiles in "last wanted" order (the browser's <c>relief.tiles</c> Map, whose insertion order IS the LRU:
    /// <c>refreshTiles</c> re-inserts every wanted key, <c>evictTiles</c> drops from the front).
    /// </summary>
    private readonly List<(int, int)> _order = new();
    private Dictionary<string, TileStat> _stats;

    public WorldHeight(HeightfieldOverview overview)
    {
        Overview = overview;
        // applyHeight: the overview's capped `tile_stats` first; every tile that lands brings its own copy.
        _stats = new Dictionary<string, TileStat>(overview.TileStats, StringComparer.Ordinal);
    }

    public IReadOnlyCollection<HeightTile> Tiles => _tiles.Values;

    /// <summary>The held tile keys, oldest wanted first (the eviction order).</summary>
    public IReadOnlyList<(int Tx, int Tz)> LruOrder => _order;

    /// <summary>
    /// <c>relief.stats</c>: every tile statistic known — the overview's (at most 64), each loaded tile's own
    /// (<c>takeTiles</c> overwrites, the same arithmetic on the same raster) and every one the background fill fetched
    /// (<see cref="AddStats"/>). An evicted tile keeps its statistic. The terrain quadtree's node bounds and level
    /// errors read it.
    /// </summary>
    public IReadOnlyDictionary<string, TileStat> Stats => _stats;

    public void AddTiles(IEnumerable<HeightTile> tiles)
    {
        bool any = false;
        foreach (var t in tiles)
        {
            // Map.set on a held key keeps its place; a new key goes to the back.
            if (!_tiles.ContainsKey(t.Key)) _order.Add(t.Key);
            _tiles[t.Key] = t;
            if (t.Stats is { } st) _stats[Terrain.HeightTiles.Key(t.Key.Tx, t.Key.Tz)] = st;
            any = true;
        }
        if (any) Revision++;
    }

    /// <summary>
    /// <c>refreshTiles</c>' "wanting a tile is USING it": a held key moves to the back of the eviction order (delete +
    /// set on the Map). An unheld key does nothing.
    /// </summary>
    public void Touch((int Tx, int Tz) key)
    {
        int i = _order.IndexOf(key);
        if (i < 0) return;
        _order.RemoveAt(i);
        _order.Add(key);
    }

    /// <summary>
    /// <c>evictTiles</c>' delete: the tile (and with it its water, which lives in the tile) leaves; its statistic stays.
    /// Not a revision: the browser bumps <c>heightRev</c> per batch taken, and an eviction only ever happens in the same
    /// breath as one.
    /// </summary>
    public bool RemoveTile((int Tx, int Tz) key)
    {
        if (!_tiles.Remove(key)) return false;
        _order.Remove(key);
        return true;
    }

    /// <summary>The statistics the background fill brought (<c>fillMissingStats</c>: <c>relief.stats.set</c>).</summary>
    public int AddStats(IEnumerable<KeyValuePair<string, TileStat>> stats)
    {
        int n = 0;
        foreach (var (k, s) in stats)
        {
            _stats[k] = s;
            n++;
        }
        return n;
    }

    /// <summary>
    /// <c>applyHeight</c>: a new relief (a new <c>height_sig</c>) throws the tiles away with the overview — a tile that
    /// outlived its signature would be a piece of a world that no longer exists, and the sampler prefers the tile — and
    /// the statistics start again from the new overview's. A revision: everything draped on the old field samples again.
    /// </summary>
    public void Reset(HeightfieldOverview overview)
    {
        Overview = overview;
        _tiles.Clear();
        _order.Clear();
        _stats = new Dictionary<string, TileStat>(overview.TileStats, StringComparer.Ordinal);
        Revision++;
    }

    /// <summary>
    /// A frozen copy for a background build (the near pyramid, the water fields): the same overview and tile objects
    /// (both immutable), copied containers — so the main thread may take and evict tiles while a worker reads this.
    /// </summary>
    public WorldHeight Snapshot()
    {
        var copy = new WorldHeight(Overview) { Revision = Revision };
        foreach (var key in _order) copy._order.Add(key);
        foreach (var (k, t) in _tiles) copy._tiles[k] = t;
        copy._stats = new Dictionary<string, TileStat>(_stats, StringComparer.Ordinal);
        return copy;
    }

    /// <summary>
    /// The water raster of the loaded tiles (<c>waterRaster.tiles</c>: a tile with a water block files it under its
    /// key, a dry tile files nothing), on the overview's tile size; null when no loaded tile carries water.
    /// </summary>
    public Water.WaterRaster? WaterRaster()
    {
        var wet = new Dictionary<string, Ground.WaterTileField>(StringComparer.Ordinal);
        foreach (var t in _tiles.Values)
            if (t.Water is { } w) wet[Terrain.HeightTiles.Key(t.Key.Tx, t.Key.Tz)] = w;
        return wet.Count == 0 ? null : new Water.WaterRaster(Overview.TileM, wet);
    }

    /// <summary>
    /// <c>terrainGround.heightRevision()</c>: counts up with every batch of tiles that lands and with every new relief,
    /// so whatever sampled the field before (a location's datum, the § A16.9 lifts, the scatter) knows to sample again
    /// (main.ts <c>tickModelTiers</c>).
    /// </summary>
    public int Revision { get; private set; }

    public bool HasTile((int, int) key) => _tiles.ContainsKey(key);

    public (int Tx, int Tz) TileKeyAt(double x, double z)
        => ((int)Math.Floor(x / Overview.TileM), (int)Math.Floor(z / Overview.TileM));

    public double GroundAt(double x, double z)
        => _tiles.TryGetValue(TileKeyAt(x, z), out var t) ? t.Grid.Sample(x, z) : Overview.Grid.Sample(x, z);

    /// <summary>The overview's tile index in payload spelling (<c>"tx,tz"</c>) — the want set's universe.</summary>
    public HashSet<string> IndexKeys() => Overview.TileKeys.ToHashSet(StringComparer.Ordinal);

    /// <summary>
    /// Index tiles whose 256 m square comes within <paramref name="radius"/> of (x, z) — the nearest point of the
    /// square, not its centre — nearest first, ties in key order: the browser's <c>wantedTiles</c>
    /// (<see cref="Terrain.HeightTiles.WantedTiles"/>, the one port of it), so the boot ring fetches what the browser would.
    /// </summary>
    public List<(int Tx, int Tz)> IndexedTilesNear(double x, double z, double radius)
    {
        var keys = new List<(int Tx, int Tz)>();
        foreach (var key in Terrain.HeightTiles.WantedTiles(IndexKeys(), Overview.TileM, x, z, radius))
            if (HeightfieldOverview.TryTileKey(key, out var k)) keys.Add(k);
        return keys;
    }
}

/// <summary>Where the bench (S2) and the start camera are centred. Coordinates in world metres.</summary>
public sealed record AnchorInfo(double X, double Y, double Z, string? LocationId, string Source)
{
    public static readonly AnchorInfo Origin = new(0, 0, 0, null, "world origin");
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
