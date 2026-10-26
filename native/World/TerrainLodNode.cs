using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using AnimaNative.Ground;
using AnimaNative.Terrain;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The browser's CDLOD terrain in Godot (<c>client3d/src/scene/terrainLod.ts</c> <c>createTerrainLod</c>): ONE patch
/// mesh of 33 × 33 vertices drawn as two <see cref="MultiMesh"/>es — the dry program and the wet one (the water lift)
/// — whose instances carry <c>INSTANCE_CUSTOM</c> = (x, z, size, level), the browser's <c>iNode</c>. The CPU work is
/// <see cref="TerrainField"/> (selection, rings, partition, pyramids — vector-checked in the core); this node only
/// uploads the pyramids as R32F textures, binds the uniforms of <see cref="TerrainLodGlsl"/> on the materials and
/// writes each frame's pieces into the instance buffers.
///
/// Frame order (the browser selects in the first frame hook, never in <c>onBeforeRender</c>): <see cref="_Process"/>
/// runs at priority 2000 — after the overview camera and the bench driver (1000) have moved the camera — so the
/// pieces drawn are the pieces selected for that very camera. The rings follow the real viewport height
/// (<see cref="TerrainField.PixelScale"/>); a change is logged. No frustum culling (the browser's decision of
/// 2026-08-22): both instances carry a world-sized AABB. The terrain casts no shadow and receives them.
/// </summary>
public partial class TerrainLodNode : Node3D
{
    /// <summary>Floats per instance in the MultiMesh buffer: a 3 × 4 transform (identity) + the four custom floats.</summary>
    public const int Stride = 16;
    private const int MinCapacity = 256;

    private static readonly Aabb WorldBox = new(new Vector3(-1e6f, -1e5f, -1e6f), new Vector3(2e6f, 2e5f, 2e6f));
    private static ArrayMesh? _patch;

    private readonly Action<string> _log;
    private readonly MultiMeshInstance3D _dry, _wet;
    private readonly ShaderMaterial _plain;
    private ShaderMaterial _dryMat, _wetMat;
    private ShaderMaterial? _pendingWet;
    private bool _wetProgram;
    private float[] _dryBuf = Array.Empty<float>(), _wetBuf = Array.Empty<float>();
    private List<LodNode> _lastDry = new(), _lastWet = new();
    private double[] _lastRange = Array.Empty<double>();
    private int _lastRelax = -1;
    private (double X, double Y, double Z, double Ps)? _lastEye;
    private int _loggedPx = -1;

    public TerrainField Field { get; private set; }
    public TerrainUniforms Uniforms { get; private set; }
    /// <summary>The textures as uploaded (null = none), and the images they were made of (the check reads them back).</summary>
    public ImageTexture? NearTex { get; private set; }
    public ImageTexture? FarTex { get; private set; }
    public ImageTexture? CapTex { get; private set; }
    public ImageTexture? WaterTex { get; private set; }
    public ImageTexture? SdTex { get; private set; }
    /// <summary>The fragment's look rows and flow on the water base lattice (<c>uTlodWaterKind</c>, <c>uTlodFlow</c>).</summary>
    public ImageTexture? KindTex { get; private set; }
    public ImageTexture? FlowTex { get; private set; }
    /// <summary>How often a streamed field replaced the one standing (<see cref="ApplyField"/>), and how many textures were
    /// updated in place vs created anew.</summary>
    public int FieldSwaps { get; private set; }
    public int TexturesUpdated { get; private set; }
    public int TexturesCreated { get; private set; }
    /// <summary>The frame drawn now (null before the first update).</summary>
    public TerrainFrame? Frame { get; private set; }
    /// <summary>The pixel scale and viewport height of the last automatic update (0 before one).</summary>
    public double PixelScale { get; private set; }
    public int ViewportPx { get; private set; }
    /// <summary>How often the instance buffers were rewritten (the selection changed).</summary>
    public int Uploads { get; private set; }
    /// <summary>CPU cost of the selection + buffer writes: how many frames selected, their total and largest time (ms).</summary>
    public int Selections { get; private set; }
    public double SelectMsTotal { get; private set; }
    public double SelectMsMax { get; private set; }
    /// <summary>The largest frame since <see cref="ResetPeak"/> (the bench reports it beside the last one).</summary>
    public (int Pieces, int Triangles, int Draws) Peak { get; private set; }

    /// <summary>Starts a new peak window (the bench drive).</summary>
    public void ResetPeak()
    {
        Peak = default;
        Selections = 0;
        SelectMsTotal = SelectMsMax = 0;
    }
    /// <summary>false = only explicit <see cref="UpdateFor"/> calls select (the check drives the camera itself).</summary>
    public bool AutoUpdate { get; set; } = true;

    /// <summary>
    /// The bench switch <c>terrain-lod-coarse</c> (Task 26b): the pixel scale the selection runs with is multiplied by this
    /// (1 = the browser's; 0.5 = the allowed screen error doubled, 2 → 4 px). A change re-selects on the next frame.
    /// </summary>
    public double PixelScaleFactor
    {
        get => _pixelScaleFactor;
        set
        {
            if (_pixelScaleFactor == value) return;
            _pixelScaleFactor = value;
            _lastEye = null;
        }
    }
    private double _pixelScaleFactor = 1;

    public MultiMeshInstance3D DryInstance => _dry;
    public MultiMeshInstance3D WetInstance => _wet;
    public ShaderMaterial PlainMaterial => _plain;

    public TerrainLodNode(TerrainField field, Action<string> log)
    {
        Name = "Terrain";
        ProcessPriority = 2000;
        Field = field;
        _log = log;
        Uniforms = field.Uniforms();
        var images = PrepareImages(field);
        NearTex = Create(images.Near);
        FarTex = Create(images.Far);
        WaterTex = Create(images.Water);
        CapTex = Create(images.Cap);
        SdTex = Create(images.Sd);
        KindTex = Create(images.Kind);
        FlowTex = Create(images.Flow);
        _dry = Instance("TerrainDry");
        _wet = Instance("TerrainWet");
        _wet.SetMeta("wet", true);
        AddChild(_dry);
        AddChild(_wet);
        _plain = new ShaderMaterial { Shader = GroundShader.Plain() };
        ShaderSafety.Ok(_plain.Shader, "terrain-plain");
        VeilUniforms.Bind(_plain);
        HemiUniforms.Bind(_plain);
        _dryMat = _wetMat = _plain;
        SetMaterials(null, null);
    }

    /// <summary>The R32F images of a field's pyramids, cap grid, sd and kind-row fields and the RG32F flow (null = none) —
    /// made off the main thread.</summary>
    public sealed record TerrainImages(Image? Near, Image? Far, Image? Water, Image? Cap, Image? Sd, Image? Kind = null,
                                       Image? Flow = null);

    /// <summary>
    /// The images of <paramref name="f"/>'s textures. Pure CPU work on <see cref="Image"/>s (no server resource), so a
    /// streamed field makes them on a worker thread; only <see cref="ApplyField"/> touches the GPU, on the main thread.
    /// <paramref name="skipFar"/>: the far pyramid is the one already uploaded (no image).
    /// </summary>
    public static TerrainImages PrepareImages(TerrainField f, bool skipFar = false)
    {
        var u = f.Uniforms();
        static Image? Pyr(HeightPyramid? p) => p is null ? null : FloatImage(p.Data, p.TexW, p.TexH);
        return new TerrainImages(Pyr(u.Near), skipFar ? null : Pyr(u.Far), Pyr(u.Water),
                                 u.Cap is { } c ? FloatImage(c.Caps, c.Cols, c.Rows) : null,
                                 u.WaterSd is { } sd ? FloatImage(sd.Data, sd.Cols, sd.Rows) : null,
                                 u.WaterKind is { } k ? FloatImage(k.Data, k.Cols, k.Rows) : null,
                                 u.WaterFlow is { } fl
                                     ? Image.CreateFromData(fl.Cols, fl.Rows, false, Image.Format.Rgf,
                                                            MemoryMarshal.AsBytes(fl.Data.AsSpan(0, fl.Cols * fl.Rows * 2)))
                                     : null);
    }

    /// <summary>An R32F image of <paramref name="data"/> (row-major), straight from the float span (no byte copy).</summary>
    public static Image FloatImage(float[] data, int w, int h)
        => Image.CreateFromData(w, h, false, Image.Format.Rf, MemoryMarshal.AsBytes(data.AsSpan(0, w * h)));

    /// <summary>An R32F texture of <paramref name="data"/> (row-major), read by <c>texelFetch</c> only (no filtering, no mips).</summary>
    public static ImageTexture FloatTexture(float[] data, int w, int h) => ImageTexture.CreateFromImage(FloatImage(data, w, h));

    private ImageTexture? Create(Image? img)
    {
        if (img is null) return null;
        TexturesCreated++;
        return ImageTexture.CreateFromImage(img);
    }

    /// <summary>
    /// The image into the texture standing in its place: <see cref="ImageTexture.Update"/> when size and format match
    /// (no new GPU allocation — the docs' advice for frequently changed textures), else a new texture. Null = none.
    /// </summary>
    private ImageTexture? Swap(ImageTexture? old, Image? img)
    {
        if (img is null) return null;
        if (old is not null && old.GetWidth() == img.GetWidth() && old.GetHeight() == img.GetHeight() && old.GetFormat() == img.GetFormat())
        {
            old.Update(img);
            TexturesUpdated++;
            return old;
        }
        return Create(img);
    }

    /// <summary>
    /// <c>setField</c> on the drawn terrain, the main-thread half of a streamed rebuild: the field and its prepared images
    /// replace the standing ones (in-place texture updates where the size held), both materials are bound again, and the
    /// next frame selects on the new field. <paramref name="images"/>.Far null with the same far pyramid = keep the
    /// uploaded far texture. <paramref name="dry"/> / <paramref name="wet"/>: the ground material and its water variant
    /// now (null = the plain terrain / no water variant), as <see cref="SetMaterials"/> takes them.
    /// </summary>
    public void ApplyField(TerrainField field, TerrainImages images, ShaderMaterial? dry, ShaderMaterial? wet)
    {
        bool sameFar = ReferenceEquals(field.Far, Field.Far);
        Field = field;
        Uniforms = field.Uniforms();
        NearTex = Swap(NearTex, images.Near);
        if (!sameFar || images.Far is not null) FarTex = Swap(FarTex, images.Far);
        WaterTex = Swap(WaterTex, images.Water);
        CapTex = Swap(CapTex, images.Cap);
        SdTex = Swap(SdTex, images.Sd);
        KindTex = Swap(KindTex, images.Kind);
        FlowTex = Swap(FlowTex, images.Flow);
        FieldSwaps++;
        // Re-bind both programs (the wet one may come or go with the water) and force the next selection.
        SetMaterials(dry, wet);
        Frame = null;
    }

    /// <summary>The next frame selects again even when the eye has not moved (the level errors changed).</summary>
    public void Invalidate() => _lastEye = null;

    /// <summary>
    /// <c>setExtent</c> on every sync (<c>rebuildBase(bounds)</c>): a moved world frame is written to both programs and
    /// selected for at the next frame.
    /// </summary>
    public void SetExtent(double[] extent)
    {
        if (!Field.SetExtent(extent)) return;
        Uniforms = Field.Uniforms();
        var e = new Vector4((float)extent[0], (float)extent[1], (float)extent[2], (float)extent[3]);
        _dryMat.SetShaderParameter("tl_extent", e);
        if (_wetMat != _dryMat) _wetMat.SetShaderParameter("tl_extent", e);
        _lastEye = null;
    }

    /// <summary>
    /// <c>patchGeometry</c>: (PATCH_N + 1)² points in [0, 1]² on y = 0, every cell split from its minimum corner to its
    /// maximum one like the browser's — wound CLOCKWISE seen from above, Godot's front face (three's is CCW).
    /// </summary>
    public static ArrayMesh PatchMesh()
    {
        if (_patch is not null) return _patch;
        int n = TerrainLod.PatchN, side = n + 1;
        var pos = new Vector3[side * side];
        for (int j = 0; j < side; j++)
        for (int i = 0; i < side; i++)
            pos[j * side + i] = new Vector3((float)i / n, 0, (float)j / n);
        var index = new int[n * n * 6];
        int k = 0;
        for (int j = 0; j < n; j++)
        for (int i = 0; i < n; i++)
        {
            int a = j * side + i;
            index[k++] = a; index[k++] = a + side + 1; index[k++] = a + side;
            index[k++] = a; index[k++] = a + 1; index[k++] = a + side + 1;
        }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = pos;
        arrays[(int)Mesh.ArrayType.Index] = index;
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        mesh.CustomAabb = WorldBox;
        return _patch = mesh;
    }

    private static MultiMeshInstance3D Instance(string name)
    {
        var mm = new MultiMesh
        {
            TransformFormat = MultiMesh.TransformFormatEnum.Transform3D,
            UseCustomData = true,
            Mesh = PatchMesh(),
            CustomAabb = WorldBox,
            VisibleInstanceCount = 0,
        };
        return new MultiMeshInstance3D
        {
            Name = name,
            Multimesh = mm,
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            GIMode = GeometryInstance3D.GIModeEnum.Disabled,
            CustomAabb = WorldBox,
            // The hemisphere pair is a shader term on every ground material (HemiUniforms): its two lights skip this layer.
            Layers = HemiUniforms.Layer,
        };
    }

    /// <summary>
    /// <c>setMaterial(dry, wet)</c>: the ground material and its water variant (null = the plain terrain; a null wet
    /// material draws every piece with the dry program — no lift, the bed). Each gets the field's uniforms.
    /// </summary>
    public void SetMaterials(ShaderMaterial? dry, ShaderMaterial? wet)
    {
        _dryMat = dry ?? _plain;
        // A water variant given while the field has no wet tile is kept for the field that brings one (streaming).
        _pendingWet = wet;
        _wetProgram = wet is not null && Field.WaterTileKeys is not null;
        _wetMat = _wetProgram ? wet! : _dryMat;
        Bind(_dryMat, water: false);
        if (_wetProgram) Bind(_wetMat, water: true);
        _dry.MaterialOverride = _dryMat;
        _wet.MaterialOverride = _wetMat;
        // Re-write the per-frame values into the new materials (and the pieces, if the partition moved).
        _lastRange = Array.Empty<double>();
        _lastRelax = -1;
        _lastEye = null;
        if (Frame is { } f) Apply(f, force: true);
    }

    /// <summary>The materials the instances wear now (dry, wet).</summary>
    public (ShaderMaterial Dry, ShaderMaterial Wet) Materials => (_dryMat, _wetMat);

    private static Vector4 V4(double[] v) => new((float)v[0], (float)v[1], (float)v[2], (float)v[3]);
    private static Vector4[] Rows(double[][] rows) => Array.ConvertAll(rows, V4);

    /// <summary><c>uploadPyramids</c> + <c>setExtent</c> + <c>setField</c>'s step and span, on one material.</summary>
    private void Bind(ShaderMaterial m, bool water)
    {
        var u = Uniforms;
        if (NearTex is not null) m.SetShaderParameter("tl_near", NearTex);
        if (FarTex is not null) m.SetShaderParameter("tl_far", FarTex);
        m.SetShaderParameter("tl_near_geom", V4(u.NearGeom));
        m.SetShaderParameter("tl_far_geom", V4(u.FarGeom));
        m.SetShaderParameter("tl_near_levels", Rows(u.NearLevels));
        m.SetShaderParameter("tl_far_levels", Rows(u.FarLevels));
        m.SetShaderParameter("tl_near_rect", V4(u.NearRect));
        m.SetShaderParameter("tl_extent", V4(u.Extent));
        m.SetShaderParameter("tl_base_step", (float)u.BaseStep);
        m.SetShaderParameter("tl_normal_span", (float)u.NormalSpan);
        if (CapTex is not null) m.SetShaderParameter("tl_cap", CapTex);
        m.SetShaderParameter("tl_cap_geom", V4(u.CapGeom));
        if (!water) return;
        if (WaterTex is not null) m.SetShaderParameter("tl_water", WaterTex);
        if (SdTex is not null) m.SetShaderParameter("tl_water_sd", SdTex);
        // The fragment's look rows and flow — the ground's water variant only (the plain program has no water).
        if (KindTex is not null) m.SetShaderParameter("tw_kind", KindTex);
        if (FlowTex is not null) m.SetShaderParameter("tw_flow", FlowTex);
        m.SetShaderParameter("tl_water_geom", V4(u.WaterGeom));
        m.SetShaderParameter("tl_water_levels", Rows(u.WaterLevels));
    }

    public override void _Process(double delta)
    {
        if (!AutoUpdate) return;
        var vp = GetViewport();
        var cam = vp?.GetCamera3D();
        if (vp is null || cam is null) return;
        int px = (int)vp.GetVisibleRect().Size.Y;
        double ps = TerrainField.PixelScale(px, cam.Fov) * _pixelScaleFactor;
        var p = cam.GlobalPosition;
        var frame = UpdateFor(p.X, p.Y, p.Z, ps);
        PixelScale = ps;
        ViewportPx = px;
        if (px != _loggedPx)
        {
            _loggedPx = px;
            _log($"terrain: viewport {px} px, fov {cam.Fov:0.#}° → pixel scale {ps:0.#}; rings [{string.Join(", ", frame.Ranges.ConvertAll(r => r.ToString("0.#")))}] m; "
                 + $"{frame.Nodes} pieces ({frame.Dry.Count} dry, {frame.Wet.Count} wet), {frame.Triangles} triangles, {frame.Draws} draws");
        }
    }

    /// <summary>
    /// <c>update(camera, viewportPx)</c>: select the frame's pieces for an eye at (x, y, z) and the pixel scale, and
    /// write them (only when the list changed) plus the rings and the cap relaxation (only when they changed).
    /// </summary>
    public TerrainFrame UpdateFor(double x, double y, double z, double pixelScale)
    {
        if (Frame is { } same && _lastEye is { } e && e.X == x && e.Y == y && e.Z == z && e.Ps == pixelScale) return same;
        _lastEye = (x, y, z, pixelScale);
        long t0 = System.Diagnostics.Stopwatch.GetTimestamp();
        var frame = Field.Select(x, y, z, pixelScale);
        Apply(frame, force: false);
        double ms = System.Diagnostics.Stopwatch.GetElapsedTime(t0).TotalMilliseconds;
        Selections++;
        SelectMsTotal += ms;
        if (ms > SelectMsMax) SelectMsMax = ms;
        return frame;
    }

    private void Apply(TerrainFrame frame, bool force)
    {
        Frame = frame;
        if (frame.Triangles > Peak.Triangles) Peak = (frame.Nodes, frame.Triangles, frame.Draws);
        var dry = frame.Dry;
        var wet = frame.Wet;
        if (!_wetProgram && wet.Count > 0)
        {
            dry = new List<LodNode>(frame.Dry);
            dry.AddRange(frame.Wet);
            wet = new List<LodNode>();
        }
        if (force || !Same(dry, _lastDry)) { Write(_dry.Multimesh, ref _dryBuf, dry); _lastDry = dry; Uploads++; }
        if (force || !Same(wet, _lastWet)) { Write(_wet.Multimesh, ref _wetBuf, wet); _lastWet = wet; }
        var range = frame.Ranges.ToArray();
        if (!SameRange(range, _lastRange))
        {
            var f = Array.ConvertAll(range, r => (float)r);
            _dryMat.SetShaderParameter("tl_range", f);
            if (_wetMat != _dryMat) _wetMat.SetShaderParameter("tl_range", f);
            _lastRange = range;
        }
        if (frame.CapRelax != _lastRelax)
        {
            var fit = new Vector4(Field.CapGrid?.Rows ?? 0, frame.CapRelax, 0, 0);
            _dryMat.SetShaderParameter("tl_cap_fit", fit);
            if (_wetMat != _dryMat) _wetMat.SetShaderParameter("tl_cap_fit", fit);
            _lastRelax = frame.CapRelax;
        }
    }

    private static bool SameRange(double[] a, double[] b)
    {
        if (a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }

    private static bool Same(List<LodNode> a, List<LodNode> b)
    {
        if (a.Count != b.Count) return false;
        for (int i = 0; i < a.Count; i++)
            if (a[i].X != b[i].X || a[i].Z != b[i].Z || a[i].Size != b[i].Size || a[i].Level != b[i].Level) return false;
        return true;
    }

    /// <summary>
    /// The pieces into one MultiMesh: identity transform + custom (x, z, size, level). The instance capacity grows in
    /// powers of two (never past <see cref="TerrainLod.MaxNodes"/>), so a moving camera re-uploads the used part of a
    /// small buffer instead of reallocating; <c>VisibleInstanceCount</c> is the frame's count.
    /// </summary>
    private static void Write(MultiMesh mm, ref float[] buf, List<LodNode> nodes)
    {
        int cap = mm.InstanceCount;
        if (cap < nodes.Count || cap == 0)
        {
            int grown = MinCapacity;
            while (grown < nodes.Count) grown *= 2;
            cap = Math.Max(Math.Min(grown, TerrainLod.MaxNodes), nodes.Count);
            mm.VisibleInstanceCount = 0;
            mm.InstanceCount = cap;
        }
        if (buf.Length != cap * Stride) buf = new float[cap * Stride];
        for (int i = 0; i < nodes.Count; i++)
        {
            int o = i * Stride;
            var n = nodes[i];
            buf[o] = 1; buf[o + 1] = 0; buf[o + 2] = 0; buf[o + 3] = 0;
            buf[o + 4] = 0; buf[o + 5] = 1; buf[o + 6] = 0; buf[o + 7] = 0;
            buf[o + 8] = 0; buf[o + 9] = 0; buf[o + 10] = 1; buf[o + 11] = 0;
            buf[o + 12] = (float)n.X; buf[o + 13] = (float)n.Z; buf[o + 14] = (float)n.Size; buf[o + 15] = n.Level;
        }
        mm.Buffer = buf;
        mm.VisibleInstanceCount = nodes.Count;
    }

    /// <summary>One line for the logs and the bench result: the last frame, the viewport it was selected for, the field.</summary>
    public string Summary()
    {
        var f = Frame;
        return f is null
            ? $"terrain[no frame {Field.Summary()}]"
            : $"terrain[pieces={f.Nodes} dry={f.Dry.Count} wet={f.Wet.Count} draws={f.Draws} triangles={f.Triangles} "
              + $"submitted={f.Nodes * 2 * TerrainLod.PatchN * TerrainLod.PatchN} peak={Peak.Pieces}/{Peak.Triangles}/{Peak.Draws} "
              + $"select_ms={(Selections > 0 ? SelectMsTotal / Selections : 0):0.###}/{SelectMsMax:0.###} over {Selections} uploads={Uploads} "
              + $"viewport={ViewportPx}px pixel_scale={PixelScale:0.#} "
              + $"rings=[{string.Join(",", f.Ranges.ConvertAll(r => r.ToString("0.#")))}] relax={f.CapRelax} cover={Field.Coverage(f):0.######} "
              + $"{Field.Summary()}]";
    }
}
