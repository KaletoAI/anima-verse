using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Ground;
using AnimaNative.Water;
using AnimaNative.World;

namespace AnimaNative.Terrain;

/// <summary>The near window's lattice: origin (x0, z0) and size in texels (<c>nearWindow</c>'s answer).</summary>
public readonly record struct NearWindowRect(double X0, double Z0, int Cols, int Rows);

/// <summary>One level of a <see cref="HeightPyramid"/> (<c>PyramidLevel</c>): its lattice and first texture row.</summary>
public readonly record struct PyramidLevel(int Cols, int Rows, double Step, int Row0);

/// <summary>
/// A decimated height (or water level) lattice stack in ONE float32 texture (<c>HeightPyramid</c>): level k+1 keeps
/// every second point of level k, the levels stacked downwards, <see cref="TexW"/> = level 0's columns.
/// </summary>
public sealed record HeightPyramid(double OriginX, double OriginZ, double Step, IReadOnlyList<PyramidLevel> Levels,
                                   float[] Data, int TexW, int TexH);

/// <summary>The near window's signed-distance lattice (<c>SdField</c>), float32, dry = <see cref="WaterTileField.SdDry"/>.</summary>
public sealed record SdField(double OriginX, double OriginZ, double Step, int Cols, int Rows, float[] Data);

/// <summary>One CDLOD instance (<c>LodNode</c>): square origin and size, level, cells per edge (32, or 16 for a
/// parent quadrant), and the morph value λ − level.</summary>
public readonly record struct LodNode(double X, double Z, double Size, int Level, int Cells, double Morph);

/// <summary>A tile's height span (<c>NodeStatSpan</c>).</summary>
public readonly record struct NodeStatSpan(double Min, double Max);

/// <summary>A camera position for <see cref="TerrainLod.LodVertex"/> (<c>LodCamera</c>).</summary>
public readonly record struct LodCamera(double X, double Y, double Z);

/// <summary>A morphed patch vertex (<c>morphedVertex</c>), and with <see cref="TerrainLod.LodVertex"/> the morph value used.</summary>
public readonly record struct LodVertexPos(double X, double Z, double Y, double T);

/// <summary>The input of <see cref="TerrainLod.SelectLodNodes"/> (<c>LodSelectOpts</c>).</summary>
public sealed record LodSelectOpts(double X0, double Z0, double X1, double Z1, double LeafM, double Levels,
                                   double MinLodDistance, double CamX, double CamY, double CamZ,
                                   Func<double, double, double, NodeStatSpan> BoundsOf)
{
    public IReadOnlyList<double>? LevelErrorM { get; init; }
    public double? PixelScale { get; init; }
    public IReadOnlyList<double>? Ranges { get; init; }
    public Func<double, double, double, double>? LodCapOf { get; init; }
}

/// <summary><c>selectLodFitted</c>'s answer: the nodes, the rings used, how often they were halved and the cap relaxed.</summary>
public sealed record LodSelection(List<LodNode> Nodes, List<double> Ranges, int Coarsenings, int CapRelax);

/// <summary>The water mip cap per tile corner (<c>LodCapGrid</c>): a float32 corner field, ring = <see cref="TerrainLod.LodCapNone"/>.</summary>
public sealed record LodCapGrid(double X0, double Z0, double Step, int Cols, int Rows, float[] Caps, double Min);

/// <summary>
/// The pure CDLOD math of the browser's terrain (<c>client3d/src/scene/terrainLod.ts</c>, contract § A16.6), line for
/// line in the same double arithmetic; checked against <c>shared/test-vectors/terrain_lod.json</c>.
/// </summary>
public static class TerrainLod
{
    /// <summary><c>PATCH_N</c>, <c>MAX_LOD_LEVELS</c>, <c>MIN_LOD_DISTANCE_M</c>, <c>MORPH_START</c>.</summary>
    public const int PatchN = 32, MaxLodLevels = 6;
    public const double MinLodDistanceM = 128, MorphStart = 0.5;
    /// <summary><c>MAX_PIXEL_ERROR</c>, <c>MAX_RANGE_WIDENING</c>, <c>MAX_NODES</c>.</summary>
    public const double MaxPixelError = 2, MaxRangeWidening = 2;
    public const int MaxNodes = 4096;
    /// <summary><c>LOD_CAP_NONE</c> = <see cref="MaxLodLevels"/>: no water cap.</summary>
    public const int LodCapNone = MaxLodLevels;
    private const int MaxFitSteps = 8, StatTileScanMax = 64, LodCapScanMax = 289;

    /// <summary><c>NEAR_MAX_TEXELS</c>, <c>NEAR_MARGIN_CELLS</c>, <c>NEAR_MARGIN_MIN_M</c>.</summary>
    public const int NearMaxTexels = 1025, NearMarginCells = 2;
    public const double NearMarginMinM = 16;

    /// <summary>
    /// <c>nearWindow</c>: the loaded tiles' bounding box grown by max(16 m, 2 overview steps), snapped onto the fine
    /// lattice, capped at 1025 texels per axis (then centred on the anchor). Keys are <c>"tx,tz"</c>; an unreadable
    /// key is skipped. <paramref name="overviewStep"/> null = the fine step (<c>overview?.step_m ?? step</c>).
    /// </summary>
    public static NearWindowRect? NearWindow(IReadOnlyCollection<string> keys, double tileM, double step,
                                             double? overviewStep, double anchorX, double anchorZ)
    {
        var parsed = new List<(double Tx, double Tz)>();
        foreach (var key in keys)
            parsed.Add(LayerCut.TryKey(key, out var tx, out var tz) ? (tx, tz) : (double.NaN, double.NaN));
        return NearWindow(parsed, tileM, step, overviewStep, anchorX, anchorZ);
    }

    /// <summary><see cref="NearWindow(IReadOnlyCollection{string}, double, double, double?, double, double)"/> on parsed keys (NaN = unreadable).</summary>
    public static NearWindowRect? NearWindow(IReadOnlyCollection<(double Tx, double Tz)> keys, double tileM, double step,
                                             double? overviewStep, double anchorX, double anchorZ)
    {
        if (keys.Count == 0 || !(step > 0) || !(tileM > 0)) return null;
        double x0 = double.PositiveInfinity, z0 = double.PositiveInfinity;
        double x1 = double.NegativeInfinity, z1 = double.NegativeInfinity;
        foreach (var (tx, tz) in keys)
        {
            if (!double.IsFinite(tx) || !double.IsFinite(tz)) continue;
            x0 = Math.Min(x0, tx * tileM);
            z0 = Math.Min(z0, tz * tileM);
            x1 = Math.Max(x1, (tx + 1) * tileM);
            z1 = Math.Max(z1, (tz + 1) * tileM);
        }
        if (!double.IsFinite(x0)) return null;
        double ovStep = overviewStep ?? step;
        double margin = Math.Max(NearMarginMinM, NearMarginCells * ovStep);
        x0 -= margin; z0 -= margin; x1 += margin; z1 += margin;
        x0 = Math.Floor(x0 / step) * step;
        z0 = Math.Floor(z0 / step) * step;
        double cols = Math.Floor((x1 - x0) / step) + 1;
        double rows = Math.Floor((z1 - z0) / step) + 1;
        if (cols > NearMaxTexels || rows > NearMaxTexels)
        {
            double halfX = Math.Min(cols, NearMaxTexels) * step / 2;
            double halfZ = Math.Min(rows, NearMaxTexels) * step / 2;
            x0 = Math.Floor((anchorX - halfX) / step) * step;
            z0 = Math.Floor((anchorZ - halfZ) / step) * step;
            cols = Math.Min(cols, NearMaxTexels);
            rows = Math.Min(rows, NearMaxTexels);
        }
        if (cols < 2 || rows < 2) return null;
        return new NearWindowRect(x0, z0, (int)cols, (int)rows);
    }

    // ── Rings and morph ────────────────────────────────────────────────────

    /// <summary>
    /// <c>lodLambda(d, ranges)</c>: the continuous LOD at distance d — Σ over the rings of
    /// clamp((d − s_i) / (r_i − s_i), 0, 1) with s_i halfway between the previous ring and r_i; a zero ring is skipped.
    /// </summary>
    public static double LodLambda(double d, IReadOnlyList<double> ranges)
    {
        double lam = 0, prev = 0;
        foreach (var r in ranges)
        {
            if (!(r > 0)) continue;
            double start = prev + MorphStart * (r - prev);
            prev = r;
            if (!(r > start))
            {
                lam += d >= r ? 1 : 0;
                continue;
            }
            double t = (d - start) / (r - start);
            lam += t <= 0 ? 0 : t >= 1 ? 1 : t;
        }
        return lam;
    }

    /// <summary>
    /// <c>lodRanges</c>: ring i = max(g_i, min(err[i+1]·pixelScale/2, 2·g_i)) with g_i = minLodDistance·2^i, forced
    /// monotone; without errors or pixel scale the geometric ladder, minLodDistance 0 = all zero.
    /// </summary>
    public static List<double> LodRanges(double minLodDistance, double levels, IReadOnlyList<double>? levelErrorM = null,
                                         double? pixelScale = null)
    {
        var ranges = new List<double>();
        double scale = pixelScale is double ps && ps > 0 ? ps : 0;
        for (int i = 0; i < levels; i++)
        {
            double r = minLodDistance * (1 << i);
            double err = levelErrorM is not null && i + 1 < levelErrorM.Count ? levelErrorM[i + 1] : 0;
            if (minLodDistance > 0 && scale > 0 && err > 0)
                r = Math.Max(r, Math.Min(err * scale / MaxPixelError, r * MaxRangeWidening));
            if (i > 0 && r < ranges[i - 1]) r = ranges[i - 1];
            ranges.Add(r);
        }
        return ranges;
    }

    /// <summary>
    /// <c>levelErrorsFrom</c>: per level ≥ 1 the largest <c>err[k]</c> of all known tiles, k = the index of
    /// baseStep·2^level in the server's mip list (exact match); level 0 and unknown levels = 0.
    /// </summary>
    public static double[] LevelErrorsFrom(IReadOnlyCollection<IReadOnlyList<double>?>? errLists, IReadOnlyList<double>? mipLevelsM,
                                           double baseStepM, int levels)
    {
        var errs = new double[Math.Max(0, levels)];
        if (errLists is null || errLists.Count == 0 || mipLevelsM is null || mipLevelsM.Count == 0 || !(baseStepM > 0)) return errs;
        for (int level = 1; level < errs.Length; level++)
        {
            double want = baseStepM * (1 << level);
            int k = -1;
            for (int m = 0; m < mipLevelsM.Count; m++)
                if (mipLevelsM[m] == want) { k = m; break; }
            if (k < 0) continue;
            double err = 0;
            foreach (var list in errLists)
                if (list is not null && k < list.Count && list[k] > err) err = list[k];
            errs[level] = err;
        }
        return errs;
    }

    /// <summary>
    /// <c>nodeBounds</c>: the height span of a node square — the union of the tile spans it covers (a covered tile
    /// without stats is the flat world, 0); more than 64 tiles, no stats or none seen = the global range.
    /// </summary>
    public static NodeStatSpan NodeBounds(IReadOnlyDictionary<string, NodeStatSpan>? stats, double tileM, NodeStatSpan globalRange,
                                          double x, double z, double size)
    {
        if (stats is null || stats.Count == 0 || !(tileM > 0)) return globalRange;
        double min = double.PositiveInfinity, max = double.NegativeInfinity;
        double tx0 = Math.Floor(x / tileM), tx1 = Math.Floor((x + size - 1e-6) / tileM);
        double tz0 = Math.Floor(z / tileM), tz1 = Math.Floor((z + size - 1e-6) / tileM);
        double covered = (tx1 - tx0 + 1) * (tz1 - tz0 + 1);
        if (covered > StatTileScanMax) return globalRange;
        int seen = 0;
        for (double tz = tz0; tz <= tz1; tz += 1)
        for (double tx = tx0; tx <= tx1; tx += 1)
        {
            if (!stats.TryGetValue(HeightTiles.Key(tx, tz), out var s)) continue;
            seen++;
            if (s.Min < min) min = s.Min;
            if (s.Max > max) max = s.Max;
        }
        if (seen == 0) return globalRange;
        if (seen < covered) { min = Math.Min(min, 0); max = Math.Max(max, 0); }
        return new NodeStatSpan(min, max);
    }

    private static double BoxDistance(double px, double py, double pz, double x0, double y0, double z0,
                                      double x1, double y1, double z1)
    {
        double dx = Math.Max(Math.Max(x0 - px, 0), px - x1);
        double dy = Math.Max(Math.Max(y0 - py, 0), py - y1);
        double dz = Math.Max(Math.Max(z0 - pz, 0), pz - z1);
        return Math.Sqrt(dx * dx + dy * dy + dz * dz);
    }

    /// <summary>
    /// <c>selectLodNodes</c>: the quadtree walk from the root squares — a node splits while the camera's 3D box
    /// distance is inside its inner ring (or its level is above the water cap); a child that would not split again is
    /// emitted as a PARENT QUADRANT (half size, 16 cells, parent spacing). No frustum culling; at most 4096 nodes.
    /// </summary>
    public static List<LodNode> SelectLodNodes(LodSelectOpts o)
    {
        var nodes = new List<LodNode>();
        int levels = (int)Math.Max(1, Math.Min(Math.Floor(o.Levels), MaxLodLevels));
        double leaf = o.LeafM;
        if (!(leaf > 0) || !(o.X1 > o.X0) || !(o.Z1 > o.Z0)) return nodes;
        int top = levels - 1;
        IReadOnlyList<double> ranges = o.Ranges ?? LodRanges(o.MinLodDistance, levels, o.LevelErrorM, o.PixelScale);
        double? Probe(double x, double z, double size)
        {
            if (x >= o.X1 || z >= o.Z1 || x + size <= o.X0 || z + size <= o.Z0) return null;
            var b = o.BoundsOf(x, z, size);
            return BoxDistance(o.CamX, o.CamY, o.CamZ, x, b.Min, z, x + size, b.Max, z + size);
        }
        var capOf = o.LodCapOf ?? ((_, _, _) => LodCapNone);
        void Emit(double x, double z, double size, int level, int cells, double d, double cap)
            => nodes.Add(new LodNode(x, z, size, level, cells, Math.Max(Math.Min(LodLambda(d, ranges), cap) - level, 0)));
        void Visit(double x, double z, int level, double d)
        {
            if (nodes.Count >= MaxNodes) return;
            double size = leaf * (1 << level);
            // ranges[level − 1]; an index past the list is JS undefined, which no comparison passes (NaN here).
            double inner = level > 0 ? (level - 1 < ranges.Count ? ranges[level - 1] : double.NaN) : 0;
            double cap = capOf(x, z, size);
            if (level > 0 && ((inner > 0 && d < inner) || level > cap))
            {
                double half = size / 2;
                for (int q = 0; q < 4; q++)
                {
                    double cx = x + ((q & 1) != 0 ? half : 0);
                    double cz = z + ((q & 2) != 0 ? half : 0);
                    if (Probe(cx, cz, half) is not { } cd) continue;
                    double ccap = capOf(cx, cz, half);
                    if (cd < inner || level > ccap) Visit(cx, cz, level - 1, cd);
                    else Emit(cx, cz, half, level, PatchN / 2, cd, ccap);
                    if (nodes.Count >= MaxNodes) return;
                }
                return;
            }
            Emit(x, z, size, level, PatchN, d, cap);
        }
        double rootSize = leaf * (1 << top);
        double rx0 = Math.Floor(o.X0 / rootSize), rx1 = Math.Floor((o.X1 - 1e-6) / rootSize);
        double rz0 = Math.Floor(o.Z0 / rootSize), rz1 = Math.Floor((o.Z1 - 1e-6) / rootSize);
        for (double rz = rz0; rz <= rz1; rz += 1)
        for (double rx = rx0; rx <= rx1; rx += 1)
            if (Probe(rx * rootSize, rz * rootSize, rootSize) is { } d) Visit(rx * rootSize, rz * rootSize, top, d);
        return nodes;
    }

    /// <summary>
    /// <c>selectLodFitted</c>: <see cref="SelectLodNodes"/>, and while it reaches 4096 nodes the rings are halved and
    /// the water cap relaxed by one more level, at most 8 times. (The browser warns once when that happens; the
    /// answer carries the count, so a caller can.)
    /// </summary>
    public static LodSelection SelectLodFitted(LodSelectOpts o)
    {
        int levels = (int)Math.Max(1, Math.Min(Math.Floor(o.Levels), MaxLodLevels));
        var ranges = o.Ranges is not null ? o.Ranges.ToList() : LodRanges(o.MinLodDistance, levels, o.LevelErrorM, o.PixelScale);
        var nodes = SelectLodNodes(o with { Ranges = ranges });
        int step = 0;
        while (nodes.Count >= MaxNodes && step < MaxFitSteps)
        {
            step++;
            ranges = ranges.Select(r => r / 2).ToList();
            int relax = step;
            var capped = o.LodCapOf;
            nodes = SelectLodNodes(o with
            {
                Ranges = ranges,
                LodCapOf = capped is not null ? (x, z, s) => capped(x, z, s) + relax : null,
            });
        }
        return new LodSelection(nodes, ranges, step, step);
    }

    // ── Pyramids ───────────────────────────────────────────────────────────

    /// <summary>
    /// <c>buildPyramid</c>: level 0 = <paramref name="at"/> on the cols × rows lattice (at least 2 × 2), each next level
    /// every second point of the one before, while both sides keep ≥ 2 points; stored as float32.
    /// </summary>
    public static HeightPyramid BuildPyramid(Func<double, double, double> at, double originX, double originZ, double step,
                                             double cols, double rows, int levelCount)
    {
        var levels = new List<PyramidLevel>();
        int c = (int)Math.Max(2, Math.Floor(cols)), r = (int)Math.Max(2, Math.Floor(rows));
        double s = step;
        int height = 0;
        for (int k = 0; k < levelCount; k++)
        {
            levels.Add(new PyramidLevel(c, r, s, height));
            height += r;
            int nc = (c - 1) / 2 + 1, nr = (r - 1) / 2 + 1;
            if (nc < 2 || nr < 2) break;
            c = nc;
            r = nr;
            s *= 2;
        }
        int texW = levels[0].Cols;
        var data = new float[texW * height];
        var b = levels[0];
        for (int j = 0; j < b.Rows; j++)
        {
            double z = originZ + j * step;
            int row = j * texW;
            for (int i = 0; i < b.Cols; i++) data[row + i] = (float)at(originX + i * step, z);
        }
        for (int k = 1; k < levels.Count; k++)
        {
            var lv = levels[k];
            var prev = levels[k - 1];
            for (int j = 0; j < lv.Rows; j++)
            {
                int src = (prev.Row0 + j * 2) * texW, dst = (lv.Row0 + j) * texW;
                for (int i = 0; i < lv.Cols; i++) data[dst + i] = data[src + i * 2];
            }
        }
        return new HeightPyramid(originX, originZ, step, levels, data, texW, height);
    }

    private static PyramidLevel? LevelOf(HeightPyramid pyr, int k)
        => pyr.Levels.Count == 0 ? null : pyr.Levels[Math.Max(0, Math.Min(k, pyr.Levels.Count - 1))];

    private static double Texel(HeightPyramid pyr, PyramidLevel lv, int i, int j, double missing)
    {
        int k = (lv.Row0 + j) * pyr.TexW + i;
        return k >= 0 && k < pyr.Data.Length ? pyr.Data[k] : missing;
    }

    /// <summary><c>pyramidHeight(pyr, x, z, k)</c>: <c>latticeSample</c> of level k (clamped); no pyramid = 0.</summary>
    public static double PyramidHeight(HeightPyramid? pyr, double x, double z, int k)
    {
        if (pyr is null || LevelOf(pyr, k) is not { } lv) return 0;
        return HeightGrid.LatticeSample((i, j) => Texel(pyr, lv, i, j, 0), lv.Cols, lv.Rows, pyr.OriginX, pyr.OriginZ, lv.Step, x, z);
    }

    /// <summary><c>wlevelAt(pyr, x, z, k)</c>: the water level of level k, masked bilinear; NaN = dry.</summary>
    public static double WaterLevelAt(HeightPyramid? pyr, double x, double z, int k)
    {
        if (pyr is null || LevelOf(pyr, k) is not { } lv || lv.Cols < 2 || lv.Rows < 2 || !(lv.Step > 0)) return double.NaN;
        static (int I, double T) Frac(double v, int n)
        {
            double c = v < 0 ? 0 : v > n - 1 ? n - 1 : v;
            int i = (int)Math.Min(Math.Floor(c), n - 2);
            return (i, c - i);
        }
        var (i, tx) = Frac((x - pyr.OriginX) / lv.Step, lv.Cols);
        var (j, tz) = Frac((z - pyr.OriginZ) / lv.Step, lv.Rows);
        double At(int a, int b) => Texel(pyr, lv, a, b, double.NaN);
        return WaterRaster.WaterBilinear(At(i, j), At(i + 1, j), At(i, j + 1), At(i + 1, j + 1), tx, tz);
    }

    /// <summary><c>pyramidLevelFor(pyr, stepM)</c>: round(log2(step / base step)), clamped to the levels.</summary>
    public static int PyramidLevelFor(HeightPyramid? pyr, double stepM)
    {
        if (pyr is null || !(pyr.Step > 0)) return 0;
        double k = Scatter.Js.Round(Math.Log2(Math.Max(stepM / pyr.Step, 1)));
        return (int)Math.Max(0, Math.Min(k, pyr.Levels.Count - 1));
    }

    /// <summary><c>gpuHeightAt</c>: the near pyramid inside its rectangle, else the far one, at the node step's level.</summary>
    public static double GpuHeightAt(HeightPyramid? near, IReadOnlyList<double>? nearRect, HeightPyramid? far,
                                     double x, double z, double nodeStep)
    {
        if (near is not null && nearRect is not null && x >= nearRect[0] && x <= nearRect[2] && z >= nearRect[1] && z <= nearRect[3])
            return PyramidHeight(near, x, z, PyramidLevelFor(near, nodeStep));
        return PyramidHeight(far, x, z, PyramidLevelFor(far, nodeStep));
    }

    /// <summary><c>gpuWaterAt</c>: the water pyramid inside the near rectangle, NaN elsewhere.</summary>
    public static double GpuWaterAt(HeightPyramid? water, IReadOnlyList<double>? nearRect, double x, double z, double nodeStep)
    {
        if (water is null || nearRect is null) return double.NaN;
        if (x < nearRect[0] || x > nearRect[2] || z < nearRect[1] || z > nearRect[3]) return double.NaN;
        return WaterLevelAt(water, x, z, PyramidLevelFor(water, nodeStep));
    }

    /// <summary><c>gpuWaterSdAt</c>: the sd field, bilinear inside its lattice; outside or none = dry.</summary>
    public static double GpuWaterSdAt(SdField? sd, double x, double z)
    {
        if (sd is null || sd.Cols < 2 || sd.Rows < 2 || !(sd.Step > 0)) return WaterTileField.SdDry;
        double fx = (x - sd.OriginX) / sd.Step, fz = (z - sd.OriginZ) / sd.Step;
        if (fx < 0 || fz < 0 || fx > sd.Cols - 1 || fz > sd.Rows - 1) return WaterTileField.SdDry;
        int i = (int)Math.Min(Math.Floor(fx), sd.Cols - 2), j = (int)Math.Min(Math.Floor(fz), sd.Rows - 2);
        double tx = fx - i, tz = fz - j;
        double At(int a, int b) => b * sd.Cols + a < sd.Data.Length ? sd.Data[b * sd.Cols + a] : WaterTileField.SdDry;
        double north = At(i, j) * (1 - tx) + At(i + 1, j) * tx;
        double south = At(i, j + 1) * (1 - tx) + At(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz;
    }

    // ── Morph twins ────────────────────────────────────────────────────────

    /// <summary>
    /// <c>morphedVertex</c>: the CPU twin of the vertex shader's block morph — the patch point snapped between the
    /// 2^k and 2^(k+1) lattices by the fraction of t, clamped to the extent, its height mixed between the two mips
    /// (each lifted onto the water). <paramref name="t"/> null = the node's morph.
    /// </summary>
    public static LodVertexPos MorphedVertex(LodNode node, double gx, double gz, HeightPyramid? near, IReadOnlyList<double>? nearRect,
                                             HeightPyramid? far, IReadOnlyList<double>? extent = null, double? t = null,
                                             HeightPyramid? water = null, SdField? sd = null)
    {
        double tt = t ?? node.Morph;
        double nodeStep = node.Size / node.Cells;
        int k = (int)Math.Min(Math.Floor(Math.Max(tt, 0)), MaxLodLevels - 1);
        double f = Math.Max(tt, 0) - k;
        double m1 = Math.Pow(2, k), m2 = m1 * 2;
        double Snap(double g)
        {
            double gc = Math.Min(g, node.Cells);
            return (gc - gc % m1) * (1 - f) + (gc - gc % m2) * f;
        }
        double x = node.X + Snap(gx) * nodeStep;
        double z = node.Z + Snap(gz) * nodeStep;
        if (extent is not null)
        {
            x = Math.Min(Math.Max(x, extent[0]), extent[2]);
            z = Math.Min(Math.Max(z, extent[1]), extent[3]);
        }
        double sdw = sd is not null ? GpuWaterSdAt(sd, x, z) : WaterShade.SdBandM;
        double own = WaterShade.Lifted(GpuHeightAt(near, nearRect, far, x, z, nodeStep * m1),
                                       GpuWaterAt(water, nearRect, x, z, nodeStep * m1), sdw);
        double parent = WaterShade.Lifted(GpuHeightAt(near, nearRect, far, x, z, nodeStep * m2),
                                          GpuWaterAt(water, nearRect, x, z, nodeStep * m2), sdw);
        return new LodVertexPos(x, z, own * (1 - f) + parent * f, tt);
    }

    /// <summary>
    /// <c>lodVertex</c>: the full vertex from a camera — t from the 3D distance to the vertex's own finest height,
    /// the block descent j = 5..1 that hands a vertex the morph of the coarsest block corner already past its level,
    /// then <see cref="MorphedVertex"/>. <see cref="LodVertexPos.T"/> is that owner's t.
    /// </summary>
    public static LodVertexPos LodVertex(LodNode node, double gx, double gz, HeightPyramid? near, IReadOnlyList<double>? nearRect,
                                         HeightPyramid? far, IReadOnlyList<double>? extent, LodCamera cam, IReadOnlyList<double> ranges,
                                         HeightPyramid? water = null, Func<double, double, double>? capAt = null, SdField? sd = null)
    {
        double nodeStep = node.Size / node.Cells;
        double TAt(double ix, double iz)
        {
            double x = node.X + ix * nodeStep, z = node.Z + iz * nodeStep;
            if (extent is not null)
            {
                x = Math.Min(Math.Max(x, extent[0]), extent[2]);
                z = Math.Min(Math.Max(z, extent[1]), extent[3]);
            }
            double y = GpuHeightAt(near, nearRect, far, x, z, 0);
            double dx = x - cam.X, dy = y - cam.Y, dz = z - cam.Z;
            double d = Math.Sqrt(dx * dx + dy * dy + dz * dz);
            double cap = capAt is not null ? capAt(x, z) : LodCapNone;
            return Math.Max(Math.Min(LodLambda(d, ranges), cap) - node.Level, 0);
        }
        double gi = Math.Min(gx, node.Cells), gj = Math.Min(gz, node.Cells);
        int k = 0;
        double t = TAt(gi, gj);
        for (int j = MaxLodLevels - 1; j >= 1; j--)
        {
            double m = Math.Pow(2, j);
            double tj = TAt(gi - gi % m, gj - gj % m);
            if (Math.Floor(tj) >= j) { k = j; t = tj; break; }
        }
        var v = MorphedVertex(node, gx, gz, near, nearRect, far, extent, k + Math.Min(Math.Max(t - k, 0), 1), water, sd);
        return v with { T = t };
    }

    // ── The water mip cap ──────────────────────────────────────────────────

    /// <summary>
    /// <c>waterTileCaps</c>: per tile the coarsest level k whose (2^k + 1)² texel block around some fully lifted
    /// texel is fully lifted (summed-area table over "water above ground and inside the outline"), in first-seen order.
    /// </summary>
    public static List<KeyValuePair<string, int>> WaterTileCaps(HeightPyramid? water, HeightPyramid? height, double tileM,
                                                                SdField? sd, int levelCount = MaxLodLevels)
    {
        var order = new List<string>();
        var caps = new Dictionary<string, int>(StringComparer.Ordinal);
        List<KeyValuePair<string, int>> Result() => order.Select(k => new KeyValuePair<string, int>(k, caps[k])).ToList();
        if (water is null || height is null || water.Levels.Count == 0 || height.Levels.Count == 0 || !(tileM > 0)) return Result();
        var wl = water.Levels[0];
        var hl = height.Levels[0];
        if (wl.Cols != hl.Cols || wl.Rows != hl.Rows) return Result();
        int top = Math.Min(levelCount, water.Levels.Count) - 1;
        if (top < 0) return Result();
        int cols = wl.Cols, rows = wl.Rows, w1 = cols + 1;
        var sat = new int[w1 * (rows + 1)];
        bool sdOk = sd is not null && sd.Cols == cols && sd.Rows == rows;
        for (int j = 0; j < rows; j++)
        {
            int wrow = (wl.Row0 + j) * water.TexW, hrow = (hl.Row0 + j) * height.TexW, srow = j * cols;
            int run = 0;
            for (int i = 0; i < cols; i++)
            {
                double sdv = sdOk && srow + i < sd!.Data.Length ? sd.Data[srow + i] : WaterTileField.SdDry;
                if (water.Data[wrow + i] > height.Data[hrow + i] && (!sdOk || sdv > 0)) run++;
                sat[(j + 1) * w1 + i + 1] = sat[j * w1 + i + 1] + run;
            }
        }
        bool Solid(int i0, int j0, int i1, int j1)
        {
            if (i0 < 0 || j0 < 0 || i1 >= cols || j1 >= rows) return false;
            int sum = sat[(j1 + 1) * w1 + i1 + 1] - sat[j0 * w1 + i1 + 1] - sat[(j1 + 1) * w1 + i0] + sat[j0 * w1 + i0];
            return sum == (i1 - i0 + 1) * (j1 - j0 + 1);
        }
        for (int j = 0; j < rows; j++)
        {
            double z = water.OriginZ + j * water.Step;
            for (int i = 0; i < cols; i++)
            {
                if (!Solid(i, j, i, j)) continue;
                var key = HeightTiles.TileKeyAt(tileM, water.OriginX + i * water.Step, z);
                int prev = caps.TryGetValue(key, out var p) ? p : -1;
                if (prev >= top) continue;
                int k = top;
                while (k > 0)
                {
                    int r = 1 << (k - 1);
                    if (Solid(i - r, j - r, i + r, j + r)) break;
                    k--;
                }
                if (k > prev)
                {
                    if (prev < 0) order.Add(key);
                    caps[key] = k;
                }
            }
        }
        return Result();
    }

    /// <summary>
    /// <c>buildLodCapGrid</c>: a corner field over the capped tiles plus a two-tile ring — each corner the minimum of
    /// its four tiles' caps (an unlisted tile = <see cref="LodCapNone"/>); no caps = null.
    /// </summary>
    public static LodCapGrid? BuildLodCapGrid(IReadOnlyList<KeyValuePair<string, double>> caps, double tileM)
    {
        if (caps.Count == 0 || !(tileM > 0)) return null;
        var byKey = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var (k, v) in caps) byKey[k] = v;
        double tx0 = double.PositiveInfinity, tz0 = double.PositiveInfinity;
        double tx1 = double.NegativeInfinity, tz1 = double.NegativeInfinity;
        foreach (var (key, _) in caps)
        {
            if (!LayerCut.TryKey(key, out var tx, out var tz)) continue;
            tx0 = Math.Min(tx0, tx); tz0 = Math.Min(tz0, tz);
            tx1 = Math.Max(tx1, tx); tz1 = Math.Max(tz1, tz);
        }
        if (!double.IsFinite(tx0)) return null;
        int cols = (int)(tx1 - tx0 + 4), rows = (int)(tz1 - tz0 + 4);
        var grid = new float[cols * rows];
        double CapOf(double tx, double tz) => byKey.TryGetValue(HeightTiles.Key(tx, tz), out var c) ? c : LodCapNone;
        double min = LodCapNone;
        for (int b = 0; b < rows; b++)
        for (int a = 0; a < cols; a++)
        {
            double tx = tx0 - 2 + a, tz = tz0 - 2 + b;
            double v = Math.Min(Math.Min(CapOf(tx, tz), CapOf(tx + 1, tz)), Math.Min(CapOf(tx, tz + 1), CapOf(tx + 1, tz + 1)));
            grid[b * cols + a] = (float)v;
            if (v < min) min = v;
        }
        return new LodCapGrid((tx0 - 1) * tileM, (tz0 - 1) * tileM, tileM, cols, rows, grid, min);
    }

    /// <summary><c>lodCapAt</c>: the cap at a point, bilinear over the corner field; on or past its border = none.</summary>
    public static double LodCapAt(LodCapGrid? grid, double x, double z)
    {
        if (grid is null || grid.Cols < 2 || grid.Rows < 2 || !(grid.Step > 0)) return LodCapNone;
        double fx = (x - grid.X0) / grid.Step, fz = (z - grid.Z0) / grid.Step;
        if (fx <= 0 || fz <= 0 || fx >= grid.Cols - 1 || fz >= grid.Rows - 1) return LodCapNone;
        int i = (int)Math.Floor(fx), j = (int)Math.Floor(fz);
        double tx = fx - i, tz = fz - j;
        double At(int a, int b) => grid.Caps[b * grid.Cols + a];
        double north = At(i, j) * (1 - tx) + At(i + 1, j) * tx;
        double south = At(i, j + 1) * (1 - tx) + At(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz;
    }

    /// <summary><c>lodCapOverSquare</c>: the smallest corner cap over a node square plus one corner each side; more than
    /// 289 corners = the grid's minimum; outside the grid = none.</summary>
    public static double LodCapOverSquare(LodCapGrid? grid, double x, double z, double size)
    {
        if (grid is null || grid.Cols < 2 || grid.Rows < 2 || !(grid.Step > 0)) return LodCapNone;
        static int Lo(double v, int n) => (int)Math.Max(0, Math.Min(Math.Floor(v) - 1, n - 1));
        static int Hi(double v, int n) => (int)Math.Max(0, Math.Min(Math.Floor(v) + 1, n - 1));
        double fx0 = (x - grid.X0) / grid.Step, fz0 = (z - grid.Z0) / grid.Step;
        double fx1 = fx0 + size / grid.Step, fz1 = fz0 + size / grid.Step;
        if (fx1 <= 0 || fz1 <= 0 || fx0 >= grid.Cols - 1 || fz0 >= grid.Rows - 1) return LodCapNone;
        int i0 = Lo(fx0, grid.Cols), i1 = Hi(fx1, grid.Cols), j0 = Lo(fz0, grid.Rows), j1 = Hi(fz1, grid.Rows);
        if ((i1 - i0 + 1) * (j1 - j0 + 1) > LodCapScanMax) return grid.Min;
        double min = LodCapNone;
        for (int b = j0; b <= j1; b++)
        for (int a = i0; a <= i1; a++)
        {
            double v = grid.Caps[b * grid.Cols + a];
            if (v < min) min = v;
        }
        return min;
    }
}
