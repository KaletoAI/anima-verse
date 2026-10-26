using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// The ground-surface part of <c>--check</c> (Task S3b). The fixture world's build already ran the ground step
/// (<see cref="WorldBuilder"/> → <see cref="GroundSurfaces"/>); this checks what it produced against numbers
/// derived BY HAND in <c>fixtures/README.md</c> ("Ground surfaces") and against values the browser's own TS
/// functions wrote (<c>fixtures/ground_reference.json</c>, from <c>ground_reference.mjs</c>):
///
///   • requests: the index, then ONE batch with the want set in the browser's order (nearest first);
///     surface images: one download per library id that a layer names, a blend and an unused entry never;
///   • the packed window (origin, sizes; id/sd bytes = the TS <c>packLayerWindow</c> bytes by SHA-256),
///     the coarse mask, every probe point's pair / raw sd / block sd / top layer / pushed sd / weight (TS),
///     the far branch (hand), the edge and tint noise, <c>ngTintFactors</c>, <c>ngAoShade</c>,
///     <c>ngFieldUv</c>, <c>layerWeight</c> cases (TS);
///   • the slices (which layer wears a texture, which its colour — and the colour-slice BYTES, = three's
///     <c>Color</c> quirk, TS), the per-layer numbers (edge blend, metres per tile), texture count, the
///     shader parameters, the material on every terrain mesh, the AO and the shading normal (hand);
///   • the fallbacks: a failing <c>/play/terrain-layers</c> keeps the plain material (logged), a failing
///     library gives colour slices only, <c>--plain-ground</c> asks for nothing.
/// </summary>
public static class GroundCheck
{
    private const double Tol = 1e-9;

    public static async Task<string> RunAsync(Node3D world, FixtureSource source, WorldBuilder builder, WorldStats stats,
                                              string dir)
    {
        var g = builder.Ground ?? throw new InvalidOperationException($"ground: no layer material ({stats.Ground.Summary()})");
        Expect("ground mode", stats.Ground.Mode == "layers", stats.Ground.Summary());
        using var refDoc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "ground_reference.json")));
        var r = refDoc.RootElement;

        // ---- requests (hand: README "Ground surfaces", want order) ----
        var wantHand = new[] { "2,3", "2,4", "3,3", "3,4", "4,3", "5,3" };
        Expect("want set = TS wantedTiles", g.Wanted.SequenceEqual(r.GetProperty("want").EnumerateArray().Select(e => e.GetString()!)),
               string.Join(";", g.Wanted));
        Expect("want set (hand)", g.Wanted.SequenceEqual(wantHand), string.Join(";", g.Wanted));
        Expect("layer requests", source.LayerRequests.SequenceEqual(new[] { "", string.Join(";", wantHand) }),
               string.Join(" | ", source.LayerRequests));
        var surfaceGets = source.ByteRequests.Where(u => u.StartsWith("/assets/surface-textures/", StringComparison.Ordinal)).ToList();
        Expect("surface downloads", surfaceGets.OrderBy(u => u, StringComparer.Ordinal).SequenceEqual(new[]
               {
                   "/assets/surface-textures/dark_stone_2.jpg", "/assets/surface-textures/ground_grass.png",
                   "/assets/surface-textures/meadow_missing.png",
               }), string.Join(";", surfaceGets));

        // ---- window + overview ----
        var w = g.Window ?? throw new InvalidOperationException("no mask window");
        var rw = r.GetProperty("window");
        Expect("window (hand)", w.OriginX == 64 && w.OriginZ == 96 && w.IdSize == 128 && w.SdSize == 256 && w.IdStep == 1
                                && w.SdStep == 0.5 && w.SdZero == 128 && w.SdCodesPerM == 127.0 / 8 && w.SdBandM == 8,
               $"{w.OriginX},{w.OriginZ} {w.IdSize}/{w.SdSize}");
        Expect("window = TS", w.OriginX == rw.GetProperty("originX").GetDouble() && w.IdSize == rw.GetProperty("idSize").GetInt32()
                              && w.SdSize == rw.GetProperty("sdSize").GetInt32(), rw.ToString());
        Expect("id bytes = TS packLayerWindow", Sha(w.Id) == rw.GetProperty("idSha256").GetString(), Sha(w.Id));
        Expect("sd bytes = TS packLayerWindow", Sha(w.Sd) == rw.GetProperty("sdSha256").GetString(), Sha(w.Sd));
        Expect("mask tiles", g.Tiles.Count == 6, $"{g.Tiles.Count}");
        var far = g.Far ?? throw new InvalidOperationException("no coarse mask");
        Expect("coarse mask (hand)", far.OriginX == 32 && far.OriginZ == 64 && far.StepM == 8 && far.Cols == 24 && far.Rows == 24,
               $"{far.OriginX},{far.OriginZ} {far.Cols}x{far.Rows}");

        // ---- probes against the TS functions ----
        Func<int, double> blendOf = a => a < g.Layers.Count ? g.Layers[a].EdgeBlendM : 0;
        int probes = 0;
        foreach (var p in r.GetProperty("probes").EnumerateArray())
        {
            double x = p.GetProperty("x").GetDouble(), z = p.GetProperty("z").GetDouble(), px = p.GetProperty("pixelM").GetDouble();
            string at = $"probe ({x}, {z})";
            var (a, b) = LayerCut.PairAt(w, x, z);
            Expect($"{at} pair", a == p.GetProperty("a").GetInt32() && b == p.GetProperty("b").GetInt32(), $"({a},{b})");
            Near($"{at} raw sd", LayerCut.SdAt(w, x, z), p.GetProperty("sdRaw").GetDouble());
            Near($"{at} block sd", LayerCut.SdBlockAt(w, x, z), p.GetProperty("sdBlock").GetDouble());
            Expect($"{at} top", LayerCut.TopLayerAt(w, x, z) == p.GetProperty("top").GetInt32(), $"{LayerCut.TopLayerAt(w, x, z)}");
            var s = LayerCut.Compose(w, far, blendOf, x, z, px);
            Expect($"{at} compose source", s.Source == "near" && s.A == a && s.B == b, $"{s}");
            Near($"{at} pushed sd", s.SdPushed, p.GetProperty("pushed").GetDouble());
            if (a != b) Near($"{at} weight", s.Weight, p.GetProperty("weight").GetDouble());
            probes++;
        }
        // Hand (README): the 2 cm probe west of the hard line and the soft-edge probe.
        Near("hand: block sd 2 cm west of x = 100", LayerCut.SdBlockAt(w, 99.98, 100.2), -12 / 15.875 + 1.46 * (8 / 15.875), 1e-12);
        Near("hand: hard-cut weight", LayerCut.Compose(w, far, blendOf, 99.98, 100.2, 0.05).Weight,
             (-12 / 15.875 + 1.46 * (8 / 15.875)) / 0.05 + 0.5, 1e-12);
        Near("hand: block sd at the soft edge", LayerCut.SdBlockAt(w, 80.4, 138.6), 12 / 15.875 - 0.7 * (8 / 15.875), 1e-12);
        Expect("hand: missing tile inside the window = bare ground",
               LayerCut.Compose(w, far, blendOf, 110, 170, 0.05) is { A: 0, B: 0, Sd: 8, Source: "near" }, "");

        // ---- the far branch (hand: README) ----
        foreach (var (x, z, layer) in new[] { (33.0, 65.0, 3), (200.0, 100.0, 4), (40.0, 150.0, 1), (-100.0, -100.0, 3),
                                              (192.0, 100.0, 4), (63.99, 100.0, 1) })
        {
            var s = LayerCut.Compose(w, far, blendOf, x, z, 0.05);
            Expect($"far ({x}, {z})", s.Source == "far" && s.A == layer && s.B == layer && s.Sd == 8, $"{s}");
        }
        Expect("no masks at all = bare ground", LayerCut.Compose(null, null, blendOf, 5, 5, 0.05) is { A: 0, B: 0, Source: "none" }, "");

        // ---- noise, tint, AO, field uv, weights (TS) ----
        foreach (var n in r.GetProperty("noise").EnumerateArray())
        {
            double x = n.GetProperty("x").GetDouble(), z = n.GetProperty("z").GetDouble();
            Near($"edge noise ({x}, {z})", LayerCut.Noise(x / 2 + 5, z / 2 + 23), n.GetProperty("edge").GetDouble());
            Near($"wide noise ({x}, {z})", LayerCut.Noise(x / 7, z / 7), n.GetProperty("wide").GetDouble());
        }
        foreach (var t in r.GetProperty("tint").EnumerateArray())
        {
            double x = t.GetProperty("x").GetDouble(), z = t.GetProperty("z").GetDouble();
            var (nb, ns) = NaturalGround.TintNoise(x, z);
            var (br, sat) = NaturalGround.TintFactors(nb, ns);
            Near($"tint ({x}, {z}) brightness", br, t.GetProperty("brightness").GetDouble());
            Near($"tint ({x}, {z}) saturation", sat, t.GetProperty("saturation").GetDouble());
        }
        foreach (var a in r.GetProperty("ao").EnumerateArray())
            Near($"ngAoShade({a.GetProperty("ring")}, {a.GetProperty("own")})",
                 NaturalGround.AoShade(a.GetProperty("ring").GetDouble(), a.GetProperty("own").GetDouble()), a.GetProperty("shade").GetDouble());
        var ovGrid = builder.Height!.Overview.Grid;
        foreach (var u in r.GetProperty("fieldUv").EnumerateArray())
        {
            var (uu, vv, inside) = NaturalGround.FieldUv(u.GetProperty("x").GetDouble(), u.GetProperty("z").GetDouble(), ovGrid);
            Expect($"ngFieldUv ({u.GetProperty("x")}, {u.GetProperty("z")})",
                   Math.Abs(uu - u.GetProperty("u").GetDouble()) < Tol && Math.Abs(vv - u.GetProperty("v").GetDouble()) < Tol
                   && inside == u.GetProperty("inside").GetBoolean(), $"{uu} {vv} {inside}");
        }
        foreach (var c in r.GetProperty("weights").EnumerateArray())
            Near($"layerWeight({c.GetProperty("sd")}, {c.GetProperty("blend")}, {c.GetProperty("fw")})",
                 LayerCut.Weight(c.GetProperty("sd").GetDouble(), c.GetProperty("blend").GetDouble(), c.GetProperty("fw").GetDouble()),
                 c.GetProperty("w").GetDouble());
        // The AO at the fixture field (hand: README): exactly 0 inside a bilinear cell, the clamp shows at the border.
        Near("hand: AO at the anchor", NaturalGround.AoAt(ovGrid, 64, 128), 0, 1e-15);
        Near("hand: AO 1 m inside the west border", NaturalGround.AoAt(ovGrid, -255, 128), -0.000703125, 1e-15);
        Near("hand: AO outside the raster", NaturalGround.AoAt(ovGrid, -400, 0), 0, 0);

        // ---- slices + per-layer numbers ----
        var sources = new[] { "texture:grass", "texture:forest", "colour:#a08a60", "texture:grass", "colour:#7a9a50" };
        Expect("slice sources (hand)", g.SliceSources.SequenceEqual(sources), string.Join(";", g.SliceSources));
        var wantParams = new (float Blend, float Size)[] { (1.5f, 4f), (1.5f, 6f), (0f, 3f), (1.5f, 4f), (1.5f, 3f) };
        for (int i = 0; i < LayerCut.MaxLayers; i++)
        {
            var want = i < wantParams.Length ? new Vector4(wantParams[i].Blend, wantParams[i].Size, 0, 0) : new Vector4(0, 3, 0, 0);
            Expect($"layer {i} params", g.LayerParams[i] == want, $"{g.LayerParams[i]} vs {want}");
        }
        Expect("textures loaded / failed", g.Stats.TexturesLoaded == 2 && g.Stats.TextureFailures == 1 && g.Stats.ColourSlices == 2,
               g.Stats.Summary());
        Expect("source sizes (hand: PNG header, JPEG SOF)", g.SourceSizes["grass"] == new Vector2I(4, 2)
                                                            && g.SourceSizes["forest"] == new Vector2I(1024, 1024),
               string.Join(";", g.SourceSizes.Select(kv => $"{kv.Key}={kv.Value}")));
        Expect("slices", g.Slices.Count == 5 && g.Slices.All(s => s.GetWidth() == LayerCut.SlicePx && s.GetHeight() == LayerCut.SlicePx
                                                                  && s.GetFormat() == Image.Format.Rgba8 && s.HasMipmaps()),
               string.Join(";", g.Slices.Select(s => $"{s.GetWidth()}x{s.GetHeight()} {s.GetFormat()} mip={s.HasMipmaps()}")));
        var colours = r.GetProperty("colours");
        foreach (var p in colours.EnumerateObject())
        {
            var (cr, cg, cb) = GroundSurfaces.SliceColourBytes(p.Name);
            var want = p.Value.EnumerateArray().Select(e => e.GetInt32()).ToArray();
            Expect($"colour bytes {p.Name} = three.Color", cr == want[0] && cg == want[1] && cb == want[2], $"({cr},{cg},{cb})");
        }
        Texel("grass slice (0,0)", g.Slices[0], 0, 0, 60, 140, 50);
        Texel("grass slice (511,511)", g.Slices[0], 511, 511, 60, 140, 50);
        Texel("lake slice wears the bed (grass)", g.Slices[3], 200, 300, 60, 140, 50);
        Texel("path colour slice (hand 90,65,30)", g.Slices[2], 17, 400, 90, 65, 30);
        Texel("meadow colour slice (hand 50,82,20)", g.Slices[4], 511, 0, 50, 82, 20);

        // ---- shader + material ----
        var mat = g.Material;
        Expect("material shader", mat.Shader == GroundShader.Get(), "");
        // Godot's dummy renderer runs the shader-language front end too (material_storage.cpp shader_set_code):
        // a shader that does not parse reports NO uniforms. 40 = the hand count of the declarations (15 layer cut +
        // natural ground, 14 of the CDLOD stage, roughness/metallic, the basement hole's hole_rect / hole_on, the
        // exploration veil's 7 fv_* — Task 26).
        int uniforms = mat.Shader.GetShaderUniformList().Count;
        Expect("ground shader compiles (front end) with its 40 uniforms", uniforms == 40, $"{uniforms}");
        Expect("ground material bound to the veil", VeilUniforms.Materials().Contains(mat)
                                                   && mat.GetShaderParameter("fv_cells_a").As<Texture2D>() is not null, "");
        Expect("ground hole off at the build", (float)mat.GetShaderParameter("hole_on") == 0f, "");
        Param(mat, "lc_near", new Vector4(64, 96, 1, 128));
        Param(mat, "lc_near_sd_geom", new Vector4(64, 96, 0.5f, 256));
        Param(mat, "lc_sd_code", new Vector2(128, 15.875f));
        Param(mat, "lc_band_m", 8f);
        Param(mat, "lc_far", new Vector4(32, 64, 8, 0));
        Param(mat, "lc_far_size", new Vector2(24, 24));
        Param(mat, "ng_strength", 1f);
        Param(mat, "ng_field", new Vector4(-256, -256, 256, 0));
        Param(mat, "ng_field_size", new Vector2(3, 3));
        // The CDLOD half, bound by the terrain node: geometry w = the pyramid's level count (6 near, 2 far).
        Param(mat, "tl_normal_span", 2f);
        Param(mat, "tl_base_step", 2f);
        Param(mat, "tl_near_geom", new Vector4(-512, -512, 2, 6));
        Param(mat, "tl_near_rect", new Vector4(-512, -512, 768, 768));
        Param(mat, "tl_far_geom", new Vector4(-256, -256, 256, 2));
        Expect("tl_near_levels[0] = (641, 641, 2, 0)", mat.GetShaderParameter("tl_near_levels").AsVector4Array()[0] == new Vector4(641, 641, 2, 0), "");
        Expect("tl_far_levels[0] = (3, 3, 256, 0)", mat.GetShaderParameter("tl_far_levels").AsVector4Array()[0] == new Vector4(3, 3, 256, 0), "");
        var arr = mat.GetShaderParameter("lc_surf").As<Texture2DArray>();
        Expect("surface array bound", arr is not null, "lc_surf unset");
        Expect("layer array bound", mat.GetShaderParameter("lc_layer").AsVector4Array().Length == LayerCut.MaxLayers, "");
        foreach (var name in new[] { "lc_near_id", "lc_near_sd", "lc_far_id", "ng_height", "tl_near", "tl_far" })
            Expect($"{name} bound", mat.GetShaderParameter(name).As<Texture2D>() is not null, "unset");
        var terrainMeshes = world.GetNode("Terrain").GetChildren().OfType<GeometryInstance3D>().ToList();
        Expect("material on both terrain programs (no water: the wet one wears the dry material)",
               terrainMeshes.Count == 2 && terrainMeshes.All(m => m.MaterialOverride == mat), $"{terrainMeshes.Count}");
        Expect("shader literals survive two decimals", GroundShader.Code().Contains("0.23") && GroundShader.Code().Contains("25.00"), "");

        // ---- shading normal on the terrain's level-0 lattices (hand: README) ----
        var (nearLat, farLat) = builder.Terrain!.Field.NormalLattices();
        var rect = builder.Terrain.Field.NearRect;
        Expect("near heights (hand)", nearLat is { OriginX: -512, OriginZ: -512, Step: 2, Cols: 641, Rows: 641 }
                                      && rect!.SequenceEqual(new double[] { -512, -512, 768, 768 }), "");
        NearN("normal at the anchor (fine tile)", TerrainNormal.NormalAt(nearLat, rect, farLat, 2, 64, 128), -0.125, 4, -0.0625);
        NearN("normal in the margin (overview through the near window)",
              TerrainNormal.NormalAt(nearLat, rect, farLat, 2, -200, -100), -0.0380859375, 4, -0.013671875);
        NearN("normal beyond the window (far lattice, clamped)",
              TerrainNormal.NormalAt(nearLat, rect, farLat, 2, 800, 0), 0, 4, -0.125);

        // ---- fallbacks ----
        var fallback = await CheckFallbacks(source, builder.Height!, dir);

        return $"ground layers={g.Layers.Count} slices={g.Slices.Count} textures={g.Stats.TexturesLoaded} "
               + $"texture_failures={g.Stats.TextureFailures} colour_slices={g.Stats.ColourSlices} mask_tiles={g.Tiles.Count} "
               + $"window={w.IdSize}/{w.SdSize} far={far.Cols}x{far.Rows} probes={probes} shader_uniforms={uniforms} | {fallback}";
    }

    private static async Task<string> CheckFallbacks(FixtureSource fixtures, WorldHeight height, string dir)
    {
        var anchor = new AnchorInfo(64, 7.5, 128, "loc-house", Anchor.OverviewSource);
        var logs = new List<string>();
        void Log(string l) { logs.Add(l); GD.Print("[check] " + l); }

        // 1. /play/terrain-layers answers 503 → the plain material stays, the reason is logged.
        var terrain = new Node3D { Name = "FallbackTerrain" };
        var mesh = new MeshInstance3D { Name = "Plain" };
        terrain.AddChild(mesh);
        var failing = new FailingLayers(fixtures, failLayers: true, failLibrary: false);
        var (st1, g1) = await WorldBuilder.DressGroundAsync(failing, terrain, height, anchor, Log, plain: false);
        Expect("fallback: plain when the layers fail", st1.Mode == "plain" && g1 is null && mesh.MaterialOverride is null
                                                       && (st1.Reason ?? "").Contains("503"), st1.Summary());
        Expect("fallback: logged", logs.Any(l => l.StartsWith("ground surfaces failed, keeping the plain material", StringComparison.Ordinal)),
               string.Join(" | ", logs));

        // 2. The library fails → still the layer material, every slice its catalog colour, every tile 3 m.
        var noLib = new FailingLayers(fixtures, failLayers: false, failLibrary: true);
        var (st2, g2) = await WorldBuilder.DressGroundAsync(noLib, terrain, height, anchor, Log, plain: false);
        var wantColour = new[] { "colour:#6f9a4a", "colour:#3f6e3a", "colour:#a08a60", "colour:#6f9a4a", "colour:#7a9a50" };
        Expect("fallback: no library = colour slices", st2.Mode == "layers" && g2 is not null && g2.SliceSources.SequenceEqual(wantColour)
                                                       && g2.LayerParams.Take(5).All(p => p.Y == 3) && st2.TexturesLoaded == 0
                                                       && mesh.MaterialOverride == g2.Material,
               g2 is null ? st2.Summary() : string.Join(";", g2.SliceSources));
        Expect("fallback: library failure logged", logs.Any(l => l.StartsWith("ground: surface library unavailable", StringComparison.Ordinal)), "");

        // 3. --plain-ground: nothing is asked for.
        int before = fixtures.LayerRequests.Count;
        var (st3, g3) = await WorldBuilder.DressGroundAsync(fixtures, terrain, height, anchor, Log, plain: true);
        Expect("--plain-ground", st3.Mode == "plain" && g3 is null && fixtures.LayerRequests.Count == before, st3.Summary());
        terrain.Free();
        return "fallbacks=3";
    }

    /// <summary>The fixture source with <c>/play/terrain-layers</c> and/or the library answering 503.</summary>
    private sealed class FailingLayers : IWorldSource
    {
        private readonly FixtureSource _f;
        private readonly bool _layers, _library;
        public FailingLayers(FixtureSource f, bool failLayers, bool failLibrary) { _f = f; _layers = failLayers; _library = failLibrary; }
        public Task<JsonDocument> GetWorldMapAsync() => _f.GetWorldMapAsync();
        public Task<JsonDocument> GetHeightfieldAsync() => _f.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys) => _f.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync() => _f.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string id) => _f.GetLocationSceneAsync(id);
        public Task<byte[]> GetBytesAsync(string url) => _f.GetBytesAsync(url);
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => _f.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync() => _f.GetAnimationClipsAsync();
        public Task<JsonDocument> GetTerrainAsync() => _f.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys)
            => _layers ? throw new ApiException(503, "/play/terrain-layers", "fixture outage") : _f.GetTerrainLayersAsync(keys);
        public Task<JsonDocument> GetSurfaceTexturesAsync()
            => _library ? throw new ApiException(503, "/assets/surface-textures", "fixture outage") : _f.GetSurfaceTexturesAsync();
    }

    private static string Sha(byte[] b) => Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(b)).ToLowerInvariant();

    private static void Texel(string what, Image img, int x, int y, int r, int g, int b)
    {
        var c = img.GetPixel(x, y);
        Expect(what, c.R8 == r && c.G8 == g && c.B8 == b && c.A8 == 255, $"({c.R8},{c.G8},{c.B8},{c.A8})");
    }

    private static void Param(ShaderMaterial m, string name, Variant want)
    {
        var got = m.GetShaderParameter(name);
        Expect($"shader parameter {name}", got.VariantType == want.VariantType && got.Equals(want), $"{got} vs {want}");
    }

    private static void NearN(string what, (double X, double Y, double Z) got, double x, double y, double z)
    {
        double len = Math.Sqrt(x * x + y * y + z * z);
        Expect(what, Math.Abs(got.X - x / len) < 1e-6 && Math.Abs(got.Y - y / len) < 1e-6 && Math.Abs(got.Z - z / len) < 1e-6,
               $"{got} vs ({x / len}, {y / len}, {z / len})");
    }

    private static void Near(string what, double got, double want, double eps = Tol)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got:R}, expected {want:R}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
