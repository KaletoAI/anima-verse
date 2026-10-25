using System;
using System.Collections.Generic;

namespace AnimaNative.Scatter;

/// <summary>A world point on the ground plane, metres.</summary>
public readonly record struct P2(double X, double Z);

/// <summary>One placed instance (<c>ScatterInstance</c>): position, yaw (radians) and — only when the caller
/// asked for a mix — the model variant.</summary>
public readonly record struct ScatterInstance(double X, double Z, double Yaw, int? Variant);

/// <summary>The occupancy store the sampler asks (<c>ScatterOccupancy</c>).</summary>
public interface IScatterOccupancy
{
    bool Blocks(double x, double z, double r, string? tag);
    void Add(double x, double z, double r, string? tag);
}

/// <summary>
/// JavaScript number semantics the port needs bit for bit: <c>Math.round</c> (ties towards +∞, not
/// .NET's banker's rounding), <c>ToInt32</c> (<c>x | 0</c>) and <c>Math.imul</c> on uint32 bits.
/// </summary>
public static class Js
{
    public static double Round(double x)
    {
        if (!double.IsFinite(x)) return x;
        double f = Math.Floor(x);
        return x - f >= 0.5 ? f + 1 : f;
    }

    /// <summary><c>x | 0</c>: ToInt32 (modulo 2^32, NaN/∞ → 0).</summary>
    public static int ToInt32(double x)
    {
        if (!double.IsFinite(x)) return 0;
        double t = Math.Truncate(x);
        double m = t % 4294967296.0;
        if (m < 0) m += 4294967296.0;
        return unchecked((int)(uint)m);
    }

    public static double Fround(double x) => (float)x;
}

/// <summary>
/// Exact port of the shared sampler <c>packages/scene-render/src/scatter.ts</c> (+ <c>occupancy.ts</c> and the
/// ring helpers of <c>groundAreas.ts</c>). Same PRNG (FNV-1a state, xorshift stream), same candidate
/// stream (three draws per candidate, always), same verdict order, same double arithmetic — the reference
/// vectors of <c>native/fixtures/scatter_reference.json</c> (written by the TS function itself) are compared
/// within 1e-6 m. Absent JS options are <c>null</c> here and read as JS reads <c>undefined</c>
/// (<c>Number(undefined)</c> = NaN).
/// </summary>
public static class ScatterMath
{
    public const int MaxPerEntry = 2000;      // SCATTER_MAX_PER_ENTRY
    public const int TriesPerPoint = 12;      // SCATTER_TRIES_PER_POINT
    public const double ClearHeightRatio = 0.5; // SCATTER_CLEAR_HEIGHT_RATIO
    public const double CellM = 64;           // SCATTER_CELL_M
    public const int MaxPerCell = 4000;       // SCATTER_MAX_PER_CELL
    public const int CellsMax = 4096;         // SCATTER_CELLS_MAX
    public const double AreaEpsM2 = 1e-9;     // groundAreas.AREA_EPS_M2

    // ---- yaw, seeds, variants ------------------------------------------------------------------

    public static double Yaw(double r, string? mode, double? deg, double axisRad = 0)
    {
        if (mode != "aligned") return r * Math.PI * 2;
        double d = deg ?? double.NaN;
        double b = double.IsFinite(d) ? (d * Math.PI) / 180 : 0;
        double axis = double.IsFinite(axisRad) ? axisRad : 0;
        double tau = Math.PI * 2;
        return (((axis + b) % tau) + tau) % tau;
    }

    public static string SeedEpochSuffix(double? epoch)
        => epoch is double e && double.IsFinite(e) ? $":e{JsNum(e)}" : "";

    public static string Seed(string areaId, int index, double? epoch = null)
        => $"terrain:scatter:{areaId}:{index}{SeedEpochSuffix(epoch)}";

    public static string CellSeed(string areaId, int index, int cx, int cz, double? epoch = null)
        => $"terrain:scatter:{areaId}:{index}:{cx},{cz}{SeedEpochSuffix(epoch)}";

    public static double? ReshuffleEpoch(double totalSeconds, double? reshuffleMin)
    {
        double minutes = reshuffleMin ?? double.NaN;
        if (!double.IsFinite(minutes) || minutes <= 0) return null;
        if (!double.IsFinite(totalSeconds)) return null;
        return Math.Floor(totalSeconds / (minutes * 60));
    }

    /// <summary>JS <c>String(n)</c> for the integers a seed carries.</summary>
    private static string JsNum(double v)
        => v == Math.Floor(v) && Math.Abs(v) < 1e21 ? ((long)v).ToString(System.Globalization.CultureInfo.InvariantCulture)
                                                     : v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);

    /// <summary>FNV-1a 32-bit over the UTF-16 code units (<c>charCodeAt</c>), unsigned.</summary>
    public static uint SeedHash(string seed)
    {
        uint h = 2166136261u;
        foreach (char c in seed)
        {
            h ^= c;
            h = unchecked(h * 16777619u);
        }
        return h;
    }

    public static int VariantIndex(string seed, double instance, double count)
    {
        double n = Math.Floor(count);
        if (!double.IsFinite(n) || n <= 1) return 0;
        double i = Math.Floor(instance);
        if (!double.IsFinite(i)) return 0;
        return (int)((((SeedHash(seed) + i) % n) + n) % n);
    }

    public static int PinnedVariant(double? variant, double count)
    {
        if (variant is not double v || !double.IsFinite(v)) return -1;
        double n = Math.Floor(count);
        if (!double.IsFinite(n) || n < 1) return -1;
        return (int)Math.Min(Math.Max(Math.Floor(v), 0), n - 1);
    }

    /// <summary><c>seededRandom</c>: FNV-1a state, xorshift-multiply stream, [0, 1).</summary>
    public static Func<double> SeededRandom(string seed)
    {
        uint h = SeedHash(seed);
        return () =>
        {
            h = unchecked((h ^ (h >> 15)) * 2246822519u);
            h = unchecked((h ^ (h >> 13)) * 3266489917u);
            h ^= h >> 16;
            return h / 4294967296.0;
        };
    }

    // ---- rings and footprints ------------------------------------------------------------------

    public static bool PointInRing(double x, double z, IReadOnlyList<P2>? ring)
    {
        bool inside = false;
        int n = ring?.Count ?? 0;
        for (int i = 0, j = n - 1; i < n; j = i, i += 1)
        {
            var (xi, zi) = (ring![i].X, ring[i].Z);
            var (xj, zj) = (ring[j].X, ring[j].Z);
            if ((zi > z) != (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
        }
        return inside;
    }

    public static bool PointInFootprint(IReadOnlyList<P2>? pts, double x, double z)
    {
        int n = pts?.Count ?? 0;
        if (n < 3) return false;
        if (!double.IsFinite(x) || !double.IsFinite(z)) return false;
        bool inside = false;
        for (int i = 0, j = n - 1; i < n; j = i, i += 1)
        {
            double xi = pts![i].X, zi = pts[i].Z, xj = pts[j].X, zj = pts[j].Z;
            if (!double.IsFinite(xi) || !double.IsFinite(zi) || !double.IsFinite(xj) || !double.IsFinite(zj)) return false;
            if ((zi > z) != (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
        }
        return inside;
    }

    public static double FootprintDistance(IReadOnlyList<P2>? pts, double x, double z)
    {
        int n = pts?.Count ?? 0;
        if (n < 3) return double.PositiveInfinity;
        if (!double.IsFinite(x) || !double.IsFinite(z)) return double.PositiveInfinity;
        bool inside = false;
        double best = double.PositiveInfinity;
        for (int i = 0, j = n - 1; i < n; j = i, i += 1)
        {
            double xi = pts![i].X, zi = pts[i].Z, xj = pts[j].X, zj = pts[j].Z;
            if (!double.IsFinite(xi) || !double.IsFinite(zi) || !double.IsFinite(xj) || !double.IsFinite(zj))
                return double.PositiveInfinity;
            if ((zi > z) != (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
            double dx = xi - xj;
            double dz = zi - zj;
            double len2 = dx * dx + dz * dz;
            double t = len2 < 1e-18 ? 0 : ((x - xj) * dx + (z - zj) * dz) / len2;
            t = t < 0 ? 0 : (t > 1 ? 1 : t);
            double ex = x - (xj + t * dx);
            double ez = z - (zj + t * dz);
            double d = Math.Sqrt(ex * ex + ez * ez);
            if (d < best) best = d;
        }
        return inside ? 0 : best;
    }

    public static bool FootprintBlocks(IReadOnlyList<P2> fp, double x, double z, double? clearM)
    {
        double clear = clearM ?? double.NaN;
        if (!(clear > 0)) return PointInFootprint(fp, x, z);
        return FootprintDistance(fp, x, z) < clear;
    }

    public static double ClearM(double heightM, double? extentM)
    {
        double extent = extentM ?? double.NaN;
        if (double.IsFinite(extent) && extent > 0) return extent / 2;
        double h = heightM;
        if (!double.IsFinite(h) || h <= 0) return 0;
        return h * ClearHeightRatio;
    }

    /// <summary><c>propBoxFootprint</c>: the turned rectangle of a placed prop (§ A9b), or null.</summary>
    public static P2[]? PropBoxFootprint(double cx, double cz, double yawDeg, double hw, double hd)
    {
        if (!double.IsFinite(cx) || !double.IsFinite(cz)) return null;
        if (!(hw > 0) || !(hd > 0)) return null;
        double yawRad = ((double.IsFinite(yawDeg) ? yawDeg : 0) * Math.PI) / 180;
        double cos = Math.Cos(yawRad), sin = Math.Sin(yawRad);
        P2 Corner(double lx, double lz) => new(cx + lx * cos + lz * sin, cz - lx * sin + lz * cos);
        return new[] { Corner(-hw, -hd), Corner(hw, -hd), Corner(hw, hd), Corner(-hw, hd) };
    }

    public static double OccupyR(double? occupyR, double? clearM)
    {
        double r = occupyR ?? clearM ?? double.NaN;
        return double.IsFinite(r) && r > 0 ? r : 0;
    }

    public static int WantedCount(double areaM2, double densityPer100m2, int? maxPoints)
    {
        double density = densityPer100m2, area = areaM2;
        if (!double.IsFinite(density) || density <= 0) return 0;
        if (!double.IsFinite(area) || area <= 0) return 0;
        double max = maxPoints ?? MaxPerEntry;
        double wanted = Math.Min(Js.Round((area / 100) * density), max);
        return wanted >= 1 ? (int)wanted : 0;
    }

    // ---- the sampler ---------------------------------------------------------------------------

    public sealed class SampleOptions
    {
        public IReadOnlyList<P2> Ring = Array.Empty<P2>();
        public double AreaM2;
        public double DensityPer100m2;
        public string Seed = "";
        public IReadOnlyList<IReadOnlyList<P2>>? Footprints;
        public double? ClearM;
        public IReadOnlyList<IReadOnlyList<P2>>? Occluders;
        public double? MinSpacingM;
        public int? MaxPoints;
        public double? VariantCount;
        public double? Variant;
        public int? TriesPerPoint;
        public Func<double>? Rng;
        public string? YawMode;
        public double? YawDeg;
        public Func<double, double, double>? AxisAt;
        public IScatterOccupancy? Occupied;
        public double? OccupyR;
        public string? OccupyTag;
    }

    /// <summary><c>scatterInstances</c>, line for line.</summary>
    public static List<ScatterInstance> Instances(SampleOptions o)
    {
        var outList = new List<ScatterInstance>();
        var ring = o.Ring ?? Array.Empty<P2>();
        double density = o.DensityPer100m2, areaM2 = o.AreaM2;
        if (ring.Count < 3) return outList;
        if (!double.IsFinite(density) || density <= 0) return outList;
        if (!double.IsFinite(areaM2) || areaM2 <= 0) return outList;
        int wanted = WantedCount(areaM2, density, o.MaxPoints);
        if (wanted < 1) return outList;

        double minX = double.PositiveInfinity, minZ = double.PositiveInfinity;
        double maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        foreach (var p in ring)
        {
            // JS: `x < minX` etc. on numbers — NaN never wins a comparison.
            if (p.X < minX) minX = p.X;
            if (p.X > maxX) maxX = p.X;
            if (p.Z < minZ) minZ = p.Z;
            if (p.Z > maxZ) maxZ = p.Z;
        }
        if (!double.IsFinite(minX) || !double.IsFinite(minZ)) return outList;

        var rnd = o.Rng ?? SeededRandom(o.Seed);
        var footprints = o.Footprints ?? Array.Empty<IReadOnlyList<P2>>();
        var clearM = o.ClearM;
        var occluders = o.Occluders ?? Array.Empty<IReadOnlyList<P2>>();
        double spacing = o.MinSpacingM ?? double.NaN;
        bool spaced = double.IsFinite(spacing) && spacing > 0;
        double spacing2 = spacing * spacing;
        var buckets = spaced ? new Dictionary<(double, double), List<P2>>() : null;
        double variants = Math.Floor(o.VariantCount ?? double.NaN);
        bool mixing = double.IsFinite(variants) && variants > 1;
        int pinned = mixing ? PinnedVariant(o.Variant, variants) : -1;
        var axisAt = o.YawMode == "aligned" ? o.AxisAt : null;
        var occupied = o.Occupied;
        double occupyR = OccupyR(o.OccupyR, o.ClearM);
        string occupyTag = o.OccupyTag ?? o.Seed;
        long tries = (long)wanted * (o.TriesPerPoint ?? TriesPerPoint);
        long candidate = 0;
        while (outList.Count < wanted && tries > 0)
        {
            tries -= 1;
            long index = candidate;
            candidate += 1;
            double x = minX + rnd() * (maxX - minX);
            double z = minZ + rnd() * (maxZ - minZ);
            double turn = rnd();
            if (!PointInRing(x, z, ring)) continue;
            bool hidden = false;
            foreach (var occ in occluders)
                if ((occ?.Count ?? 0) >= 3 && PointInRing(x, z, occ)) { hidden = true; break; }
            if (hidden) continue;
            bool covered = false;
            foreach (var fp in footprints)
                if (FootprintBlocks(fp, x, z, clearM)) { covered = true; break; }
            if (covered) continue;
            if (buckets is not null)
            {
                double bx = Math.Floor(x / spacing), bz = Math.Floor(z / spacing);
                bool crowded = false;
                for (int dz = -1; dz <= 1 && !crowded; dz += 1)
                    for (int dx = -1; dx <= 1 && !crowded; dx += 1)
                    {
                        if (!buckets.TryGetValue((bx + dx, bz + dz), out var near)) continue;
                        foreach (var a in near)
                        {
                            double ex = x - a.X, ez = z - a.Z;
                            if (ex * ex + ez * ez < spacing2) { crowded = true; break; }
                        }
                    }
                if (crowded) continue;
            }
            if (occupied is not null && occupied.Blocks(x, z, occupyR, occupyTag)) continue;
            if (buckets is not null)
            {
                var key = (Math.Floor(x / spacing), Math.Floor(z / spacing));
                if (buckets.TryGetValue(key, out var bucket)) bucket.Add(new P2(x, z));
                else buckets[key] = new List<P2> { new(x, z) };
            }
            occupied?.Add(x, z, occupyR, occupyTag);
            double yaw = Yaw(turn, o.YawMode, o.YawDeg, axisAt is not null ? axisAt(x, z) : 0);
            outList.Add(mixing
                ? new ScatterInstance(x, z, yaw, pinned >= 0 ? pinned : VariantIndex(o.Seed, index, variants))
                : new ScatterInstance(x, z, yaw, null));
        }
        return outList;
    }

    // ---- the cell raster -----------------------------------------------------------------------

    public static int CellAt(double v) => (int)Math.Floor(v / CellM);

    public static P2[] CellRing(int cx, int cz)
    {
        double x0 = cx * CellM, z0 = cz * CellM, x1 = x0 + CellM, z1 = z0 + CellM;
        return new[] { new P2(x0, z0), new P2(x1, z0), new P2(x1, z1), new P2(x0, z1) };
    }

    public static int CellSpan(double cullM)
    {
        if (!double.IsFinite(cullM) || cullM <= 0) return 1;
        return Math.Max(1, Math.Min((int)Math.Ceiling(cullM / CellM), (int)Math.Floor(Math.Sqrt(CellsMax) / 2)));
    }

    /// <summary><c>wantedScatterCells</c>: the (2k+1)² window around the anchor's cell, row-major (z outer).</summary>
    public static List<(int Cx, int Cz)> WantedCells(double x, double z, double cullM)
    {
        var outList = new List<(int, int)>();
        if (!double.IsFinite(x) || !double.IsFinite(z)) return outList;
        int k = CellSpan(cullM), cx = CellAt(x), cz = CellAt(z);
        for (int dz = -k; dz <= k; dz += 1)
            for (int dx = -k; dx <= k; dx += 1) outList.Add((cx + dx, cz + dz));
        return outList;
    }

    public sealed class CellOptions
    {
        public IReadOnlyList<P2> Ring = Array.Empty<P2>();
        public int Cx, Cz;
        public double DensityPer100m2;
        public string Seed = "";
        public IReadOnlyList<IReadOnlyList<P2>>? Footprints;
        public double? ClearM;
        public IReadOnlyList<IReadOnlyList<P2>>? Occluders;
        public double? MinSpacingM;
        public int? MaxPoints;
        public double? VariantCount;
        public double? Variant;
        public Func<double>? Rng;
        public string? YawMode;
        public double? YawDeg;
        public Func<double, double, double>? AxisAt;
        public IScatterOccupancy? Occupied;
        public double? OccupyR;
        public string? OccupyTag;
    }

    /// <summary>The add-filtered occupancy wrapper of <c>scatterCellInstances</c>.</summary>
    private sealed class RingFilteredOccupancy : IScatterOccupancy
    {
        private readonly IScatterOccupancy _inner;
        private readonly IReadOnlyList<P2> _ring;
        public RingFilteredOccupancy(IScatterOccupancy inner, IReadOnlyList<P2> ring) { _inner = inner; _ring = ring; }
        public bool Blocks(double x, double z, double r, string? tag) => _inner.Blocks(x, z, r, tag);
        public void Add(double x, double z, double r, string? tag) { if (PointInRing(x, z, _ring)) _inner.Add(x, z, r, tag); }
    }

    /// <summary><c>scatterCellInstances</c>: the cell box sampled with one try per wanted instance, the
    /// painted ring as the filter behind it.</summary>
    public static List<ScatterInstance> CellInstances(CellOptions o)
    {
        var ring = o.Ring ?? Array.Empty<P2>();
        if (ring.Count < 3) return new List<ScatterInstance>();
        var points = Instances(new SampleOptions
        {
            Ring = CellRing(o.Cx, o.Cz),
            AreaM2 = CellM * CellM,
            DensityPer100m2 = o.DensityPer100m2,
            Seed = o.Seed,
            Footprints = o.Footprints,
            ClearM = o.ClearM,
            Occluders = o.Occluders,
            MinSpacingM = o.MinSpacingM,
            MaxPoints = o.MaxPoints ?? MaxPerCell,
            TriesPerPoint = 1,
            VariantCount = o.VariantCount,
            Variant = o.Variant,
            Rng = o.Rng,
            YawMode = o.YawMode,
            YawDeg = o.YawDeg,
            AxisAt = o.AxisAt,
            Occupied = o.Occupied is null ? null : new RingFilteredOccupancy(o.Occupied, ring),
            OccupyR = o.OccupyR,
            OccupyTag = o.OccupyTag,
        });
        return points.FindAll(p => PointInRing(p.X, p.Z, ring));
    }

    /// <summary><c>propGroundFit</c>: uniform scale to the target height, lift so the lowest point is 0.</summary>
    public static (double Scale, double OffsetY) GroundFit(double minY, double maxY, double? targetH)
    {
        if (!double.IsFinite(minY) || !double.IsFinite(maxY)) return (1, 0);
        double height = maxY - minY;
        double target = targetH ?? double.NaN;
        double scale = double.IsFinite(target) && target > 0 && height > 1e-6 ? target / height : 1;
        return (scale, -minY * scale);
    }

    // ---- groundAreas.ts ------------------------------------------------------------------------

    public static double SignedArea(IReadOnlyList<P2> poly)
    {
        int n = poly?.Count ?? 0;
        if (n < 3) return 0;
        double sum = 0;
        for (int i = 0; i < n; i += 1)
        {
            var a = poly![i];
            var b = poly[(i + 1) % n];
            sum += a.X * b.Z - b.X * a.Z;
        }
        return sum / 2;
    }

    public static double PolygonArea(IReadOnlyList<P2> poly) => Math.Abs(SignedArea(poly));

    /// <summary><c>cleanRing</c>: junk dropped, consecutive duplicates and closing corners collapsed, &lt; 3 → empty.</summary>
    public static List<P2> CleanRing(IEnumerable<P2>? polygon)
    {
        var outList = new List<P2>();
        if (polygon is null) return outList;
        foreach (var p in polygon)
        {
            if (!double.IsFinite(p.X) || !double.IsFinite(p.Z)) continue;
            if (outList.Count > 0 && outList[^1].X == p.X && outList[^1].Z == p.Z) continue;
            outList.Add(p);
        }
        while (outList.Count > 1 && outList[0].X == outList[^1].X && outList[0].Z == outList[^1].Z)
            outList.RemoveAt(outList.Count - 1);
        return outList.Count >= 3 ? outList : new List<P2>();
    }

    /// <summary>The ring <c>buildAreaGeometry</c> hands out, or null where it builds nothing (area &lt; ε).</summary>
    public static List<P2>? AreaRing(IEnumerable<P2>? polygon)
    {
        var ring = CleanRing(polygon);
        if (ring.Count == 0 || Math.Abs(SignedArea(ring)) < AreaEpsM2) return null;
        return ring;
    }
}

/// <summary>
/// <c>occupancy.ts</c> <c>OccupancyGrid</c>: survivors filed in 8 m buckets; a query is blocked by any
/// circle of ANOTHER tag that overlaps (strictly) its own.
/// </summary>
public sealed class OccupancyGrid : IScatterOccupancy
{
    private const double DefaultBucketM = 8;
    private readonly double _bucketM;
    private readonly Dictionary<(double, double), List<(double X, double Z, double R, string? Tag)>> _buckets = new();
    private double _rMax;

    public OccupancyGrid(double bucketM = DefaultBucketM)
        => _bucketM = double.IsFinite(bucketM) && bucketM > 0 ? bucketM : DefaultBucketM;

    public void Add(double x, double z, double r, string? tag)
    {
        if (!double.IsFinite(x) || !double.IsFinite(z)) return;
        double radius = double.IsFinite(r) && r > 0 ? r : 0;
        var key = (Math.Floor(x / _bucketM), Math.Floor(z / _bucketM));
        if (_buckets.TryGetValue(key, out var b)) b.Add((x, z, radius, tag));
        else _buckets[key] = new() { (x, z, radius, tag) };
        if (radius > _rMax) _rMax = radius;
    }

    public bool Blocks(double x, double z, double r, string? tag)
    {
        if (_buckets.Count == 0) return false;
        if (!double.IsFinite(x) || !double.IsFinite(z)) return false;
        double radius = double.IsFinite(r) && r > 0 ? r : 0;
        double reach = Math.Ceiling((radius + _rMax) / _bucketM);
        double bx = Math.Floor(x / _bucketM), bz = Math.Floor(z / _bucketM);
        for (double dz = -reach; dz <= reach; dz += 1)
            for (double dx = -reach; dx <= reach; dx += 1)
            {
                if (!_buckets.TryGetValue((bx + dx, bz + dz), out var near)) continue;
                foreach (var (ax, az, ar, atag) in near)
                {
                    if (tag is not null && atag == tag) continue;
                    double ex = x - ax, ez = z - az, limit = radius + ar;
                    if (ex * ex + ez * ez < limit * limit) return true;
                }
            }
        return false;
    }
}

/// <summary><c>cellOccupancy</c>: one grid per 64 m cell, shared by every area of a pass.</summary>
public sealed class CellOccupancy : IScatterOccupancy
{
    private readonly Dictionary<(int, int), OccupancyGrid> _grids;
    public CellOccupancy(Dictionary<(int, int), OccupancyGrid> grids) => _grids = grids;

    public OccupancyGrid GridOf(int cx, int cz)
    {
        if (!_grids.TryGetValue((cx, cz), out var g)) { g = new OccupancyGrid(); _grids[(cx, cz)] = g; }
        return g;
    }

    public bool Blocks(double x, double z, double r, string? tag)
        => _grids.TryGetValue((ScatterMath.CellAt(x), ScatterMath.CellAt(z)), out var g) && g.Blocks(x, z, r, tag);

    public void Add(double x, double z, double r, string? tag)
        => GridOf(ScatterMath.CellAt(x), ScatterMath.CellAt(z)).Add(x, z, r, tag);
}
