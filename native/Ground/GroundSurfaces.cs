using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Ground;

/// <summary>What the ground load produced, for the log/status line, the bench result and the check.</summary>
public sealed class GroundStats
{
    /// <summary>"layers" = the browser's ground material; "plain" = the S1a vertex-colour material (fallback / <c>--plain-ground</c>).</summary>
    public string Mode = "plain";
    public string? Reason;
    public int Layers, Slices, TexturesLoaded, TextureFailures, ColourSlices;
    public int WantedTiles, MaskTiles, WindowIdSize, WindowSdSize, FarCols, FarRows;
    public float AoStrength;
    public int NearHeightCols, NearHeightRows;
    public double NormalSpan;

    public string Summary() => Mode != "layers"
        ? $"ground[plain{(Reason is null ? "" : ": " + Reason)}]"
        : $"ground[layers={Layers} slices={Slices} textures={TexturesLoaded} texture_failures={TextureFailures} "
          + $"colour_slices={ColourSlices} mask_tiles={MaskTiles}/{WantedTiles} window={WindowIdSize}/{WindowSdSize} "
          + $"far={FarCols}x{FarRows} ao={AoStrength:0} near_heights={NearHeightCols}x{NearHeightRows} "
          + $"normal_span={NormalSpan:0.###}]";
}

/// <summary>
/// The browser's ground SURFACES on the S1a terrain meshes (Task S3b) — port of what
/// <c>client3d/src/scene/ground.ts</c> (<c>applyLayers</c>, <c>refreshLayerTiles</c>, <c>rebuildBase</c>),
/// <c>layerGround.ts</c> (<c>setLayerTable</c>, <c>setLayerOverview</c>, <c>setLayerTiles</c>),
/// <c>naturalGround.ts</c> (<c>setNaturalGroundField</c>) and <c>terrainLod.ts</c> (<c>setField</c>: near/far
/// height window, normal span) feed into the one ground material, from the same requests:
///
///   1. <c>GET /play/terrain</c> — the type catalog: a kind's colour (<c>kindColor</c>, fallback #888888) and
///      its library surface (<c>surfaceOf</c>: the type's <c>surface</c>, else the kind itself when the library
///      has an entry of that name);
///   2. <c>GET /assets/surface-textures</c> — the library (<c>getSurfaceTextures</c>: a failure is an empty
///      library; entries need a kind and a url or a blend; <c>size_m || 3</c>). Blend compositions have no
///      url, so they load nothing and a layer naming one wears its colour — the ground has not read blends
///      since the grid died (tiles.ts, E4);
///   3. <c>GET /play/terrain-layers</c> — the index (format, layer table, coarse overview mask, tile keys);
///   4. <c>GET /play/terrain-layers?keys=…</c> — the fine masks of <c>wantedTiles(tile_keys, tile_m, anchor,
///      560 m)</c>, nearest first, 16 keys per request (<c>LAYER_BATCH_MAX</c>);
///   5. each layer surface's image (<c>preloadSurfaceTexture</c>, one download per library id), drawn onto one
///      512² slice of a texture array; a layer without a loaded image gets a slice of its flat catalog colour.
///
/// The online path and <c>--check</c> run this one class. Any failure of steps 3/4 or of the texture build
/// throws; <see cref="WorldBuilder"/> then keeps the plain material and logs why. A single image that fails
/// only turns its slice into the colour slice — that is what the browser does (<c>.catch(() =&gt; {})</c>).
/// </summary>
public sealed class GroundSurfaces
{
    private const int DownloadConcurrency = 4;

    public LayerIndex Index { get; private set; } = null!;
    public LayerFormat Format { get; private set; } = null!;
    public List<TerrainLayer> Layers { get; private set; } = new();
    public List<string> Wanted { get; private set; } = new();
    public List<KeyValuePair<string, LayerTile>> Tiles { get; } = new();
    public LayerMaskWindow? Window { get; private set; }
    /// <summary>The coarse mask as bound (null = invalid → the shader's far size is 0).</summary>
    public LayerOverview? Far { get; private set; }
    /// <summary>The slices, in layer order, each RGBA8 512² with mipmaps.</summary>
    public List<Image> Slices { get; } = new();
    /// <summary>Per slice: <c>texture:&lt;surface&gt;</c> or <c>colour:#rrggbb</c>.</summary>
    public List<string> SliceSources { get; } = new();
    /// <summary>The 64 entries of the shader's <c>lc_layer</c>: edge_blend_m, metres per tile, 0, 0.</summary>
    public Vector4[] LayerParams { get; } = new Vector4[LayerCut.MaxLayers];
    /// <summary>Library id → decoded source size (before the 512² resample), for every image that loaded.</summary>
    public Dictionary<string, Vector2I> SourceSizes { get; } = new();
    public HeightLattice? NearHeights { get; private set; }
    public double[]? NearRect { get; private set; }
    public HeightLattice? FarHeights { get; private set; }
    public HeightGrid? AoField { get; private set; }
    public ShaderMaterial Material { get; private set; } = null!;
    public GroundStats Stats { get; } = new() { Mode = "layers" };

    private readonly Dictionary<string, (string? Url, double SizeM)> _library = new();
    private readonly Dictionary<string, Image> _loaded = new();
    private TerrainPayload _catalog = null!;

    public static async Task<GroundSurfaces> LoadAsync(IWorldSource source, WorldHeight height, double anchorX,
                                                       double anchorZ, Action<string> log)
    {
        var g = new GroundSurfaces();
        await g.Run(source, height, anchorX, anchorZ, log);
        return g;
    }

    private async Task Run(IWorldSource source, WorldHeight height, double anchorX, double anchorZ, Action<string> log)
    {
        using (var terrain = await source.GetTerrainAsync()) _catalog = TerrainPayload.Parse(terrain.RootElement);
        await LoadLibrary(source, log);

        using (var doc = await source.GetTerrainLayersAsync(Array.Empty<string>()))
            Index = LayerCut.ParseIndex(doc.RootElement);
        Format = Index.Format;
        Layers = Index.Layers.Take(LayerCut.MaxLayers).ToList();

        // The mask tiles the anchor wants (refreshLayerTiles): batches of 16; a failed batch keeps what stands.
        Wanted = LayerCut.WantedTiles(Index.TileKeys.ToHashSet(), Format.TileM, anchorX, anchorZ);
        for (int i = 0; i < Wanted.Count; i += LayerCut.BatchMax)
        {
            var keys = Wanted.Skip(i).Take(LayerCut.BatchMax).ToList();
            LayerBatch batch;
            try
            {
                using var doc = await source.GetTerrainLayersAsync(keys);
                batch = LayerCut.ParseBatch(doc.RootElement);
            }
            catch (Exception e)
            {
                log($"ground: mask batch failed ({e.Message}) — the missing tiles read as bare ground");
                break;
            }
            if (batch.Format.Sig.Length > 0 && batch.Format.Sig != Format.Sig)
                log($"ground: mask batch sig {batch.Format.Sig} differs from the index {Format.Sig} (the browser re-indexes; the spike keeps the tiles)");
            Tiles.AddRange(batch.Tiles);
        }
        Window = LayerCut.Pack(Tiles, Format);
        Far = Index.Overview is { } ov && ov.Cols > 1 && ov.Rows > 1 && ov.StepM > 0 && ov.Id is { } ids
              && ids.Length >= ov.Cols * ov.Rows * 2 ? ov : null;

        await LoadSurfaceImages(source, log);
        BuildSlices();
        BuildHeights(height, anchorX, anchorZ);
        BuildMaterial();

        Stats.Layers = Layers.Count;
        Stats.Slices = Slices.Count;
        Stats.ColourSlices = SliceSources.Count(s => s.StartsWith("colour:", StringComparison.Ordinal));
        Stats.TexturesLoaded = _loaded.Count;
        Stats.WantedTiles = Wanted.Count;
        Stats.MaskTiles = Tiles.Count;
        Stats.WindowIdSize = Window?.IdSize ?? 0;
        Stats.WindowSdSize = Window?.SdSize ?? 0;
        Stats.FarCols = Far?.Cols ?? 0;
        Stats.FarRows = Far?.Rows ?? 0;
        log("ground: " + Stats.Summary());
    }

    // ── Library + images ────────────────────────────────────────────────────

    private async Task LoadLibrary(IWorldSource source, Action<string> log)
    {
        try
        {
            using var doc = await source.GetSurfaceTexturesAsync();
            var root = doc.RootElement;
            var list = root.ValueKind == JsonValueKind.Array ? root.EnumerateArray()
                : Json.Arr(root, "textures");
            foreach (var t in list)
            {
                if (t.ValueKind != JsonValueKind.Object) continue;
                var kind = Json.Str(t, "kind");
                var url = Json.Str(t, "url");
                bool blend = t.TryGetProperty("blend", out var b) && b.ValueKind is not (JsonValueKind.Null or JsonValueKind.Undefined or JsonValueKind.False);
                if (kind.Length == 0 || (url.Length == 0 && !blend)) continue;
                double size = Json.Num(t, "size_m");
                _library[kind.ToLowerInvariant()] = (url.Length > 0 ? url : null, size != 0 ? size : 3);
            }
        }
        catch (Exception e)
        {
            // getSurfaceTextures: any failure is an empty library — every layer then wears its colour.
            log($"ground: surface library unavailable ({e.Message}) — colour slices only");
        }
    }

    private async Task LoadSurfaceImages(IWorldSource source, Action<string> log)
    {
        var wanted = Layers.Select(l => (l.Surface ?? "").ToLowerInvariant()).Distinct()
                           .Where(k => _library.TryGetValue(k, out var e) && e.Url is not null).ToList();
        using var gate = new SemaphoreSlim(DownloadConcurrency);
        var jobs = wanted.Select(async key =>
        {
            await gate.WaitAsync();
            try
            {
                var url = _library[key].Url!;
                var bytes = await source.GetBytesAsync(url);
                var (img, size) = await Task.Run(() => DecodeSlice(bytes));
                return (key, img, size, error: (string?)null);
            }
            catch (Exception e) { return (key, img: (Image?)null, size: default(Vector2I), error: e.Message); }
            finally { gate.Release(); }
        }).ToList();
        foreach (var (key, img, size, error) in await Task.WhenAll(jobs))
        {
            if (img is null)
            {
                Stats.TextureFailures++;
                log($"ground: surface '{key}' failed ({error}) — its layers wear the catalog colour");
                continue;
            }
            _loaded[key] = img;
            SourceSizes[key] = size;
        }
    }

    /// <summary>Decode PNG/JPEG/WebP and draw it onto one 512² RGBA slice (the canvas <c>drawImage</c> of setLayerTable).</summary>
    public static (Image Image, Vector2I SourceSize) DecodeSlice(byte[] bytes)
    {
        var img = new Image();
        Error err;
        if (bytes.Length > 8 && bytes[0] == 0x89 && bytes[1] == (byte)'P' && bytes[2] == (byte)'N' && bytes[3] == (byte)'G')
            err = img.LoadPngFromBuffer(bytes);
        else if (bytes.Length > 3 && bytes[0] == 0xFF && bytes[1] == 0xD8)
            err = img.LoadJpgFromBuffer(bytes);
        else if (bytes.Length > 12 && bytes[0] == (byte)'R' && bytes[1] == (byte)'I' && bytes[8] == (byte)'W' && bytes[9] == (byte)'E')
            err = img.LoadWebpFromBuffer(bytes);
        else
            throw new FormatException("not a PNG, JPEG or WebP image");
        if (err != Error.Ok || img.IsEmpty()) throw new FormatException($"image decode failed ({err})");
        var size = img.GetSize();
        if (img.IsCompressed()) img.Decompress();
        img.Convert(Image.Format.Rgba8);
        if (size.X != LayerCut.SlicePx || size.Y != LayerCut.SlicePx)
            img.Resize(LayerCut.SlicePx, LayerCut.SlicePx, Image.Interpolation.Bilinear);
        return (img, size);
    }

    // ── Slices + per-layer numbers (setLayerTable) ──────────────────────────

    /// <summary><c>kindColor</c>: the catalog colour, else the server's grey.</summary>
    public string KindColor(string kind) => _catalog.KindColor(kind);

    /// <summary><c>surfaceOf</c>: the type's surface, else the kind itself when the library has it.</summary>
    public string SurfaceOf(string kind)
    {
        var key = (kind ?? "").ToLowerInvariant();
        var named = _catalog.TypeOf(key)?.Surface ?? "";
        return named.Length > 0 ? named : key.Length > 0 && _library.ContainsKey(key) ? key : "";
    }

    /// <summary><c>surfaceFor(id, 'wall')</c>: only a library entry whose image has LOADED answers.</summary>
    private (Image Image, double SizeM)? SurfaceFor(string? id)
    {
        var key = (id ?? "").ToLowerInvariant();
        return _library.TryGetValue(key, out var e) && _loaded.TryGetValue(key, out var img) ? (img, e.SizeM) : null;
    }

    private void BuildSlices()
    {
        for (int index = 0; index < Layers.Count; index++)
        {
            var layer = Layers[index];
            var kind = !string.IsNullOrEmpty(layer.BedKind) ? layer.BedKind! : layer.Kind;
            var lib = SurfaceFor(layer.Surface);
            Image slice;
            if (lib is { } l)
            {
                slice = (Image)l.Image.Duplicate();
                SliceSources.Add("texture:" + (layer.Surface ?? "").ToLowerInvariant());
            }
            else
            {
                var css = KindColor(kind);
                var (r, g, b) = SliceColourBytes(css);
                slice = Image.CreateEmpty(LayerCut.SlicePx, LayerCut.SlicePx, false, Image.Format.Rgba8);
                slice.Fill(Color.Color8(r, g, b, 255));
                SliceSources.Add("colour:" + css);
            }
            slice.GenerateMipmaps();
            Slices.Add(slice);
            double size = SurfaceFor(SurfaceOf(kind))?.SizeM ?? 3;
            LayerParams[index] = new Vector4((float)layer.EdgeBlendM, (float)(size > 0 ? size : 3), 0, 0);
        }
        for (int index = Layers.Count; index < LayerCut.MaxLayers; index++) LayerParams[index] = new Vector4(0, 3, 0, 0);
        if (Slices.Count == 0)
        {
            var empty = Image.CreateEmpty(LayerCut.SlicePx, LayerCut.SlicePx, false, Image.Format.Rgba8);
            empty.GenerateMipmaps();
            Slices.Add(empty);
        }
    }

    /// <summary>
    /// The bytes the browser writes into a colour slice: <c>new THREE.Color(css)</c> — which (three r152+, colour
    /// management on) converts the sRGB hex into the LINEAR working space — then <c>Math.round(c.r · 255)</c> into
    /// a texture tagged sRGB. So the GPU decodes it a second time and the flat colour comes out darker than the
    /// catalog says. A browser quirk, mirrored on purpose: the two clients have to show the same ground.
    /// An unparseable colour stays three's default white.
    /// </summary>
    public static (byte R, byte G, byte B) SliceColourBytes(string css)
    {
        double r = 1, g = 1, b = 1;
        var s = (css ?? "").Trim();
        if (s.StartsWith('#') && (s.Length == 7 || s.Length == 4)
            && int.TryParse(s[1..], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var hex))
        {
            if (s.Length == 7) { r = ((hex >> 16) & 255) / 255.0; g = ((hex >> 8) & 255) / 255.0; b = (hex & 255) / 255.0; }
            else { r = ((hex >> 8) & 15) / 15.0; g = ((hex >> 4) & 15) / 15.0; b = (hex & 15) / 15.0; }
            r = SrgbToLinear(r); g = SrgbToLinear(g); b = SrgbToLinear(b);
        }
        return ((byte)Js.Round(r * 255), (byte)Js.Round(g * 255), (byte)Js.Round(b * 255));
    }

    /// <summary>three's <c>SRGBToLinear</c>.</summary>
    public static double SrgbToLinear(double c)
        => c < 0.04045 ? c * 0.0773993808 : Math.Pow(c * 0.9478672986 + 0.0521327014, 2.4);

    // ── Heights: AO field + the normal's near/far lattices ──────────────────

    private void BuildHeights(WorldHeight height, double anchorX, double anchorZ)
    {
        var ov = height.Overview.Grid;
        // setNaturalGroundField: a field too small, or flat, switches the AO off exactly.
        if (ov.Rows >= 2 && ov.Cols >= 2 && ov.Step > 0 && ov.Heights.Length > 0 && ov.Heights.Max() > ov.Heights.Min())
        {
            AoField = ov;
            Stats.AoStrength = 1;
        }
        // terrainLod.setField: base step = tile_step_m (else 2 m), the normal span = that step.
        double step = height.Overview.TileStepM > 0 ? height.Overview.TileStepM : 2;
        Stats.NormalSpan = step;
        FarHeights = TerrainNormal.BuildFar(ov);
        if (TerrainNormal.BuildNear(height, step, anchorX, anchorZ) is { } near)
        {
            NearHeights = near.Lattice;
            NearRect = near.Rect;
            Stats.NearHeightCols = near.Lattice.Cols;
            Stats.NearHeightRows = near.Lattice.Rows;
        }
    }

    // ── The material ────────────────────────────────────────────────────────

    private static ImageTexture Tex(int w, int h, Image.Format fmt, byte[] data)
        => ImageTexture.CreateFromImage(Image.CreateFromData(w, h, false, fmt, data));

    private static ImageTexture FloatTex(HeightLattice lat)
    {
        var bytes = new byte[lat.H.Length * 4];
        Buffer.BlockCopy(lat.H, 0, bytes, 0, bytes.Length);
        return Tex(lat.Cols, lat.Rows, Image.Format.Rf, bytes);
    }

    private void BuildMaterial()
    {
        var mat = new ShaderMaterial { Shader = GroundShader.Get() };
        var arr = new Texture2DArray();
        var err = arr.CreateFromImages(new Godot.Collections.Array<Image>(Slices));
        if (err != Error.Ok) throw new InvalidOperationException($"surface texture array: {err}");
        mat.SetShaderParameter("lc_surf", arr);
        mat.SetShaderParameter("lc_layer", LayerParams);
        if (Window is { } w)
        {
            mat.SetShaderParameter("lc_near_id", Tex(w.IdSize, w.IdSize, Image.Format.Rg8, w.Id));
            mat.SetShaderParameter("lc_near_sd", Tex(w.SdSize, w.SdSize, Image.Format.R8, w.Sd));
            mat.SetShaderParameter("lc_near", new Vector4((float)w.OriginX, (float)w.OriginZ, (float)w.IdStep, w.IdSize));
            mat.SetShaderParameter("lc_near_sd_geom", new Vector4((float)w.OriginX, (float)w.OriginZ, (float)w.SdStep, w.SdSize));
            mat.SetShaderParameter("lc_sd_code", new Vector2((float)w.SdZero, (float)w.SdCodesPerM));
            mat.SetShaderParameter("lc_band_m", (float)w.SdBandM);
        }
        else mat.SetShaderParameter("lc_near", new Vector4(0, 0, 1, 0));
        if (Far is { } f)
        {
            mat.SetShaderParameter("lc_far_id", Tex(f.Cols, f.Rows, Image.Format.Rg8, f.Id![..(f.Cols * f.Rows * 2)]));
            mat.SetShaderParameter("lc_far", new Vector4((float)f.OriginX, (float)f.OriginZ, (float)f.StepM, 0));
            mat.SetShaderParameter("lc_far_size", new Vector2(f.Cols, f.Rows));
        }
        else mat.SetShaderParameter("lc_far_size", Vector2.Zero);

        if (AoField is { } ao)
        {
            var half = new byte[ao.Heights.Length * 2];
            for (int k = 0; k < ao.Heights.Length; k++)
            {
                ushort bits = BitConverter.HalfToUInt16Bits((Half)ao.Heights[k]);
                half[2 * k] = (byte)(bits & 255);
                half[2 * k + 1] = (byte)(bits >> 8);
            }
            mat.SetShaderParameter("ng_height", Tex(ao.Cols, ao.Rows, Image.Format.Rh, half));
            mat.SetShaderParameter("ng_field", new Vector4((float)ao.OriginX, (float)ao.OriginZ, (float)ao.Step, 0));
            mat.SetShaderParameter("ng_field_size", new Vector2(ao.Cols, ao.Rows));
        }
        mat.SetShaderParameter("ng_strength", Stats.AoStrength);

        if (NearHeights is { } n && NearRect is { } r)
        {
            mat.SetShaderParameter("tl_near", FloatTex(n));
            mat.SetShaderParameter("tl_near_geom", new Vector4((float)n.OriginX, (float)n.OriginZ, (float)n.Step, 1));
            mat.SetShaderParameter("tl_near_level", new Vector4(n.Cols, n.Rows, (float)n.Step, 0));
            mat.SetShaderParameter("tl_near_rect", new Vector4((float)r[0], (float)r[1], (float)r[2], (float)r[3]));
        }
        if (FarHeights is { } fh)
        {
            mat.SetShaderParameter("tl_far", FloatTex(fh));
            mat.SetShaderParameter("tl_far_geom", new Vector4((float)fh.OriginX, (float)fh.OriginZ, (float)fh.Step, 1));
            mat.SetShaderParameter("tl_far_level", new Vector4(fh.Cols, fh.Rows, (float)fh.Step, 0));
        }
        mat.SetShaderParameter("tl_normal_span", (float)Stats.NormalSpan);
        Material = mat;
    }

    /// <summary>Put the ground material on every terrain mesh (overview + tiles), over the S1a vertex colour.</summary>
    public void ApplyTo(IEnumerable<GeometryInstance3D> nodes)
    {
        foreach (var n in nodes) n.MaterialOverride = Material;
    }
}
