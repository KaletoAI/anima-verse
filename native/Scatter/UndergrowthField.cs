using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Terrain;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Scatter;

/// <summary>One painted shape as the undergrowth reads it (<c>UndergrowthArea</c>).</summary>
public sealed record UndergrowthArea(string Id, string Kind, List<P2> Ring, (double MinX, double MinZ, double MaxX, double MaxZ) Bounds,
                                     double Value, string Color, double SwayM);

/// <summary>
/// The layer nobody authored (§ A9) — port of <c>client3d/src/scene/undergrowth.ts</c>: a window of
/// 64 m cells within <c>UNDERGROWTH_CELL_RADIUS_M</c> of the anchor, each (area, cell) sampled by the shared
/// <c>scatterInstances</c> from its own seed <c>terrain:undergrowth:&lt;area&gt;:&lt;cx&gt;,&lt;cz&gt;</c> at
/// <c>UNDERGROWTH_DENSITY_PER_M2 × meta.undergrowth</c>, one MultiMesh per (cell, area) with per-instance
/// colour, the three-plane star tuft, the procedural blade texture with alpha cut, wind, and the per-instance
/// LOD (cull at 60 m, hash thinning from 30 m).
///
/// One gate differs: the browser keeps a point only where the baked layer MASK (<c>topLayerIndexAt</c>,
/// the <c>/play/terrain-layers</c> tiles) names this area's kind as the top layer. The spike does not load
/// the layer tiles; the occluders already drop every point an area painted later covers, so the kept set is
/// "this area is the topmost painted shape here" — the mask's statement up to its raster at the borders.
///
/// THREADING (Task 26): the cells a moved anchor, a re-drape or new areas ask for are sampled on a worker (one
/// <see cref="Coalescer"/> build at a time, from frozen areas, footprints and a <see cref="WorldHeight.Snapshot"/>);
/// only the MultiMesh nodes are made on the main thread. A cell whose ground or areas changed keeps drawing its old
/// layers until the new ones stand. The boot's first window (<see cref="SetAnchor"/> with <c>inline: true</c>) runs
/// the same <see cref="SampleCells"/> inline.
/// </summary>
public partial class UndergrowthField : Node3D
{
    private readonly WorldHeight _height;
    private readonly Coalescer _build;
    private Task _lastRequest = Task.CompletedTask;
    /// <summary>Counts every new set of areas: a build sampled for an older set is thrown away.</summary>
    private int _areasGen;
    /// <summary>Cells whose layers are outdated (new ground or areas) → the serial of that marking; they draw until rebuilt.</summary>
    private readonly Dictionary<(int, int), int> _staleAt = new();
    private int _serial;
    private List<UndergrowthArea> _areas = new();
    private List<(IReadOnlyList<P2> Fp, (double, double, double, double) Bounds)> _footprints = new();
    private readonly Dictionary<(int, int), List<CellLayer>> _cells = new();
    private bool _hasAnchor;
    private double _anchorX, _anchorZ;
    private (double X, double Y, double Z)? _lodCam;
    private ArrayMesh? _mesh;
    private ImageTexture? _texture;
    private readonly Dictionary<string, ShaderMaterial> _materials = new();

    public sealed class CellLayer
    {
        public required string AreaId;
        public required (int Cx, int Cz) Cell;
        public required List<ScatterInstance> Points;
        public required MultiMeshInstance3D Node;
        public required MultiMesh Mm;
        public required int BaseCount;
        public required float[] Src;   // 16 floats per instance: 12 transform + 4 colour
        public required float[] Pos;
        public required byte[] Slots;
        public required float[] Buf;
        public required (double X, double Y, double Z) SphereCenter;
        public required double SphereRadius;
        public bool Hidden;
        public int N;
    }

    public const int TrisPerTuft = 12;

    /// <summary>Cells built (mounted), worker builds thrown away for newer areas, last / largest worker and mount ms.</summary>
    public int CellsBuilt { get; private set; }
    public int Discarded { get; private set; }
    public double LastBuildMs { get; private set; }
    public double MaxBuildMs { get; private set; }
    public double LastApplyMs { get; private set; }
    public double MaxApplyMs { get; private set; }
    /// <summary>A cell build is on the worker (or waiting for its follow-up).</summary>
    public bool Building => _build.Busy;

    public UndergrowthField(WorldHeight height)
    {
        Name = "Undergrowth";
        _height = height;
        _build = new Coalescer(BuildOnceAsync);
    }

    /// <summary>Completes when every cell build asked for so far has stood (or failed — the failure is logged).</summary>
    public Task WhenBuiltAsync() => _lastRequest;

    public IEnumerable<CellLayer> Layers => _cells.Values.SelectMany(l => l);
    public IReadOnlyCollection<(int, int)> CellKeys => _cells.Keys;

    /// <summary>The painted shapes in LIST order (the stacking order the occluders rely on).</summary>
    public static List<UndergrowthArea> AreasOf(TerrainPayload t)
    {
        var list = new List<UndergrowthArea>();
        foreach (var a in t.Areas)
        {
            var ring = ScatterMath.AreaRing(a.Polygon);
            if (ring is null) continue;
            double minX = double.PositiveInfinity, minZ = double.PositiveInfinity, maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
            foreach (var p in ring) { minX = Math.Min(minX, p.X); maxX = Math.Max(maxX, p.X); minZ = Math.Min(minZ, p.Z); maxZ = Math.Max(maxZ, p.Z); }
            var type = t.TypeOf(a.Kind);
            list.Add(new UndergrowthArea(a.Id, a.Kind, ring, (minX, minZ, maxX, maxZ), type?.Undergrowth ?? 0,
                                         t.KindColor(a.Kind), type?.SwayM ?? 0));
        }
        return list;
    }

    private static (double, double, double, double) FootprintBox(IReadOnlyList<P2> fp)
    {
        var empty = (double.PositiveInfinity, double.PositiveInfinity, double.NegativeInfinity, double.NegativeInfinity);
        if (fp.Count < 3) return empty;
        double minX = double.PositiveInfinity, minZ = double.PositiveInfinity, maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        foreach (var p in fp)
        {
            if (!double.IsFinite(p.X) || !double.IsFinite(p.Z)) return empty;
            if (p.X < minX) minX = p.X;
            if (p.X > maxX) maxX = p.X;
            if (p.Z < minZ) minZ = p.Z;
            if (p.Z > maxZ) maxZ = p.Z;
        }
        return (minX, minZ, maxX, maxZ);
    }

    /// <summary>New painted shapes: every standing cell is outdated (drawn until its new layers stand).</summary>
    public void SetAreas(List<UndergrowthArea> areas, IEnumerable<IReadOnlyList<P2>> footprints)
    {
        _areas = areas;
        _footprints = footprints.Select(f => (f, FootprintBox(f))).ToList();
        _areasGen++;
        foreach (var key in _cells.Keys) _staleAt[key] = ++_serial;
        _materials.Clear();
        if (_hasAnchor) RefreshCells(false);
    }

    /// <summary>
    /// The ground changed under the cells (<c>rebuildAreas</c> → <c>undergrowth.setAreas</c>): every cell is grown again
    /// on the ground that stands now.
    /// </summary>
    /// <param name="tiles">The changed tile squares (null = every cell); only the cells touching one are grown again.</param>
    public void Redrape(IReadOnlyCollection<(int Tx, int Tz)>? tiles = null, double tileM = 0)
    {
        foreach (var key in _cells.Keys)
            if (tiles is null || ScatterField.TileTouchesCell(tiles, tileM, key.Item1, key.Item2, ScatterLod.UgCellM))
                _staleAt[key] = ++_serial;
        if (_hasAnchor) RefreshCells(false);
    }

    /// <summary>
    /// The window follows the anchor: cells that left it go at once, the new ones are sampled on the worker
    /// (<paramref name="inline"/> = right here, the boot's first window).
    /// </summary>
    public void SetAnchor(double x, double z, bool inline = false)
    {
        if (!double.IsFinite(x) || !double.IsFinite(z)) return;
        _anchorX = x;
        _anchorZ = z;
        _hasAnchor = true;
        RefreshCells(inline);
    }

    /// <summary>Drops the cells outside the window; returns the wanted cells that are missing or outdated, in window order.</summary>
    private List<(int Cx, int Cz)> Needed()
    {
        var want = UndergrowthMath.WantedCells(_anchorX, _anchorZ);
        var keep = want.ToHashSet();
        foreach (var key in _cells.Keys.ToList())
            if (!keep.Contains(key)) DropCell(key);
        return want.Where(k => !_cells.ContainsKey(k) || _staleAt.ContainsKey(k)).ToList();
    }

    private void RefreshCells(bool inline)
    {
        var need = Needed();
        if (need.Count == 0) return;
        if (inline)
        {
            var inputs = Inputs(need);
            Apply(inputs, SampleCells(inputs), null);
            return;
        }
        _lastRequest = Logged(_build.RequestAsync());
    }

    private static async Task Logged(Task build)
    {
        try { await build; }
        catch (Exception e) { GD.PushWarning($"[native] undergrowth: cell build failed, the cells standing stay: {e.Message}"); }
    }

    /// <summary>What one cell build reads, frozen on the main thread.</summary>
    public sealed record CellInputs(int AreasGen, int Serial, IReadOnlyList<(int Cx, int Cz)> Keys, IReadOnlyList<UndergrowthArea> Areas,
                                    IReadOnlyList<(IReadOnlyList<P2> Fp, (double, double, double, double) Bounds)> Footprints,
                                    WorldHeight Ground);

    /// <summary>One (area, cell) layer, sampled and draped, ready to be mounted.</summary>
    public sealed record LayerSpec(int AreaIndex, List<ScatterInstance> Points, float[] Src, float[] Pos,
                                   (double X, double Y, double Z) Centre, double Radius);

    private CellInputs Inputs(List<(int Cx, int Cz)> keys)
        => new(_areasGen, _serial, keys, _areas, _footprints, _height.Snapshot());

    /// <summary>One build: the cells needed NOW, sampled on a worker, mounted here unless newer areas came.</summary>
    private async Task BuildOnceAsync()
    {
        var need = Needed();
        if (need.Count == 0) return;
        var inputs = Inputs(need);
        var clock = Stopwatch.StartNew();
        var specs = await Task.Run(() => SampleCells(inputs));
        double workerMs = clock.Elapsed.TotalMilliseconds;
        if (!IsInstanceValid(this) || inputs.AreasGen != _areasGen)
        {
            Discarded++;
            return;   // newer areas are here; their own request is queued behind this one
        }
        Apply(inputs, specs, workerMs);
    }

    /// <summary>
    /// The main-thread half: a built cell replaces what stands there — unless it left the window meanwhile, or it was
    /// marked outdated AFTER the inputs were frozen (that marking queued its own build).
    /// </summary>
    /// <param name="workerMs">The worker's time; null = the inline boot build (not counted into the runtime figures).</param>
    private void Apply(CellInputs inputs, List<List<LayerSpec>> specs, double? workerMs)
    {
        var clock = Stopwatch.StartNew();
        var want = UndergrowthMath.WantedCells(_anchorX, _anchorZ).ToHashSet();
        for (int i = 0; i < inputs.Keys.Count; i++)
        {
            var key = inputs.Keys[i];
            if (!want.Contains(key)) continue;
            bool stale = _staleAt.TryGetValue(key, out int at);
            if (_cells.ContainsKey(key) && !stale) continue;
            if (stale && at > inputs.Serial) continue;
            DropCell(key);
            _cells[key] = specs[i].Select(spec => MakeLayer(_areas[spec.AreaIndex], key, spec)).ToList();
            CellsBuilt++;
        }
        if (workerMs is not double ms) return;
        LastBuildMs = ms;
        MaxBuildMs = Math.Max(MaxBuildMs, ms);
        LastApplyMs = clock.Elapsed.TotalMilliseconds;
        MaxApplyMs = Math.Max(MaxApplyMs, LastApplyMs);
    }

    private void DropCell((int, int) key)
    {
        _staleAt.Remove(key);
        if (!_cells.TryGetValue(key, out var layers)) return;
        foreach (var l in layers) l.Node.QueueFree();
        _cells.Remove(key);
    }

    /// <summary>The instances one (area, cell) grows — sampler + ring filter, no Godot objects.</summary>
    public static List<ScatterInstance> SampleCell(IReadOnlyList<UndergrowthArea> areas, int index, int cx, int cz,
                                                   IReadOnlyList<IReadOnlyList<P2>> nearFootprints)
    {
        var area = areas[index];
        double cell = ScatterLod.UgCellM;
        double x0 = cx * cell, z0 = cz * cell, x1 = x0 + cell, z1 = z0 + cell;
        bool Meets((double MinX, double MinZ, double MaxX, double MaxZ) b) => b.MaxX >= x0 && b.MinX <= x1 && b.MaxZ >= z0 && b.MinZ <= z1;
        var occluders = new List<IReadOnlyList<P2>>();
        for (int j = index + 1; j < areas.Count; j++)
            if (Meets(areas[j].Bounds)) occluders.Add(areas[j].Ring);
        var points = ScatterMath.Instances(new ScatterMath.SampleOptions
        {
            Ring = new[] { new P2(x0, z0), new P2(x1, z0), new P2(x1, z1), new P2(x0, z1) },
            AreaM2 = cell * cell,
            DensityPer100m2 = ScatterLod.UgDensityPer100m2(area.Value),
            Seed = UndergrowthMath.CellSeed(area.Id, cx, cz),
            Footprints = nearFootprints,
            Occluders = occluders,
            MaxPoints = ScatterLod.UgMaxPerCell,
            TriesPerPoint = 1,
        });
        return points.FindAll(p => ScatterMath.PointInRing(p.X, p.Z, area.Ring));
    }

    /// <summary>Every (area, cell) layer of the cells in <paramref name="inputs"/> — pure (a worker runs it).</summary>
    public static List<List<LayerSpec>> SampleCells(CellInputs inputs)
    {
        var outList = new List<List<LayerSpec>>(inputs.Keys.Count);
        foreach (var key in inputs.Keys) outList.Add(SampleCellLayers(inputs, key));
        return outList;
    }

    private static List<LayerSpec> SampleCellLayers(CellInputs inputs, (int Cx, int Cz) key)
    {
        var (cx, cz) = key;
        double cell = ScatterLod.UgCellM;
        double x0 = cx * cell, z0 = cz * cell, x1 = x0 + cell, z1 = z0 + cell;
        bool Meets((double MinX, double MinZ, double MaxX, double MaxZ) b) => b.MaxX >= x0 && b.MinX <= x1 && b.MaxZ >= z0 && b.MinZ <= z1;
        var near = inputs.Footprints.Where(f => Meets(f.Bounds)).Select(f => f.Fp).ToList();
        var areas = inputs.Areas;
        var outList = new List<LayerSpec>();
        for (int index = 0; index < areas.Count; index++)
        {
            var area = areas[index];
            if (ScatterLod.UgCellCount(area.Value) < 1) continue;
            if (!Meets(area.Bounds)) continue;
            var kept = SampleCell(areas, index, cx, cz, near);
            if (kept.Count == 0) continue;
            outList.Add(Drape(inputs.Ground, index, kept));
        }
        return outList;
    }

    /// <summary>One layer's buffers: Godot's 3×4 rows scaled by the tuft height on the ground, the tint, the sphere.</summary>
    private static LayerSpec Drape(WorldHeight ground, int areaIndex, List<ScatterInstance> kept)
    {
        int n = kept.Count;
        var src = new float[n * 16];
        var pos = new float[n * 3];
        for (int i = 0; i < n; i++)
        {
            var p = kept[i];
            double scale = ScatterLod.UgHeight(p.Yaw) / UndergrowthMath.HRefM;
            double y = ground.GroundAt(p.X, p.Z);
            float c = (float)(Math.Cos(p.Yaw) * scale), s = (float)(Math.Sin(p.Yaw) * scale), k = (float)scale;
            int o = i * 16;
            src[o] = c; src[o + 1] = 0; src[o + 2] = s; src[o + 3] = (float)p.X;
            src[o + 4] = 0; src[o + 5] = k; src[o + 6] = 0; src[o + 7] = (float)y;
            src[o + 8] = -s; src[o + 9] = 0; src[o + 10] = c; src[o + 11] = (float)p.Z;
            var (tr, tg, tb) = UndergrowthMath.Tint(UndergrowthMath.Shade(p.X, p.Z));
            src[o + 12] = (float)tr; src[o + 13] = (float)tg; src[o + 14] = (float)tb; src[o + 15] = 1f;
            pos[i * 3] = (float)p.X;
            pos[i * 3 + 1] = (float)y;
            pos[i * 3 + 2] = (float)p.Z;
        }
        var (centre, radius) = ScatterField.InstanceSphere(pos, UndergrowthMath.ReachM);
        return new LayerSpec(areaIndex, kept, src, pos, centre, radius);
    }

    /// <summary>Main thread: the MultiMesh and node of one sampled layer.</summary>
    private CellLayer MakeLayer(UndergrowthArea area, (int, int) key, LayerSpec spec)
    {
        _mesh ??= TuftMesh();
        var (kept, src, pos, centre, radius) = (spec.Points, spec.Src, spec.Pos, spec.Centre, spec.Radius);
        int n = kept.Count;
        var mm = new MultiMesh
        {
            TransformFormat = MultiMesh.TransformFormatEnum.Transform3D,
            UseColors = true,
            Mesh = _mesh,
        };
        mm.InstanceCount = n;
        mm.VisibleInstanceCount = 0;
        mm.CustomAabb = ScatterField.SphereBox(centre, radius);
        var node = new MultiMeshInstance3D
        {
            Name = $"Ug_{key.Item1}_{key.Item2}_{area.Id}",
            Multimesh = mm,
            MaterialOverride = MaterialFor(area),
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            Visible = false,
        };
        AddChild(node);
        var layer = new CellLayer
        {
            AreaId = area.Id, Cell = key, Points = kept, Node = node, Mm = mm, BaseCount = n, Src = src, Pos = pos,
            Slots = Enumerable.Repeat((byte)1, n).ToArray(), Buf = new float[n * 16],
            SphereCenter = centre, SphereRadius = radius,
        };
        if (_lodCam is { } cam) BinLayer(layer, cam);
        return layer;
    }

    private ShaderMaterial MaterialFor(UndergrowthArea area)
    {
        string key = $"{area.Kind}|{area.Color}|{area.SwayM}";
        if (_materials.TryGetValue(key, out var m)) return m;
        if (_texture is null)
        {
            var img = Image.CreateFromData(UndergrowthMath.TexSize, UndergrowthMath.TexSize, false, Image.Format.Rgba8,
                                           UndergrowthMath.TexturePixels());
            img.GenerateMipmaps();
            _texture = ImageTexture.CreateFromImage(img);
        }
        m = ScatterShaders.Undergrowth(_texture, area.Color, area.SwayM);
        _materials[key] = m;
        return m;
    }

    private static ArrayMesh TuftMesh()
    {
        var (pos, uv, index) = UndergrowthMath.Geometry(UndergrowthMath.HRefM);
        int nv = pos.Length / 3;
        var verts = new Vector3[nv];
        var uvs = new Vector2[nv];
        var normals = new Vector3[nv];
        for (int i = 0; i < nv; i++)
        {
            verts[i] = new Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
            // three's v runs up the quad with row 0 of the (unflipped) DataTexture at v = 0; Godot's
            // v = 0 is row 0 of the Image as well, so the uv goes over unchanged.
            uvs[i] = new Vector2(uv[i * 2], uv[i * 2 + 1]);
            normals[i] = Vector3.Up;
        }
        // three winds front faces counter-clockwise, Godot clockwise: reverse each triangle. Both windings
        // are in the list anyway (the tuft is double-sided by construction), so this only keeps the order.
        var idx = new int[index.Length];
        for (int t = 0; t < index.Length; t += 3) { idx[t] = index[t]; idx[t + 1] = index[t + 2]; idx[t + 2] = index[t + 1]; }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = verts;
        arrays[(int)Mesh.ArrayType.Normal] = normals;
        arrays[(int)Mesh.ArrayType.TexUV] = uvs;
        arrays[(int)Mesh.ArrayType.Index] = idx;
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        return mesh;
    }

    public void Tick(double camX, double camY, double camZ)
    {
        _lodCam = (camX, camY, camZ);
        foreach (var layers in _cells.Values)
            foreach (var l in layers) BinLayer(l, _lodCam.Value);
    }

    /// <summary><c>binLayer</c>: sphere test, then per instance cull + thinning; upload only on change.</summary>
    private static void BinLayer(CellLayer l, (double X, double Y, double Z) cam)
    {
        double cdx = cam.X - l.SphereCenter.X, cdy = cam.Y - l.SphereCenter.Y, cdz = cam.Z - l.SphereCenter.Z;
        if (Math.Sqrt(cdx * cdx + cdy * cdy + cdz * cdz) - l.SphereRadius > ScatterLod.UgCullM)
        {
            if (l.Hidden) return;
            l.Hidden = true;
            Array.Fill(l.Slots, (byte)1);
            l.N = 0;
            l.Mm.VisibleInstanceCount = 0;
            l.Node.Visible = false;
            return;
        }
        l.Hidden = false;
        double cull2 = ScatterLod.UgCullM * ScatterLod.UgCullM;
        int n = 0;
        bool dirty = false;
        for (int i = 0; i < l.BaseCount; i++)
        {
            double dx = l.Pos[i * 3] - cam.X, dy = l.Pos[i * 3 + 1] - cam.Y, dz = l.Pos[i * 3 + 2] - cam.Z;
            double d2 = dx * dx + dy * dy + dz * dz;
            byte slot = d2 <= cull2 && ScatterLod.UgVisible(i, Math.Sqrt(d2)) ? (byte)0 : (byte)1;
            if (l.Slots[i] != slot) { l.Slots[i] = slot; dirty = true; }
            if (slot == 0) { Array.Copy(l.Src, i * 16, l.Buf, n * 16, 16); n++; }
        }
        l.N = n;
        l.Mm.VisibleInstanceCount = n;
        l.Node.Visible = n > 0;
        if (dirty) RenderingServer.MultimeshSetBuffer(l.Mm.GetRid(), l.Buf);
    }

    public LayerCounts Counts()
    {
        int meshes = 0, inst = 0, baseN = 0;
        foreach (var l in Layers)
        {
            baseN += l.BaseCount;
            if (l.N > 0) { meshes++; inst += l.N; }
        }
        return new LayerCounts(meshes, inst, (long)inst * TrisPerTuft, baseN);
    }
}
