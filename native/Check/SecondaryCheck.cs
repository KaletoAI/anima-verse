using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check secondary</c> (part of every <c>--check</c>, Task 33): the secondary motion and the extension bones like
/// the browser (packages/scene-render/src/secondaryMotion.ts + skinnedNormals.ts, figures.ts <c>Figure.update</c>) on
/// the skinned fixture <c>fixtures/secondary/chain.glb</c> (README "Secondary motion", written by
/// <c>tools/chain_glb.py</c>), imported by Godot like every model, driven through a real <see cref="Figure"/> and its
/// <see cref="SecondaryMotionModifier"/> (stepped by the check: <see cref="Figure.SecondaryManual"/>). Every expected
/// number is derived in the README:
///
///   M1 the glTF extras: Godot 4.7 imports a joint's extras as the bone meta <c>extras</c>; B's anchor_blend reads
///      {Spine1 .5, Spine2 .5, Missing .3};
///   M2 the extents of vector [C3] (girth 2, length 1.5) after 400 steps of 1/120 s: c1 world diag(2, 1.5, 2), c2 at
///      (0, −1.5, 0), the skinned rings half width 0.2 at distances 0.75 / 2.25; 2 binds pushed exactly; the bones'
///      nearest TRS scale (2, 1.5, 2); one surface wears the correcting material, its shader parses (uniform
///      <c>skin_linear</c>), c1's packed matrix is diag(2, 1.5, 2) and corrects the 45° normal by 16.26°;
///   M3 a step of the root: the figure moves 0.1 m along +x in one 1/30 s frame — the one-link particle trails like
///      vector [S3] (p = 0.034222 m of 0.1), lever 0.5 m: c1 tilts atan(0.065778 / 0.5) = 7.4946°;
///   M4 a 3 m jump in one frame resets (tilt 0); the next 0.1 m step trails 7.4946° again;
///   M5 a frozen world carries the particle: another 0.1 m step and a 1 s frozen gap keep 7.4946°;
///   M6 the low tier (far): reset and gain 0 — tilt 0 while stepping on;
///   M7 the anchor blend (scripts/smoke_extension_rig_anchor_blend.mjs): B at bind (0, 1, 1); Spine2 turned 20° about
///      X puts B's head at (0, (2 − sin 20°)/2, (1 + cos 20°)/2) = (0, 0.828990, 0.969846);
///   M9 the engine itself steps the modifier (not manual) once the figure is in the tree;
///   M8 (information) the demo figure, when the repository's demo world is next to the fixtures: its extension
///      joints, the chains built, and the stock normal error its scale reaches over a walk and a stop.
/// </summary>
public static class SecondaryCheck
{
    private const double Tol = 1e-4;
    private const double DegTol = 2e-3;
    private const string Plain = "\"gravity\":0,\"gravity_scale\":1,\"translate\":0,\"flatten\":0,\"sag_max_deg\":180,\"spill\":0,"
                                 + "\"max_deg\":180,\"rest_deg\":0,\"rest_max_deg\":90";

    private static MotionPayload Payload(string rev, string group)
        => MotionPayload.Parse(JsonDocument.Parse($"{{\"rev\":\"{rev}\",\"groups\":{{\"g\":{{{group}}}}}}}").RootElement)!;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var glb = File.ReadAllBytes(Path.Combine(fixtures, "secondary", "chain.glb"));
        var world = new Node3D { Name = "SecondaryWorld" };
        host.AddChild(world);
        try
        {
            // ---- M1 extras ----
            var (probeRoot, _) = GlbLoader.Import(GlbLoader.Prepare(glb), "chain.glb");
            var probeSkel = ClipLibrary.Find<Skeleton3D>(probeRoot) ?? throw new InvalidOperationException("secondary: no skeleton");
            var blend = SecondaryMotionModifier.AnchorBlendOf(probeSkel, probeSkel.FindBone("B"))
                        ?? throw new InvalidOperationException("secondary: M1 B has no anchor_blend extras");
            Expect("M1 anchor_blend entries", blend.Count == 3, string.Join(",", blend.Keys));
            NearD("M1 share Spine1", blend["mixamorig:Spine1"], .5, 1e-9);
            NearD("M1 share Spine2", blend["mixamorig:Spine2"], .5, 1e-9);
            probeRoot.Free();

            // ---- M2 extents ([C3]) ----
            var c3 = Payload("c3", $"\"bones\":[\"c1\",\"c2\"],\"freq_hz\":2,\"zeta\":1,{Plain},\"gain\":0,\"squash\":[0.5,2],\"stretch\":0,\"length\":1.5,\"girth\":2");
            var (fig, mod, skel) = Make(world, glb, "Chain", c3);
            for (int i = 0; i < 400; i++) Step(fig, mod, 1.0 / 120);
            int c1 = skel.FindBone("c1"), c2 = skel.FindBone("c2");
            var w1 = mod.Rig.World[c1];
            NearD("M2 c1 world x scale", w1.Xx, 2, Tol);
            NearD("M2 c1 world y scale", w1.Yy, 1.5, Tol);
            NearD("M2 c1 world z scale", w1.Zz, 2, Tol);
            NearV("M2 c2 head", mod.Rig.World[c2].Position(), 0, -1.5, 0, Tol);
            var (mesh, skin) = mod.LastSkins.Single();
            var probe = BridgeFit.SkinsOf(fig.Body!, skel).Single();
            V3 Vertex(int v)
            {
                var raw = new V3(probe.Rest[v * 3], probe.Rest[v * 3 + 1], probe.Rest[v * 3 + 2]);
                return skin[probe.Bones[v * probe.Slots]].Apply(raw);
            }
            NearD("M2 c1 ring half width", Vertex(0).DistanceTo(Vertex(1)) / 2, 0.2, Tol);
            NearD("M2 c1 ring distance", ((Vertex(0) + Vertex(1)) * .5).Length(), 0.75, Tol);
            NearD("M2 c2 ring half width", Vertex(4).DistanceTo(Vertex(5)) / 2, 0.2, Tol);
            NearD("M2 c2 ring distance", ((Vertex(4) + Vertex(5)) * .5).Length(), 2.25, Tol);
            Expect("M2 exactly the binds of c1 and c2 are pushed", mod.PushedBinds == 2, $"{mod.PushedBinds}");
            var poseScale = skel.GetBonePoseScale(c1);
            NearV("M2 c1 nearest TRS scale", new V3(poseScale.X, poseScale.Y, poseScale.Z), 2, 1.5, 2, Tol);
            Expect("M2 one surface wears the correcting material", mod.CorrectedSurfaces == 1, $"{mod.CorrectedSurfaces}; skipped {string.Join("; ", mod.Skipped)}");
            var material = mod.Materials.Single();
            var uniforms = material.Shader.GetShaderUniformList().Select(u => u.AsGodotDictionary()["name"].AsString()).ToList();
            Expect("M2 the correcting shader parses", uniforms.Contains(SkinNormalMaterial.SkinParam), string.Join(",", uniforms));
            var packed = material.GetShaderParameter(SkinNormalMaterial.SkinParam).AsFloat32Array();
            int bind = Array.IndexOf(probe.BindNodes, c1);
            NearD("M2 packed c1 column x", packed[bind * 9 + 0], 2, Tol);
            NearD("M2 packed c1 column y", packed[bind * 9 + 4], 1.5, Tol);
            NearD("M2 packed c1 column z", packed[bind * 9 + 8], 2, Tol);
            var m = skin[bind];
            var n = new V3(1, 1, 0).Normalized();
            double before = SkinNormals.ErrorDeg(m, n);
            NearD("M2 stock normal error of (1,1,0)/√2 under diag(2,1.5,2), deg", before, 16.2602, DegTol);
            NearD("M2 corrected normal = browser normal", SkinNormals.Correct(m, SkinNormals.Stock(m, n)).DistanceTo(SkinNormals.Browser(m, n)), 0, 1e-9);
            fig.QueueFree();

            // ---- M3–M6 one-link swing ----
            var swing = Payload("swing", $"\"bones\":[\"c1\"],\"freq_hz\":2,\"zeta\":1,{Plain},\"gain\":1,\"squash\":[0.1,3]");
            (fig, mod, skel) = Make(world, glb, "Swing", swing);
            c1 = skel.FindBone("c1");
            double trail = Math.Atan((0.1 - 0.03422162311801544) / 0.5) * 180 / Math.PI;
            Step(fig, mod, 1.0 / 30);
            NearD("M3 at rest", Tilt(mod, c1), 0, DegTol);
            Move(fig, 0.1);
            Step(fig, mod, 1.0 / 30);
            NearD("M3 the step trails like [S3], deg", Tilt(mod, c1), trail, DegTol);
            Move(fig, 3.1);
            Step(fig, mod, 1.0 / 30);
            NearD("M4 a 3 m jump resets", Tilt(mod, c1), 0, DegTol);
            Move(fig, 3.2);
            Step(fig, mod, 1.0 / 30);
            NearD("M4 the next step trails again, deg", Tilt(mod, c1), trail, DegTol);
            fig.SecondaryFrozen = true;
            Move(fig, 3.3);
            Step(fig, mod, 1.0 / 30);
            NearD("M5 frozen: a step keeps the trail, deg", Tilt(mod, c1), trail, DegTol);
            Step(fig, mod, 1.0);
            NearD("M5 frozen: a 1 s gap keeps the trail, deg", Tilt(mod, c1), trail, DegTol);
            fig.SecondaryFrozen = false;
            fig.LoadedTier = FigureTier.Low;
            Move(fig, 3.4);
            Step(fig, mod, 1.0 / 30);
            NearD("M6 far: reset, no swing", Tilt(mod, c1), 0, DegTol);
            Move(fig, 3.5);
            Step(fig, mod, 1.0 / 30);
            NearD("M6 far: still no swing while stepping", Tilt(mod, c1), 0, DegTol);
            fig.QueueFree();

            // ---- M7 anchor blend ----
            var still = Payload("blend", "\"bones\":[\"B\"],\"freq_hz\":2,\"zeta\":0.3,\"gravity\":0,\"gravity_scale\":1,\"gain\":0,"
                + "\"max_deg\":0,\"sag_max_deg\":0,\"spill_max_deg\":0,\"head_sag\":1,\"axis_gain\":[1,1,1],\"flatten\":0,\"stretch\":0,"
                + "\"spread\":0,\"flatten_floor\":1,\"spill\":0,\"translate\":0,\"squash\":[1,1],\"length\":1,\"girth\":1,\"rest_deg\":0,"
                + "\"rest_max_deg\":90,\"straighten_deg\":0");
            (fig, mod, skel) = Make(world, glb, "Blend", still);
            int b = skel.FindBone("B"), s2 = skel.FindBone("mixamorig_Spine2");
            Step(fig, mod, 1.0 / 60);
            NearV("M7 B at bind", mod.Rig.World[b].Position(), 0, 1, 1, Tol);
            skel.SetBonePoseRotation(s2, new Quaternion(Vector3.Right, Mathf.DegToRad(20)));
            Step(fig, mod, 1.0 / 60);
            double s20 = Math.Sin(20 * Math.PI / 180), c20 = Math.Cos(20 * Math.PI / 180);
            NearV("M7 B's head at the share-weighted blend", mod.Rig.World[b].Position(), 0, (2 - s20) / 2, (1 + c20) / 2, Tol);
            fig.QueueFree();

            // ---- M9 the engine steps the modifier (after the mixer, in the skeleton's update) ----
            (fig, mod, skel) = Make(world, glb, "Live", swing);
            fig.SecondaryManual = false;
            fig.UpdateFigure(0);
            for (int i = 0; i < 3; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            int liveSteps = mod.Steps;
            Expect("M9 the engine stepped the modifier", liveSteps >= 2, $"{liveSteps} steps");
            fig.QueueFree();

            var demo = DemoFigure(world, fixtures);
            var report = $"secondary M1..M9 ok (C3 extents 2/1.5, rings 0.2 @ 0.75/2.25, normal fix {before:0.00}°; step trail {trail:0.0000}°, "
                         + $"jump reset, frozen kept, far still; anchor blend ok; engine-stepped {liveSteps}×){demo}";
            GD.Print($"[check-secondary] {report}");
            return report;
        }
        finally
        {
            world.QueueFree();
        }
    }

    /// <summary>A figure at the origin facing yaw 0 with a fresh import of the fixture as its body and the payload's motion.</summary>
    private static (Figure, SecondaryMotionModifier, Skeleton3D) Make(Node3D world, byte[] glb, string name, MotionPayload payload)
    {
        var (root, _) = GlbLoader.Import(GlbLoader.Prepare(glb), name);
        var skel = ClipLibrary.Find<Skeleton3D>(root)!;
        var fig = new Figure(name) { SecondaryManual = true, Motion = payload };
        world.AddChild(fig);
        fig.SetYaw(0);
        var body = new Node3D { Name = "Body" };
        body.AddChild(root);
        fig.SetBody(body, true, skel, null);
        var mod = fig.Secondary ?? throw new InvalidOperationException($"secondary: {name} built no motion");
        return (fig, mod, skel);
    }

    /// <summary>One frame: the figure's update (jump watch, frozen/far, payload), then the modifier's step.</summary>
    private static void Step(Figure fig, SecondaryMotionModifier mod, double dt)
    {
        fig.UpdateFigure(dt);
        mod.StepNow(dt);
    }

    private static void Move(Figure fig, double x) => fig.Position = new Vector3((float)x, 0, 0);

    /// <summary>The tilt of c1's lever (its −Y axis) towards −x, degrees.</summary>
    private static double Tilt(SecondaryMotionModifier mod, int bone)
    {
        var down = mod.Rig.World[bone].ApplyLinear(new V3(0, -1, 0));
        return Math.Atan2(-down.X, -down.Y) * 180 / Math.PI;
    }

    private static readonly HashSet<string> MixamoKeys = new(
        new[] { "hips", "spine", "spine1", "spine2", "neck", "head", "headtop_end", "lefteye", "righteye" }
        .Concat(new[] { "left", "right" }.SelectMany(side =>
            new[] { "shoulder", "arm", "forearm", "hand", "upleg", "leg", "foot", "toebase", "toe_end" }.Select(p => side + p)
            .Concat(new[] { "thumb", "index", "middle", "ring", "pinky" }.SelectMany(f => Enumerable.Range(1, 4).Select(k => $"{side}hand{f}{k}"))))));

    /// <summary>
    /// M8: the tracked demo figure with an extension group (52 Mixamo joints + its own), when the demo world is there:
    /// one group over every non-Mixamo joint with the group parameters of the shipped declaration, a walk of 1 s at
    /// 1.4 m/s and a stop of 1 s at 60 fps; the largest stock-normal error its extension binds reach.
    /// </summary>
    private static string DemoFigure(Node3D world, string fixtures)
    {
        var dir = Path.GetFullPath(Path.Combine(fixtures, "..", "..", "worlds", "demo", "characters"));
        if (!Directory.Exists(dir)) return "; demo figure: not found (skipped)";
        foreach (var file in Directory.GetFiles(dir, "*.glb", SearchOption.AllDirectories).Where(f => !f.Contains("/low/") && !f.Contains("/raw/")
                     && !f.Contains("/prerig/") && !f.Contains("/unrigged/") && !f.Contains("/facefix/")).OrderBy(f => f, StringComparer.Ordinal))
        {
            var (root, _) = GlbLoader.Import(GlbLoader.Prepare(File.ReadAllBytes(file)), Path.GetFileName(file));
            var skel = ClipLibrary.Find<Skeleton3D>(root);
            var extension = skel is null ? new List<string>()
                : Enumerable.Range(0, skel.GetBoneCount()).Select(skel.GetBoneName).Where(n => !MixamoKeys.Contains(BoneNames.Norm(n))).ToList();
            if (skel is null || extension.Count == 0)
            {
                root.Free();
                continue;
            }
            var bones = string.Join(",", extension.Select(e => $"\"{e}\""));
            var payload = Payload("demo", $"\"bones\":[{bones}],\"freq_hz\":2.2,\"zeta\":0.15,\"gravity\":0.35,\"gravity_scale\":1,\"spill\":0.5,"
                + "\"flatten\":0.6,\"axis_gain\":[0.5,1,0.15],\"translate\":0.6,\"head_sag\":0.4,\"spill_max_deg\":30,\"gain\":1,\"max_deg\":30,"
                + "\"squash\":[0.7,1.45],\"stretch\":0.7,\"flatten_floor\":0.5,\"sag_max_deg\":30,\"rest_deg\":0,\"rest_max_deg\":30");
            var fig = new Figure("Demo") { SecondaryManual = true, Motion = payload };
            world.AddChild(fig);
            fig.SetYaw(0);
            var body = new Node3D { Name = "Body" };
            body.AddChild(root);
            fig.SetBody(body, true, skel, null);
            if (fig.Secondary is not { } mod)
            {
                fig.QueueFree();
                return $"; demo figure {skel.GetBoneCount()} joints, extension {extension.Count}: NO motion built";
            }
            var nodes = extension.Select(skel.FindBone).ToHashSet();
            double worst = 0, worstRatio = 1;
            for (int i = 0; i < 120; i++)
            {
                if (i < 60) Move(fig, 1.4 * (i + 1) / 60);
                Step(fig, mod, 1.0 / 60);
                foreach (var (mi, skin) in mod.LastSkins)
                {
                    var probe = BridgeFit.SkinsOf(body, skel).First(p => p.Owner == mi);
                    for (int j = 0; j < skin.Length; j++)
                    {
                        if (!nodes.Contains(probe.BindNodes[j])) continue;
                        var (lo, hi) = SkinNormals.SingularRange(skin[j]);
                        if (lo <= 0) continue;
                        worstRatio = Math.Max(worstRatio, hi / lo);
                        worst = Math.Max(worst, SkinNormals.MaxErrorDeg(skin[j]));
                    }
                }
            }
            string line = $"; demo figure {Path.GetFileName(file)}: {skel.GetBoneCount()} joints, {extension.Count} extension, "
                          + $"{mod.Motion.ParticleCount} particles, {mod.CorrectedSurfaces} corrected surfaces, walk+stop σmax/σmin {worstRatio:0.000} "
                          + $"→ stock normal error ≤ {worst:0.00}°";
            fig.QueueFree();
            return line;
        }
        return "; demo figure: no extension joints found";
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"secondary: {what} FAILED ({detail})");
    }

    private static void NearD(string what, double got, double want, double tol)
    {
        Expect(what, double.IsFinite(got) && Math.Abs(got - want) <= tol, $"got {got:0.######}, want {want:0.######} ± {tol}");
        GD.Print($"[check-secondary] {what}: {got:0.######}");
    }

    private static void NearV(string what, V3 got, double x, double y, double z, double tol)
        => Expect(what, Math.Abs(got.X - x) <= tol && Math.Abs(got.Y - y) <= tol && Math.Abs(got.Z - z) <= tol,
                  $"got ({got.X:0.######}, {got.Y:0.######}, {got.Z:0.######}), want ({x:0.######}, {y:0.######}, {z:0.######}) ± {tol}");
}
