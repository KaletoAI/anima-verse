using System;
using System.IO;
using System.Linq;
using AnimaNative.Gltf;
using AnimaNative.Scene;
using AnimaNative.Sky;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check fog</c> (part of every <c>--check</c>, Task 22): the distance fog on the REAL nodes (the stage and the pass
/// Main builds) against numbers derived by hand in native/fixtures/README.md "Fog":
///
///   F0 one fog path for every material class: the Environment fog is off, and none of ground, water, scatter, recipe,
///      cut port (StandardShaderCode) or an imported GLB material fogs itself (no FOG write, no next pass) — all of them
///      reach the screen through the one pass;
///   F1 the pass: compiled, priority 127 (after every transparent surface), a 2 × 2 quad under the camera that is never
///      culled and casts no shadow, the browser band 220/520 m printed on the view depth;
///   F2 the fog factor through the pass's own path (depth buffer of the overview camera → view depth → smoothstep) at
///      0.2, 220, 295, 370, 445, 520, 799 m;
///   F3 the colour: three's display-space mix (a wall pixel at 370 m under the noon and the night sky);
///   F4 the colour follows the clock's sky (boot, 07:00 dusk, 22:00 night), and not the room ambience.
/// </summary>
public static class FogCheck
{
    public static string Run(Node3D host, string fixtures)
    {
        var root = new Node3D { Name = "FogStage" };
        host.AddChild(root);
        try
        {
            var stage = StageAmbience.Build(root);
            var camera = new Camera3D { Name = "FogCamera" };
            root.AddChild(camera);
            var fog = DistanceFog.Attach(camera);
            stage.Fog = fog;

            // ---- F0 one path ----
            Expect("F0 Godot's Environment fog stays off", !stage.Env.FogEnabled && !stage.Env.VolumetricFogEnabled, "");
            var codes = new (string Class, string Code)[]
            {
                ("ground", Ground.GroundShader.Code()),
                ("water", Ground.GroundShader.Code(true)),
                ("scatter", Scatter.ScatterShaders.Code(0.2, true, false, true, false)),
                ("recipe", RecipeMaterials.Code(false, false)),
                ("recipe translucent", RecipeMaterials.Code(true, true)),
                ("cut port", StandardShaderCode.Generate(new StandardShaderSpec())!),
            };
            foreach (var (cls, code) in codes)
                Expect($"F0 {cls} does not fog itself", !code.Contains("FOG") && !code.Contains("fog_disabled"), "");
            var doc = new GltfDocument();
            var state = new GltfState();
            Expect("F0 GLB parse", doc.AppendFromBuffer(File.ReadAllBytes(Path.Combine(fixtures, "building_original.glb")), "", state) == Error.Ok, "");
            GlbLoader.BrowserLook(state);
            var mats = state.GetMaterials().OfType<BaseMaterial3D>().ToArray();
            Expect("F0 GLB materials carry no fog pass of their own", mats.Length > 0 && mats.All(m => m.NextPass is null), $"{mats.Length}");

            // ---- F1 the pass ----
            Expect("F1 compiled", fog.PassMaterial is not null && fog.Visible
                   && ShaderSafety.Lines.Any(l => l.StartsWith("shader fog-post: compiled")), string.Join(" / ", ShaderSafety.Lines.Where(l => l.Contains("fog"))));
            var pm = fog.PassMaterial!;
            Expect("F1 drawn last", pm.RenderPriority == 127 && pm.RenderPriority == (int)Material.RenderPriorityMax, $"{pm.RenderPriority}");
            Expect("F1 the quad", fog.MaterialOverride == pm && fog.Mesh is QuadMesh q && q.Size == new Vector2(2, 2)
                   && fog.GetParent() == camera && fog.ExtraCullMargin == 16384f
                   && fog.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off, "");
            Expect("F1 the band on the view depth", pm.Shader.Code.Contains("smoothstep(220.0, 520.0, -v.z / v.w)")
                   && pm.Shader.Code.Contains("render_mode unshaded, blend_mix, depth_draw_never, depth_test_disabled"), "");

            // ---- F2 the factor (README "Fog": d = n(f − z)/((f − n)z), z back = nf/(d(f − n) + n), t = (z − 220)/300) ----
            var overview = new OverviewCamera();
            bool lens = Math.Abs(overview.Near - FogPost.CameraNear) < 1e-6 && Math.Abs(overview.Far - FogPost.CameraFar) < 1e-4
                        && Math.Abs(overview.Fov - 45) < 1e-6;
            overview.Free();
            Expect("F2 the twin's lens is the overview camera's (45°, 0.2, 800)", lens, "");
            Near("F2 depth buffer at 370 m", FogPost.DepthAt(370), 2.906131938e-4, 1e-12);
            var grey = (0.5, 0.5, 0.5);
            var sky = (0.6, 0.7, 0.8);
            foreach (var (z, want) in new[] { (0.2, 0.0), (220, 0), (295, 0.15625), (370, 0.5), (445, 0.84375), (520, 1), (799, 1) })
            {
                double got = FogPost.Fragment(grey, FogPost.DepthAt(z), sky)?.Alpha ?? 0;
                Near($"F2 fog at {z} m", got, want, 1e-9);
            }
            Expect("F2 the background stays", FogPost.Fragment(grey, 0, sky) is null, "");

            // ---- F3 the colour: wall bytes (60, 62, 58) at 370 m, f = 0.5 ----
            static double L(int b) => GodotSrgb.ToLinear(b / 255.0);
            var wall = (L(60), L(62), L(58));
            stage.SetHour(12);
            Bytes("F3 noon (60+159, 62+199, 58+232)/2", FogPost.Shown(wall, FogPost.DepthAt(370), fog.FogSrgb), 109.5, 130.5, 145.0);
            stage.SetHour(22);
            Bytes("F3 night (60+26, 62+35, 58+64)/2", FogPost.Shown(wall, FogPost.DepthAt(370), fog.FogSrgb), 43, 48.5, 61);

            // ---- F4 the colour follows the sky ----
            var boot = StageAmbience.Build(root);
            var bootFog = DistanceFog.Attach(camera);
            boot.Fog = bootFog;
            Srgb("F4 boot sky 9fc7e8", bootFog, 159 / 255.0, 199 / 255.0, 232 / 255.0);
            stage.SetHour(7);
            Srgb("F4 07:00 dusk", fog, 0.771432, 0.707033, 0.732679);
            stage.SetHour(22);
            Srgb("F4 22:00 night 1a2340", fog, 26 / 255.0, 35 / 255.0, 64 / 255.0);
            stage.Apply(new AmbienceState(0.5, 1, 0.6, 0.6));
            Srgb("F4 the ambience leaves the fog alone", fog, 26 / 255.0, 35 / 255.0, 64 / 255.0);
            var u = pm.GetShaderParameter("fog_srgb").AsVector3();
            Expect("F4 the uniform carries it", Math.Abs(u.X - 26 / 255.0) < 1e-4 && Math.Abs(u.Z - 64 / 255.0) < 1e-4, $"{u * 255}");

            return "fog F0..F4 ok (one screen pass for every material class, Godot fog off; f at 0.2/220/295/370/445/520/799 m "
                   + "= 0/0/0.15625/0.5/0.84375/1/1 on the view depth; display-space mix: wall @370 m noon (109.5, 130.5, 145) night (43, 48.5, 61); "
                   + "colour = clock sky)";
        }
        finally
        {
            root.QueueFree();
        }
    }

    private static void Srgb(string what, DistanceFog fog, double r, double g, double b)
        => Expect(what, Math.Abs(fog.FogSrgb.R - r) < 1e-4 && Math.Abs(fog.FogSrgb.G - g) < 1e-4 && Math.Abs(fog.FogSrgb.B - b) < 1e-4,
                  $"got {fog.FogSrgb}, expected ({r}, {g}, {b})");

    private static void Bytes(string what, (double R, double G, double B) got, double r, double g, double b)
        => Expect(what, Math.Abs(got.R * 255 - r) < 0.01 && Math.Abs(got.G * 255 - g) < 0.01 && Math.Abs(got.B * 255 - b) < 0.01,
                  $"got ({got.R * 255}, {got.G * 255}, {got.B * 255}), expected ({r}, {g}, {b})");

    private static void Near(string what, double got, double want, double eps)
        => Expect(what, Math.Abs(got - want) < eps, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"fog {what}: {detail}");
    }
}
