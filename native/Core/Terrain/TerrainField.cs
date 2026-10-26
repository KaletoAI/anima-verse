using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Ground;
using AnimaNative.Overview;
using AnimaNative.Water;
using AnimaNative.World;

namespace AnimaNative.Terrain;

/// <summary>One frame's CDLOD pieces, split by program (<c>createTerrainLod.update</c>): the dry list, the wet list (the
/// lifting water variant), the rings used, what the budget had to relax, and the browser's triangle count
/// (Σ cells² · 2 — a parent quadrant counts its 16², not the patch's degenerate rest).</summary>
public sealed record TerrainFrame(List<LodNode> Dry, List<LodNode> Wet, List<double> Ranges, int CapRelax, int Coarsenings,
                                  int Triangles)
{
    public int Nodes => Dry.Count + Wet.Count;
    /// <summary>Draw calls of the terrain (one per non-empty program; Godot's depth pre-pass doubles what it reports).</summary>
    public int Draws => (Dry.Count > 0 ? 1 : 0) + (Wet.Count > 0 ? 1 : 0);
}

/// <summary>
/// Everything the terrain's two programs read, as the numbers the GPU gets — the uniform objects of
/// <c>terrainLod.ts</c> (<c>uTlodNear</c>, <c>uTlodNearGeom</c>, <c>uTlodNearLevel</c>, …). Geometry vectors are
/// (originX, originZ, step, level count); a level row is (cols, rows, step, first texture row). A null texture = the
/// neutral one (its geometry then says "none", so the shader never reads it).
/// </summary>
public sealed record TerrainUniforms(
    HeightPyramid? Near, double[] NearGeom, double[][] NearLevels, double[] NearRect,
    HeightPyramid? Far, double[] FarGeom, double[][] FarLevels,
    double[] Extent, double BaseStep, double NormalSpan,
    LodCapGrid? Cap, double[] CapGeom,
    HeightPyramid? Water, double[] WaterGeom, double[][] WaterLevels, SdField? WaterSd);

/// <summary>
/// The CPU half of the browser's CDLOD terrain (<c>client3d/src/scene/terrainLod.ts</c> <c>createTerrainLod</c>:
/// <c>setField</c>, <c>setExtent</c>, <c>update</c>) on top of the vector-checked maths of <see cref="TerrainLod"/>:
///
///   • the FAR pyramid from the overview grid (<c>buildFar</c>: round-to-nearest lattice read, non-finite = 0), the
///     NEAR pyramid over the loaded tiles' window (<c>buildNear</c>: <see cref="TerrainLod.NearWindow"/> filled through
///     the tile-first <see cref="WorldHeight.GroundAt"/>), both decimated by <see cref="TerrainLod.BuildPyramid"/>;
///   • the water (Wasser v2 K-A): the level pyramid and the signed-distance field on the NEAR lattice, the wet tile
///     set of the partition, and the water mip cap (<see cref="TerrainLod.WaterTileCaps"/> → <see cref="TerrainLod.BuildLodCapGrid"/>);
///   • the global height range (the first levels of both pyramids, starting from 0 like the browser), the per-level
///     errors from every known tile statistic, the node bounds;
///   • per frame <see cref="Select"/>: <see cref="TerrainLod.SelectLodFitted"/> over the world frame plus the dry/wet
///     partition (<see cref="NodeHasWater"/>).
///
/// No Godot here: the client hands the pyramids to R32F textures and the frame's nodes to two MultiMeshes.
/// </summary>
public sealed class TerrainField
{
    /// <summary><c>BASE_MARGIN_M</c> (ground.ts): the frame reaches this far past <c>world_bounds</c>.</summary>
    public const double BaseMarginM = 60;
    /// <summary><c>BASE_FALLBACK_M</c>: the square drawn when nothing is placed at all.</summary>
    public const double BaseFallbackM = 200;
    /// <summary><c>FALLBACK_BASE_STEP_M</c>: the leaf lattice step when the payload names none.</summary>
    public const double FallbackBaseStepM = 2;
    /// <summary><c>WATER_TILE_SCAN_MAX</c>: a piece over more tiles than this is wet without looking.</summary>
    public const int WaterTileScanMax = 81;

    public double BaseStep { get; private init; }
    /// <summary>The leaf node edge, <see cref="TerrainLod.PatchN"/> · base step.</summary>
    public double LeafM { get; private init; }
    public HeightPyramid? Far { get; private init; }
    public HeightPyramid? Near { get; private init; }
    /// <summary>The near pyramid's support rectangle [x0, z0, x1, z1] (null without one).</summary>
    public double[]? NearRect { get; private init; }
    public HeightPyramid? Water { get; private init; }
    public SdField? Sd { get; private init; }
    public LodCapGrid? CapGrid { get; private init; }
    /// <summary>The wet tile keys of the partition (null = no water program at all).</summary>
    public IReadOnlySet<string>? WaterTileKeys { get; private init; }
    public double WaterTileM { get; private init; }
    public NodeStatSpan GlobalRange { get; private init; }
    public double[] LevelErrorM { get; private set; } = new double[TerrainLod.MaxLodLevels];
    /// <summary>The world frame [x0, z0, x1, z1] every vertex is clamped to (<c>setExtent</c>).</summary>
    public double[] Extent { get; private set; } = { -100, -100, 100, 100 };

    /// <summary>
    /// <c>setExtent</c> again (<c>rebuildBase(bounds)</c> on every sync): a new frame for the same field. The memos stay
    /// — they are keyed by quadtree squares, whose bounds, caps and wet verdicts do not depend on the frame. Answers
    /// whether the frame moved (the uniform then has to follow).
    /// </summary>
    public bool SetExtent(double[] extent)
    {
        if (extent.Length != 4 || extent.SequenceEqual(Extent)) return false;
        Extent = (double[])extent.Clone();
        return true;
    }

    private readonly Dictionary<string, NodeStatSpan> _spans = new(StringComparer.Ordinal);
    /// <summary>The node squares are fixed quadtree cells: their bounds, caps and wet verdicts are memoised (the bounds until the stats change)
    /// (a cache, not a second rule — <see cref="TerrainLod.NodeBounds"/> / <see cref="TerrainLod.LodCapOverSquare"/> fill it).</summary>
    private readonly Dictionary<(double, double, double), NodeStatSpan> _boundsMemo = new();
    private readonly Dictionary<(double, double, double), double> _capMemo = new();
    private readonly Dictionary<(double, double, double), bool> _wetMemo = new();
    private IReadOnlyDictionary<string, TileStat> _stats = new Dictionary<string, TileStat>();
    private double[] _mipLevelsM = Array.Empty<double>();
    private double _tileM;

    /// <summary>
    /// <c>plateExtent</c> + <c>setExtent</c>: <c>world_bounds</c> grown by <see cref="BaseMarginM"/>, or the
    /// <see cref="BaseFallbackM"/> square round the origin without bounds; the far edge at least 1 m past the near one.
    /// </summary>
    public static double[] ExtentOf(BoundsXZ? bounds)
    {
        double x0, z0, x1, z1;
        if (bounds is not { } b)
        {
            double h = BaseFallbackM / 2;
            (x0, z0, x1, z1) = (-h, -h, h, h);
        }
        else (x0, z0, x1, z1) = (b.MinX - BaseMarginM, b.MinZ - BaseMarginM, b.MaxX + BaseMarginM, b.MaxZ + BaseMarginM);
        return new[] { x0, z0, Math.Max(x1, x0 + 1), Math.Max(z1, z0 + 1) };
    }

    /// <summary>The screen-space error scale of the rings: the drawing buffer's height over 2·tan(fov/2) (TL:3509).</summary>
    public static double PixelScale(double viewportPx, double fovDeg)
        => fovDeg > 0 && viewportPx > 0 ? viewportPx / (2 * Math.Tan(fovDeg * Math.PI / 360)) : 0;

    /// <summary>
    /// <c>nodeHasWater</c>: does a piece need the lifting program — any wet tile key inside its CLOSED rectangle
    /// (<c>floor((x + size) / tileM)</c>, no epsilon, so a vertex shared across a tile border is covered by both pieces);
    /// more than <see cref="WaterTileScanMax"/> tiles = wet without looking; no set or no tile size = dry.
    /// </summary>
    public static bool NodeHasWater(IReadOnlySet<string>? tiles, double tileM, double x, double z, double size)
    {
        if (tiles is null || tiles.Count == 0 || !(tileM > 0)) return false;
        double tx0 = Math.Floor(x / tileM), tx1 = Math.Floor((x + size) / tileM);
        double tz0 = Math.Floor(z / tileM), tz1 = Math.Floor((z + size) / tileM);
        if ((tx1 - tx0 + 1) * (tz1 - tz0 + 1) > WaterTileScanMax) return true;
        for (double tz = tz0; tz <= tz1; tz += 1)
        for (double tx = tx0; tx <= tx1; tx += 1)
            if (tiles.Contains(HeightTiles.Key(tx, tz))) return true;
        return false;
    }

    /// <summary>
    /// <c>buildFar</c>: the overview grid at its own lattice — round-to-nearest index (exact AT the lattice points the
    /// pyramid samples), a non-finite value is 0; fewer than 2 × 2 points or no step = none.
    /// </summary>
    public static HeightPyramid? BuildFar(HeightGrid ov)
    {
        if (ov.Rows < 2 || ov.Cols < 2 || !(ov.Step > 0)) return null;
        double At(double x, double z)
        {
            double fx = Scatter.Js.Round((x - ov.OriginX) / ov.Step), fz = Scatter.Js.Round((z - ov.OriginZ) / ov.Step);
            if (fx < 0 || fz < 0 || fx >= ov.Cols || fz >= ov.Rows) return 0;
            float v = ov.At((int)fx, (int)fz);
            return float.IsFinite(v) ? v : 0;
        }
        return TerrainLod.BuildPyramid(At, ov.OriginX, ov.OriginZ, ov.Step, ov.Cols, ov.Rows, TerrainLod.MaxLodLevels);
    }

    /// <summary>
    /// <c>setField</c> + <c>setExtent</c>: the pyramids, the water fields, the cap grid, the range and the level errors
    /// of the relief held by <paramref name="height"/> (overview + loaded tiles + every known statistic), with the near
    /// window anchored on (<paramref name="anchorX"/>, <paramref name="anchorZ"/>). <paramref name="water"/> null = the
    /// dry world (no lift, no cap, no wet program — <c>--no-water</c>, or a water variant that is not there).
    /// </summary>
    /// <param name="far">The far pyramid of the field this one replaces when the overview did not change (a streamed
    /// tile batch moves only the near half): reused as it is instead of decimating the overview again.</param>
    public static TerrainField Build(WorldHeight height, double anchorX, double anchorZ, WaterRaster? water, double[] extent,
                                     HeightPyramid? far = null)
    {
        var ov = height.Overview;
        double baseStep = ov.TileStepM > 0 ? ov.TileStepM : FallbackBaseStepM;
        far ??= BuildFar(ov.Grid);
        HeightPyramid? near = null;
        double[]? nearRect = null;
        var keys = height.Tiles.Select(t => ((double)t.Key.Tx, (double)t.Key.Tz)).ToList();
        if (TerrainLod.NearWindow(keys, ov.TileM, baseStep, ov.Grid.Step, anchorX, anchorZ) is { } win)
        {
            near = TerrainLod.BuildPyramid(height.GroundAt, win.X0, win.Z0, baseStep, win.Cols, win.Rows, TerrainLod.MaxLodLevels);
            nearRect = new[] { win.X0, win.Z0, win.X0 + (win.Cols - 1) * baseStep, win.Z0 + (win.Rows - 1) * baseStep };
        }
        // globalRange: the first level of both pyramids, from (0, 0) like the browser's accumulator.
        double min = 0, max = 0;
        foreach (var pyr in new[] { near, far })
        {
            if (pyr is null || pyr.Levels.Count == 0) continue;
            var b = pyr.Levels[0];
            for (int j = 0; j < b.Rows; j++)
            {
                int row = j * pyr.TexW;
                for (int i = 0; i < b.Cols; i++)
                {
                    float v = pyr.Data[row + i];
                    if (v < min) min = v;
                    if (v > max) max = v;
                }
            }
        }
        // buildWater / buildSd: on the near pyramid's own lattice (same origin, step and base size).
        HeightPyramid? waterPyr = null;
        SdField? sd = null;
        if (near is not null && near.Levels.Count > 0 && water is { Tiles.Count: > 0 })
        {
            var b = near.Levels[0];
            waterPyr = TerrainLod.BuildPyramid((x, z) => WaterRaster.LevelAt(water, x, z), near.OriginX, near.OriginZ, near.Step,
                                               b.Cols, b.Rows, TerrainLod.MaxLodLevels);
            var data = new float[b.Cols * b.Rows];
            for (int j = 0; j < b.Rows; j++)
            {
                double z = waterPyr.OriginZ + j * waterPyr.Step;
                for (int i = 0; i < b.Cols; i++)
                    data[j * b.Cols + i] = (float)WaterRaster.SdAt(water, waterPyr.OriginX + i * waterPyr.Step, z);
            }
            sd = new SdField(waterPyr.OriginX, waterPyr.OriginZ, waterPyr.Step, b.Cols, b.Rows, data);
        }
        double waterTileM = waterPyr is not null ? water!.TileM : 0;
        IReadOnlySet<string>? wetKeys = waterPyr is not null ? water!.Tiles.Keys.ToHashSet(StringComparer.Ordinal) : null;
        var caps = TerrainLod.WaterTileCaps(waterPyr, near, waterTileM, sd, TerrainLod.MaxLodLevels)
                             .Select(kv => new KeyValuePair<string, double>(kv.Key, kv.Value)).ToList();
        var field = new TerrainField
        {
            BaseStep = baseStep,
            LeafM = TerrainLod.PatchN * baseStep,
            Far = far,
            Near = near,
            NearRect = nearRect,
            Water = waterPyr,
            Sd = sd,
            WaterTileM = waterTileM,
            WaterTileKeys = wetKeys,
            CapGrid = TerrainLod.BuildLodCapGrid(caps, waterTileM),
            GlobalRange = new NodeStatSpan(min, max),
            Extent = (double[])extent.Clone(),
        };
        field.TakeStats(height.Stats, ov.MipLevelsM, ov.TileM);
        return field;
    }

    /// <summary>
    /// The statistics the node bounds and the level errors read (<c>relief.stats</c>, <c>mipLevelsM</c>) —
    /// <c>refreshStats</c> when more arrive: only the errors are re-derived, the bounds read the map per call.
    /// </summary>
    public void TakeStats(IReadOnlyDictionary<string, TileStat> stats, IReadOnlyList<double> mipLevelsM, double tileM)
    {
        _stats = stats;
        _mipLevelsM = mipLevelsM.ToArray();
        _tileM = tileM;
        _spans.Clear();
        _boundsMemo.Clear();
        foreach (var (k, s) in stats) _spans[k] = new NodeStatSpan(s.Min, s.Max);
        LevelErrorM = TerrainLod.LevelErrorsFrom(stats.Values.Select(s => (IReadOnlyList<double>?)s.Err).ToList(), _mipLevelsM,
                                                 BaseStep, TerrainLod.MaxLodLevels);
    }

    /// <summary><c>boundsOf</c>: the node square's height span (<see cref="TerrainLod.NodeBounds"/>).</summary>
    public NodeStatSpan BoundsOf(double x, double z, double size)
    {
        if (_boundsMemo.TryGetValue((x, z, size), out var b)) return b;
        return _boundsMemo[(x, z, size)] = TerrainLod.NodeBounds(_spans, _tileM, GlobalRange, x, z, size);
    }

    private double CapOver(LodCapGrid grid, double x, double z, double size)
    {
        if (_capMemo.TryGetValue((x, z, size), out var c)) return c;
        return _capMemo[(x, z, size)] = TerrainLod.LodCapOverSquare(grid, x, z, size);
    }

    /// <summary>
    /// <c>update</c>: the frame's pieces for an eye at (<paramref name="camX"/>, <paramref name="camY"/>,
    /// <paramref name="camZ"/>) — <see cref="TerrainLod.SelectLodFitted"/> over the world frame with the rings widened by
    /// the level errors at <paramref name="pixelScale"/>, capped by the water — then each piece onto the dry or the wet
    /// program. No leaf (no field) = nothing.
    /// </summary>
    public TerrainFrame Select(double camX, double camY, double camZ, double pixelScale)
    {
        if (!(LeafM > 0)) return new TerrainFrame(new(), new(), new(), 0, 0, 0);
        var grid = CapGrid;
        var sel = TerrainLod.SelectLodFitted(new LodSelectOpts(Extent[0], Extent[1], Extent[2], Extent[3], LeafM,
                                                               TerrainLod.MaxLodLevels, TerrainLod.MinLodDistanceM,
                                                               camX, camY, camZ, (x, z, s) => BoundsOf(x, z, s))
        {
            LevelErrorM = LevelErrorM,
            PixelScale = pixelScale,
            LodCapOf = grid is not null ? (x, z, s) => CapOver(grid, x, z, s) : null,
        });
        var dry = new List<LodNode>();
        var wet = new List<LodNode>();
        int triangles = 0;
        foreach (var n in sel.Nodes)
        {
            if (!_wetMemo.TryGetValue((n.X, n.Z, n.Size), out bool isWet))
                _wetMemo[(n.X, n.Z, n.Size)] = isWet = NodeHasWater(WaterTileKeys, WaterTileM, n.X, n.Z, n.Size);
            (isWet ? wet : dry).Add(n);
            triangles += n.Cells * n.Cells * 2;
        }
        var ranges = Enumerable.Range(0, TerrainLod.MaxLodLevels).Select(i => i < sel.Ranges.Count ? sel.Ranges[i] : 0).ToList();
        return new TerrainFrame(dry, wet, ranges, sel.CapRelax, sel.Coarsenings, triangles);
    }

    /// <summary>
    /// How much of the world frame the frame's pieces cover: Σ area(piece ∩ frame) over the frame's area. The pieces are
    /// disjoint quadtree squares, so 1 means the frame is covered without a hole (and the clamp to the frame closes the
    /// edge) — the "no hole at the world edge" reading of a headless run.
    /// </summary>
    public double Coverage(TerrainFrame frame)
    {
        double x0 = Extent[0], z0 = Extent[1], x1 = Extent[2], z1 = Extent[3];
        double total = (x1 - x0) * (z1 - z0);
        if (!(total > 0)) return 0;
        double sum = 0;
        foreach (var n in frame.Dry.Concat(frame.Wet))
        {
            double w = Math.Min(n.X + n.Size, x1) - Math.Max(n.X, x0), d = Math.Min(n.Z + n.Size, z1) - Math.Max(n.Z, z0);
            if (w > 0 && d > 0) sum += w * d;
        }
        return sum / total;
    }

    /// <summary>The cap the vertex stage reads at a point (<c>tlodCapAt</c> + the budget's relaxation; none = <see cref="TerrainLod.LodCapNone"/>).</summary>
    public double CapAt(double x, double z, int capRelax)
        => CapGrid is null ? TerrainLod.LodCapNone : TerrainLod.LodCapAt(CapGrid, x, z) + capRelax;

    /// <summary>
    /// <c>uploadPyramids</c>: what the programs are handed — the geometry vectors, the level rows (zero past the
    /// pyramid's own levels), the near rectangle ((0, 0, −1, −1) without one), the frame, and the cap grid's
    /// (x0, z0, step, cols); its rows go into the per-frame <c>tl_cap_fit</c> with the relaxation.
    /// </summary>
    public TerrainUniforms Uniforms()
    {
        static double[] Geom(HeightPyramid? p) => p is null ? new double[] { 0, 0, 1, 0 } : new[] { p.OriginX, p.OriginZ, p.Step, p.Levels.Count };
        static double[][] Levels(HeightPyramid? p)
        {
            var rows = new double[TerrainLod.MaxLodLevels][];
            for (int i = 0; i < rows.Length; i++)
                rows[i] = p is not null && i < p.Levels.Count
                    ? new double[] { p.Levels[i].Cols, p.Levels[i].Rows, p.Levels[i].Step, p.Levels[i].Row0 }
                    : new double[] { 0, 0, 0, 0 };
            return rows;
        }
        var cap = CapGrid;
        return new TerrainUniforms(
            Near, Geom(Near), Levels(Near), Near is not null && NearRect is not null ? (double[])NearRect.Clone() : new double[] { 0, 0, -1, -1 },
            Far, Geom(Far), Levels(Far),
            (double[])Extent.Clone(), BaseStep, BaseStep,
            cap, cap is null ? new double[] { 0, 0, 1, 0 } : new[] { cap.X0, cap.Z0, cap.Step, cap.Cols },
            Water, Geom(Water), Levels(Water), Sd);
    }

    /// <summary>The fragment normal's lattices: level 0 of the near and the far pyramid (<see cref="TerrainNormal"/>).</summary>
    public (HeightLattice? Near, HeightLattice? Far) NormalLattices() => (TerrainNormal.Level0(Near), TerrainNormal.Level0(Far));

    /// <summary>One log/stats line: the pyramids, the frame, the water.</summary>
    public string Summary()
    {
        static string P(HeightPyramid? p) => p is null ? "none" : $"{p.Levels[0].Cols}x{p.Levels[0].Rows}/{p.Levels.Count}@{p.Step:0.###}";
        return $"near={P(Near)} far={P(Far)} extent=({Extent[0]:0.###},{Extent[1]:0.###},{Extent[2]:0.###},{Extent[3]:0.###}) "
               + $"range=({GlobalRange.Min:0.###},{GlobalRange.Max:0.###}) water={(Water is null ? "none" : $"{WaterTileKeys!.Count} tiles")} "
               + $"cap={(CapGrid is null ? "none" : $"{CapGrid.Cols}x{CapGrid.Rows} min {CapGrid.Min:0.#}")}";
    }
}
