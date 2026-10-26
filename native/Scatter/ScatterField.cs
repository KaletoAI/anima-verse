using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Api;
using Godot;

namespace AnimaNative.Scatter;

/// <summary>What a layer draws right now: instances in the buffers, the triangles they contribute.</summary>
public readonly record struct LayerCounts(int Meshes, int Instances, long Triangles, int BaseInstances)
{
    public override string ToString() => $"meshes={Meshes} instances={Instances} triangles={Triangles} base={BaseInstances}";
}

/// <summary>
/// The AUTHORED scatter of the painted areas (trees, bushes, rocks) — a port of the scatter half of
/// <c>client3d/src/scene/ground.ts</c> (<c>buildScatter</c> → <c>binProp</c> → <c>mountUrl</c>), drawn
/// with one <see cref="MultiMeshInstance3D"/> per (row, model variant, tier):
///
///   · WHERE: the 64 m cell window of <c>wantedScatterCells</c> around the anchor (k = ceil(cull/64)),
///     each cell sampled by the shared <c>scatterCellInstances</c> (exact C# port), areas bottom to top,
///     one occupancy grid per cell over the whole pass, footprints = location outlines + prop boxes,
///     occluders = the areas painted above, clearance = estimate until the mesh is measured, then a
///     re-sample 250 ms later (<c>noteSpread</c>);
///   · WHAT: the tuft cone until the GLB lands, then the <c>low</c> tier on the cheap buffer and — once an
///     instance is within the far distance — the <c>full</c> tier on its own buffer;
///   · LOD: per instance, <c>instanceTier</c> (hysteresis 35–45 m), <c>instanceVisible</c> (hash thinning
///     to 0.25 at 120 m), <c>inViewCone</c>, the entry-wide sphere test first; buffers re-filled on every
///     pass, uploaded only when the set changed.
///
/// NOT ported (each named in the S3 report with the side it favours): the impostor billboards beyond the
/// cull line (<c>impostors.ts</c> — Godot draws LESS than the browser beyond 120 m); the along/edge/center
/// rows (<c>strokeStations</c>, <c>scatterEdgeInstances</c>, <c>scatterCenterInstance</c> — skipped and
/// counted); the <c>aligned</c> yaw's surface axis (the angle alone is used; position and count are
/// unaffected).
/// </summary>
public partial class ScatterField : Node3D
{
    public const double TuftRadiusM = 0.22, TuftHeightM = 0.8;
    public const double SpreadResampleS = 0.25;
    public const double SwayMaxM = ScatterShaders.SwayMaxM;

    /// <summary>The clearance ledger (<c>propSpread</c>): width per metre of height of each loaded prop URL.
    /// Module-global in the browser, so static here.</summary>
    private static readonly Dictionary<string, double> PropSpread = new();

    private readonly IWorldSource _source;
    private readonly Func<double, double, double> _heightAt;
    private readonly Action<string> _log;
    private TerrainPayload? _payload;
    private List<IReadOnlyList<P2>> _footprints = new();
    private ScatterLodCfg _cfg = ScatterLod.Defaults;

    /// <summary>The detail distances in force (the player's, once the HUD sent them).</summary>
    public ScatterLodCfg Lod => _cfg;
    private List<(int Cx, int Cz)> _cells = new();
    private string _cellSig = "";
    private double _anchorX, _anchorZ;
    private readonly List<AreaScatter> _areas = new();
    private (double X, double Y, double Z)? _lodCam;
    private ScatterViewCone _cone = ScatterLod.ViewCone(0, 1, double.NaN);
    private readonly Dictionary<string, Task<PropMeshData?>> _loads = new();
    private readonly Dictionary<(string Url, double H), (ArrayMesh Mesh, Aabb Bounds, int Tris)> _grounded = new();
    private readonly Dictionary<string, ShaderMaterial> _materials = new();
    private readonly Dictionary<double, ArrayMesh> _cones = new();
    private bool _spreadArmed;
    private int _pending;

    /// <summary>GAME clock of the worldmap (<c>game_time.total_seconds</c>) for reshuffling rows; NaN = none.</summary>
    public double GameSeconds { get; set; } = double.NaN;
    public int Rebuilds { get; private set; }
    /// <summary>Re-samples because the ground changed under the window (<see cref="Redrape"/>), part of <see cref="Rebuilds"/>.</summary>
    public int Redrapes { get; private set; }
    public int SkippedRows { get; private set; }
    public int LoadFailures { get; private set; }
    /// <summary>Loads in flight or a clearance re-sample armed.</summary>
    public bool Busy => _pending > 0 || _spreadArmed;
    public IReadOnlyList<(int Cx, int Cz)> Cells => _cells;

    private sealed class AreaScatter
    {
        public required TerrainAreaInfo Area;
        public required List<P2> Ring;
        public required List<IReadOnlyList<P2>> Occluders;
        public List<Prop> Props = new();
    }

    /// <summary>One <c>ScatterProp</c>: one (row, variant), two buffers, one instance list.</summary>
    public sealed class Prop
    {
        public required int Row;
        public required int VariantPos;
        public required List<ScatterInstance> Points;
        public required MultiMeshInstance3D LowNode;
        public required MultiMesh Low;
        public MultiMeshInstance3D? HighNode;
        public MultiMesh? High;
        public required int BaseCount;
        public required float[] Src;      // 12 floats per instance (Godot's 3×4 row-major buffer layout)
        public required float[] Pos;      // 3 floats per instance (float32 like the browser's Float32Array)
        public required byte[] Tiers;
        public required byte[] Slots;
        public required float[] LowBuf;
        public float[]? HighBuf;
        public required (double X, double Y, double Z) SphereCenter;
        public required double SphereRadius;
        public required Aabb Box;
        public bool Hidden, Disposed;
        public required string LoUrl, HiUrl;
        public required bool HasHigh;
        public required double TargetH, Sway;
        public string WantLow = "", WantHigh = "", ShownLow = "", ShownHigh = "";
        public int LowTris = 10, HighTris;
        public int LowN, HighN;
    }

    public IEnumerable<Prop> Props => _areas.SelectMany(a => a.Props);

    public ScatterField(IWorldSource source, Func<double, double, double> heightAt, Action<string> log)
    {
        Name = "Scatter";
        _source = source;
        _heightAt = heightAt;
        _log = log;
    }

    /// <summary>Take over the terrain and the location footprints, then (re)build every area's scatter.</summary>
    public void SetTerrain(TerrainPayload payload, IEnumerable<P2[]> locationFootprints)
    {
        _payload = payload;
        _footprints = locationFootprints.Cast<IReadOnlyList<P2>>().Concat(payload.PropFootprints()).ToList();
        RebuildAreas();
    }

    /// <summary><c>setHeightAnchor</c>'s scatter half: move the cell window, re-sample if it changed.</summary>
    public void SetAnchor(double x, double z)
    {
        if (!double.IsFinite(x) || !double.IsFinite(z)) return;
        _anchorX = x;
        _anchorZ = z;
        if (MoveWindow(x, z) && _areas.Count > 0) RebuildScatter();
    }

    private bool MoveWindow(double x, double z)
    {
        var cells = ScatterMath.WantedCells(x, z, _cfg.CullM);
        string sig = $"{_cfg.CullM}|{(cells.Count > 0 ? $"{cells[0].Cx},{cells[0].Cz}" : "")}|{cells.Count}";
        if (sig == _cellSig) return false;
        _cellSig = sig;
        _cells = cells;
        return true;
    }

    private void RebuildAreas()
    {
        MoveWindow(_anchorX, _anchorZ);
        ClearAreas();
        if (_payload is null) return;
        var rings = _payload.Areas.Select(a => ScatterMath.AreaRing(a.Polygon)).ToList();
        var grids = new Dictionary<(int, int), OccupancyGrid>();
        SkippedRows = 0;
        for (int i = 0; i < _payload.Areas.Count; i++)
        {
            var ring = rings[i];
            if (ring is null) continue;
            var occluders = rings.Skip(i + 1).Where(r => r is not null).Cast<IReadOnlyList<P2>>().ToList();
            var a = new AreaScatter { Area = _payload.Areas[i], Ring = ring, Occluders = occluders };
            SkippedRows += a.Area.OtherRows;
            a.Props = BuildScatter(a, grids);
            _areas.Add(a);
        }
        Rebuilds++;
        if (SkippedRows > 0) _log($"scatter: {SkippedRows} along/edge/center rows not ported (skipped)");
    }

    /// <summary>
    /// The ground under the window changed (a streamed tile batch, a new relief): every prop samples it again
    /// (<c>rebuildAreas</c> → <c>rebuildScatter</c>, props only).
    /// </summary>
    /// <param name="tiles">The changed tile squares (null = everything); the window is re-sampled only when one of its
    /// cells touches one — a batch at the rim of the 560 m ring leaves the props round the anchor as they are.</param>
    public void Redrape(IReadOnlyCollection<(int Tx, int Tz)>? tiles = null, double tileM = 0)
    {
        if (_areas.Count == 0) return;
        if (tiles is not null && !_cells.Any(c => TileTouchesCell(tiles, tileM, c.Cx, c.Cz, ScatterMath.CellM))) return;
        Redrapes++;
        RebuildScatter();
    }

    /// <summary>Does any tile square touch the cell (closed squares: a shared edge counts — <c>floor</c> puts it in either)?</summary>
    public static bool TileTouchesCell(IReadOnlyCollection<(int Tx, int Tz)> tiles, double tileM, int cx, int cz, double cellM)
    {
        double x0 = cx * cellM, z0 = cz * cellM;
        foreach (var (tx, tz) in tiles)
            if (x0 <= (tx + 1) * tileM && x0 + cellM >= tx * tileM && z0 <= (tz + 1) * tileM && z0 + cellM >= tz * tileM) return true;
        return false;
    }

    /// <summary><c>rebuildScatter</c>: the window moved (or a clearance was measured) — props only.</summary>
    private void RebuildScatter()
    {
        var grids = new Dictionary<(int, int), OccupancyGrid>();
        foreach (var a in _areas)
        {
            DisposeProps(a.Props);
            a.Props = BuildScatter(a, grids);
        }
        Rebuilds++;
    }

    private void ClearAreas()
    {
        foreach (var a in _areas) DisposeProps(a.Props);
        _areas.Clear();
    }

    private void DisposeProps(List<Prop> props)
    {
        foreach (var p in props)
        {
            p.Disposed = true;
            p.LowNode.QueueFree();
            p.HighNode?.QueueFree();
        }
        props.Clear();
    }

    private static (double, double, double, double) RingBounds(IReadOnlyList<P2> ring)
    {
        double minX = double.PositiveInfinity, minZ = double.PositiveInfinity;
        double maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        foreach (var p in ring)
        {
            if (p.X < minX) minX = p.X;
            if (p.X > maxX) maxX = p.X;
            if (p.Z < minZ) minZ = p.Z;
            if (p.Z > maxZ) maxZ = p.Z;
        }
        return (minX, minZ, maxX, maxZ);
    }

    private static double? SpreadOf(IEnumerable<string> urls)
    {
        double? best = null;
        foreach (var u in urls)
            if (u.Length > 0 && PropSpread.TryGetValue(u, out var s) && (best is null || s > best)) best = s;
        return best;
    }

    /// <summary>Sampled instances of one row over the window (for the check): the spread rows only.</summary>
    public static List<ScatterInstance> SampleRow(TerrainAreaInfo area, int index, ScatterEntry entry, IReadOnlyList<P2> ring,
                                                  IReadOnlyList<IReadOnlyList<P2>> occluders,
                                                  IReadOnlyList<IReadOnlyList<P2>> footprints,
                                                  IEnumerable<(int Cx, int Cz)> cells, CellOccupancy occ,
                                                  int variantCount, double clearM, double gameSeconds)
    {
        var pts = new List<ScatterInstance>();
        double? epoch = ScatterMath.ReshuffleEpoch(gameSeconds, entry.ReshuffleMin);
        foreach (var (cx, cz) in cells)
            pts.AddRange(ScatterMath.CellInstances(new ScatterMath.CellOptions
            {
                Ring = ring, Cx = cx, Cz = cz, DensityPer100m2 = entry.DensityPer100m2,
                Seed = ScatterMath.CellSeed(area.Id, index, cx, cz, epoch),
                Footprints = footprints, ClearM = clearM, Occluders = occluders,
                MinSpacingM = entry.MinSpacingM is double s && s > 0 ? s : null,
                VariantCount = variantCount, Variant = entry.Variant,
                YawMode = entry.YawMode, YawDeg = entry.YawDeg,
                AxisAt = null,   // the aligned surface axis (scatterAxis.ts) is not ported: axis 0
                Occupied = occ.GridOf(cx, cz), OccupyR = clearM, OccupyTag = ScatterMath.Seed(area.Id, index),
            }));
        return pts;
    }

    /// <summary>The tier maps a row may draw (<c>readVariantMaps</c>) with their resolved URLs.</summary>
    public static List<(string LoUrl, string HiUrl)> KindsOf(ScatterEntry entry)
    {
        var maps = entry.ModelVariants is { Count: > 0 } mv ? mv : new List<Dictionary<string, string>> { entry.Variants };
        string model = entry.Model ?? "";
        return maps.Select((v, i) =>
        {
            string fallback = i == 0 ? model : "";
            string lo = TerrainPayload.PickVariant(v, "low");
            string hi = TerrainPayload.PickVariant(v, "full");
            return (lo.Length > 0 ? lo : fallback, hi.Length > 0 ? hi : fallback);
        }).ToList();
    }

    private List<Prop> BuildScatter(AreaScatter a, Dictionary<(int, int), OccupancyGrid> grids)
    {
        var outList = new List<Prop>();
        var type = _payload!.TypeOf(a.Area.Kind);
        double sway = type?.SwayM ?? 0;
        var (rMinX, rMinZ, rMaxX, rMaxZ) = RingBounds(a.Ring);
        var cells = _cells.Where(c =>
        {
            double x0 = c.Cx * ScatterMath.CellM, z0 = c.Cz * ScatterMath.CellM;
            return rMaxX >= x0 && rMinX <= x0 + ScatterMath.CellM && rMaxZ >= z0 && rMinZ <= z0 + ScatterMath.CellM;
        }).ToList();
        if (cells.Count == 0) return outList;
        var occ = new CellOccupancy(grids);
        string color = _payload.KindColor(a.Area.Kind);
        for (int index = 0; index < a.Area.Scatter.Count; index++)
        {
            var entry = a.Area.Scatter[index];
            if (entry.Place is "edge" or "center") continue;
            // JS truthiness: an empty model string is the built-in tuft too.
            double h = !string.IsNullOrEmpty(entry.Model) ? ScatterLod.TargetH(entry.PropHeightM) : TuftHeightM;
            var kinds = KindsOf(entry);
            var spread = SpreadOf(kinds.SelectMany(k => new[] { k.HiUrl, k.LoUrl }));
            double clearM = ScatterMath.ClearM(h, spread is double s ? s * h : null);
            var buckets = kinds.Select(_ => new List<ScatterInstance>()).ToList();
            foreach (var p in SampleRow(a.Area, index, entry, a.Ring, a.Occluders, _footprints, cells, occ,
                                        kinds.Count, clearM, GameSeconds))
            {
                int v = p.Variant ?? 0;
                (v >= 0 && v < buckets.Count ? buckets[v] : buckets[0]).Add(p);
            }
            double entrySway = ScatterLod.Sway(sway, entry.SwayFactor);
            double sink = ScatterLod.GroundOffset(entry.GroundOffsetM);
            for (int v = 0; v < kinds.Count; v++)
            {
                if (buckets[v].Count == 0) continue;
                var prop = MakeProp(index, v, buckets[v], h, color, entrySway, sink, kinds[v].LoUrl, kinds[v].HiUrl,
                                    ScatterLod.TargetH(entry.PropHeightM));
                if (_lodCam is { } cam) BinProp(prop, cam);
                else FillAll(prop);
                outList.Add(prop);
            }
        }
        return outList;
    }

    private Prop MakeProp(int row, int variantPos, List<ScatterInstance> points, double h, string color, double sway,
                          double sink, string loUrl, string hiUrl, double targetH)
    {
        int n = points.Count;
        var src = new float[n * 12];
        var pos = new float[n * 3];
        for (int i = 0; i < n; i++)
        {
            var p = points[i];
            double y = _heightAt(p.X, p.Z) + sink;
            float c = (float)Math.Cos(p.Yaw), s = (float)Math.Sin(p.Yaw);
            int o = i * 12;
            src[o] = c; src[o + 1] = 0; src[o + 2] = s; src[o + 3] = (float)p.X;
            src[o + 4] = 0; src[o + 5] = 1; src[o + 6] = 0; src[o + 7] = (float)y;
            src[o + 8] = -s; src[o + 9] = 0; src[o + 10] = c; src[o + 11] = (float)p.Z;
            pos[i * 3] = (float)p.X;
            pos[i * 3 + 1] = (float)y;
            pos[i * 3 + 2] = (float)p.Z;
        }
        var (centre, radius) = InstanceSphere(pos, h + SwayMaxM);
        var box = SphereBox(centre, radius);
        if (!_cones.TryGetValue(h, out var cone)) _cones[h] = cone = PropMesh.Cone(TuftRadiusM, h);
        string tuftKey = $"tuft|{color}|{sway:0.00}|{h}";
        if (!_materials.TryGetValue(tuftKey, out var tuftMat)) _materials[tuftKey] = tuftMat = ScatterShaders.Tuft(color, sway, h);
        var low = NewMultiMesh(cone, n, box);
        var lowNode = new MultiMeshInstance3D
        {
            Name = $"ScatterLow_{row}_{variantPos}",
            Multimesh = low,
            MaterialOverride = tuftMat,
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            Visible = false,
        };
        AddChild(lowNode);
        return new Prop
        {
            Row = row, VariantPos = variantPos, Points = points,
            LowNode = lowNode, Low = low, BaseCount = n, Src = src, Pos = pos,
            Tiers = Enumerable.Repeat((byte)1, n).ToArray(),
            Slots = Enumerable.Repeat((byte)2, n).ToArray(),
            LowBuf = new float[n * 12],
            SphereCenter = centre, SphereRadius = radius, Box = box,
            LoUrl = loUrl, HiUrl = hiUrl, HasHigh = hiUrl.Length > 0 && hiUrl != loUrl,
            TargetH = targetH, Sway = sway,
        };
    }

    private static MultiMesh NewMultiMesh(Mesh mesh, int count, Aabb box, bool colors = false)
    {
        var mm = new MultiMesh
        {
            TransformFormat = MultiMesh.TransformFormatEnum.Transform3D,
            UseColors = colors,
            Mesh = mesh,
        };
        mm.InstanceCount = count;
        mm.VisibleInstanceCount = 0;
        // Like the browser's fixed instance sphere: the AABB is set, never recomputed per upload.
        mm.CustomAabb = box;
        return mm;
    }

    public static Aabb SphereBox((double X, double Y, double Z) c, double r)
        => new(new Vector3((float)(c.X - r), (float)(c.Y - r), (float)(c.Z - r)), Vector3.One * (float)(2 * r));

    public static ((double X, double Y, double Z) Centre, double Radius) InstanceSphere(float[] pos, double pad)
    {
        double minX = double.PositiveInfinity, minY = double.PositiveInfinity, minZ = double.PositiveInfinity;
        double maxX = double.NegativeInfinity, maxY = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        for (int i = 0; i < pos.Length; i += 3)
        {
            if (pos[i] < minX) minX = pos[i];
            if (pos[i] > maxX) maxX = pos[i];
            if (pos[i + 1] < minY) minY = pos[i + 1];
            if (pos[i + 1] > maxY) maxY = pos[i + 1];
            if (pos[i + 2] < minZ) minZ = pos[i + 2];
            if (pos[i + 2] > maxZ) maxZ = pos[i + 2];
        }
        var centre = ((minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2);
        double dx = maxX - minX, dy = maxY - minY, dz = maxZ - minZ;
        return (centre, Math.Sqrt(dx * dx + dy * dy + dz * dz) / 2 + pad);
    }

    private static void Upload(MultiMesh mm, float[] buf) => RenderingServer.MultimeshSetBuffer(mm.GetRid(), buf);

    private void FillAll(Prop p)
    {
        p.Hidden = false;
        Array.Fill(p.Tiers, (byte)1);
        Array.Fill(p.Slots, (byte)1);
        Array.Copy(p.Src, p.LowBuf, p.Src.Length);
        p.LowN = p.BaseCount;
        p.Low.VisibleInstanceCount = p.BaseCount;
        p.LowNode.Visible = p.BaseCount > 0;
        Upload(p.Low, p.LowBuf);
        MountUrl(p, p.LoUrl, false);
    }

    /// <summary>
    /// <c>setScatterLod(cfg)</c> of client3d/src/scene/ground.ts: the player's detail distances. A new cull
    /// distance is a new cell window (re-sampled when it changed); every placed instance is re-binned against the
    /// camera of the last LOD pass at once, not on the next beat.
    /// </summary>
    public void SetLod(ScatterLodCfg cfg)
    {
        _cfg = cfg;
        if (MoveWindow(_anchorX, _anchorZ) && _areas.Count > 0) RebuildScatter();
        if (_lodCam is not { } cam) return;
        foreach (var a in _areas)
            foreach (var p in a.Props) BinProp(p, cam);
    }

    /// <summary>One LOD pass (<c>tickScatterLod</c>): the camera, its forward direction and lens.</summary>
    public void Tick(double camX, double camY, double camZ, double fwdX, double fwdZ, double vFovDeg, double aspect)
    {
        _lodCam = (camX, camY, camZ);
        _cone = ScatterLod.ViewCone(fwdX, fwdZ, ScatterLod.HorizontalFovRad(vFovDeg, aspect));
        foreach (var a in _areas)
            foreach (var p in a.Props) BinProp(p, _lodCam.Value);
    }

    /// <summary><c>binProp</c> without the impostor half.</summary>
    private void BinProp(Prop p, (double X, double Y, double Z) cam)
    {
        var cfg = _cfg;
        double cdx = cam.X - p.SphereCenter.X, cdy = cam.Y - p.SphereCenter.Y, cdz = cam.Z - p.SphereCenter.Z;
        if (Math.Sqrt(cdx * cdx + cdy * cdy + cdz * cdz) - p.SphereRadius > cfg.CullM)
        {
            if (p.Hidden) return;
            p.Hidden = true;
            Array.Fill(p.Tiers, (byte)2);
            Array.Fill(p.Slots, (byte)2);
            p.LowN = 0;
            p.Low.VisibleInstanceCount = 0;
            p.LowNode.Visible = false;
            if (p.High is not null) { p.HighN = 0; p.High.VisibleInstanceCount = 0; p.HighNode!.Visible = false; }
            return;
        }
        p.Hidden = false;
        bool hasFarHalf = p.LoUrl.Length > 0;
        double cull2 = cfg.CullM * cfg.CullM;
        var hiBuf = p.High is not null ? p.HighBuf : null;
        int loN = 0, hiN = 0;
        bool loDirty = false, hiDirty = false;
        double minD = double.PositiveInfinity;
        for (int i = 0; i < p.BaseCount; i++)
        {
            double dx = p.Pos[i * 3] - cam.X, dy = p.Pos[i * 3 + 1] - cam.Y, dz = p.Pos[i * 3 + 2] - cam.Z;
            double d2 = dx * dx + dy * dy + dz * dz;
            byte tier = 2, slot = 2;
            if (d2 <= cull2)
            {
                double d = Math.Sqrt(d2);
                if (d < minD) minD = d;
                byte prev = p.Tiers[i];
                tier = ScatterLod.InstanceTier(d, hasFarHalf && prev == 2 ? (byte)1 : prev, cfg);
                if (tier != 2 && ScatterLod.InstanceVisible(i, d, cfg)
                    && ScatterLod.InViewCone(dx, dz, _cone.FwdX, _cone.FwdZ, _cone.CosHalf))
                    slot = tier == 0 && hiBuf is not null ? (byte)0 : (byte)1;
            }
            p.Tiers[i] = tier;
            byte was = p.Slots[i];
            if (was != slot)
            {
                p.Slots[i] = slot;
                if (slot == 0 || was == 0) hiDirty = true;
                if (slot == 1 || was == 1) loDirty = true;
            }
            if (slot == 0 && hiBuf is not null) { Array.Copy(p.Src, i * 12, hiBuf, hiN * 12, 12); hiN++; }
            else if (slot == 1) { Array.Copy(p.Src, i * 12, p.LowBuf, loN * 12, 12); loN++; }
        }
        p.LowN = loN;
        p.Low.VisibleInstanceCount = loN;
        p.LowNode.Visible = loN > 0;
        if (loDirty) Upload(p.Low, p.LowBuf);
        if (p.High is not null)
        {
            p.HighN = hiN;
            p.High.VisibleInstanceCount = hiN;
            p.HighNode!.Visible = hiN > 0;
            if (hiDirty) Upload(p.High, p.HighBuf!);
        }
        if (minD <= cfg.CullM) MountUrl(p, p.LoUrl, false);
        if (p.HasHigh && minD <= cfg.FarM) MountUrl(p, p.HiUrl, true);
    }

    private void MountUrl(Prop p, string url, bool high)
    {
        if (url.Length == 0) return;
        if ((high ? p.WantHigh : p.WantLow) == url) return;
        if (high) p.WantHigh = url; else p.WantLow = url;
        _ = LoadAndMount(p, url, high);
    }

    private Task<PropMeshData?> LoadData(string url)
    {
        if (_loads.TryGetValue(url, out var t)) return t;
        t = LoadDataInner(url);
        _loads[url] = t;
        return t;
    }

    private async Task<PropMeshData?> LoadDataInner(string url)
    {
        try { return await PropMesh.LoadAsync(_source, url); }
        catch (Exception e)
        {
            LoadFailures++;
            _log($"scatter prop {url} failed: {e.Message}");
            return null;
        }
    }

    private async Task LoadAndMount(Prop p, string url, bool high)
    {
        _pending++;
        try
        {
            var data = await LoadData(url);
            if (data is null)
            {
                // A load that never mounted must not pin the wish (`abandon`).
                if (high ? p.WantHigh == url : p.WantLow == url) { if (high) p.WantHigh = ""; else p.WantLow = ""; }
                return;
            }
            if (p.Disposed || (high ? p.WantHigh : p.WantLow) != url) return;
            if (!_grounded.TryGetValue((url, p.TargetH), out var g))
            {
                var (mesh, bounds) = PropMesh.Grounded(data, p.TargetH);
                _grounded[(url, p.TargetH)] = g = (mesh, bounds, data.Triangles);
            }
            NoteSpread(url, g.Bounds);
            string key = $"{url}|{p.Sway:0.00}|{p.TargetH}";
            if (!_materials.TryGetValue(key, out var mat))
                _materials[key] = mat = ScatterShaders.FromGltf(data.Material, p.Sway, p.TargetH);
            Place(p, url, high, g.Mesh, mat, g.Tris);
        }
        finally { _pending--; }
    }

    private void Place(Prop p, string url, bool high, Mesh mesh, Material mat, int tris)
    {
        if (high)
        {
            if (p.High is null)
            {
                p.High = NewMultiMesh(mesh, p.BaseCount, p.Box);
                p.HighBuf = new float[p.BaseCount * 12];
                p.HighNode = new MultiMeshInstance3D
                {
                    Name = $"ScatterHigh_{p.Row}_{p.VariantPos}",
                    Multimesh = p.High,
                    MaterialOverride = mat,
                    CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                    Visible = false,
                };
                AddChild(p.HighNode);
            }
            else
            {
                p.High.Mesh = mesh;
                p.HighNode!.MaterialOverride = mat;
            }
            p.ShownHigh = url;
            p.HighTris = tris;
        }
        else
        {
            p.Low.Mesh = mesh;
            p.LowNode.MaterialOverride = mat;
            p.ShownLow = url;
            p.LowTris = tris;
        }
        if (_lodCam is { } cam) BinProp(p, cam);
    }

    /// <summary><c>noteSpread</c>: file the measured width/height; a changed value re-samples once, 250 ms later.</summary>
    private void NoteSpread(string url, Aabb b)
    {
        double height = b.Size.Y;
        if (!(height > 1e-6)) return;
        double width = Math.Max(b.Size.X, b.Size.Z);
        if (!double.IsFinite(width) || width <= 0) return;
        double spread = width / height;
        if (PropSpread.TryGetValue(url, out var prev) && Math.Abs(prev - spread) < 1e-6) return;
        PropSpread[url] = spread;
        if (_areas.Count == 0 || _spreadArmed || !IsInsideTree()) return;
        _spreadArmed = true;
        GetTree().CreateTimer(SpreadResampleS).Timeout += () =>
        {
            // The tree's timer outlives this node (back to the title reloads the scene).
            if (!IsInstanceValid(this) || !IsInsideTree()) return;
            _spreadArmed = false;
            if (_areas.Count > 0) RebuildScatter();
        };
    }

    /// <summary>The measured spread of a URL, if any (for the check).</summary>
    public static double? MeasuredSpread(string url) => PropSpread.TryGetValue(url, out var s) ? s : null;

    public LayerCounts Counts()
    {
        int meshes = 0, inst = 0, baseN = 0;
        long tris = 0;
        foreach (var p in Props)
        {
            baseN += p.BaseCount;
            if (p.LowN > 0) { meshes++; inst += p.LowN; tris += (long)p.LowN * p.LowTris; }
            if (p.HighN > 0) { meshes++; inst += p.HighN; tris += (long)p.HighN * p.HighTris; }
        }
        return new LayerCounts(meshes, inst, tris, baseN);
    }
}
