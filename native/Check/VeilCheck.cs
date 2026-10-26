using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Ground;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check veil</c> (part of every <c>--check</c>, Task 26): the exploration veil of client3d/src/scene/fogVeil.ts on
/// the REAL ground shaders and the shared uniforms (<see cref="VeilUniforms"/>), against the hand numbers of
/// native/fixtures/README.md "Veil":
///
///   V0 shaders: ground / ground-water / terrain-plain compile with 41 / 51 / 23 uniforms (+7 each; Task 26b +1 / +2 / +1); the text pins the
///      cell size, the zero-alpha branch, the linear + clamped + black-default samplers and the three output mixes;
///   V1 cells: <c>fixtures/explored.json</c> through <see cref="ExploredSync"/> and the fixture source → a 5 × 4 R8
///      texture on all three materials, the geometry, explored texels 6 and 13; an unchanged signature asks nothing;
///   V2 the soft edge: the bilinear twin of the texture at the hand points (1 / 0.5 / 0.25 / 0);
///   V3 the crossfade: 0 → 0.5 → 1 over 0.6 s, A takes B when it lands, a material bound later gets the state at once;
///   V4 the strength and colour: height 32.5 m → 0.36, unfogged → 0, the sky → <c>fv_color</c>, the empty memory →
///      the neutral texel.
/// </summary>
public static class VeilCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        VeilUniforms.Reset();
        try
        {
            return await Run(fixtures);
        }
        finally
        {
            VeilUniforms.Reset();
        }
    }

    private static async Task<string> Run(string fixtures)
    {
        // ---- V0 shaders ----
        var dry = GroundShader.Get();
        var wet = GroundShader.Get(true);
        var plain = GroundShader.Plain();
        foreach (var (s, name) in new[] { (dry, "ground"), (wet, "ground-water"), (plain, "terrain-plain") })
            Expect($"V0 {name} compiles", ShaderSafety.Ok(s, name), string.Join(" | ", ShaderSafety.Lines));
        int nDry = dry.GetShaderUniformList().Count, nWet = wet.GetShaderUniformList().Count, nPlain = plain.GetShaderUniformList().Count;
        Expect("V0 uniforms 41 / 51 / 23 (33 / 42 / 15 + the veil's 7 + av_hemi, + tw_ripple_on wet — Task 26b)",
               nDry == 41 && nWet == 51 && nPlain == 23,
               $"{nDry} / {nWet} / {nPlain}");
        foreach (var (code, name) in new[] { (GroundShader.Code(), "dry"), (GroundShader.Code(true), "wet"), (GroundShader.PlainCode(), "plain") })
        {
            Expect($"V0 {name}: cells sampled linear, clamped, black by default",
                   code.Contains("uniform sampler2D fv_cells_a : hint_default_black, filter_linear, repeat_disable;")
                   && code.Contains("uniform sampler2D fv_cells_b : hint_default_black, filter_linear, repeat_disable;"), "");
            Expect($"V0 {name}: the 64 m cell, texel centres on cell centres", code.Contains("vec2 uv = (p / 64.00 - geom.xy) / geom.zw;"), "");
            Expect($"V0 {name}: alpha 0 reads no texture", code.Contains("if (fv_alpha <= 0.0) return 0.0;"), "");
            Expect($"V0 {name}: the mix of A and B, the haze of the unexplored share",
                   code.Contains("mix(fv_explored_at(fv_cells_a, fv_geom_a, p), fv_explored_at(fv_cells_b, fv_geom_b, p), fv_mix)")
                   && code.Contains("return fv_alpha * (1.0 - clamp(seen, 0.0, 1.0));"), "");
            Expect($"V0 {name}: every veil uniform declared once",
                   GroundShader.VeilUniformNames.All(u => System.Text.RegularExpressions.Regex.Matches(code, $@"\buniform \w+ {u}\b").Count == 1), "");
        }
        // Task 26b: the albedo is named (av_alb) because the hemisphere term multiplies the SAME albedo the lights see.
        Expect("V0 dry: lit · (1 − a) + colour · a", GroundShader.Code().Contains("vec3 av_alb = alb * (1.0 - fv_a);")
                                                    && GroundShader.Code().Contains("ALBEDO = av_alb;")
                                                    && GroundShader.Code().Contains("EMISSION = fv_color * fv_a + av_alb * (1.0 - ground_metallic) * av_hemi"), "");
        Expect("V0 wet: the veil under the sky and the foam",
               GroundShader.Code(true).Contains("vec3 av_alb = alb * (1.0 - k) * (1.0 - f) * (1.0 - fv_a);")
               && GroundShader.Code(true).Contains("EMISSION = (fv_color * fv_a * (1.0 - k) + tw_sky * k) * (1.0 - f) + vec3(f) + av_alb * (1.0 - metal) * av_hemi"), "");
        Expect("V0 plain: the same mix on its colour", GroundShader.PlainCode().Contains("vec3 av_alb = plain_albedo * (1.0 - fv_a);")
                                                      && GroundShader.PlainCode().Contains("float fv_a = fv_amount(v_world);"), "");

        var mats = new[] { new ShaderMaterial { Shader = dry }, new ShaderMaterial { Shader = wet }, new ShaderMaterial { Shader = plain } };
        foreach (var m in mats) VeilUniforms.Bind(m);
        Expect("V0 three bound", VeilUniforms.Materials().Count == 3, $"{VeilUniforms.Materials().Count}");
        foreach (var m in mats)
        {
            Expect("V0 boot: alpha 0, mix 1, the neutral texel on both", F(m, "fv_alpha") == 0 && F(m, "fv_mix") == 1
                   && Tex(m, "fv_cells_a") == VeilUniforms.Neutral && Tex(m, "fv_cells_b") == VeilUniforms.Neutral
                   && G(m, "fv_geom_a") == new Vector4(0, 0, 1, 1), "");
            // 0x9fc7e8 → linear (0.3467, 0.5711, 0.8069): the three sky before the first clock reading.
            var c = (Vector3)m.GetShaderParameter("fv_color");
            Expect("V0 boot colour = the default sky, linear", Math.Abs(c.X - 0.3467) < 5e-4 && Math.Abs(c.Y - 0.5711) < 5e-4
                                                             && Math.Abs(c.Z - 0.8069) < 5e-4, $"{c}");
        }

        // ---- V1 cells through the sync and the fixture source ----
        var source = new FixtureSource(fixtures);
        var sync = new ExploredSync(async () =>
        {
            using var doc = await source.GetExploredAsync();
            return ExploredSync.Parse(doc.RootElement);
        }, VeilUniforms.SetCells, VeilUniforms.SetFogged);
        await sync.SyncAsync(true, "2");
        Expect("V1 one request, the server's signature", source.ExploredRequests == 1 && sync.Sig == "2", $"{source.ExploredRequests} {sync.Sig}");
        await sync.SyncAsync(true, "2");
        Expect("V1 unchanged signature: no request", source.ExploredRequests == 1, $"{source.ExploredRequests}");
        var st = VeilUniforms.State;
        // explored.json: "0,0", "2,1" → grid (−1, −1, 5, 4), texels 6 and 13 (README "Veil").
        Expect("V1 grid", st.GeomB == (-1.0, -1.0, 5.0, 4.0), $"{st.GeomB}");
        var img = st.B.GetImage();
        Expect("V1 texture 5 × 4 R8", img.GetWidth() == 5 && img.GetHeight() == 4 && img.GetFormat() == Image.Format.R8,
               $"{img.GetWidth()}x{img.GetHeight()} {img.GetFormat()}");
        var lit = Enumerable.Range(0, 20).Where(i => img.GetPixel(i % 5, i / 5).R > 0.5f).ToArray();
        Expect("V1 explored texels 6 and 13", lit.SequenceEqual(new[] { 6, 13 }), string.Join(",", lit));
        foreach (var m in mats)
            Expect("V1 every material: B = the new set, A = the neutral texel, mix 0, geometry",
                   Tex(m, "fv_cells_b") == st.B && Tex(m, "fv_cells_a") == VeilUniforms.Neutral && F(m, "fv_mix") == 0
                   && G(m, "fv_geom_b") == new Vector4(-1, -1, 5, 4), "");

        // ---- V2 the soft edge (bilinear twin of the texture, the linear filter) ----
        var cells = FogVeil.Cells(new[] { "0,0", "2,1" });
        Near("V2 centre of explored (0,0) at (32, 32)", ExploredAt(cells, 32, 32), 1);
        Near("V2 the shared boundary x = 64", ExploredAt(cells, 64, 32), 0.5);
        Near("V2 16 m into the unexplored cell (80, 32)", ExploredAt(cells, 80, 32), 0.25);
        Near("V2 32 m in: the haze is whole (96, 32)", ExploredAt(cells, 96, 32), 0);
        Near("V2 far outside the grid (clamped to the zero ring)", ExploredAt(cells, -500, 900), 0);

        // ---- V3 the crossfade ----
        VeilUniforms.Tick(0.3);
        foreach (var m in mats) Near("V3 0.3 s: mix 0.5", F(m, "fv_mix"), 0.5);
        VeilUniforms.Tick(0.3);
        foreach (var m in mats)
            Expect("V3 0.6 s: settled, A takes B", F(m, "fv_mix") == 1 && Tex(m, "fv_cells_a") == st.B && Tex(m, "fv_cells_b") == st.B
                   && G(m, "fv_geom_a") == new Vector4(-1, -1, 5, 4), "");
        var late = new ShaderMaterial { Shader = dry };
        VeilUniforms.Bind(late);
        Expect("V3 a ground bound later gets the state at once", Tex(late, "fv_cells_a") == st.B && F(late, "fv_mix") == 1, "");

        // ---- V4 strength, colour, the empty memory ----
        VeilUniforms.SetCameraHeight(32.5);
        foreach (var m in mats) Near("V4 height 32.5 m → 0.72 · smoothstep(0.5) = 0.36", F(m, "fv_alpha"), 0.36);
        await sync.SyncAsync(false, "2");
        foreach (var m in mats) Near("V4 unfogged (show all) → 0", F(m, "fv_alpha"), 0);
        await sync.SyncAsync(true, "2");
        Near("V4 fogged again", F(mats[0], "fv_alpha"), 0.36);
        VeilUniforms.SetSky(new Vector3(0.1f, 0.2f, 0.3f));
        foreach (var m in mats) Expect("V4 the sky reaches every veil", (Vector3)m.GetShaderParameter("fv_color") == new Vector3(0.1f, 0.2f, 0.3f), "");
        await sync.SyncAsync(true, "");
        VeilUniforms.Tick(1);
        Expect("V4 no avatar: the empty memory, the neutral texel", Tex(mats[1], "fv_cells_b") == VeilUniforms.Neutral
                                                                 && Tex(mats[1], "fv_cells_a") == VeilUniforms.Neutral
                                                                 && source.ExploredRequests == 1, "");
        return $"veil[V0 41/51/23, V1 cells 2 grid 5x4, V2 edge 1/0.5/0.25/0, V3 fade 0.6 s, V4 0.36; {VeilUniforms.Summary()}]";
    }

    /// <summary>
    /// The texture as the GPU's linear filter reads it, clamp to edge: texel coordinate = uv · size − 0.5 (texel centres
    /// on cell centres), bilinear between the four neighbours.
    /// </summary>
    public static double ExploredAt(FogCells cells, double x, double z)
    {
        var (u, v) = cells.Grid is { } g ? FogVeil.TexUv(x, z, g) : (0.5, 0.5);
        double fx = u * cells.Cols - 0.5, fz = v * cells.Rows - 0.5;
        int i0 = (int)Math.Floor(fx), j0 = (int)Math.Floor(fz);
        double tx = fx - i0, tz = fz - j0;
        double T(int i, int j) => cells.Data[Math.Clamp(j, 0, cells.Rows - 1) * cells.Cols + Math.Clamp(i, 0, cells.Cols - 1)] / 255.0;
        return (T(i0, j0) * (1 - tx) + T(i0 + 1, j0) * tx) * (1 - tz) + (T(i0, j0 + 1) * (1 - tx) + T(i0 + 1, j0 + 1) * tx) * tz;
    }

    private static float F(ShaderMaterial m, string name) => (float)m.GetShaderParameter(name);
    private static Vector4 G(ShaderMaterial m, string name) => (Vector4)m.GetShaderParameter(name);
    private static Texture2D? Tex(ShaderMaterial m, string name) => m.GetShaderParameter(name).As<Texture2D>();

    private static void Near(string what, double got, double want)
        => Expect(what, Math.Abs(got - want) < 1e-6, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
