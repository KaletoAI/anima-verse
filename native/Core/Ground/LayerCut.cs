using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Ground;

/// <summary>One row of the layer table (<c>TerrainLayer</c> in <c>packages/scene-render/src/layerCut.ts</c>).</summary>
public sealed record TerrainLayer(int Index, string Kind, string Surface, double EdgeBlendM, bool Water, string? BedKind);

/// <summary>The numbers a reader needs to decode the mask bytes (<c>TerrainLayerFormat</c>), shipped with every answer.</summary>
public sealed record LayerFormat(string Sig, double TileM, double IdStepM, double SdStepM, double SdBandM,
                                 double SdZero, double SdCodesPerM);

/// <summary>One baked tile of <c>GET /play/terrain-layers?keys=…</c>; a tile of one ground carries <c>uniform</c> only.</summary>
public sealed record LayerTile(double OriginX, double OriginZ, int? Uniform, int IdSize, int SdSize, byte[]? Id, byte[]? Sd);

/// <summary>The coarse world-wide id mask (<c>TerrainLayerOverview</c>) — what the ground wears beyond the fine tiles.</summary>
public sealed record LayerOverview(double OriginX, double OriginZ, double StepM, int Cols, int Rows, byte[]? Id);

/// <summary>The INDEX answer (no keys): format, table, overview, which tiles exist.</summary>
public sealed record LayerIndex(LayerFormat Format, List<TerrainLayer> Layers, LayerOverview? Overview, List<string> TileKeys);

/// <summary>The BATCH answer (keys): format, table, the tiles (keyed <c>"tx,tz"</c>, payload order).</summary>
public sealed record LayerBatch(LayerFormat Format, List<TerrainLayer> Layers, List<KeyValuePair<string, LayerTile>> Tiles);

/// <summary>The loaded masks packed into ONE square window (<c>LayerMaskWindow</c>).</summary>
public sealed class LayerMaskWindow
{
    public double OriginX, OriginZ, IdStep, SdStep, SdZero, SdCodesPerM, SdBandM;
    public int IdSize, SdSize;
    public byte[] Id = Array.Empty<byte>();
    public byte[] Sd = Array.Empty<byte>();
}

/// <summary>What the compositor reads at one world point — the CPU twin of <c>lcCompose</c>'s selection.</summary>
public readonly record struct LayerSample(int A, int B, double Sd, double SdPushed, double Weight, string Source);

/// <summary>
/// Exact port of the layer cut of the ground (<c>packages/scene-render/src/layerCut.ts</c>, contract § A16.7):
/// the payload, the window packing (<c>packLayerWindow</c>), the CPU twins of the shader lookups
/// (<c>layerPairAt</c>, <c>layerSdAt</c>, <c>layerSdBlockAt</c>, <c>topLayerAt</c>), the edge noise
/// (<c>lcNoise</c>, <c>lcPushedSd</c>) and the cut (<c>layerWeight</c>). The mask tiles are fetched by the height
/// tiles' want set (<see cref="Terrain.HeightTiles.WantedTiles"/>).
/// Same double arithmetic in the same order; <c>Check/GroundCheck.cs</c> compares it with values the TS
/// functions wrote (<c>fixtures/ground_reference.mjs</c>).
/// </summary>
public static class LayerCut
{
    /// <summary><c>LC_EDGE_NOISE_M</c> / <c>LC_EDGE_WAVE_M</c>: how far the noise pushes an edge, over what wavelength.</summary>
    public const double EdgeNoiseM = 0.5, EdgeWaveM = 2;
    /// <summary><c>LC_MAX_LAYERS</c> (layerGround.ts): the shader's uniform array size.</summary>
    public const int MaxLayers = 64;
    /// <summary><c>SLICE_PX</c> (layerGround.ts): edge length of one slice of the surface array.</summary>
    public const int SlicePx = 512;
    /// <summary><c>LAYER_BATCH_MAX</c> (ground.ts) = the server's <c>terrain_layers.BATCH_MAX</c>.</summary>
    public const int BatchMax = 16;

    // ── Payload ────────────────────────────────────────────────────────────

    public static LayerFormat ParseFormat(JsonElement root) => new(
        Json.Str(root, "sig"), Json.Num(root, "tile_m"), Json.Num(root, "id_step_m"), Json.Num(root, "sd_step_m"),
        Json.Num(root, "sd_band_m"), Json.Num(root, "sd_zero"), Json.Num(root, "sd_codes_per_m"));

    public static List<TerrainLayer> ParseLayers(JsonElement root)
    {
        var list = new List<TerrainLayer>();
        foreach (var l in Json.Arr(root, "layers"))
        {
            if (l.ValueKind != JsonValueKind.Object) continue;
            var bed = Json.Str(l, "bed_kind");
            list.Add(new TerrainLayer((int)Json.Num(l, "index"), Json.Str(l, "kind"), Json.Str(l, "surface"),
                                      Json.Num(l, "edge_blend_m"), Json.Bool(l, "water"), bed.Length > 0 ? bed : null));
        }
        return list;
    }

    public static LayerIndex ParseIndex(JsonElement root)
    {
        LayerOverview? ov = null;
        if (root.TryGetProperty("overview", out var o) && o.ValueKind == JsonValueKind.Object)
            ov = new LayerOverview(Json.Num(o, "origin_x"), Json.Num(o, "origin_z"), Json.Num(o, "step_m"),
                                   (int)Json.Num(o, "cols"), (int)Json.Num(o, "rows"), Base64(Json.Str(o, "id")));
        var keys = Json.Arr(root, "tile_keys").Where(k => k.ValueKind == JsonValueKind.String)
                       .Select(k => k.GetString() ?? "").ToList();
        return new LayerIndex(ParseFormat(root), ParseLayers(root), ov, keys);
    }

    public static LayerBatch ParseBatch(JsonElement root)
    {
        var tiles = new List<KeyValuePair<string, LayerTile>>();
        if (root.TryGetProperty("tiles", out var t) && t.ValueKind == JsonValueKind.Object)
            foreach (var p in t.EnumerateObject())
            {
                var e = p.Value;
                if (e.ValueKind != JsonValueKind.Object) continue;
                int? uniform = e.TryGetProperty("uniform", out var u) && u.ValueKind == JsonValueKind.Number
                    ? Js.ToInt32(u.GetDouble()) : null;
                tiles.Add(new(p.Name, new LayerTile(Json.Num(e, "origin_x"), Json.Num(e, "origin_z"), uniform,
                    (int)Json.Num(e, "id_size"), (int)Json.Num(e, "sd_size"),
                    Base64(Json.Str(e, "id")), Base64(Json.Str(e, "sd")))));
            }
        return new LayerBatch(ParseFormat(root), ParseLayers(root), tiles);
    }

    /// <summary>base64 → bytes; empty/absent → null (<c>base64Bytes</c>).</summary>
    public static byte[]? Base64(string? b64)
    {
        if (string.IsNullOrEmpty(b64)) return null;
        try { return Convert.FromBase64String(b64); }
        catch (FormatException) { return null; }
    }

    /// <summary>JS <c>key.split(',').map(Number)</c> for a <c>"tx,tz"</c> key; false when either part is not finite.</summary>
    public static bool TryKey(string key, out double tx, out double tz)
    {
        tx = tz = double.NaN;
        var parts = key.Split(',');
        if (parts.Length < 2) return false;
        tx = JsNumber(parts[0]);
        tz = JsNumber(parts[1]);
        return double.IsFinite(tx) && double.IsFinite(tz);
    }

    private static double JsNumber(string s)
    {
        s = s.Trim();
        if (s.Length == 0) return 0;  // Number('') = 0
        return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : double.NaN;
    }

    // ── Edge look ──────────────────────────────────────────────────────────

    /// <summary><c>lcNoise</c>: value noise in [0, 1) over world metres, the fract-sin hash.</summary>
    public static double Noise(double x, double z)
    {
        static double Hash(double px, double pz)
        {
            double s = Math.Sin(px * 12.9898 + pz * 78.233) * 43758.5453;
            return s - Math.Floor(s);
        }
        double ix = Math.Floor(x), iz = Math.Floor(z);
        double fx = x - ix, fz = z - iz;
        double wx = fx * fx * (3 - 2 * fx), wz = fz * fz * (3 - 2 * fz);
        double a = Hash(ix, iz), b = Hash(ix + 1, iz), c = Hash(ix, iz + 1), d = Hash(ix + 1, iz + 1);
        return (a * (1 - wx) + b * wx) * (1 - wz) + (c * (1 - wx) + d * wx) * wz;
    }

    /// <summary><c>lcPushedSd</c>: the baked distance plus the noise push, capped at half the blend width.</summary>
    public static double PushedSd(double sd, double blendM, double x, double z)
    {
        double cap = Math.Min(EdgeNoiseM, 0.5 * Math.Max(blendM, 0));
        if (!(cap > 0)) return sd;
        return sd + (Noise(x / EdgeWaveM + 5, z / EdgeWaveM + 23) * 2 - 1) * cap;
    }

    /// <summary><c>layerWeight</c>: how much of layer A a fragment shows (smoothstep of the width, or the pixel-wide step).</summary>
    public static double Weight(double sd, double blendM, double fw)
    {
        static double Clamp01(double v) => v < 0 ? 0 : v > 1 ? 1 : v;
        if (blendM > 0)
        {
            double t = Clamp01((sd + blendM * 0.5) / blendM);
            return t * t * (3 - 2 * t);
        }
        return Clamp01(sd / Math.Max(fw, 1e-6) + 0.5);
    }

    public static double DecodeSd(double code, double zero, double codesPerM)
        => (code - zero) / (codesPerM != 0 && !double.IsNaN(codesPerM) ? codesPerM : 1);

    // ── The window ─────────────────────────────────────────────────────────

    /// <summary>
    /// <c>packLayerWindow</c>: the held tiles as ONE square window over their bounding box (larger axis wins),
    /// a uniform tile filled with its layer on both halves, a missing tile left at pair (0, 0) / sd byte 255.
    /// </summary>
    public static LayerMaskWindow? Pack(IReadOnlyList<KeyValuePair<string, LayerTile>> tiles, LayerFormat fmt)
    {
        if (tiles.Count == 0 || !(fmt.TileM > 0)) return null;
        double tx0 = double.PositiveInfinity, tz0 = double.PositiveInfinity;
        double tx1 = double.NegativeInfinity, tz1 = double.NegativeInfinity;
        foreach (var (key, _) in tiles)
        {
            if (!TryKey(key, out var tx, out var tz)) continue;
            tx0 = Math.Min(tx0, tx); tz0 = Math.Min(tz0, tz);
            tx1 = Math.Max(tx1, tx); tz1 = Math.Max(tz1, tz);
        }
        if (!double.IsFinite(tx0)) return null;
        int idPer = (int)Js.Round(fmt.TileM / fmt.IdStepM);
        int sdPer = (int)Js.Round(fmt.TileM / fmt.SdStepM);
        int span = (int)Math.Max(tx1 - tx0 + 1, tz1 - tz0 + 1);
        int idN = idPer * span, sdN = sdPer * span;
        var id = new byte[idN * idN * 2];
        var sd = new byte[sdN * sdN];
        Array.Fill(sd, (byte)255);
        foreach (var (key, tile) in tiles)
        {
            if (!TryKey(key, out var tx, out var tz)) continue;
            int ix0 = (int)(tx - tx0) * idPer, iz0 = (int)(tz - tz0) * idPer;
            int sx0 = (int)(tx - tx0) * sdPer, sz0 = (int)(tz - tz0) * sdPer;
            if (tile.Uniform is int uni)
            {
                byte layer = (byte)(uni & 255);
                for (int j = 0; j < idPer; j++)
                {
                    int dst = ((iz0 + j) * idN + ix0) * 2;
                    for (int i = 0; i < idPer; i++) { id[dst] = layer; id[dst + 1] = layer; dst += 2; }
                }
                continue;
            }
            if (tile.Id is { } idBytes)
                for (int j = 0; j < idPer; j++)
                    CopyRow(idBytes, j * idPer * 2, idPer * 2, id, ((iz0 + j) * idN + ix0) * 2);
            if (tile.Sd is { } sdBytes)
                for (int j = 0; j < sdPer; j++)
                    CopyRow(sdBytes, j * sdPer, sdPer, sd, (sz0 + j) * sdN + sx0);
        }
        return new LayerMaskWindow
        {
            OriginX = tx0 * fmt.TileM, OriginZ = tz0 * fmt.TileM, IdStep = fmt.IdStepM, SdStep = fmt.SdStepM,
            IdSize = idN, SdSize = sdN, Id = id, Sd = sd,
            SdZero = fmt.SdZero, SdCodesPerM = fmt.SdCodesPerM, SdBandM = fmt.SdBandM,
        };
    }

    /// <summary><c>dst.set(src.subarray(at, at + len), to)</c> — a short source copies what it has.</summary>
    private static void CopyRow(byte[] src, int at, int len, byte[] dst, int to)
    {
        int n = Math.Min(len, Math.Max(src.Length - at, 0));
        if (n > 0) Array.Copy(src, at, dst, to, Math.Min(n, dst.Length - to));
    }

    private static int TexelOf(double p, double origin, double step, int size)
    {
        double i = Math.Floor((p - origin) / step);
        return i < 0 ? 0 : i >= size ? size - 1 : (int)i;
    }

    /// <summary><c>layerPairAt</c>: the (A, B) pair at a world point; no window = bare ground.</summary>
    public static (int A, int B) PairAt(LayerMaskWindow? win, double x, double z)
    {
        if (win is null) return (0, 0);
        int i = TexelOf(x, win.OriginX, win.IdStep, win.IdSize), j = TexelOf(z, win.OriginZ, win.IdStep, win.IdSize);
        int k = (j * win.IdSize + i) * 2;
        return (win.Id[k], win.Id[k + 1]);
    }

    /// <summary><c>layerSdAt</c>: the raw sd texel a point falls in, metres.</summary>
    public static double SdAt(LayerMaskWindow? win, double x, double z)
    {
        if (win is null) return 0;
        int i = TexelOf(x, win.OriginX, win.SdStep, win.SdSize), j = TexelOf(z, win.OriginZ, win.SdStep, win.SdSize);
        return DecodeSd(win.Sd[j * win.SdSize + i], win.SdZero, win.SdCodesPerM);
    }

    /// <summary><c>layerSdBlockAt</c>: bilinear over the sd texels of the point's OWN id texel, extrapolated.</summary>
    public static double SdBlockAt(LayerMaskWindow? win, double x, double z)
    {
        if (win is null) return 0;
        double ratio = Math.Max(Js.Round(win.IdStep / win.SdStep), 1);
        int ix = TexelOf(x, win.OriginX, win.IdStep, win.IdSize), iz = TexelOf(z, win.OriginZ, win.IdStep, win.IdSize);
        double t0x = ix * ratio, t0z = iz * ratio;
        double t1x = t0x + ratio - 1, t1z = t0z + ratio - 1;
        double c0x = win.OriginX + (t0x + 0.5) * win.SdStep, c0z = win.OriginZ + (t0z + 0.5) * win.SdStep;
        double spanM = (ratio - 1) * win.SdStep;
        double fx = spanM > 0 ? (x - c0x) / spanM : 0, fz = spanM > 0 ? (z - c0z) / spanM : 0;
        double At(double i, double j)
        {
            int ci = i < 0 ? 0 : i >= win.SdSize ? win.SdSize - 1 : (int)i;
            int cj = j < 0 ? 0 : j >= win.SdSize ? win.SdSize - 1 : (int)j;
            return DecodeSd(win.Sd[cj * win.SdSize + ci], win.SdZero, win.SdCodesPerM);
        }
        double s00 = At(t0x, t0z), s10 = At(t1x, t0z), s01 = At(t0x, t1z), s11 = At(t1x, t1z);
        return (s00 + (s10 - s00) * fx) * (1 - fz) + (s01 + (s11 - s01) * fx) * fz;
    }

    /// <summary><c>topLayerAt</c>: which layer is on top at a world point (sign of the block distance).</summary>
    public static int TopLayerAt(LayerMaskWindow? win, double x, double z)
    {
        if (win is null) return 0;
        var (a, b) = PairAt(win, x, z);
        if (a == b) return a;
        return SdBlockAt(win, x, z) >= 0 ? a : b;
    }

    /// <summary>
    /// The CPU twin of <c>lcCompose</c>'s selection, in the shader's order: inside the near window the fine
    /// masks (pair + block distance), else the coarse overview (pair, distance = the band), else bare ground;
    /// then the noise push on the distance with layer A's blend width and the cut weight. <paramref name="blendOf"/>
    /// is the shader's <c>uLcLayer[a].x</c>.
    /// </summary>
    public static LayerSample Compose(LayerMaskWindow? win, LayerOverview? far, Func<int, double> blendOf,
                                      double x, double z, double pixelM)
    {
        int a, b;
        double sd = win?.SdBandM ?? 8;
        string source;
        double nearN = win?.IdSize ?? 0;
        if (win is not null && nearN > 0.5)
        {
            double nx = (x - win.OriginX) / win.IdStep, nz = (z - win.OriginZ) / win.IdStep;
            if (nx >= 0 && nz >= 0 && nx < nearN && nz < nearN)
            {
                (a, b) = PairAt(win, x, z);
                sd = SdBlockAt(win, x, z);
                return Finish(a, b, sd, "near");
            }
        }
        if (far is { Id: { } ids } && far.Cols > 1 && far.Rows > 1 && far.StepM > 0 && ids.Length >= far.Cols * far.Rows * 2)
        {
            int fi = (int)Math.Clamp(Math.Floor((x - far.OriginX) / far.StepM), 0, far.Cols - 1);
            int fj = (int)Math.Clamp(Math.Floor((z - far.OriginZ) / far.StepM), 0, far.Rows - 1);
            int k = (fj * far.Cols + fi) * 2;
            (a, b) = (ids[k], ids[k + 1]);
            source = "far";
        }
        else
        {
            (a, b) = (0, 0);
            source = "none";
        }
        return Finish(a, b, sd, source);

        LayerSample Finish(int la, int lb, double d, string src)
        {
            double blend = blendOf(la);
            double pushed = PushedSd(d, blend, x, z);
            double w = Weight(pushed, blend, pixelM);
            return new LayerSample(la, lb, d, pushed, la == lb ? 1 : w, src);
        }
    }
}

/// <summary>
/// The pure numbers of the NATURAL GROUND (<c>client3d/src/scene/naturalGroundMath.ts</c>) — the single source of
/// the literals <see cref="GroundShader"/> prints, like the browser prints its shader out of the TS constants.
/// Since E3 only stages (2) colour patches and (3) height AO run on the terrain: stage (1) is guarded by
/// <c>USE_MAP</c>, and the terrain material carries no map (the compositor does its own anti-tile).
/// </summary>
public static class NaturalGround
{
    public const double DetailScale = 0.23, DetailOffset = 0.5, MixM = 7, MixMax = 0.5;
    public const double TintM = 25, TintAmp = 0.08;
    public const double AoRingM = 3, AoSpanM = 2, AoDown = 0.12, AoUp = 0.06;

    /// <summary><c>ngDetailUv</c>: the broad anti-tile sample's coordinate, <c>uv · 0.23 + 0.5</c>.</summary>
    public static (double U, double V) DetailUv(double u, double v) => (u * DetailScale + DetailOffset, v * DetailScale + DetailOffset);

    /// <summary><c>ngTintFactors</c>.</summary>
    public static (double Brightness, double Saturation) TintFactors(double nBright, double nSat)
        => (1 + TintAmp * (nBright * 2 - 1), 1 + TintAmp * (nSat * 2 - 1));

    /// <summary>The two noise readings the shader takes at a point (<c>ngNoise(p/25)</c>, <c>ngNoise(p/25 + (37, 11))</c>).</summary>
    public static (double NBright, double NSat) TintNoise(double x, double z)
        => (LayerCut.Noise(x / TintM, z / TintM), LayerCut.Noise(x / TintM + 37, z / TintM + 11));

    /// <summary><c>ngAoShade</c>: the AO term (multiplier − 1) for a ring mean against the own height.</summary>
    public static double AoShade(double ringMean, double own)
    {
        double t = Math.Min(Math.Max((ringMean - own) / AoSpanM, -1), 1);
        return t > 0 ? -AoDown * t : -AoUp * t;
    }

    /// <summary><c>ngAoTaps</c>.</summary>
    public static (double Dx, double Dz)[] AoTaps(double ringM = AoRingM)
        => new[] { (ringM, 0.0), (-ringM, 0.0), (0.0, ringM), (0.0, -ringM) };

    /// <summary><c>ngFieldUv</c>: world point → texel-centred texture coordinate of the overview height texture.</summary>
    public static (double U, double V, bool Inside) FieldUv(double x, double z, HeightGrid field)
    {
        double u = ((x - field.OriginX) / field.Step + 0.5) / field.Cols;
        double v = ((z - field.OriginZ) / field.Step + 0.5) / field.Rows;
        return (u, v, u >= 0 && u <= 1 && v >= 0 && v <= 1);
    }

    /// <summary>
    /// The CPU twin of the shader's <c>ngHeightAt</c>: a LINEAR, clamp-to-edge texture fetch at the texel-centred
    /// coordinate — i.e. bilinear over the lattice, clamped to the border texels. (The GPU does it in half float
    /// with fixed-point weights; this is the exact value.)
    /// </summary>
    public static double FieldHeightAt(HeightGrid g, double x, double z)
    {
        double fx = Math.Clamp((x - g.OriginX) / g.Step, 0, g.Cols - 1);
        double fz = Math.Clamp((z - g.OriginZ) / g.Step, 0, g.Rows - 1);
        int i = (int)Math.Min(Math.Floor(fx), g.Cols - 2), j = (int)Math.Min(Math.Floor(fz), g.Rows - 2);
        double tx = fx - i, tz = fz - j;
        double n = g.At(i, j) * (1 - tx) + g.At(i + 1, j) * tx;
        double s = g.At(i, j + 1) * (1 - tx) + g.At(i + 1, j + 1) * tx;
        return n * (1 - tz) + s * tz;
    }

    /// <summary>The whole AO stage at a point: what the albedo is multiplied by, minus one (0 outside the raster).</summary>
    public static double AoAt(HeightGrid g, double x, double z)
    {
        double own = FieldHeightAt(g, x, z);
        double sum = 0;
        foreach (var (dx, dz) in AoTaps()) sum += FieldHeightAt(g, x + dx, z + dz);
        double shade = AoShade(sum / 4, own);
        return FieldUv(x, z, g).Inside ? shade : 0;
    }
}
