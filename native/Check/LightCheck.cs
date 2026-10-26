using System;
using System.IO;
using System.Linq;
using AnimaNative.Gltf;
using AnimaNative.Scene;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check light</c> (part of every <c>--check</c>, Task 21): the game-hour stage on the REAL nodes
/// (<see cref="StageAmbience.Build"/>, the same call Main makes), read back from Godot, against numbers derived by hand in
/// native/fixtures/README.md "Light":
///
///   L0 the stage before the first clock reading (the browser constructor's lights, ambience ignored) and the fixed
///      settings: no sky reflection, colour ambient, linear tone map, specular 1 on sun and fill, 0 on the hemisphere
///      pair, the lower pair light negative, one orthogonal shadow on the sun only;
///   L1 hours 6, 7, 9, 12, 18 and 22: the sun direction (Godot −Z = from the offset to the snapped target), the sun /
///      background colours as Godot channels, the energies = three intensity / π, the water's sky bytes, the night factor;
///      and — the proof of the conversion — what Godot's renderer computes from them (<c>Color.SrgbToLinear()</c> ×
///      energy × π) equals three's linear colour × intensity;
///   L2 the hemisphere: ambient + the ± pair reproduce three's <c>I · mix(G, S, ½ + ½·n.y) / π</c> at n.y = 1, 0, −1;
///   L3 the room ambience on the clock base (daylight 0.5: energies halved, the water's sky bytes);
///   L4 the shadow fit: max distance from the camera distance, Godot's texel size against the browser's 6.84 cm;
///   L5 the material policy: Lambert + no received shadow on every imported GLB material, the scatter shader likewise,
///      the terrain casts no shadow; the MSAA option;
///   L6 the hemisphere pair as the terrain's shader term (Task 26b, <see cref="HemiUniforms"/>): the term is the pair
///      light as Godot decodes it × its energy (noon = the L2 difference n.y 1 − n.y 0), ambient + term·n.y equals the
///      lit sum of L2 for every n.y, the terrain sits on the layer both pair lights skip (sun, fill, lamps and every
///      default-layer instance keep them), all three ground shaders add the term, and the bench switch zeroes it.
/// </summary>
public static class LightCheck
{
    private const float Eps = 1e-6f;

    public static string Run(Node3D host, string fixtures)
    {
        var root = new Node3D { Name = "LightStage" };
        host.AddChild(root);
        var water = new ShaderMaterial { Shader = new Shader { Code = "shader_type spatial;\nuniform vec3 tw_sky = vec3(0.62, 0.78, 0.91);\n" } };
        // What GroundSurfaces writes at creation (the boot sky, scene-render's surfaceSkyUniform start value).
        water.SetShaderParameter("tw_sky", new Vector3(0.62f, 0.78f, 0.91f));
        try
        {
            var stage = StageAmbience.Build(root, () => water);

            // ---- L0 before the clock + fixed settings ----
            // Constructor: sun 2.0, hemi 1.5, fill 0.5 → /π = 0.636620, 0.477465, 0.159155; sky 9fc7e8 = (159, 199, 232)/255.
            Energy("L0 boot sun", stage.Sun.LightEnergy, 0.636619772);
            Energy("L0 boot hemi", stage.Env.AmbientLightEnergy, 0.477464829);
            Energy("L0 boot fill", stage.Fill.LightEnergy, 0.159154943);
            Col("L0 boot sun colour", stage.Sun.LightColor, 1, 242 / 255.0, 216 / 255.0);
            Col("L0 boot sky", stage.Env.BackgroundColor, 159 / 255.0, 199 / 255.0, 232 / 255.0);
            stage.Apply(new AmbienceState(0.3, 1, 0.5, 0.5));
            Energy("L0 the ambience waits for the clock (applyAmbience without baseLights)", stage.Sun.LightEnergy, 0.636619772);
            Expect("L0 water sky untouched", water.GetShaderParameter("tw_sky").AsVector3() == new Vector3(0.62f, 0.78f, 0.91f), "");
            stage.Apply(AmbienceState.Neutral);
            var env = stage.Env;
            Expect("L0 environment", env.ReflectedLightSource == Godot.Environment.ReflectionSource.Disabled
                   && env.AmbientLightSource == Godot.Environment.AmbientSource.Color
                   && env.BackgroundMode == Godot.Environment.BGMode.Color
                   && env.TonemapMode == Godot.Environment.ToneMapper.Linear && env.TonemapExposure == 1f
                   && !env.GlowEnabled && !env.SsaoEnabled && !env.SsrEnabled, "");
            Expect("L0 specular", stage.Sun.LightSpecular == 1f && stage.Fill.LightSpecular == 1f
                   && stage.HemiUp.LightSpecular == 0f && stage.HemiDown.LightSpecular == 0f, "");
            Expect("L0 hemisphere pair", !stage.HemiUp.LightNegative && stage.HemiDown.LightNegative
                   && Dir(stage.HemiUp).IsEqualApprox(Vector3.Up) && Dir(stage.HemiDown).IsEqualApprox(Vector3.Down), "");
            Expect("L0 shadows", stage.Sun.ShadowEnabled && stage.Sun.DirectionalShadowMode == DirectionalLight3D.ShadowMode.Orthogonal
                   && !stage.Fill.ShadowEnabled && !stage.HemiUp.ShadowEnabled && !stage.HemiDown.ShadowEnabled, "");
            // Fill from (−30, 20, −25) to the origin: |·| = √1925 = 43.8748 → (−0.683763, 0.455842, −0.569803).
            NearV("L0 fill direction", Dir(stage.Fill), new Vector3(-0.683763f, 0.455842f, -0.569803f));

            // ---- L1 the hours ----
            var target = new Vector3(10.03f, 2f, -7.5f);
            Hour(stage, water, target, 6, new Vector3(0.918635f, 0.097988f, 0.382764f), Moon, NightSky, 0.25, 0.35, 0.15, NightSkyBytes, 1);
            Hour(stage, water, target, 7, new Vector3(0.872468f, 0.311703f, 0.376352f), (1, 0.8412030258, 0.6858348060),
                 (0.7714320343, 0.7070326850, 0.7326785259), 0.767638090, 0.660582854, 0.253527618, (197, 180, 187), 0.223542865);
            Hour(stage, water, target, 9, new Vector3(0.565685f, 0.754247f, 0.333333f), Noon, DaySky, 1.664213562, 1.198528137, 0.432842712, DaySkyBytes, 0);
            Hour(stage, water, target, 12, new Vector3(0f, 0.954480f, 0.298275f), Noon, DaySky, 2.25, 1.55, 0.55, DaySkyBytes, 0);
            Hour(stage, water, target, 18, new Vector3(-0.918635f, 0.097988f, 0.382764f), Moon, NightSky, 0.25, 0.35, 0.15, NightSkyBytes, 1);
            Hour(stage, water, target, 22, new Vector3(-0.758108f, 0.161730f, 0.631756f), Moon, NightSky, 0.25, 0.35, 0.15, NightSkyBytes, 1);

            // ---- L2 the hemisphere at noon ----
            stage.SetHour(12);
            HemiAt(stage, 1, 0.364070476, 0.421836530, 0.493380324);
            HemiAt(stage, 0, 0.244732059, 0.290634515, 0.293023698);
            HemiAt(stage, -1, 0.125393643, 0.159432501, 0.092667073);
            // Ambient (S + G)/2 and the pair's (S − G)/2 as Godot channels (README "Light").
            Col("L2 ambient colour", env.AmbientLightColor, 0.7327369660, 0.7912292406, 0.7941208591);
            Col("L2 pair colour", stage.HemiUp.LightColor, 0.5290075734, 0.5525311845, 0.6697333453);

            // ---- L3 ambience on the clock base ----
            stage.Apply(new AmbienceState(0.5, 1, 1, 1));
            Energy("L3 sun × daylight", stage.Sun.LightEnergy, 0.716197244 / 2);
            Energy("L3 hemi × daylight", stage.Env.AmbientLightEnergy, 0.493380324 / 2);
            Energy("L3 fill × daylight", stage.Fill.LightEnergy, 0.175070437 / 2);
            Bytes("L3 water sky = getHex(sky · 0.5)", water, 116, 146, 170);
            Col("L3 the sky background stays", env.BackgroundColor, DaySky.R, DaySky.G, DaySky.B);
            stage.Apply(AmbienceState.Neutral);

            // ---- L4 the shadow fit ----
            stage.Track(target, 80);
            Expect("L4 max distance at 80 m", stage.Sun.DirectionalShadowMaxDistance == 150f, $"{stage.Sun.DirectionalShadowMaxDistance}");
            stage.Track(target, 5);
            Expect("L4 max distance at 5 m", stage.Sun.DirectionalShadowMaxDistance == 80f, $"{stage.Sun.DirectionalShadowMaxDistance}");
            stage.Track(target, 150);
            Expect("L4 max distance at 150 m", stage.Sun.DirectionalShadowMaxDistance == 220f, $"{stage.Sun.DirectionalShadowMaxDistance}");
            double texel80 = ShadowFit.TexelM(150, 45, 16.0 / 9, 0.2);
            Expect("L4 texel at 80 m ≈ the browser's 140/2048", Math.Abs(texel80 - 0.0719155839) < 1e-9, $"{texel80}");
            int atlas = ProjectSettings.GetSetting("rendering/lights_and_shadows/directional_shadow/size").AsInt32();
            Expect("L4 the directional atlas is the 4096 the fit assumes", atlas == ShadowFit.AtlasPx, $"{atlas}");

            // ---- L5 material policy ----
            var doc = new GltfDocument();
            var state = new GltfState();
            Expect("L5 GLB parse", doc.AppendFromBuffer(File.ReadAllBytes(Path.Combine(fixtures, "building_original.glb")), "", state) == Error.Ok, "");
            int touched = GlbLoader.BrowserLook(state);
            var mats = state.GetMaterials().OfType<BaseMaterial3D>().ToArray();
            Expect("L5 GLB materials Lambert, no received shadow", mats.Length > 0 && touched == mats.Length
                   && mats.All(m => m.DiffuseMode == BaseMaterial3D.DiffuseModeEnum.Lambert && m.DisableReceiveShadows), $"{touched}/{mats.Length}");
            var scatter = Scatter.ScatterShaders.Code(0.2, true, false, true, false);
            Expect("L5 scatter Lambert, no received shadow", scatter.Contains("diffuse_lambert") && scatter.Contains("shadows_disabled")
                   && !scatter.Contains("diffuse_burley"), "");
            using (var hf = System.Text.Json.JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "heightfield.json"))))
            {
                var height = new WorldHeight(HeightfieldOverview.Parse(hf.RootElement));
                var terrain = new TerrainLodNode(Terrain.TerrainField.Build(height, 0, 0, null, Terrain.TerrainField.ExtentOf(null)), _ => { });
                Expect("L5 the terrain casts no shadow", terrain.DryInstance.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off
                       && terrain.WetInstance.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off, "");
                terrain.Free();
            }
            Expect("L5 MSAA default 4×, --msaa=0 off", CliOptions.Parse(Array.Empty<string>()).Msaa == Viewport.Msaa.Msaa4X
                   && CliOptions.Parse(new[] { "--msaa=0" }).Msaa == Viewport.Msaa.Disabled
                   && CliOptions.Parse(new[] { "--msaa=2" }).Msaa == Viewport.Msaa.Msaa2X, "");
            Energy("L5 a lamp of intensity 2 → 2/π", (float)StageLight.Energy(2), 0.636619772);

            // ---- L6 the hemisphere term on the terrain (Task 26b) ----
            stage.SetHour(12);
            stage.Apply(AmbienceState.Neutral);
            // Noon, README "Light": the pair = (n.y 1) − (n.y 0) = (0.364070476 − 0.244732059, …).
            var term = HemiUniforms.Value;
            Expect("L6 the term = the pair as Godot decodes it × energy", term == StageAmbience.HemiTermOf(stage.Frame), $"{term}");
            Expect("L6 noon term (0.119338417, 0.131202015, 0.200356626)", Math.Abs(term.X - 0.119338417) < 1e-5
                   && Math.Abs(term.Y - 0.131202015) < 1e-5 && Math.Abs(term.Z - 0.200356626) < 1e-5, $"{term}");
            var amb6 = stage.Env.AmbientLightColor.SrgbToLinear() * stage.Env.AmbientLightEnergy;
            foreach (float ny in new[] { 1f, 0.75f, 0.5f, 0.2f, 0f, -0.5f, -1f })
            {
                // What the lights sum to on a Lambert surface (L2's path) against ambient + the shader term.
                var n = new Vector3(0, ny, 0);
                var lit = amb6 + stage.HemiUp.LightColor.SrgbToLinear() * stage.HemiUp.LightEnergy * Math.Max(0, n.Dot(Dir(stage.HemiUp)))
                          - stage.HemiDown.LightColor.SrgbToLinear() * stage.HemiDown.LightEnergy * Math.Max(0, n.Dot(Dir(stage.HemiDown)));
                var shaded = new Vector3(amb6.R, amb6.G, amb6.B) + term * ny;
                Expect($"L6 ambient + term·n.y = the pair's sum at n.y {ny}", Math.Abs(shaded.X - lit.R) < 1e-6
                       && Math.Abs(shaded.Y - lit.G) < 1e-6 && Math.Abs(shaded.Z - lit.B) < 1e-6, $"{shaded} vs {lit}");
            }
            uint layer = HemiUniforms.Layer;
            Expect("L6 both pair lights skip the terrain layer", (stage.HemiUp.LightCullMask & layer) == 0
                   && (stage.HemiDown.LightCullMask & layer) == 0, $"{stage.HemiUp.LightCullMask:x}");
            Expect("L6 sun and fill still light it", (stage.Sun.LightCullMask & layer) != 0 && (stage.Fill.LightCullMask & layer) != 0, "");
            var probeMesh = new MeshInstance3D();
            bool defaultLayer = probeMesh.Layers == 1u;
            probeMesh.Free();
            Expect("L6 the pair keeps every default-layer instance", (stage.HemiUp.LightCullMask & 1u) != 0
                   && (stage.HemiDown.LightCullMask & 1u) != 0 && defaultLayer, "");
            using (var hf = System.Text.Json.JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "heightfield.json"))))
            {
                var height = new WorldHeight(HeightfieldOverview.Parse(hf.RootElement));
                var terrain = new TerrainLodNode(Terrain.TerrainField.Build(height, 0, 0, null, Terrain.TerrainField.ExtentOf(null)), _ => { });
                Expect("L6 the terrain instances sit on that layer only", terrain.DryInstance.Layers == layer && terrain.WetInstance.Layers == layer, "");
                var plainMat = terrain.Materials.Dry;
                Expect("L6 the plain terrain material carries the term", HemiUniforms.Materials().Contains(plainMat)
                       && plainMat.GetShaderParameter(HemiUniforms.Uniform).AsVector3() == term, "");
                HemiUniforms.Off = true;
                Expect("L6 the bench switch zeroes it", plainMat.GetShaderParameter(HemiUniforms.Uniform).AsVector3() == Vector3.Zero, "");
                HemiUniforms.Off = false;
                Expect("L6 and puts it back", plainMat.GetShaderParameter(HemiUniforms.Uniform).AsVector3() == term, "");
                terrain.Free();
            }
            foreach (var (code, name) in new[] { (Ground.GroundShader.Code(), "ground"), (Ground.GroundShader.Code(true), "ground-water"),
                                                 (Ground.GroundShader.PlainCode(), "terrain-plain") })
                Expect($"L6 {name} adds the term", code.Contains("uniform vec3 av_hemi") && code.Contains("* av_hemi * normalize("), "");

            return $"light L0..L6 ok (hours 6 7 9 12 18 22, noon sun {0.716197:0.######} hemi {0.493380:0.######} fill {0.175070:0.######}, "
                   + $"hemisphere ±pair exact at n.y 1/0/−1, shadow ortho {atlas} px max-dist 80/150/220, texel@80 m {texel80 * 100:0.##} cm, "
                   + $"GLB {mats.Length} materials Lambert/no-receive; terrain hemisphere term {term.X:0.######}/{term.Y:0.######}/{term.Z:0.######} "
                   + "on layer 20, pair lights skip it)";
        }
        finally
        {
            root.QueueFree();
        }
    }

    // Hand colours (README "Light"): an unblended hex reaches Godot as its bytes / 255 (Encode inverts the conversion).
    private static readonly (double R, double G, double B) Noon = (1, 242 / 255.0, 216 / 255.0);
    private static readonly (double R, double G, double B) Moon = (159 / 255.0, 180 / 255.0, 224 / 255.0);
    private static readonly (double R, double G, double B) DaySky = (159 / 255.0, 199 / 255.0, 232 / 255.0);
    private static readonly (double R, double G, double B) NightSky = (26 / 255.0, 35 / 255.0, 64 / 255.0);
    private static readonly (int R, int G, int B) DaySkyBytes = (159, 199, 232), NightSkyBytes = (26, 35, 64);

    private static void Hour(StageAmbience stage, ShaderMaterial water, Vector3 target, double hour, Vector3 dir,
                             (double R, double G, double B) sun, (double R, double G, double B) sky,
                             double sunI, double hemiI, double fillI, (int R, int G, int B) waterBytes, double night)
    {
        string h = $"L1 {hour:00}:00";
        stage.SetHour(hour);
        stage.Apply(AmbienceState.Neutral);
        stage.Track(target, 80);
        NearV($"{h} sun direction", Dir(stage.Sun), dir);
        Col($"{h} sun colour", stage.Sun.LightColor, sun.R, sun.G, sun.B);
        Col($"{h} sky", stage.Env.BackgroundColor, sky.R, sky.G, sky.B);
        Energy($"{h} sun energy = {sunI}/π", stage.Sun.LightEnergy, sunI / Math.PI);
        Energy($"{h} hemi energy = {hemiI}/π", stage.Env.AmbientLightEnergy, hemiI / Math.PI);
        Energy($"{h} fill energy = {fillI}/π", stage.Fill.LightEnergy, fillI / Math.PI);
        Energy($"{h} pair energy = {hemiI}/π", stage.HemiUp.LightEnergy, hemiI / Math.PI);
        Bytes($"{h} water sky", water, waterBytes.R, waterBytes.G, waterBytes.B);
        Expect($"{h} night", Math.Abs(stage.Frame.Night - night) < 1e-9, $"{stage.Frame.Night}");
        // The proof: Godot's renderer gets srgb_to_linear(colour) · energy · π (light_storage.cpp); three lights with its
        // linear colour · intensity. The linear colour comes from the hand Godot channels through three's own decode.
        var lin = stage.Sun.LightColor.SrgbToLinear() * stage.Sun.LightEnergy * Mathf.Pi;
        var want = new LinearRgb(LinearRgb.SrgbToLinear(sun.R), LinearRgb.SrgbToLinear(sun.G), LinearRgb.SrgbToLinear(sun.B));
        Expect($"{h} renderer sun = three colour × intensity", Math.Abs(lin.R - want.R * sunI) < 1e-5 && Math.Abs(lin.G - want.G * sunI) < 1e-5
               && Math.Abs(lin.B - want.B * sunI) < 1e-5, $"{lin} vs {want} × {sunI}");
        // The sun stands at snapShadowCentre(target) + offset (the browser's numbers; Godot lights by direction only).
        var off = StageLight.SunOffset(stage.Frame.SunAngle);
        var c = ShadowSnap.SnapCentre((target.X, target.Y, target.Z), off);
        var p = stage.Sun.Position;
        Expect($"{h} sun position", Math.Abs(p.X - (c.X + off.X)) < 1e-3 && Math.Abs(p.Y - (c.Y + off.Y)) < 1e-3 && Math.Abs(p.Z - (c.Z + off.Z)) < 1e-3
               && new Vector3((float)c.X, (float)c.Y, (float)c.Z).DistanceTo(target) <= ShadowSnap.TexelM() * 0.7072, $"{p}");
    }

    private static void HemiAt(StageAmbience stage, float ny, double r, double g, double b)
    {
        // Godot: ambient·E (no 1/π) + pair·E·π·max(0, n·L)/π for the upper light (L = +y) and minus the same for the
        // negative lower one (L = −y). three: I · mix(G, S, ½ + ½·n.y) / π (hand values).
        var n = new Vector3(0, ny, 0);
        var amb = stage.Env.AmbientLightColor.SrgbToLinear() * stage.Env.AmbientLightEnergy;
        var up = stage.HemiUp.LightColor.SrgbToLinear() * stage.HemiUp.LightEnergy * Math.Max(0, n.Dot(Dir(stage.HemiUp)));
        var down = stage.HemiDown.LightColor.SrgbToLinear() * stage.HemiDown.LightEnergy * Math.Max(0, n.Dot(Dir(stage.HemiDown)));
        var sum = amb + up - down;
        Expect($"L2 hemisphere at n.y {ny}", Math.Abs(sum.R - r) < 1e-5 && Math.Abs(sum.G - g) < 1e-5 && Math.Abs(sum.B - b) < 1e-5,
               $"{sum} vs ({r}, {g}, {b})");
    }

    /// <summary>The direction TOWARDS a directional light (its +Z; it shines along −Z).</summary>
    private static Vector3 Dir(DirectionalLight3D l) => l.GlobalTransform.Basis.Z.Normalized();

    private static void Energy(string what, float got, double want)
        => Expect(what, Math.Abs(got - want) < 1e-6, $"got {got}, expected {want}");

    private static void Col(string what, Color got, double r, double g, double b)
        => Expect(what, Math.Abs(got.R - r) < 1e-5 && Math.Abs(got.G - g) < 1e-5 && Math.Abs(got.B - b) < 1e-5, $"got {got}, expected ({r}, {g}, {b})");

    private static void Bytes(string what, ShaderMaterial water, int r, int g, int b)
    {
        var v = water.GetShaderParameter("tw_sky").AsVector3();
        Expect(what, Math.Abs(v.X - r / 255.0) < Eps && Math.Abs(v.Y - g / 255.0) < Eps && Math.Abs(v.Z - b / 255.0) < Eps,
               $"got {v * 255}, expected ({r}, {g}, {b})");
    }

    private static void NearV(string what, Vector3 got, Vector3 want)
        => Expect(what, got.DistanceTo(want) < 1e-5f, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"light {what}: {detail}");
    }
}
